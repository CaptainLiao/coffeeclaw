# CoffeeClaw — 企业级 Agent 开发平台 PRD

> **项目代号**：CoffeeClaw
> **版本**：v3.1（小团队务实版）
> **更新日期**：2026-03-11
> **文档范围**：Agent 开发平台核心能力（不含上层业务应用）
> **设计取向**：以快速落地为优先，借助成熟开源框架完成 v1，再按需自研替换

---

## 一、 平台定位与目标

### 1.1 产品定位
CoffeeClaw 是一个 **企业级 AI Agent 开发平台**，为开发者提供构建、编排、执行和管理自主 Agent 的完整基础设施。平台聚焦于 Agent 能力本身的抽象与标准化，上层业务（OTA 客服、企业助手等）以应用形态接入。

```text
┌──────────────────────────────────┐
│        业务应用层（不在本文档范围）   │
│  OTA客服 │ 企业助手 │ 数据分析 │ …  │
├──────────────────────────────────┤
│    ★ CoffeeClaw Agent 开发平台 ★    │  ← 本文档范围
│  Runtime │ 编排 │ 工具 │ Memory │  │
├──────────────────────────────────┤
│         基础设施层                 │
│  云资源 │ 模型API │ 数据库 │ 监控  │
└──────────────────────────────────┘
```

### 1.2 设计原则
1. **Runtime 优先**：以 Agent 核心循环为中心，用 LangGraph 作为 v1 实现基础，后续按需自研替换。
2. **借力开源**：优先使用成熟开源框架（LangGraph、LiteLLM），而非过早自研。
3. **安全隔离**：v1 采用 Docker 容器 + 网络策略隔离工具执行；凭证通过 Vault/环境变量管理，WASM 沙箱作为后期演进目标。
4. **多 Agent 协作**：借鉴 Deer-Flow，支持协调器 + 专家 Agent 分工，通过 LangGraph 多图协作实现。
5. **工具标准化**：基于 MCP（Model Context Protocol）协议，统一工具注册、发现与调用。
6. **模型无关**：通过 LiteLLM 抽象模型接口层，支持任意 LLM 后端切换与路由。
7. **渐进演进**：先跑通核心业务路径，再按团队规模和实际瓶颈逐步替换组件。

### 1.3 核心量化指标
| 指标 | 目标值 | 说明 |
| :--- | :--- | :--- |
| Agent 单步工具调用延迟 | P99 < 200ms | 不含 LLM 推理时间 |
| LLM 推理延迟（含路由） | P99 < 2s | 含模型选择 + 推理 |
| Agent 编排延迟（DAG 调度） | < 50ms | 纯调度开销 |
| WASM 沙箱启动 | < 10ms | 冷启动 |
| 工具调用并发 | 10,000 QPS | 单集群 |
| 平台可用性 | 99.99% | 年度停机 < 52 分钟 |

---

## 二、 核心模块设计

### 2.1 Agent Runtime（平台心脏）

Agent Runtime 是 CoffeeClaw 的核心，负责 Agent 的生命周期管理、推理决策循环与执行控制。

#### 2.1.1 核心循环

Runtime 循环基于 **LangGraph** 实现，以 StateGraph 驱动 `感知 → 思考 → 行动 → 反思` 四节点图：

```python
# CoffeeClaw Agent 核心循环（基于 LangGraph 实现）
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

def build_agent_graph(agent_config: AgentConfig) -> CompiledGraph:
    graph = StateGraph(AgentState)

    # 节点定义
    graph.add_node("sense",   sense_node)    # 1. 感知：从 Memory 检索上下文
    graph.add_node("think",   think_node)    # 2. 思考：LLM 推理，选择工具/委派/响应
    graph.add_node("act",     act_node)      # 3. 行动：执行工具调用或委派子 Agent
    graph.add_node("reflect", reflect_node)  # 4. 反思：更新记忆，评估是否完成/升级

    # 边与条件路由
    graph.set_entry_point("sense")
    graph.add_edge("sense",   "think")
    graph.add_edge("think",   "act")
    graph.add_conditional_edges(
        "act",
        route_after_act,   # 返回 "reflect" | "sense"（继续循环）| END
        {"reflect": "reflect", "sense": "sense", END: END}
    )
    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,  # 返回 "sense"（继续）| "escalate"（人工） | END
        {"sense": "sense", "escalate": "escalate", END: END}
    )

    # 持久化 checkpoint（支持人工审批暂停恢复）
    checkpointer = PostgresSaver.from_conn_string(settings.POSTGRES_DSN)
    return graph.compile(checkpointer=checkpointer)
```

> **为何选 LangGraph**：内置 StateGraph 状态持久化、断点恢复、人工审批暂停（interrupt_before/after），以及完整的执行轨迹记录，小团队无需自研状态机。

#### 2.1.2 Agent 生命周期
```text
Created → Initialized → Running → (Paused ↔ Running) → Completed / Failed / Escalated
                                        ↑
                                   Checkpointed（支持中断恢复）
```

- **Created**：Agent 实例化，加载配置与策略。
- **Initialized**：绑定 Memory、注册可用工具、连接模型服务。
- **Running**：执行核心循环。
- **Paused**：等待人工审批或外部事件，状态持久化到 State Store。
- **Checkpointed**：定期快照完整状态，支持故障恢复与任务复现。
- **Completed / Failed / Escalated**：终态，触发后处理（日志归档、指标上报、通知回调）。

#### 2.1.3 Agent 定义（声明式配置）
与 Skills 类似，为了兼容开源社区的优秀 Prompt 库和角色设定库，Agent 也采用 **Markdown + YAML Frontmatter** 的通用标准格式。

```markdown
---
name: flight_expert
version: "1.2.0"
description: "机票领域专家 Agent"

# 模型配置
model:
  primary: gpt-4o
  fallback: qwen-max
  routing_strategy: cost_optimized

# 绑定的工具与 Skills（支持 MCP URI 或 本域目录加载）
capabilities:
  tools:
    - mcp://tools/flight-search@v2
    - mcp://tools/order-query@v1
    - mcp://tools/payment@v1
  skills:
    - local://skills/flight-rebooking

# 记忆配置
memory:
  short_term: redis
  long_term: pgvector
  state_store: postgres

# 安全策略
policy:
  sandbox: docker         # v1 使用 container 方案
  max_steps: 50           # 最大执行步数
  max_tool_calls: 20      # 最大工具调用次数
  escalation_threshold: 0.6 # 置信度低于此值则升级人工
  allowed_domains:
    - "*.airline-api.com"
    - "*.hotel-api.com"
  blocked_actions:
    - "delete_order"      # 禁止删除订单
---

# 角色设定 (Identity & Persona)
你是一个经验丰富、极其专业的航空公司客服代表助手高级 Agent。
你的目标是凭借你的专业知识，通过调用系统工具快速、准确地协助用户完成机票预订、退改签、行李额度查询等请求。

# 核心原则 (Core Guidelines)
1. **安全合规**：未经调用对应工具（例如 `payment` 并收到确切回执），绝不允许向用户承诺已完成支付或退款操作。
2. **同理心**：在处理延误、甚至取消等紧急情绪场景时，优先安抚用户情绪。
3. **数据严谨**：引用航班时间时，必须明确时区（如“北京时间”）；涉及到费用的换算时必须注明币种和汇率参考。
```

---

### 2.2 Agent 编排引擎（LangGraph 多 Agent + 固定工作流）

CoffeeClaw 的编排层提供两种互补机制，v1 均基于开源方案实现，避免过早自研：

| 编排模式 | 适用场景 | v1 实现方案 | 典型例子 |
| :--- | :--- | :--- | :--- |
| **动态多 Agent 协作** | 开放式、需要多专家协同的复杂任务 | LangGraph Multi-Agent Graph | "帮我规划三亚5天行程" |
| **固定工作流** | 确定性、有明确步骤的业务流程 | LangGraph Checkpoint | 退票审批流程、自助改签、发票开具 |

两者可以嵌套：Agent 自主决策时可触发一个固定工作流，固定工作流中的某节点也可委派给 Agent。

#### 2.2.1 动态多 Agent 协作（LangGraph Multi-Agent）

动态协作基于 LangGraph 的 **Supervisor + Subgraph** 模式，协调器 Agent 将任务分发给各领域专家 Agent：

```text
                    用户请求
                       │
                       ▼
              ┌────────────────┐
              │  协调器 Agent   │  任务解析、路由分发、结果整合
              │  (Supervisor)  │  ← LangGraph Supervisor 节点
              └────────┬───────┘
                       │ 按意图路由
          ┌────────────┼────────────┐
          ▼            ▼            ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ 机票专家  │  │ 酒店专家  │  │ 售后专家  │  各自独立的 LangGraph
   │  Agent  │  │  Agent  │  │  Agent  │  Subgraph
   └─────────┘  └─────────┘  └─────────┘
```

```python
# LangGraph Multi-Agent 实现（基于 langgraph >= 0.2）
from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

# 创建各领域专家 Agent
flight_agent = create_react_agent(llm, tools=flight_tools, name="flight_expert")
hotel_agent  = create_react_agent(llm, tools=hotel_tools,  name="hotel_expert")
service_agent = create_react_agent(llm, tools=service_tools, name="service_expert")

# 协调器统一调度
supervisor = create_supervisor(
    agents=[flight_agent, hotel_agent, service_agent],
    model=llm,
    prompt="你是任务协调器，根据用户需求路由到合适的专家 Agent"
)
```

| 能力 | 说明 |
| :--- | :--- |
| **意图路由** | Supervisor 根据用户意图选择对应专家 Agent |
| **并发调用** | 多个独立子任务可并行触发多个专家（LangGraph 原生支持）|
| **执行轨迹** | LangGraph 内置完整的 step 记录，通过 Postgres checkpoint 持久化 |
| **人工介入** | LangGraph `interrupt_before` 机制，遇审批节点自动暂停等待 |

> **后期演进**：当多 Agent 并发规模增大、LangGraph 调度成为瓶颈时，再考虑自研 DAG 调度器。

#### 2.2.2 固定工作流引擎（Workflow Engine）

固定工作流用于处理确定性业务流程——步骤固定、规则明确、需要人工审批或多系统协调的场景。

##### v1 方案：基于 LangGraph 的确定性状态图

> **复用基础设施。** 既然 Agent 核心循环使用了 LangGraph，固定工作流同样可以使用 LangGraph 的 StateGraph 和 Checkpoint 机制来实现。这能避免引入新的大负荷子系统，降低运维难度。

```python
# LangGraph 固定工作流定义（退票流程示例）
from langgraph.graph import StateGraph, END

def build_refund_workflow() -> CompiledGraph:
    workflow = StateGraph(RefundState)

    # 定义固定的业务节点
    workflow.add_node("query_order", query_order_node)
    workflow.add_node("check_rules", check_rules_node)
    workflow.add_node("manual_approval", manual_approval_node)
    workflow.add_node("execute_refund", execute_refund_node)
    workflow.add_node("notify_user", notify_user_node)

    # 定义确定的流转路径和条件分支
    workflow.set_entry_point("query_order")
    workflow.add_edge("query_order", "check_rules")
    
    # 条件分支：大额订单需要人工审批
    workflow.add_conditional_edges(
        "check_rules",
        check_approval_needed,
        {"requires_approval": "manual_approval", "auto_refund": "execute_refund"}
    )
    
    workflow.add_edge("manual_approval", "execute_refund")
    workflow.add_edge("execute_refund", "notify_user")
    workflow.add_edge("notify_user", END)

    # 利用 checkpointer 实现中断和长效运行
    return workflow.compile(
        checkpointer=postgres_saver,
        interrupt_before=["manual_approval"] # 在人工审批节点前自动挂起
    )
```

| LangGraph 工作流优势 | 说明 |
| :--- | :--- |
| **统一技术栈** | 与 Agent Runtime 共享相同的 Graph 表示和持久化基础设施 |
| **原生中断与恢复** | 通过 `interrupt_before`/`interrupt_after` 原生支持人工审批挂起 |
| **时间旅行调试** | 借助 Checkpoint 可以回溯到工作流的任何历史状态重放 |
| **灵活的重试策略** | 可以在节点内部集成 Tenacity 等重试库来实现节点级的出错重试 |
| **快速上手** | Python 原生定义，无需额外部署和维护复杂的工作流服务器集群 |

##### 动态编排 × 固定工作流的协作

两种编排模式可以灵活嵌套：

```text
场景1：Agent 触发固定工作流
  用户："帮我退掉明天的机票"
  → Agent Runtime 识别意图 refund_ticket
  → 触发 RefundWorkflow (LangGraph 编译的图)
  → 工作流按确定性步骤执行（查询→规则→审批→退款→通知）

场景2：固定工作流内委派 Agent
  退票流程遇到未预设的异常状态
  → 工作流图将执行权转移给 service_expert Agent 节点
  → Agent 自主分析并修复数据，然后将结果返回给工作流节点继续执行

场景3：LangGraph Supervisor 并行触发多个工作流
  用户："改签航班并重新订酒店"
  → Supervisor Agent 并行分发：
     ├── flight_expert Agent → 启动 RebookingWorkflow
     ├── hotel_expert Agent  → 自主搜索酒店（ReAct 循环）
     └── 整合行程方案 → 返回用户
```

#### 2.2.3 Agent 注册表
```yaml
# agent-registry.yaml — 专家 Agent 注册表
agents:
  - name: coordinator
    type: orchestrator
    description: "任务解析与协调"
    capabilities: [intent_analysis, task_decomposition, conflict_resolution]

  - name: flight-expert
    type: domain_expert
    description: "机票领域专家"
    capabilities: [fare_rules, rebooking, flight_status]
    tools: [flight_search, gds_query, airline_api]

  - name: hotel-expert
    type: domain_expert
    description: "酒店领域专家"
    capabilities: [room_availability, pricing, amenities]
    tools: [hotel_search, pms_query, review_analysis]

  - name: service-expert
    type: domain_expert
    description: "售后服务专家"
    capabilities: [complaint_handling, refund_processing, escalation]
    tools: [order_query, refund_api, ticket_system]

routing_rules:
  - intent: "flight_*"    → agent: flight-expert
  - intent: "hotel_*"     → agent: hotel-expert
  - intent: "complaint_*" → agent: service-expert
  - intent: "complex_*"   → mode: multi_agent_consultation  # 多专家会诊
```

---

### 2.3 工具与 Skill 系统（MCP + 隔离执行 + 能力封装）

平台不仅提供底层的“动作”（Tools），还提供更高聚合度的“业务能力”（Skills），形成 `Agent -> Skill -> Tool` 的调用层次。v1 工具使用 Docker 容器隔离。

#### 2.3.1 MCP 工具协议

每个工具遵循 Model Context Protocol 标准定义：

```json
{
  "tool": {
    "name": "flight_search",
    "version": "2.1.0",
    "description": "搜索可用航班信息",
    "input_schema": {
      "type": "object",
      "properties": {
        "origin": { "type": "string", "description": "出发城市 IATA 代码" },
        "destination": { "type": "string", "description": "到达城市 IATA 代码" },
        "date": { "type": "string", "format": "date" },
        "cabin_class": { "type": "string", "enum": ["economy", "business", "first"] }
      },
      "required": ["origin", "destination", "date"]
    },
    "output_schema": {
      "type": "array",
      "items": { "$ref": "#/definitions/FlightOption" }
    },
    "execution": {
      "timeout_ms": 5000,
      "retry": { "max_attempts": 3, "backoff": "exponential" },
      "fallback": "cached_flight_search",
      "sandbox": "docker",
      "required_permissions": ["network:gds-api.example.com"]
    }
  }
}
```

#### 2.3.2 工具隔离执行（v1: Docker 容器）

v1 采用 **Docker 容器 + 网络策略** 实现工具隔离，成熟可控；WASM 沙箱作为 v2+ 演进目标：

```text
┌────────────────────────────────────────┐
│     工具隔离执行（v1：Docker 容器）       │
│                                        │
│   Tool Call Request                    │
│        │                               │
│        ▼                               │
│   ┌───────────────────────────────┐    │
│   │    Docker 容器管理器            │    │
│   │  1. 复用容器池（冷启动 <500ms） │    │
│   │  2. 网络策略：仅白名单域名       │    │
│   │  3. 边界注入凭证（环境变量）     │    │
│   │  4. 执行工具代码               │    │
│   │  5. 返回结果，定期回收容器        │    │
│   └───────────────────────────────┘    │
│   凭证通过环境变量注入，LLM 上下文不含凭证 │
└────────────────────────────────────────┘
```

**安全机制**：
| 机制 | 说明 |
| :--- | :--- |
| **网络白名单** | Docker 网络策略仅允许访问 `allowed_domains` 中声明的域名 |
| **凭证边界注入** | API Key 通过 Docker 环境变量注入，LLM 上下文不包含明文 |
| **资源限制** | CPU / 内存 / 网络带宽的硬上限 |
| **审计日志** | 记录每次工具调用的完整输入/输出/耗时 |

**隔离级别对比**：
| 维度 | 传统进程 | Docker 容器（v1）| WASM 沙箱（v2+ 目标）|
| :--- | :--- | :--- | :--- |
| 启动延迟 | 毫秒级 | **100-500ms**（容器池复用）| **<10ms** |
| 内存开销 | 数十 MB | **数百 MB** | **5-20 MB** |
| 安全边界 | OS 权限 | **内核命名空间** | **语言运行时级** |
| 凭证保护 | 环境变量暴露 | **Secret 挂载** | **边界注入，LLM 不可见** |
| 成熟度 | 高 | **高** | 低（需踩坑）|

#### 2.3.3 工具注册与发现

```text
                    ┌──────────────┐
                    │  工具注册中心   │
                    │  (Registry)   │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ 内置工具     │ │ 自定义工具   │ │ 市场工具    │
     │ (Platform)  │ │ (Custom)   │ │ (Community)│
     ├────────────┤ ├────────────┤ ├────────────┤
     │ HTTP 请求   │ │ 航司 API    │ │ 搜索引擎    │
     │ 数据库查询   │ │ 酒店 PMS    │ │ 邮件发送    │
     │ 文件操作    │ │ 支付网关    │ │ 日历集成    │
     │ 代码执行    │ │ CRM 系统    │ │ 地图服务    │
     └────────────┘ └────────────┘ └────────────┘
```

工具发现流程：Agent 启动时从注册中心拉取其权限范围内的工具列表 → LLM 推理时参考工具描述选择合适工具 → Runtime 验证权限后在隔离容器中执行。

#### 2.3.4 Skill 系统（能力封装与复用）

单一的 Tool（如“调用API查询数据”）往往缺乏业务上下文。**Skill（技能）** 是在 Tool 之上封装的更高阶逻辑单元，它是特定领域专家经验的沉淀。

**拥抱开源社区标准：**
为了直接复用开源社区沉淀的优秀 Skills，CoffeeClaw 放弃私有的构造型 YAML，采用社区最通用的 **Folder & Markdown** 结构（即 YAML Frontmatter + Markdown 正文的形式）。这使得开源的提示词库、SOP 库可以直接被挂载和使用。

**Skill 目录结构：**
```text
skills/flight-rebooking/
├── SKILL.md           # (必填) 核心指令、SOP 和元数据
├── scripts/           # (可选) 技能配套的执行脚本 (Python/Shell)
└── examples/          # (可选) 供 LLM 参考的 Few-shot 示例
```

**通用 SKILL.md 定义示例：**
```markdown
---
name: flight_rebooking
version: "1.0.0"
description: "处理用户机票改签的专家技能"
require_tools: 
  - mcp://tools/flight-search@v2
  - mcp://tools/fare-rules-query@v1
---

# 核心指令
处理改签时，必须首先核实原机票的退改规则。
如果距离起飞时间 < 4 小时，必须提醒用户有紧急改签费。
推荐航班时，默认推荐同等舱位，时间差在前后 2 小时内的航班。

# 标准操作流程 (SOP)
1. **核实订单**：请求用户提供订单号，如果已有则跳过。
2. **查询规则**：调用 `fare-rules-query` 判断当前时间是否允许改签。
3. **搜索新航班**：调用 `flight-search` 查询用户目标日期的可用航班。
4. **人工确认**：整理好改签费用明细与新航班信息，呈现给用户确认。
```

**Skill 的运作方式：**
- Agent 可以在运行时“动态装载”某个 Skill 文件夹（解析 `SKILL.md` 的 Frontmatter 注册元数据，读取 Markdown 正文作为 System Prompt 的扩展），执行完毕后卸载，极大节省 Token 上下文。
- 从团队治理角度，业务专家（无需懂代码）可以通过编写人类可读的 Markdown 文件来沉淀业务经验；开源社区分享的 Markdown SOP 也能实现“开箱即用”。

---

### 2.4 Memory System（三层记忆架构）

Agent 需要三层记忆以支撑不同时间尺度的上下文管理：

```text
┌─────────────────────────────────────────────────┐
│                  Memory System                    │
│                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐ │
│  │  Short-term  │  │  Long-term   │  │  State   │ │
│  │  Memory      │  │  Memory      │  │  Store   │ │
│  ├─────────────┤  ├──────────────┤  ├──────────┤ │
│  │ 当前会话上下文 │  │ 知识与经验     │  │ 任务状态  │ │
│  │ 最近对话历史  │  │ 向量化记忆     │  │ 检查点   │ │
│  │ 工具调用结果  │  │ 语义检索      │  │ 执行轨迹  │ │
│  ├─────────────┤  ├──────────────┤  ├──────────┤ │
│  │ Redis        │  │ Qdrant/Milvus│  │ Postgres │ │
│  │ TTL: 1-24h   │  │ 永久         │  │ + pgvector│ │
│  │ 延迟: <1ms   │  │ 延迟: 5-20ms │  │ 延迟: <5ms│ │
│  └─────────────┘  └──────────────┘  └──────────┘ │
└─────────────────────────────────────────────────┘
```

#### 2.4.1 Short-term Memory（短期记忆）
- **用途**：当前会话的对话历史、槽位信息、工具调用结果。
- **存储**：Redis，TTL 1-24 小时。
- **关键设计**：
  - 滑动窗口：保留最近 N 轮对话 + 摘要压缩更早的历史。
  - Token 预算管理：根据模型上下文窗口动态裁剪。
  - 跨 Agent 传递：当协调器委派子任务时，传递相关上下文子集。

#### 2.4.2 Long-term Memory（长期记忆）
- **用途**：Agent 的知识库、学习经验、用户偏好。
- **存储**：v1 推荐使用 **PostgreSQL + pgvector**，规模化后可升级至 Qdrant / Milvus。
- **关键设计**：
  - 向量索引：使用 BGE-M3 / GTE-large 生成 Embedding。
  - 混合检索：向量语义检索 + BM25 关键词检索，融合排序。
  - 记忆沉淀：Agent 成功完成任务后，自动将关键经验向量化存储。
  - 遗忘机制：基于访问频率和时效性的衰减权重。

#### 2.4.3 State Store（状态存储）
- **用途**：任务执行状态、检查点、审计轨迹。
- **存储**：PostgreSQL。
- **核心表结构**：
```sql
-- Agent 实例表
CREATE TABLE agents (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50),
    config JSONB,           -- Agent 声明式配置
    status VARCHAR(20),     -- created/running/paused/completed/failed
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- 任务表
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    agent_id UUID REFERENCES agents(id),
    goal TEXT,
    status VARCHAR(20),
    dag JSONB,              -- 任务 DAG 结构
    current_step INT,
    created_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- 执行步骤表（完整轨迹，支持复现）
CREATE TABLE task_steps (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id),
    step_index INT,
    action_type VARCHAR(20),  -- tool_call / delegate / respond
    plan JSONB,               -- LLM 生成的推理计划
    result JSONB,             -- 执行结果
    latency_ms INT,
    model_used VARCHAR(100),
    token_usage JSONB,        -- {prompt_tokens, completion_tokens}
    created_at TIMESTAMPTZ
);

-- 工具调用审计日志
CREATE TABLE tool_logs (
    id UUID PRIMARY KEY,
    task_step_id UUID REFERENCES task_steps(id),
    tool_name VARCHAR(255),
    input_params JSONB,
    output_result JSONB,
    sandbox_type VARCHAR(20),
    permissions_used TEXT[],
    latency_ms INT,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMPTZ
);
```

---

### 2.5 模型服务层（智能路由 + 推理加速）

模型服务层抽象 LLM 细节，对 Agent Runtime 提供统一接口。

#### 2.5.1 模型路由策略

```text
           Agent 推理请求
                │
                ▼
        ┌───────────────┐
        │  模型路由器     │
        │  (Router)     │
        └───────┬───────┘
                │ 评估策略
       ┌────────┼────────┬────────────┐
       ▼        ▼        ▼            ▼
   ┌───────┐ ┌──────┐ ┌──────┐  ┌─────────┐
   │ GPT-4 │ │ Qwen │ │Llama │  │DistilBERT│
   │ 复杂   │ │ 常规  │ │ 私有  │  │ 边缘轻量  │
   │ 推理   │ │ 问答  │ │ 部署  │  │ 分类      │
   └───────┘ └──────┘ └──────┘  └─────────┘
```

**三种路由策略**：
| 策略 | 逻辑 | 适用场景 |
| :--- | :--- | :--- |
| `cost_optimized` | 简单任务用轻量模型，仅复杂推理升级至大模型 | 日常运营，降本 30-50% |
| `quality_first` | 始终使用最强模型，失败则降级 | 关键业务（支付、退改签） |
| `latency_first` | 优先选择延迟最低的可用模型 | 实时交互场景 |

**容错机制**：
- **故障转移**：主模型不可用时自动切换备用模型（GPT-4 → Qwen → 本地模型）。
- **熔断降级**：错误率 > 10% 或延迟 > 2s 时触发熔断，切换至轻量模型。
- **并发限流**：按模型 Provider 配置 QPS 上限，防止超额计费。

#### 2.5.2 推理优化
| 技术 | 效果 | 适用场景 |
| :--- | :--- | :--- |
| 模型量化 (INT8/INT4) | 显存降低 50-75%，延迟降低 30% | 私有化部署 |
| 动态批处理 | GPU 利用率提升 2-4x | 高并发 |
| KV Cache 复用 | 相似上下文的推理加速 40% | 多轮对话 |
| 推测解码 (Speculative) | 小模型草稿 + 大模型验证，加速 2-3x | 生成式场景 |
| vLLM PagedAttention | 吞吐量提升 2-4x | 自建推理服务 |

#### 2.5.3 安全过滤
在模型调用前后各设一道安全关卡：
- **输入过滤**：Prompt 注入检测、敏感信息拦截（身份证号/银行卡号不进 LLM 上下文）。
- **输出过滤**：有害内容检测、事实一致性校验（关键数据与数据库比对）、幻觉检测。

---

## 三、 可观测性

全链路可观测是平台运维和持续优化的基础。

### 3.1 四维观测体系
| 维度 | 技术栈 | 关注指标 |
| :--- | :--- | :--- |
| **链路追踪** | OpenTelemetry + Jaeger | 用户请求 → 意图识别 → 模型推理 → 工具调用 → 响应，全链路耗时 |
| **指标监控** | Prometheus + Grafana | Token 用量、工具调用成功率、模型延迟、Agent 完成率 |
| **日志平台** | structlog + ELK/Loki | 结构化日志，支持按 Agent/Task/Tool 维度检索 |
| **审计系统** | 自建 (Append-Only) | 所有敏感操作的完整上下文，保留 ≥ 3 年 |

### 3.2 关键业务指标看板
- **Agent 效能**：任务完成率、平均步骤数、平均耗时、人工升级率。
- **模型效率**：Token 消耗/任务、模型路由命中、成本/任务。
- **工具健康**：各工具调用量、成功率、P99 延迟、沙箱资源使用。
- **系统健康**：QPS、错误率、可用性 SLI/SLO、错误预算消耗。

---

## 四、 核心技术选型

### 4.1 平台核心
| 组件 | v1 推荐方案 | 后期演进 | 说明 |
| :--- | :--- | :--- | :--- |
| 开发语言 | Python 3.11+ | - | 统一技术栈，asyncio 高并发 |
| Web 框架 | FastAPI | - | 异步原生、自动 OpenAPI 文档 |
| Agent Runtime | **LangGraph** | 自研（v2+ 演进） | 内置状态持久化、断点恢复 |
| 模型集成层 | **LiteLLM** | - | 多模型统一接口 |
| 工作流引擎 | **LangGraph** | - | 统一编排底层，利用 Checkpoint 处理审批挂起 |
| 工具协议 | MCP (Model Context Protocol) | - | 社区标准 |
| 工具隔离 | **Docker 容器** | WASM（v2+ 演进） | 成熟可控 |
| 推理服务 | OpenAI/Anthropic 云 API | 自建 vLLM（规模化后） | v1 直接用云 API |

### 4.2 存储
| 用途 | v1 推荐方案 | 升级方案 | 说明 |
| :--- | :--- | :--- | :--- |
| Short-term Memory | Redis 7.0 | Redis Cluster | 会话上下文 |
| Long-term Memory | **Postgres + pgvector** | Qdrant / Milvus | 先用 pgvector，够用再升级 |
| State Store | PostgreSQL | - | 任务状态 + 审计 |

### 4.3 基础设施（分阶段引入）
| 组件 | v1 方案 | 规模化后升级 |
| :--- | :--- | :--- |
| 本地开发 | Docker Compose | - |
| 凭证管理 | 环境变量 + .env | HashiCorp Vault |
| CI/CD | GitHub Actions | ArgoCD + GitOps |
| 生产部署 | 云服务器（单机/双节点） | Kubernetes |

> **读/写分离、服务网格（Istio）、Kafka 消息队列等重型基础设施待规模化后再引入，v1 不强求。**

---

## 五、 项目结构

```text
coffeeclaw/
├── src/                            # 源代码
│   ├── __init__.py
│   ├── main.py                     # FastAPI 应用入口
│   ├── runtime/                    # Agent Runtime 核心（基于 LangGraph）
│   │   ├── __init__.py
│   │   ├── graph.py                # LangGraph StateGraph 定义（核心循环）
│   │   ├── nodes.py                # 各节点逻辑（sense/think/act/reflect）
│   │   ├── lifecycle.py            # 生命周期管理
│   │   └── checkpoint.py           # Postgres checkpoint 管理
│   ├── orchestrator/               # 多 Agent 编排（LangGraph Multi-Agent）
│   │   ├── __init__.py
│   │   ├── supervisor.py           # Supervisor + Subgraph 编排
│   │   └── registry.py             # Agent 注册表 + 路由规则
│   ├── workflow/                   # 固定工作流（基于 LangGraph）
│   │   ├── __init__.py
│   │   ├── graphs.py               # 固定工作流的 StateGraph 定义
│   │   └── nodes/                  # 各个具体业务节点实现
│   ├── tools/                      # 工具与 Skill 系统
│   │   ├── __init__.py
│   │   ├── mcp/                    # MCP 协议实现
│   │   ├── docker/                 # Docker 容器隔离执行（v1 沙箱）
│   │   ├── registry/               # 工具注册与发现
│   │   └── skills/                 # Skill 技能管理器（解析提示词与SOP）
│   ├── memory/                     # Memory System
│   │   ├── __init__.py
│   │   ├── shortterm.py            # Redis 短期记忆
│   │   ├── longterm.py             # Postgres + pgvector 长期记忆
│   │   └── statestore.py           # Postgres 状态存储
│   ├── model/                      # 模型服务层
│   │   ├── __init__.py
│   │   ├── router.py               # 智能路由（cost/quality/latency）
│   │   ├── provider.py             # 多模型 Provider（LiteLLM）
│   │   └── safety.py               # 输入输出安全过滤
│   ├── observability/              # 可观测性
│   │   ├── __init__.py
│   │   ├── tracing.py              # OpenTelemetry 追踪
│   │   ├── metrics.py              # Prometheus 指标
│   │   └── audit.py                # 审计日志
│   └── api/                        # API 层
│       ├── __init__.py
│       ├── routes.py               # FastAPI 路由定义
│       └── schemas.py              # Pydantic 数据模型
│
├── configs/                    # 配置文件
│   ├── agents/                 # Agent 声明式库 (AGENT.md)
│   ├── skills/                 # 各类开源与私有 Skills 仓库（SKILL.md）
│   └── tools/                  # 工具定义（MCP JSON）
│
├── tests/                      # 测试
│   ├── unit/
│   └── integration/
│
├── deploy/                     # 部署配置
│   └── docker/                 # Docker Compose（本地 + 生产简单版）
│
├── docs/                       # 文档
│
├── pyproject.toml              # 项目配置（依赖、构建）
├── Dockerfile
└── docker-compose.yml          # 本地开发环境
```

---

## 六、 实施路径

### Phase 1：核心 Runtime（第 1-2 个月）
- [ ] 基于 LangGraph 实现 Agent 核心循环（sense-think-act-reflect）
- [ ] 解析社区标准 Agent 配置格式 (Markdown Frontmatter)
- [ ] Memory System 基础版（Redis 短期 + Postgres 状态存储）
- [ ] 模型服务层基础版（LiteLLM 接入，支持 OpenAI/Anthropic）
- [ ] 基础工具与 Skill 系统（解析社区标准的 `SKILL.md`，支持动态装载 prompt 与工具）
- [ ] 本地开发环境 (Docker Compose)

**交付标准**：单个 Agent 可执行多步工具调用完成任务。

### Phase 2：多 Agent + 工作流（第 3-4 个月）
- [ ] LangGraph Multi-Agent 编排（协调器 + 专家 Agent 分发）
- [ ] Agent 注册表 + 意图路由规则
- [ ] 基于 LangGraph 实现固定工作流（人工审批通过 interrupt 支持）
- [ ] Postgres + pgvector Long-term Memory（向量语义检索）
- [ ] 模型智能路由（成本/质量/延迟三策略）
- [ ] 可观测性基础（OpenTelemetry + Prometheus）
- [ ] 凭证管理升级（HashiCorp Vault 或相当的 Secret 管理）

**交付标准**：多 Agent 协作完成复合任务，固定工作流支持人工审批和多系统协调。

### Phase 3：生产就绪 + 性能优化（第 5-6 个月）
- [ ] 检查点与故障恢复（任务可中断续做）
- [ ] 完整审计日志系统
- [ ] 模型推理优化（评估是否自建 vLLM + KV Cache）
- [ ] 工具隔离升级评估（WASM vs Docker 的正式决策）
- [ ] 向量库升级评估（pgvector 是否足够或迁移 Qdrant）
- [ ] 生产就绪部署（Docker Compose → 云服务器集群 → 按需 K8s）
- [ ] 全链路压测 + 性能基准建立
- [ ] 文档与 SDK

**交付标准**：平台可承载生产流量，可观测性完备，后续架构演进有清晰路径。
