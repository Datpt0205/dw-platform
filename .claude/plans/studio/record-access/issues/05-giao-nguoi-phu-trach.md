# 05 — Giao người phụ trách và đổi workspace sở hữu

Status: needs-triage
Blocked by: 03, 04
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, RA24, RA25, RA26

## Mục tiêu

Trưởng kinh doanh, hay bước "Giao cho" của quy trình tiếp nhận, giao một lead của Marketing cho một nhân viên Sales
qua một hàm duy nhất được đổi người phụ trách, giữ workspace sở hữu trừ khi người giao chọn khác, có audit và outbox
trong cùng giao dịch (spec R8; ADR-0105 (Proposed) mục 2 và 3; DO-11 theo khuyến nghị (a), tạm).

## Việc cần làm

1. `studio.assign_record(p_record_id uuid, p_owner_kind text, p_owner_id uuid, p_workspace_id uuid)`: SECURITY
   DEFINER thuộc `dw_migrator`, `search_path` cố định, EXECUTE thu khỏi PUBLIC và cấp cho `dw_app`, không nhận tên bảng;
   tenant, chủ thể và loại actor lấy từ setting. Thứ tự kiểm, mỗi bước một SQLSTATE riêng mà adapter đổi ra mã lý do:
   bản ghi thấy được với người gọi (không thì 404); người gọi có tầm `assign` trên bản ghi, điều kiện dựng bằng module
   mẫu policy của ticket 03 từ cùng các hàm `studio.acl_*` (không thì `assign_not_permitted`); người nhận là thành viên
   công ty `active` của tenant đang gắn và có `read` trên object ở bất kỳ mức nào (người của tenant khác thì 404, còn
   lại `assign_target_out_of_reach`); khi `p_workspace_id` khác NULL: workspace đó trong `studio.acl_workspaces('create')`
   hay tầm `create` Toàn công ty của người giao và người nhận là thành viên của nó (không thì
   `assign_target_out_of_reach`); `p_owner_kind = 'team'` bị từ chối cho tới W2.
2. Hàm cập nhật `owner_id`, `owner_kind`, `workspace_id` khi được chọn, tăng `version` của bản ghi, và trả
   `version`, `owner_id`, `workspace_id` mà không đọc lại qua RLS, nên người giao mất quyền thấy sau lần giao không làm
   giao dịch lùi.
3. Dịch vụ `AssignRecordService` trong `dw_studio`: gọi hàm qua adapter bản ghi, rồi trong cùng giao dịch ghi audit
   `studio.record.assigned` (`object_id`, `record_id`, người phụ trách và workspace sở hữu trước và sau; không giá trị
   trường) và outbox `studio.record.assigned` (payload v1: cùng các id và `version`) vào `platform.outbox_events`.
4. Route `POST /api/v1/studio/objects/{api_name}/records/{record_id}/assign`: `Idempotency-Key` qua
   `get_idempotent_operation`; thân `{"owner_id": "...", "workspace_id": "..."}`, `workspace_id` tùy chọn; 200 với
   `record_id`, `version`, `owner_id`, `workspace_id`; 403 `assign_not_permitted`, 403 `assign_target_out_of_reach`,
   404, trong `details.reason_code` của lỗi; `make generate-contracts`.
5. Bước "Giao cho" của workflow-nodes gọi cùng `AssignRecordService`; không đường nào khác đổi được người phụ trách vì
   `dw_app` không có UPDATE trên các cột đó (ticket 03).

## Tiêu chí chấp nhận

- [ ] R8.1 (RA26): người phụ trách có `read` và `assign` mức Của tôi giao lead của mình cho một nhân viên Sales → 200,
      người phụ trách mới, `version` tăng 1, dù sau lần giao người giao không còn thấy lead; thêm bước đọc lại qua RLS
      trong hàm → test đỏ.
- [ ] R8.2: không gửi `workspace_id` → workspace sở hữu giữ nguyên Marketing.
- [ ] R8.3: gửi `workspace_id` của Sales khi Sales trong tầm `create` của người giao và người nhận là thành viên Sales
      → workspace sở hữu thành Sales trong cùng giao dịch.
- [ ] R8.4 (RA24): người thấy lead mà không có tầm `assign`, kể cả khi chỉ với tới qua `public_read_write` → 403
      `assign_not_permitted`, không cột nào đổi; gỡ kiểm `assign` trong hàm → test đỏ.
- [ ] R8.5 (RA24): người nhận không có `read` trên object, hay bị tạm khóa, hay `workspace_id` ngoài tầm `create` của
      người giao, hay người nhận không là thành viên workspace đích → 403 `assign_target_out_of_reach`, không cột nào
      đổi.
- [ ] R8.6 (RA24): người nhận thuộc tenant B → 404 như id không tồn tại; bản ghi người gọi không thấy → 404; không cột
      nào đổi.
- [ ] R8.7 (RA25): một lần giao → đúng một audit `studio.record.assigned` chỉ có id; lỗi giả lập sau khi ghi audit →
      giao dịch lùi, 0 audit, người phụ trách cũ.
- [ ] R8.8 (RA25): một lần giao → đúng một dòng outbox `studio.record.assigned` cùng giao dịch; giao dịch lùi → 0 dòng
      outbox.
- [ ] R8.9 (RA26): người phụ trách cũ chỉ có `read` mức Của tôi SELECT bản ghi ở câu lệnh đầu tiên sau commit → 0 dòng.
- [ ] R8.10 (RA25): cùng người gọi gửi lại cùng `Idempotency-Key` → trả kết quả lần đầu, một audit, một outbox,
      `version` tăng một lần.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/dependencies/idempotency.py:217`; spec: R8.10.
- `db/migrations/sql/0001_platform_baseline.sql:304`; spec: R8.8.
- `db/migrations/sql/0012_partition_maintenance.sql:45-48`; spec: R8.1.
- `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:62-66`; spec: R8.4, R8.5.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:67-74`; spec: R8.1, R8.2.

## Comments

- 2026-10-23 (agent): DO-11 theo khuyến nghị (a), tạm: lần giao giữ workspace sở hữu mặc định, người giao chọn khác
  được; người phụ trách được ở workspace khác (lead của Marketing, người phụ trách ở Sales).
