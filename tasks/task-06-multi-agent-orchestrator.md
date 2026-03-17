# Task 06 — 多 Agent 编排（LangGraph Supervisor）

**所属阶段**：Phase 2（第 3-4 个月）  
**交付标准**：实现 Supervisor + Subgraph 模式，支持根据用户意图将任务路由给多个对应的专家 Agent
**当前状态**：已完成（2026-03-17）

---

## 背景

在复杂业务场景下，单个 Agent 难以兼顾所有工具和规则。CoffeeClaw 采用 LangGraph 的 Supervisor 模式进行动态多 Agent 编排：协调器（Supervisor）负责意图解析、任务分发与结果整合，各领域专家 Agent 负责具体的垂直任务。

---

## 任务列表

### 1. Agent 注册表扩展（`src/orchestrator/registry.py`）
- [x] 实现 `AgentRegistry` 单例类，加载 `configs/agents/agent-registry.yaml`
- [x] 解析 `agent-registry.yaml` 中的 `agents` 列表：
  - 加载每个专家 Agent 的配置（复用 Task 02 的 `AgentConfigParser`）
  - 获取其 `capabilities` 与可用 `tools`
- [x] 解析 `routing_rules`（意图 → Agent 路由映射规则）

### 2. 构建领域专家 Agent（`src/orchestrator/supervisor.py`）
- [x] 提供函数把 Task 02 中构建的单个 `CompiledGraph`（即专家 Agent）封装为可被 Supervisor 调用的节点
- [x] 支持将 Supervisor 下发的子任务目标作为专家 Agent `AgentState` 的初始 `goal`
- [x] 确保子 Agent 执行时，向 State Store 写入独立的任务步骤子树（Audit 关联）

### 3. 构建 Supervisor 节点（`src/orchestrator/supervisor.py`）
- [x] 根据注册表动态生成 `members` 列表（专家 Agent 全集）
- [x] 使用 `langgraph_supervisor.create_supervisor` 构建协调器：
  - 传入 `members`
  - 将 `AgentRegistry` 提供的能力描述组装进 Supervisor 的 System Prompt
  - 使用 LiteLLM `ModelService` 驱动 Supervisor 的推理
- [x] **上下文传递**：Supervisor 将全局对话历史（从 Short-term Memory 检索）和具体指令传递给子 Agent
- [x] **并行调用支持**：修改 LangGraph 边逻辑，允许 Supervisor 同时分发多个不相互依赖的子任务（如同时查询机票和酒店）

### 4. 意图路由规则（`src/orchestrator/registry.py`）
- [x] 当 Supervisor LLM 决策能力不足或为了节省大模型成本时，引入一个前置路由层
- [x] `IntentRouter`：轻量级分类器（基于提示词的小模型，或基于 `routing_rules` 的硬编码规则）
- [x] 先经过 `IntentRouter` 获取意图标签，约束/指导 Supervisor 的分发选择

### 5. Multi-Agent 图装配（`src/orchestrator/__init__.py`）
- [x] 提供门面函数 `build_multi_agent_graph()`：
  - 初始化 AgentRegistry
  - 实例化所有配置好的专家 Agent nodes
  - 构建 Supervisor node
  - 连结成一个巨大的 LangGraph 编译图
- [x] 配置 Checkpoint：使整个 Multi-Agent 协作过程支持暂停与恢复

### 6. 示例配置与测试
- [x] 在 `configs/agents/agent-registry.yaml` 中配置至少 2 个测试用的专家 Agent（如 `flight-expert`, `hotel-expert`）
- [x] 创建 `configs/agents/flight-expert.md` 和 `hotel-expert.md` 供解析

### 7. API 接口（`src/api/routes.py` 扩展）
- [x] `GET /orchestrator/agents` — 查询可用专家 Agent 列表及其能力
- [x] `POST /orchestrator/run` — 向协调器边界发起复杂任务请求

---

## 验收标准
- [x] `langgraph_supervisor` 成功构建包含至少 2 个专家 Agent 的父图
- [x] 发送复合指令（例："帮我查下明天的天气并在酒店留个言"）时，Supervisor 能正确将其拆分并先后/并行路由给两个不同的专家 Agent
- [x] 所有子 Agent 和 Supervisor 的执行轨迹统一记录在 `task_steps` 数据库表中
- [x] 通过 `thread_id` 可以准确恢复整个多 Agent 会话状态

---

## 依赖关系
- **前置**：Task 02（Agent Runtime 单点能力就绪）
- **后置**：无

---

## 参考资料
- PRD 2.2.1：动态多 Agent 协作
- PRD 2.2.3：Agent 注册表
