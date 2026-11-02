# 03 — Spike: model proxy với từng nhà cung cấp thật

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: không (spike đo đạc; phần cần khóa thật, tách khỏi ticket 01 ngày 2/11/2026)

## Mục tiêu

Trên stack và transport của ticket 01, đo bảy nhà cung cấp mà một máy không có khóa không đo được: OpenAI, Azure OpenAI, Anthropic, Gemini AI Studio, Bedrock khóa tĩnh, vLLM và FPT AI Factory (FOG-19). Đo thêm usage mà LiteLLM báo so với usage mà nhà cung cấp tính, và prompt cache giữa hai công ty (`.claude/plans/studio/discovery/issues/17-litellm-model-proxy.md`, mục Phép đo quyết định). Ticket thuộc Chờ Đạt 21: cần một khóa thử cho mỗi nhà cung cấp và một máy chạy vLLM có GPU. Không khóa nào được vào môi trường của `model-proxy` hay vào repo.

## Việc cần làm

1. Khóa chỉ nằm trong môi trường của tiến trình test trên host, dưới tên `DW_SPIKE_<PROVIDER>_*`:
    - Azure: khóa, endpoint và deployment;
    - Bedrock: cặp khóa tĩnh và vùng;
    - vLLM và FPT AI Factory: khóa và `api_base`.

    Khóa chỉ tới `model-proxy` qua transport của ticket 01, từng lượt gọi. `egress-standin` chỉ cho ra internet tới đúng các máy của bảy nhà cung cấp này.
2. Với mỗi nhà cung cấp, đo:
    - streaming có usage;
    - gọi công cụ;
    - `response_format`, cả `json_object` lẫn `json_schema`;
    - ánh xạ lỗi: 401 khi khóa sai, 400, và 429 nếu tạo ra được;
    - usage LiteLLM báo so với usage nhà cung cấp tính: ghi độ lệch cho từng nhà cung cấp, chưa đặt ngưỡng;
    - token cache và token reasoning, nếu nhà cung cấp có.
3. Bedrock khóa tĩnh cần các tham số `aws_*` mà ticket 01 chặn. Đo xem có cách nào cho khóa đi qua mà không mở lại các tham số đó. Không có cách thì dừng và ghi đề xuất sửa ADR-0118 (Accepted) quyết định 8 vào Comments; không tự nới cấu hình.
4. Prompt cache trên OpenAI: dùng khóa A, rồi khóa B, với cùng một prompt dài ít nhất 1024 token. Ghi `cached_tokens` của lời gọi B và ghi `cache_salt` có được chuyển tiếp không.
5. Giới hạn chi phí và dữ liệu:
    - mỗi lời gọi có `max_tokens` không quá 64, và cả lượt không quá 300 lời gọi;
    - chỉ dùng nội dung tổng hợp, không dữ liệu cá nhân hay dữ liệu của công ty nào, vì xử lý ở nước ngoài là chuyển dữ liệu (ADR-0123 (Accepted)).
6. Ghi bảng số đo vào Comments, và một dòng Quyết định vào `spec.md`.

## Tiêu chí chấp nhận

- [ ] Bảng số đo có trong Comments, và mỗi ô của bảy nhà cung cấp có giá trị đo hoặc "không hỗ trợ" kèm đầu ra; sai nếu thiếu một nhà cung cấp.
- [ ] Không có khóa thật nào trong `docker logs` của `model-proxy` và `egress-standin`, hay trong callback, ở cả bốn dạng của ticket 01; sai nếu bộ quét không tìm thấy một canary trồng sẵn.
- [ ] Thiếu một biến `DW_SPIKE_*` thì test của nhà cung cấp tương ứng đỏ và nêu tên nhà cung cấp đó, không bỏ qua.
- [ ] Xong: `uv run python -m pytest infra/spikes/model-proxy/tests -k litellm_providers` xanh.

## Nguồn

- `uv.lock:2741-2742`; `uv.lock:1736-1737`; spec: không.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): tách từ ticket 01 theo gate `checking-plan-readiness` (HIGH 2), vì sáu nhà cung cấp cần khóa thật và vLLM cần GPU (Chờ Đạt 21). Ticket chưa qua gate. Nếu sai thì: gộp lại vào ticket 01.
