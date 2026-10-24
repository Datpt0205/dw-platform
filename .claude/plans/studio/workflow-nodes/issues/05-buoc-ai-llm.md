# 05 — ai.llm: đầu ra có cấu trúc kiểm phía server, prompt bao chứa, tôn trọng opt-out

Status: needs-triage
Blocked by: 03, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.4, R7.5, WN2, WN3

## Mục tiêu

Bước `ai.llm` trả đầu ra theo JSON Schema người dựng đặt, kiểm ở máy chủ, sửa tối đa một lần, với giá
trị bản ghi và `Mô tả cho AI` của đối tượng và trường chỉ vào prompt qua khối bao chứa (workflow-nodes R7.1, R7.2,
R7.4, R7.5, WN2, WN3). Bỏ qua bản ghi opt-out (R7.3, WN14) ở W2 cùng cờ của compliance-pdpl.

## Việc cần làm

1. Khung prompt `configs/prompts/studio/llm_node@1.0.0.yaml`, dựng bằng `assemble_system_prompt` của
   agent-builder/02 (ADR-0117 (Accepted) quyết 4); hướng dẫn của tenant là một khối riêng bao chứa, không phải thân
   mẫu. Lưu hướng dẫn qua đúng linter của agent-builder/02, nên chuỗi `<input` hay `<tenant_instructions` bị từ
   chối (tenant không tự mở khối); ticket này không viết linter thứ hai.
2. Đầu ra `text` hoặc theo JSON Schema của tenant; kiểm phía server bằng bộ kiểm `jsonschema-rs` của
   tools-and-skills; sửa tối đa một lần; vẫn sai → `continue` với `default_output` và đi Nhánh ra lỗi,
   lượt chạy không dừng. Metadata: token, chi phí chuỗi thập phân, route class.
3. Mọi giá trị bản ghi vào prompt qua đích `prompt` của bộ dựng mẫu (bao `<input>`, cắt 16 KiB); mục
   bối cảnh mang một nhãn mô tả cho model, nhãn đó cũng bao chứa (mẫu học từ config-chang.md mẫu 1). Nhãn đó là
   `Mô tả cho AI` (`ai_description`, tối đa 500 ký tự) của đối tượng và của trường mà custom-objects/02 lưu, đọc như
   dữ liệu từ bên ngoài và bao như mọi giá trị (R7.5, YC101).
4. Bộ phân giải model theo tenant của model-connections áp và ghi route class mỗi lời gọi. Bỏ qua bản ghi
   mang `ai_opt_out` hay `processing_restricted` là W2 (R7.3), vì W1 chỉ chạy trên lead giả lập (YC89).
5. Hình chiếu chấm điểm lead: đầu vào gửi model không chứa định danh trực tiếp; số điện thoại và email
   trong văn bản tự do bị che bằng `text.mask_contacts`.

## Tiêu chí chấp nhận

- [ ] R7.1 (WN3): model giả trả `score=150` (ngoài lược đồ) hai lần → `output_invalid`, đi Nhánh ra
      lỗi, lượt chạy không dừng; gỡ kiểm JSON Schema → test đỏ.
- [ ] R7.2 (WN2): một lời nhắn lead chứa `</input>` vào prompt không đóng được khối; gỡ bao chứa → đỏ.
- [ ] R7.4: đầu vào chấm điểm không chứa họ tên, số điện thoại, email hay Zalo id; số và email trong
      văn bản tự do hiện dạng đã che.
- [ ] R7.1: hướng dẫn tenant chứa `<input` → lưu từ chối bằng mã lỗi của linter agent-builder/02; mô-đun bước không
      có hàm kiểm chuỗi `<input` nào của riêng nó (test kiến trúc).
- [ ] R7.5 (WN2): `ai_description` của trường `notes` chứa `</input>` và một chỉ dẫn → chỉ xuất hiện trong khối
      `<input>` đã thoát của mục bối cảnh, không đóng được khối; gỡ bao chứa ở mục bối cảnh → test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_ai_llm_node.py` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; spec: R7.2.
- ADR-0112 (Accepted) quyết 8; spec: R7.1.
- ADR-0010 (Accepted); spec: R7.2.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026 (Q9): cờ Hạn chế xử lý ở W2, nên R7.3 và WN14 rời ticket này sang W2.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: ticket dùng `assemble_system_prompt` và linter của agent-builder/02, chờ ticket đó (A:agent-builder:R2.2~workflow-nodes/05); `Mô tả cho AI` vào prompt như dữ liệu từ bên ngoài (N3, YC101), chờ custom-objects/02 nơi trường này ra đời.
