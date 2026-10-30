# Hiệu ứng theo mức bảo đảm, biên mạng, run và outbox không kẹt

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 25/10/2026
Duyệt: agent, tạm theo ủy quyền 30/10/2026
Sẵn sàng: ĐẠT (30/10/2026; 0 CRITICAL, 0 HIGH; ticket 01)

Studio gọi công cụ có hiệu ứng, gọi ra ngoài và xếp run cùng sự kiện lên các dịch vụ nền đang để một hiệu ứng
chạy hai lần, một client lách giới hạn tốc độ, một URL ra ngoài tới địa chỉ nội bộ, kho vector và cache không
đòi xác thực, một run kẹt sau khi resume chết và một sự kiện outbox đốt hết lượt thử trong hai giây. Spec này sửa
các lỗi đã đo trong code ngày 23/10/2026, mỗi bản vá kèm một test âm đã thấy đỏ trước bản vá và đỏ lại khi hoàn
tác; không thêm tính năng. Nó phục vụ YC4, YC41 (mức đồng thời và nhật ký lần gửi của các mức bảo đảm, V4.30), YC63
và phần công cụ của YC5. Spec tách từ foundations-hardening (Quyết định), nên số R6-R10, G5, G7 và số kiểm soát giữ nguyên,
kiểm soát mang tiền tố RH; ticket của spec khác chạm cùng hàm, bảng hay tệp với một ticket ở đây chờ ticket đó
qua dòng Blocked by của chúng (ADR-0103 (Accepted), ADR-0108 (Accepted)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

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
  cho outbox (`configs/policies/retention@1.8.0.yaml:23`). Thiếu: hạn giữ chưa ai quyết.
- Idempotency HTTP: dấu vân tay không có người gọi
  (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:48-68`), `complete` và
  `release` không có token
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:130-164`),
  không lane nào quét khóa (`db/migrations/sql/0002_http_idempotency.sql:67-69`). Ràng buộc: lỗi có
  thật, chủ là `app-standards` (Ngoài phạm vi).

## Mục tiêu

Số R6-R10 giữ nguyên từ foundations-hardening, nơi chúng được viết; spec này không có R1-R5.

### R6 — Công cụ có hiệu ứng không gửi trùng theo mức bảo đảm, và không có cửa sau [Sửa]

Hai lời gọi cùng khóa không cùng gửi khi claim còn hạn (mức đồng thời), mỗi lần gửi ra ngoài có một dòng `dispatched`
bền trước lời gọi, một lần gửi chưa biết kết quả không bao giờ được gửi lại mù mà giao cho `on_unknown` của Hành động
(mức không khóa của SMTP: tự động thì tối đa một lần), và mọi thứ model gọi được đều đi qua ToolExecutor (V4.30;
ADR-0108 (Accepted) quyết định 5, ADR-0116 (Accepted) quyết định 3 và 7). Mức có khóa hay tra cứu không ở lát này (H-5).
Trước đây: executor tìm lần thành công rồi mới chạy handler (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-222`).

- R6.1 NẾU hai lời gọi cùng khóa chống lặp tới một công cụ có `side_effect_level` khác `none` chạy
  đồng thời trong khi claim của một lời gọi còn hạn, THÌ ToolExecutor PHẢI chạy handler cho đúng một lời gọi, lời
  gọi kia nhận replay hay `ConflictError` (mức đồng thời; V4.30).
- R6.2 NẾU người giữ một claim đã bị tiếp quản sau `expires_at` nhả claim, THÌ ToolExecutor PHẢI giữ
  nguyên claim của người giữ mới.
- R6.3 NẾU vai `dw_app` UPDATE một dòng `platform.tool_executions` hay ghi `status` ngoài tập mà
  CHECK `ck_tool_executions_status` cho phép (W1: `succeeded`, `failed`, `dispatched`, `outcome_unknown` từ lần tạo,
  cộng `simulated` từ tenant-config/03), THÌ PostgreSQL PHẢI từ chối câu lệnh và không đổi dòng nào.
- R6.4 NẾU danh sách công cụ của một lượt gọi model có mục không phải `BaseTool` của nền tảng (dict
  hay công cụ phía nhà cung cấp), THÌ runner PHẢI gọi model mà không có mục đó.
- R6.5 NẾU input của một lần gọi công cụ có khóa bí mật nằm trong mảng ở độ sâu bất kỳ, THÌ
  ToolExecutor PHẢI ghi giá trị đó là `[REDACTED]` trong audit `tool.failed` và trong thuộc tính span.
- R6.6 Agent do `build_agent` dựng cho một worker không khai `sub_agents` PHẢI gắn cho model đúng các công cụ trong toolset của worker mà run có đủ scope,
  không có công cụ dựng sẵn nào của thư viện agent (đo 30/10/2026 trên `deepagents` 0.7.15: `create_agent` không cài
  `write_todos` hay công cụ nào khác; công cụ `task` của `sub_agents` thuộc `tools-and-skills`).
- R6.7 KHI một claim đã quá `expires_at` mà không lời gọi nào tiếp quản, lane `tool_claims_retention`
  PHẢI xóa claim đó ở lượt chạy kế tiếp của lane.
- R6.8 NẾU một lần ghi claim của tenant A mang `workspace_id` của một workspace thuộc tenant B, THÌ
  PostgreSQL PHẢI từ chối lần ghi đó và không ghi dòng nào.
- R6.9 NẾU khóa của một lời gọi có một lần gửi chưa biết kết quả (một dòng `dispatched` của khóa trong
  `platform.tool_executions` mà chưa dòng `succeeded` hay `failed` nào mang `dispatch_id` của nó), THÌ ToolExecutor PHẢI không gọi handler
  và trả kết quả có kiểu `outcome_unknown` để bên gọi làm theo `on_unknown` của Hành động, dù claim của lời gọi là
  claim mới, claim tiếp quản hay claim mà lane đã dọn (V4.30; H-5).
- R6.10 KHI một lời gọi gặp claim cùng khóa đã quá `expires_at` mà khóa đó không có lần gửi nào chưa biết kết quả
  (R6.9), ToolExecutor PHẢI tiếp quản claim rồi đi tiếp bước ghi `dispatched` và gọi handler, vì mọi lần gửi trước của
  khóa đã có kết quả biết được (V4.30).
- R6.11 KHI ToolExecutor sắp gọi handler của một lời gọi có hiệu ứng ra ngoài nền tảng (W1: công cụ có
  `side_effect_level` là `external` hay `critical`, Hành động `connector_action` của tools-and-skills cũng vậy) mà không bị giả lập (tenant-config:R5.1), ToolExecutor PHẢI
  chèn một dòng `dispatched` cho khóa đó và commit nó trong một giao dịch riêng trước lời gọi ra ngoài (V4.30).
- R6.12 KHI lời gọi handler sau một dòng `dispatched` kết thúc, ToolExecutor PHẢI ghi đúng một dòng kết thúc mang `dispatch_id`
  của lần gửi đó theo kết quả có kiểu: `succeeded` khi handler trả kết quả, `failed` mang mã khi handler báo `not_dispatched`
  hay `rejected`, và `outcome_unknown` khi handler báo `outcome_unknown` hay ném một lỗi không có kiểu nào trong ba
  kiểu đó (V4.30; `failure-modes.md` #7).
- R6.13 NẾU claim của một lời gọi đã bị tiếp quản hay đã quá `expires_at` lúc lời gọi đó sắp chèn dòng `dispatched`,
  THÌ ToolExecutor PHẢI không chèn dòng đó và không gọi handler, nên người giữ cũ treo quá hạn không gửi song song với
  người giữ mới (V4.30).
- R6.14 NẾU tenant B gọi một công cụ với cùng `tool_name` và khóa chống lặp như một claim còn hạn, một lần thành công
  hay một lần gửi chưa biết kết quả của tenant A, THÌ ToolExecutor PHẢI chạy handler của B như thể khóa chưa từng
  dùng: B không nhận replay output của A, không nhận `ConflictError` và không nhận `outcome_unknown` vì dòng của A
  (CLAUDE.md, Tenancy and authorization).

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

## Hành vi giữ nguyên

Số G giữ nguyên từ foundations-hardening; G5 ở cả hai spec (Quyết định 25/10/2026).

- G5 KHI một run được duyệt rồi tiến trình khởi động lại, runner PHẢI TIẾP TỤC chạy tiếp run từ
  checkpoint (test: `test_pause_restart_resume_approved`).
- G7 KHI request tới `/api/v1/health` hay `/api/v1/ready`, middleware giới hạn tốc độ PHẢI TIẾP TỤC
  không đếm request đó (test: `test_health_is_exempt_and_zero_disables`).

## Trong phạm vi

- Bảng `platform.tool_execution_claims` (ADR-0108 (Accepted) quyết định 5), lane
  `tool_claims_retention`, CHECK, cột `dispatch_id` và quyền của `platform.tool_executions`, lọc mục không phải
  `BaseTool`, che bí mật trong mảng, ghim `deepagents`, test hợp đồng danh sách công cụ.
- Nhật ký lần gửi trong `platform.tool_executions` (V4.30): dòng `dispatched` commit trước lời gọi ra ngoài và rào bằng
  `claim_token`, dòng kết thúc theo kết quả có kiểu, kiểm lần gửi chưa biết kết quả trước mọi lần gọi handler (R6.9
  tới R6.13), và ba lỗi có kiểu của một lần gửi mà `dw_agent_runtime` khai cho handler ném (`not_dispatched`,
  `rejected` mang mã, `outcome_unknown`); đây là bước giành lượt và ghi `dispatched` mà tools-and-skills/01 đưa vào sổ
  bước của `ToolExecutor` (tools-and-skills:R2.6; H-3).
- Xô giới hạn tốc độ theo địa chỉ; một chính sách địa chỉ trong `net_guard`; xác thực Qdrant và
  Valkey ở mọi profile; vai `dw_monitor`; digest cho ảnh bên thứ ba và kiểm CI của nó.
- Compare-and-set khi resume; CHECK trạng thái run, yêu cầu phê duyệt, quyết định; `available_at`,
  `dead_at`, gauge `dw_outbox_dead_letters`, cảnh báo `DwOutboxDeadLetters` và script phát lại thư chết
  của người vận hành, cùng mảnh `configs/copy/audit_actions.d/runtime-hardening.yaml` mang nhãn của audit
  `platform.outbox.replayed` (telemetry-and-audit:R1.6; H-21).

## Ngoài phạm vi

| Việc                                                                                                                                             | Vì sao                                                                                                                                                                                              | Chủ                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Idempotency HTTP gắn người gọi, fencing token, lane quét khóa                                                                                    | Một chủ cho idempotency HTTP (ADR-0108 (Accepted) quyết định 4)                                                                                                                                     | `app-standards` ticket 02                                |
| Egress client ghim địa chỉ lúc kết nối, smokescreen                                                                                              | Kiểm DNS chỉ trước khi dùng là việc của egress client; ticket 02 sửa vị từ dùng chung                                                                                                               | `connections-and-vault` (ADR-0115 (Accepted))            |
| Giới hạn theo tenant dùng chung giữa các bản sao API qua `RateLimiterPort`; mất Valkey thì mỗi tiến trình giữ xô ở hạn mức chia số bản sao       | DO-49: usage-and-limits là chủ duy nhất của giới hạn theo tenant; middleware của ticket 02 chỉ chặn ở cửa API theo địa chỉ và bearer                                                                | `usage-and-limits`                                       |
| Lease và tiếp quản run trong 90 giây (YC41)                                                                                                      | Hàng đợi run chưa có                                                                                                                                                                                | `workflow-engine` (ADR-0113 (Accepted))                  |
| Ghi `expired` khi yêu cầu phê duyệt hết hạn, cùng YC52 và lane hẹn giờ                                                                           | Ticket 03 chỉ mở CHECK cho giá trị này; ở W1 một phê duyệt không có hạn của riêng nó, và hạn chót của lượt chạy kết thúc lượt còn chờ cùng phê duyệt mở của nó (V4.14, ADR-0113 (Accepted) quyết 3) | `workflow-engine`, W2 (ADR-0112 (Accepted))              |
| TLS chặng nội bộ, sao lưu mã hóa, SLA báo sự cố 24 giờ từ khi nền tảng biết (DO-56.2)                                                            | W2 theo ADR-0123 (Accepted); runbook và sổ sự cố có trước chạy bóng                                                                                                                                 | `compliance-pdpl`                                        |
| Xóa dòng outbox đã xử lý và hạn giữ của nó                                                                                                       | Hạn giữ là chủ đề không đoán và chưa ai quyết; bảng thời hạn của DO-52 không có outbox                                                                                                              | đợt sau                                                  |
| Xóa `platform.tool_executions.output` sau 30 ngày (ADR-0122 (Accepted) quyết 7) qua một hàm riêng của lane lưu giữ                               | R6.3 thu UPDATE của `dw_app` trên bảng này và không trả lại; telemetry-and-audit là chủ chính sách retention và lane lưu giữ, như với payload của `run_steps`                                       | `telemetry-and-audit`                                    |
| Egress trả kết quả có kiểu (`not_dispatched`, `rejected`, `outcome_unknown`, `succeeded`) và ném ba lỗi có kiểu của ticket 01                    | V4.30 mục 2; egress client là chủ kết quả có kiểu (ADR-0115 (Accepted) quyết 6), ticket 01 chỉ khai ba lỗi mà executor đọc (R6.12)                                                                  | `connections-and-vault` (ticket 03)                      |
| Điểm chờ `outcome_review`, route giải dưới `runs.reconcile`, wrapper chỉ thử lại khi `not_dispatched` hay `rejected` thử lại được                | V4.30 mục 5, 6: lát này trả `outcome_unknown` (R6.9, R6.12), động cơ đỗ lượt và giải; lần giải đóng lần gửi chưa biết kết quả bằng một dòng kết thúc (Phụ thuộc)                                    | `workflow-engine` (ticket 03, ticket 08)                 |
| W2: mức có khóa hay tra cứu (`idempotency.mode` khác `none`, `reconciliation`, `resend_same_key`, `lookup_then_resend`, lane `studio_reconcile`) | H-5: tác động ra ngoài duy nhất của W1 là SMTP, không khóa, không tra cứu; khối `delivery` có đủ trường nhưng bộ nạp từ chối các giá trị đó tới trình kết nối đầu tiên khai chúng                   | `connections-and-vault`, `workflow-engine`, đợt sau (W2) |
| Cột `credential_version` của `platform.tool_executions`                                                                                          | H-10: egress phân giải bí mật nên connections-and-vault là chủ cột; ticket 01 không đổi vì cột đó                                                                                                   | `connections-and-vault`                                  |

## Kiểm soát

| #    | Kiểm soát                                                                    | Yêu cầu      | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---- | ---------------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RH15 | Hai lời gọi cùng khóa không cùng gửi khi claim còn hạn                       | R6.1, R6.2   | Hai lời gọi `external` cùng khóa trên executor, handler ngủ 0,5 giây → handler chạy một lần; nhả bằng token cũ → claim mới còn; gỡ claim → đỏ                                                                                                                                                                                                                                                                                                                                                                         |
| RH16 | Lần gọi công cụ chỉ thêm, trạng thái có CHECK                                | R6.3         | Bằng `dw_app`: UPDATE `platform.tool_executions` → `permission denied`; INSERT `status='bogus'` → CHECK từ chối; INSERT `dispatched` và `outcome_unknown` → nhận; CHECK thiếu một trong hai giá trị đó → ca nhận đỏ                                                                                                                                                                                                                                                                                                   |
| RH17 | Không có cửa sau quanh ToolExecutor                                          | R6.4, R6.6   | Mục dict trong danh sách công cụ → model không nhận; agent từ factory thật với toolset rỗng → model không thấy công cụ nào; thêm một công cụ dựng sẵn → đỏ                                                                                                                                                                                                                                                                                                                                                            |
| RH18 | Bí mật trong mảng bị che                                                     | R6.5         | Input `{"items": [{"api_key": "sk-123"}]}` thất bại → audit `tool.failed` mang `[REDACTED]`; bỏ đệ quy vào list → đỏ                                                                                                                                                                                                                                                                                                                                                                                                  |
| RH19 | Claim mồ côi có người dọn                                                    | R6.7         | Claim quá hạn → hết sau một lượt lane, claim chưa hạn còn; không đăng ký lane → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| RH20 | Giới hạn tốc độ không lách bằng bearer ngẫu nhiên                            | R7.1         | `10 × L + 1` request từ một địa chỉ, mỗi request một bearer → request cuối 429; bỏ xô địa chỉ → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                    |
| RH21 | Không gọi ra địa chỉ không global                                            | R7.2         | Resolver giả trả `100.64.0.1`, `100.100.100.200`, `224.0.0.1`, `ff02::1`, `64:ff9b::a9fe:a9fe` → `OutboundUrlError`; vị từ cũ → đỏ                                                                                                                                                                                                                                                                                                                                                                                    |
| RH22 | Kho dữ liệu đòi xác thực                                                     | R8.1, R8.2   | Settings `uat` thiếu `qdrant_api_key` → không khởi động; compose smoke gọi Qdrant không khóa → 401, Valkey không mật khẩu → `NOAUTH`                                                                                                                                                                                                                                                                                                                                                                                  |
| RH23 | Ảnh bên thứ ba ghim digest                                                   | R8.3         | Gỡ `@sha256:` khỏi một `image:` → kiểm CI đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| RH24 | Exporter không dùng vai ứng dụng                                             | R8.4         | `DATA_SOURCE_NAME` dùng `dw_app` → kiểm compose đỏ; `dw_monitor` SELECT bảng tenant → `permission denied`                                                                                                                                                                                                                                                                                                                                                                                                             |
| RH25 | Run không kẹt ở `waiting_approval`                                           | R9.1, R9.2   | Resume chết sau khi rời `waiting_approval`, `updated_at` lùi quá ngưỡng → lượt mới chạy; hai resume đồng thời → một chạy, một 409; bỏ compare-and-set → đỏ                                                                                                                                                                                                                                                                                                                                                            |
| RH26 | Trạng thái có CHECK theo enum                                                | R9.3         | `status='bogus'` → CHECK từ chối; thêm giá trị vào enum mà không vào CHECK → test catalog đỏ                                                                                                                                                                                                                                                                                                                                                                                                                          |
| RH27 | Outbox lùi thời gian                                                         | R10.1        | Lỗi lần một → không claim lại khi `available_at` còn ở tương lai, lùi nó về quá khứ → claim lại; bỏ điều kiện `available_at` → đỏ                                                                                                                                                                                                                                                                                                                                                                                     |
| RH28 | Thư chết không bị claim lại và thấy được                                     | R10.2, R10.3 | Hết lượt → `dead_at` đặt, gauge 1, không claim lại; `UndeliverableEventError` → `dead_at` ngay lần đầu; bỏ điều kiện `dead_at` → đỏ                                                                                                                                                                                                                                                                                                                                                                                   |
| RH29 | Chỉ người vận hành phát lại thư chết, có audit                               | R10.4, R10.5 | `--operator` không có trong `platform.platform_operators` → thoát 1, sự kiện vẫn mang `dead_at`, không có audit; người vận hành phát lại → sự kiện về hàng đợi và đúng một audit đứng tên người đó; bỏ kiểm người vận hành → đỏ                                                                                                                                                                                                                                                                                       |
| RH32 | Claim không trỏ sang workspace của tenant khác                               | R6.8         | Bằng `dw_app` gắn tenant A: INSERT `platform.tool_execution_claims` với `workspace_id` của một workspace tenant B → lỗi khóa ngoại, không dòng nào; đổi FK ghép thành FK một cột `workspace_id` → test đỏ                                                                                                                                                                                                                                                                                                             |
| RH33 | Lần gửi chưa biết kết quả không bao giờ bị gửi lại mù                        | R6.9, R6.10  | K4 trên PostgreSQL thật: nhà cung cấp giả nhận lời gọi và trả 2xx, tiến trình chết trước dòng kết thúc → lời gọi kế tiếp cùng khóa, với claim quá hạn hay sau khi lane đã dọn claim, nhận `outcome_unknown`, handler không chạy, nhà cung cấp giả có đúng 1 lời gọi; dòng kết thúc của lần gửi là `outcome_unknown` → như trên; claim quá hạn mà lần gửi trước đã `failed` hay chưa có `dispatched` nào → tiếp quản, handler chạy; gỡ kiểm lần gửi chưa biết kết quả → nhà cung cấp giả nhận lời gọi thứ hai, test đỏ |
| RH34 | Nhật ký lần gửi bền trước lời gọi ra ngoài, kết quả không rõ không thành lỗi | R6.11, R6.12 | Lúc nhà cung cấp giả nhận lời gọi, một kết nối thứ hai đọc thấy dòng `dispatched` đã commit; T: nhà cung cấp giả áp dụng rồi để lời gọi hết thời gian → dòng `outcome_unknown`, không `failed`; handler ném lỗi không có kiểu sau `dispatched` → `outcome_unknown`; `not_dispatched`, `rejected` → `failed` mang mã; gỡ bước ghi `dispatched`, hay ghi `failed` cho lỗi không có kiểu → ca K4 hay T gửi hai lần, test đỏ                                                                                              |
| RH35 | Người giữ claim cũ không gửi sau khi bị tiếp quản                            | R6.13        | S: người giữ cũ dừng ngay trước bước ghi `dispatched` tới quá `expires_at`, người mới tiếp quản và gửi, rồi người cũ chạy tiếp → không có dòng `dispatched` thứ hai, handler của người cũ không chạy, nhà cung cấp giả có đúng 1 lời gọi; gỡ rào `claim_token` ở câu chèn `dispatched` → nhà cung cấp giả nhận 2 lời gọi, test đỏ                                                                                                                                                                                     |
| RH36 | Khóa của tenant này không chặn, không replay cho tenant khác                 | R6.14        | Tenant A có claim còn hạn, một lần `succeeded` và một lần gửi chưa biết kết quả với cùng `tool_name` và khóa; tenant B gọi khóa đó → handler của B chạy một lần, B nhận output của chính nó; bỏ `tenant_id` khỏi khóa chính của claim → test đỏ                                                                                                                                                                                                                                                                       |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi trong
  Comments của ticket.
- `make ci && make test-integration` xanh, gồm integration của `dw_platform`, `dw_agent_runtime`, `apps/api`
  và `apps/worker`, và compose smoke của Qdrant và Valkey có xác thực.
- `reviewing-feature-security` và `reviewing-deployment-security` chạy cho từng ticket.

## Phụ thuộc

- foundations-hardening: ticket 01 của spec đó (hai test không thể đỏ được sửa trước) đi trước cả ba ticket ở
  đây; dạng policy RLS mà `test_rls_coverage.py` đòi lúc merge, có thể đã đổi ở foundations-hardening/03
  (foundations-hardening:R5.3), cho bảng `platform.tool_execution_claims` của ticket 01.
- tenant-config: cột `run_mode` của `platform.worker_runs` và đường resume dựng lại nó (tenant-config:R4.1,
  tenant-config:R4.5); ticket 03 chờ tenant-config/03 vì cùng ALTER bảng đó và cùng sửa đường resume (OPS-b).
- org-and-principals: `uq_workspaces_tenant_id_id` (org-and-principals:R1.1, ticket 01 của spec đó), đích của FK
  ghép `(tenant_id, workspace_id)` của `platform.tool_execution_claims` ở ticket 01; ticket 01 chờ
  org-and-principals/01.
- Ticket của spec khác chờ ticket ở đây theo dòng Blocked by của chính chúng (OPS-b);
  `scripts/check_plans.py --table` in bảng sống, spec này không chép lại.
- tools-and-skills: thứ tự bước của `ToolExecutor` (tools-and-skills:R2.6) đặt bước giành lượt và ghi `dispatched` của
  ticket 01 ngay trước bước gọi handler, và tools-and-skills/01, đi sau ticket 01, đưa bước đó vào sổ bước ở composition
  root (tools-and-skills:R2.7; H-3).
- connections-and-vault: egress client của `.claude/plans/studio/connections-and-vault/issues/03-egress-client-allowlist-va-chu-ky.md`
  ném ba lỗi có kiểu mà ticket 01 khai, theo kết quả có kiểu của nó (ADR-0115 (Accepted) quyết 6); trước ticket đó,
  handler nào không ném chúng thì mọi lỗi sau `dispatched` ghi `outcome_unknown` (R6.12).
- workflow-engine: lần giải điểm chờ `outcome_review` của `.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`
  đóng lần gửi chưa biết kết quả bằng một dòng kết thúc mang `dispatch_id` của dòng `dispatched` đó trước khi Bước
  chạy lại, `succeeded` kèm bằng chứng cho "Đã
  nhận" và `failed` cho "Chưa nhận, gửi lại cùng khóa", vì không có dòng đó thì R6.9 lại trả `outcome_unknown` (V4.30
  mục 6).
- telemetry-and-audit: catalog hành động gộp từ một mảnh mỗi spec (telemetry-and-audit:R1.6, telemetry-and-audit:R1.10;
  H-21); ticket 03 thêm mảnh của spec này cho `platform.outbox.replayed`, và test AST của catalog đọc mảnh đó khi
  `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`, đi sau ticket 01 và ticket 03, vào.
- Seam: `ConsumerRegistry.register` và `build_retention_consumer` ở composition root của worker cho lane
  `tool_claims_retention`; `ToolExecutor` nhận `ToolClaimPort` qua constructor.
- Hợp đồng: ADR-0108 (Accepted) quyết định 5; ADR-0113 (Accepted) quyết định 1; ADR-0115 (Accepted) quyết định
  5; ADR-0116 (Accepted) quyết định 3 và 7.
- Kiểm lại khi: FOG-34 chọn bản `deepagents` → R6.6, ticket 01; ADR-0113 (Accepted) đổi tập trạng thái run →
  R9.3, ticket 03; tenant-config/03 đổi đường resume → ticket 03; telemetry-and-audit đổi cách xóa
  `platform.tool_executions.output` → R6.3, ticket 01; tenant-config/03 đổi tập trạng thái của
  `platform.tool_executions` → R6.3, ticket 01; org-and-principals/01 đổi `uq_workspaces_tenant_id_id` → R6.8,
  RH32, ticket 01; foundations-hardening/03 đổi dạng policy RLS → ticket 01; connections-and-vault đổi tập kết quả có
  kiểu của egress → R6.12, ticket 01; workflow-engine đổi cách lần giải `outcome_review` đóng lần gửi chưa biết kết quả
  → R6.9, ticket 01; connections-and-vault thêm cột `credential_version` vào `platform.tool_executions` (H-10) → R6.3,
  ticket 01; tools-and-skills đổi chỗ bước giành lượt và ghi `dispatched` trong sổ bước → R6.11, ticket 01; một trình
  kết nối khai khóa hay tra cứu (W2, H-5) → R6.9, R6.10; telemetry-and-audit đổi định dạng hay chỗ của mảnh nhãn audit
  (H-21) → Trong phạm vi, ticket 03.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D5: si-platform là tham chiếu và port có chọn lọc; spec này port thiết kế claim
  trước (si-platform `db/si/migrations/0040_tool_call_claims.sql`) và xô địa chỉ `10 × L`, viết lại thành revision
  Alembic trên `platform.*` với `dw_app`. Sửa: R6, R7.1.
- 23/10/2026 (agent, tạm): ticket 01 ghim `deepagents==0.7.15`, bản đang khóa; bản từ 0.7.23 trở lên
  mà ADR-0116 (Accepted) quyết định 7 đòi đi cùng `SkillsMiddleware` ở `tools-and-skills`, chọn qua
  FOG-34 và phải qua test của R6.6. Nếu sai thì: ticket 01 nâng thẳng lên bản FOG-34 chọn, kéo theo
  `langchain`, `langchain-core`, `langsmith`.
- 23/10/2026 (agent, tạm): claim quá `expires_at` không còn canh gì (ADR-0108 (Accepted) quyết định 5
  cho tiếp quản nó), nên lane `tool_claims_retention` xóa nó không cần hạn giữ thêm. Nếu sai thì: thêm
  một mảnh hạn giữ vào `configs/policies/retention.d/`.
- 23/10/2026 (agent, tạm): outbox lùi `min(30 × 2^(n-1), 3600)` giây sau lần thất bại thứ n rồi cộng
  jitter ngẫu nhiên từ 0 tới 20% khoảng đó, tính bằng `now()` của PostgreSQL như claim; jitter chỉ
  cộng nên mốc "không trước" của R10.1 giữ được. Nếu sai thì: đổi công thức ở R10.1 và test của nó.
- 23/10/2026 (agent, tạm): DO-31 theo khuyến nghị (a): yêu cầu phê duyệt hết hạn không bao giờ thành
  duyệt; CHECK ở R9.3 nhận `expired` cho `workflow-engine` ghi (ADR-0112 (Accepted)). Nếu sai thì:
  bỏ `expired` khỏi CHECK.
- 23/10/2026 (agent, tạm): README của worker (`configs/workers/README.md:14-17`) sửa ở ticket 01, vì
  ADR-0117 (Accepted) và ADR-0125 (Accepted) giao việc đó cho spec này. Nếu sai thì: chuyển sang
  spec đang giữ README.
- 23/10/2026 (Đạt): DO-56.1 theo (a): người vận hành phát lại thư chết bằng một script có audit đứng
  tên mình, script đặt `app.tenant_id` theo từng sự kiện và chỉ đọc id; công ty chỉ xem lượt chạy lỗi
  trong Lịch sử chạy, không có route mới. Hỏi: Q2. Sửa: R10.4, thêm R10.5, RH29, ticket 03.
- 23/10/2026 (Đạt): DO-56.2 theo (a): SLA báo sự cố trong DPA là 24 giờ từ khi nền tảng biết, việc
  của compliance-pdpl ở W2. Sửa: hàng TLS và SLA ở Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-31 theo (a), xác nhận dòng tạm cùng ngày: hết hạn phê duyệt sang W2 cùng YC52
  và lane hẹn giờ; ở W1 phê duyệt chờ không hạn; CHECK ở R9.3 giữ `expired`, người ghi là
  workflow-engine ở W2. Sửa: hàng ghi `expired` ở Ngoài phạm vi, ticket 03.
- 23/10/2026 (Đạt): DO-49 theo (a): một `RateLimiterPort` của usage-and-limits là chủ của giới hạn
  theo tenant; middleware của ticket 02 là chặn ở cửa API, không phải chủ thứ hai. Sửa: hàng giới hạn
  dùng chung ở Ngoài phạm vi, ticket 02.
- 23/10/2026 (Đạt): OPS-b: ticket 03 chờ tenant-config/03 (cùng ALTER `platform.worker_runs` và cùng đường
  resume); studio-skeleton/04 chờ ticket 02. Sửa: Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-03.2 theo (a): port mã thuần của si-platform cần thỏa thuận viết, ghim commit và dòng
  đầu `Ported from si-platform`; spec này dựng lại thiết kế của si-platform (claim trước, xô địa chỉ `10 × L`)
  chứ không chép mã, nên không chờ thỏa thuận.
- 24/10/2026 (agent, tạm): agent-lifecycle/01 chờ ticket 03, không theo chiều ngược, vì ticket 03 dựng
  compare-and-set trên đường resume, nơi agent-lifecycle/01 chèn phép kiểm công tắc, và cạnh nằm ở dòng
  Blocked by của agent-lifecycle/01 (C:agent-lifecycle/01~compliance-pdpl/03). Sửa: ticket 03. Nếu sai thì: ticket 03
  chờ agent-lifecycle/01 và agent-lifecycle/01 bỏ cạnh của nó.
- 24/10/2026 (Đạt): xóa `platform.tool_executions.output` sau 30 ngày (ADR-0122 (Accepted) quyết 7) là việc
  của lane lưu giữ của telemetry-and-audit, chủ tệp chính sách retention và lane đó, qua một hàm riêng của
  lane; R6.3 giữ và `dw_app` không nhận lại UPDATE (phát hiện vòng 2 giữa ADR-0122 (Accepted) và
  runtime-hardening:R6.3). Sửa: Ngoài phạm vi, Phụ thuộc, ticket 01.
- 24/10/2026 (agent, tạm): tenant-config/04 chờ ticket 03, vì cả hai ALTER `platform.worker_runs` và CHECK
  `ck_worker_runs_status` có trước cột `run_manifest_hash`; cạnh nằm ở dòng Blocked by của tenant-config/04, ghi ở
  Comments của hai ticket (C:runtime-hardening/03~tenant-config/04). Sửa: ticket 03. Nếu sai thì: đảo chiều,
  ticket 03 chờ tenant-config/04 và tenant-config/04 bỏ cạnh của nó.
- 24/10/2026 (agent, tạm): CHECK `ck_worker_runs_status` của ticket 03 nhận thêm `dead_lettered`, trạng thái thư chết mà
  lane `studio_run_reaper` ghi (ADR-0113 (Accepted) quyết 3; workflow-engine:R5.7), như `queued`, `waiting`, `blocked`,
  vì workflow-engine:R3.2 để spec này là chủ duy nhất của CHECK đó (phát hiện CRITICAL vòng 3 giữa ADR-0113 (Accepted) và
  workflow-engine:R3.1). Sửa: R9.3, ticket 03. Nếu sai thì: R9.3 và ticket 03 bỏ `dead_lettered`, ticket của
  workflow-engine ghi giá trị đó thay CHECK bằng cùng tập cộng `dead_lettered` như tenant-config/03 làm với
  `ck_tool_executions_status`, và workflow-engine:R3.2 bỏ câu về chủ.
- 24/10/2026 (agent, tạm): `workspace_id` của `platform.tool_execution_claims` là FK ghép `(tenant_id, workspace_id)` tới
  `platform.workspaces (tenant_id, id)` qua `uq_workspaces_tenant_id_id` của org-and-principals/01, `ON DELETE CASCADE`,
  với chỉ mục `(tenant_id, workspace_id)`, thay cho FK một cột, vì kiểm khóa ngoại không đi qua RLS nên FK một cột để
  claim của một công ty trỏ tới workspace của công ty khác (CLAUDE.md, Tenancy and authorization và Data model rules;
  org-and-principals:R1.1); ticket 01 cần org-and-principals/01 đi trước. Sửa: Phụ thuộc, ticket 01. Nếu sai thì:
  claim bỏ khóa ngoại tới workspace kèm lý do (dòng chỉ sống tới `expires_at`, như `platform.tool_executions` hôm nay
  không có khóa ngoại nào), và ticket 01 không chờ org-and-principals/01.
- 24/10/2026 (agent, tạm): ticket 01 chờ org-and-principals/01 ở dòng Blocked by, vì `uq_workspaces_tenant_id_id`, đích
  của FK ghép `(tenant_id, workspace_id)` của `platform.tool_execution_claims`, chỉ ticket đó tạo
  (org-and-principals:R1.1); cạnh đã kiểm không tạo vòng trên đồ thị ticket của area, và dòng trên thôi nói cạnh chỉ là
  đề xuất ở Comments. Sửa: Phụ thuộc, Quyết định, ticket 01. Nếu sai thì: claim bỏ khóa ngoại tới workspace kèm lý do,
  và ticket 01 bỏ cạnh.
- 24/10/2026 (agent, tạm): FK ghép `(tenant_id, workspace_id)` của `platform.tool_execution_claims` có ca âm chéo tenant ở
  R6.8 với kiểm soát RH32: claim của tenant A mang `workspace_id` của tenant B bị PostgreSQL từ chối, và đổi FK ghép thành
  FK một cột làm test đỏ, vì test âm cho ghi chéo tenant là bắt buộc (CLAUDE.md, Tenancy and authorization) và một kiểm
  soát mà test chưa từng thấy đỏ không chứng minh gì (failure-modes #3). Sửa: R6.8, RH32, Phụ thuộc, ticket 01. Nếu sai
  thì: R6.8 và RH32 rút bằng `[Bỏ]` cùng lúc claim bỏ khóa ngoại tới workspace kèm lý do.
- 24/10/2026 (Đạt): một spec quá cỡ của `writing-plan-specs` được tách khi tới `checking-plan-readiness`,
  foundations-hardening trước (vòng 3 của kiểm nhất quán, nhận theo khuyến nghị): phần hiệu ứng, biên mạng,
  run và outbox của spec đó (R6-R10, G7, ticket 04, 05, 06, kiểm soát FH15-FH29 và FH32) thành spec này, giữ
  nguyên số R và số G, kiểm soát giữ số với tiền tố RH. Sửa: mọi mục.
- 25/10/2026 (agent, tạm): ba ticket chuyển sang mang số 01, 02, 03 (từ 04, 05, 06), vì `scripts/check_plans.py`
  đòi mỗi thư mục ticket đếm từ 01 (kiểm `numbering`); số R, G và kiểm soát, những mã mà spec và ticket khác dẫn,
  giữ nguyên, và mọi chỗ dẫn ở area đổi theo. Các dòng trước hai dòng này là dòng của foundations-hardening về
  phần chuyển sang, giữ ngày và người quyết, với số ticket và mã kiểm soát đổi theo. G5 ở cả spec này lẫn
  foundations-hardening, cùng câu và cùng test, vì foundations-hardening/02 (allowlist serializer của
  checkpoint) và ticket 03 ở đây (compare-and-set khi resume) cùng có thể làm vỡ việc chạy tiếp một run đã
  duyệt. Sửa: Danh sách ticket, Hành vi giữ nguyên, ticket 01-03. Nếu sai thì: ba ticket giữ số 04-06 và kiểm
  `numbering` nhận một thư mục tách bắt đầu từ số khác 01; G5 chỉ ở một spec, và ticket của spec kia chạy test
  của nó ở dòng Xong.
- 25/10/2026 (Đạt): V4.30: lời hứa "đúng một lần" thành các mức bảo đảm gọi bằng tên (nội bộ, có khóa hay tra cứu,
  không khóa, đồng thời) cùng điểm chờ `outcome_review`; ở lát này, CHECK `ck_tool_executions_status` có `dispatched`
  và `outcome_unknown` từ lần tạo, executor chèn một dòng `dispatched` commit trong giao dịch riêng trước lời gọi ra
  ngoài, bảng vẫn chỉ thêm, tiếp quản claim quá hạn tách hai ca theo dòng `dispatched` (chưa có thì chạy lại, có mà
  chưa có dòng kết thúc thì theo `on_unknown`, không bao giờ chạy lại mù), và câu "đúng một lần" của R6 viết lại theo
  mức bảo đảm. Sửa: tiêu đề, đoạn mở, R6, R6.1, R6.3, thêm R6.9-R6.13, RH15, RH16, thêm RH33-RH35, Trong phạm vi,
  Ngoài phạm vi, Phụ thuộc, ticket 01.
- 25/10/2026 (agent, tạm): cách áp V4.30 ở lát này: hai ca tiếp quản là hai tiêu chí mới, R6.10 (claim quá hạn, không
  lần gửi nào chưa biết kết quả: tiếp quản rồi gửi) và R6.9 (lần gửi chưa biết kết quả: không gọi handler, trả
  `outcome_unknown`), còn R6.2 giữ ca nhả bằng token cũ mà nó vẫn nói, để không mã nào đổi nghĩa; "lần gửi chưa biết
  kết quả" là dòng `dispatched` mới nhất chưa có `succeeded` hay `failed` sau nó, nên dòng kết thúc `outcome_unknown`
  cũng chặn gửi lại, và R6.9 kiểm ở mọi lần giành claim, vì lane `tool_claims_retention` có thể đã dọn claim của lần
  gửi đó (K4); dòng `dispatched` chỉ ghi cho lời gọi ra ngoài nền tảng không bị giả lập, vì hiệu ứng nội bộ đúng một
  lần nhờ khóa của node lưu cùng giao dịch với lần ghi (mức nội bộ, custom-objects); câu chèn `dispatched` rào bằng
  `claim_token` (R6.13), vì mức không khóa hứa 0 lần tự gửi lại ở cả ca S của ma trận sập; executor ghi kết quả theo
  ba lỗi có kiểu mà `dw_agent_runtime` khai, egress client ném (bên dùng khai Protocol), và một lỗi không có kiểu sau
  `dispatched` là `outcome_unknown`, không `failed`, vì `failed` mở đường thử lại của wrapper (ca T, `failure-modes.md`
  #7). Sửa: R6.9-R6.13, RH33-RH35, Trong phạm vi, Ngoài phạm vi, Phụ thuộc, ticket 01. Nếu sai thì: R6.2 viết lại
  thành ca tiếp quản và ca nhả token sang mã mới, dòng `outcome_unknown` không chặn gửi lại (chỉ `dispatched` thiếu dòng
  kết thúc chặn), mọi lời gọi có `side_effect_level` khác `none` đều ghi `dispatched`, ca S chỉ được hứa trong hạn
  claim (R6.13 rút), hay connections-and-vault/03 khai kiểu kết quả và phần đọc của R6.12 dời sang một ticket đi sau
  ticket đó, vì ticket 01 đi trước nó.
- 30/10/2026 (agent, tạm theo ủy quyền): sửa theo gate của ticket 01. R6.14 và RH36 thêm ca âm đọc chéo tenant
  (claim, replay, lần gửi chưa biết kết quả), vì CLAUDE.md đòi test âm cho đọc lẫn ghi chéo tenant mà R6.8 chỉ phủ ghi.
  R6.11 ở W1 phủ công cụ `external` và `critical`, vì ADR-0116 (Accepted) quyết 3 và ADR-0108 (Accepted) quyết 5 ghi
  `dispatched` trước mọi lời gọi handler ra ngoài, và `connector_action` chưa có khi ticket 01 chạy. Dòng kết thúc mang
  `dispatch_id` (id dòng `dispatched` của nó) và một index duy nhất một phần cho mỗi `dispatch_id` một dòng `succeeded`
  hay `failed`, vì "sau nó" không có cột thứ tự (`id` là uuid, `started_at` có thể trùng) và dòng kết thúc muộn của
  người giữ cũ phải đóng đúng lần gửi của nó. R6.6 bỏ `write_todos`: đo trên `deepagents` 0.7.15, `build_agent` gắn
  cho model đúng toolset đã lọc scope, không gì khác. Neo retention sang `retention@1.8.0.yaml`. Sửa: R6.6, R6.9, R6.11,
  R6.12, thêm R6.14, RH17, RH33, thêm RH36, Hiện trạng, Trong phạm vi, ticket 01. Nếu sai thì: thứ tự theo một cột
  `bigint` tăng dần thay cho `dispatch_id`; R6.11 chỉ ghi `dispatched` cho `connector_action` và công cụ `external`
  của nền tảng nhận tiếp quản mù như hôm nay.
- 30/10/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01-03.
- 30/10/2026 (agent, tạm theo ủy quyền): Duyệt spec theo `## Ủy quyền` của studio.md. Theo
  lượt xác nhận của gate ticket 01: RH36 bỏ vế "đọc `platform.tool_executions` không gắn tenant", vì FORCE RLS theo
  `app.tenant_id` đã thu hẹp câu đọc nên đột biến đó không đỏ được; R6.6 nói rõ worker không khai `sub_agents`; Phụ
  thuộc của workflow-engine nêu `dispatch_id`. Nếu sai thì: RH36 thêm một đột biến đọc bằng vai bỏ qua RLS.

## Danh sách ticket

| #   | Ticket                                                                                                                                    |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [ToolExecutor giành lượt trước hiệu ứng, không còn cửa sau](issues/01-toolexecutor-gianh-luot-khong-cua-sau.md)                           |
| 02  | [Biên mạng: rate limit theo địa chỉ, net_guard chỉ địa chỉ toàn cầu, Qdrant và Valkey có xác thực](issues/02-bien-mang-va-kho-du-lieu.md) |
| 03  | [Run không kẹt ở waiting_approval, CHECK trạng thái, outbox lùi thời gian và thư chết](issues/03-run-va-outbox-khong-ket.md)              |
