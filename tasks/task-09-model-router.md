# Task 09 — 模型智能路由策略

**所属阶段**：Phase 2（第 3-4 个月）  
**交付标准**：实现三种动态模型路由策略（cost_optimized / quality_first / latency_first），支持基于错误率和延迟的熔断降级机制

---

## 背景

Phase 1 中的模型服务（Task 04）仅支持基础的 Fallback 容错逻辑。为了平衡大规模运行 Agent 的成本与效果，需要引入智能路由器。不同的 Agent 或不同复杂度的任务，可配置不同的路由策略，由路由器在运行时动态分配最匹配的模型端点。

---

## 任务列表

### 1. 完善模型注册与健康检查（`src/model/registry.py`）
- [ ] 维护内存字典（或短连 Redis）缓存各个模型 Provider 的健康状态：
  - 最近 1 分钟平均延迟
  - 错误率计数器（窗口大小为 5 分钟）
- [ ] 后台异步微小探针 (Health Check) 任务：给主流模型发极短探测 prompt，计算 `latency_ms`
- [ ] 探针周期、统计窗口、错误率阈值改为配置项，避免硬编码（例如 `model_probe_interval_seconds`、`model_health_window_seconds`）

### 2. 路由策略工厂（`src/model/router.py`）
- [ ] 废弃 / 重构 Task 04 的 `BasicRouter`，改为 `SmartRouter` 类
- [ ] 实现 `quality_first` 策略：
  - 强制使用声明为最强性能的 `primary` 模型（如 gpt-4o 或 claude-3.5-sonnet）
  - 获取失败后才 fallback 到 `fallback` 模型
- [ ] 实现 `cost_optimized` 策略：
  - **动态分类**：拦截请求并判断。如果是查询类、闲聊类的简单请求（通过极短正则或文本长度判定），直接路由到 `fallback` / 本地轻量模型
  - 仅带复杂推理需求（比如 `tool_calls` 较多或系统标记由于重试再次进来）时自动升级到 `primary`
- [ ] 实现 `latency_first` 策略：
  - 读取健康检查记录
  - 直接选择最近 1 分钟内延迟最小且未触发熔断的可用模型
- [ ] 获取 `AgentConfig.model.routing_strategy` 并分配到对应工厂类

### 3. 熔断与限流机制（`src/model/router.py`）
- [ ] `CircuitBreaker` 熔断器：
  - 针对某个具体模型（如 gpt-4o），如果在配置窗口内连续多次 5xx 错误，或平均延迟超过配置阈值，触发 `OPEN` 状态
  - 处于 `OPEN` 状态的模型直接跳过尝试，快速失败路由给下一个顺位
  - 每隔配置时间转为 `HALF_OPEN`，放出少量流量试探。成功则 `CLOSED`
- [ ] `RateLimiter`（基于 Redis + Lua 脚本 或 token bucket）：
  - 给模型设置并发度上限或分钟 QPS 上限，防止触发服务商的并发限制账单

### 4. API 接口与诊断（`src/api/routes.py` 扩展）
- [ ] `GET /system/models/health` — 查看各模型当前的健康度、延迟统计与熔断状态
- [ ] `GET /system/models/metrics` — 暴露简单的接口，供 Task 10 的 Prometheus 拉取转换

---

## 验收标准
- [ ] Agent A 配置为 `cost_optimized`，执行常见打招呼问题时被路由给了小模型，执行复杂数学规划或预定被路由给了大模型
- [ ] Agent B 配置为 `latency_first`，主大模型（通过中间代理模拟 5000ms 延迟）被探测到高延迟，路由器自动切换请求到副模型
- [ ] 模拟触发某个 provider 连续 5 次故障后，接口直接在 10ms 内抛出熔断 fallback（而非每次重新死等重试拉高整体耗时）
- [ ] 所有路由决策写入 `task_steps` 中的新列或放入 `result.metadata` 方便后续追溯

---

## 依赖关系
- **前置**：Task 04（底层 LiteLLM Provider 已存在）
- **后置**：无

---

## 参考资料
- PRD 2.5.1：模型路由器设计
- PRD 2.5.1：容错机制（熔断与故障转移）
