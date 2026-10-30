# 01 — ToolExecutor giành lượt trước hiệu ứng, không còn cửa sau

Status: resolved
Blocked by: .claude/plans/studio/foundations-hardening/issues/01-test-khong-the-do.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, R6.12, R6.13, R6.14, RH15, RH16, RH17, RH18, RH19, RH32, RH33, RH34, RH35, RH36

## Mục tiêu

Hai lời gọi cùng khóa không cùng gửi khi claim còn hạn, mỗi lần gửi ra ngoài có một dòng `dispatched` commit trước lời
gọi, một lần gửi chưa biết kết quả không bao giờ bị gửi lại mù mà trả `outcome_unknown` cho bên gọi, claim mồ côi có
người dọn, claim không trỏ được sang workspace của tenant khác, bản ghi lần gọi chỉ thêm và có CHECK, và không mục
nào tới model mà không qua ToolExecutor (R6.1-R6.13, RH15-RH19, RH32-RH35; V4.30; ADR-0108 (Accepted) quyết định 5;
ADR-0116 (Accepted) quyết định 3 và 7). Mọi loại công cụ Studio sau này thừa hưởng claim và nhật ký lần gửi từ đây;
đây là bước giành lượt và ghi `dispatched` mà tools-and-skills/01 đưa vào sổ bước (H-3), và là một phần của cổng E1.

## Việc cần làm

Claim và nhật ký lần gửi trước hiệu ứng (R6.1-R6.3, R6.7-R6.13):

1. Revision Alembic mới `db/migrations/versions/*_tool_execution_claims.py` (id ngẫu nhiên): bảng
   `platform.tool_execution_claims` theo ADR-0108 (Accepted) quyết định 5:
    - cột `tenant_id uuid NOT NULL` (FK tới tenant, `ON DELETE CASCADE`), `workspace_id uuid NOT NULL`
      (FK ghép `(tenant_id, workspace_id)` tới `platform.workspaces (tenant_id, id)` qua `uq_workspaces_tenant_id_id`
      của org-and-principals/01, `ON DELETE CASCADE`, index `(tenant_id, workspace_id)`), `tool_name text NOT NULL`,
      `idempotency_key text NOT NULL`, `run_id uuid NOT NULL`,
      `claim_token uuid NOT NULL DEFAULT gen_random_uuid()`, `claimed_at timestamptz NOT NULL DEFAULT now()`,
      `expires_at timestamptz NOT NULL`;
    - khóa chính `(tenant_id, tool_name, idempotency_key)`; CHECK `expires_at > claimed_at`; index
      `(expires_at)` cho lane dọn; tên ràng buộc theo `NAMING_CONVENTION`;
    - RLS ENABLE và FORCE; policy tenant theo dạng `test_rls_coverage.py` đòi lúc merge (foundations-hardening/03 có
      thể đã đổi dạng); policy `worker_drain` đọc `app.worker_drain` cho lane dọn;
    - `dw_app` giữ SELECT, INSERT, DELETE; REVOKE UPDATE mà default privileges cấp.
2. Cùng revision: REVOKE UPDATE trên `platform.tool_executions` khỏi `dw_app` (DELETE giữ vì
   offboarding xóa theo tenant); CHECK `ck_tool_executions_status` cho
   `status IN ('succeeded', 'failed', 'dispatched', 'outcome_unknown')` ngay từ lần tạo (V4.30), sau khi
   `SELECT DISTINCT status` trên dữ liệu hiện có không thấy giá trị khác (ghi Comments); bảng vẫn chỉ thêm, và
   `uq_tool_executions_idempotency` chỉ phủ dòng `succeeded` (`db/migrations/sql/0001_platform_baseline.sql:698`) nên
   dòng `dispatched` không đụng nó; cột `dispatch_id uuid`, `id` của dòng `dispatched` mà dòng kết thúc đóng (NULL ở mọi dòng khác), CHECK
   `ck_tool_executions_dispatch_id` `dispatch_id IS NULL OR status <> 'dispatched'`, và index duy nhất một phần
   `uq_tool_executions_dispatch_resolved` trên `(tenant_id, dispatch_id)` `WHERE dispatch_id IS NOT NULL AND status IN
('succeeded', 'failed')` (mỗi lần gửi có nhiều nhất một dòng `succeeded` hay `failed`; dòng `outcome_unknown` trước
   nó được phép; R6.9, R6.12); tenant-config/03, đi sau ticket này, thay CHECK đó bằng cùng tập cộng `simulated`
   (ADR-0111 (Accepted)). Cột
   `output` quá 30 ngày do lane lưu giữ của telemetry-and-audit xóa qua một hàm riêng của lane
   (ADR-0122 (Accepted) quyết 7), nên không trả UPDATE cho `dw_app` để lane đó dùng.
3. Port `ToolClaimPort` do `dw_agent_runtime` khai (claim, tiếp quản claim quá hạn, nhả theo token, tìm lần gửi chưa
   biết kết quả, chèn dòng `dispatched` có rào), adapter SQL nối ở composition root; `ToolExecutor` nhận port qua
   constructor. Cùng chỗ khai: ba lỗi có kiểu mà handler ném sau khi lần gửi bắt đầu, `NotDispatchedError`,
   `RejectedError` (mang mã nhà cung cấp) và `OutcomeUnknownError`, đều là `DWError` mang thuộc tính `outcome`
   (`not_dispatched`, `rejected`, `outcome_unknown`) và `code` có sẵn `upstream_unavailable`, không thêm giá trị vào
   `ErrorCode` (hợp đồng API, ADR-0108 (Accepted) quyết 1); executor ném `OutcomeUnknownError` cho bên gọi ở R6.9 và R6.12,
   không thử lại, và đường agent đưa nó tới model qua `PlatformToolErrorsMiddleware` như mọi lỗi có kiểu, để egress client của connections-and-vault/03 ném
   theo kết quả có kiểu của nó (ADR-0115 (Accepted) quyết 6).
4. `ToolExecutor._execute`, khi có khóa chống lặp và `side_effect_level` khác `none` (R6.1): INSERT claim trước `find_succeeded`, với
   `expires_at = now() + timeout_seconds × (1 + max_retries) + 30 giây`:
    - giành được, hay tiếp quản claim quá hạn bằng `DELETE ... WHERE claim_token = :old AND expires_at < now()` rồi
      INSERT lại (R6.10): tìm lần thành công (có thì replay); khóa có lần gửi chưa biết kết quả, tức một dòng `dispatched`
      của khóa mà chưa dòng `succeeded` hay `failed` nào mang `dispatch_id` của nó, thì trả `outcome_unknown` và không gọi handler
      (R6.9); không thì, với lời gọi có `side_effect_level` `external` hay `critical` không bị giả lập, chèn dòng `dispatched` bằng
      `INSERT ... SELECT ... WHERE EXISTS` (claim mang `claim_token` của mình còn hạn) và commit trong giao dịch riêng,
      không chèn được dòng nào thì dừng mà không gọi handler (R6.11, R6.13); gọi handler; ghi đúng một dòng kết thúc
      mang `dispatch_id` theo kết quả có kiểu, `succeeded`, `failed` mang mã cho `NotDispatchedError` và `RejectedError`, `outcome_unknown`
      cho `OutcomeUnknownError` và mọi lỗi khác ném sau `dispatched` (R6.12); rồi nhả claim trong `finally` bằng token
      của mình;
    - không giành được và claim hiện có còn hạn: có lần thành công thì replay, còn lại `ConflictError` (R6.1).
      Bước này là bước giành lượt và ghi `dispatched` của thứ tự tools-and-skills:R2.6, ngay trước bước gọi handler;
      ticket này dựng nó trong `_execute` hiện có, tools-and-skills/01 đưa nó vào sổ bước (H-3).
5. `SqlToolExecutionStore.record`: `IntegrityError` trên `uq_tool_executions_idempotency` thành đọc
   lại lần thành công và replay, không ném lỗi.
6. Lane `tool_claims_retention`: một `RetentionPrunePort` xóa claim có `expires_at < now()`, đăng ký ở
   `apps/worker/src/dw_worker/main.py` bằng `build_retention_consumer` với
   `RETENTION_INTERVAL_SECONDS` như `checkpoint_retention`; thêm lane vào test tập lane
   `apps/worker/tests/unit/test_worker.py`.

Không còn cửa sau (R6.4, R6.5, R6.6):

7. `ScopedToolsMiddleware` và `OfferedToolsOnlyMiddleware` bỏ mọi mục không phải `BaseTool` và log
   kiểu của mục (không log nội dung); `build_agent` từ chối mục không phải `BaseTool`.
8. `redact_mapping` đi vào list và tuple ở mọi độ sâu, che theo cùng `is_sensitive_key`.
9. Ghim `deepagents==0.7.15` trong `packages/python/dw_agent_runtime/pyproject.toml` rồi `uv lock`
   (Quyết định của spec); test hợp đồng: dựng agent bằng `build_agent` thật với model giả, toolset
   rỗng và toolset một công cụ, khẳng định tập tên công cụ gắn cho model đúng bằng toolset đã lọc theo scope
   của run, không `write_todos` (đo 30/10/2026: `create_agent` không cài nó).
10. Sửa comment liệt kê công cụ dựng sẵn ở `langchain_tools.py` cho khớp comment đã đo ở
    `agent_factory.py`, và bỏ `write_todos` khỏi `_ALWAYS_ALLOWED` vì không gì cài nó (đảo
    `test_the_todo_tool_survives_because_a_middleware_owns_it` thành ca bị ẩn); sửa `configs/workers/README.md`: runner đọc `autonomy_level` qua
    `lower_autonomy` và bảng của `autonomy.py`, câu "read by nothing" không còn đúng (ADR-0117 (Accepted),
    ADR-0125 (Accepted)).

## Tiêu chí chấp nhận

- [x] R6.1 (RH15): integration với PostgreSQL thật, `asyncio.gather` hai lời gọi một công cụ
      `external` cùng khóa trên `ToolExecutor` trực tiếp (không qua graph), handler ngủ 0,5 giây →
      handler chạy đúng một lần, lời gọi kia nhận replay hoặc `ConflictError`; gỡ bước claim → đỏ (ghi
      Comments).
- [x] R6.2 (RH15): claim của người giữ cũ bị tiếp quản; người giữ cũ nhả bằng token cũ → claim của người mới còn; bỏ
      điều kiện token ở câu nhả → đỏ.
- [x] R6.3 (RH16): bằng `dw_app`: UPDATE `platform.tool_executions` → `permission denied`; INSERT
      `status='bogus'` → CHECK từ chối; INSERT `dispatched` và `outcome_unknown` → nhận; khẳng định catalog trong
      `test_privileges.py`.
- [x] R6.9 (RH33): K4 trên PostgreSQL thật: nhà cung cấp giả nhận lời gọi và trả 2xx, tiến trình chết sau dòng
      `dispatched` và trước dòng kết thúc → lời gọi kế tiếp cùng khóa với claim quá hạn, và một lời gọi nữa sau khi lane
      `tool_claims_retention` đã dọn claim, đều nhận `outcome_unknown`, handler không chạy, nhà cung cấp giả có đúng 1
      lời gọi; dòng mới nhất của khóa là `outcome_unknown` → như trên; gỡ kiểm lần gửi chưa biết kết quả → nhà cung
      cấp giả nhận lời gọi thứ hai, test đỏ.
- [x] R6.10 (RH33): claim quá hạn mà khóa chưa có `dispatched` nào, và claim quá hạn mà lần gửi trước đã `failed` →
      lời gọi kế tiếp tiếp quản, ghi `dispatched` rồi chạy handler một lần.
- [x] R6.11 (RH34): lúc nhà cung cấp giả nhận lời gọi, một kết nối thứ hai đọc thấy dòng `dispatched` của khóa đã
      commit; gỡ bước ghi `dispatched` → ca K4 của R6.9 gửi hai lần, test đỏ.
- [x] R6.12 (RH34): T: nhà cung cấp giả áp dụng rồi để lời gọi hết thời gian → dòng kết thúc `outcome_unknown`, không
      `failed`; handler ném lỗi không có kiểu sau `dispatched` → `outcome_unknown`; `NotDispatchedError` và
      `RejectedError` → `failed` mang mã; trả kết quả → `succeeded`; mỗi lần gửi đúng một dòng kết thúc; ghi `failed`
      cho lỗi không có kiểu → test đỏ.
- [x] R6.13 (RH35): S: người giữ cũ dừng ngay trước bước ghi `dispatched` tới quá `expires_at`, người mới tiếp quản và
      gửi, rồi người cũ chạy tiếp → không có dòng `dispatched` thứ hai, handler của người cũ không chạy, nhà cung cấp
      giả có đúng 1 lời gọi; gỡ rào `claim_token` ở câu chèn → nhà cung cấp giả nhận 2 lời gọi, test đỏ.
- [x] R6.14 (RH36): integration trên PostgreSQL thật: tenant A có claim còn hạn, một dòng `succeeded` và một lần gửi
      chưa biết kết quả cho cùng `tool_name` và khóa; tenant B gọi khóa đó → handler của B chạy đúng một lần, B nhận
      output của chính nó; bỏ `tenant_id` khỏi khóa chính của claim → đỏ.
- [x] R6.4 (RH17): một mục dict trong danh sách công cụ → model giả không nhận nó ở cả hai middleware;
      `build_agent` với mục không phải `BaseTool` → lỗi; hoàn tác bộ lọc → đỏ.
- [x] R6.5 (RH18): lời gọi thất bại với input `{"items": [{"api_key": "sk-123"}]}` → audit
      `tool.failed` và thuộc tính span mang `[REDACTED]`; bỏ đệ quy vào list → đỏ.
- [x] R6.6 (RH17): test hợp đồng ở bước 9 xanh trên bản ghim (toolset rỗng → model không thấy công cụ nào); thêm một `BaseTool` ngoài toolset vào
      agent → đỏ.
- [x] R6.7 (RH19): một claim quá hạn và một claim chưa hạn → sau một lượt `tool_claims_retention` chỉ
      claim chưa hạn còn; bỏ đăng ký lane → test tập lane đỏ.
- [x] R6.8 (RH32): bằng `dw_app` gắn tenant A, INSERT `platform.tool_execution_claims` với `workspace_id` của một
      workspace tenant B → lỗi khóa ngoại 23503, không dòng nào; migration thử đổi FK ghép thành FK một cột
      `workspace_id` → test đỏ.
- [x] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-222`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:200`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/tool_execution_store.py:81-118`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:587`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:301-306`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:453-457`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:414-418`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:28-34`
- `packages/python/dw_observability/src/dw_observability/redaction.py:28-40`
- `packages/python/dw_agent_runtime/pyproject.toml:18`
- `configs/workers/README.md:14-17`
- `db/migrations/sql/0001_platform_baseline.sql:698`
- `docs/adr/0108-one-error-envelope-and-caller-bound-idempotency.md:90-97`
- spec: R6, RH15-RH19, RH32-RH35; V4.30; org-and-principals:R1.1 (`uq_workspaces_tenant_id_id`); tools-and-skills:R2.6
  (chỗ của bước); si-platform `db/si/migrations/0040_tool_call_claims.sql`.

## Comments

- 2026-10-24 (agent): vòng sửa 4, lượt ba: `workspace_id` của `platform.tool_execution_claims` là FK ghép tới
  `platform.workspaces (tenant_id, id)` thay cho FK một cột, vì kiểm khóa ngoại không đi qua RLS (Quyết định 24/10/2026
  của spec). Đề xuất thêm `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md` vào Blocked
  by: `uq_workspaces_tenant_id_id`, đích của FK đó, chỉ ticket đó tạo (org-and-principals:R1.1).
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: Blocked by thêm org-and-principals/01 như đề xuất ở dòng trên (cạnh đã kiểm
  không tạo vòng); tiêu chí R6.8 với kiểm soát RH32 là ca âm của FK ghép đó: claim của tenant A mang `workspace_id` của
  tenant B bị từ chối (hai dòng Quyết định 24/10/2026 của spec).
- 2026-10-25 (agent): ticket chuyển từ foundations-hardening/04 sang đây thành ticket 01 khi spec tách (hai dòng Quyết định cuối của spec); kiểm soát FH15-FH19, FH32 thành RH15-RH19, RH32, cùng số, và cạnh tới ticket 01 cùng thư mục cũ thành đường dẫn tới foundations-hardening/01. Không đổi việc cần làm, không thêm cạnh.
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt và dòng tạm cùng ngày của spec: CHECK `ck_tool_executions_status` có
  `dispatched` và `outcome_unknown` từ lần tạo (bước 2); nhật ký lần gửi, kiểm lần gửi chưa biết kết quả ở mọi lần giành
  claim, rào `claim_token` khi ghi `dispatched` và ba lỗi có kiểu (bước 3, 4; R6.9-R6.13, RH33-RH35); ca tiếp quản cũ
  của R6.2 tách thành R6.9 và R6.10, R6.2 giữ ca nhả bằng token cũ. Không thêm cạnh; không thêm cột `credential_version`
  (H-10, connections-and-vault là chủ).
- 2026-10-30 (agent, tạm theo ủy quyền): gate checking-plan-readiness, các quyết định nhỏ cho người dựng.
  (a) Claim chỉ khi có khóa và `side_effect_level` khác `none`, như R6.1; đường agent không dựng khóa cho `none`.
  (b) `outcome_unknown` ở R6.9 và R6.12 audit `tool.failed` với `details.outcome = "outcome_unknown"` (R6.9 thêm
  `details.reason = "unresolved_dispatch"`), không hành động mới, nên không cần mảnh nhãn trước telemetry-and-audit/03;
  dòng `dispatched` không audit riêng, dòng kết thúc của nó audit. (c) Cột `error`: `not_dispatched`, hay
  `rejected:<mã>` với mã cắt còn 64 ký tự và qua `redact_text`; `outcome_unknown` cho lỗi không rõ. (d) Người giữ cũ bị
  rào ở R6.13 nhận `ConflictError`, không dòng nào, như lời gọi trùng của R6.1. (e) Lỗi PostgreSQL khi chèn claim hay
  `dispatched` lan ra và handler không chạy; lỗi khi nhả claim chỉ log, claim tự hết ở `expires_at`. (f) Lời gọi đang
  chạy bằng mã cũ lúc deploy không có claim và không có `dispatched`, nên chết giữa chừng thì lời gọi sau chạy lại như
  hôm nay; chấp nhận vì khóa gắn `run_id` và bảng claim mới tạo. Nếu sai thì: (a) claim mọi khóa; (b) thêm hành động
  `tool.outcome_unknown` cùng mảnh nhãn; (c) thêm cột mã; (d) trả `outcome_unknown`; (e) không đổi; (f) dừng worker khi
  deploy.
- 2026-10-30 (agent): gate checking-plan-readiness MEDIUM để người dựng xem: bảng claim có `workspace_id` nhưng policy
  chỉ theo tenant như `platform.tool_executions`, vì khóa chính không có `workspace_id` (ADR-0108 (Accepted) quyết 5);
  `expires_at` không cộng thời gian thử lại của egress vì `asyncio.wait_for` bao cả handler.
- 2026-10-30 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): làm xong (`21a23f7`, `18b2434`, `aa53159`). Khác chữ của bước, (agent, tạm):
  (1) executor không thử lại lời gọi `external` hay `critical` nào sau dòng `dispatched`, kể cả khi lỗi là tạm thời, vì
  mỗi lần thử là một lần gửi; `max_retries` của công cụ đó chỉ còn vào `expires_at`. Nếu sai thì: thử lại riêng
  `NotDispatchedError`, mỗi lần một dòng `dispatched` mới. (2) Thêm index `ix_tool_executions_dispatched`
  `(tenant_id, tool_name, idempotency_key) WHERE status = 'dispatched'`, vì mọi lời gọi có claim hỏi lần gửi chưa biết
  kết quả và không có nó thì câu hỏi quét mọi dòng của tenant. (3) Lane dọn claim ở module riêng
  `adapters/tool_claim_retention.py`, thêm vào danh sách miễn trừ của `test_drain_setting_scan.py` kèm lý do, vì
  `reviewing-feature-security` thấy `app.worker_drain` nằm cạnh adapter claim mà API nhập và phép quét đã đỏ. (4)
  `conftest.py` của integration runtime tạo tenant A, B và workspace của chúng, vì khóa ngoại của claim từ chối tenant
  không có. (5) Đường agent nhận `OutcomeUnknownError` qua `tool_unavailable` có sẵn, không thêm câu copy.
- 2026-10-30 (agent): bước 2: không DB local nào có dòng `platform.tool_executions` (`SELECT status, count(*)` rỗng ở
  `dw`, `dw_test_runtime`, `dw_test_api`, `dw_latency`, `dw_lat_head`); `ADD CONSTRAINT ck_tool_executions_status` tự
  từ chối mọi giá trị khác lúc nâng cấp. R6.6 đo trên `deepagents` 0.7.15: `build_agent` gắn đúng toolset đã lọc scope,
  không `write_todos`.
- 2026-10-30 (agent): mutation check `mutations/01.yaml` 18/18 đỏ, đối chứng xanh; RH17 (R6.6) hai chỗ sửa cùng lúc
  tại chỗ bằng tay (bỏ lọc toolset và thêm một công cụ lạ) → test hợp đồng đỏ cả hai ca, khôi phục từ bản sao lưu →
  xanh. Đối chứng đỏ ở lần chạy đầu là `test_worker.py` chạy trên bản sao gói của `mutate.py`: nó tìm cấu hình theo
  đường dẫn của gói; mutation của lane thu hẹp về `test_only_the_platform_lanes_are_wired`.
- 2026-10-30 (agent): độ trễ `ToolExecutor.execute`, công cụ `external`, PostgreSQL compose, ấm, 300 lần mỗi ca, so
  với `9d9fb54`: khóa mới P50/P95/P99 21,9/28,4/38,1 → 50,3/61,2/71,2 ms; phát lại 14,1/18,6/24,4 → 29,2/37,7/46,1 ms.
  Trong ngân sách (P95 ≤ 300 ms, P99 ≤ 1 s) nhưng P95 gấp khoảng hai lần: một lời gọi có khóa nay chạy bảy giao dịch
  ngắn thay vì ba (claim, tìm lần thành công, kiểm lần gửi chưa biết kết quả, dòng `dispatched` commit riêng, dòng kết
  thúc, audit, nhả claim), mỗi giao dịch khoảng 7 ms ở máy này; bốn giao dịch thêm là ADR-0108 (Accepted) quyết 5 cùng R6.1, R6.9, R6.11 đòi, dòng `dispatched` phải commit riêng. Nếu cần nhanh hơn: gộp kiểm lần gửi chưa biết kết quả vào
  giao dịch claim (bớt một giao dịch).
- 2026-10-30 (agent): cổng nhanh xanh: ruff, format, mypy (464 tệp), `make test-unit` (1594), `make test-contract` (24),
  `make test-architecture` (7 hợp đồng); integration của `dw_agent_runtime`, `dw_platform`, `apps/worker`, `apps/api`
  xanh. `make test-integration` đầy đủ và `/code-review` chờ lúc đóng đợt (`wave-close.md`). Ticket resolved.
