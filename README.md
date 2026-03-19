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

- `SQL_DSN`
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

默认的 `docker-compose.yml` 是更干净的运行态配置：

- 使用 `prod` 镜像目标
- 不挂载源码目录
- 不启用容器内热重载

本地开发如果需要挂载源码和 `--reload`，请叠加 `docker-compose.dev.yml`。

默认的 Docker Compose 启动方式下，Postgres 和 Redis 都运行在容器中，应用容器会自动连接它们。
数据库表结构不再由应用启动时自动创建，而是由 Alembic 迁移统一管理。
`docker-compose.yml` 会通过 `env_file` 读取 `.env` / `.env.local`，因此模型和应用配置会直接沿用你的本地文件。
只有 `SQL_DSN` 和 `REDIS_URL` 会在 Compose 中覆盖成容器内地址，因为容器里不能使用 `localhost` 访问 `postgres` / `redis` 服务。

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

运行态启动：

```powershell
python .\scripts\docker.py prod
```

该命令会先运行一次 `migrate` 服务执行 `alembic upgrade head`，迁移成功后 `app` 才会启动。

开发态启动（挂载源码 + 容器内热重载）：

```powershell
python .\scripts\docker.py dev
```

停止服务：

```powershell
python .\scripts\docker.py down
```

查看容器状态：

```powershell
python .\scripts\docker.py ps
```

查看日志：

```powershell
python .\scripts\docker.py logs app --tail 120
```

预期结果：

- `migrate` 状态为 `Exited (0)`
- `app` 状态为 `Up`
- `postgres` 状态为 `Up` 且 `healthy`
- `redis` 状态为 `Up` 且 `healthy`

说明：

- Docker 开发容器已启用 `WATCHFILES_FORCE_POLLING=true`，避免 Windows 绑定挂载下 `--reload` 的文件监听抖动。

## 启动后验证

验证健康检查接口：

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health | Select-Object -ExpandProperty Content
```

预期返回：

```json
{"code":1,"data":{"status":"ok","db":true,"redis":true}}
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

- `POST /api/v1/agents/run`：提交单 Agent 任务，立即返回 `task_id` 和 `running`
- `GET /api/v1/agents/status`：查看 Agent 当前状态和最近任务
- `POST /api/v1/agents/pause`：请求暂停当前运行任务，返回 `pausing` 或 `paused`
- `POST /api/v1/agents/resume`：恢复已暂停任务，立即返回 `running`
- `GET /api/v1/tasks/{task_id}/trace`：查看任务最终状态、步骤和工具日志
- `GET /api/v1/tools`：查看已注册工具
- `GET /api/v1/tools/{tool_name}`：查看工具定义详情
- `POST /api/v1/tools/{tool_name}/test`：直接测试工具调用
- `GET /api/v1/skills`：查看已加载技能
- `GET /api/v1/orchestrator/agents`：查看可用专家 Agent
- `POST /api/v1/orchestrator/run`：发起多 Agent 协作任务

单 Agent 运行控制说明：

- `run` / `resume` 现在是后台执行语义，不会同步等待任务结束
- 任务是否完成，请通过 `status` 或 `trace` 轮询确认
- `pausing` 表示暂停请求已接收；如果当前 step 恰好完成并且任务直接结束，最终状态也可能是 `completed`
- 当前暂停语义是“步级暂停”：当前 step 结束后尽快暂停，不会强杀正在执行中的工具调用

示例（PowerShell）：

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/v1/tools | Select-Object -ExpandProperty Content
```

## 使用 Python 本地启动

如果你希望应用进程在宿主机运行，需要先确保 Postgres 和 Redis 已经可用，然后同步依赖：

```powershell
uv sync --extra dev
```

首次启动新库或清空数据库后，先执行迁移：

```powershell
uv run alembic upgrade head
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
