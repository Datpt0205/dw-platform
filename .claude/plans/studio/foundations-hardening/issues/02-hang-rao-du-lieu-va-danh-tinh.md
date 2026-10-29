# 02 — Hàng rào dữ liệu bị quên, vòng đời tenant, nối danh tính và checkpoint an toàn

Status: needs-triage
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
   quét đỏ thêm ở `import <module được miễn>` và ở `from <module được miễn> import <tên>` khi `<tên>` là
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
    dòng user bằng `SELECT ... FOR UPDATE` để hai lần đăng nhập đầu cùng lúc không cùng qua; (d) email
    trùng một user có sẵn mà không qua (c) → `PermissionDeniedError` 403 với
    `details.reason_code = "identity_email_in_use"`, không ghi dòng nào; (e) còn lại tạo user mới, email
    rỗng khi `email_verified` không đúng (R4.5); INSERT `ON CONFLICT (subject) DO NOTHING RETURNING id`,
    khi xung đột thì chỉ đọc lại danh tính `(issuer, subject)` (lần đăng nhập đầu song song đã thắng),
    không có thì `PermissionDeniedError` 403 với `details.reason_code = "identity_subject_in_use"`, không
    ghi dòng nào (R4.3); không đọc lại user theo `users.subject`.
14. `SqlMembershipLookup.find_access` bỏ nhánh khớp `users.subject` khi issuer khác `dw-dev`.
15. Cùng revision ở bước 10: trigger `platform.guard_privileged_login_identity()` BEFORE INSERT trên
    `platform.external_identities` từ chối danh tính đăng nhập (provider không thuộc liên kết chat)
    cho người vận hành hay nhân viên `support_staff` khi `current_user` không giữ `rolbypassrls`
    (`ck_external_identities_privileged_relink`); trigger BEFORE DELETE từ chối xóa danh tính đăng
    nhập khi `current_user` không giữ `rolbypassrls` (`ck_external_identities_login_kept`); cả hai đọc
    `pg_roles` theo `current_user`, nên vai bảo trì của seed và một xóa dây chuyền từ `platform.users`
    chạy dưới chủ bảng vẫn qua (ghi điều đo được vào Comments); REVOKE UPDATE, TRUNCATE trên
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

- [ ] R2.1 (FH2): mở rộng `packages/python/dw_knowledge/tests/integration/test_qdrant_tenant_filter.py`
      với Qdrant thật: tenant B xóa id của A → 404 và tìm kiếm của A vẫn trả tài liệu; workspace 2
      xóa tài liệu workspace 1 → 404; mọi tenant xóa id tài liệu toàn cục → 404 và tài liệu vẫn tìm
      được; gỡ `tenant_id` khỏi filter tombstone → đỏ (ghi Comments).
- [ ] R2.2 (FH3): xóa thành công ghi đúng một `knowledge.document.deleted`; audit ném lỗi → tài liệu
      không mang `status='deleted'`; chuyển ghi audit ra sau commit → đỏ.
- [ ] R2.3 (FH4): `GET /api/v1/memory/items` với clearance `internal` không trả mục `confidential`
      hay `restricted`; bỏ điều kiện phân loại → đỏ.
- [ ] R2.4 (FH5): hai tenant chung `thread_id`, B có checkpoint mới hơn → sau `prune` checkpoint mới
      nhất của A còn; bỏ so `tenant_id` ở `newer` → đỏ.
- [ ] R2.5 (FH6): một dòng checkpoint có kiểu ngoài `ALLOWED` → nạp ra dict, không object nào của
      kiểu đó được dựng; đổi allowlist thành `True` → đỏ.
- [ ] R2.6 (FH34): ba module thử dưới `apps`: một có `set_config('app.worker_drain', 'on', true)`,
      một nhập `_SET_WORKER_DRAIN` từ `dw_knowledge.ingest_jobs`, một gọi `set_config(:k, 'on', true)`
      với `k='app.worker_drain'`, một nhập `IngestJobQueue` từ `dw_knowledge.ingest_jobs`, một
      `import dw_knowledge.ingest_jobs` → test kiến trúc đỏ và nêu từng module; các module trong
      `EXEMPT`, `apps/worker`, docstring và thư mục `tests` không làm đỏ; `IngestJobStore` của API không
      làm đỏ; gỡ phép quét, gỡ nhánh lớp hay hàm, hay thêm một tên không lý do → đỏ.
- [ ] R3.1 (FH7): `POST /api/v1/platform/tenants/{tenant_id}/unlock` và `/lock` cho tenant
      `offboarding` → 409 `tenant_offboarding`, `status` giữ nguyên; hoàn tất offboarding vẫn đặt
      `offboarded`; gỡ điều kiện trạng thái → đỏ.
- [ ] R3.2 (FH7): UPDATE thẳng `offboarded → active` và `offboarding → locked` bằng `dw_provisioner`
      → trigger từ chối với `ck_tenants_status_transition`; `offboarding → offboarded` và
      `offboarded → offboarding` vẫn nhận; gỡ trigger → test SQL đỏ; đổi trigger thành danh sách cấm
      `active`, `locked` → ca `offboarding → setup` (CHECK nới trong giao dịch test) đỏ.
- [ ] R3.3 (FH8): với cache giả trung thực (`delete_pattern` xóa thật), thành viên có context trong
      cache, người vận hành khóa tenant → request kế tiếp 403; bỏ lời gọi xóa cache → đỏ.
- [ ] R4.1 (FH9): token `email_verified=false` có email trùng user được mời → 403
      `identity_email_in_use`, không thêm dòng danh tính nào; gỡ kiểm `email_verified` → đỏ.
- [ ] R4.2 (FH9): email đã xác minh của user đã có danh tính đăng nhập → 403; email đã xác minh của
      người vận hành chưa từng đăng nhập → 403; gỡ từng điều kiện → đỏ.
- [ ] R4.3 (FH10): token issuer X có `sub` bằng subject lưu trên user chỉ biết qua issuer Y →
      `find_access` không trả AccessContext, `bootstrap` trả 403 `identity_subject_in_use` và không thêm
      dòng nào; token `dw-dev` theo subject vẫn vào; khôi phục đọc lại user theo `subject` → đỏ.
- [ ] R4.4 (FH11): bằng `dw_app`, và bằng một vai thử không `BYPASSRLS` có INSERT: INSERT danh tính
      đăng nhập cho người vận hành → trigger từ chối; bằng `dw_app`: UPDATE một danh tính →
      `permission denied`; DELETE danh tính đăng nhập → trigger từ chối; DELETE danh tính `zalo` vẫn
      nhận; đổi điều kiện thành `current_user = 'dw_app'` → ca vai thử đỏ.
- [ ] R4.5 (FH9): token `email_verified=false` với email chưa có user → user mới có email rỗng; lời
      mời theo email đó sau đó tạo user khác; ghi email chưa xác minh → đỏ.
- [ ] G1: `test_a_member_deletes_a_document_of_their_own_workspace` xanh trước và sau bản vá.
- [ ] G2: `test_an_invited_person_signs_in_and_finds_their_workspace` xanh với token dev mang
      `email_verified`.
- [ ] G3: `test_email_links_a_keycloak_login_to_the_imported_user` xanh với `email_verified=True`.
- [ ] G4: `test_relinking_a_user_replaces_their_old_chat` xanh dưới quyền mới.
- [ ] G5: `test_pause_restart_resume_approved` xanh với serializer có `ALLOWED`.
- [ ] Xong: `make ci && make test-integration` xanh.

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
