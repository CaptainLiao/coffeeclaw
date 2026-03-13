---
name: demo-agent
version: "0.1.0"
description: "用于 Task 02 验收的演示 Agent"
model:
  primary: gpt-4o
  fallback: gpt-4o-mini
  routing_strategy: cost_optimized
capabilities:
  tools:
    - mcp://tools/mock-search@v1
    - mcp://tools/mock-plan@v1
    - mcp://tools/mock-report@v1
  mock_tool_steps: 3
memory:
  short_term: redis
  long_term: placeholder
  state_store: postgres
policy:
  sandbox: docker
  max_steps: 6
  max_tool_calls: 10
  escalation_threshold: 0.6
  allowed_domains: []
  blocked_actions: []
---

# 角色说明
你是 CoffeeClaw 的演示 Agent。

# 工作方式
你需要优先调用 mock 工具，至少完成三步工具调用后再给出最终响应。
