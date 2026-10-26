# 07 — Phân tích năng lực của agent: luật tự chủ và móc của loại agent

Status: needs-triage
Blocked by: 05, .claude/plans/studio/agent-builder/issues/05-gioi-han-du-lieu-cua-agent.md
Area: studio
Yêu cầu: R4.3, R4.4, R4.5, R4.6, CP13, CP14, CP15

## Mục tiêu

Khi gửi kiểm định một phiên bản agent, cùng module `capability_analysis` của ticket 05 đọc nhãn năng lực của các công
cụ trong Bộ công cụ và giới hạn dữ liệu của agent; một agent mang cả ba nhãn phải tự chủ ≤ A2, công cụ thiếu phân loại
bị từ chối, và kết quả ghi vào `studio.version_assessments` như với quy trình (spec R4.3-R4.6; ADR-0125 (Accepted)).
Ticket tách từ bước 3 của ticket 05 (V4.31), để phân tích của quy trình không chờ loại `agent`.

## Việc cần làm

1. Móc phân tích của loại `agent`: đăng ký `capability_analysis` vào bảng kiểm theo loại lúc gửi kiểm định của
   agent-lifecycle/03 cho loại `agent` (agent-lifecycle:R2.7), bên cạnh mục của loại `workflow` mà ticket 05 đăng ký;
   module đọc tài liệu agent của agent-builder/02 và Bộ công cụ đã ghim, gán nhãn `untrusted_source`,
   `private_data`, `external_effect` của từng công cụ từ bảng điều phối ở composition root của ticket 05 (công cụ loại
   lạ mang cả ba nhãn, spec R4.1), và nhãn `private_data` từ giới hạn dữ liệu mà phép dẫn của agent-builder/05 trả.
2. Quy tắc agent: mang cả ba nhãn thì Mức tự chủ khai ≤ A2 (công cụ `external` và `critical` luôn hỏi); trên A2 →
   422 `capability_trifecta_autonomy` kèm hai cách sửa (hạ tự chủ, hoặc tách phần đọc nội dung không tin cậy khỏi phần
   giữ tác động); công cụ thiếu một phân loại trong Bộ công cụ → 422 `tool_unclassified`; overlay công ty hay một Mức
   tự chủ nâng trên A2 cho agent bộ ba → 422, phiên bản vẫn Nháp, vì sàn chỉ siết được (spec R4.3, R4.4, R4.5).
3. Kết quả ghi một dòng `studio.version_assessments` (bảng của ticket 05) cho Mã băm định nghĩa của phiên bản agent
   trong giao dịch gửi kiểm định, cùng cột như dòng của quy trình (spec R4.6).
4. Case trong bộ eval bảo mật: agent Marketing có công cụ gửi tin, đọc lead và nhận nội dung từ web ở A3.

## Tiêu chí chấp nhận

- [ ] R4.3 (CP13): agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy` kèm hai cách sửa; cùng agent ở A2 →
      gửi kiểm định được; gỡ kiểm → test đỏ.
- [ ] R4.4 (CP14): Bộ công cụ của agent có một công cụ thiếu một trong ba phân loại → 422 `tool_unclassified`; gỡ kiểm
      → test đỏ.
- [ ] R4.5 (CP15): overlay công ty nâng Mức tự chủ trên A2 cho một agent bộ ba → gửi kiểm định 422
      `capability_trifecta_autonomy`, phiên bản vẫn Nháp.
- [ ] R4.6: gửi kiểm định một agent hợp lệ → đúng một dòng `studio.version_assessments` cho Mã băm định nghĩa của
      phiên bản, ghi trong cùng giao dịch; rollback giao dịch gửi kiểm định → không dòng nào; bỏ mục `agent` khỏi bảng
      kiểm theo loại → gửi kiểm định agent A3 bộ ba qua được, test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`; spec: R4.3 (thang tự chủ, hai sàn
  `critical` và `approval_policy: always`).
- ADR-0125 (Accepted) quyết 1, 2, 3, 5; agent-lifecycle:R2.7; spec: R4.3-R4.6.

## Comments

- 2026-10-25 (agent): ticket mới theo V4.31 của Đạt (lượt h), số và đường dẫn theo bảng ticket mới của lượt: luật agent
  (bước 3 cũ của ticket 05) và móc phân tích của loại `agent`; Blocked by 05 và agent-builder/05 theo bảng cạnh của
  lượt, thay cạnh 05 <- agent-builder/02.
