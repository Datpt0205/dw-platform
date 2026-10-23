# 04 — Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy có trần của gói

Status: needs-triage
Blocked by: 03, .claude/plans/studio/agent-builder/issues/03-runtime-agent.md, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, UL4

## Mục tiêu

Mọi cửa chạm model đi qua một kiểu có đo đòi lease, không cửa nào vòng qua hạn mức; giới hạn hành vi
(số bước, lời gọi model, lời gọi công cụ mỗi lượt chạy) là kẹp của giá trị trong phiên bản và Trần của
gói, dừng sạch ở ranh giới kế tiếp với một dạng từ chối (spec R6). Giới hạn thời gian `max_run_seconds`
là W2, vì hạn chót bền của workflow-engine là W2.

## Việc cần làm

1. `RuntimeSeam` không còn lộ gateway thô, chat model trần, adapter embedding hay rerank; chỉ
   `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
   `metered_invoke` đòi lease; lane nạp tri thức đo embeddings với `purpose = 'ingestion'`, gắn
   workspace và người tải tài liệu. Hợp đồng import-linter: chỉ composition root import
   `RoutingModelGateway`, adapter embedding, rerank cụ thể. Test liệt kê field của `RuntimeSeam`: mọi
   field chạm model là kiểu có đo.
2. `RunLimits = kẹp(giá trị của phiên bản, Trần của gói)`; agent: `ModelCallLimitMiddleware(run_limit, exit_behavior="error")`,
   `ToolCallLimitMiddleware(run_limit, exit_behavior="error")`, `recursion_limit` truyền mọi lần gọi và
   gán lại cho subagent biên dịch sẵn; quy trình: số bước → `recursion_limit`. Mọi vi phạm →
   `LimitExceededError(metric)` → run `failed`, `error.code = limit_exceeded`, không áp chính sách lỗi của
   node; audit `run.limit_stopped`.

## Tiêu chí chấp nhận

- [ ] R6.1 (UL4): mọi field chạm model của `RuntimeSeam` là kiểu có đo; đặt một field thành gateway thô
      → test field đỏ.
- [ ] R6.2 (UL4): lease cạn, gọi thẳng gateway có cấu trúc, `metered_invoke`, chat model, embeddings,
      rerank, lane nạp → mỗi cửa từ chối `limit_exceeded` (test âm gọi thẳng từng cửa, không qua lớp đã
      chặn).
- [ ] R6.3: lượt chạy chạm giới hạn số bước hay số lời gọi công cụ (kẹp bởi gói) → dừng ở ranh giới kế
      tiếp `limit_exceeded`, không áp chính sách lỗi của node; subagent `create_deep_agent` không gán
      lại `recursion_limit` → test đỏ; giới hạn công cụ với lời gọi song song dừng sạch.
- [ ] R6.4: giá trị hành vi trong phiên bản cao hơn Trần của gói → bị kẹp về Trần của gói lúc chạy.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/bootstrap/container.py:104`; spec: R6.1 (`RuntimeSeam.gateway` lộ gateway thô).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:203`; spec: R6.2
  (`metered_invoke` không trần hôm nay); ADR-0121 (Accepted) quyết 4, 9.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 07, 10, cộng phần hạn mức ở executor của B8b
  tools-and-skills 08. Cùng helper kiểm soát rồi hạn mức với cửa đóng băng của agent-lifecycle.
- 2026-10-23 (agent): bỏ `max_run_seconds` khỏi W1 (phát hiện H:usage-and-limits/04~workflow-engine, ghi ở
  Ngoài phạm vi của spec).
