# 04 — Kết nối dùng chung theo workspace: quy tắc dùng được, API, màn Kết nối, audit

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R5.12, R5.13, R5.14, R5.15, CV12, CV13, CV14, CV15, CV21, CV24

## Mục tiêu

Quản trị viên thêm, kiểm, tắt và thu hồi Kết nối dùng chung của một workspace trên trang Kết nối; một
quy tắc `connection_usable` quyết mọi lượt dùng ở phát hành, lúc nhận lượt chạy và trước mỗi lời gọi ra
ngoài; tắt hay thu hồi có hiệu lực trước lần gọi kế tiếp, và thay bí mật dừng lượt đã ghim phiên bản cũ ở lần dùng
kế tiếp (spec R5.15; V4.20); và bí mật không bao giờ trả về (spec R5). Gộp
từ B8a-connections connections-and-vault 07. P1 chỉ kết nối dùng chung theo workspace (DO-48).

## Việc cần làm

1. Migration (revision hex) trên `platform.connections` (ticket 02 tạo bảng): trigger
   `platform.guard_connection_status()` theo bảng chuyển trạng thái (cấm `revoked → active`); partial
   unique một kết nối `active` cho mỗi `(tenant_id, connector_key, external_account)`.
2. `connection_usable(connection, context, purpose)` một hàm, đúng chữ ký của ADR-0115 (Accepted) quyết 2 mà
   ADR-0118 (Accepted) quyết 3 gọi với `purpose='model'` ở W2: `context` mang công ty và chủ thể của ngữ cảnh truy
   cập hay lượt chạy, workspace của lượt chạy hay của giá trị đang duyệt, và `pinned_secret_versions`, một
   `secret_version` cho mỗi (kết nối, trường) mà bản kê của lượt ghim (tenant-config:R7.4, đọc qua
   `RunBindingsPort`), rỗng khi chưa có bản kê (lúc duyệt giá trị Điểm gắn và lúc nhận lượt chạy); W1 chỉ nhận
   `purpose='tool'` và trả false với mọi giá trị khác (R5.14). Hàm trả false khi
   Connection status không `active`, khi Phạm vi dùng chung `workspace` không phủ workspace của lượt chạy, khi
   chủ thể không giữ `connections.use` ở workspace đó (qua `platform.effective_grants` của tenant-rbac/02;
   ADR-0115 (Accepted) quyết 2), hay, trước lời gọi egress của một lượt chạy, khi một `secret_version` trong
   `pinned_secret_versions` đã thu hồi (`revoked_at <= now()`, mà ticket 02 ghi khi bí mật được thay) hay không còn
   dòng nào trong `platform.secret_envelopes` (đóng khi thiếu), đọc qua `platform.secret_status` của ticket 02, với
   lý do `credential_revoked` mà Bộ gọi ra ngoài trả khi từ chối, không gửi byte nào và không thử lại (spec R5.15;
   V4.20); dùng ở ba chỗ (duyệt giá trị Điểm gắn với người đề xuất, nhận lượt chạy, trước mỗi lời gọi egress).
3. `ConnectionDependentsPort` khai ở đây, cho "Được dùng bởi" và chặn xóa. Bên đáp ứng là tenant-config
   (đọc `studio.dependencies` cộng giá trị Bộ giá trị gắn đã duyệt trong `platform.config_versions`);
   workflow-engine và agent-builder không cài nó (tenant-config:R3.7). tenant-config/05 chờ ticket này, nên R5.8 ở đây kiểm qua
   một bản giả theo đúng hợp đồng port (trả danh sách phụ thuộc của fixture).
4. Routes `GET`, `POST /api/v1/connections`, `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`,
   `POST /api/v1/connections/{id}/test`, `.../disable`, `.../enable`,
   `GET /api/v1/connections/{id}/dependents`; quyền `connections.read`, `connections.manage` và khóa
   `connections.use` mà `connection_usable` đọc, cả ba đăng ký vào Danh mục quyền trong migration của ticket
   này với câu INSERT nêu mọi cột NOT NULL có lúc đó (gồm nhãn, `scope_kind`, `risk` theo tenant-rbac/01 và
   `tenant_grantable` của tenant-rbac/02), độ sâu qua `platform.effective_grants` của tenant-rbac/02; trường bí
   mật `writeOnly` lưu qua `platform.put_secret` (ticket 02); `Idempotency-Key` cho
   `POST`; DELETE còn phụ thuộc → 409 `connection_in_use`; id của công ty khác ở mọi route → 404; `PATCH` không
   nhận `status` hay `owning_workspace_id` (cột không đổi sau khi tạo: spec R1.7, cài ở ticket 02).
5. Bật lại hai người (D11): `POST .../enable` cho một Kết nối `disabled` hỏi trước `platform.checker_candidates`
   của tenant-rbac/02 với khóa `connections.manage`, người gửi và workspace sở hữu của Kết nối: rỗng → 409
   `conflict` với `details.reason_code` `no_checker_available`, không mở yêu cầu, status
   giữ `disabled` (R5.13); không thì trả 202 với một yêu cầu phê duyệt không lượt chạy `connections.enable`,
   `required_scope` `connections.manage`, payload chỉ mang id kết nối; Connection status giữ `disabled`.
   `connections.enable` vào `strict_approval_prefixes` bằng `|=` ở API và worker, nên người gửi tự quyết nhận 409
   `conflict` với `details.reason_code` `second_person_required` (R5.11; ADR-0104 (Accepted) quyết 11). Handler
   `connections.enable.decided` đăng ký ở composition root của worker, chạy lặp lại không đổi kết
   quả theo id phê duyệt: duyệt → `disabled → active` cùng audit `connection.enabled` đứng tên người quyết,
   `details.lane` `outbox`, trong một giao dịch; từ chối → không đổi gì. `.../disable` vẫn một người, có hiệu
   lực ngay.
6. Audit `connection.created`, `connection.updated`, `connection.disabled`, `connection.revoked`,
   `connection.tested`; outbox `connection.status_changed` v1; thông báo `needs_reauth` qua
   `platform.deliver_notification`.
7. Web `/studio/connections` (seam và allowlist antd của studio-skeleton/03): `Table` (tên, trình kết
   nối, tài khoản ngoài, Phạm vi dùng chung, Connection status bằng chữ, lần dùng gần nhất); `Drawer`
   thêm kết nối (API key, basic); trang chi tiết (sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng
   bởi", yêu cầu bật lại đang chờ); xác nhận xóa nêu tên kết nối và danh sách phụ thuộc; bí mật đã lưu hiện
   "Đã cấu hình".
8. `make generate-contracts`.

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
- [ ] R5.9 (CV14): chủ thể không giữ `connections.use` ở workspace của lượt chạy → `connection_usable` false,
      từ chối lúc duyệt giá trị Điểm gắn, lúc nhận lượt và ở Bộ gọi ra ngoài; cấp `connections.use` → qua; gỡ
      kiểm `connections.use` trong `connection_usable` → test đỏ.
- [ ] R5.10 (CV21): `POST .../enable` cho kết nối `disabled` → 202 kèm id phê duyệt `connections.enable` có
      `required_scope` `connections.manage`; Connection status vẫn `disabled`, egress vẫn
      `connection_disabled`; `PATCH` mang `status: active` không đổi status; đổi status ngay ở `POST` → test
      đỏ.
- [ ] R5.11 (CV21): người gửi tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`, status
      không đổi; người không giữ `connections.manage` quyết → 404; bỏ `connections.enable` khỏi tiền tố nghiêm →
      test đỏ.
- [ ] R5.12 (CV21): người thứ hai giữ `connections.manage` duyệt → `active`, audit `connection.enabled` đứng
      tên người đó với `details.lane` `outbox`; handler chạy lại cùng quyết định → không đổi gì thêm.
- [ ] R5.13 (CV21): chỉ người gửi giữ `connections.manage` với tới workspace sở hữu của Kết nối →
      `POST .../enable` trả 409 `conflict` với `details.reason_code` `no_checker_available`, không dòng
      `platform.approval_requests` nào, status vẫn `disabled`; thêm người thứ hai giữ khóa → 202; gỡ kiểm người
      duyệt → test đỏ.
- [ ] R5.14 (CV14): kết nối `active`, chủ thể giữ `connections.use` ở workspace của lượt chạy: `purpose='tool'` →
      true; `purpose='model'` hay một chuỗi lạ → false; gỡ kiểm `purpose` → test đỏ.
- [ ] R5.15 (CV24): một lượt chạy có `pinned_secret_versions` ghim phiên bản 1 của `api_key`, rồi quản trị viên lưu
      giá trị mới → `connection_usable` trả false với lý do `credential_revoked` trước lời gọi ra ngoài kế tiếp của
      lượt, Bộ gọi ra ngoài trả `credential_revoked`, mock nhà cung cấp không nhận gì; xóa dòng phiên bản 1 qua
      `platform.delete_secret` → vẫn `credential_revoked`; một lượt mới ghim phiên bản 2 → qua; gỡ nhánh thu hồi khỏi
      `connection_usable` → hàm trả true cho lượt cũ, test đỏ (hỏi thẳng hàm, vì `platform.open_secret` của ticket 02
      vẫn chặn lời gọi ở lớp sau, failure-modes #5).
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:77`; spec: R5.1
  (quyền theo độ sâu).
- spec: R5, CV12-CV15, CV24; ADR-0115 (Accepted) quyết 2; ticket 02 (`platform.connections`,
  `platform.put_secret`, `revoked_at`, `platform.secret_status`), ticket 03 (Bộ gọi ra ngoài).

## Comments

- 2026-10-23 (agent): DO-48 (tạm khuyến nghị a) chốt P1 chỉ kết nối dùng chung theo workspace; kết nối cá
  nhân và ủy quyền là W2 (B8a ticket 17).
- 2026-10-23 (agent): Đạt chốt DO-48.1 (a) ngày 23/10/2026, ticket giữ như đang viết. Theo phát hiện kiểm
  nhất quán cùng ngày: `ConnectionDependentsPort` do tenant-config đáp ứng (bước 3); khóa `connections.read`,
  `connections.manage` đăng ký trong migration của ticket này (bước 4).
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026: `connection_usable` kiểm thêm `connections.use`
  (ADR-0115 (Accepted) quyết 2; bước 2, bước 4, R5.9, CV14); phạm vi D11 (người đặt yêu cầu và Đạt): bật lại
  một kết nối cần người thứ hai qua phê duyệt nghiêm `connections.enable`, tắt vẫn một người (bước 5; R5.10,
  R5.11, R5.12, CV21). Các bước sau đó đánh số lại từ 6.
- 2026-10-24 (agent): theo kiểm nhất quán vòng 3 (vòng sửa thứ tư): `POST .../enable` hỏi
  `platform.checker_candidates` và trả 409 `no_checker_available` khi không còn người duyệt khác người gửi (bước
  5; R5.13, CV21); người gửi tự quyết nhận `second_person_required` (V4.P9, R5.11); câu INSERT đăng ký khóa nêu
  `tenant_grantable` (V4.P2, bước 4). Blocked by đã có tenant-rbac/02. Khóa duyệt `connections.manage` của
  `connections.enable` nay là quyết định của Đạt (V4.5), ADR-0115 (Accepted) quyết 2 ghi.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: `connection_usable` đọc phiên bản bí mật đã thu hồi từ cột
  `secret_version` của `platform.secret_envelopes` (ticket 02), một `secret_version` mà bản kê ghim không còn
  dòng nào, thay "credential version" mà không bảng nào khai, và nhận các `secret_version` đã ghim qua tham số
  `pinned_secret_versions`, vì hàm không tự đọc bản kê (bước 2; ADR-0115 (Accepted) quyết 1).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: chữ ký thành `connection_usable(connection, context, purpose)` của
  ADR-0115 (Accepted) quyết 2, `pinned_secret_versions` đi trong `context`, và W1 chỉ nhận `purpose='tool'` (R5.14,
  CV14), để kết nối model của W2 thêm một giá trị mà không sửa chỗ gọi nào (CLAUDE.md, Per-tenant artifacts);
  bản kê ghim một `secret_version` cho mỗi (kết nối, trường), vì phiên bản đếm theo (chủ thể, trường)
  (tenant-config:R7.4) (bước 2); `PATCH` không nhận `owning_workspace_id`, cột mà ticket 02 giữ không đổi (bước
  4).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f: theo V4.20 (Đạt), nhánh thu hồi của `connection_usable` nay có nguồn:
  thay bí mật của một Kết nối ghi `revoked_at` cho phiên bản cũ (ticket 02), và một `secret_version` đã ghim mà đã
  thu hồi hay không còn dòng nào làm hàm trả false với lý do `credential_revoked` trước lời gọi ra ngoài kế tiếp của
  lượt (bước 2; spec R5.15, CV24), thay câu cũ gọi phiên bản đã thu hồi là phiên bản không còn dòng.
