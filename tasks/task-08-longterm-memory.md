# Task 08 — 长期记忆 (Long-term Memory)

**所属阶段**：Phase 2（第 3-4 个月）  
**交付标准**：基于 pgvector 实现记忆切片和向量化存储；实现 Agent 每次任务完成后的反思记录，并在下次推理前提供语义检索

---

## 背景

长期记忆是 Agent 沉淀知识和经验的地方。v1 通过复用现有的 PostgreSQL 并引入 `pgvector` 插件实现低成本的语义向量库。当 Agent 结单时将重要教训打乱并存储，未来在收到相似任务时，可供 `sense` 节点提取回忆。

---

## 任务列表

### 1. Postgres 插件与表结构（Alembic Migration）
- [ ] 确保 Docker 提供的 Postgres 镜像集成了 `pgvector`
- [ ] 在数据库初始化启用扩展：
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
- [ ] 创建长期记忆表：
  ```sql
  CREATE TABLE long_term_memories (
      id UUID PRIMARY KEY,
      agent_id UUID REFERENCES agents(id),
      content TEXT NOT NULL,          -- 经验/知识明文
      embedding vector,               -- 维度由配置确定，避免与特定 embedding 模型强耦合
      metadata JSONB,                 -- 额外标签 (领域、任务ID、创建时间)
      access_count INT DEFAULT 0,     -- 访问频次（用于遗忘淘汰衰减）
      created_at TIMESTAMPTZ DEFAULT NOW(),
      last_accessed_at TIMESTAMPTZ
  );
  -- 对 embedding 列创建 IVFFlat 或 HNSW 索引加速查询
  ```

### 2. Embedding 模型接入（`src/model/provider.py` 扩展）
- [ ] 在 LiteLLM 封装内增加 `async_embedding(text: str, model: str)` 方法
- [ ] 支持统一调用 OpenAI `text-embedding-3-small` 或本地 BGE 等模型获取向量数组
- [ ] 在配置中新增并使用：
  - `embedding_model`
  - `embedding_dimension`
  - `memory_similarity_threshold`

### 3. LongTermMemory 核心实现（`src/memory/longterm.py`）
- [ ] 使用 SQLAlchemy 映射表模型（包括 `Mapped[Vector]` 的支持语句）
- [ ] `add_memory(agent_id, content, metadata=None)`：获得文本 Embedding 并写入 DB
- [ ] `search_memories(agent_id, query_text, top_k=3, threshold=None)`（默认读取配置）：
  1. 通过 API 获取 Query Embedding
  2. 使用 pgvector 的余弦相似度操作符 (`<=>`) 在库中查找最匹配记录
  3. 查到后自动更新该记录的 `last_accessed_at` 和 `access_count`
- [ ] （可选）`forget_old_memories()` 跑定时清理打分过低或太久未用的上下文记忆空间

### 4. Runtime 循环集成
- [ ] 拓展 **reflect 节点**（`src/runtime/nodes.py`）：
  - 任务被标记为 `completed` 或 `failed` 后，由 LLM 总结 `"对后续处理同类问题有帮助的心得 / 方案 / 用户偏好"`
  - 调用 `add_memory` 将结构化心得入库
- [ ] 拓展 **sense 节点**（`src/runtime/nodes.py`）：
  - 基于当前用户最新一条指令，异步并行调用：
    - 短期记忆检索 (Task 03)
    - 长期记忆向量检索 (`search_memories`)
  - 把匹配到的历史经验（格式化为字符串）合并到送入 think 节点的 `AgentState.memory_context` 内

### 5. API 接口（`src/api/routes.py` 扩展）
- [ ] `GET /agents/{agent_id}/memories` — 查看 Agent 的长期记忆树（后台管理用）
- [ ] `DELETE /agents/{agent_id}/memories/{memory_id}` — 手动干预删除错误经验

---

## 验收标准
- [ ] 第一轮对话：告诉 Agent "我对靠窗位置晕车，请以后帮我定过道"，Agent 完成订票并生成反思经验存入 PG
- [ ] 第二轮会话（清空 redis 或新建 thread_id 后）：新建订票任务，不再提醒晕车，但 Agent 自动在 prompt 里搜寻到 pgvector 中此用户的喜好，选择过道座位
- [ ] 记忆检索命中/未命中与相似度阈值行为可观测，查询时延通过 Task 10 指标与压测场景验收

---

## 依赖关系
- **前置**：Task 03（底层 Postgres DB 设施），Task 04（Model Service 可供提取 Embedding）
- **后置**：无

---

## 参考资料
- PRD 2.4.2：Long-term Memory 设计
- pgvector 官方集成文档
