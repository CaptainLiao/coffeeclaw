# Task 03 — Memory System 基础版

**所属阶段**：Phase 1（第 1-2 个月）  
**交付标准**：Short-term Memory（Redis）与 State Store（Postgres）可用，Agent 可在多轮对话中保持上下文连贯

---

## 背景

CoffeeClaw 的 Memory System 采用三层架构。Phase 1 实现前两层：
- **Short-term Memory**（Redis）：当前会话上下文，TTL 1-24h
- **State Store**（Postgres）：任务状态、执行步骤、审计轨迹

Long-term Memory（pgvector 向量检索）在 Phase 2 Task 08 中实现。

---

## 任务列表

### 1. Redis 连接管理（`src/memory/shortterm.py`）
- [ ] 使用 `redis.asyncio` 创建异步 Redis 连接池
- [ ] 实现 `get_redis_client()` 工厂函数，在 FastAPI 启动时初始化，关闭时释放

### 2. Short-term Memory 实现（`src/memory/shortterm.py`）
- [ ] 实现 `ShortTermMemory` 类，Key 结构：`session:{session_id}:messages`
- [ ] `append_message(session_id, message)` — 向列表追加消息（LangChain Message 序列化为 JSON）
- [ ] `get_messages(session_id, limit=50)` — 获取最近 N 条消息
- [ ] `set_session_ttl(session_id, ttl_seconds=86400)` — 设置/刷新 TTL
- [ ] `clear_session(session_id)` — 清除会话
- [ ] **滑动窗口压缩**：当消息数超过阈值（如 100 条）时，保留最近 50 条 + 生成摘要存入 `session:{id}:summary`
- [ ] **Token 预算管理**：`get_context_within_budget(session_id, max_tokens)` — 根据 Token 数限制动态裁剪历史

### 3. Postgres 异步连接管理（`src/memory/statestore.py`）
- [ ] 使用 `SQLAlchemy 2.0 async engine` 创建异步连接池
- [ ] 实现 `get_db_session()` 异步上下文管理器
- [ ] 在 FastAPI 启动生命周期中初始化连接池，关闭时 dispose

### 4. State Store CRUD（`src/memory/statestore.py`）
- [ ] 基于 PRD 2.4.3 节的表结构，定义 SQLAlchemy ORM 模型：
  - `AgentModel`（对应 `agents` 表）
  - `TaskModel`（对应 `tasks` 表）
  - `TaskStepModel`（对应 `task_steps` 表）
  - `ToolLogModel`（对应 `tool_logs` 表）
- [ ] 实现 `AgentStateStore` 类，提供：
  - `create_agent(config: AgentConfig)` → 写入 `agents` 表，返回 `agent_id`
  - `update_agent_status(agent_id, status)` → 更新状态字段
  - `create_task(agent_id, goal)` → 写入 `tasks` 表，返回 `task_id`
  - `update_task_status(task_id, status, dag=None)` → 更新任务状态
  - `append_task_step(task_id, step: TaskStepData)` → 写入单步执行记录
  - `append_tool_log(task_step_id, log: ToolLogData)` → 写入工具调用日志
  - `get_task_trace(task_id)` → 查询完整执行轨迹（步骤 + 工具日志）

### 5. Memory 门面类（`src/memory/__init__.py`）
- [ ] 实现 `MemoryManager` 门面类，组合 `ShortTermMemory` 与 `AgentStateStore`
- [ ] 提供统一接口供 Runtime 调用：
  - `save_turn(session_id, user_msg, assistant_msg)` — 保存一轮对话
  - `load_context(session_id, max_tokens)` — 加载上下文
  - `persist_step(task_id, step_data)` — 持久化步骤
  - `persist_tool_log(step_id, log_data)` — 持久化工具日志

### 6. 数据库迁移脚本
- [ ] 在 `deploy/docker/init.sql` 中补全 PRD 2.4.3 节所有表的 DDL（含索引）：
  - `agents` 表：在 `status`、`created_at` 字段建索引
  - `tasks` 表：在 `agent_id`、`status` 字段建索引
  - `task_steps` 表：在 `task_id`、`step_index` 建联合索引
  - `tool_logs` 表：在 `task_step_id`、`tool_name`、`success` 建索引

### 7. API 接口（`src/api/routes.py` 扩展）
- [ ] `GET /tasks/{task_id}/trace` — 查询任务完整执行轨迹

---

## 验收标准
- [ ] Redis：跨多个请求的同一 `session_id` 可正确累积和检索消息
- [ ] Redis：超过 100 条消息时自动触发滑动窗口压缩
- [ ] Postgres：Agent 完整生命周期（创建 → 运行 → 完成）的状态变更全部记录入库
- [ ] Postgres：`GET /tasks/{task_id}/trace` 返回完整的步骤与工具调用记录
- [ ] 单元测试：`ShortTermMemory` 的 CRUD、TTL、滑动窗口逻辑均有测试覆盖

---

## 依赖关系
- **前置**：Task 01（项目初始化，Docker Compose 中 Redis + Postgres 可用）
- **后置**：Task 02（Runtime 核心循环使用 Memory）、Task 08（在此基础上扩展 Long-term Memory）

---

## 参考资料
- PRD 2.4.1：Short-term Memory 设计
- PRD 2.4.3：State Store 表结构（完整 SQL）
