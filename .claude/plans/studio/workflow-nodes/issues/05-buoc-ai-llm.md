# 05 — ai.llm: đầu ra có cấu trúc kiểm phía server, prompt bao chứa, tôn trọng opt-out

Status: needs-triage
Blocked by: 03, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, WN2, WN3, WN14

## Mục tiêu

Bước `ai.llm` trả đầu ra theo JSON Schema người dựng đặt, kiểm ở máy chủ, sửa tối đa một lần, với giá
trị bản ghi chỉ vào prompt qua khối bao chứa và bản ghi opt-out bị bỏ qua (workflow-nodes R7.1, R7.2,
R7.3, R7.4, WN2, WN3, WN14).

## Việc cần làm

1. Khung prompt `configs/prompts/studio/llm_node@1.0.0.yaml`; hướng dẫn của tenant là một khối riêng bao
   chứa, không phải thân mẫu. Lưu từ chối hướng dẫn chứa chuỗi `<input` (tenant không tự mở khối).
2. Đầu ra `text` hoặc theo JSON Schema của tenant; kiểm phía server bằng bộ kiểm `jsonschema-rs` của
   tools-and-skills; sửa tối đa một lần; vẫn sai → `continue` với `default_output` và đi Nhánh ra lỗi,
   lượt chạy không dừng. Metadata: token, chi phí chuỗi thập phân, route class.
3. Mọi giá trị bản ghi vào prompt qua đích `prompt` của bộ dựng mẫu (bao `<input>`, cắt 16 KiB); mục
   bối cảnh mang một nhãn mô tả cho model, nhãn đó cũng bao chứa (mẫu học từ config-chang.md mẫu 1).
4. Trước khi gọi model: nếu bản ghi mang `ai_opt_out` hoặc `processing_restricted` (cờ của
   compliance-pdpl) thì bỏ qua, không gọi. Bộ phân giải model theo tenant của model-connections áp và
   ghi route class mỗi lời gọi.
5. Hình chiếu chấm điểm lead: đầu vào gửi model không chứa định danh trực tiếp; số điện thoại và email
   trong văn bản tự do bị che bằng `text.mask_contacts`.

## Tiêu chí chấp nhận

- [ ] R7.1 (WN3): model giả trả `score=150` (ngoài lược đồ) hai lần → `output_invalid`, đi Nhánh ra
      lỗi, lượt chạy không dừng; gỡ kiểm JSON Schema → test đỏ.
- [ ] R7.2 (WN2): một lời nhắn lead chứa `</input>` vào prompt không đóng được khối; gỡ bao chứa → đỏ.
- [ ] R7.3 (WN14): một lead `ai_opt_out` → không có lời gọi model nào.
- [ ] R7.4: đầu vào chấm điểm không chứa họ tên, số điện thoại, email hay Zalo id; số và email trong
      văn bản tự do hiện dạng đã che.
- [ ] R7.1: hướng dẫn tenant chứa `<input` → lưu từ chối.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_ai_llm_node.py` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; spec: R7.2.
- ADR-0112 (Proposed) quyết 7; spec: R7.1, R7.3.
- ADR-0010 (Accepted); spec: R7.2.

## Comments
