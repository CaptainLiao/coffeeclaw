# Task 10 — 可观测性基础（Observability）

**所属阶段**：Phase 2（第 3-4 个月）  
**交付标准**：提供完整的请求全链路追踪 (Trace)、结构化日志 (Log)、核心服务运行指标提取 (Metric)；可供 Prometheus 与 Grafana 直接读取展示

---

## 背景

在单体多 Agent 环境中，追踪一个请求为何失败/变慢，或者某个模型为何大量消耗 Token 都必须依靠完备的可观测性方案。Phase 2（v1 终态）要求在本地开发及测试服务器中初步搭建这一基础设施（Metrics + Tracing + Logging ）。

---

## 任务列表

### 1. Prometheus 指标采集（`src/observability/metrics.py`）
- [ ] 引入 `prometheus_client` 库，并在 FastAPI （`src/main.py`）启动时暴露出 `/metrics` 端点
- [ ] 定义并注入如下业务指标：
  - **Counter**: `agent_task_completed_total` (labels: `agent_id`, `status`=success/failed/escalated)
  - **Counter**: `model_token_usage_total` (labels: `model_name`, `type`=prompt/completion)
  - **Histogram**: `tool_execution_duration_seconds` (labels: `tool_name`)
  - **Counter**: `tool_execution_errors_total` (labels: `tool_name`, `error_type`)
  - **Gauge**: `docker_sandbox_pool_active` (监控沙箱并发使用率)

### 2. OpenTelemetry 链路追踪（`src/observability/tracing.py`）
- [ ] 配置 `opentelemetry-sdk`，针对 FastAPI、SQLAlchemy、Redis 分别注入 Auto-instrumentation
- [ ] 提供全局 `tracer`，在 Agent Runtime 中按以下 Span 粒度手动打点：
  - `agent_run`：一个 `thread_id` 开始直到结束的最外层 Span
    - 子 Span 1：`graph_sense`
    - 子 Span 2：`graph_think`（包裹实际的 LiteLLM api 请求子 Span）
    - 子 Span 3：`graph_act`（内部包含多个工具调用的子 Span `tool_invoke`）
    - 子 Span 4：`graph_reflect`
- [ ] **环境变量控制**：能够通过 `OTEL_EXPORTER_OTLP_ENDPOINT` 指向本地跑的 Jaeger 容器。如果没有配置，Trace 信息转去 console 或 Dev_Null

### 3. Log 与 Trace 绑定（`src/observability/logging.py` 增强）
- [ ] 对 Task 01 中的 `structlog` 配置进行补充
- [ ] 从 OpenTelemetry 当前上下文中获取 `trace_id` 和 `span_id`，利用 `structlog` 处理器的 processor 机制自动向每条 Log 增加字段
  ```json
  {"event": "Tool executed", "tool": "flight_search", "trace_id": "xxxxx", "span_id": "yyyy"}
  ```

### 4. 业务审计系统联调确认（Review）
- [ ] 确保 `Task 03` 中的 `tool_logs` 表和 `task_steps` 表的数据插入点能抓取到对应 Trace ID（作为附带的 `trace_id` 存入数据库外键或独立字段），打通数据侧和监控流

### 5. 搭建一体化观察环境（`deploy/docker/docker-compose.obs.yml`）
- [ ] 为了快速演示和本地排错，新建一个额外的 Compose 文件（只挂起可选基础设施组件）：
  - `prometheus`: 抓取 App 的 `http://app:8000/metrics`
  - `grafana`: 根据提前写好的 Dashboards JSON (存放在 `deploy/grafana/dashboards/` 目录下)，自动展示 P99 Agent 耗时等大盘
  - `jaeger` (all-in-one): 用于接收 OTLP trace 并在 16686 端口展示 UI

---

## 验收标准
- [ ] `docker-compose -f docker-compose.yml -f docker-compose.obs.yml up -d` 能把基础服务+三个监控中间件全部拉起
- [ ] 打开 Grafana 地址，能看到 Agent 处理任务的成功率曲线、模型消耗 Token 柱状图
- [ ] 发起调用后产生错误，打开 Jaeger 能看到具体 Span 瀑布图，看到哪一步（是 LLM 等太久，还是 Tool 执行错）崩溃，并且 Log 带相同的 `trace_id`
- [ ] 所有代码均不强依赖监控端存在（即只起原本的 `docker-compose.yml` 也不应当崩溃）

---

## 依赖关系
- **前置**：Task 01（FastAPI 路由与日志就绪），Task 02/04/05（各模块核心代码存在，可打 Span 点）
- **后置**：全面满足 v1 及之后环境部署上线需求

---

## 参考资料
- PRD 第三章：可观测性设计（四维体系及核心监控指标）
- 社区最佳实践库：OpenTelemetry Python
