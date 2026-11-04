# 04 — Kết nối dùng chung theo workspace: quy tắc dùng được, API, thu hồi vì lộ, bật lại hai người, audit

Status: ready-for-agent
Blocked by: 02, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.15, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.8, R5.9, R5.10, R5.11, R5.12, R5.13, R5.14, R5.15, R5.16, R5.17, R5.18, R5.19, R5.20, R5.21, CV12, CV13, CV14, CV15, CV21, CV24, CV28, CV31

## Mục tiêu

Quản trị viên thêm, xoay, tắt, bật lại (hai người), xóa và thu hồi vì lộ Kết nối dùng chung của một workspace qua API,
mỗi route chỉ trên Kết nối mà người gọi với tới (spec R5.18); một quy tắc `connection_usable` trả lời "lượt này dùng
được Kết nối này bây giờ không" cho ba chỗ gọi mà tenant-config/05 và ticket 05 dựng (duyệt giá trị Điểm gắn, nhận lượt
chạy, trước mỗi lời gọi ra ngoài); xoay bí mật không dừng lượt nào, còn thu hồi vì lộ làm hàm từ chối mọi lượt được xin
lúc hay trước nó, kể cả khi đã có phiên bản mới (spec R1.15, R5.15-R5.17; V4.35; H-28); bảng chuyển trạng thái là của
cơ sở dữ liệu (ADR-0115 (Accepted) quyết 2); và bí mật không bao giờ trả về (spec R5.2). Route
`POST .../test` và audit `connection.tested` ở ticket 05, nơi có `SmtpEgress` để thử; màn `/studio/connections` ở
ticket 07 (V4.31). Gộp từ B8a-connections connections-and-vault 07. P1 chỉ kết nối dùng chung theo workspace (DO-48).

## Việc cần làm

1. Migration (revision hex) trên `platform.connections` (ticket 02 tạo bảng):
    - Trigger `platform.guard_connection_status()`, BEFORE INSERT OR UPDATE OF `status`, một bảng chuyển trạng thái cho
      mọi bên ghi (spec Dữ liệu, R5.6, R5.19): INSERT chỉ `pending` hay `active`; `pending → active | disabled`;
      `active → disabled | needs_reauth | revoked`; `needs_reauth → active | disabled | revoked`;
      `disabled → active | revoked`; `revoked` là trạng thái cuối; giữ nguyên status luôn nhận; mọi cặp khác → lỗi
      (SQLSTATE 23514), dòng không đổi. Cột `disabled_at timestamptz NULL`, không DEFAULT, chỉ trigger này ghi
      (`now()` mỗi lần status đổi sang `disabled` từ một trạng thái khác; không grant UPDATE cột cho `dw_app`). `disabled → active` chỉ nhận khi
      giao dịch đã đặt `app.connection_enable_approval` (`set_config(..., true)`) là id của một dòng
      `platform.approval_requests` cùng công ty, `approval_type` `connections.enable`, `status` `approved`, `payload`
      `connection_id` là id dòng này và `created_at` sau `disabled_at` của dòng (R5.19). P1 chỉ ghi INSERT `active`
      (bước 4), `active → disabled` (bước 4) và `disabled → active` (handler bước 5); `pending`, `needs_reauth`,
      `revoked` không có bên ghi ở P1, mà bộ điều phối OAuth W2 ghi (spec Ngoài phạm vi).
    - Unique từng phần `uq_connections_account_live` một dòng có `status <> 'revoked'` cho mỗi
      `(tenant_id, connector_key, lower(external_account))` (spec Dữ liệu, R5.21; `POST` bỏ khoảng trắng hai đầu trước
      khi lưu, nên `A@X.vn` và ` a@x.vn` là một tài khoản), không chỉ dòng `active`: một Kết nối
      `disabled` chặn tạo Kết nối mới cho cùng tài khoản, nên đường trở lại của tài khoản đó là bật lại hai người (bước
      5), và handler bật lại không bao giờ gặp một dòng `active` khác cùng tài khoản; `external_account` NULL không
      trùng nhau (NULL khác NULL), như spec Dữ liệu ghi.
    - Cột `compromised_at` và hàm thu hồi vì lộ của bước 2a; cột `name text NOT NULL` CHECK `btrim(name) <> ''` và
      `char_length(name) <= 200`, tên mà R5.7 và màn của ticket 07 hiện, thêm được NOT NULL vì trước ticket này không
      lệnh nào ghi dòng Kết nối; `dw_app` có UPDATE cột `name` (đổi tên qua `PATCH`).
    - Đăng ký `connections.read`, `connections.manage`, `connections.use` vào `platform.permissions`, câu INSERT nêu mọi
      cột NOT NULL có lúc đó (`db/migrations/versions/ebb17244abc6_permission_catalogue.py:322-345`,
      `db/migrations/versions/b5677d345bc1_tenant_roles.py:1230`):
      `area` `connections`, `label_vi`, `scope_kind` `workspace` cả ba, `risk` `standard` cho `read` và `use`,
      `elevated` cho `manage`, `status` `active`, `owner_package` `dw_platform`, `tenant_grantable` đúng. Không vai mẫu
      nào nhận khóa trong migration này: `tenant_owner` giữ chúng do được tính (ADR-0104 (Accepted) quyết 2), người
      khác nhận qua một thay đổi vai hai người (quyết 10). Mỗi khóa được kiểm qua một hằng module tên `*_SCOPE` hay
      `.require(...)`, để `test_permission_catalogue.py` (c) thấy khóa `active` có bên kiểm.
2. `connection_usable(connection, context, purpose) -> Usability` một hàm ở `dw_platform.application.connections`,
   lớp ứng dụng kết nối của nền tảng, đúng chữ ký của ADR-0115 (Accepted) quyết 2 mà ADR-0118 (Accepted) quyết 3 gọi
   với `purpose='model'` ở W2; `connection` là id Kết nối, và hàm đọc dòng ở mỗi lần hỏi, không qua bộ đệm nào, để tắt
   có hiệu lực trước lời gọi kế (spec R5.5). `context` là `UsableContext(tenant_id, principal_id, workspace_id, call_site,
run_requested_at)`: `call_site` bắt buộc, không mặc định, một trong `binding_review`, `run_admission`, `egress`;
   `principal_id` là chủ thể mà lượt hành động thay (`principal` của bản kê, tenant-config/05 bước 9) hay người đề xuất
   giá trị Điểm gắn; `workspace_id` là workspace của lượt hay của giá trị đang duyệt; `run_requested_at` là
   `created_at` của dòng `platform.worker_runs` của lượt. Hàm không đọc `platform.worker_runs`, bản kê hay phiên bản
   bí mật nào được ghim (ADR-0109 (Accepted) quyết 6; V4.35): chỗ gọi đưa các giá trị đó. `Usability` mang `usable`
   và một `reason` khi false. Hàm trả false, theo thứ tự, khi:
    - không thấy dòng Kết nối dưới `app.tenant_id` (`connection_not_found`), kể cả Kết nối đã xóa;
    - `purpose` khác `tool` (`purpose_not_allowed`; spec R5.14);
    - status khác `active` (`connection_disabled`; spec R5.5);
    - `share_scope` khác `workspace`, hay `owning_workspace_id` khác `context.workspace_id`
      (`connection_out_of_scope`; spec R5.4, R5.20);
    - `principal_id` NULL, hay `context.workspace_id` không nằm trong
      `platform.workspace_reach(tenant_id, principal_id, 'connections.use')` (`connection_use_denied`; spec R5.9;
      ADR-0104 (Accepted) quyết 5), một chủ của độ sâu, không tự đọc `platform.effective_grants`;
    - chỉ khi `call_site` là `egress` (spec R5.15, R5.16; ADR-0115 (Accepted) quyết 2: "before a run's egress call"),
      với lý do `credential_revoked`: `run_requested_at` NULL (đóng khi thiếu); một trường của
      `ConnectorCatalogPort.secret_fields(connector_key, connector_major)` không còn phiên bản nào có `revoked_at`
      NULL hay ở tương lai theo `platform.secret_status` của ticket 02, kể cả khi trường không còn dòng nào, hay cổng
      trả None (trình kết nối không có ở lớp nền tảng); hay `compromised_at` khác NULL và
      `run_requested_at <= compromised_at`.
      Một lượt được xin trước một lần xoay mà Kết nối chưa bị thu hồi vì lộ sau đó qua được (spec R5.17, R1.14), và lời
      gọi mở phiên bản mới qua `platform.open_secret` là việc của ticket 05. `ConnectorCatalogPort` (bên dùng khai):
      `secret_fields(connector_key, connector_major) -> frozenset[str] | None`, danh sách trường bí mật mà `auth` của Bản
      mô tả khai; ticket này gắn ở composition root một cài đặt trả None cho mọi khóa, như `CatalogueHostsPort` của ticket
      03, tới khi ticket 05 gắn danh mục của Bản mô tả (`smtp@1.0.0`: `{password}`); test dùng bản giả. Ba chỗ gọi không
      thuộc ticket này: lúc duyệt giá trị Điểm gắn và lúc nhận lượt ở tenant-config/05 (bước 9; R8.4, R8.9), trước lời
      gọi ra ngoài ở `ManifestActionHandler` và `SmtpEgress` của ticket 05; ticket này hỏi thẳng hàm (failure-modes #5).
      Bên gọi ngoài `dw_platform` tới hàm qua một Protocol chính nó khai, composition root gắn hàm này (CLAUDE.md,
      Non-negotiable architecture); hàm đọc trong một giao dịch ngắn của riêng nó với `app.tenant_id` là
      `context.tenant_id` (`set_config(..., true)`), nên một lần tắt đã commit trước lời hỏi luôn được thấy.
      2a. Thu hồi vì lộ (spec R1.15, R1.16, R5.16; V4.35; H-28): cùng migration của bước 1 thêm cột
      `compromised_at timestamptz` NULL, không DEFAULT, vào `platform.connections` (grant cột của `dw_app` không có UPDATE
      trên nó, ticket 02 bước 2), trigger `platform.guard_connection_compromised_at()` từ chối mọi UPDATE đặt cột về NULL
      hay lùi nó về trước giá trị đã có, và hàm SECURITY DEFINER `platform.revoke_connection_secrets(p_connection_id uuid)`
      (`SET search_path = pg_catalog, platform`, REVOKE ALL FROM PUBLIC, GRANT EXECUTE cho `dw_app`; lấy công ty từ
      `app.tenant_id`, không nhận tham số công ty), trong một giao dịch: khóa dòng Kết nối `FOR UPDATE`, ghi
      `revoked_at = now()` cho mọi dòng `platform.secret_envelopes` của Kết nối có `revoked_at` NULL hay ở tương lai,
      không đụng `replaced_at`, rồi `compromised_at = now()` trên dòng Kết nối; Kết nối không thấy được dưới
      `app.tenant_id` → không ghi gì, route trả 404. Route `POST /api/v1/connections/{id}/revoke-credentials` theo luật
      quyền của bước 4 với khóa `connections.manage`, một người (spec R1.15; Đạt, Q-h3); audit
      `connection.credentials_revoked` cùng giao dịch, không mang giá trị bí mật. Lần xoay vẫn là `PATCH` với giá trị mới
      của trường, qua `platform.put_secret` của ticket 02.
3. `ConnectionDependentsPort` khai ở đây, cho "Được dùng bởi" và chặn xóa: `dependents(context, connection_id) ->
ConnectionDependents(total: int, visible: list[DependentRef(kind, id, name)])`, `total` đếm mọi thành phần phụ thuộc,
   `visible` chỉ những thành phần người gọi đọc được (tenant-config:R3.4, R3.7); `DELETE` đọc `total`, `GET .../dependents`
   trả cả hai, schema vào OpenAPI ở bước 7. Bên đáp ứng là tenant-config/05 (bước 11:
   đọc `studio.dependencies` cộng giá trị Bộ giá trị gắn đã duyệt trong `platform.config_versions`); workflow-engine và
   agent-builder không cài nó (tenant-config:R3.7). Tới khi tenant-config/05 thay ở composition root, ticket này gắn một
   cài đặt trả danh sách rỗng, đúng sự thật vì trước tenant-config/05 không Bộ giá trị gắn nào mang giá trị Kết nối và
   tài liệu chỉ mang tên Điểm gắn (DO-06); R5.8 kiểm qua một bản giả theo đúng hợp đồng port (trả danh sách phụ thuộc
   của fixture). Port ném lỗi → `DELETE` không xóa gì và lỗi nổi lên (đóng khi thiếu).
4. Routes `GET`, `POST /api/v1/connections`, `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`,
   `POST /api/v1/connections/{id}/disable`, `.../enable`, `.../revoke-credentials` (bước 2a),
   `GET /api/v1/connections/{id}/dependents`. Một luật quyền cho mọi route, như `ArtifactService`
   (`packages/python/dw_studio/src/dw_studio/core/application/service.py:1-9`, `:170-176`), độ sâu từ
   `platform.workspace_reach` (ADR-0104 (Accepted) quyết 5; spec R5.18):
    - đọc (`GET` danh sách, `GET {id}`, `.../dependents`): danh sách chỉ gồm Kết nối có `owning_workspace_id` trong
      `workspace_reach(..., 'connections.read')`; theo id, Kết nối của công ty khác hay ngoài tầm với đó → 404
      `not_found`, port phụ thuộc không được hỏi;
    - ghi (`PATCH`, `DELETE`, `.../disable`, `.../enable`, `.../revoke-credentials`): trước hết luật đọc (404), rồi
      `owning_workspace_id` trong `workspace_reach(..., 'connections.manage')`, không thì 403 `permission_denied`,
      không dòng nào đổi, không yêu cầu phê duyệt nào mở;
    - `POST`: `owning_workspace_id` là workspace của ngữ cảnh truy cập (thân yêu cầu không có trường đó), và workspace
      đó phải nằm trong `workspace_reach(..., 'connections.manage')`, không thì 403.
      `POST` nhận `name`, `connector_key`, `connector_major`, `external_account` bắt buộc và không rỗng (thiếu → 422, để
      R5.21 không bị vòng qua bằng NULL), `share_scope` chỉ `workspace` (giá trị khác →
      422; spec R5.20) và mọi trường bí mật mà `ConnectorCatalogPort.secret_fields` trả (thiếu, thừa hay cổng trả None →
      422), lưu từng trường qua `platform.put_secret` (ticket 02), tạo dòng `active`, cùng một giao dịch; còn một Kết nối
      chưa `revoked` cho cùng `(connector_key, external_account)` → 409 `conflict` với `details.reason_code`
      `connection_exists` (R5.21), đọc từ tên ràng buộc `uq_connections_account_live`. `PATCH` chỉ nhận
      `name` và giá trị mới của trường bí mật mà `ConnectorCatalogPort.secret_fields` khai (xoay; trường lạ hay cổng trả
      None → 422), ở mọi status trừ `revoked`, không nhận `status`, `owning_workspace_id` (cột không đổi: spec R1.7,
      ticket 02), `share_scope`, `connector_key`, `connector_major`, `external_account` (tài khoản là danh tính của Kết
      nối: đổi tài khoản là xóa rồi tạo). `.../disable` một người, có hiệu lực ngay
      (`active → disabled`); Kết nối không `active` → 409 `conflict` với `details.reason_code` `connection_not_active`,
      không audit, `disabled_at` không đổi. `DELETE` khóa dòng `FOR UPDATE`, hỏi `ConnectionDependentsPort`, còn phụ thuộc → 409
      `connection_in_use`, không xóa; xóa thì FK CASCADE xóa phong bì (ticket 02). Trường bí mật `writeOnly`; phản hồi chỉ
      nêu tên trường đã cấu hình. `Idempotency-Key` cho mọi `POST` và `PATCH`, tùy chọn như ADR-0108 (Accepted) quyết 4: lần phát lại
      với cùng khóa trả câu trả lời đã lưu; vân tay của thân bỏ giá trị trường bí mật (chỉ giữ tên trường), vì một mã băm
      không khóa của mật khẩu ngoài Kho bí mật đoán ngược được (spec R1.2), nên cùng khóa với giá trị bí mật khác trả câu
      trả lời đã lưu mà không lưu giá trị mới; màn của ticket 07 sinh khóa mới cho mỗi lần gửi.
5. Bật lại hai người (D11): `POST .../enable` cho một Kết nối `disabled`, sau luật ghi của bước 4, khóa dòng Kết nối
   `FOR UPDATE`; Kết nối không `disabled` → 409 `conflict` với `details.reason_code` `connection_not_disabled`; đã có
   một yêu cầu `connections.enable` `pending` cho Kết nối → 409 `conflict` với `details.reason_code` `enable_pending`,
   không mở yêu cầu thứ hai; hỏi `platform.checker_candidates` của tenant-rbac/02 với khóa `connections.manage`, người
   gửi và workspace sở hữu của Kết nối: rỗng → 409 `conflict` với `details.reason_code` `no_checker_available`, không mở
   yêu cầu, status giữ `disabled` (R5.13); không thì trả 202 với một yêu cầu phê duyệt không lượt chạy
   `connections.enable`, `required_scope` `connections.manage`, `workspace_id` là workspace sở hữu của Kết nối (không
   phải workspace đang làm việc của người gửi), để tập người mà `checker_candidates` tìm và tập người thấy và quyết được
   yêu cầu (`ApproveAndResumeService._visible`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py`)
   đọc cùng một workspace; payload chỉ mang id kết nối; Connection status giữ `disabled`. `connections.enable` vào
   `strict_approval_prefixes` bằng `|=` ở API và worker, nên người gửi tự quyết nhận 409 `conflict` với
   `details.reason_code` `second_person_required` (R5.11; ADR-0104 (Accepted) quyết 11). Handler
   `connections.enable.decided` đăng ký ở composition root của worker, chạy lặp lại không đổi kết quả theo id phê duyệt:
   duyệt → khóa dòng Kết nối `FOR UPDATE`; dòng không còn, status khác `disabled`, hay `created_at` của yêu cầu không
   sau `disabled_at` (Kết nối bị tắt lại sau khi yêu cầu mở) → không ghi gì, không audit, kết thúc không lỗi để outbox
   không thử lại (R5.19); không thì đặt `app.connection_enable_approval` là id phê duyệt, `disabled → active`, audit
   `connection.enabled` đứng tên người quyết, `details.lane` `outbox`, trong một giao dịch; từ chối → không đổi gì.
6. Audit, mỗi sự kiện trong giao dịch của thay đổi, đứng tên người gọi (handler: người quyết, ADR-0011 (Accepted)), ở
   công ty và workspace sở hữu của Kết nối (không phải workspace đang làm việc của người gọi), không giá trị bí mật: `connection.created`, `connection.updated` (`details` nêu cột đã đổi và, với trường bí mật,
   tên trường cùng `secret_version` mới), `connection.disabled`, `connection.enabled`, `connection.deleted`,
   `connection.credentials_revoked`; nhãn trong mảnh `configs/copy/audit_actions.d/connections-and-vault.yaml` (H-21),
   mảnh mà ticket 03 tạo. `connection.revoked`, thông báo `needs_reauth` và outbox `connection.status_changed` v1 không
   có bên ghi hay bên đọc ở P1, nên đi cùng bộ điều phối OAuth W2 (spec Ngoài phạm vi; failure-modes #1).
7. `make generate-contracts`, để ticket 07 dựng màn `/studio/connections` trên client đã sinh.

## Tiêu chí chấp nhận

- [ ] R5.1: người giữ `connections.manage` với tới workspace đang làm việc tạo một Kết nối với mọi trường bí mật mà
      bản giả của `ConnectorCatalogPort` khai → mỗi trường một phong bì qua `platform.put_secret`, dòng `active` có
      `owning_workspace_id` là workspace đó, audit `connection.created` cùng giao dịch ở workspace đó; thiếu một trường,
      thêm một trường lạ, thiếu `name` hay `external_account`, hay `connector_key` mà cổng trả None → 422, không dòng
      nào; `PATCH` mang `external_account` → 422; `.../disable` lên Kết nối đã `disabled` → 409
      `connection_not_active`, `disabled_at` không đổi; vân tay của khóa chống lặp đã lưu không chứa canary; ghi audit ném lỗi → không dòng Kết nối,
      không phong bì nào.
- [ ] R5.2 (CV12): duyệt mọi schema 2xx của router kết nối → không trường bí mật; `GET` sau khi tạo không chứa giá
      trị canary; trường bí mật đã lưu hiện "Đã cấu hình"; audit `connection.created` và `connection.updated` của một
      lần xoay không chứa canary.
- [ ] R5.3 (CV13): hỏi thẳng `connection_usable` với `context.tenant_id` của công ty B và id Kết nối của công ty A →
      false, `connection_not_found`; `dw_app` với `app.tenant_id` của B gọi `platform.revoke_connection_secrets` với id
      của A → không phong bì, không `compromised_at` nào đổi; gỡ vế công ty khỏi câu UPDATE của hàm hay đặt
      `app.tenant_id` từ dòng Kết nối thay vì từ `context` → ca đó đỏ. Công ty B gọi `GET {id}`, `PATCH`, `DELETE`, `.../disable`, `.../enable`, `.../dependents` và
      `.../revoke-credentials` với id của công ty A → 404, dòng của A không đổi, không dòng
      `platform.approval_requests` nào, port phụ thuộc giả không được hỏi; `GET` danh sách của B không có Kết nối nào
      của A; `DISABLE ROW LEVEL SECURITY` trên `platform.connections` trong migration thử → test đỏ.
- [ ] R5.18 (CV31): trong một công ty, người giữ `connections.read` và `connections.manage` chỉ ở workspace W1 → `GET`
      danh sách không có Kết nối của W2, `GET {id}`, `.../dependents` của W2 → 404; người giữ `connections.read` ở mức
      công ty và `connections.manage` chỉ ở W1 → `PATCH` (xoay `api_key`), `DELETE`, `.../disable`, `.../enable`,
      `.../revoke-credentials` trên Kết nối của W2 → 403, không phong bì, dòng hay yêu cầu nào đổi; `POST` trong ngữ cảnh
      W2 → 403; người giữ khóa ở mức công ty → nhận; gỡ phép kiểm `workspace_reach` ở luật ghi → `PATCH` của W1 lên
      Kết nối W2 thành công, test đỏ.
- [ ] R5.4 (CV14): hỏi thẳng `connection_usable` với `workspace_id` khác `owning_workspace_id` → false,
      `connection_out_of_scope`; cùng workspace → true; gỡ kiểm workspace → test đỏ.
- [ ] R5.20 (CV14): `POST` với `share_scope` `owner` hay `workspace_subtree` → 422, không dòng; `PATCH` mang
      `share_scope` → 422; dòng có `share_scope` `workspace_subtree` ghi thẳng bằng vai migrator → `connection_usable`
      false, `connection_out_of_scope`; cho hàm coi mọi `share_scope` như `workspace` → test đỏ.
- [ ] R5.5 (CV15): `.../disable` → status `disabled` ngay, audit `connection.disabled`, `connection_usable` ở cả ba
      `call_site` → false, `connection_disabled`; gỡ kiểm status trong hàm → test đỏ.
- [ ] R5.6 (CV15): `UPDATE` Connection status `revoked → active`, `revoked → disabled` hay `disabled → pending` bằng
      `dw_app` → trigger từ chối (23514), dòng không đổi; INSERT với `disabled` → từ chối; `active → disabled` → nhận và
      `disabled_at` có giá trị; gỡ trigger → test đỏ.
- [ ] R5.8: `DELETE` khi bản giả của `ConnectionDependentsPort` trả một phụ thuộc → 409 `connection_in_use`, không
      xóa; không phụ thuộc → xóa, phong bì của Kết nối xóa theo, audit `connection.deleted` cùng giao dịch; bản giả ném
      lỗi → không xóa; `connection_usable` với id đã xóa → false, `connection_not_found`.
- [ ] R5.9 (CV14): `principal_id` không giữ `connections.use` với tới workspace của ngữ cảnh → false,
      `connection_use_denied`, ở cả ba `call_site`; giữ ở một workspace khác → false; giữ ở mức công ty → true;
      `principal_id` NULL → false; gỡ kiểm `connections.use` → test đỏ.
- [ ] R5.10 (CV21): `POST .../enable` cho Kết nối `disabled` → 202 kèm id phê duyệt `connections.enable` có
      `required_scope` `connections.manage` và `workspace_id` là workspace sở hữu; Connection status vẫn `disabled`,
      `connection_usable` vẫn false; `PATCH` mang `status: active` → 422, status không đổi; Kết nối `active` → 409
      `connection_not_disabled`; gửi lần hai khi yêu cầu đầu còn `pending` → 409 `enable_pending`, vẫn một yêu cầu; đổi
      status ngay ở `POST` → test đỏ.
- [ ] R5.11 (CV21): người gửi tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`, status
      không đổi; người không giữ `connections.manage` hay chỉ giữ nó ở workspace khác workspace sở hữu quyết → 404;
      bỏ `connections.enable` khỏi tiền tố nghiêm → test đỏ.
- [ ] R5.12 (CV21): người thứ hai giữ `connections.manage` với tới workspace sở hữu duyệt → `active`, audit
      `connection.enabled` đứng tên người đó với `details.lane` `outbox`; handler chạy lại cùng quyết định → không đổi gì
      thêm, không audit thứ hai.
- [ ] R5.19 (CV21): yêu cầu mở lúc t0, Kết nối được bật bằng đường khác rồi tắt lại lúc t1, yêu cầu được duyệt sau t1
      → handler không đổi gì, không audit, kết thúc không lỗi; `UPDATE ... SET status = 'active'` từ `disabled` bằng
      `dw_app` không đặt `app.connection_enable_approval`, hay đặt id của một yêu cầu `pending`, của Kết nối khác hay mở
      trước `disabled_at` → trigger từ chối; gỡ phép kiểm yêu cầu khỏi trigger → `UPDATE` thẳng thành công, test đỏ;
      gỡ phép so `disabled_at` khỏi handler → ca t0, t1 đỏ ở handler (trigger vẫn chặn, nên test hỏi từng lớp).
- [ ] R5.13 (CV21): chỉ người gửi giữ `connections.manage` với tới workspace sở hữu của Kết nối → `POST .../enable`
      trả 409 `conflict` với `details.reason_code` `no_checker_available`, không dòng `platform.approval_requests` nào,
      status vẫn `disabled`; thêm người thứ hai giữ khóa ở workspace đó → 202; gỡ kiểm người duyệt → test đỏ.
- [ ] R5.21 (CV21): Kết nối `disabled` cho `(smtp, a@x.vn)`, `POST` một Kết nối mới cùng `connector_key` và
      `external_account` → 409 `conflict` với `details.reason_code` `connection_exists`, không dòng nào; Kết nối cũ đã
      xóa → `POST` nhận, audit `connection.deleted` và `connection.created` cùng nêu tài khoản; `POST` với `A@X.vn ` khi Kết nối
      `disabled` có `a@x.vn` → 409 `connection_exists`; đổi index về chỉ dòng `active` hay bỏ `lower` → `POST` lúc Kết nối
      cũ `disabled` thành công, test đỏ.
- [ ] R5.14 (CV14): Kết nối `active`, chủ thể giữ `connections.use` ở workspace của ngữ cảnh: `purpose='tool'` → true;
      `purpose='model'` hay một chuỗi lạ → false, `purpose_not_allowed`; gỡ kiểm `purpose` → test đỏ.
- [ ] R5.15 (CV24): `call_site` `egress`, mọi phiên bản của `api_key` đã thu hồi, rồi xóa hết qua
      `platform.delete_secret` → false, `credential_revoked`; trường còn một phiên bản chưa thu hồi → true; cổng trả None
      → false; `run_requested_at` NULL → false; cùng các dòng ở `call_site` `run_admission` → true (nhánh bí mật chỉ ở
      `egress`); gỡ nhánh "không còn phiên bản chưa thu hồi" → hàm trả true, test đỏ (hỏi thẳng hàm, vì
      `platform.open_secret` của ticket 02 vẫn chặn ở lớp sau, failure-modes #5).
- [ ] R5.16 (CV28): `run_requested_at` t0, thu hồi vì lộ lúc t1 rồi lưu phiên bản mới lúc t2 → `connection_usable` ở
      `egress` false, `credential_revoked`; `run_requested_at` sau t1 → true; bằng đúng `compromised_at` → false; gỡ nhánh
      `compromised_at` → ca t0 qua, test đỏ. Ca đầu-cuối qua `SmtpEgress` (máy chủ giả không nhận gì) ở ticket 05.
- [ ] R5.17 (CV24): `run_requested_at` t0, lưu giá trị mới cho `api_key` lúc t1 (xoay, không thu hồi vì lộ) →
      `connection_usable` ở `egress` true; cho hàm từ chối mọi `run_requested_at` trước phiên bản mới nhất → ca này đỏ.
      Lời gọi mở phiên bản 2 ở ticket 05.
- [ ] R1.15 (CV28): gọi route thu hồi vì lộ cho một Kết nối có `api_key` phiên bản 2 đang dùng và `password` phiên bản
      1 → cả hai phiên bản có `revoked_at` bằng `now()` của giao dịch, `replaced_at` không đổi, `compromised_at` bằng
      cùng thời điểm, một audit `connection.credentials_revoked` không chứa giá trị canary; Kết nối khác cùng công ty
      không đổi; công ty B gọi route với id của công ty A → 404, không dòng nào đổi; người thiếu `connections.manage` với
      tới workspace sở hữu → 403, không dòng nào đổi; `dw_app` UPDATE `compromised_at` → `permission denied`; vai
      migrator đặt nó về NULL hay lùi nó → trigger từ chối; ghi audit ném lỗi → giao dịch lùi, không phiên bản nào bị
      thu hồi; `has_function_privilege` của `dw_provisioner` trên `platform.revoke_connection_secrets` → sai; gỡ vế phong
      bì khỏi hàm → `platform.open_secret` không nêu phiên bản vẫn mở phiên bản 2, test đỏ.
- [ ] R5.9 (CV14): Danh mục quyền: ba khóa có `scope_kind` `workspace`, `risk` và `tenant_grantable` như bước 1;
      `test_permission_catalogue.py` xanh; bỏ hằng `*_SCOPE` của `connections.use` → (c) đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:77`; spec: R5.1
  (quyền theo độ sâu).
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:434-451` (`platform.workspace_reach`), `:476-496`
  (`platform.checker_candidates`, lọc theo workspace khi được nêu); spec: R5.9, R5.13, R5.18.
- `packages/python/dw_studio/src/dw_studio/core/application/service.py:1-9`, `:170-176`; spec: R5.18 (404 khi
  không đọc được, 403 khi đọc được mà không ghi được, theo `workspace_reach`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py` (`_visible` lọc theo workspace của người
  quyết, `holds_stamped_scope`); spec: R5.11, R5.13 (yêu cầu nằm ở workspace sở hữu).
- `db/migrations/versions/ebb17244abc6_permission_catalogue.py:322-345`;
  `db/migrations/versions/b5677d345bc1_tenant_roles.py:1230`; spec:
  Trong phạm vi (cột NOT NULL của `platform.permissions`).
- `packages/python/dw_platform/tests/integration/test_permission_catalogue.py:1-25` (khóa `active` cần bên kiểm mà
  `ast` thấy).
- spec: R1.15, R5, CV12-CV15, CV21, CV24, CV28, CV31; ADR-0115 (Accepted) quyết 1, 2; ADR-0109 (Accepted) quyết 6;
  ADR-0104 (Accepted) quyết 5, 10, 11; ADR-0108 (Accepted) quyết 4; ticket 02 (`platform.connections`,
  `platform.put_secret`, `revoked_at`, `replaced_at`, `platform.secret_status`), ticket 03 (`CatalogueHostsPort` làm
  tiền lệ cổng rỗng ở W1); `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190` (dạng hàm
  SECURITY DEFINER có `search_path` cố định).

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
- 2026-10-25 (agent): lượt h, theo V4.31 của Đạt (bảng cạnh của lượt): màn `/studio/connections` (bước 7 cũ) tách sang
  `.claude/plans/studio/connections-and-vault/issues/07-man-ket-noi.md`, R5.7 dời theo; gỡ Blocked by
  studio-skeleton/03 (ticket 07 chờ nó). Theo V4.35 và H-28: `connection_usable` thôi nhận `pinned_secret_versions`,
  kiểm "không còn phiên bản chưa thu hồi" và `compromised_at` so với `created_at` của lượt (bước 2; R5.15-R5.17); bước 2a
  thêm thu hồi vì lộ (`compromised_at`, trigger chỉ tiến, `platform.revoke_connection_secrets`, route
  `revoke-credentials`, audit `connection.credentials_revoked`; R1.15, CV28), người được làm: người giữ `connections.manage`, một người (Q-h3, 26/10).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness (builder check và boundary walk: năm subagent,
  một builder và bốn boundary chia sáu ranh giới) CHƯA ĐẠT lượt đầu, 2 CRITICAL, 10 HIGH, sửa theo khuyến nghị; mỗi
  quyết định cùng `Nếu sai thì:` ở mục Quyết định của spec, dòng 3/11/2026 của ticket 04, (a)-(p). CRITICAL: (a) test âm
  chéo công ty chỉ phủ bốn route (CLAUDE.md, Tenancy and authorization): R5.3 nay phủ mọi route, danh sách và
  `dependents` gồm; (b) quyền theo id không nêu workspace neo, không test âm khác workspace: một luật đọc 404, ghi 403 theo
  `platform.workspace_reach`, `POST` ở workspace đang làm việc (R5.18, CV31), và `connections.use` cũng đọc qua
  `workspace_reach`. HIGH: (c) tiêu chí đòi Bộ gọi ra ngoài và máy giả mà ticket không gọi ra ngoài: tiêu chí hỏi thẳng
  hàm, ca đầu-cuối ở ticket 05; (d) danh sách trường bí mật phải có không có nguồn: `ConnectorCatalogPort` rỗng ở W1;
  (e) chủ thể, chỗ gọi và `run_requested_at` NULL: `UsableContext` với `call_site` bắt buộc, NULL đóng; (f) bảng chuyển
  trạng thái, `disabled → active` chỉ qua yêu cầu đã duyệt (R5.19), `pending`, `needs_reauth`, `revoked` và sự kiện của
  chúng sang W2; (g) `share_scope` khác `workspace` từ chối (R5.20); (h) cột của ba khóa quyền; (i) yêu cầu bật lại nằm ở
  workspace sở hữu, một yêu cầu chờ mỗi Kết nối, handler bỏ qua yêu cầu cũ; (j) `test` không có gì để gọi ở ticket này:
  route và `connection.tested` sang ticket 05; (k) `DELETE` không audit, port lỗi: `connection.deleted`, đóng khi lỗi;
  (l) tạo mới vòng qua bật lại hai người: unique theo dòng chưa `revoked` (R5.21). Lượt kiểm lại (builder check mới)
  thêm 4 HIGH, sửa: (m) vân tay `Idempotency-Key` bỏ giá trị bí mật; (n) `external_account` bắt buộc ở `POST`, không đổi
  qua `PATCH`; (o) hình của `ConnectionDependentsPort`; (p) cột `name`. Hai MEDIUM sửa luôn: audit ở workspace sở hữu,
  `.../disable` lên Kết nối không `active` → 409. Lượt kiểm lại thứ hai thêm 1 CRITICAL và 2 HIGH, sửa: (q) test âm chéo
  công ty hỏi thẳng `connection_usable` và `platform.revoke_connection_secrets`, không chỉ qua route (CLAUDE.md;
  failure-modes #5); (r) unique theo `lower(external_account)`, `POST` bỏ khoảng trắng; (s) ticket 02 bước 1 ghi
  `name`, `disabled_at`, `uq_connections_account_live` và trigger trạng thái là của ticket này (sửa ticket 02 vì
  mâu thuẫn, không đổi gì ticket 02 dựng). Không tách ticket ready-for-human:
  không bước nào cần tài khoản nhà cung cấp hay bí mật triển khai (Chờ Đạt 20, DO-20 ở ticket 01 và 06).
- 2026-11-03 (agent): MEDIUM, chưa sửa: (M1) `platform.checker_candidates` đếm người giữ khóa mà không đòi
  `approvals.decide`, trong khi `ApproveAndResumeService._authorize` đòi cả hai, nên một yêu cầu có thể nằm chờ không ai
  quyết được (người gửi rút được yêu cầu của mình, nên `enable_pending` không kẹt mãi): seam chung của mọi phê duyệt
  hai người, chủ là tenant-rbac; (M2) `last_used_at` và `scopes` không có bên ghi ở P1 (ticket 05 ghi `last_used_at` sau
  lời gọi thành công, `scopes` là của OAuth W2); (M3) xoay (`platform.put_secret`) chạy song song với thu hồi vì lộ:
  `revoke_connection_secrets` khóa dòng Kết nối, `put_secret` của ticket 02 thì không, nên một phiên bản ghi trong giao
  dịch bắt đầu trước lần thu hồi có thể sống; hướng an toàn vì lượt cũ vẫn bị `compromised_at` chặn; (M4) khóa
  `scope_kind` `workspace` nhận độ sâu `workspace_subtree` mà `platform.workspace_reach` chỉ đọc `tenant` và `workspace`
  (`db/migrations/versions/b5677d345bc1_tenant_roles.py:447-448`), nên lần cấp ấy không cho tầm với nào (đóng); chủ
  là tenant-rbac; (M5) `checker_candidates` đếm người giữ khóa ở mức công ty dù họ không có membership ở workspace sở
  hữu, mà `_visible` lọc theo workspace đang làm việc: seam chung, chủ là tenant-rbac; (M6) lúc nhận lượt có nên hỏi
  nhánh bí mật không (ADR-0115 (Accepted) quyết 2 chỉ nói trước lời gọi egress): giữ như ADR; (M7) ticket 03 bước 2
  còn ghi "bên gọi (ticket 04, 05)" mở bí mật trước egress: nay chỉ ticket 05 gọi egress; không đổi hợp đồng của
  ticket 03, sửa chữ khi ticket 03 được dựng; (M8) `connection_usable` đọc dòng Kết nối không qua bộ đệm nào (bước 2).
- 2026-11-03 (agent): MEDIUM của lượt kiểm lại thứ hai, chưa sửa: (M9) schema phản hồi một Kết nối: nêu `compromised_at`,
  `disabled_at`, id yêu cầu `connections.enable` đang chờ, và "Đã cấu hình" chỉ khi trường còn phiên bản chưa thu hồi
  (theo `platform.secret_status`), để ticket 07 không đổi snapshot; (M10) `SecretStore` của ticket 02 chạy trong giao
  dịch của bên gọi để R5.1 lùi cả phong bì khi audit lỗi, và lời gọi `KmsPort` nằm trước `FOR UPDATE`; (M11)
  `created_at` của yêu cầu `connections.enable` là `now()` của giao dịch, có thể trước `disabled_at` khi giao dịch
  `.../enable` bắt đầu trước lần tắt và chờ khóa: ghi mốc so sánh bằng `clock_timestamp()` sau khi khóa dòng, hay
  người gửi rút yêu cầu; (M12) `GET` danh sách phân trang keyset trên index `(tenant_id, created_at DESC, id DESC)`,
  giới hạn mặc định và trần theo quy ước của app-standards; (M13) hai máy chủ SMTP khác nhau cùng tên đăng nhập trong
  một công ty nhận 409 `connection_exists`: `external_account` của `smtp` do ticket 05 định nghĩa (gợi ý
  `<login>@<host>`).
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
