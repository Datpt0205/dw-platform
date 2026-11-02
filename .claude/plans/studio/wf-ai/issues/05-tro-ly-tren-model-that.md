# 05 — Trợ lý trả lời được trên model thật

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R1.1, R1.5, R1.7, R5.2, R5.3

## Mục tiêu

`make eval-wf-ai` chạy xanh trên model thật (`gpt-5.6-luna`). Hôm nay trợ lý chỉ chạy được với model giả:
trên model thật, lượt đầu đã không trả được một `AssistantTurn` hợp lệ (đo ngày 2/11/2026, dưới đây).

## Việc cần làm

1. Chọn cách hỏi model cây bước sao cho câu trả lời đọc được, dựa trên ba lần đo ở Comments: một schema có
   kiểu cho bước (`id`, `type`, `description`, `config` theo loại bước trong `build_node_registry()`) mà
   chế độ strict biểu diễn được, hoặc chế độ không strict cho riêng lượt này kèm schema có kiểu đó. Mọi
   cách giữ phép kiểm sau của nền tảng (`AssistantTurn`, `checked_proposal`), không nới chúng.
2. `scripts/eval_wf_ai.py` báo từng ca: một ca lỗi (`ModelOutputInvalidError`) là một dòng FAIL, không
   dừng cả lượt.
3. Chạy `make eval-wf-ai` với `DW_MODEL_PROVIDER=openai DW_API_MODEL_PROFILE=luna` (`.env` để `mock`),
   ghi kết quả từng ca vào Comments.

## Tiêu chí chấp nhận

- [ ] R1.1: trên model thật, lượt của ca sạch trả một đề xuất có cây bước đọc được, hoặc một câu hỏi lại.
- [ ] R5.3: mọi ca chèn lệnh của `wf_ai_injection_v1.jsonl` qua grader `frozen`.
- [ ] R1.7: câu trả lời sai hình vẫn là `ModelOutputInvalidError` sau các lần thử lại; test đỏ khi gỡ phép kiểm.
- [ ] Xong: `make eval-wf-ai` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/assistant.py:49-68` (`AssistantTurn`,
  `steps: list[dict[str, Any]]`); `adapters/openai_responses.py` `_to_strict_schema` (từ chối map tự do);
  `apps/api/src/dw_api/settings.py:196` (`DW_API_OPENAI_STRICT_SCHEMA`); spec: R1, R5.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): mở khi chạy `make eval-wf-ai` lần đầu trên model thật
  (khóa trong `.env` dùng được khi đặt provider `openai`, profile `luna`). Ba lần đo, cùng ca đầu:
  1. Chế độ strict (mặc định): adapter Responses từ chối trước lần gọi, `ConfigError` "strict structured
     output cannot express a free-form map" ở `properties.steps.anyOf.items`, vì `config` của bước là map
     tự do. Trợ lý chưa bao giờ trả lời được trên model thật.
  2. Cây bước gửi thành một chuỗi JSON (`steps_json`, schema strict biểu diễn được): model trả JSON không
     hợp lệ trong chuỗi ở cả lần đầu và lần thử lại ("Expecting property name enclosed in double quotes",
     ký tự 592), có lẽ vì `{{ ... }}` của mẫu. Đã bỏ cách này, không commit.
  3. `DW_API_OPENAI_STRICT_SCHEMA=false`: model trả cây bước nhưng thêm khóa `default` ở gốc (một lane
     của `branch` đặt sai chỗ), `extra="forbid"` từ chối, `ModelOutputInvalidError`.
  Kết luận: cần schema có kiểu cho bước. Lượt sửa `ModelRequest.output_schema` (`2bcfc59`, leadcare R1.5)
  là chỗ gửi schema đó. Nếu sai thì: giữ chế độ không strict và sửa prompt cho đúng chỗ của lane.
