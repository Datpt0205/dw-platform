# 02 — Hàng rào dữ liệu bị quên, vòng đời tenant, nối danh tính và checkpoint an toàn

Status: resolved (2026-10-29, main)
Blocked by: 01
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.1, R3.2, R3.3, R4.1, R4.2, R4.3, R4.4, R4.5, G1, G2, G3, G4, G5, FH2, FH3, FH4, FH5, FH6, FH7, FH8, FH9, FH10, FH11, FH34

## Mục tiêu

Ba đường đã quên hàng rào (xóa tài liệu tri thức, liệt kê bộ nhớ, dọn checkpoint) được rào theo
tenant và workspace; checkpoint chỉ dựng lại kiểu trong allowlist; tenant đang offboarding không mở
lại được và khóa có hiệu lực từ request kế tiếp; nối danh tính theo quy tắc tạm của ADR-0103 (Accepted)
quyết định 8, áp ngay từ P0 (DO-17.1) (R2, R3, R4, G1-G5, FH2-FH11). Xóa cache ở route khóa là cách tạm
tới tenant-rbac/02; ticket đó và org-and-principals/02 chờ ticket này (OPS-b).

## Việc cần làm

Tri thức (R2.1, R2.2, G1):

1. Viết trước bản vá test hồi quy `test_a_member_deletes_a_document_of_their_own_workspace` (xóa
   tài liệu của workspace mình → 204, tìm kiếm của workspace đó không còn trả nó); test xanh trước và
   sau bản vá.
2. `KnowledgeGateway.soft_delete_document`: UPDATE `knowledge.documents` thêm điều kiện `tenant_id`
   và `workspace_id` của AccessContext và `scope = 'tenant'`, có `RETURNING id`; 0 dòng →
   `NotFoundError` (route trả 404, không phân biệt "không có" với "không phải của bạn"), kể cả khi tài
   liệu đã mang `status = 'deleted'` (điều kiện `status <> 'deleted'`, nên lần xóa thứ hai không ghi
   audit thứ hai); chỉ khi có
   dòng mới cập nhật `knowledge.chunks` và ghi audit `knowledge.document.deleted` (tenant, workspace,
   người gọi, `document_id`) trong cùng giao dịch; tombstone vector sau khi giao dịch commit.
3. `VectorIndexPort.tombstone_document` và `delete_document` nhận thêm `tenant_id`; filter Qdrant của
   tài liệu là `must=[source_document_id, tenant_id]` trong adapter Qdrant, cùng điều kiện trong
   `InMemoryVectorIndexAdapter`; mọi nơi gọi (ingest trong `gateway.py`, purge trong `retention.py`)
   truyền tenant của dòng tài liệu.

Bộ nhớ (R2.3):

4. `MemoryService.list_items`: thêm điều kiện phân loại thuộc `classifications_for_clearance` của
   clearance trong AccessContext, cùng chủ với `recall`; thứ tự và con trỏ giữ nguyên.

Checkpoint (R2.4, R2.5, G5):

5. `SqlCheckpointRetention.prune`: `newer` và `recent` so thêm `tenant_id`; truy vấn chọn thêm
   `tenant_id`; DELETE trên `platform.run_checkpoint_writes` và `platform.run_checkpoints` theo bộ bốn
   `(tenant_id, thread_id, checkpoint_ns, checkpoint_id)`.
   5a. Test kiến trúc `packages/python/dw_platform/tests/unit/test_drain_setting_scan.py`, theo mẫu
   `packages/python/dw_platform/tests/unit/test_key_tables_scan.py`: quét mọi `*.py` dưới `apps` và
   `packages` ngoài thư mục `tests`, bằng AST: mọi hằng chuỗi chứa `app.worker_drain` (trong
   `set_config`, `SET [LOCAL]` hay làm giá trị tham số), và mọi `from <module được miễn> import <tên>`
   mà tên đó trong module được miễn là một hằng chứa `app.worker_drain`; so với
   `EXEMPT: dict[str, str]` (module → lý do) đóng băng gồm bảy adapter ở Hiện trạng (R2.6, FH34).
   Docstring (hằng chuỗi đứng một mình đầu module, lớp hay hàm) không tính. Ngoài `apps/worker`, phép
   quét đỏ thêm ở `import <module được miễn>`, ở `from <package> import <module được miễn>` và ở
   `from <module được miễn> import <tên>` khi `<tên>` là
   lớp hay hàm cấp module mà thân dùng hằng drain của module đó (tìm bằng AST trên chính module được
   miễn, không danh sách tay).
   5b. Tách `IngestJobStore.claim_next` sang lớp mới `IngestJobQueue` trong `dw_knowledge/ingest_jobs.py`
   (cùng `session_factory`, `clock`, `id_generator`); worker dựng nó ở
   `apps/worker/src/dw_worker/composition.py` và `consumers/ingest.py` gọi nó; `IngestJobStore` mà API
   dựng không còn đặt drain.
6. `SqlAlchemyCheckpointSaver` nhận serializer qua constructor thay vì dựng cứng `JsonPlusSerializer()`;
   composition root (`apps/api/src/dw_api/bootstrap/runtime.py`, nơi duy nhất dựng saver hôm nay)
   dựng `JsonPlusSerializer(allowed_msgpack_modules=ALLOWED)` với `ALLOWED` là một tuple tường minh
   các cặp (module, tên kiểu) đặt ở một module của composition root. Không dùng biến môi trường
   `LANGGRAPH_STRICT_MSGPACK` (ADR-0112 (Accepted) quyết định 10).
7. Lập `ALLOWED` bằng đo, không đoán (FOG-37): chạy integration của `dw_agent_runtime` và
   `apps/worker` với một serializer ghi lại mọi kiểu được nạp, rồi liệt kê đúng các kiểu đó; ghi danh
   sách và cách đo vào Comments. Đây là phép đo của discovery/14 phần FOG-37: discovery/14 đã có
   `## Answer` thì trỏ về đó, chưa có thì discovery/14 đóng phần này bằng một dòng trỏ tới Comments ở
   đây (OPS-j).
8. Xác minh advisory CVE-2025-64439 đối với langgraph-checkpoint 4.2.0 đã khóa; ghi kết luận vào
   Comments.

Vòng đời tenant (R3.1, R3.2, R3.3):

9. `ProvisioningService.set_tenant_status` (khóa, mở khóa) gọi
   `SqlProvisioningRepository.set_tenant_status(tenant_id, status, only_from=("active", "locked"))`:
   UPDATE `platform.tenants` thêm `status IN (...)` khi có `only_from`; 0 dòng mà tenant tồn tại →
   `ConflictError` với `details.reason_code = "tenant_offboarding"` (409); tenant không tồn tại vẫn 404.
   `initiate_offboarding` và `finalize_offboarding` gọi không `only_from`, như hôm nay; trigger của bước
   10 canh chúng.
10. Revision Alembic mới `db/migrations/versions/*_tenant_status_and_identity_guards.py` (id ngẫu
    nhiên của alembic): hàm `platform.guard_tenant_status()` và trigger BEFORE UPDATE OF status trên
    `platform.tenants`, với mọi vai, từ chối bước rời `offboarding` tới giá trị khác `offboarded` và
    bước rời `offboarded` tới giá trị khác `offboarding`, bằng
    `RAISE ... USING ERRCODE = 'check_violation'` và tên `ck_tenants_status_transition`; giữ nguyên
    trạng thái (`NEW.status = OLD.status`) luôn nhận. Các bước khác giữ như hôm nay (Quyết định
    29/10/2026 của spec).
11. Route `POST /api/v1/platform/tenants/{tenant_id}/lock`, `POST /api/v1/platform/tenants/{tenant_id}/unlock`
    và `POST /api/v1/platform/tenants/{tenant_id}/offboard` gọi
    `CachePort.delete_pattern(tenant_cache_pattern(tenant_id))` sau khi trạng thái đổi; container của
    API truyền cache cho các route này như `admin_console.py` đang làm. Ba lời gọi này là cách tạm tới
    tenant-rbac/02: ticket đó đưa phiên bản quyền vào khóa cache, gỡ ba lời gọi và đổi phép đột biến
    của FH8 sang gỡ trigger `bump_access_version` trên `platform.tenants`.

Nối danh tính (R4.1-R4.4, G2-G4), áp ngay theo DO-17.1:

12. `VerifiedClaims` thêm `email_verified: bool = False`; `KeycloakTokenVerifier` đặt
    `claims.get("email_verified") is True`; `DevTokenVerifier` phát `email_verified: true` (chỉ issuer
    `dw-dev`).
13. `SqlIdentityBootstrap._resolve_user` theo thứ tự của ADR-0103 (Accepted) quyết định 8: (a) danh
    tính đăng nhập `(issuer, subject)`; (b) subject lưu trên user chỉ khi issuer là `dw-dev`; (c) email
    chỉ khi `email_verified` đúng, user chưa có danh tính đăng nhập nào và không là người vận
    hành hay nhân viên `support_staff` (đọc như `bootstrap` đang đọc hai danh sách đó), sau khi khóa
    khóa tư vấn của giao dịch `pg_advisory_xact_lock` trên id của user (không `SELECT ... FOR UPDATE`, vì
    ticket 03 thu UPDATE của `dw_app` trên `platform.users`) để hai lần đăng nhập đầu cùng lúc không
    cùng qua; (d) email
    trùng một user có sẵn mà không qua (c) → `PermissionDeniedError` 403 với
    `details.reason_code = "identity_email_in_use"`, không ghi dòng nào; (e) còn lại tạo user mới, email
    NULL khi `email_verified` không đúng (R4.5); INSERT `ON CONFLICT (subject) DO NOTHING RETURNING id`,
    khi xung đột thì chỉ đọc lại danh tính `(issuer, subject)` (lần đăng nhập đầu song song đã thắng),
    không có thì `PermissionDeniedError` 403 với `details.reason_code = "identity_subject_in_use"`, không
    ghi dòng nào (R4.3); không đọc lại user theo `users.subject`.
14. `SqlMembershipLookup.find_access` bỏ nhánh khớp `users.subject` khi issuer khác `dw-dev`.
15. Cùng revision ở bước 10: trigger `platform.guard_privileged_login_identity()` BEFORE INSERT trên
    `platform.external_identities` từ chối danh tính đăng nhập (provider không thuộc liên kết chat)
    cho người vận hành hay nhân viên `support_staff` khi `current_user` khác `dw_provisioner`
    (`ck_external_identities_privileged_relink`; ADR-0103 (Accepted) quyết định 8); trigger BEFORE
    DELETE từ chối xóa danh tính đăng nhập khi `current_user` không giữ `rolbypassrls` theo `pg_roles`
    (`ck_external_identities_login_kept`), để xóa dây chuyền từ `platform.users` chạy dưới chủ bảng vẫn
    qua (ghi điều đo được vào Comments); `dw_platform/testing/seed_env.py` ghi danh tính Keycloak trước
    khi đặt người vận hành và bỏ qua danh tính đã có, vì trigger BEFORE INSERT chạy cả khi
    `ON CONFLICT DO NOTHING` sẽ bỏ dòng; REVOKE UPDATE, TRUNCATE trên
    `platform.external_identities` khỏi `dw_app`. Một test giữ danh sách provider chat trong hai
    trigger bằng `tables.CHANNEL_LINK_PROVIDERS`; quyền mới được khẳng định trong `test_privileges.py`.
16. Sửa docstring đầu `identity_provisioning.py`, comment "Email-based account linking" trong
    `_resolve_user` và comment quyền đầu `zalo_link_repo.py` cho đúng quy tắc và quyền mới.
17. Token của `test_email_links_a_keycloak_login_to_the_imported_user` và token dev của các test lời
    mời mang `email_verified=True`.
18. Đo token thật của realm `dw` có mang `email_verified` không, và realm có IdP brokered nào không;
    ghi kết quả vào Comments. Phép đo trùng
    discovery/23 (FOG-78), chạy trước ticket này nếu kịp mà ticket không chờ nó: có `## Answer` thì trỏ
    về đó, chưa có thì discovery/23 đóng phần này bằng một dòng trỏ tới Comments ở đây (OPS-j).
19. Song song, và trước khi ticket này merge, hỏi dw-proterial (DO-17.1): importer của họ có tạo user
    `<source>:<name>` rồi trông vào nối email ở lần đăng nhập đầu không, và IdP của họ có gửi
    `email_verified` không; ghi câu trả lời vào Comments. Nếu IdP không gửi, những người đó nhận 403
    `identity_email_in_use`: báo Đạt chọn mã nhận lời mời sớm hơn W2 hay một đường nối do quản trị viên
    làm; quy tắc của ticket này không đổi.

## Tiêu chí chấp nhận

- [x] R2.1 (FH2): mở rộng `packages/python/dw_knowledge/tests/integration/test_qdrant_tenant_filter.py`
      với Qdrant thật: tenant B xóa id của A → 404 và tìm kiếm của A vẫn trả tài liệu; workspace 2
      xóa tài liệu workspace 1 → 404; mọi tenant xóa id tài liệu toàn cục → 404 và tài liệu vẫn tìm
      được; gỡ `tenant_id` khỏi filter tombstone → đỏ (ghi Comments).
- [x] R2.2 (FH3): xóa thành công ghi đúng một `knowledge.document.deleted`; audit ném lỗi → tài liệu
      không mang `status='deleted'`; chuyển ghi audit ra sau commit → đỏ.
- [x] R2.3 (FH4): `GET /api/v1/memory/items` với clearance `internal` không trả mục `confidential`
      hay `restricted`; bỏ điều kiện phân loại → đỏ.
- [x] R2.4 (FH5): hai tenant chung `thread_id`, B có checkpoint mới hơn → sau `prune` checkpoint mới
      nhất của A còn; bỏ so `tenant_id` ở `newer` → đỏ.
- [x] R2.5 (FH6): một dòng checkpoint có kiểu ngoài `ALLOWED` → nạp ra dict, không object nào của
      kiểu đó được dựng; đổi allowlist thành `True` → đỏ.
- [x] R2.6 (FH34): sáu module thử dưới `apps/api`: một có `set_config('app.worker_drain', 'on', true)`,
      một nhập `_SET_WORKER_DRAIN` từ `dw_knowledge.ingest_jobs`, một gọi `set_config(:k, 'on', true)`
      với `k='app.worker_drain'`, một nhập `IngestJobQueue` từ `dw_knowledge.ingest_jobs`, một
      `import dw_knowledge.ingest_jobs`, một `from dw_knowledge import ingest_jobs` → test kiến trúc đỏ
      và nêu từng module; các module trong
      `EXEMPT`, `apps/worker`, docstring và thư mục `tests` không làm đỏ; `IngestJobStore` của API không
      làm đỏ; gỡ phép quét, gỡ nhánh lớp hay hàm, hay thêm một tên không lý do → đỏ.
- [x] R3.1 (FH7): `POST /api/v1/platform/tenants/{tenant_id}/unlock` và `/lock` cho tenant
      `offboarding` → 409 `tenant_offboarding`, `status` giữ nguyên; hoàn tất offboarding vẫn đặt
      `offboarded`; gỡ điều kiện trạng thái → đỏ.
- [x] R3.2 (FH7): UPDATE thẳng `offboarded → active` và `offboarding → locked` bằng `dw_provisioner`
      → trigger từ chối với `ck_tenants_status_transition`; `offboarding → offboarded` và
      `offboarded → offboarding` vẫn nhận; gỡ trigger → test SQL đỏ; đổi trigger thành danh sách cấm
      `active`, `locked` → ca `offboarding → setup` (CHECK nới trong giao dịch test) đỏ.
- [x] R3.3 (FH8): với cache giả trung thực (`delete_pattern` xóa thật), thành viên có context trong
      cache, người vận hành khóa tenant → request kế tiếp 403; bỏ lời gọi xóa cache → đỏ.
- [x] R4.1 (FH9): token `email_verified=false` có email trùng user được mời → 403
      `identity_email_in_use`, không thêm dòng danh tính nào; gỡ kiểm `email_verified` → đỏ.
- [x] R4.2 (FH9): email đã xác minh của user đã có danh tính đăng nhập → 403; email đã xác minh của
      người vận hành chưa từng đăng nhập → 403; gỡ từng điều kiện → đỏ.
- [x] R4.3 (FH10): token issuer X có `sub` bằng subject lưu trên user chỉ biết qua issuer Y →
      `find_access` không trả AccessContext, `bootstrap` trả 403 `identity_subject_in_use` và không thêm
      dòng nào; token `dw-dev` theo subject vẫn vào; khôi phục đọc lại user theo `subject` → đỏ.
- [x] R4.4 (FH11): bằng `dw_app` và bằng `dw_migrator`: INSERT danh tính đăng nhập cho người vận
      hành → trigger từ chối; bằng `dw_provisioner`: nhận; bằng `dw_app`: UPDATE một danh tính →
      `permission denied`; DELETE danh tính đăng nhập → trigger từ chối; DELETE danh tính `zalo` vẫn
      nhận; đổi điều kiện INSERT thành `current_user = 'dw_app'` hay thành mọi vai `BYPASSRLS` → ca
      `dw_migrator` đỏ.
- [x] R4.5 (FH9): token `email_verified=false` với email chưa có user → user mới có email NULL; lời
      mời theo email đó sau đó tạo user khác; ghi email chưa xác minh → đỏ.
- [x] G1: `test_a_member_deletes_a_document_of_their_own_workspace` xanh trước và sau bản vá.
- [x] G2: `test_an_invited_person_signs_in_and_finds_their_workspace` xanh với token dev mang
      `email_verified`.
- [x] G3: `test_email_links_a_keycloak_login_to_the_imported_user` xanh với `email_verified=True`.
- [x] G4: `test_relinking_a_user_replaces_their_old_chat` xanh dưới quyền mới.
- [x] G5: `test_pause_restart_resume_approved` xanh với serializer có `ALLOWED`.
- [x] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_knowledge/src/dw_knowledge/gateway.py:549-566`
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:186-194`
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:230-241`
- `packages/python/dw_memory/src/dw_memory/service.py:776-786`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint_retention.py:92-100`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:59-60`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:173-181`
- `packages/python/dw_platform/src/dw_platform/application/provisioning.py:310-314`
- `apps/api/src/dw_api/routes/v1/admin_console.py:303`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:121-199`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:200-211`
- `packages/python/dw_platform/src/dw_platform/adapters/identity/keycloak.py:63-70`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/zalo_link_repo.py:187-222`
- `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:95-99`
- spec: R2, R3, R4, G1-G5, FH2-FH11; si-platform
  `packages/python/platform/si_core/src/si_core/application/identity.py` (ngữ nghĩa
  `email_verified`).

## Comments

- 2026-10-28 (agent): thêm R2.6 và FH34 (bước 5a) theo CRITICAL của checking-plan-readiness trên `59884c8`, áp quyết định 27/10/2026 của Đạt.
- 2026-10-29 (agent, tạm theo ủy quyền): checking-plan-readiness trên `a9573e8`: 0 CRITICAL, 7 HIGH, sửa theo khuyến nghị (Quyết định 29/10/2026 của spec; bước 2, 5a, 5b, 9, 10, 13, 15, 18). MEDIUM cho người làm: tombstone lỗi sau commit để vector sống tới lần purge của retention (đối soát ngoài phạm vi); một kiểu ngoài `ALLOWED` lúc resume nạp ra dict theo R2.5 và run đi tiếp trên dict; `delete_pattern` lỗi sau khi đổi trạng thái thì route trả lỗi, không 204 im lặng; lần nối bị từ chối không có audit (ngoài phạm vi); phép đo `ALLOWED` chạy cả integration của `apps/api`, nơi saver được dựng; user có `users.subject` của issuer khác `dw-dev` mà không có danh tính đăng nhập: đếm trên DB local và ghi vào đây, không backfill.
- 2026-10-29 (agent, tạm theo ủy quyền): lượt xác nhận: 6/7 HIGH đã sửa; một CRITICAL mới (trigger cho mọi vai `BYPASSRLS` thêm danh tính của người vận hành, trái chữ ADR-0103 (Accepted) quyết định 8), một HIGH mới (`SELECT ... FOR UPDATE` cần UPDATE mà ticket 03 thu), hai MEDIUM (email rỗng là NULL; `from dw_knowledge import ingest_jobs`) và một LOW, sửa theo khuyến nghị (bước 5a, 13, 15, R4.4, R4.5, FH11); vì có CRITICAL mới, gate đầy đủ chạy lại một lượt (`wave-close.md` mục 1).
- 2026-10-29 (agent, tạm theo ủy quyền): gate đầy đủ lượt 2 trên `fd23d47`: 0 CRITICAL, 0 HIGH. MEDIUM cho người làm: "refusing to load" của ADR-0112 (Accepted) Consequences đọc là không dựng object của kiểu ngoài `ALLOWED`, đúng R2.5; phép đột biến tombstone của FH2 đỏ qua test gọi thẳng adapter Qdrant với tenant B trên tài liệu của A, vì gateway không tombstone khi 0 dòng; lớp hay hàm "dùng hằng drain" tính bắc cầu trong module (gọi một tên cấp module đã dùng hằng); `tenant_id` của `tombstone_document`, `delete_document` là `UUID` bắt buộc, `knowledge.documents.tenant_id` NOT NULL nên tài liệu toàn cục truyền tenant đã nạp nó; so email theo `lower(email)` ở mọi chỗ như hôm nay; nhánh `dw-dev` chỉ tới được ở profile `local` (`apps/api/src/dw_api/bootstrap/identity.py:16-26`, mọi profile khác bắt `oidc`); mọi user tạo qua đăng nhập đã có dòng danh tính từ baseline (`b890210`), nên R4.3 chỉ chặn subject của importer, lời mời và seed; user email NULL được mời sau đó thành hai user tới khi mã nhận lời mời ở W2; khóa tenant chưa dừng run do worker khởi (thuộc tenant-rbac/02 và runtime); 409 `tenant_offboarding` cho `setup` thuộc spec đưa `setup` vào CHECK; 403 `identity_email_in_use` cho email chưa xác minh giữ theo Quyết định 23/10/2026.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-29 (agent): đã code. Tri thức: `soft_delete_document` cập nhật theo tenant, workspace, `scope = 'tenant'` và `status <> 'deleted'` với `RETURNING`, 0 dòng → `NotFoundError`, audit `knowledge.document.deleted` trong cùng giao dịch, tombstone sau commit; `VectorIndexPort.tombstone_document`/`delete_document` nhận `tenant_id`, filter Qdrant `must=[source_document_id, tenant_id]`, adapter bộ nhớ trong khóa theo `(tenant_id, document_id)`, purge của retention truyền tenant của dòng. Bộ nhớ: `list_items` lọc `classifications_for_clearance`. Checkpoint: `newer`, `recent` so `tenant_id`, DELETE theo bộ bốn. Drain: `test_drain_setting_scan.py`, `IngestJobQueue` tách khỏi `IngestJobStore`. Serializer: saver nhận serializer bắt buộc, `dw_api/bootstrap/checkpoint_serde.py` giữ `ALLOWED`. Tenant: `only_from` ở repository, 409 `tenant_offboarding`, revision `6887b6020075` (trigger trạng thái, hai trigger danh tính, REVOKE UPDATE, TRUNCATE), xóa cache ở lock, unlock, offboard. Danh tính: `email_verified` ở `VerifiedClaims` và hai verifier, `_resolve_user` theo quyết định 8, `find_access` chỉ khớp `users.subject` với `dw-dev`, seed ghi danh tính Keycloak trước người vận hành.
- 2026-10-29 (agent): bước 7, phép đo `ALLOWED` (FOG-37): chạy integration của `dw_agent_runtime`, `apps/worker` và `apps/api` (cả `apps/api` vì saver dựng ở đó, theo MEDIUM của gate) với một plugin pytest và một `sitecustomize` cho tiến trình con, ghi mọi sự kiện `msgpack_unregistered_allowed`/`msgpack_blocked` của `langgraph.checkpoint.serde.jsonplus.emit_serde_event`; không kiểu nào ngoài `SAFE_MSGPACK_TYPES` được nạp, nên `ALLOWED = ()`. Đối chứng dương: một dataclass lạ được ghi lại, serializer mặc định dựng object, serializer có allowlist rỗng trả `dict`. discovery/14 chưa có `## Answer`, nên đây là phép đo của nó cho phần FOG-37 (OPS-j).
- 2026-10-29 (agent): bước 8, CVE-2025-64439: bản vá ở langgraph-checkpoint 3.0.0 (allowlist cho việc dựng kiểu, bỏ đường dự phòng `json`); `uv.lock` khóa 4.2.0, nên không bị ảnh hưởng (GitLab Advisory Database, Wiz, 29/10/2026).
- 2026-10-29 (agent): bước 18, đo trên Keycloak 26 của compose (cổng 18686), realm `dw`, hai user thử tạo rồi xóa qua admin API, đăng nhập qua `dw-web` bằng authorization code + PKCE: access token của user `emailVerified=true` mang `email_verified: true` (boolean); user `emailVerified=false` dừng ở một bước bắt buộc (302 về `login-actions`) và không nhận token; realm không có IdP brokered nào, Organizations tắt. discovery/23 chưa có `## Answer`, nên đây là phép đo của nó cho phần `email_verified` (OPS-j).
- 2026-10-29 (agent): bước 19 chưa làm được: agent không có kênh tới dw-proterial; Đạt hỏi. Quyết định 23/10/2026 của Đạt nói câu trả lời không chặn ticket này, chỉ quyết đẩy mã nhận lời mời sớm hơn W2.
- 2026-10-29 (agent, tạm): bước 13 (b): khớp `users.subject` của `dw-dev` trả user mà không ghi dòng danh tính, vì trigger của bước 15 từ chối `dw_app` thêm danh tính đăng nhập cho người vận hành, và người vận hành của seed (`dev|chi.le`) đăng nhập dev theo đường này. Nếu sai thì: seed ghi trước danh tính `dw-dev` cho người dùng seed, và (b) ghi dòng như (c).
- 2026-10-29 (agent, tạm): G3: user của importer trong test được tạo thẳng bằng một dòng `platform.users`, không qua `bootstrap` với issuer `sugarcrm`, vì đăng nhập cho user đó một danh tính và quy tắc mới đúng là chặn nối email vào user đã đăng nhập; importer thật ghi dòng, không đăng nhập ai. Nếu sai thì: importer ghi danh tính với một provider không tính là đăng nhập.
- 2026-10-29 (agent, tạm): `SqlProvisioningRepository.set_tenant_status` trả trạng thái trước đó (`str | None`) thay cho `bool`, đọc dưới `FOR UPDATE` rồi mới cập nhật, để dịch vụ phân biệt 404 với 409 mà không cần thêm phương thức port. Nếu sai thì: một phương thức `tenant_status` riêng.
- 2026-10-29 (agent, tạm): FH11 ca nhận của `dw_provisioner`: vai đó không có INSERT trên `platform.external_identities` (chưa luồng nào thêm danh tính cho người vận hành), nên test cấp quyền rồi `SET LOCAL ROLE dw_provisioner` trong một giao dịch rollback; migration không cấp thêm quyền. Ca từ chối thử `dw_app` và `dw_migrator`.
- 2026-10-29 (agent, tạm): `JsonPlusSerializer` được dựng trong adapter (`dw_agent_runtime.adapters.checkpoint.allowlisted_serializer`), còn `ALLOWED` ở composition root của API, vì LangGraph chỉ ở adapter runtime và `apps/api` không khai `langgraph` (`scripts/verify_architecture.py`).
- 2026-10-29 (agent, tạm): G1 là test ở gateway trong `test_qdrant_tenant_filter.py` (route chỉ chuyển kết quả của gateway, `NotFoundError` thành 404); G2 xanh với `_Identity` của test mang `email_verified=True` thay cho token dev; R4.5 "lời mời sau đó tạo user khác" khẳng định không user nào giữ email đó, vì lời mời tìm theo `lower(email)`.
- 2026-10-29 (agent, tạm): test dựa vào lỗi R4.3 (user chỉ có `users.subject`, tra bằng issuer IdP) nay tra bằng `dw-dev`: `support_world.py`, `test_permission_sets.py`, `test_zalo_link_repo.py`, `apps/worker/tests/integration/test_zalo_inbound_db.py`; `_Identity` giả của tám file test mang `email_verified=True` (IdP doanh nghiệp đã xác minh).
- 2026-10-29 (agent): mutation check (`mutations/02.yaml`, một đột biến mỗi hàng Kiểm soát FH2-FH11, FH34), `scripts/mutate.py --jobs 1`: 11/11 đỏ. Control của FH8, FH9, FH10 đỏ trong bản chép gói vì `dw_api` và bộ nạp retention terms của `dw_platform` tìm `configs/` theo `__file__`; ba đột biến đó chạy lại tại chỗ bằng chính `_in_place` của script: control xanh, đột biến đỏ. Phát hiện về công cụ (failure-modes #3, cho Đạt): đột biến tại chỗ mà `old` không khớp byte (tệp CRLF) không được áp và script không báo, nên FH7 đã ra "NOT CAUGHT" tới khi tệp đổi về LF; và chế độ chép gói không chạy được với gói tìm `configs/` theo `__file__`.
- 2026-10-29 (agent): `reviewing-feature-security`: (1) tenant: FH2, FH5 và tombstone theo tenant; (2) quyền: R3.1 ở dịch vụ, R3.2 ở PostgreSQL với mọi vai, R4.4 ở PostgreSQL, R3.3 ở cache; (3) tự chủ: không đổi, không công cụ nào mới; (4) nội dung không tin cậy: checkpoint không dựng kiểu ngoài allowlist (FH6); (5) audit: `knowledge.document.deleted` cùng giao dịch (FH3); (6) mặc định: serializer bắt buộc truyền, không mặc định; email chưa xác minh không giữ chỗ (R4.5); trigger danh tính là danh sách cho phép. Không đổi image, lockfile hay compose, nên không cần quét image mới.
- 2026-10-29 (agent): P50/P95/P99 (ms), app thật qua httpx, PostgreSQL thật, 1.000 mục bộ nhớ (một phần năm `confidential`), 320 tài liệu, 20 lượt làm nóng rồi 300 yêu cầu mỗi operation, tuần tự, Qdrant thay bằng adapter trong bộ nhớ (thay đổi nằm ở Postgres), so với `261599b` (mã như `a9573e8`) xuất bằng `git archive`:

    | Operation                                            | Trước (P50/P95/P99) | Sau (P50/P95/P99)  |
    | ---------------------------------------------------- | ------------------- | ------------------ |
    | `GET /api/v1/me` (`find_access`)                     | 17,4 / 22,6 / 26,8  | 16,8 / 21,8 / 26,8 |
    | `GET /api/v1/auth/bootstrap`                         | 22,9 / 30,4 / 37,8  | 24,5 / 31,6 / 38,7 |
    | `GET /api/v1/memory/items`                           | 32,1 / 40,9 / 58,1  | 31,6 / 43,8 / 57,3 |
    | `DELETE /api/v1/knowledge/documents/{id}`            | 31,2 / 39,7 / 48,3  | 34,0 / 42,1 / 48,4 |
    | `POST /api/v1/platform/tenants/{id}/lock`, `/unlock` | 41,4 / 49,2 / 58,5  | 45,1 / 56,0 / 63,2 |

    Mọi operation trong ngân sách; không P95 nào chậm hơn 20%. Khóa và mở khóa chậm nhất (+13,8% P95) vì đọc trạng thái dưới `FOR UPDATE` trước khi cập nhật; xóa tài liệu +6% vì thêm dòng audit.

- 2026-10-29 (agent): dòng Xong đọc theo `.claude/rules/wave-close.md`: cổng nhanh (ruff, format, mypy, `make test-unit` 1548 đạt, `make test-contract`, `make test-architecture`) và integration của các package bị đụng; `make test-integration` đầy đủ chạy ở cuối đợt. Integration của `dw_knowledge`, `dw_memory`, `dw_agent_runtime`, `dw_platform`, `apps/api`, `apps/worker` xanh, trừ `apps/api/tests/integration/test_idempotent_operations.py::test_a_grant_replayed_after_support_is_switched_off_is_refused`, đỏ cả trên `HEAD` sạch (đã thử bằng cách cất thay đổi), không do ticket này; ticket sửa nó còn phải mở. Hạ tầng chạy ở cổng riêng (Qdrant 16333, Valkey 16379, S3 19000) vì các cổng mặc định đang thuộc container của si-platform.
