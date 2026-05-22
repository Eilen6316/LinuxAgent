# Plan C12：Existing approval migration

## 目标

把现有命令确认、文件 patch 确认、权限请求、wizard/resume 识别迁移到 C11 的
pending request 协议。迁移过程中不能降低 HITL 安全语义。

## 范围

- command approval 映射为 pending request。
- file patch approval 映射为 pending request。
- 现有 wizard/selector 若仍存在运行时入口，映射为 pending request。
- `/resume` 从 pending request type 识别待处理事项。
- audit 保留原有人类决策记录。
- 迁移期必须双跑兼容：legacy interrupt payload 和新 pending request 都能被 UI/resume
  正确处理；只有完成回归覆盖后才能删除旧路径。

## 不做

- 不改审批内容生成策略。
- 不把 approval 变成普通 chat input。
- 不删除旧兼容路径，直到测试确认新路径覆盖。
- 不在迁移期临时新增第二套 request type 命名。

## 实施步骤

1. 找到现有 interrupt payload type 和 resume 展示路径。
2. 对照 C11 映射表，为每类 payload 编写 request adapter。
3. 保留 legacy payload 读取路径，同时让新路径输出 pending request。
4. 更新 UI dispatcher，使 confirm/patch/wizard 都走 pending request。
5. 更新 resume 展示，从 request type 获取用户可见摘要。
6. 保留 audit decision event，与 request id 关联。
7. 在测试覆盖 legacy 与 pending request 双路径后，再移除多余兼容代码。

## 测试/验证

- 单元测试覆盖 command confirm request。
- 单元测试覆盖 file patch request。
- 单元测试覆盖 resume 展示 pending request。
- 单元测试覆盖 legacy payload 与 pending request 双路径一致。
- 回归测试覆盖拒绝/取消不会继续执行命令。

## 验收

- 所有现有人机确认都可用统一 request 表达。
- resume 不再靠零散 payload 字段猜测。
- 安全审批语义不回退。
- 旧 payload 在迁移窗口内不会导致 UI/resume 识别失败。

## 完成记录

- 2026-05-19：完成现有审批路径到 pending request 协议的迁移。
- 提交：`77f3031` (`runtime lifecycle: migrate pending approvals`)。
- 实施摘要：
  - 新增 `src/linuxagent/app/pending_requests.py`，集中处理 app 层 pending request
    中断摘要与恢复决策。
  - `GraphRuntime` 在 LangGraph interrupt 边界同时保留 legacy payload 和
    pending request 表达，迁移期双路径兼容。
  - `ui/interrupt_dispatcher.py` 接入 pending request dispatcher，命令确认、
    file patch、wizard/selector 和权限请求继续保留原 HITL 语义。
  - `pending_request.py` 补充 legacy payload adapter、interrupt mapping 和安全
    fallback。
- 验证：
  - `tests/unit/app/test_agent.py`
  - `tests/unit/graph/test_runtime.py`
  - `tests/unit/test_pending_request.py`
  - `tests/unit/ui/test_interrupt_dispatcher.py`
