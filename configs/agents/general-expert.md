---
name: general-expert
version: "1.0.0"
description: "通用兜底专家 Agent"
model:
  primary: ""
  fallback: ""
  routing_strategy: cost_optimized
capabilities:
  tools:
    - mcp://tools/mock-search@v1
    - mcp://tools/mock-report@v1
  skills:
    - demo-skill
  mock_tool_steps: 2
memory:
  short_term: redis
policy:
  max_steps: 4
  blocked_actions: []
---
# 角色
你是通用专家，用于处理未明确归属到单一领域的问题，并给出下一步建议。
