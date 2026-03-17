---
name: demo-skill
version: "1.0.0"
description: "演示技能：先检索，再规划，最后输出总结。"
require_tools:
  - mock-search
  - mock-plan
  - mock-report
---

## SOP

1. 先调用检索类工具收集输入相关事实。
2. 再调用规划工具形成步骤化方案。
3. 最后调用报告工具归纳输出，确保结论与工具结果一致。
