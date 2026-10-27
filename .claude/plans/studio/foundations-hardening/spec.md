# Vá nền móng trước khi Studio xây lên

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio đặt dữ liệu do tenant định nghĩa, agent do tenant dựng và việc gửi ra ngoài lên các dịch vụ nền
đang có lỗi cô lập tenant, cô lập người gọi và test không thể đỏ. Spec này sửa các lỗi đã đo trong code
ngày 23/10/2026, mỗi bản vá kèm một test âm đã thấy đỏ trước bản vá và đỏ lại khi hoàn tác; không thêm
tính năng. Nó phục vụ YC4; phần hiệu ứng, biên mạng, run và outbox (YC41, YC63, phần công cụ của YC5)
tách sang runtime-hardening (Quyết định); ticket của spec khác chạm cùng hàm, bảng hay tệp với một
ticket ở đây chờ ticket đó qua dòng Blocked by của chúng (ADR-0103 (Accepted), ADR-0108 (Accepted)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `soft_delete_document` cập nhật theo `id` dưới RLS tenant, không điều kiện workspace hay `scope`,
  không `RETURNING`, rồi tombstone vector vô điều kiện
  (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py:549-566`). Thiếu: xóa được tài liệu của
  workspace khác cùng tenant và gọi tombstone cả khi không dòng nào khớp.
- Filter Qdrant của một tài liệu chỉ có `source_document_id`
  (`packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:186-194`), dùng cho cả
  xóa cứng (`packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:196-206`) lẫn
  tombstone (`packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:230-241`).
  Thiếu: id tài liệu của tenant khác hay của tài liệu toàn cục bị tombstone với mọi tenant.
- Tài liệu toàn cục đọc được từ mọi tenant (`db/migrations/sql/0001_platform_baseline.sql:767`), id
  của nó không mang tenant (`packages/python/dw_knowledge/src/dw_knowledge/identity.py:45-47`),
  policy của tài liệu chỉ theo tenant (`db/migrations/sql/0001_platform_baseline.sql:773`) còn tìm
  kiếm lọc theo workspace của người gọi
  (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py:156-167`). Ràng buộc: hàng rào
  workspace của việc xóa phải nằm trong câu lệnh, RLS không đặt nó.
- Route xóa trả 204 cho mọi người giữ `knowledge.write` dù có khớp hay không
  (`apps/api/src/dw_api/routes/v1/knowledge.py:176-187`); hành động audit duy nhất của tri thức là
  `knowledge.document.purged` (`packages/python/dw_knowledge/src/dw_knowledge/retention.py:74`).
  Thiếu: xóa mềm không để lại audit.
- `list_items` chỉ lọc workspace (`packages/python/dw_memory/src/dw_memory/service.py:776-786`) còn
  `recall` lọc theo `classifications_for_clearance`
  (`packages/python/dw_memory/src/dw_memory/service.py:850`); `GET /api/v1/memory/items` gọi nó cho
  mọi người giữ `memory.read` (`apps/api/src/dw_api/routes/v1/memory.py:55-75`). Thiếu: mục
  `confidential` và `restricted` lộ qua danh sách.
- Lane `checkpoint_retention` chạy dưới `app.worker_drain`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint_retention.py:107`);
  truy vấn con `newer` và `recent` chỉ so `thread_id`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint_retention.py:92-100`)
  dù `same_thread` so cả tenant
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint_retention.py:78-79`),
  và khóa chính không có tenant (`db/migrations/sql/0001_platform_baseline.sql:588`). Thiếu:
  checkpoint mới hơn của tenant khác trên cùng `thread_id` làm checkpoint mới nhất của tenant này bị
  coi là cũ.
- `thread_id` là `thread_id` của run hoặc chính `run_id`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:183`). Ràng buộc:
  hôm nay lỗi trên chỉ lộ khi một context truyền cùng `thread_id` cho hai tenant.
- Saver dựng cứng `JsonPlusSerializer()`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:59-60`), được dựng
  ở `apps/api/src/dw_api/bootstrap/runtime.py:214`, trên langgraph-checkpoint 4.2.0
  (`uv.lock:2090-2091`). Thiếu: đo ngày 23/10/2026 trên 4.2.0, serializer mặc định dựng lại object
  của một kiểu chưa đăng ký (chỉ cảnh báo), còn `allowed_msgpack_modules` tường minh trả dict.
- `set_tenant_status` chỉ kiểm trạng thái đích
  (`packages/python/dw_platform/src/dw_platform/application/provisioning.py:29`,
  `packages/python/dw_platform/src/dw_platform/application/provisioning.py:295-305`) và repository
  cập nhật không điều kiện trạng thái hiện tại
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:173-181`),
  nên route mở khóa (`apps/api/src/dw_api/routes/v1/platform.py:198-204`) mở lại tenant đang
  offboarding. Thiếu: `ck_tenants_status` chỉ liệt kê bốn giá trị
  (`db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`), không canh bước
  chuyển.
- `offboarding` chỉ được đặt qua luồng offboarding, không bằng tay
  (`packages/python/dw_platform/src/dw_platform/application/provisioning.py:310-314`), và
  `offboarded` chỉ sau khi yêu cầu `completed`
  (`packages/python/dw_platform/src/dw_platform/application/provisioning.py:357-361`). Ràng buộc:
  căn cứ của bước chuyển bị chặn ở R3.
- Route khóa và mở khóa không chạm cache (`apps/api/src/dw_api/routes/v1/platform.py:189-204`);
  AccessContext được cache 30 giây
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`), lookup
  không cache từ chối tenant không `active`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:103-105`),
  và `tenant_cache_pattern` (`packages/python/dw_platform/src/dw_platform/application/cache.py:29-32`)
  chỉ được dùng ở `apps/api/src/dw_api/routes/v1/admin_console.py:303`. Thiếu: tenant bị khóa còn
  chạy tới 30 giây.
- `_resolve_user` nối theo `users.subject` của mọi issuer
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:138-145`),
  rồi theo email của bất kỳ user nào
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:156-166`),
  tin rằng IdP đã xác minh email
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:14-19`).
  Thiếu: không kiểm `email_verified`, issuer hay việc user đã từng đăng nhập.
- `find_access` khớp `users.subject` với mọi issuer
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:200-211`);
  `VerifiedClaims` không có `email_verified`
  (`packages/python/dw_platform/src/dw_platform/application/identity.py:21-31`) và Keycloak không
  ánh xạ nó (`packages/python/dw_platform/src/dw_platform/adapters/identity/keycloak.py:63-70`); grep
  không thấy `email_verified` trong Python, TypeScript, JSON hay YAML của repo. Thiếu: subject của
  issuer này khớp user của issuer khác.
- Issuer dev là `dw-dev`
  (`packages/python/dw_platform/src/dw_platform/adapters/identity/dev_token.py:18`), email user là
  duy nhất (`db/migrations/sql/0001_platform_baseline.sql:616`), không có membership thì API trả 403
  (`packages/python/dw_platform/src/dw_platform/application/identity.py:108-114`). Ràng buộc: email
  chưa xác minh trùng một user có sẵn không nối được và cũng không tạo được user mới.
- Nối theo email đang mở ở `docs/adr/0024-customer-granted-support-access.md:129-131` và ở
  `.claude/plans/platform-runtime/tenant-members-and-invitations/spec.md:70-72`. Ràng buộc: lời mời
  dựa vào đường nối email.
- Baseline cấp `dw_app` SELECT, INSERT, UPDATE, DELETE trên mọi bảng
  (`db/migrations/sql/0001_platform_grants.sql:31-32`) và qua default privileges
  (`db/migrations/sql/0001_platform_grants.sql:45-46`); grep `REVOKE` trong `db/migrations` không
  thấy revision nào thu quyền ghi trên người vận hành, gói dịch vụ, user hay danh tính, khác
  `support_staff` đã thu
  (`db/migrations/versions/af8ee878b4ab_platform_support_staff_and_support_.py:358-370`). Thiếu:
  `dw_app` tự thêm được người vận hành, mà cổng vận hành đọc bảng đó qua `dw_app`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:96-102`,
  `apps/api/src/dw_api/dependencies/auth.py:159-163`).
- Ghi thật của `dw_app` trên các bảng đó: INSERT user
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:168-177`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:161`), INSERT
  danh tính
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:188-198`),
  DELETE rồi INSERT danh tính Zalo
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/zalo_link_repo.py:187-222`);
  người vận hành được ghi qua engine của `dw_provisioner`
  (`apps/api/src/dw_api/bootstrap/wiring.py:264-270`). Ràng buộc: thu quyền không được chặn các
  đường này.
- `test_privileges.py` chỉ khẳng định quyền đọc các bảng này
  (`packages/python/dw_platform/tests/integration/test_privileges.py:45-56`); danh sách quyền
  `dw_provisioner` của baseline (`db/migrations/sql/0001_platform_grants.sql:64-74`) khác của script
  (`scripts/create_provisioner_role.py:107-115`). Thiếu: hai bản của một sự thật.
- 27 policy của baseline đọc setting theo dòng, ví dụ
  `db/migrations/sql/0001_platform_baseline.sql:773`; grep không thấy sub-SELECT nào trong
  `db/migrations`; hàm partition sinh cùng dạng (`db/migrations/sql/0013_partition_maintenance.sql:32`,
  `db/migrations/sql/0013_partition_maintenance.sql:74`). Chưa rõ: lợi ích của dạng sub-SELECT chưa
  đo ở repo này; si-platform đo 451 ms xuống 125 ms trên 200.000 dòng
  (si-platform `db/si/migrations/0057_record_tenant_policies_initplan.sql`).
- `test_rls_coverage.py` nhận setting tin cậy theo chuỗi tên
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:95`) và kiểm hình workspace
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:427-447`). Ràng buộc: dạng
  mới phải để hai kiểm này còn thấy tên setting.
- Danh mục xuất của offboarding lấy mọi bảng có policy `tenant_isolation_%` mà `dw_app` đọc được
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-89`), và hàm tạo
  partition cho mỗi partition một policy cùng tiền tố
  (`db/migrations/sql/0013_partition_maintenance.sql:73-76`). Thiếu: dòng của bảng phân vùng được xuất
  hai lần, một qua bảng cha và một qua partition (đọc mã, chưa chạy).
- `export_rows` đọc mỗi bảng bằng một `SELECT` và giữ mọi dòng trong bộ nhớ
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-181`), rồi lane
  dựng gói zip trong `BytesIO` (`apps/worker/src/dw_worker/consumers/offboarding.py:175-192`). Thiếu: bộ
  nhớ của lane tăng theo số dòng của công ty (D12: 50 triệu bản ghi mỗi công ty).
- Audit `tenant.offboarding.purged` đứng tên người vận hành đã yêu cầu
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:217-247`), như
  ADR-0011 (Accepted) cho phép (`docs/adr/0011-a-background-lane-audits-as-itself.md:44-45`).
  Ràng buộc: actor đó giữ nguyên.
- Lane xóa mỗi bảng xóa được bằng một câu `DELETE` chung, các bảng trong danh sách viết tay `_ORDERED_FIRST` trước,
  phần còn lại theo chữ cái (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:103-114`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:183-194`); lane được dựng ở
  composition root của worker (`apps/worker/src/dw_worker/main.py:403-405`). Thiếu: một khóa ngoại `RESTRICT` mới chỉ
  được thỏa khi ai đó nhớ sửa danh sách đó, và một bước xóa không phải câu `DELETE` chung (hàm SECURITY DEFINER của
  spec khác) không có chỗ nào khai bảng nó xóa.
- Walker `support_routes` chỉ duyệt `APIRoute` cấp đầu
  (`apps/api/tests/unit/test_support_routes.py:44-52`) rồi so với tập rỗng
  (`apps/api/tests/unit/test_support_routes.py:65-67`, `apps/api/src/dw_api/bootstrap/wiring.py:110`).
  Thiếu: đo ngày 23/10/2026 với FastAPI 0.141.1 (`uv.lock:1283-1284`), router được include hiện ra là
  `_IncludedRouter` và walker không thấy route nào, còn `iter_route_contexts` thấy
  (`apps/api/tests/unit/test_platform_endpoint.py:271`).
- Test tiến trình nền chạy `pgrep ... || echo NONE`
  (`apps/docgen/tests/integration/test_sandbox_image.py:182-191`). Thiếu: đo ngày 23/10/2026,
  `dw-docgen:local` không có `pgrep` (procps không có trong `infra/docker/docgen.Dockerfile:70-76`)
  nên test luôn xanh.

## Mục tiêu

### R1 — Test bảo vệ đỏ được [Sửa]

Người review tin được hai test canh truy cập support và tiến trình nền, vì chúng đỏ khi điều chúng
canh bị gỡ.
Trước đây: walker chỉ thấy route gắn thẳng vào app (`apps/api/tests/unit/test_support_routes.py:44-52`).

- R1.1 KHI một route của app, kể cả route trong router được include, nhận ngữ cảnh dựng từ grant
  truy cập mà không có trong `SUPPORT_ALLOWED_ROUTES`, test phủ route của grant PHẢI đỏ.
- R1.2 KHI một lệnh chạy nền trong một phiên docgen còn sống sau khi request khởi chạy nó đã được trả
  lời, test tiến trình nền PHẢI đỏ.

### R2 — Tri thức, bộ nhớ và checkpoint giữ hàng rào tenant và workspace [Sửa]

Thành viên của một tenant không xóa, đọc hay dọn được dữ liệu của tenant hay workspace khác qua ba
đường đã quên hàng rào.
Trước đây: xóa tài liệu theo id rồi tombstone vector theo id (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py:549-566`).

- R2.1 NẾU người gọi `DELETE /api/v1/knowledge/documents/{document_id}` với id của tài liệu thuộc
  tenant khác, workspace khác hoặc tài liệu toàn cục, THÌ API tri thức PHẢI trả 404 và không đổi
  dòng tài liệu, chunk hay vector nào.
- R2.2 KHI API tri thức đánh dấu xóa một tài liệu, API tri thức PHẢI ghi audit
  `knowledge.document.deleted` trong cùng giao dịch với việc đánh dấu.
- R2.3 NẾU clearance của người gọi `GET /api/v1/memory/items` thấp hơn phân loại của một mục bộ nhớ,
  THÌ API bộ nhớ PHẢI bỏ mục đó khỏi trang trả về.
- R2.4 NẾU tenant khác có checkpoint mới hơn trên cùng `thread_id`, THÌ lane `checkpoint_retention`
  PHẢI giữ checkpoint mới nhất của tenant này.
- R2.5 NẾU một dòng checkpoint chứa giá trị có kiểu ngoài allowlist của composition root, THÌ kho
  checkpoint của runner PHẢI trả giá trị đó dạng dữ liệu thô và không dựng object nào của kiểu ấy.

### R3 — Tenant không quay lại sau offboarding và khóa có hiệu lực từ request kế tiếp [Sửa]

Người vận hành không mở lại được tenant đang bị xóa dữ liệu, và thành viên của tenant bị khóa dừng
ở request kế tiếp.
Trước đây: mở khóa đặt `active` cho tenant ở mọi trạng thái (`packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:173-181`).

- R3.1 NẾU người vận hành gọi `POST /api/v1/platform/tenants/{tenant_id}/lock` hoặc
  `POST /api/v1/platform/tenants/{tenant_id}/unlock` cho tenant đang `offboarding` hoặc `offboarded`,
  THÌ API nền tảng PHẢI trả 409 `tenant_offboarding` và không đổi trạng thái tenant.
- R3.2 NẾU một câu lệnh của vai bất kỳ đổi `status` của tenant từ `offboarding` hoặc `offboarded`
  sang `active` hoặc `locked`, THÌ PostgreSQL PHẢI từ chối câu lệnh và không đổi dòng nào.
- R3.3 KHI người vận hành khóa một tenant, API PHẢI trả 403 cho request kế tiếp của mọi thành viên
  tenant đó, kể cả khi AccessContext của người đó còn trong cache.

### R4 — Nối danh tính theo quy tắc tạm [Sửa]

Một token không chiếm được tài khoản có sẵn qua email chưa xác minh hay qua subject của issuer khác;
quy tắc là quyết định 8 của ADR-0103 (Accepted), Đạt cho áp ngay từ P0 (DO-17.1).
Trước đây: nối theo subject của mọi issuer rồi theo email của bất kỳ user nào (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:138-166`).

- R4.1 NẾU email của token trùng email của một user có sẵn mà `email_verified` của token khác
  `true`, THÌ API xác thực PHẢI trả 403 `identity_email_in_use`, không nối danh tính và không tạo
  user.
- R4.2 NẾU email đã xác minh của token thuộc một user đã từng đăng nhập, một người vận hành hay một
  nhân viên `support_staff`, THÌ API xác thực PHẢI trả 403 `identity_email_in_use`, không nối danh
  tính và không tạo user.
- R4.3 NẾU `sub` của token từ issuer khác `dw-dev` chỉ trùng subject lưu trên user mà không có danh
  tính `(iss, sub)` khớp, THÌ API PHẢI trả 403 và không dựng AccessContext nào.
- R4.4 NẾU vai `dw_app` thêm danh tính đăng nhập cho người vận hành hay nhân viên `support_staff`,
  sửa một danh tính, hoặc xóa một danh tính không phải liên kết chat, THÌ PostgreSQL PHẢI từ chối
  câu lệnh và không đổi dòng nào.

### R5 — `dw_app` không ghi bảng quyền lực và RLS đọc setting một lần mỗi câu lệnh [Sửa]

Thông tin đăng nhập của ứng dụng không tạo được người vận hành hay sửa gói dịch vụ, và policy RLS
không tính lại một setting không đổi cho từng dòng.
Trước đây: `dw_app` giữ INSERT, UPDATE, DELETE trên mọi bảng (`db/migrations/sql/0001_platform_grants.sql:31-32`).

- R5.1 NẾU vai `dw_app` INSERT, UPDATE, DELETE hay TRUNCATE trên `platform.platform_operators` hoặc
  `platform.plans`, hay UPDATE, DELETE, TRUNCATE trên `platform.users`, THÌ PostgreSQL PHẢI từ chối
  với `permission denied` và không đổi dòng nào.
- R5.2 Script dựng vai `dw_provisioner` PHẢI cấp cho vai đó đúng tập quyền mà migration cấp trên
  từng bảng, không thêm và không bớt.
- R5.3 Mọi policy RLS trong catalog, kể cả policy của partition tạo sau, PHẢI đọc mỗi setting phiên
  trong một sub-SELECT theo dạng của ADR-0105 (Accepted) quyết định 1.

R6-R10 chuyển nguyên số sang runtime-hardening (Quyết định 24/10/2026); spec này không dùng lại các số đó.

### R11 — Offboarding xuất mỗi dòng đúng một lần, theo lô, xóa theo thứ tự suy từ catalog, và audit nêu tên lane [Sửa]

Người vận hành nhận gói xuất của một công ty có mỗi dòng đúng một lần, lane xuất không giữ cả bảng
trong bộ nhớ (YC6, D12), lần xóa không hỏng ở một khóa ngoại mà không ai nhớ ghi vào danh sách, và audit của lần
xóa đứng tên người vận hành đã yêu cầu kèm tên lane đã thi hành quyết định đó (`CLAUDE.md`, "Agent and tool rules";
ADR-0011 (Accepted); ADR-0109 (Accepted) Consequences).
Trước đây: danh mục xuất gồm cả partition, và mỗi bảng được đọc bằng một câu lệnh giữ mọi dòng (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-181`); audit `tenant.offboarding.purged` ghi `details` rỗng (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:236`); thứ tự xóa là danh sách tay `_ORDERED_FIRST` rồi chữ cái (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:103-114`).

- R11.1 KHI lane `offboarding` xuất dữ liệu của một tenant, lane `offboarding` PHẢI đưa mỗi dòng của
  mỗi bảng tenant, kể cả bảng phân vùng, vào gói xuất đúng một lần.
- R11.2 KHI lane `offboarding` đọc một bảng để xuất, mỗi câu lệnh đọc của lane `offboarding` PHẢI trả
  không quá 1.000 dòng, theo thứ tự khóa chính.
- R11.3 KHI lane `offboarding` ghi audit `tenant.offboarding.purged`, lane `offboarding` PHẢI đặt
  `details.lane` của audit đó bằng `offboarding`.
- R11.4 KHI lane `offboarding` xóa dữ liệu của một tenant, lane `offboarding` PHẢI chạy các bước xóa của sổ bước xóa ở
  composition root, mỗi bước khai các bảng nó xóa, theo thứ tự suy từ các khóa ngoại `ON DELETE RESTRICT` và
  `NO ACTION` mà `pg_constraint` của cơ sở dữ liệu đang chạy khai: bước xóa bảng tham chiếu chạy trước bước xóa bảng
  được tham chiếu, kể cả khi bảng tham chiếu chỉ mất dòng qua `CASCADE` từ bảng của một bước khác, không theo danh sách
  viết tay nào (H-2).
- R11.5 NẾU hai bước của sổ khai cùng một bảng, hay các cạnh suy từ `pg_constraint` tạo một vòng giữa các bước, THÌ
  lane `offboarding` PHẢI từ chối lượt xóa trước câu xóa đầu tiên, giữ tenant ở `offboarding` và ghi lỗi nêu tên các
  bảng hay các khóa ngoại của vòng.

## Hành vi giữ nguyên

- G1 KHI người giữ `knowledge.write` xóa một tài liệu của workspace đang làm việc, API tri thức PHẢI
  TIẾP TỤC trả 204 và tìm kiếm của workspace đó không còn trả tài liệu ấy (test:
  `test_a_member_deletes_a_document_of_their_own_workspace`).
- G2 KHI người được mời đăng nhập lần đầu bằng token có email đã xác minh trùng lời mời, API xác thực
  PHẢI TIẾP TỤC nối danh tính vào user được mời (test:
  `test_an_invited_person_signs_in_and_finds_their_workspace`).
- G3 KHI người do importer tạo đăng nhập lần đầu qua Keycloak với email đã xác minh, API xác thực
  PHẢI TIẾP TỤC nối danh tính vào user đó (test:
  `test_email_links_a_keycloak_login_to_the_imported_user`).
- G4 KHI một người nối lại Zalo, kho liên kết PHẢI TIẾP TỤC thay danh tính chat cũ bằng danh tính
  mới (test: `test_relinking_a_user_replaces_their_old_chat`).
- G5 KHI một run được duyệt rồi tiến trình khởi động lại, runner PHẢI TIẾP TỤC chạy tiếp run từ
  checkpoint (test: `test_pause_restart_resume_approved`).
- G6 KHI một kết nối chưa đặt setting tenant nào, PostgreSQL PHẢI TIẾP TỤC không trả dòng nào của
  bảng tenant (test: `test_a_connection_that_never_scopes_itself_reads_nothing`).
- G8 KHI lane `offboarding` xóa dữ liệu của một tenant, lane `offboarding` PHẢI TIẾP TỤC ghi audit
  `tenant.offboarding.purged` đứng tên người vận hành đã yêu cầu (test:
  `test_purge_records_an_audit_event_before_deleting_anything`).

G7 chuyển sang runtime-hardening; G5 ở cả hai spec (Quyết định 25/10/2026).

## Trong phạm vi

- Hàng rào tenant và workspace của `DELETE /api/v1/knowledge/documents/{document_id}`,
  `GET /api/v1/memory/items` và lane `checkpoint_retention`; audit `knowledge.document.deleted`;
  allowlist của serializer checkpoint ở composition root.
- Trigger trạng thái tenant; xóa cache khi khóa, mở khóa và offboard, là cách tạm tới tenant-rbac/02,
  nơi phiên bản quyền vào khóa cache và ba lời gọi xóa cache được gỡ; quy tắc nối danh tính tạm,
  trigger và quyền của `dw_app` trên `platform.external_identities`.
- Thu quyền ghi của `dw_app` trên `platform.users`, `platform.platform_operators`, `platform.plans`;
  một nguồn cho quyền của `dw_provisioner`; dạng sub-SELECT cho mọi policy RLS.
- Hai test không thể đỏ và việc rà các mẫu cùng họ.
- Danh mục xuất của offboarding chỉ gồm bảng cha, đọc theo lô keyset trên khóa chính; `details.lane`
  của audit `tenant.offboarding.purged`.
- Sổ bước xóa của lane `offboarding` ở composition root của worker, mỗi bước khai bảng nó xóa, thứ tự suy từ khóa ngoại
  `RESTRICT` và `NO ACTION` trong `pg_constraint` thay cho `_ORDERED_FIRST`; bước mặc định cho mỗi bảng xóa được mà
  không bước nào khai; test phủ của studio-skeleton:R4.2 đọc sổ đó.

## Ngoài phạm vi

| Việc                                                                                                    | Vì sao                                                                                                                               | Chủ                                            |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| Quyền trả về ở `GET /api/v1/auth/bootstrap` gồm permission set                                          | Thuộc vai và quyền của tenant                                                                                                        | `tenant-rbac` ticket 01                        |
| IdP theo tenant, mã nhận lời mời thay bước email                                                        | Ticket 02 là quy tắc tạm; câu trả lời của dw-proterial có thể đẩy mã nhận lời mời sớm hơn W2 (DO-17.1)                               | `org-and-principals`, W2 (ADR-0103 (Accepted)) |
| Mã hóa checkpoint bằng khóa theo tenant                                                                 | Cần KMS và saver mới (ADR-0112 (Accepted) quyết định 10)                                                                             | `connections-and-vault`, `workflow-engine`     |
| Hai chủ của quyền đăng tri thức toàn cục                                                                | Hôm nay từ chối an toàn; R2.1 không mở thêm đường xóa tài liệu toàn cục                                                              | đợt sau                                        |
| Gói xuất offboarding ghi ra đĩa và tải lên theo phần, để bộ nhớ của lane không tăng theo kích thước gói | Ticket 07 chỉ đọc theo lô keyset như quyết định offboarding chọn; gói zip còn dựng trong bộ nhớ, và W1 chỉ có dữ liệu giả lập (YC89) | `foundations-hardening`, đợt sau               |

## Kiểm soát

| #    | Kiểm soát                                                         | Yêu cầu      | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---- | ----------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FH1  | Test phủ route của grant và test tiến trình nền đỏ được           | R1.1, R1.2   | Thêm phụ thuộc ngữ cảnh grant vào `GET /api/v1/runs/{run_id}` → test phủ route đỏ; khẳng định "không còn tiến trình" trên lần quét cùng request với `sleep 300 &` → đỏ                                                                                                                                                                                                                                                                                                                                                                  |
| FH2  | Xóa tài liệu chỉ trong workspace của người gọi, vector của mình   | R2.1         | Qdrant thật: tenant B xóa id của A, workspace 2 xóa tài liệu workspace 1, mọi tenant xóa tài liệu toàn cục → 404, tài liệu vẫn tìm được; gỡ `tenant_id` khỏi filter tombstone → đỏ                                                                                                                                                                                                                                                                                                                                                      |
| FH3  | Xóa mềm có audit cùng giao dịch                                   | R2.2         | Audit ném lỗi → tài liệu không mang `status='deleted'`; ghi audit sau commit → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| FH4  | Danh sách bộ nhớ theo clearance                                   | R2.3         | Clearance `internal` gọi `GET /api/v1/memory/items` → không có mục `confidential`; bỏ lọc → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| FH5  | Dọn checkpoint không chạm tenant khác                             | R2.4         | Hai tenant chung `thread_id`, B có checkpoint mới hơn → checkpoint mới nhất của A còn; bỏ so `tenant_id` ở `newer` → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                 |
| FH6  | Checkpoint không dựng kiểu ngoài allowlist                        | R2.5         | Dòng có kiểu ngoài allowlist → nạp ra dict, không object nào được dựng; allowlist `True` → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| FH7  | Tenant offboarding không quay lại `active`, `locked`              | R3.1, R3.2   | `unlock` tenant `offboarding` → 409, trạng thái giữ; UPDATE `offboarded → active` bằng `dw_provisioner` → trigger từ chối; gỡ trigger → đỏ                                                                                                                                                                                                                                                                                                                                                                                              |
| FH8  | Khóa tenant có hiệu lực từ request kế tiếp                        | R3.3         | Cache giả trung thực, thành viên có context trong cache, khóa tenant → request kế tiếp 403; tới khi tenant-rbac/02 merge: bỏ xóa cache → đỏ; từ tenant-rbac/02: gỡ trigger `bump_access_version` trên `platform.tenants` → đỏ                                                                                                                                                                                                                                                                                                           |
| FH9  | Chỉ nối qua email đã xác minh tới user chưa từng đăng nhập        | R4.1, R4.2   | Token `email_verified=false` trùng email lời mời → 403, không thêm danh tính; email đã xác minh của user đã đăng nhập → 403; gỡ kiểm → đỏ                                                                                                                                                                                                                                                                                                                                                                                               |
| FH10 | Subject không khớp chéo issuer                                    | R4.3         | Issuer X, `sub` bằng subject của user chỉ biết qua issuer Y → 403, không AccessContext                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| FH11 | Danh tính đăng nhập của người vận hành chỉ qua `dw_provisioner`   | R4.4         | Bằng `dw_app`: INSERT danh tính đăng nhập cho người vận hành → từ chối; UPDATE danh tính → `permission denied`; DELETE danh tính đăng nhập → từ chối                                                                                                                                                                                                                                                                                                                                                                                    |
| FH12 | `dw_app` không ghi bảng quyền lực                                 | R5.1         | Bằng `dw_app`: INSERT `platform.platform_operators`, UPDATE `platform.plans`, UPDATE `platform.users` → `permission denied`; khôi phục một GRANT → đỏ                                                                                                                                                                                                                                                                                                                                                                                   |
| FH13 | Quyền của `dw_provisioner` có một nguồn                           | R5.2         | Thêm một bảng vào danh sách của script mà migration không cấp → test so quyền đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| FH14 | Policy đọc setting một lần mỗi câu lệnh                           | R5.3         | ALTER một policy về dạng theo dòng → test catalog đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| FH30 | Gói xuất không lặp dòng của bảng phân vùng                        | R11.1        | Bảng phân vùng thử có partition tháng và DEFAULT mà `dw_app` đọc được theo tên, mỗi nơi một dòng của tenant → mỗi dòng có đúng một lần trong kết quả xuất; test viết trước, đỏ trên mã hiện có; bỏ lọc partition khỏi danh mục xuất → đỏ                                                                                                                                                                                                                                                                                                |
| FH31 | Audit của lần xóa đứng tên người yêu cầu và nêu lane đã thi hành  | G8, R11.3    | Purge một tenant có yêu cầu offboarding → audit `tenant.offboarding.purged` có actor là người yêu cầu và `details.lane` bằng `offboarding`; đổi actor sang `system_actor('offboarding')` → test G8 đỏ; ghi lại `details` rỗng → test R11.3 đỏ                                                                                                                                                                                                                                                                                           |
| FH33 | Thứ tự xóa của offboarding suy từ catalog, không từ danh sách tay | R11.4, R11.5 | Hai bảng thử tạo trong giao dịch test, tên xếp theo chữ cái ngược chiều cạnh, nối bằng khóa ngoại `RESTRICT` (và một cặp `NO ACTION`) → purge xóa được cả hai; bảng con chỉ mất dòng qua `CASCADE` từ bảng của một bước khác → bước đó chạy trước bước xóa bảng cha; thay phép suy bằng thứ tự chữ cái hay một danh sách cạnh chép tay → lỗi khóa ngoại, test đỏ; hai bước khai cùng một bảng, hay vòng hai bảng `RESTRICT` → từ chối trước câu xóa đầu, 0 dòng bị xóa, tenant giữ `offboarding`; gỡ kiểm trùng hay kiểm vòng → test đỏ |

FH15-FH29 và FH32 chuyển sang runtime-hardening thành RH15-RH29 và RH32 (Quyết định 24/10/2026); spec này
không dùng lại các số đó, nên kiểm soát mới lấy từ FH33.

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi trong
  Comments của ticket.
- `make ci && make test-integration` xanh, gồm integration của `dw_platform`, `dw_knowledge`,
  `dw_agent_runtime`, `apps/api`, `apps/worker` và `apps/docgen`.
- `reviewing-feature-security` và `reviewing-deployment-security` chạy cho từng ticket.
- Phép đo InitPlan và kết luận ghi trong Comments của ticket 03.

## Phụ thuộc

- studio-skeleton: bản ba tham số của `platform._ensure_one_partition` và việc thu mọi quyền của `dw_app`
  trên partition (studio-skeleton:R3.1, studio-skeleton:R3.3); ticket 03 chờ studio-skeleton/01. Test phủ
  offboarding và `STUDIO_EXCLUSIONS` (studio-skeleton:R4.1, studio-skeleton:R4.3) dùng chính hai truy vấn
  catalog của `SqlTenantOffboarding`, nên ticket 07 chờ studio-skeleton/01 vì cùng sửa `offboarding.py`; ticket 07
  thay thứ tự các bước xóa mà studio-skeleton/01 khai ở một chỗ trong `offboarding.py` bằng sổ bước xóa của R11.4, và
  test phủ của studio-skeleton:R4.2 đọc sổ đó, đỏ khi một bước đăng ký đi trái một cạnh `RESTRICT` hay `NO ACTION`.
- Bên đăng ký bước vào sổ của R11.4, mỗi bên trong ticket của mình, không chờ nhau (H-2): usage-and-limits/02
  (`platform.purge_tenant_append_only`, khai các bảng `append_only` của sổ phân vùng; usage-and-limits:R3.10) và
  org-and-principals/03 (`platform.purge_tenant_service_users`, khai `platform.users`; org-and-principals:R6.8). Một bảng
  mới chỉ cần câu `DELETE` chung thì không đăng ký gì: bước mặc định nhận nó từ danh mục xóa, và cạnh `RESTRICT` của nó
  vào thứ tự từ `pg_constraint`, như `platform.run_steps.child_run_id` → `platform.worker_runs` của
  telemetry-and-audit:R3.10 hay `platform.run_manifest_keys` → `studio.artifact_versions` của tenant-config:R6.5.
- Ticket của spec khác chờ ticket ở đây theo dòng Blocked by của chính chúng (OPS-b);
  `scripts/check_plans.py --table` in bảng sống, spec này không chép lại.
- Seam: `CachePort.delete_pattern` với `tenant_cache_pattern`; `classifications_for_clearance` là chủ duy nhất
  của clearance; lane `checkpoint_retention` và lane `offboarding` hiện có.
- Hợp đồng: ADR-0011 (Accepted); ADR-0103 (Accepted) quyết định 8; ADR-0105 (Accepted) quyết định 1;
  ADR-0112 (Accepted) quyết định 10.
- Kiểm lại khi: ADR-0103 (Accepted) đổi quyết định 8 → R4, ticket 02; FOG-37 chốt allowlist → R2.5, ticket 02;
  phép đo của ticket 03 dưới ngưỡng → R5.3 rút, custom-objects và record-access kiểm lại dạng policy mà chúng
  bắt buộc cho bảng Studio; tenant-rbac/02 merge → R3.3, FH8, ticket 02 (ba lời gọi xóa cache được gỡ);
  studio-skeleton/01 đổi chữ ký hàm partition → ticket 03; studio-skeleton/01 đổi test phủ offboarding hay
  `STUDIO_EXCLUSIONS` → ticket 07; một spec thêm khóa ngoại `RESTRICT` hay `NO ACTION` tạo vòng giữa hai bước xóa →
  R11.5, ticket 07; một bước đăng ký xóa một bảng nó không khai → R11.4, FH33.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D5: si-platform là tham chiếu và port có chọn lọc; spec này port thiết
  kế claim trước (si-platform `db/si/migrations/0040_tool_call_claims.sql`), ngữ nghĩa
  `email_verified`, xô địa chỉ `10 × L` và dạng InitPlan, viết lại thành revision Alembic trên
  `platform.*` với `dw_app`. Sửa: R4, R5.3 (R6 và R7.1 nay ở runtime-hardening).
- 23/10/2026 (người yêu cầu): D12: mọi phép đo của kế hoạch theo quy mô 10 triệu bản ghi mỗi object.
  Sửa: R5.3.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: D12 nói đo theo quy mô 10 triệu bản ghi, brief B11 nói đo
  InitPlan trên 200.000 dòng; theo brief, vì phép đo so hai dạng policy trên cùng một bảng chứ không
  đo sức chứa. Nếu sai thì: ticket 03 đo thêm ở 10 triệu dòng trước khi chuyển.
- 23/10/2026 (agent, tạm): lợi ích InitPlan "lặp lại được" khi trung vị của dạng sub-SELECT thấp hơn
  dạng theo dòng ít nhất 20%; dưới ngưỡng thì R5.3 rút bằng `[Bỏ]` và ticket 03 ghi "không áp dụng".
  Nếu sai thì: đổi ngưỡng, R5.3 giữ hay rút theo ngưỡng mới.
- 23/10/2026 (agent, tạm): trigger trạng thái tenant chỉ chặn bước có căn cứ (`offboarding`,
  `offboarded` về `active`, `locked`); `offboarded` có phải trạng thái cuối hay không chưa ai quyết
  nên không đoán. Nếu sai thì: trigger chặn thêm bước rời `offboarded`.
- 23/10/2026 (agent, tạm): 403 `identity_email_in_use` dùng chung cho email chưa xác minh, người vận
  hành và nhân viên `support_staff`; ADR-0103 (Accepted) quyết định 8 chỉ đặt mã cho user đã đăng
  nhập. Nếu sai thì: tách mã riêng cho email chưa xác minh.
- 23/10/2026 (Đạt): DO-17.1 theo (a): quy tắc nối danh tính tạm của ADR-0103 (Accepted) quyết định 8
  áp ngay từ P0; hỏi dw-proterial song song, trước khi ticket 02 merge, xem importer có dựa vào nối
  email chưa xác minh không và IdP của họ có gửi `email_verified` không; câu trả lời chỉ quyết việc
  đẩy mã nhận lời mời sớm hơn W2, không chặn ticket 02. Hỏi: Q1. Sửa: R4, ticket 02.
- 23/10/2026 (Đạt): Khóa tenant có hiệu lực ngay theo (a): xóa cache ở route khóa, mở khóa và
  offboard là cách tạm tới tenant-rbac/02; ticket đó gỡ ba lời gọi, đổi phép đột biến của FH8 sang gỡ
  trigger `bump_access_version` trên `platform.tenants` và chờ ticket 02 này; FH8 giữ hành vi. Sửa:
  Trong phạm vi, FH8, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): H:studio-skeleton:offboarding theo (a): offboarding xuất qua bảng cha, bỏ
  partition con và đọc theo lô keyset ở ticket mới 07; actor của audit `tenant.offboarding.purged` giữ
  là người vận hành đã yêu cầu (ADR-0011 (Accepted)). Sửa: Hiện trạng, thêm R11, G8, FH30, ticket 07.
- 23/10/2026 (Đạt): OPS-b: org-and-principals/02 chờ ticket 02; hai cạnh khác của cùng quyết định (ticket 06 cũ
  chờ tenant-config/03, studio-skeleton/04 chờ ticket 05 cũ) nay ở runtime-hardening. Sửa: Phụ thuộc.
- 23/10/2026 (Đạt): OPS-j: phép đo trùng ticket khám phá chạy một lần: discovery/23 (FOG-78) chạy
  trước ticket 02 nếu kịp, ticket 02 không chờ nó; discovery/05 chạy trước ticket 03 trên thân đường
  găng; có `## Answer` thì ticket trỏ về đó, chưa có thì phép đo ở ticket là phép đo của ticket khám
  phá. Sửa: ticket 02, ticket 03.
- 23/10/2026 (agent, tạm): ticket 03 chờ studio-skeleton/01 và viết lại bản ba tham số của
  `platform._ensure_one_partition`, giữ việc thu quyền `dw_app` trên partition, theo cách sửa thứ nhất
  của phát hiện C:foundations-hardening/03~studio-skeleton/01; OPS-b không xét cặp này. Nếu sai thì:
  đảo chiều, studio-skeleton/01 chờ ticket 03 và giữ dạng policy của nó.
- 23/10/2026 (Đạt): DO-03.2 theo (a): port mã thuần của si-platform cần thỏa thuận viết, ghim commit và
  dòng đầu `Ported from si-platform`; spec này dựng lại thiết kế của si-platform (`email_verified`, dạng
  InitPlan; claim trước và xô địa chỉ `10 × L` nay ở runtime-hardening) chứ không chép mã, nên không chờ
  thỏa thuận.
- 23/10/2026 (agent, tạm): lô đọc của offboarding là 1.000 dòng theo khóa chính, và danh mục xuất bỏ
  partition bằng điều kiện `relispartition`, độc lập với việc thu quyền partition của studio-skeleton/01.
  Nếu sai thì: đổi hằng ở R11.2 và test của nó.
- 24/10/2026 (Đạt): lane `offboarding` thi hành quyết định đã ghi của người vận hành, nên audit
  `tenant.offboarding.purged` đứng tên người đó và ghi `details.lane` bằng `offboarding` (`CLAUDE.md`,
  "Agent and tool rules"; ADR-0011 (Accepted); E:CLAUDE.md#agent-and-tool-rules~record-access:DO-13); G8
  giữ actor như mã hôm nay, còn `details.lane` là hành vi mới nên vào R11.3. Sửa: R11, thêm R11.3, FH31,
  Trong phạm vi, Phụ thuộc, ticket 07.
- 24/10/2026 (Đạt): ticket 07 chờ studio-skeleton/01, còn record-access/03 và custom-objects/02 chờ ticket
  07, để `offboarding.py` có một thứ tự sửa (C:foundations-hardening/07~record-access/03, cách thứ nhất).
  Sửa: Phụ thuộc, ticket 07.
- 24/10/2026 (Đạt): usage-and-limits/01 chờ ticket 03, để quyền ghi và cột của `platform.plans` đổi theo một
  thứ tự (C:foundations-hardening/03~usage-and-limits/01). Sửa: ticket 03.
- 24/10/2026 (Đạt): một spec quá cỡ của `writing-plan-specs` được tách khi tới `checking-plan-readiness`,
  foundations-hardening trước (vòng 3 của kiểm nhất quán, nhận theo khuyến nghị): phần hiệu ứng, biên mạng,
  run và outbox (R6-R10, G7, ticket 04, 05, 06, kiểm soát FH15-FH29 và FH32) thành spec mới
  runtime-hardening, giữ nguyên số R và số G, kiểm soát giữ số với tiền tố RH; spec này giữ R1-R5, R11,
  G1-G6, G8, FH1-FH14, FH30, FH31 và ticket 01, 02, 03, 07, và không dùng lại các số đã chuyển. Sửa: mọi mục.
- 25/10/2026 (agent, tạm): ba ticket chuyển sang mang số 01, 02, 03 ở runtime-hardening (từ 04, 05, 06), vì
  `scripts/check_plans.py` đòi mỗi thư mục ticket đếm từ 01 (kiểm `numbering`); số R, G và kiểm soát, những mã
  mà spec và ticket khác dẫn, giữ nguyên, và mọi chỗ dẫn ở area đổi theo. G5 ở cả hai spec, cùng câu và cùng
  test, vì ticket 02 ở đây (allowlist serializer của checkpoint) và runtime-hardening/03 (compare-and-set khi
  resume) cùng có thể làm vỡ việc chạy tiếp một run đã duyệt. Sửa: Danh sách ticket, Hành vi giữ nguyên. Nếu
  sai thì: ba ticket giữ số 04-06 ở runtime-hardening và kiểm `numbering` nhận một thư mục tách bắt đầu từ số
  khác 01.
- 25/10/2026 (agent, tạm): H-2: các bước xóa của lane `offboarding` là một sổ ở composition root của worker
  (`apps/worker/src/dw_worker/main.py`), mỗi bước khai các bảng nó xóa; thứ tự chạy suy từ các khóa ngoại `RESTRICT` và
  `NO ACTION` trong `pg_constraint` của cơ sở dữ liệu đang chạy, không danh sách viết tay, và thay `_ORDERED_FIRST` cùng
  thứ tự khai của studio-skeleton/01 ở ticket 07; bảng xóa được mà không bước nào khai nhận bước mặc định (câu `DELETE`
  chung của hôm nay); một bảng chỉ mất dòng qua `CASCADE` mang cạnh của nó sang bước của bảng cha `CASCADE`; trùng bảng
  hay vòng thì từ chối trước câu xóa đầu (R11.5), vì một thứ tự đoán là mặc định mở (failure-modes #7);
  org-and-principals/03 và usage-and-limits/02 mỗi bên đăng ký bước của mình, không chờ nhau; cạnh `RESTRICT`
  `platform.run_steps.child_run_id` → `platform.worker_runs` (telemetry-and-audit:R3.10) là một cạnh của thứ tự đó; test
  phủ của studio-skeleton:R4.2 đỏ khi một bước đăng ký đi trái cạnh `RESTRICT`. Sửa: Hiện trạng, thêm R11.4, R11.5,
  FH33, Trong phạm vi, Phụ thuộc, ticket 07. Nếu sai thì: thứ tự viết tay trong `offboarding.py` và cạnh
  org-and-principals/03 <- usage-and-limits/02.
- 27/10/2026 (Đạt): Nhận từ app-standards (hàng Ngoài phạm vi của spec đó) phép quét nguồn giới hạn nơi đặt `app.worker_drain`: một kết nối `dw_app` của API đặt được setting đó, và policy drain của checkpoint mở cả đọc (`db/migrations/versions/7bbd071748ca_run_checkpoints_worker_drain_and_sweep_.py:46-58`); lượt sửa kế của spec này viết nó thành yêu cầu, hàng Kiểm soát và ticket.

## Danh sách ticket

| #   | Ticket                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Test không thể đỏ: walker route và tiến trình nền sandbox](issues/01-test-khong-the-do.md)                                  |
| 02  | [Hàng rào dữ liệu bị quên, vòng đời tenant, nối danh tính và checkpoint an toàn](issues/02-hang-rao-du-lieu-va-danh-tinh.md) |
| 03  | [Thu quyền ghi thừa của dw_app và RLS đọc setting một lần mỗi câu lệnh](issues/03-quyen-dw-app-va-rls-initplan.md)           |
| 07  | [Offboarding xuất mỗi dòng một lần, đọc theo lô keyset, xóa theo sổ bước](issues/07-offboarding-xuat-mot-lan-theo-lo.md)     |

Ticket 04, 05, 06 chuyển sang runtime-hardening thành ticket 01, 02, 03 (Quyết định 25/10/2026); số 04-06
không dùng lại ở đây.
