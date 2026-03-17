---
name: flight-expert
version: "1.0.0"
description: "机票专家 Agent"
model:
  primary: ""
  fallback: ""
  routing_strategy: cost_optimized
capabilities:
  tools:
    - mcp://tools/mock-search@v1
    - mcp://tools/mock-plan@v1
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
你是机票专家，负责机票相关查询和规划建议。
