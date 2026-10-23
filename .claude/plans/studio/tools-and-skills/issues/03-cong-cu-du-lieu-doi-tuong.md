# 03 — Công cụ dữ liệu đối tượng theo phiên bản lược đồ, dùng quyền của người gọi

Status: needs-triage
Blocked by: 02, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, TS8, TS9

## Mục tiêu

Trợ lý đọc được lead, chiến dịch và tương tác theo đúng quyền của người hỏi bằng công cụ đọc đối tượng
sinh từ phiên bản lược đồ, chạy qua RecordService với quyền người gọi, lược đồ thu hẹp theo bảo mật
trường, và không giữ công cụ gửi tin hay sửa bản ghi (spec R6). Gộp từ B8b-tools tools-and-skills 05.

## Việc cần làm

1. Khai `ObjectDataPort` (`search`, `get`, `describe_for_tools`; `create`, `update` về sau), chạy với
   `AccessContext` của người gọi; custom-objects cài qua RecordService (custom-objects/04).
2. `ObjectToolGenerator`: phiên bản đối tượng × thao tác bật → `dw.tool/v1` `kind: object_crud`, tên
   `obj.<api_name>.search` và `obj.<api_name>.get` (W1 chỉ đọc); ánh xạ kiểu trường từ bộ chiếu lược đồ;
   `additionalProperties: false`; DSL lọc với `op` thuộc danh sách đóng; `limit` tối đa 50.
3. Mức sàn: `search`, `get` → `none` (không bao giờ `never`); công cụ đọc trả id bản ghi và chỉ trường
   người gọi đọc được.
4. Handler outbox `studio.object.version_published`, actor `system:object_tools`; thay đổi phá vỡ → sự
   kiện lệch cho agent-lifecycle đọc.
5. `FieldSecurityToolSchemaMiddleware` thu hẹp lược đồ model thấy theo người gọi, chỉ thu hẹp không mở
   rộng; giá trị Đã ẩn vắng khỏi đầu vào và đầu ra công cụ (field-security/01).

## Tiêu chí chấp nhận

- [ ] R6.1: ghim một phiên bản đối tượng vào Bộ công cụ → sinh `obj.<api_name>.search` và
      `obj.<api_name>.get` từ bộ chiếu lược đồ theo `schema_version`.
- [ ] R6.2: `obj.lead_search` chạy qua RecordService với `AccessContext` của người gọi; người gọi ở mức
      truy cập Của tôi chỉ thấy bản ghi mình phụ trách.
- [ ] R6.3 (TS8): người không đọc được `phone` gọi `obj.lead_search` → đầu ra không có `phone`, lược đồ
      model thấy không có `phone`; gỡ `FieldSecurityToolSchemaMiddleware` → test đỏ.
- [ ] R6.4 (TS9): trợ lý của công ty B gọi công cụ hỏi lead của công ty A → `not_found`, không lộ bản
      ghi; gỡ kiểm tenant → test đỏ.
- [ ] R6.5 (TS9): đối tượng xuất bản phiên bản xóa một trường → công cụ ghim bản cũ báo lệch.
- [ ] R6.7 (TS9): lời gọi công cụ dùng trường đã xóa → RecordService từ chối; gỡ kiểm lệch → test đỏ.
- [ ] R6.6: `obj.lead_search` và `obj.lead_get` mang Mức tác động `none` và trả id bản ghi; bản ghi
      không thấy được → `not_found`, không 403.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- spec: R6, TS8, TS9; ADR-0116 (Proposed) quyết 1; custom-objects/04 (`RecordQueryCompiler`,
  custom-objects:R8.1; bộ chiếu lược đồ, custom-objects:R3.6; cách ly tenant, custom-objects:R4.3);
  field-security/01 (giá trị Đã ẩn); tenant-config/02 qua ticket 02 (ghim Bộ công cụ).

## Comments

- 2026-10-23 (agent): W1 chỉ công cụ đọc (`search`, `get`) cho trợ lý; `create`, `update` của công cụ
  đối tượng là W2. Phủ YC96 (trợ lý Marketing chỉ đọc) cùng YC19 và YC23.
