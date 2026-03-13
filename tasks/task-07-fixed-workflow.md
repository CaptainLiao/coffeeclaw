# Task 07 — 固定工作流引擎

**所属阶段**：Phase 2（第 3-4 个月）  
**交付标准**：支持定义确定性的业务状态流程（如审批流），可处理人工中断与恢复，可嵌套调用大模型 Agent 解决异常

---

## 背景

Agent 的非确定性并不适合所有业务。有些关键流程（如退款、审批）需要严格按预设步骤执行。通过复用 LangGraph 基础设施，CoffeeClaw 的工作流引擎提供确定性的节点流转，并原生支持人工干预中断。

---

## 任务列表

### 1. 工作流基类（`src/workflow/base.py`）
- [ ] 定义通用的 `WorkflowState(TypedDict)` 基类：
  ```python
  class WorkflowState(TypedDict):
      workflow_id: str
      input_data: dict
      context: dict        # 工作流各节点的中间产物
      status: str          # running / pending_approval / completed / failed
      error: str | None
  ```
- [ ] 封装基础图构建工具 `BaseWorkflow`，要求子类提供节点实现和流转连接逻辑

### 2. 工作流定义（`src/workflow/graphs.py`）
- [ ] 实现示例工作流 `build_refund_workflow()`，包括如下确定性节点：
  - `query_order_node`：查询订单详情（模拟 API 或简单函数）
  - `check_rules_node`：核实验证规则
  - `manual_approval_node`：人工审批节点（空转或单纯记录状态）
  - `execute_refund_node`：执行资金退回（模拟）
  - `notify_user_node`：下发通知
- [ ] 构建节点连边，并提供条件路由逻辑（如基于金额大于 1000 跳转审批，否则自动退款）

### 3. 人工审批挂起机制（`src/workflow/graphs.py`）
- [ ] 编译图时注入 Postgres Checkpointer
- [ ] 使用 LangGraph 的 `interrupt_before` 功能定位并拦截人工节点：
  ```python
  graph.compile(checkpointer=postgres_saver, interrupt_before=["manual_approval"])
  ```
- [ ] 提供查询挂起状态的方法（判断能否/是否需要恢复提供外部输入）

### 4. Agent 协作嵌入（Agent in Workflow）
- [ ] 在 `check_rules_node` 模拟一条异常路径（如：找不到规则说明）
- [ ] 实现：将异常分支路由给独立的 `service_expert` Agent（作为工作流的内部节点调用 Task 02 的 `build_agent_graph` 产物）
- [ ] Agent 执行返回修正数据后，重返工作流主线

### 5. 生命周期与 API（`src/api/routes.py` 扩展）
- [ ] `POST /workflows/refund/start` — 创建实例并触发首节点
- [ ] `GET /workflows/{workflow_id}/status` — 轮询工作流最新状态、挂起原因
- [ ] `POST /workflows/{workflow_id}/approve` — 提交人工审批结果并恢复图继续运行：
  ```python
  # 恢复执行时可注入审批表单决议
  graph.update_state(config, {"context": {"approval_decision": "approved"}})
  # 继续跑
  graph.invoke(None, config)
  ```

---

## 验收标准
- [ ] `refund_workflow` 创建后能自动流转完非挂起节点
- [ ] 面临需审批情景，工作流暂停，API `status` 查询返回 `pending_approval`
- [ ] 调用 `/approve` API 后，工作流从挂起点继续跑，最终变成 `completed`
- [ ] 所有状态转换利用 `Task 03` 搭建的 Postgres Saver 正确实现，服务器重启不丢失中间上下文

---

## 依赖关系
- **前置**：Task 02（Checkpoint 与 LangGraph 基础就绪）
- **后置**：无

---

## 参考资料
- PRD 2.2.2：固定工作流引擎
- LangGraph 官方文档（中断与时间旅行相关）
