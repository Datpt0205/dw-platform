# 06 — Giới hạn hành vi của vòng agent: lời gọi model, lời gọi công cụ và recursion_limit của subagent

Status: needs-triage
Blocked by: 04, .claude/plans/studio/agent-builder/issues/03-runtime-agent.md
Area: studio
Yêu cầu: R6.3, UL13

## Mục tiêu

Một lượt chạy agent dừng sạch ở ranh giới kế tiếp với `limit_exceeded` khi chạm số lời gọi model, số lời gọi công cụ
hay độ sâu đệ quy mà `RunLimits` của ticket 04 kẹp theo Trần của gói, kể cả trong subagent biên dịch sẵn, và chính
sách lỗi của node không áp (spec R6.3, UL13). Đây là phần agent tách khỏi ticket 04 (V4.31): nó thuộc làn trợ lý và lối
ra W1b, không thuộc lối ra W1a, nên không ticket W1a nào chờ nó.

## Việc cần làm

1. Vòng agent của agent-builder/03 đọc `RunLimits` của ticket 04 (không tự kẹp lại):
   `ModelCallLimitMiddleware(run_limit=RunLimits.max_model_calls, exit_behavior="error")` và
   `ToolCallLimitMiddleware(run_limit=RunLimits.max_tool_calls, exit_behavior="error")` vào ngăn xếp middleware ở chỗ
   mà agent-builder/03 giữ thứ tự (ADR-0117 (Accepted) quyết 5); ticket này không đổi thứ tự của `ResidencyGate` và
   `LimitsMiddleware` (spec R6.5).
2. `recursion_limit` truyền ở mọi lần gọi vòng agent và gán lại cho mỗi subagent `create_deep_agent` biên dịch sẵn, vì
   subagent biên dịch sẵn không nhận cấu hình của lượt gọi cha; trước khi viết, chạy thử trên phiên bản LangGraph và
   deepagents đang ghim và ghi vào Comments subagent có nhận `recursion_limit` của cha hay không (failure-modes #4).
3. Vi phạm ở vòng agent → `LimitExceededError(metric)` như ticket 04: run `failed`, `error.code = limit_exceeded`,
   không áp chính sách lỗi của node; audit `run.limit_stopped` qua cùng đường ticket 04 ghi.
4. Test trong `packages/python/dw_agent_runtime/tests/`: model giả trả lời gọi công cụ mãi; một lượt có hai lời gọi
   công cụ song song khi chỉ còn chỗ cho một; một subagent đệ quy.

## Tiêu chí chấp nhận

- [ ] R6.3 (UL13): agent với `max_tool_calls_per_run` 3 và model giả gọi công cụ mãi → lời gọi công cụ thứ tư không
      chạy, run `failed` với `limit_exceeded`, audit `run.limit_stopped`; gỡ `ToolCallLimitMiddleware` khỏi ngăn xếp →
      lời gọi thứ tư chạy, test đỏ.
- [ ] R6.3 (UL13): còn chỗ cho một lời gọi công cụ mà model trả hai lời gọi song song → dừng sạch ở ranh giới kế tiếp,
      lời gọi thứ hai không chạy, run `failed` với `limit_exceeded`.
- [ ] R6.3: chạm `max_model_calls_per_run` → dừng `limit_exceeded`, không hạ ngầm sang model rẻ hơn; gỡ
      `ModelCallLimitMiddleware` → test đỏ.
- [ ] R6.3: subagent `create_deep_agent` đệ quy vượt `recursion_limit` của lượt → dừng `limit_exceeded`; bỏ phép gán lại
      `recursion_limit` cho subagent → subagent chạy quá giới hạn, test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:207-209`; spec: R6.3 (ngăn xếp
  middleware của vòng agent hôm nay có trần tiền `RunBudgetMiddleware` và `recursion_limit`, không trần số lời gọi).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:193-197`; spec: R6.3
  (`recursion_limit` truyền ở lời gọi của runner).
- ADR-0112 (Accepted) Context (`recursion_limit` đặt lại mỗi lần tiếp tục, đo trên LangGraph 1.2.11); ADR-0121 (Accepted)
  quyết 9; spec: R6.3 (đọc `RunLimits` mà ticket 04 kẹp theo R6.4).

## Comments

- 2026-10-26 (agent): tách từ ticket 04 theo V4.31 (mục C của lượt h): phần agent của bước 2 và các ca agent của tiêu
  chí R6.3 dời về đây, cạnh tới agent-builder/03 dời theo; R6.3 ở dòng Yêu cầu của cả hai ticket, mỗi ticket một nửa
  (quy trình ở 04, agent ở đây), UL13 cùng ticket 03; không mã nào đổi số.
