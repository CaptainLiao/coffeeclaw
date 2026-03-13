# Task 02 — Agent Runtime 核心循环

**所属阶段**：Phase 1（第 1-2 个月）  
**交付标准**：单个 Agent 可基于声明式配置（AGENT.md）启动，并执行多步工具调用完成给定任务

---

## 背景

Agent Runtime 是 CoffeeClaw 的核心，基于 **LangGraph** 实现 `感知(sense) → 思考(think) → 行动(act) → 反思(reflect)` 四节点循环。Runtime 负责 Agent 整个生命周期管理，并通过 Postgres checkpoint 支持状态持久化与中断恢复。

---

## 任务列表

### 1. AgentState 定义（`src/runtime/graph.py`）
- [x] 使用 `TypedDict` 定义 `AgentState`，字段包含：
  ```python
  class AgentState(TypedDict):
      messages: list            # 对话历史（LangChain Message 格式）
      goal: str                 # 当前任务目标
      tool_calls: list          # 本步骤待执行的工具调用
      tool_results: list        # 工具调用返回结果
      step_count: int           # 当前步骤计数
      reflection: str           # 反思结果摘要
      status: str               # running / completed / failed / escalate
      agent_config: dict        # Agent 声明式配置（从 AGENT.md 解析）
      memory_context: str       # 从 Memory 检索到的上下文
  ```
- [x] 实现 `build_agent_graph(agent_config)` 函数，构建并返回编译好的 LangGraph `CompiledGraph`

### 2. 四节点逻辑（`src/runtime/nodes.py`）
- [x] **sense 节点**（感知）：
  - 从 Short-term Memory（Redis）检索最近对话历史
  - 将上下文注入 `AgentState.memory_context`
  - 构建本轮 LLM 推理所需的上下文窗口（Token 预算管理，超出则截断早期历史）
- [x] **think 节点**（思考）：
  - 调用 `src/model/provider.py` 中的统一模型接口（LiteLLM）
  - 传入当前 State + 工具定义列表，让 LLM 决策：调用工具 / 委派子 Agent / 直接响应
  - 返回 `tool_calls`（工具调用指令）或最终响应
- [x] **act 节点**（行动）：
  - 遍历 `tool_calls`，通过工具执行器（Task 05 实现）在 Docker 容器中执行
  - 将 `tool_results` 写回 `AgentState`
  - 记录工具调用到 `tool_logs` 表（审计）
- [x] **reflect 节点**（反思）：
  - LLM 基于当前执行结果评估：任务完成？继续循环？需要人工介入？
  - 更新 `AgentState.status` 与 `reflection` 字段
  - 若完成，将关键经验写入 Long-term Memory（Task 08 实现占位）

### 3. 条件路由（`src/runtime/graph.py`）
- [x] 实现 `route_after_act(state)` 路由函数：
  - 工具执行成功 → `"reflect"`
  - 工具执行失败 / 重试耗尽 → `"reflect"`（带失败标记）
- [x] 实现 `route_after_reflect(state)` 路由函数：
  - `status == "completed"` → `END`
  - `status == "failed"` → `END`
  - `status == "escalate"` → `"escalate"`（人工审批节点，Task 07 扩展）
  - 超过 `max_steps` → 强制结束，`status = "failed"`
  - 其他 → `"sense"`（继续下一轮循环）

### 4. Agent 声明式配置解析（`src/runtime/lifecycle.py`）
- [x] 实现 `AgentConfigParser.parse(agent_md_path)` 方法：
  - 解析 YAML Frontmatter（读取 `name`、`version`、`model`、`capabilities`、`memory`、`policy` 字段）
  - 解析 Markdown 正文（作为 System Prompt 内容）
  - 返回 `AgentConfig` Pydantic 模型
- [x] `AgentConfig` 包含：
  ```python
  class ModelConfig(BaseModel):
      primary: str
      fallback: str
      routing_strategy: str = "cost_optimized"
  
  class PolicyConfig(BaseModel):
      sandbox: str = "docker"
      max_steps: int = 50
      max_tool_calls: int = 20
      escalation_threshold: float = 0.6
      allowed_domains: list[str] = []
      blocked_actions: list[str] = []
  
  class AgentConfig(BaseModel):
      name: str
      version: str
      description: str
      model: ModelConfig
      capabilities: dict
      memory: dict
      policy: PolicyConfig
      system_prompt: str          # Markdown 正文
  ```

### 5. Agent 生命周期管理（`src/runtime/lifecycle.py`）
- [x] 实现 `AgentManager` 类，负责：
  - `create_agent(config_path)` → 创建 Agent 实例，写入 `agents` 表，状态 `created`
  - `initialize_agent(agent_id)` → 绑定 Memory、注册工具、连接模型，状态 `initialized`
  - `run_agent(agent_id, goal, thread_id)` → 启动核心循环，状态 `running`
  - `pause_agent(agent_id)` → 保存 Checkpoint，状态 `paused`
  - `resume_agent(agent_id, thread_id)` → 从 Checkpoint 恢复，状态 `running`
  - `get_agent_status(agent_id)` → 查询当前状态与最新 step 信息

### 6. Postgres Checkpoint（`src/runtime/checkpoint.py`）
- [x] 封装 `PostgresSaver.from_conn_string()` 初始化逻辑
- [x] 提供 `get_checkpointer()` 异步工厂函数，供 `build_agent_graph()` 调用
- [x] 处理连接池复用，避免每次重建

### 7. API 接口（`src/api/routes.py` 扩展）
- [x] `POST /agents` — 创建 Agent（接收 `agent_config_path` 或内联配置 JSON）
- [x] `POST /agents/{agent_id}/run` — 启动 Agent 执行任务（`{"goal": "...", "thread_id": "..."}`）
- [x] `GET /agents/{agent_id}/status` — 查询 Agent 状态
- [x] `POST /agents/{agent_id}/pause` — 暂停 Agent
- [x] `POST /agents/{agent_id}/resume` — 恢复 Agent（传入 `thread_id`）

### 8. 示例 Agent 配置（`configs/agents/`）
- [x] 创建 `configs/agents/demo-agent.md`，参考 PRD 2.1.3 节示例格式，用于验收测试

---

## 验收标准
- [x] 加载 `configs/agents/demo-agent.md`，成功解析配置
- [x] `POST /agents/{agent_id}/run` 触发 Agent 执行，能完成 ≥ 3 步工具调用（使用 Mock 工具）
- [x] 中断后通过相同 `thread_id` 恢复，执行上下文完整保留
- [x] `step_count` 达到 `max_steps` 时，Agent 自动终止，状态置为 `failed`
- [x] 所有工具调用记录写入 `tool_logs` 表

## 当前实现说明

- 当前 `sense / think / act` 使用了 runtime 内部的临时 mock 适配器，目的是先把 Task 02 的核心循环、checkpoint、恢复和 API 跑通。
- 真实的 LiteLLM、Short-term Memory 检索策略和 Docker 工具执行器将分别在 Task 03 / 04 / 05 中替换，不需要重写 `graph` 与 `lifecycle` 主干。
- `pause_agent()` 当前语义是“状态置为 paused，并允许后续基于 checkpoint 恢复”，不是运行中强制中断。

## 本次验收记录

- `pytest tests -q` 通过
- `ruff check src tests` 通过
- `mypy src tests --cache-dir .tmp_mypy_cache` 通过
- API 闭环验证通过：创建 Agent、运行任务、查询状态、基于相同 `thread_id` 恢复

---

## 依赖关系
- **前置**：Task 01（项目初始化）
- **后置**：Task 03（替换短期记忆实现）、Task 04（替换模型实现）、Task 05（替换工具执行实现）、Task 06（多 Agent 编排）、Task 07（固定工作流）

---

## 参考资料
- PRD 2.1.1：核心循环（LangGraph 代码示例）
- PRD 2.1.2：Agent 生命周期
- PRD 2.1.3：Agent 声明式配置格式（AGENT.md）
