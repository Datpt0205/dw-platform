# 04 — Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy có trần của gói

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, UL4

## Mục tiêu

Mọi cửa chạm model đi qua một kiểu có đo đòi lease, không cửa nào vòng qua hạn mức; giới hạn hành vi
(số bước, lời gọi model, lời gọi công cụ mỗi lượt chạy) là kẹp của giá trị trong phiên bản và Trần của
gói, và lượt quy trình chạm giới hạn số bước dừng sạch ở ranh giới kế tiếp với một dạng từ chối (spec R6). Đây là
phần của cổng E1 (V4.31); phần vòng agent của R6.3 (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`,
`recursion_limit` của subagent) ở ticket 06, thuộc làn trợ lý và lối ra W1b. Giới hạn thời gian theo gói (`max_run_seconds`)
là W2 cùng bên đọc của nó: hạn chót `deadline_at` của W1 là của workflow-engine và dùng trần mặc định 30 ngày khi
`limits.max_run_seconds` chưa có ở W1, không đọc số nào của gói (workflow-engine:R5.22; V4.14; Ngoài phạm vi của
spec).

## Việc cần làm

1. `RuntimeSeam` không còn lộ gateway thô, chat model trần, adapter embedding hay rerank; chỉ
   `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
   `metered_invoke` đòi lease; lane nạp tri thức đo embeddings với `purpose = 'ingestion'`, gắn
   workspace và người tải tài liệu. Hợp đồng import-linter: chỉ composition root import
   `RoutingModelGateway`, adapter embedding, rerank cụ thể. Test liệt kê field của `RuntimeSeam`: mọi
   field chạm model là kiểu có đo.
2. `RunLimits = kẹp(giá trị của phiên bản, Trần của gói)`, kiểu mà cả quy trình lẫn vòng agent (ticket 06) đọc;
   quy trình: `RunLimits.max_steps` tới bộ đếm bước theo lượt của wrapper nút
   bằng tiêm (workflow-engine:R4.20, ở workflow-engine/06, ticket chờ ticket này), không tới
   `recursion_limit`, vì `recursion_limit` đặt lại mỗi lần tiếp tục (đo trên LangGraph 1.2.11,
   ADR-0112 (Accepted) Context). Mọi vi phạm → `LimitExceededError(metric)` → run `failed`,
   `error.code = limit_exceeded`, không áp chính sách lỗi của node; audit `run.limit_stopped`. Middleware giới hạn
   của vòng agent và `recursion_limit` của subagent là ticket 06.

## Tiêu chí chấp nhận

- [ ] R6.1 (UL4): mọi field chạm model của `RuntimeSeam` là kiểu có đo; đặt một field thành gateway thô
      → test field đỏ.
- [ ] R6.2 (UL4): lease cạn, gọi thẳng gateway có cấu trúc, `metered_invoke`, chat model, embeddings,
      rerank, lane nạp → mỗi cửa từ chối `limit_exceeded` (test âm gọi thẳng từng cửa, không qua lớp đã
      chặn).
- [ ] R6.3: một Bước thử trong lượt quy trình, khai `on_error: continue`, gọi cửa có đo khi lease đã cạn và nhận
      `LimitExceededError` → run `failed` với `limit_exceeded`, Bước kế không chạy và chính sách lỗi của node không áp;
      bỏ phép bỏ qua chính sách lỗi cho `LimitExceededError` → lượt đi tiếp theo `continue`, test đỏ; giới hạn số bước
      theo lượt qua nhiều lần tiếp tục thử ở tiêu chí R4.20 của workflow-engine/06, trên `RunLimits` mà ticket này trả.
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
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo V4.14 của Đạt: `deadline_at` có từ W1 ở workflow-engine, với trần
  mặc định 30 ngày khi `limits.max_run_seconds` chưa có ở W1, nên Mục tiêu đổi lý do: giới hạn thời gian theo gói vẫn
  là W2 vì không bên nào ở W1 đọc nó, không phải vì hạn chót là W2. Ticket này không đổi việc cần làm và không thêm
  cạnh.
- 2026-10-25 (agent): bước 2 thôi nối số bước của quy trình vào `recursion_limit`: theo V4.26, trần của lượt
  quy trình là bộ đếm bước theo lượt của workflow-engine:R4.20, mà workflow-engine/06 dựng và nhận
  `RunLimits.max_steps` của ticket này bằng tiêm, vì `recursion_limit` đặt lại mỗi lần tiếp tục;
  `recursion_limit` vẫn là trần của vòng agent. Không thêm cạnh: workflow-engine/06 đã chờ ticket này.
- 2026-10-26 (agent): vòng 4, lượt h, theo V4.31: tách ticket. Ticket này giữ số và giữ R6.1, R6.2, phần quy trình
  của R6.3, R6.4 và UL4 (cổng E1); phần agent của bước 2 (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`,
  `recursion_limit` của subagent) và các ca agent của tiêu chí R6.3 dời sang ticket 06, nên gỡ cạnh
  04 <- agent-builder/03 (cạnh đó nằm ở ticket 06).
