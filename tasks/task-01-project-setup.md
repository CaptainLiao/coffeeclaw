# Task 01 — 项目初始化与本地开发环境

**所属阶段**：Phase 1（第 1-2 周）  
**交付标准**：本地一条命令可启动完整开发环境，所有基础服务健康运行

---

## 背景

CoffeeClaw 是企业级 AI Agent 开发平台，v1 采用 Python + FastAPI + LangGraph 作为核心技术栈。本任务完成所有基础脚手架搭建，为后续模块开发提供标准化环境。

> 当前仓库在 PRD 业务目录之外，额外采用了薄 `src/core/`、`src/infrastructure/`、`src/services/` 作为共享支撑层：`core` 负责应用装配与配置，`infrastructure` 负责外部资源初始化，`services` 当前仅承载系统级健康检查编排。

---

## 任务列表

### 1. 项目结构初始化
- [x] 按照 PRD 第五章定义的目录结构创建完整骨架
  ```
  coffeeclaw/
  ├── src/
  │   ├── __init__.py
  │   ├── main.py
  │   ├── runtime/
  │   ├── orchestrator/
  │   ├── workflow/
  │   ├── tools/
  │   ├── memory/
  │   ├── model/
  │   ├── observability/
  │   └── api/
  ├── configs/
  │   ├── agents/
  │   ├── skills/
  │   └── tools/
  ├── tests/
  │   ├── unit/
  │   └── integration/
  ├── deploy/
  │   └── docker/
  └── docs/
  ```
- [x] 在所有 Python 包目录下创建 `__init__.py`
- [x] 创建各目录的 `.gitkeep` 占位文件（如 `configs/agents/`、`configs/skills/`）

### 2. Python 项目配置
- [x] 创建 `pyproject.toml`，使用 `uv` 或 `poetry` 管理依赖
- [x] 核心依赖（v1 技术栈）：
  ```toml
  [project]
  name = "coffeeclaw"
  version = "0.1.0"
  requires-python = ">=3.11"
  
  dependencies = [
      "fastapi>=0.115",
      "uvicorn[standard]>=0.30",
      "langgraph>=0.2",
      "langgraph-checkpoint-postgres",
      "litellm>=1.40",
      "redis>=5.0",
      "asyncpg>=0.29",
      "psycopg[binary]>=3.1",
      "sqlalchemy[asyncio]>=2.0",
      "pydantic>=2.7",
      "pydantic-settings>=2.3",
      "python-dotenv>=1.0",
      "structlog>=24.0",
      "opentelemetry-sdk>=1.25",
      "prometheus-client>=0.20",
      "docker>=7.0",
      "pyyaml>=6.0",
      "tenacity>=8.0",
  ]
  
  [project.optional-dependencies]
  dev = [
      "pytest>=8.0",
      "pytest-asyncio>=0.23",
      "httpx>=0.27",
      "ruff>=0.5",
      "mypy>=1.10",
  ]
  ```
- [x] 创建 `.env.example`，列出所有必需的环境变量（不含真实值）：
  ```env
  # OpenAI-compatible Model Gateway
  MODEL_API_KEY=
  MODEL_API_BASE=
  
  # Database
  SQL_DSN=postgresql+asyncpg://user:pass@localhost:5432/coffeeclaw
  REDIS_URL=redis://localhost:6379/0
  
  # App
  APP_ENV=development
  LOG_LEVEL=INFO
  
  # Agent Defaults
  DEFAULT_PRIMARY_MODEL=gpt-4o
  DEFAULT_FALLBACK_MODEL=gpt-4o-mini
  ```
- [x] 创建 `src/config.py`，使用 `pydantic-settings` 统一加载配置

### 3. FastAPI 应用入口
- [x] 创建 `src/main.py`，包含：
  - FastAPI 实例初始化
  - 生命周期事件（启动时连接 DB/Redis，关闭时优雅断开）
  - 挂载路由（来自 `src/api/routes.py`）
  - 挂载 CORS 中间件
  - 挂载全局异常处理器
  - 健康检查端点 `GET /health`，检查 Postgres、Redis 连通性
- [x] 创建 `src/api/schemas.py`：通用 Pydantic 响应模型（`SuccessResponse`、`ErrorResponse`）
- [x] 创建 `src/api/routes.py`：空路由骨架，供后续任务填充

### 4. Docker 本地开发环境
- [x] 创建 `docker-compose.yml`（项目根目录），包含：
  - **postgres**：PostgreSQL 16，挂载 `./deploy/docker/init.sql` 初始化数据库 Schema
  - **redis**：Redis 7.0 Alpine，开启 AOF 持久化
  - **app**：CoffeeClaw 本体（开发模式，挂载代码目录，热重载）
- [x] 创建 `Dockerfile`（多阶段构建）：
  - `base`：Python 3.11 slim + 依赖安装
  - `dev`：挂载源码，使用 `uvicorn --reload`
  - `prod`：最小镜像（后续 Phase 3 使用）
- [x] 创建 `deploy/docker/init.sql`，包含 PRD 2.4.3 节定义的核心表：
  - `agents`（Agent 实例表）
  - `tasks`（任务表）
  - `task_steps`（执行步骤表）
  - `tool_logs`（工具调用审计日志）

### 5. 代码质量与 CI 配置
- [x] 创建 `ruff.toml`（或 `pyproject.toml` 中 `[tool.ruff]` 节），配置 lint 规则
- [x] 创建 `mypy.ini` 或 `[tool.mypy]` 节，开启严格类型检查
- [x] 创建 `.github/workflows/ci.yml`，包含：
  - `ruff check` 代码风格检查
  - `mypy` 类型检查
  - `pytest` 单元测试（含覆盖率报告）

### 6. 基础日志配置
- [x] 创建 `src/observability/__init__.py` 与 `src/observability/logging.py`
- [x] 使用 `structlog` 配置结构化日志，输出 JSON 格式
- [x] 在 FastAPI 的请求中间件中注入 `request_id`，并传递到所有日志

---

## 验收标准
- [x] `docker compose up -d` 一键启动，无报错
- [x] `GET http://localhost:8000/health` 返回 `{"status": "ok", "db": true, "redis": true}`
- [x] `GET http://localhost:8000/docs` 可打开 Swagger UI
- [x] `pytest tests/` 通过所有初始测试（至少包含健康检查路由测试）
- [x] `ruff check src/` 无 lint 错误

---

## 依赖关系
- **前置**：无
- **后置**：Task 02（Agent Runtime）、Task 03（Memory）、Task 04（模型服务）、Task 05（工具系统）

---

## 参考资料
- PRD 第五章：项目结构
- PRD 4.1 / 4.2 / 4.3：技术选型
- PRD 2.4.3：核心数据库 Schema
