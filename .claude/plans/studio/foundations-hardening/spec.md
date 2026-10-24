# Vá nền móng trước khi Studio xây lên

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio đặt dữ liệu do tenant định nghĩa, agent do tenant dựng và việc gửi ra ngoài lên các dịch vụ
nền đang có lỗi cô lập tenant, cô lập người gọi, hiệu ứng chạy hai lần và test không thể đỏ. Spec
này sửa các lỗi đã đo trong code ngày 23/10/2026, mỗi bản vá kèm một test âm đã thấy đỏ trước bản vá
và đỏ lại khi hoàn tác; không thêm tính năng. Nó phục vụ YC4, YC41 (phần mỗi tác động được nhận đúng
một lần), YC63 và phần công cụ của YC5; ticket của spec khác chạm cùng hàm, bảng hay tệp với một ticket
ở đây chờ ticket đó qua dòng Blocked by của chúng (ADR-0103 (Accepted), ADR-0108 (Accepted)).

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
- Executor tìm lần thành công (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-220`),
  chạy handler (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:222-274`) rồi
  mới ghi (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:280`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:322`); index duy nhất một phần
  chỉ từ chối bản ghi thứ hai (`db/migrations/sql/0001_platform_baseline.sql:698`) và store không bắt
  `IntegrityError`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/tool_execution_store.py:81-118`);
  khóa là run cộng đối số
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:587`). Thiếu:
  hai lời gọi cùng khóa chạy đồng thời đều qua bước tìm rồi cùng chạy handler; việc `create_agent`
  chạy các lời gọi của một bước song song chưa đo ở repo này.
- Store tự nhận chỉ thêm
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/tool_execution_store.py:1`) nhưng
  default privileges cấp UPDATE, DELETE (`db/migrations/sql/0001_platform_grants.sql:45-46`);
  `status` không có CHECK (`db/migrations/sql/0001_platform_baseline.sql:423`) và executor chỉ ghi
  `failed`, `succeeded` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:285`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:327`). Thiếu: bản ghi sửa được
  và trạng thái không có ràng buộc.
- `ScopedToolsMiddleware` và `OfferedToolsOnlyMiddleware` cho qua mọi mục không phải `BaseTool`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:301-306`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:453-457`).
  Thiếu: một công cụ phía nhà cung cấp đi vòng qua ToolExecutor; hôm nay chưa đường nào thêm nó.
- `redact_mapping` không đi vào list
  (`packages/python/dw_observability/src/dw_observability/redaction.py:28-40`) mà nuôi input của
  audit `tool.failed` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:200`) và
  thuộc tính span (`packages/python/dw_observability/src/dw_observability/telemetry.py:22`). Thiếu:
  `{"items": [{"api_key": "sk-123"}]}` ra nguyên văn.
- `deepagents` khai khoảng `>=0.7,<1` (`packages/python/dw_agent_runtime/pyproject.toml:18`), lock
  0.7.15 (`uv.lock:679-680`); hai comment kể bộ công cụ dựng sẵn khác nhau
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:28-34` có
  `delete`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:414-418`
  có `execute`); README nói `autonomy_level` không ai đọc (`configs/workers/README.md:14-17`) trong
  khi runner đọc nó
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:239-240`).
  Thiếu: không test nào khóa danh sách công cụ đưa cho model.
- `_key` băm nguyên header `Authorization` khi có
  (`apps/api/src/dw_api/middleware/rate_limit.py:36-41`), bộ đếm theo tiến trình
  (`apps/api/src/dw_api/middleware/rate_limit.py:34`), và uvicorn chỉ tin `X-Forwarded-For` từ Caddy
  (`infra/compose/docker-compose.host.yml:94-97`). Thiếu: mỗi bearer ngẫu nhiên là một xô mới.
- Vị từ của `net_guard` là private, loopback, link-local, reserved, unspecified
  (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:36-45`), phân giải một lần rồi trả URL
  (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`); người gọi là URL gốc do người vận
  hành cấu hình (`apps/api/src/dw_api/bootstrap/models.py:28`,
  `apps/api/src/dw_api/bootstrap/knowledge.py:53`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/model_stack.py:94`). Thiếu: đo
  ngày 23/10/2026 trên Python 3.12.15 và 3.13.15, `100.64.0.1`, `100.100.100.200`, `224.0.0.1` và
  `ff02::1` lọt qua, còn `64:ff9b::a9fe:a9fe` có `is_global` đúng nên vị từ chỉ dựa `is_global` cũng
  để lọt.
- API và worker đọc `DW_API_OUTBOUND_ALLOWED_HOSTS`, `DW_WORKER_OUTBOUND_ALLOWED_HOSTS`
  (`apps/api/src/dw_api/settings.py:208`, `apps/worker/src/dw_worker/settings.py:182`), compose không
  truyền hai biến này và `.env.example` còn tên cũ (`.env.example:254`). Thiếu: danh sách máy chủ
  được phép không tới được tiến trình.
- Compose cơ sở ghi Qdrant và Valkey chạy không xác thực (`infra/compose/docker-compose.yml:19-25`),
  chỉ overlay dev đặt khóa (`infra/compose/docker-compose.dev.yml:33`) và mật khẩu
  (`infra/compose/docker-compose.dev.yml:49`), overlay uat chỉ giới hạn bộ nhớ
  (`infra/compose/docker-compose.uat.yml:48-62`); client dùng `redis://valkey:6379/0`
  (`infra/compose/docker-compose.yml:281`), kiểm cấu hình chỉ đòi URL Qdrant
  (`apps/api/src/dw_api/settings.py:362-366`, `apps/worker/src/dw_worker/settings.py:330`), và
  `postgres-exporter` nối bằng `dw_app` (`infra/compose/docker-compose.yml:599`). Thiếu: mọi socket
  trên `dw-internal` đọc được text chunk của mọi tenant mà không qua RLS.
- Tag trôi ở `infra/compose/docker-compose.yml:45`, `infra/compose/docker-compose.yml:94`,
  `infra/compose/docker-compose.yml:510`, `infra/compose/docker-compose.yml:532`,
  `infra/compose/docker-compose.yml:563`, `infra/compose/docker-compose.yml:611`; các ảnh bên thứ ba
  khác có tag phiên bản nhưng không digest; chỉ Caddy có digest
  (`infra/compose/docker-compose.host.yml:48`). Ràng buộc: `CLAUDE.md:128-129` đòi ghim phiên bản.
- `resume` kiểm `waiting_approval` rồi chạy graph mà không đổi trạng thái
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:508-513`) và
  chỉ bắt `Exception`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:536-547`);
  reaper chỉ dọn `running` quá ngưỡng
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:232-254`), ngưỡng là
  3600 giây (`configs/policies/worker_runs@1.0.0.yaml:28`); lượt mới của thread được báo chờ duyệt
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:188-196`) theo một
  truy vấn không xem yêu cầu phê duyệt đã được quyết chưa
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:267-275`). Thiếu:
  resume chết giữa chừng làm thread kẹt mãi.
- `status` của run, `status` của yêu cầu phê duyệt và `outcome` của quyết định không có CHECK
  (`db/migrations/sql/0001_platform_baseline.sql:454`,
  `db/migrations/sql/0001_platform_baseline.sql:179`,
  `db/migrations/sql/0001_platform_baseline.sql:161`); giá trị do enum quyết
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:34-40`,
  `packages/python/dw_platform/src/dw_platform/domain/approval.py:44-53`), và Studio thêm `queued`,
  `waiting`, `blocked` cho run (`docs/adr/0113-every-run-is-requested-and-queued-in-postgres.md:40-44`).
  Thiếu: giá trị lạ không bị cơ sở dữ liệu từ chối.
- `_deliver` ghi `UndeliverableEventError` như mọi lỗi khác
  (`apps/worker/src/dw_worker/consumers/outbox.py:51-56`) dù docstring của lớp nói thử lại không
  giúp gì (`apps/worker/src/dw_worker/consumers/outbox.py:44-45`); claim lấy mọi dòng còn lượt theo
  `occurred_at`, không có thời điểm sớm nhất
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:46-79`,
  `db/migrations/sql/0001_platform_baseline.sql:304-319`), poll mỗi giây và 3 lượt
  (`apps/worker/src/dw_worker/settings.py:54`, `apps/worker/src/dw_worker/settings.py:219`);
  `backlog` chỉ đếm dòng còn lượt
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:102-119`).
  Thiếu: ba lượt thử trong khoảng hai giây và thư chết không có số đo nào, như đã ghi ở
  `.claude/plans/platform-runtime.md:88-91`.
- Không câu lệnh nào ngoài test xóa dòng outbox đã xử lý (grep), và chính sách retention không có lớp
  cho outbox (`configs/policies/retention@1.7.0.yaml:23`). Thiếu: hạn giữ chưa ai quyết.
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
- Idempotency HTTP: dấu vân tay không có người gọi
  (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:48-68`), `complete` và
  `release` không có token
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:130-164`),
  không lane nào quét khóa (`db/migrations/sql/0002_http_idempotency.sql:67-69`). Ràng buộc: lỗi có
  thật, chủ là `app-standards` (Ngoài phạm vi).

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

### R6 — Công cụ có hiệu ứng chạy đúng một lần và không có cửa sau [Sửa]

Mỗi hiệu ứng của một công cụ chạy một lần dù lời gọi trùng nhau, và mọi thứ model gọi được đều đi qua
ToolExecutor (ADR-0108 (Accepted) quyết định 5, ADR-0116 (Accepted) quyết định 3 và 7).
Trước đây: executor tìm lần thành công rồi mới chạy handler (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-222`).

- R6.1 NẾU hai lời gọi cùng khóa chống lặp tới một công cụ có `side_effect_level` khác `none` chạy
  đồng thời, THÌ ToolExecutor PHẢI chạy handler đúng một lần.
- R6.2 NẾU người giữ một claim đã bị tiếp quản sau `expires_at` nhả claim, THÌ ToolExecutor PHẢI giữ
  nguyên claim của người giữ mới.
- R6.3 NẾU vai `dw_app` UPDATE một dòng `platform.tool_executions` hay ghi `status` ngoài tập mà
  CHECK `ck_tool_executions_status` cho phép (W1: `succeeded`, `failed`, cộng `simulated` từ
  tenant-config/03), THÌ PostgreSQL PHẢI từ chối câu lệnh và không đổi dòng nào.
- R6.4 NẾU danh sách công cụ của một lượt gọi model có mục không phải `BaseTool` của nền tảng (dict
  hay công cụ phía nhà cung cấp), THÌ runner PHẢI gọi model mà không có mục đó.
- R6.5 NẾU input của một lần gọi công cụ có khóa bí mật nằm trong mảng ở độ sâu bất kỳ, THÌ
  ToolExecutor PHẢI ghi giá trị đó là `[REDACTED]` trong audit `tool.failed` và trong thuộc tính span.
- R6.6 Agent do runner dựng PHẢI gắn cho model đúng các công cụ trong toolset của worker cộng
  `write_todos`, không có công cụ dựng sẵn nào của thư viện agent.
- R6.7 KHI một claim đã quá `expires_at` mà không lời gọi nào tiếp quản, lane `tool_claims_retention`
  PHẢI xóa claim đó ở lượt chạy kế tiếp của lane.

### R7 — Giới hạn tốc độ theo địa chỉ và một chính sách địa chỉ ra ngoài [Sửa]

Một client không lách giới hạn tốc độ bằng bearer ngẫu nhiên, và không lời gọi ra ngoài nào của nền
tảng tới địa chỉ không global (ADR-0115 (Accepted) quyết định 5).
Trước đây: khóa đếm là bearer khi có header (`apps/api/src/dw_api/middleware/rate_limit.py:36-41`).

- R7.1 NẾU một địa chỉ client gửi quá `10 × L` request trong một cửa sổ 60 giây tới một tiến trình
  API (L là `rate_limit_per_minute`), THÌ middleware giới hạn tốc độ PHẢI trả 429 từ request thứ
  `10 × L + 1`, dù mỗi request mang một bearer khác.
- R7.2 NẾU host của một URL ra ngoài phân giải tới một địa chỉ không global, multicast, hay dạng
  IPv4-mapped, 6to4, Teredo, NAT64 `64:ff9b::/96` của một địa chỉ như vậy, THÌ bộ kiểm URL ra ngoài
  PHẢI từ chối với `OutboundUrlError` trước khi mở kết nối, trừ host có tên trong danh sách máy chủ
  được phép.

### R8 — Kho dữ liệu đòi xác thực ở mọi profile và ảnh ghim digest [Sửa]

Một tiến trình trên mạng nội bộ không đọc được vector hay cache khi thiếu thông tin xác thực, và ảnh
chạy là đúng ảnh đã quét.
Trước đây: chỉ overlay dev đặt khóa Qdrant (`infra/compose/docker-compose.dev.yml:33`).

- R8.1 NẾU một client gọi Qdrant không kèm API key hoặc mở kết nối Valkey không kèm mật khẩu, ở
  profile compose bất kỳ, THÌ Qdrant và Valkey PHẢI từ chối kết nối đó (401 hay `NOAUTH`).
- R8.2 NẾU `settings.is_deployed` đúng mà `qdrant_api_key` trống, hoặc `REDIS_URL` của API không
  mang mật khẩu, THÌ tiến trình API hay worker đó PHẢI dừng lúc khởi động với lỗi cấu hình.
- R8.3 Mọi dòng `image:` của ảnh bên thứ ba trong `infra/compose/` PHẢI mang tag phiên bản cùng
  digest `@sha256:`.
- R8.4 Dịch vụ `postgres-exporter` PHẢI kết nối PostgreSQL bằng vai `dw_monitor` chỉ giữ
  `pg_monitor`.

### R9 — Run không kẹt ở `waiting_approval` và trạng thái có CHECK [Sửa]

Một thread không kẹt mãi sau khi resume chết, và PostgreSQL từ chối trạng thái lạ của run, yêu cầu
phê duyệt và quyết định.
Trước đây: resume chạy graph mà không đổi trạng thái (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:536-547`).

- R9.1 NẾU tiến trình resume một run chết hay bị hủy sau khi run rời `waiting_approval`, THÌ runner
  PHẢI cho lượt mới của cùng thread chạy sau ngưỡng `stale_run_after_seconds` của chính sách
  `worker_runs` (3600 giây) thay vì báo thread đang chờ duyệt.
- R9.2 NẾU hai yêu cầu resume cùng một run đến đồng thời, THÌ runner PHẢI chạy graph cho đúng một
  yêu cầu và trả 409 cho yêu cầu kia.
- R9.3 NẾU một câu lệnh ghi `status` của run ngoài `pending`, `running`, `waiting_approval`,
  `completed`, `failed`, `cancelled`, `queued`, `waiting`, `blocked`, `dead_lettered`, `status` của yêu cầu phê duyệt
  ngoài `pending`, `approved`, `rejected`, `cancelled`, `expired`, hay `outcome` của quyết định ngoài
  `approved`, `rejected`, THÌ PostgreSQL PHẢI từ chối câu lệnh và không đổi dòng nào.

### R10 — Outbox lùi thời gian khi thử lại và thư chết thấy được [Sửa]

Một sự kiện lỗi không đốt hết lượt thử trong hai giây, và sự kiện bỏ cuộc hiện trên số đo và cảnh
báo.
Trước đây: claim mọi dòng còn lượt theo `occurred_at` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:46-79`).

- R10.1 KHI lần giao thứ n của một sự kiện outbox thất bại mà sự kiện còn lượt, lane `outbox` PHẢI
  không claim lại sự kiện đó trước `min(30 × 2^(n-1), 3600)` giây sau lần thất bại.
- R10.2 NẾU một sự kiện thất bại ở lượt thứ `outbox_max_attempts` hoặc handler báo không giao được,
  THÌ lane `outbox` PHẢI đặt `dead_at` và không claim lại sự kiện đó.
- R10.3 Worker PHẢI xuất gauge `dw_outbox_dead_letters` bằng số sự kiện đang mang `dead_at`, bằng 0
  khi không có.
- R10.4 KHI người vận hành chạy script phát lại cho một sự kiện mang `dead_at`, script phát lại PHẢI
  đưa sự kiện về hàng đợi (xóa `dead_at`, `attempts` về 0) và ghi một audit đứng tên người vận hành đó
  trong cùng giao dịch.
- R10.5 NẾU `--operator` của script phát lại không phải một người vận hành, THÌ script phát lại PHẢI
  thoát với mã 1 và không đổi sự kiện nào.

### R11 — Offboarding xuất mỗi dòng đúng một lần, theo lô, và audit nêu tên lane [Sửa]

Người vận hành nhận gói xuất của một công ty có mỗi dòng đúng một lần, lane xuất không giữ cả bảng
trong bộ nhớ (YC6, D12), và audit của lần xóa đứng tên người vận hành đã yêu cầu kèm tên lane đã thi
hành quyết định đó (`CLAUDE.md`, "Agent and tool rules"; ADR-0011 (Accepted)).
Trước đây: danh mục xuất gồm cả partition, và mỗi bảng được đọc bằng một câu lệnh giữ mọi dòng (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-181`); audit `tenant.offboarding.purged` ghi `details` rỗng (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:236`).

- R11.1 KHI lane `offboarding` xuất dữ liệu của một tenant, lane `offboarding` PHẢI đưa mỗi dòng của
  mỗi bảng tenant, kể cả bảng phân vùng, vào gói xuất đúng một lần.
- R11.2 KHI lane `offboarding` đọc một bảng để xuất, mỗi câu lệnh đọc của lane `offboarding` PHẢI trả
  không quá 1.000 dòng, theo thứ tự khóa chính.
- R11.3 KHI lane `offboarding` ghi audit `tenant.offboarding.purged`, lane `offboarding` PHẢI đặt
  `details.lane` của audit đó bằng `offboarding`.

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
- G7 KHI request tới `/api/v1/health` hay `/api/v1/ready`, middleware giới hạn tốc độ PHẢI TIẾP TỤC
  không đếm request đó (test: `test_health_is_exempt_and_zero_disables`).
- G8 KHI lane `offboarding` xóa dữ liệu của một tenant, lane `offboarding` PHẢI TIẾP TỤC ghi audit
  `tenant.offboarding.purged` đứng tên người vận hành đã yêu cầu (test:
  `test_purge_records_an_audit_event_before_deleting_anything`).

## Trong phạm vi

- Hàng rào tenant và workspace của `DELETE /api/v1/knowledge/documents/{document_id}`,
  `GET /api/v1/memory/items` và lane `checkpoint_retention`; audit `knowledge.document.deleted`;
  allowlist của serializer checkpoint ở composition root.
- Trigger trạng thái tenant; xóa cache khi khóa, mở khóa và offboard, là cách tạm tới tenant-rbac/02,
  nơi phiên bản quyền vào khóa cache và ba lời gọi xóa cache được gỡ; quy tắc nối danh tính tạm,
  trigger và quyền của `dw_app` trên `platform.external_identities`.
- Thu quyền ghi của `dw_app` trên `platform.users`, `platform.platform_operators`, `platform.plans`;
  một nguồn cho quyền của `dw_provisioner`; dạng sub-SELECT cho mọi policy RLS.
- Bảng `platform.tool_execution_claims` (ADR-0108 (Accepted) quyết định 5), lane
  `tool_claims_retention`, CHECK và quyền của `platform.tool_executions`, lọc mục không phải
  `BaseTool`, che bí mật trong mảng, ghim `deepagents`, test hợp đồng danh sách công cụ.
- Xô giới hạn tốc độ theo địa chỉ; một chính sách địa chỉ trong `net_guard`; xác thực Qdrant và
  Valkey ở mọi profile; vai `dw_monitor`; digest cho ảnh bên thứ ba và kiểm CI của nó.
- Compare-and-set khi resume; CHECK trạng thái run, yêu cầu phê duyệt, quyết định; `available_at`,
  `dead_at`, gauge `dw_outbox_dead_letters`, cảnh báo `DwOutboxDeadLetters` và script phát lại thư chết
  của người vận hành.
- Hai test không thể đỏ và việc rà các mẫu cùng họ.
- Danh mục xuất của offboarding chỉ gồm bảng cha, đọc theo lô keyset trên khóa chính; `details.lane`
  của audit `tenant.offboarding.purged`.

## Ngoài phạm vi

| Việc                                                                                                                                       | Vì sao                                                                                                                                                                        | Chủ                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Idempotency HTTP gắn người gọi, fencing token, lane quét khóa                                                                              | Một chủ cho idempotency HTTP (ADR-0108 (Accepted) quyết định 4)                                                                                                               | `app-standards` ticket 02                      |
| Quyền trả về ở `GET /api/v1/auth/bootstrap` gồm permission set                                                                             | Thuộc vai và quyền của tenant                                                                                                                                                 | `tenant-rbac` ticket 01                        |
| Egress client ghim địa chỉ lúc kết nối, smokescreen                                                                                        | Kiểm DNS chỉ trước khi dùng là việc của egress client; ticket 05 sửa vị từ dùng chung                                                                                         | `connections-and-vault` (ADR-0115 (Accepted))  |
| IdP theo tenant, mã nhận lời mời thay bước email                                                                                           | Ticket 02 là quy tắc tạm; câu trả lời của dw-proterial có thể đẩy mã nhận lời mời sớm hơn W2 (DO-17.1)                                                                        | `org-and-principals`, W2 (ADR-0103 (Accepted)) |
| Giới hạn theo tenant dùng chung giữa các bản sao API qua `RateLimiterPort`; mất Valkey thì mỗi tiến trình giữ xô ở hạn mức chia số bản sao | DO-49: usage-and-limits là chủ duy nhất của giới hạn theo tenant; middleware của ticket 05 chỉ chặn ở cửa API theo địa chỉ và bearer                                          | `usage-and-limits`                             |
| Lease và tiếp quản run trong 90 giây (YC41)                                                                                                | Hàng đợi run chưa có                                                                                                                                                          | `workflow-engine` (ADR-0113 (Accepted))        |
| Ghi `expired` khi yêu cầu phê duyệt hết hạn, cùng YC52 và lane hẹn giờ                                                                     | Ticket 06 chỉ mở CHECK cho giá trị này; ở W1 phê duyệt chờ không hạn, nên phê duyệt mở và lượt chạy đỗ không có gì dọn khi không ai quyết, chấp nhận với lead giả lập (DO-31) | `workflow-engine`, W2 (ADR-0112 (Accepted))    |
| Mã hóa checkpoint bằng khóa theo tenant                                                                                                    | Cần KMS và saver mới (ADR-0112 (Accepted) quyết định 10)                                                                                                                      | `connections-and-vault`, `workflow-engine`     |
| TLS chặng nội bộ, sao lưu mã hóa, SLA báo sự cố 24 giờ từ khi nền tảng biết (DO-56.2)                                                      | W2 theo ADR-0123 (Accepted); runbook và sổ sự cố có trước chạy bóng                                                                                                           | `compliance-pdpl`                              |
| Hai chủ của quyền đăng tri thức toàn cục                                                                                                   | Hôm nay từ chối an toàn; R2.1 không mở thêm đường xóa tài liệu toàn cục                                                                                                       | đợt sau                                        |
| Xóa dòng outbox đã xử lý và hạn giữ của nó                                                                                                 | Hạn giữ là chủ đề không đoán và chưa ai quyết; bảng thời hạn của DO-52 không có outbox                                                                                        | đợt sau                                        |
| Gói xuất offboarding ghi ra đĩa và tải lên theo phần, để bộ nhớ của lane không tăng theo kích thước gói                                    | Ticket 07 chỉ đọc theo lô keyset như quyết định offboarding chọn; gói zip còn dựng trong bộ nhớ, và W1 chỉ có dữ liệu giả lập (YC89)                                          | `foundations-hardening`, đợt sau               |
| Xóa `platform.tool_executions.output` sau 30 ngày (ADR-0122 (Accepted) quyết 7) qua một hàm riêng của lane lưu giữ                         | R6.3 thu UPDATE của `dw_app` trên bảng này và không trả lại; telemetry-and-audit là chủ tệp chính sách retention và lane lưu giữ, như với payload của `run_steps`             | `telemetry-and-audit`                          |

## Kiểm soát

| #    | Kiểm soát                                                        | Yêu cầu      | Test âm                                                                                                                                                                                                                                       |
| ---- | ---------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FH1  | Test phủ route của grant và test tiến trình nền đỏ được          | R1.1, R1.2   | Thêm phụ thuộc ngữ cảnh grant vào `GET /api/v1/runs/{run_id}` → test phủ route đỏ; khẳng định "không còn tiến trình" trên lần quét cùng request với `sleep 300 &` → đỏ                                                                        |
| FH2  | Xóa tài liệu chỉ trong workspace của người gọi, vector của mình  | R2.1         | Qdrant thật: tenant B xóa id của A, workspace 2 xóa tài liệu workspace 1, mọi tenant xóa tài liệu toàn cục → 404, tài liệu vẫn tìm được; gỡ `tenant_id` khỏi filter tombstone → đỏ                                                            |
| FH3  | Xóa mềm có audit cùng giao dịch                                  | R2.2         | Audit ném lỗi → tài liệu không mang `status='deleted'`; ghi audit sau commit → đỏ                                                                                                                                                             |
| FH4  | Danh sách bộ nhớ theo clearance                                  | R2.3         | Clearance `internal` gọi `GET /api/v1/memory/items` → không có mục `confidential`; bỏ lọc → đỏ                                                                                                                                                |
| FH5  | Dọn checkpoint không chạm tenant khác                            | R2.4         | Hai tenant chung `thread_id`, B có checkpoint mới hơn → checkpoint mới nhất của A còn; bỏ so `tenant_id` ở `newer` → đỏ                                                                                                                       |
| FH6  | Checkpoint không dựng kiểu ngoài allowlist                       | R2.5         | Dòng có kiểu ngoài allowlist → nạp ra dict, không object nào được dựng; allowlist `True` → đỏ                                                                                                                                                 |
| FH7  | Tenant offboarding không quay lại `active`, `locked`             | R3.1, R3.2   | `unlock` tenant `offboarding` → 409, trạng thái giữ; UPDATE `offboarded → active` bằng `dw_provisioner` → trigger từ chối; gỡ trigger → đỏ                                                                                                    |
| FH8  | Khóa tenant có hiệu lực từ request kế tiếp                       | R3.3         | Cache giả trung thực, thành viên có context trong cache, khóa tenant → request kế tiếp 403; tới khi tenant-rbac/02 merge: bỏ xóa cache → đỏ; từ tenant-rbac/02: gỡ trigger `bump_access_version` trên `platform.tenants` → đỏ                 |
| FH9  | Chỉ nối qua email đã xác minh tới user chưa từng đăng nhập       | R4.1, R4.2   | Token `email_verified=false` trùng email lời mời → 403, không thêm danh tính; email đã xác minh của user đã đăng nhập → 403; gỡ kiểm → đỏ                                                                                                     |
| FH10 | Subject không khớp chéo issuer                                   | R4.3         | Issuer X, `sub` bằng subject của user chỉ biết qua issuer Y → 403, không AccessContext                                                                                                                                                        |
| FH11 | Danh tính đăng nhập của người vận hành chỉ qua `dw_provisioner`  | R4.4         | Bằng `dw_app`: INSERT danh tính đăng nhập cho người vận hành → từ chối; UPDATE danh tính → `permission denied`; DELETE danh tính đăng nhập → từ chối                                                                                          |
| FH12 | `dw_app` không ghi bảng quyền lực                                | R5.1         | Bằng `dw_app`: INSERT `platform.platform_operators`, UPDATE `platform.plans`, UPDATE `platform.users` → `permission denied`; khôi phục một GRANT → đỏ                                                                                         |
| FH13 | Quyền của `dw_provisioner` có một nguồn                          | R5.2         | Thêm một bảng vào danh sách của script mà migration không cấp → test so quyền đỏ                                                                                                                                                              |
| FH14 | Policy đọc setting một lần mỗi câu lệnh                          | R5.3         | ALTER một policy về dạng theo dòng → test catalog đỏ                                                                                                                                                                                          |
| FH15 | Công cụ có hiệu ứng chạy một lần                                 | R6.1, R6.2   | Hai lời gọi `external` cùng khóa trên executor, handler ngủ 0,5 giây → handler chạy một lần; nhả bằng token cũ → claim mới còn; gỡ claim → đỏ                                                                                                 |
| FH16 | Lần gọi công cụ chỉ thêm, trạng thái có CHECK                    | R6.3         | Bằng `dw_app`: UPDATE `platform.tool_executions` → `permission denied`; INSERT `status='bogus'` → CHECK từ chối                                                                                                                               |
| FH17 | Không có cửa sau quanh ToolExecutor                              | R6.4, R6.6   | Mục dict trong danh sách công cụ → model không nhận; agent từ factory thật với toolset rỗng → model chỉ thấy `write_todos`; thêm một công cụ dựng sẵn → đỏ                                                                                    |
| FH18 | Bí mật trong mảng bị che                                         | R6.5         | Input `{"items": [{"api_key": "sk-123"}]}` thất bại → audit `tool.failed` mang `[REDACTED]`; bỏ đệ quy vào list → đỏ                                                                                                                          |
| FH19 | Claim mồ côi có người dọn                                        | R6.7         | Claim quá hạn → hết sau một lượt lane, claim chưa hạn còn; không đăng ký lane → đỏ                                                                                                                                                            |
| FH20 | Giới hạn tốc độ không lách bằng bearer ngẫu nhiên                | R7.1         | `10 × L + 1` request từ một địa chỉ, mỗi request một bearer → request cuối 429; bỏ xô địa chỉ → đỏ                                                                                                                                            |
| FH21 | Không gọi ra địa chỉ không global                                | R7.2         | Resolver giả trả `100.64.0.1`, `100.100.100.200`, `224.0.0.1`, `ff02::1`, `64:ff9b::a9fe:a9fe` → `OutboundUrlError`; vị từ cũ → đỏ                                                                                                            |
| FH22 | Kho dữ liệu đòi xác thực                                         | R8.1, R8.2   | Settings `uat` thiếu `qdrant_api_key` → không khởi động; compose smoke gọi Qdrant không khóa → 401, Valkey không mật khẩu → `NOAUTH`                                                                                                          |
| FH23 | Ảnh bên thứ ba ghim digest                                       | R8.3         | Gỡ `@sha256:` khỏi một `image:` → kiểm CI đỏ                                                                                                                                                                                                  |
| FH24 | Exporter không dùng vai ứng dụng                                 | R8.4         | `DATA_SOURCE_NAME` dùng `dw_app` → kiểm compose đỏ; `dw_monitor` SELECT bảng tenant → `permission denied`                                                                                                                                     |
| FH25 | Run không kẹt ở `waiting_approval`                               | R9.1, R9.2   | Resume chết sau khi rời `waiting_approval`, `updated_at` lùi quá ngưỡng → lượt mới chạy; hai resume đồng thời → một chạy, một 409; bỏ compare-and-set → đỏ                                                                                    |
| FH26 | Trạng thái có CHECK theo enum                                    | R9.3         | `status='bogus'` → CHECK từ chối; thêm giá trị vào enum mà không vào CHECK → test catalog đỏ                                                                                                                                                  |
| FH27 | Outbox lùi thời gian                                             | R10.1        | Lỗi lần một → không claim lại khi `available_at` còn ở tương lai, lùi nó về quá khứ → claim lại; bỏ điều kiện `available_at` → đỏ                                                                                                             |
| FH28 | Thư chết không bị claim lại và thấy được                         | R10.2, R10.3 | Hết lượt → `dead_at` đặt, gauge 1, không claim lại; `UndeliverableEventError` → `dead_at` ngay lần đầu; bỏ điều kiện `dead_at` → đỏ                                                                                                           |
| FH29 | Chỉ người vận hành phát lại thư chết, có audit                   | R10.4, R10.5 | `--operator` không có trong `platform.platform_operators` → thoát 1, sự kiện vẫn mang `dead_at`, không có audit; người vận hành phát lại → sự kiện về hàng đợi và đúng một audit đứng tên người đó; bỏ kiểm người vận hành → đỏ               |
| FH30 | Gói xuất không lặp dòng của bảng phân vùng                       | R11.1        | Bảng phân vùng thử có partition tháng và DEFAULT mà `dw_app` đọc được theo tên, mỗi nơi một dòng của tenant → mỗi dòng có đúng một lần trong kết quả xuất; test viết trước, đỏ trên mã hiện có; bỏ lọc partition khỏi danh mục xuất → đỏ      |
| FH31 | Audit của lần xóa đứng tên người yêu cầu và nêu lane đã thi hành | G8, R11.3    | Purge một tenant có yêu cầu offboarding → audit `tenant.offboarding.purged` có actor là người yêu cầu và `details.lane` bằng `offboarding`; đổi actor sang `system_actor('offboarding')` → test G8 đỏ; ghi lại `details` rỗng → test R11.3 đỏ |

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
  catalog của `SqlTenantOffboarding`, nên ticket 07 chờ studio-skeleton/01 vì cùng sửa `offboarding.py`.
- tenant-config: cột `run_mode` của `platform.worker_runs` và đường resume dựng lại nó (tenant-config:R4.1,
  tenant-config:R4.5); ticket 06 chờ tenant-config/03 vì cùng ALTER bảng đó và cùng sửa đường resume
  (OPS-b).
- Ticket của spec khác chờ ticket ở đây theo dòng Blocked by của chính chúng (OPS-b);
  `scripts/check_plans.py --table` in bảng sống, spec này không chép lại.
- Seam: `ConsumerRegistry.register` và `build_retention_consumer` ở composition root của worker cho
  lane mới; `CachePort.delete_pattern` với `tenant_cache_pattern`; `classifications_for_clearance` là
  chủ duy nhất của clearance.
- Hợp đồng: ADR-0011 (Accepted); ADR-0103 (Accepted) quyết định 8; ADR-0105 (Accepted) quyết định 1; ADR-0108 (Accepted)
  quyết định 5; ADR-0112 (Accepted) quyết định 10; ADR-0113 (Accepted) quyết định 1; ADR-0115 (Accepted)
  quyết định 5; ADR-0116 (Accepted) quyết định 3 và 7.
- Kiểm lại khi: ADR-0103 (Accepted) đổi quyết định 8 → R4, ticket 02; FOG-34 chọn bản `deepagents` →
  R6.6, ticket 04; FOG-37 chốt allowlist → R2.5, ticket 02; ADR-0113 (Accepted) đổi tập trạng thái run →
  R9.3, ticket 06; phép đo của ticket 03 dưới ngưỡng → R5.3 rút, custom-objects và record-access kiểm
  lại dạng policy mà chúng bắt buộc cho bảng Studio; tenant-rbac/02 merge → R3.3, FH8, ticket 02 (ba lời
  gọi xóa cache được gỡ); studio-skeleton/01 đổi chữ ký hàm partition → ticket 03; tenant-config/03 đổi
  đường resume → ticket 06; studio-skeleton/01 đổi test phủ offboarding hay `STUDIO_EXCLUSIONS` → ticket 07;
  telemetry-and-audit đổi cách xóa `platform.tool_executions.output` → R6.3, ticket 04; tenant-config/03 đổi
  tập trạng thái của `platform.tool_executions` → R6.3, ticket 04.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D5: si-platform là tham chiếu và port có chọn lọc; spec này port thiết
  kế claim trước (si-platform `db/si/migrations/0040_tool_call_claims.sql`), ngữ nghĩa
  `email_verified`, xô địa chỉ `10 × L` và dạng InitPlan, viết lại thành revision Alembic trên
  `platform.*` với `dw_app`. Sửa: R4, R5.3, R6, R7.1.
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
- 23/10/2026 (agent, tạm): ticket 04 ghim `deepagents==0.7.15`, bản đang khóa; bản từ 0.7.23 trở lên
  mà ADR-0116 (Accepted) quyết định 7 đòi đi cùng `SkillsMiddleware` ở `tools-and-skills`, chọn qua
  FOG-34 và phải qua test của R6.6. Nếu sai thì: ticket 04 nâng thẳng lên bản FOG-34 chọn, kéo theo
  `langchain`, `langchain-core`, `langsmith`.
- 23/10/2026 (agent, tạm): claim quá `expires_at` không còn canh gì (ADR-0108 (Accepted) quyết định 5
  cho tiếp quản nó), nên lane `tool_claims_retention` xóa nó không cần hạn giữ thêm. Nếu sai thì: thêm
  hạn giữ vào `retention@1.7.0.yaml`.
- 23/10/2026 (agent, tạm): outbox lùi `min(30 × 2^(n-1), 3600)` giây sau lần thất bại thứ n rồi cộng
  jitter ngẫu nhiên từ 0 tới 20% khoảng đó, tính bằng `now()` của PostgreSQL như claim; jitter chỉ
  cộng nên mốc "không trước" của R10.1 giữ được. Nếu sai thì: đổi công thức ở R10.1 và test của nó.
- 23/10/2026 (agent, tạm): DO-31 theo khuyến nghị (a): yêu cầu phê duyệt hết hạn không bao giờ thành
  duyệt; CHECK ở R9.3 nhận `expired` cho `workflow-engine` ghi (ADR-0112 (Accepted)). Nếu sai thì:
  bỏ `expired` khỏi CHECK.
- 23/10/2026 (agent, tạm): README của worker (`configs/workers/README.md:14-17`) sửa ở ticket 04, vì
  ADR-0117 (Accepted) và ADR-0125 (Accepted) giao việc đó cho spec này. Nếu sai thì: chuyển sang
  spec đang giữ README.
- 23/10/2026 (Đạt): DO-17.1 theo (a): quy tắc nối danh tính tạm của ADR-0103 (Accepted) quyết định 8
  áp ngay từ P0; hỏi dw-proterial song song, trước khi ticket 02 merge, xem importer có dựa vào nối
  email chưa xác minh không và IdP của họ có gửi `email_verified` không; câu trả lời chỉ quyết việc
  đẩy mã nhận lời mời sớm hơn W2, không chặn ticket 02. Hỏi: Q1. Sửa: R4, ticket 02.
- 23/10/2026 (Đạt): DO-56.1 theo (a): người vận hành phát lại thư chết bằng một script có audit đứng
  tên mình, script đặt `app.tenant_id` theo từng sự kiện và chỉ đọc id; công ty chỉ xem lượt chạy lỗi
  trong Lịch sử chạy, không có route mới. Hỏi: Q2. Sửa: R10.4, thêm R10.5, FH29, ticket 06.
- 23/10/2026 (Đạt): DO-56.2 theo (a): SLA báo sự cố trong DPA là 24 giờ từ khi nền tảng biết, việc
  của compliance-pdpl ở W2. Sửa: hàng TLS và SLA ở Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-31 theo (a), xác nhận dòng tạm cùng ngày: hết hạn phê duyệt sang W2 cùng YC52
  và lane hẹn giờ; ở W1 phê duyệt chờ không hạn; CHECK ở R9.3 giữ `expired`, người ghi là
  workflow-engine ở W2. Sửa: hàng ghi `expired` ở Ngoài phạm vi, ticket 06.
- 23/10/2026 (Đạt): Khóa tenant có hiệu lực ngay theo (a): xóa cache ở route khóa, mở khóa và
  offboard là cách tạm tới tenant-rbac/02; ticket đó gỡ ba lời gọi, đổi phép đột biến của FH8 sang gỡ
  trigger `bump_access_version` trên `platform.tenants` và chờ ticket 02 này; FH8 giữ hành vi. Sửa:
  Trong phạm vi, FH8, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): H:studio-skeleton:offboarding theo (a): offboarding xuất qua bảng cha, bỏ
  partition con và đọc theo lô keyset ở ticket mới 07; actor của audit `tenant.offboarding.purged` giữ
  là người vận hành đã yêu cầu (ADR-0011 (Accepted)). Sửa: Hiện trạng, thêm R11, G8, FH30, ticket 07.
- 23/10/2026 (Đạt): DO-49 theo (a): một `RateLimiterPort` của usage-and-limits là chủ của giới hạn
  theo tenant; middleware của ticket 05 là chặn ở cửa API, không phải chủ thứ hai. Sửa: hàng giới hạn
  dùng chung ở Ngoài phạm vi, ticket 05.
- 23/10/2026 (Đạt): OPS-b: ticket 06 chờ tenant-config/03 (cùng ALTER `platform.worker_runs` và cùng
  đường resume); studio-skeleton/04 chờ ticket 05; org-and-principals/02 chờ ticket 02. Sửa: Phụ thuộc,
  ticket 06.
- 23/10/2026 (Đạt): OPS-j: phép đo trùng ticket khám phá chạy một lần: discovery/23 (FOG-78) chạy
  trước ticket 02 nếu kịp, ticket 02 không chờ nó; discovery/05 chạy trước ticket 03 trên thân đường
  găng; có `## Answer` thì ticket trỏ về đó, chưa có thì phép đo ở ticket là phép đo của ticket khám
  phá. Sửa: ticket 02, ticket 03.
- 23/10/2026 (agent, tạm): ticket 03 chờ studio-skeleton/01 và viết lại bản ba tham số của
  `platform._ensure_one_partition`, giữ việc thu quyền `dw_app` trên partition, theo cách sửa thứ nhất
  của phát hiện C:foundations-hardening/03~studio-skeleton/01; OPS-b không xét cặp này. Nếu sai thì:
  đảo chiều, studio-skeleton/01 chờ ticket 03 và giữ dạng policy của nó.
- 23/10/2026 (Đạt): DO-03.2 theo (a): port mã thuần của si-platform cần thỏa thuận viết, ghim commit
  và dòng đầu `Ported from si-platform`; spec này dựng lại thiết kế của si-platform (claim trước,
  `email_verified`, xô địa chỉ `10 × L`, dạng InitPlan) chứ không chép mã, nên không chờ thỏa thuận.
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
- 24/10/2026 (agent, tạm): agent-lifecycle/01 chờ ticket 06, không theo chiều ngược, vì ticket 06 dựng
  compare-and-set trên đường resume, nơi agent-lifecycle/01 chèn phép kiểm công tắc, và cạnh nằm ở dòng
  Blocked by của agent-lifecycle/01 (C:agent-lifecycle/01~compliance-pdpl/03). Sửa: ticket 06. Nếu sai thì: ticket 06
  chờ agent-lifecycle/01 và agent-lifecycle/01 bỏ cạnh của nó.
- 24/10/2026 (Đạt): xóa `platform.tool_executions.output` sau 30 ngày (ADR-0122 (Accepted) quyết 7) là việc
  của lane lưu giữ của telemetry-and-audit, chủ tệp chính sách retention và lane đó, qua một hàm riêng của
  lane; R6.3 giữ và `dw_app` không nhận lại UPDATE (phát hiện vòng 2 giữa ADR-0122 (Accepted) và
  foundations-hardening:R6.3). Sửa: Ngoài phạm vi, Phụ thuộc, ticket 04.
- 24/10/2026 (agent, tạm): tenant-config/04 chờ ticket 06, vì cả hai ALTER `platform.worker_runs` và CHECK
  `ck_worker_runs_status` có trước cột `run_manifest_hash`; cạnh nằm ở dòng Blocked by của tenant-config/04, ghi ở
  Comments của hai ticket (C:foundations-hardening/06~tenant-config/04). Sửa: ticket 06. Nếu sai thì: đảo chiều,
  ticket 06 chờ tenant-config/04 và tenant-config/04 bỏ cạnh của nó.
- 24/10/2026 (agent, tạm): CHECK `ck_worker_runs_status` của ticket 06 nhận thêm `dead_lettered`, trạng thái thư chết mà
  lane `studio_run_reaper` ghi (ADR-0113 (Accepted) quyết 3; workflow-engine:R5.7), như `queued`, `waiting`, `blocked`,
  vì workflow-engine:R3.2 để spec này là chủ duy nhất của CHECK đó (phát hiện CRITICAL vòng 3 giữa ADR-0113 (Accepted) và
  workflow-engine:R3.1). Sửa: R9.3, ticket 06. Nếu sai thì: R9.3 và ticket 06 bỏ `dead_lettered`, ticket của
  workflow-engine ghi giá trị đó thay CHECK bằng cùng tập cộng `dead_lettered` như tenant-config/03 làm với
  `ck_tool_executions_status`, và workflow-engine:R3.2 bỏ câu về chủ.

## Danh sách ticket

| #   | Ticket                                                                                                                                    |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Test không thể đỏ: walker route và tiến trình nền sandbox](issues/01-test-khong-the-do.md)                                               |
| 02  | [Hàng rào dữ liệu bị quên, vòng đời tenant, nối danh tính và checkpoint an toàn](issues/02-hang-rao-du-lieu-va-danh-tinh.md)              |
| 03  | [Thu quyền ghi thừa của dw_app và RLS đọc setting một lần mỗi câu lệnh](issues/03-quyen-dw-app-va-rls-initplan.md)                        |
| 04  | [ToolExecutor giành lượt trước hiệu ứng, không còn cửa sau](issues/04-toolexecutor-gianh-luot-khong-cua-sau.md)                           |
| 05  | [Biên mạng: rate limit theo địa chỉ, net_guard chỉ địa chỉ toàn cầu, Qdrant và Valkey có xác thực](issues/05-bien-mang-va-kho-du-lieu.md) |
| 06  | [Run không kẹt ở waiting_approval, CHECK trạng thái, outbox lùi thời gian và thư chết](issues/06-run-va-outbox-khong-ket.md)              |
| 07  | [Offboarding xuất mỗi dòng một lần, đọc theo lô keyset](issues/07-offboarding-xuat-mot-lan-theo-lo.md)                                    |
