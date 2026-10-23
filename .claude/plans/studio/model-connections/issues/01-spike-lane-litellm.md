# 01 — Spike: model proxy LiteLLM theo nhà cung cấp và tiêm khóa ở transport

Status: needs-triage
Area: studio
Yêu cầu: không (spike đo đạc trước khi W2 dựng model proxy thật theo ADR BYOM, D8 và D13)

## Mục tiêu

Đo được rằng một model proxy LiteLLM không trạng thái, ghim theo digest, dịch được lời gọi tới từng nhà cung cấp mà không lưu khóa, với khóa tiêm ở transport mỗi lượt; kết quả chốt cấu hình và bản ghim trước khi W2 dựng service thật (ADR-0118 (Accepted), D8, D13). Spike chạy trên một nhánh thử, không tạo bảng, route hay migration nào.

## Việc cần làm

1. Dựng model proxy từ một wheel LiteLLM 1.106.1 ghim băm (`--require-hashes`; một bản mới chỉ dùng sau 14 ngày và một lần kiểm advisory, ADR-0118 (Accepted)), không database, không biến provider trong môi trường, không cache hay callback; smokescreen đặt trước model proxy.
2. Đo từng nhà cung cấp: OpenAI, Azure, Anthropic, Gemini AI Studio, Bedrock khóa tĩnh, vLLM, Ollama, FPT AI Factory — streaming có usage, gọi công cụ, `response_format`, và ánh xạ lỗi của mỗi nhà cung cấp.
3. Dựng transport `httpx2` trên `openai` 3.14.1 tiêm khóa vào request mỗi lượt, không qua `extra_body` (để khóa không lọt vào payload callback như phép đo M5).
4. Ghi báo cáo từng mục của B9-8.6 vào mục Quyết định của `spec.md`, và kết luận một model proxy hay hai (dựa trên gateway có sẵn của người đặt yêu cầu, O6/F7).

## Tiêu chí chấp nhận

- [ ] Báo cáo từng mục của B9-8.6 (streaming usage, công cụ, `response_format`, Bedrock, ánh xạ lỗi) có trong `spec.md`; sai nếu thiếu một nhà cung cấp.
- [ ] Test hợp đồng: gọi model proxy thiếu khóa trả 401 của nhà cung cấp; sai nếu model proxy tự điền khóa từ môi trường.
- [ ] Test hợp đồng: tham số bị cấm gửi tới model proxy bị từ chối; sai nếu model proxy chuyển tiếp nguyên trạng.
- [ ] Nhật ký của model proxy không chứa khóa trong `serialized` và `invocation_params`; sai nếu khóa xuất hiện ở bất kỳ payload nào.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/spike -k litellm_lane` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/chat_model.py:33`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:76`; spec: không.

## Comments

- 2026-10-23 (agent): đổi "lane LiteLLM" thành model proxy theo glossary (phát hiện kiểm nhất quán ngày 23/10/2026); tên tệp giữ nguyên. Đạt chấp nhận ADR-0118 (Accepted) ngày 23/10/2026: LiteLLM ghim 1.106.1 theo luật 14 ngày và kiểm advisory (bước 1).
