# 17 — Model proxy LiteLLM và gateway: usage theo nhà cung cấp, tiêm khóa từng lượt gọi, trần token

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-19 `litellm-behaviour`, FOG-21 `openai-transport`, FOG-20 `max-tokens`, FOG-22 `embed-rerank-usage`

## Câu hỏi

1. LiteLLM theo từng nhà cung cấp: usage khi stream; token đọc và ghi cache, token reasoning; báo chi phí; lời gọi công
   cụ; `response_format` có đi qua không; từ khóa JSON Schema nào qua (`additionalProperties: false`, `anyOf` có null,
   enum, format); ánh xạ lỗi (FOG-19)?
2. An toàn khóa: thiếu khóa thì trả 401 và không lấy khóa từ biến môi trường; `api_base` bị regex có neo từ chối ở mọi
   vị trí lồng nhau; khóa tiêm theo lượt gọi mà không lưu lại; proxy ra ngoài được tôn trọng; `cache_salt` được chuyển
   tiếp; khóa phân vùng prompt cache là gì (FOG-19)?
3. Một transport httpx2 có tiêm được `api_key` và `api_base` vào thân request cho `openai` 3.14.1 (`uv.lock:2718`) mà
   không làm hỏng streaming không (FOG-21)?
4. Middleware hạn mức có đặt được `max_tokens` hay `max_output_tokens` cho từng lời gọi trên đường agent của langchain
   1.4.1 (Responses API) để trần ràng buộc ở nhà cung cấp không; token reasoning có tính trong trần đó trên route
   `gpt-5.6-luna` của gateway không (FOG-20)?
5. Endpoint embeddings và nhà cung cấp rerank FPT Cloud sau gateway trả những trường usage nào (FOG-22)?

## Vì sao

Độ chính xác quyết toán, an toàn khóa của model của tenant và rò rỉ thời gian qua prompt cache giữa các công ty đều
dựa vào hành vi thư viện chưa ai chạy (failure-modes #4). Trần chi phí không ràng buộc ở nhà cung cấp chỉ là trang trí.
D6 đo cả embedding và rerank.

## Mở khóa

- Spec: `model-connections` (01, 02), `usage-and-limits` (02 sổ sử dụng, 03 quyết toán và trần mỗi lời gọi),
  `tools-and-skills` (hồ sơ lược đồ).
- ADR: 0118 (Open 1: bản LiteLLM ghim), 0121.
- DO: DO-19 (D13), DO-43 (agent, tạm: không chuyển sang model nền tảng trả phí), DO-21.
- Ticket W1: `model-connections/01` (P0) đo câu 1-3; `usage-and-limits/03` dùng câu 4, `usage-and-limits/02` dùng
  câu 5.

## Dựng tối thiểu

Container model proxy theo D13: LiteLLM ghim theo digest (bản theo ADR 0118 Open 1), không database, không khóa nhà
cung cấp trong môi trường, không cache hay callback; một bộ test gọi vài nhà cung cấp với khóa tiêm qua transport, có và
không stream, có công cụ và có `response_format`; với câu 4-5, gọi qua gateway hiện có.

## Phép đo quyết định

| Đo                                                       | Ngưỡng                                         | Quyết định                              |
| -------------------------------------------------------- | ---------------------------------------------- | --------------------------------------- |
| Khóa sau mỗi lượt gọi trong log, file, bộ nhớ tiến trình | Không còn ở đâu; thiếu khóa thì 401            | Lane triển khai được không (ADR 0118)   |
| `api_base` lạ ở mọi vị trí lồng                          | Bị từ chối; test đỏ khi bỏ regex               | Lane triển khai được không (ADR 0118)   |
| Usage LiteLLM báo so với usage nhà cung cấp tính         | Chưa có ngưỡng; ghi sai lệch theo nhà cung cấp | Quyết toán đọc số nào (ADR 0121)        |
| `max_tokens` mỗi lời gọi                                 | Nhà cung cấp dừng đúng trần                    | Trần mỗi lời gọi của `usage-and-limits` |
| Prompt cache giữa hai công ty                            | Không trúng cache chéo                         | Cần `cache_salt` theo công ty không     |

## Nguồn

- Brief B8a (F6), B8b, B9, B10b, B11; `docs/adr/0118-one-model-resolver-and-tenant-models-via-litellm.md` (Open 1).
- [research.md](../research.md) mục 9 (hành vi LiteLLM theo nhà cung cấp chưa kiểm; sự cố chuỗi cung ứng 2026).

## Comments
