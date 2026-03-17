# Task 04 — 模型服务层基础版（OpenAI 兼容接口接入）

**所属阶段**：Phase 1（第 1-2 个月）  
**交付标准**：Agent 可通过 OpenAI 兼容接口调用模型并替换 Task 02 的 mock 思考链路；主模型不可用时自动降级
**当前状态**：已完成（2026-03-17）

---

## 背景

模型服务层使用 **LiteLLM** 作为多模型统一适配层，对 Agent Runtime 提供标准化推理接口。v1 使用 OpenAI 兼容 API（可对接 OpenAI/OneAPI/vLLM 等兼容网关），安全过滤在调用前后各设一道关卡。Phase 1 实现基础接入与安全过滤；Phase 2 Task 09 完成智能路由三策略。

---

## 任务列表

### 1. LiteLLM Provider 封装（`src/model/provider.py`）
- [ ] 实现 `ModelProvider` 类，封装 LiteLLM 调用：
  - `async_completion(messages, model, tools, **kwargs)` — 异步调用，返回标准 ChatCompletion 响应
  - `async_stream_completion(messages, model, tools, **kwargs)` — 流式调用，返回 AsyncGenerator
- [ ] 通过 `pydantic-settings` 从环境变量加载各 Provider 的 API Key
  - `MODEL_API_KEY`、`MODEL_API_BASE`（对照 `.env.example`）
- [ ] 统一错误处理：将 LiteLLM 各 Provider 异常归一化为内部 `ModelError`（含 `provider`、`status_code`、`message` 字段）
- [ ] 内置 **重试逻辑**（使用 `tenacity`）：遇到 rate limit（429）或服务器错误（5xx）时指数退避重试，最多 3 次

### 2. 基础模型路由（`src/model/router.py`）
- [ ] Phase 1 实现**简化路由**（仅故障转移），Phase 2 Task 09 扩展三策略：
  ```python
  class BasicRouter:
      def __init__(self, primary: str, fallback: str):
          self.primary = primary
          self.fallback = fallback
      
      async def call(self, messages, tools, **kwargs):
          try:
              return await provider.async_completion(
                  messages, model=self.primary, tools=tools, **kwargs
              )
          except ModelError as e:
              if e.status_code in (429, 500, 502, 503):
                  logger.warning("Primary model failed, falling back", ...)
                  return await provider.async_completion(
                      messages, model=self.fallback, tools=tools, **kwargs
                  )
              raise
  ```
- [ ] 读取 `AgentConfig.model.primary` 和 `AgentConfig.model.fallback` 初始化路由器

### 3. 输入安全过滤（`src/model/safety.py`）
- [ ] 实现 `InputFilter.check(messages)` 方法：
  - **Prompt 注入检测**：使用规则匹配方式，检测常见注入模式（如 `ignore previous instructions`、`system:` overrides 等）
  - **敏感信息拦截**：使用正则表达式检测身份证号、银行卡号、手机号，拦截并替换为 `[REDACTED]`，防止敏感数据进入 LLM 上下文
  - 检测到注入风险时抛出 `SecurityError` 并记录告警日志

### 4. 输出安全过滤（`src/model/safety.py`）
- [ ] 实现 `OutputFilter.check(response)` 方法：
  - **有害内容检测**：调用 OpenAI Moderation API（或本地规则）检测有害输出
  - **幻觉检测（基础版）**：对响应中出现的关键数字/日期，与 `tool_results` 中返回的数据进行比对，差异过大时打 Warning 标记
  - 有害内容时拒绝输出，返回标准错误消息

### 5. Token 使用量追踪（`src/model/provider.py`）
- [ ] 从 LiteLLM 响应中提取 `usage`（`prompt_tokens`、`completion_tokens`、`total_tokens`）
- [ ] 写入 `task_steps.token_usage` 字段（JSONB）
- [ ] 实现 `TokenTracker.get_cost(model, usage)` — 基于 LiteLLM 内置价格表估算本次调用成本（美元）

### 6. 模型服务统一门面（`src/model/__init__.py`）
- [ ] 实现 `ModelService` 门面类，供 Runtime `think` 节点调用：
  ```python
  class ModelService:
      async def think(
          self,
          agent_config: AgentConfig,
          messages: list,
          tools: list,
          task_id: str,
          step_index: int,
      ) -> ModelResponse:
          # 1. InputFilter.check(messages)
          # 2. BasicRouter.call(messages, tools)
          # 3. OutputFilter.check(response)
          # 4. 写入 token_usage 到 task_steps
          # 5. 返回格式化的 ModelResponse
  ```

### 7. 配置（`src/config.py` 扩展）
- [ ] 新增 `ModelConfig` Pydantic 设置：
  ```python
  class ModelSettings(BaseSettings):
      model_api_key: str
      model_api_base: str = ""
      default_primary_model: str = "gpt-4o"
      default_fallback_model: str = "gpt-4o-mini"
      model_timeout_seconds: int = 60
      max_retries: int = 3
  ```

---

## 验收标准
- [ ] 调用 `ModelService.think()` 成功获取 LLM 响应，含 `tool_calls` 结构体
- [ ] 主模型模拟 503 错误时，自动切换到 Fallback 模型，整体调用不失败
- [ ] 包含身份证号的消息在输入过滤后被脱敏（替换为 `[REDACTED]`）
- [ ] 每次推理的 `token_usage` 正确写入数据库
- [ ] Runtime `think` 节点从 mock 适配器切换为 `ModelService` 后，Task 02 主流程回归测试通过

---

## 依赖关系
- **前置**：Task 01（项目初始化）、Task 02（Runtime 主干已落地）、Task 03（State Store，用于写入 token_usage）
- **后置**：Task 09（三策略路由扩展）

---

## 参考资料
- PRD 2.5.1：模型路由策略
- PRD 2.5.2：推理优化（Phase 1 仅实现基础接入）
- PRD 2.5.3：安全过滤
