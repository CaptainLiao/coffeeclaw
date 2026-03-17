# CoffeeClaw

CoffeeClaw 是一个基于 FastAPI、LangGraph、Postgres 和 Redis 的 Agent 平台后端。

当前仓库已完成：

- FastAPI 应用启动与装配
- 基于 Docker 的本地开发环境
- Postgres 与 Redis 依赖接入
- 基础健康检查与日志链路
- Agent Runtime（创建/运行/暂停/恢复/状态/Trace）
- 短期记忆与任务轨迹落库
- OpenAI 兼容模型接入与基础安全过滤
- MCP 工具注册/调用、Skill 装载与注入
- 多 Agent 编排（Supervisor + 专家 Agent 路由）

## 当前目录结构

项目当前采用“薄共享层 + 领域目录”的结构：

- `src/core/`：应用工厂、配置、共享状态访问
- `src/api/`：HTTP 路由、Schema、依赖注入
- `src/observability/`：日志、请求上下文、异常处理
- `src/infrastructure/`：外部资源初始化与释放
- `src/services/`：少量横切应用服务
- `src/runtime/`：Agent 生命周期、图执行、状态流转
- `src/model/`：模型调用、路由、输入输出安全过滤
- `src/tools/`：MCP 工具定义、注册表、执行器、Skill 管理
- `src/memory/`：短期记忆存储适配
- `src/orchestrator/`、`src/workflow/`：后续任务扩展

更多说明见 `docs/architecture.md` 和 `prd.md`。

## 环境要求

- Docker Desktop
- Python 3.11
- `uv`

## 配置说明

配置采用两层文件覆盖机制：

1. `.env`（基础配置）
2. `.env.local`（本机覆盖，最高优先级）

生产环境建议通过外部环境变量注入，不依赖编辑文件。

主要环境变量：

- `POSTGRES_DSN`
- `REDIS_URL`
- `RUNTIME_REPOSITORY_BACKEND`（`postgres` 或 `memory`）
- `SHORTTERM_MEMORY_BACKEND`（`redis` 或 `memory`）
- `CHECKPOINT_BACKEND`（`postgres` 或 `memory`）
- `APP_ENV`
- `LOG_LEVEL`
- `MODEL_API_KEY`（推荐，单一 OpenAI 兼容入口）
- `MODEL_API_BASE`（可选，自建/第三方 OpenAI 兼容地址）
- `DEFAULT_PRIMARY_MODEL`
- `DEFAULT_FALLBACK_MODEL`
- `MODEL_TIMEOUT_SECONDS`
- `MAX_RETRIES`

模型选择规则：

- configs\agents 配置里如果不写 `model`，自动使用 `DEFAULT_PRIMARY_MODEL` / `DEFAULT_FALLBACK_MODEL`
- 这样切换模型时通常只需要改 `.env.local`，不需要改每个 agent 文件

默认的 Docker Compose 启动方式下，Postgres 和 Redis 都运行在容器中，应用容器会自动连接它们。

如需后续切换存储后端，可直接改环境变量：

- `RUNTIME_REPOSITORY_BACKEND=postgres|memory`
- `SHORTTERM_MEMORY_BACKEND=redis|memory`
- `CHECKPOINT_BACKEND=postgres|memory`

## 依赖管理

项目使用：

- `pyproject.toml` 声明依赖
- `uv.lock` 锁定精确版本

当你修改 `pyproject.toml` 中的依赖后，执行：

```powershell
uv lock
```

如果还需要把本地开发环境同步到最新锁文件，再执行：

```powershell
uv sync --extra dev
```

## 使用 Docker 启动

首次启动或修改依赖/镜像配置后：

```powershell
docker compose up -d --build
```

日常启动（不改依赖时）：

```powershell
docker compose up -d
```

查看容器状态：

```powershell
docker compose ps
```

预期结果：

- `app` 状态为 `Up`
- `postgres` 状态为 `Up` 且 `healthy`
- `redis` 状态为 `Up` 且 `healthy`

## 停止服务

```powershell
docker compose down
```

## 启动后验证

验证健康检查接口：

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health | Select-Object -ExpandProperty Content
```

预期返回：

```json
{"status":"ok","db":true,"redis":true}
```

打开 Swagger 文档：

- `http://localhost:8000/docs`

也可以用命令验证：

```powershell
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/docs).StatusCode
```

预期结果：

```text
200
```

## 工具与技能接口

- `GET /api/v1/tools`：查看已注册工具
- `GET /api/v1/tools/{tool_name}`：查看工具定义详情
- `POST /api/v1/tools/{tool_name}/test`：直接测试工具调用
- `GET /api/v1/skills`：查看已加载技能
- `GET /api/v1/orchestrator/agents`：查看可用专家 Agent
- `POST /api/v1/orchestrator/run`：发起多 Agent 协作任务

示例（PowerShell）：

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/v1/tools | Select-Object -ExpandProperty Content
```

## 使用 Python 本地启动

如果你希望应用进程在宿主机运行，需要先确保 Postgres 和 Redis 已经可用，然后同步依赖：

```powershell
uv sync --extra dev
```

启动 API：

```powershell
uv run uvicorn src.main:app --reload
```

## 质量检查

运行测试和静态检查：
- `python .\scripts\test.py`：只跑 `pytest`
- `python .\scripts\check.py`：依次跑 `ruff + mypy + pytest`

## 当前范围

仓库目前仍处于基础搭建阶段。大部分领域模块还只是占位目录，后续会按 `tasks/` 下的任务逐步实现。 
