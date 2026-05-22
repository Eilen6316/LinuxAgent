# Plan C15：Tool concurrency and resource locks

## 目标

建立工具并发模型：只读工具可以并发，写操作串行或按资源锁控制。并发能力由工具
metadata 表达，不能靠模型文案或 Python 关键词猜测。

## 范围

- 扩展工具 metadata：read-only/write、resource keys、network、parallel safe。
- executor 根据 metadata 决定并发批次和资源锁。
- UI 展示真实并发批次和每个子项状态。
- 失败时明确部分成功、部分失败、整体结果。

## 不做

- 不把危险写操作放进并发。
- 不让模型通过文字声明改变工具安全属性。
- 不改变 policy/sandbox 判定。

## 实施步骤

1. 盘点现有工具 metadata 和 parallel execution 入口。
2. 定义 capability/resource lock 字段。
3. 为只读工具批次执行补 parent work item。
4. 为写工具加串行或资源锁保护。
5. 将并发结果结构化返回给 planner/respond。

## 测试/验证

- 单元测试覆盖 read-only 并发批次。
- 单元测试覆盖同资源写操作串行。
- 单元测试覆盖一个子任务失败时其他结果仍可见。
- harness 覆盖并发 UI 事件。

## 验收

- 并发来自工具 metadata，不来自硬编码命令名。
- 写操作不会被错误并发。
- 用户能看到并发任务的每个子项。

## 完成记录

- 2026-05-19：完成工具并发与资源锁控制。
- 提交：`65bd494` (`runtime: add tool concurrency controls`)。
- 实施摘要：
  - 扩展 `tools/catalog.py` 和各 workspace/system/network/intelligence tool metadata，
    标注 read-only/write、parallel safety 与资源键。
  - `providers/base.py` 新增基于 metadata 的 tool call 调度：只读且资源不冲突的工具可
    并发，写操作或资源冲突工具串行执行。
  - provider/tool loop 保留 cancellation token、timeout、output budget、sandbox metadata
    和 typed runtime observer 传递。
  - UI prompt session 增加并发运行期间的输入处理保护。
- 验证：
  - `tests/unit/providers/test_base.py`
  - `tests/unit/ui/test_console.py`
