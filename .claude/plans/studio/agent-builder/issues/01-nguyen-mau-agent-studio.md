# 01 — Nguyên mẫu: agent Studio chạy trong runner theo (công ty, phiên bản)

Status: needs-triage
Area: studio
Yêu cầu: không (nguyên mẫu đo đạc, chốt ADR B9-3 trước khi cắt runtime thật)

## Mục tiêu

Đo được rằng runner hiện có dựng và chạy một agent theo (công ty, phiên bản) trong giới hạn bộ nhớ của host, và khóa hai giả định thư viện vào test hợp đồng, trước khi ticket 03 dựng runtime thật. Nguyên mẫu chạy trên một nhánh thử, không tạo bảng, route hay migration nào.

## Việc cần làm

1. Dựng `StudioGraphSource` thử đọc một fixture JSON thay cho tài liệu phiên bản, trả graph chưa biên dịch, cache LRU có trần theo khóa `(tenant_id, agent_version_id, pinned_hash)`, `pinned_hash` lấy từ fixture như bản kê ghim (spec R3.1).
2. Dựng `StudioModelSelection` thử với một resolver giả, đặt nó trước bước `RunBudget` trong ngăn xếp middleware; xác nhận thứ tự bằng phép đo M2 (middleware đứng trước là lớp ngoài).
3. Thêm một agent con có `RunControl` thử, truyền ngân sách của cha xuống con.
4. Đo thời gian và bộ nhớ biên dịch ở 10 và 100 phiên bản; đo tiếp tục một lượt chạy ở một tiến trình thứ hai (resume). Ghi bảng số đo vào mục Quyết định của `spec.md`.
5. Thêm hai test hợp đồng thư viện vào repo: một cho langchain (đảo model qua `wrap_model_call` làm model mặc định nhận 0 lượt gọi), một cho deepagents (`SubAgentMiddleware` trên `create_agent` buộc con khai `tools`). Mỗi test đỏ nếu thư viện đổi hành vi.

## Tiêu chí chấp nhận

- [ ] Bảng số đo thời gian và bộ nhớ biên dịch ở 10 và 100 phiên bản có trong `spec.md`; sai nếu thiếu một cột đo.
- [ ] Nguyên mẫu tiếp tục một lượt chạy ở tiến trình thứ hai và trả đúng trạng thái; sai nếu resume mất checkpoint.
- [ ] Test hợp đồng langchain xanh và đỏ khi ép model mặc định nhận lượt gọi; sai nếu nó xanh cả hai chiều.
- [ ] Test hợp đồng deepagents xanh và đỏ khi con thiếu `tools` lại được cấp công cụ; sai nếu nó không bắt được thay đổi.
- [ ] Xong: `uv run pytest packages/python/dw_agent_runtime/tests/prototype` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:28-36`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`; spec: không.

## Comments

- 2026-10-24 (agent): vòng sửa thứ tư, lượt d: khóa cache của nguyên mẫu mang `pinned_hash` như runtime thật (spec R3.1; ADR-0117 (Accepted) quyết 5), vì bản Nháp của agent chạy được ở `simulate` dưới mã băm tạm và giữ id khi sửa (bước 1).
