# Task 05 — 工具与 Skill 系统基础版

**所属阶段**：Phase 1（第 1-2 个月）  
**交付标准**：Agent 可注册工具（MCP 协议）并通过统一执行器接口完成调用；可动态装载 `SKILL.md` 技能文件，将其 Prompt 注入 System 上下文；Docker 隔离执行提供可替换实现与冒烟验证

---

## 背景

CoffeeClaw 的工具与 Skill 系统形成 `Agent → Skill → Tool` 的调用层次：
- **Tool**：遵循 MCP 协议的底层执行单元，v1 在 Docker 容器中隔离运行
- **Skill**：封装业务经验的高阶逻辑，以 `SKILL.md`（Markdown + YAML Frontmatter）定义，由 Agent 动态装载

---

## 任务列表

### 1. MCP 工具协议定义（`src/tools/mcp/`）
- [ ] 实现 `MCPToolDefinition` Pydantic 模型，完整映射 PRD 2.3.1 节 JSON Schema：
  ```python
  class ExecutionConfig(BaseModel):
      timeout_ms: int = 5000
      retry: RetryConfig = RetryConfig()
      fallback: str | None = None
      sandbox: str = "docker"
      required_permissions: list[str] = []
  
  class MCPToolDefinition(BaseModel):
      name: str
      version: str
      description: str
      input_schema: dict       # JSON Schema
      output_schema: dict      # JSON Schema
      execution: ExecutionConfig
  ```
- [ ] 实现 `MCPToolLoader.from_json(path)` — 从 `configs/tools/*.json` 加载工具定义
- [ ] 实现 `MCPToolLoader.from_dict(data)` — 从字典加载（运行时动态注册）

### 2. 工具注册表（`src/tools/registry/`）
- [ ] 实现 `ToolRegistry` 单例类：
  - `register(tool_def: MCPToolDefinition)` — 注册工具（内存存储，v1 不持久化）
  - `get(tool_name: str)` → `MCPToolDefinition | None` — 按名称查询
  - `list_for_agent(agent_config: AgentConfig)` → `list[MCPToolDefinition]` — 返回该 Agent 权限范围内的工具列表
  - `load_from_dir(dir_path)` — 批量扫描 `configs/tools/` 目录，加载所有 JSON 定义
- [ ] 应用启动时（FastAPI lifespan）自动调用 `load_from_dir` 完成初始注册

### 3. 执行器分层与 Docker 实现（`src/tools/docker/`）
- [ ] 定义统一 `ToolExecutor` 协议与 `ToolExecutorFactory.get(sandbox_type)`（接口优先，支持后续 wasm）
- [ ] 先落地一个本地/进程内执行器用于主流程联调与单测，确保 Task 02 `act` 节点可先无阻塞接入
- [ ] 实现 `DockerToolExecutor` 基础版（可替换）：
  - `execute(tool_def, input_params, credentials)` 支持超时、结果解析、异常归一化
  - 支持凭证环境变量注入与最小资源限制
- [ ] 高复杂能力拆分为后续增强项（不阻塞本任务收口）：
  - 容器池预热与回收策略
  - 细粒度网络白名单策略
  - 完整重试编排与故障注入测试

### 4. 工具调用门面（`src/tools/__init__.py`）
- [ ] 实现 `ToolCaller` 类，供 Runtime `act` 节点调用：
  ```python
  class ToolCaller:
      async def call(
          self,
          tool_name: str,
          input_params: dict,
          agent_config: AgentConfig,
          task_step_id: str,
      ) -> ToolResult:
          # 1. 从 Registry 查找工具定义
          # 2. 验证 input_params（JSON Schema 校验）
          # 3. 检查 blocked_actions 策略
          # 4. DockerToolExecutor.execute()
          # 5. 记录 tool_logs（通过 MemoryManager）
          # 6. 返回 ToolResult
  ```
- [ ] `ToolResult` 包含：`success: bool`、`output: dict | None`、`error: str | None`、`latency_ms: int`

### 5. Skill 技能管理器（`src/tools/skills/`）
- [ ] 实现 `SkillLoader.load(skill_dir)` 方法，解析 `SKILL.md`：
  - 提取 YAML Frontmatter：`name`、`version`、`description`、`require_tools`
  - 提取 Markdown 正文作为 Skill Prompt（SOP 与核心指令）
  - 返回 `SkillDefinition(name, version, description, require_tools, prompt)`
- [ ] 实现 `SkillManager` 类：
  - `load_from_dir(dir_path)` — 扫描 `configs/skills/` 目录，批量加载所有技能
  - `get(skill_name)` → `SkillDefinition | None`
  - `inject_into_context(skill_name, agent_system_prompt)` — 将 Skill Prompt 追加到 Agent System Prompt（返回合并后的 Prompt 字符串）
  - 技能按需装载（Agent 推理时传入 `capabilities.skills` 列表，用完即卸载）

### 6. 示例工具与技能定义
- [ ] 创建 `configs/tools/http-request.json` — 通用 HTTP 请求工具（Mock 实现，用于测试）
- [ ] 创建 `configs/tools/echo.json` — Echo 工具（原样返回输入，用于单元测试）
- [ ] 创建 `configs/skills/demo-skill/SKILL.md` — 示例技能定义（参考 PRD 2.3.4 节格式）

### 7. API 接口（`src/api/routes.py` 扩展）
- [ ] `GET /tools` — 列出所有已注册工具
- [ ] `GET /tools/{tool_name}` — 查看工具详情（含 input/output schema）
- [ ] `GET /skills` — 列出所有已加载技能
- [ ] `POST /tools/{tool_name}/test` — 直接测试工具调用（Dev 环境使用）

---

## 验收标准
- [ ] 扫描 `configs/tools/` 目录，所有工具定义自动注册到 Registry
- [ ] 通过 `ToolCaller.call("echo", {"message": "hello"})` 成功执行并返回结果（默认执行器）
- [ ] `DockerToolExecutor` 完成至少 1 条工具调用冒烟测试（可在集成测试或手工验收中完成）
- [ ] `blocked_actions` 策略生效：调用被禁止的工具时返回 `PermissionError`
- [ ] `configs/skills/demo-skill/SKILL.md` 加载后，Skill Prompt 正确注入 Agent System Prompt
- [ ] 工具调用记录准确写入 `tool_logs` 表（含 `latency_ms`、`success`）

---

## 依赖关系
- **前置**：Task 01（项目初始化，Docker 环境可用）、Task 02（Runtime 主干已落地）、Task 03（工具日志写入 State Store）
- **后置**：Task 06（多 Agent 共享工具注册表）

---

## 参考资料
- PRD 2.3.1：MCP 工具协议（JSON Schema 示例）
- PRD 2.3.2：工具隔离执行（Docker 容器方案）
- PRD 2.3.3：工具注册与发现
- PRD 2.3.4：Skill 系统（SKILL.md 格式）
