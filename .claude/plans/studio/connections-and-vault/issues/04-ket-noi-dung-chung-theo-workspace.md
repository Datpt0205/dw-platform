# 04 — Kết nối dùng chung theo workspace: quy tắc dùng được, API, màn Kết nối, audit

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, CV12, CV13, CV14, CV15

## Mục tiêu

Quản trị viên thêm, kiểm, tắt và thu hồi Kết nối dùng chung của một workspace trên trang Kết nối; một
quy tắc `connection_usable` quyết mọi lượt dùng ở phát hành, lúc nhận lượt chạy và trước mỗi lời gọi ra
ngoài; tắt hay thu hồi có hiệu lực trước lần gọi kế tiếp; và bí mật không bao giờ trả về (spec R5). Gộp
từ B8a-connections connections-and-vault 07. P1 chỉ kết nối dùng chung theo workspace (DO-48).

## Việc cần làm

1. Migration (revision hex) trên `platform.connections` (ticket 02 tạo bảng): trigger
   `platform.guard_connection_status()` theo bảng chuyển trạng thái (cấm `revoked → active`); partial
   unique một kết nối `active` cho mỗi `(tenant_id, connector_key, external_account)`.
2. `connection_usable(connection_id, principal, workspace_id)` một hàm: trả false khi Connection status
   không `active`, khi Phạm vi dùng chung `workspace` không phủ workspace của lượt chạy, hay khi credential
   version đã thu hồi; dùng ở ba chỗ (phát hành điểm gắn, nhận lượt chạy, trước mỗi lời gọi egress).
3. `ConnectionDependentsPort` khai ở đây (workflow-engine và agent-builder cài), cho "Được dùng bởi" và
   chặn xóa.
4. Routes `GET`, `POST /api/v1/connections`, `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`,
   `POST /api/v1/connections/{id}/test`, `.../disable`, `.../enable`,
   `GET /api/v1/connections/{id}/dependents`; quyền `connections.read`, `connections.manage` (tenant-rbac
   ánh xạ); trường bí mật `writeOnly` lưu qua `platform.put_secret` (ticket 02); `Idempotency-Key` cho
   `POST`; DELETE còn phụ thuộc → 409 `connection_in_use`; id của công ty khác ở mọi route → 404.
5. Audit `connection.created`, `connection.updated`, `connection.disabled`, `connection.revoked`,
   `connection.tested`; outbox `connection.status_changed` v1; thông báo `needs_reauth` qua
   `platform.deliver_notification`.
6. Web `/studio/connections` (seam và allowlist antd của studio-skeleton/03): `Table` (tên, trình kết
   nối, tài khoản ngoài, Phạm vi dùng chung, Connection status bằng chữ, lần dùng gần nhất); `Drawer`
   thêm kết nối (API key, basic); trang chi tiết (sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng
   bởi"); xác nhận xóa nêu tên kết nối và danh sách phụ thuộc; bí mật đã lưu hiện "Đã cấu hình".
7. `make generate-contracts`.

## Tiêu chí chấp nhận

- [ ] R5.1: người giữ `connections.manage` tạo kết nối → bí mật vào Kho bí mật, dòng Connection status
      `pending` hay `active`, audit `connection.created`.
- [ ] R5.2 (CV12): duyệt mọi schema 2xx của router kết nối → không trường bí mật; `GET` sau khi tạo
      không chứa giá trị canary; trường bí mật đã lưu hiện "Đã cấu hình".
- [ ] R5.3 (CV13): công ty B gọi `GET`, `PATCH`, `DELETE`, `test` với id của công ty A → 404; mock nhà
      cung cấp không nhận gì.
- [ ] R5.4 (CV14): lượt chạy ở một workspace dùng kết nối `workspace` của workspace khác → `connection_usable`
      false, từ chối ở phát hành và ở Bộ gọi ra ngoài; gỡ kiểm workspace trong `connection_usable` → test
      đỏ.
- [ ] R5.5 (CV15): kết nối `disabled` → `connection_disabled` ở egress trước lời gọi kế; tắt một kết nối
      đang được một lượt chạy dùng → lời gọi ra ngoài kế tiếp bị từ chối.
- [ ] R5.6 (CV15): `UPDATE` Connection status `revoked → active` → trigger từ chối; gỡ kiểm trong
      `connection_usable` → test đỏ.
- [ ] R5.7: Playwright mở `/studio/connections` → thấy tên, trình kết nối, tài khoản ngoài, phạm vi,
      trạng thái bằng chữ và "Được dùng bởi"; người thiếu `connections.manage` thấy nút bị tắt kèm lý do
      và API `POST` vẫn trả 403.
- [ ] R5.8: xóa kết nối còn thành phần phụ thuộc → 409 `connection_in_use`, không xóa.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:77`; spec: R5.1
  (quyền theo độ sâu).
- spec: R5, CV12-CV15; ADR-0115 (Proposed) quyết 2; ticket 02 (`platform.connections`,
  `platform.put_secret`), ticket 03 (Bộ gọi ra ngoài).

## Comments

- 2026-10-23 (agent): DO-48 (tạm khuyến nghị a) chốt P1 chỉ kết nối dùng chung theo workspace; kết nối cá
  nhân và ủy quyền là W2 (B8a ticket 17).
