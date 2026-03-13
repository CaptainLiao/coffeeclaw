# Task 03 — Memory System 基础版

**所属阶段**：Phase 1（第 1-2 个月）  
**交付标准**：Short-term Memory（Redis）可用，并与现有 Runtime State Store（Postgres）打通，Agent 可在多轮对话中保持上下文连贯

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

### 3. State Store 连接与仓储复用（`src/runtime/repository.py`）
- [ ] 复用当前 Runtime 已落地的 State Store 仓储实现，避免在 `src/memory/` 再新增一套平行 ORM
- [ ] 对现有仓储补齐 Memory 场景所需接口（如 trace 查询、token_usage/tool_logs 写入辅助）
- [ ] 统一由应用资源层维护连接生命周期，不重复初始化 Postgres 连接池

### 4. State Store CRUD 增强（`src/runtime/repository.py`）
- [ ] 基于 PRD 2.4.3 节表结构，检查并补齐现有仓储能力：
  - `agents` / `tasks` / `task_steps` / `tool_logs` 的读写接口完整性
  - `get_task_trace(task_id)` 查询完整执行轨迹（步骤 + 工具日志）
- [ ] 统一 Runtime 与 Memory 的状态持久化入口，禁止出现 `runtime.repository` 与 `memory.statestore` 双轨实现

### 5. Memory 门面类（`src/memory/__init__.py`）
- [ ] 实现 `MemoryManager` 门面类，组合 `ShortTermMemory` 与 Runtime 仓储接口
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
- **前置**：Task 01（项目初始化，Docker Compose 中 Redis + Postgres 可用）、Task 02（Runtime 主干已落地）
- **后置**：Task 04（写入 token_usage 等模型数据）、Task 05（写入工具审计数据）、Task 08（在此基础上扩展 Long-term Memory）

---

## 参考资料
- PRD 2.4.1：Short-term Memory 设计
- PRD 2.4.3：State Store 表结构（完整 SQL）
