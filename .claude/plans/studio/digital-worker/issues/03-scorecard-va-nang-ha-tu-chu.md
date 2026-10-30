# 03 — Scorecard tính từ dữ liệu, nâng hạ mức đã kiếm

Status: resolved
Blocked by: 02, .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, DWK17, DWK18, DWK19, DWK20

## Mục tiêu

Business Owner đọc scorecard của DW tính từ hàng đợi, quyết định duyệt và chi phí của lượt chạy, và
đổi mức đã kiếm: hạ ngay, nâng khi người thứ hai duyệt (R7, R8, ADR-0128 (Proposed) quyết 5, 9).

## Việc cần làm

1. Migration mới: `platform.worker_runs.model_cost_usd numeric(12,6) NOT NULL DEFAULT 0` CHECK `>= 0`.
2. `dw_agent_runtime/adapters/run_cost_recorder.py`: một `UsageRecorderPort` cộng `cost_usd` của lời
   gọi vào `model_cost_usd` của lượt chạy bằng `UPDATE ... SET model_cost_usd = model_cost_usd + :c`;
   đăng ký trong `CompositeUsageRecorder` ở composition root của worker và API.
3. `dw_platform/application/scorecard.py` và repository: `GET /v1/digital-workers/{id}/scorecard?days=`
   (1-90, mặc định 30, cửa sổ cuộn `now() - n × 24 giờ`), một truy vấn tổng hợp mỗi nguồn theo R7.1: việc
   có `dw_id` là DW theo `created_at`, approval `dw.decision` có `payload->>'dw_id'` là DW theo `decided_at`
   (duyệt nguyên văn, duyệt có sửa theo `edited`, từ chối), tổng `model_cost_usd` của lượt chạy có
   `run_as_principal_id` là principal của DW theo `created_at`.
4. `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy` `{level}`: hạ (BO hay TO) ghi ngay
   với audit `dw.autonomy.lowered`; nâng (chỉ BO, không quá trần, không khi đã có approval nâng đang chờ
   cho loại đó) mở approval `dw.autonomy.raise` không lượt chạy với `from_level`, `to_level`, trả 202 với
   id approval; thêm `dw.autonomy.` vào `strict_approval_prefixes` và một `DecisionAdmission` chỉ nhận
   Validator hay Technical Owner hiện tại của DW (R8.3).
5. Handler outbox `dw.autonomy.raise.decided` ở worker: duyệt, `earned_level` hiện tại bằng `from_level` và
   DW chưa `retired` thì ghi `to_level` (`UPDATE ... WHERE earned_level = :from_level`) và audit
   `dw.autonomy.raised` đứng tên người duyệt với `details.lane`; không thì audit `dw.autonomy.raise_stale`
   và không đổi mức (R8.6).
6. Đo P50/P95/P99 của route scorecard và danh sách việc (ticket đổi cách truy cập DB, `latency.md`).
7. Test âm DWK17-DWK20.
8. Theo gate lượt 2: index unique một phần trên `platform.approval_requests ((payload->>'dw_id'), (payload->>'decision_class'))`
   `WHERE approval_type = 'dw.autonomy.raise' AND status = 'pending'` (R8.4); bắt vi phạm unique thành 409 `raise_pending`.

## Tiêu chí chấp nhận

- [x] R7.1: với 3 việc `done`, 1 `handed_off`, 2 approval duyệt (1 có sửa), 1 từ chối và chi phí 0,012 + 0,003, scorecard trả đúng số; việc của DW khác không tính.
- [x] R7.2: `days=0` và `days=91` → 422 `days_out_of_range`; `days=1` và `days=90` → 200.
- [x] R7.3: hai lời gọi model của một lượt chạy cộng đúng vào `model_cost_usd`; lời gọi của lượt khác không chạm.
- [x] R8.1: BO hạ A3 xuống A2 → mức mới ngay, `effective_level` trả A2 ở lần hỏi kế tiếp, có audit.
- [x] R8.2 (DWK17): BO nâng A2 lên A3 → 202, mức vẫn A2; người thứ hai từ chối → vẫn A2; duyệt → A3.
- [x] R8.6 (DWK17): từ chối không đổi mức; duyệt ghi mức mới và audit; hạ khẩn xuống A0 rồi duyệt đề nghị A2→A3 → mức giữ A0, audit `dw.autonomy.raise_stale`.
- [x] R8.3 (DWK18): BO tự duyệt đề nghị của mình, người ngoài DW giữ `approvals.decide` duyệt, hay duyệt không lý do → 409, mức không đổi.
- [x] R8.4 (DWK19): đề nghị A4 với trần A3 → 422 `above_ceiling`; đề nghị thứ hai khi một đang chờ → 409 `raise_pending`; không approval mới.
- [x] R8.5 (DWK20): Validator hạ → 403 `not_dw_owner`; TO nâng → 403.
- [x] R8.4 (DWK19): hai đề nghị nâng cùng lúc cho một loại → đúng một approval, lời gọi kia 409 `raise_pending`.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/usage_recorders.py:1-40`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:304-305`; spec: R7, R8, DWK17-DWK20.

## Comments

- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): đang làm. Xong bước 1-2 (`d340030`: cột `model_cost_usd`, `RunCostRecorder` trong
  `build_model_stack`, nên cả API và worker ghi). Còn: bước 3 scorecard, 4 route nâng hạ, 5 handler outbox, 8 index
  unique một phần, 6 độ trễ, 7 test âm; mutation, rà bảo mật.
- 2026-10-30 (agent): bước 3-5, 8 xong (`a6963ad`). Khác với ticket hay quyết khi spec im lặng (agent, tạm):
  - Scorecard: tỷ lệ là `null` khi cửa sổ không có việc nào (không phải 0); `model_cost_usd` trả chuỗi thập phân
    đúng sáu chữ số của cột. Cửa sổ tính bằng đồng hồ của ứng dụng (`clock.now() - days × 24 giờ`). Nếu sai thì: đổi
    `Scorecard.*_rate` và `ScorecardView`.
  - Route nâng hạ: mức bằng mức hiện tại là 422 `level_unchanged`; mức lạ 422 `level_invalid`; loại không có ở DW 404
    `decision_class_not_found`; hai lần hạ cùng lúc, lần thua là 409 `level_changed`. Mở đề nghị nâng ghi thêm audit
    `dw.autonomy.raise_requested` cùng giao dịch với approval.
  - Từ chối đề nghị nâng: handler không ghi `raise_stale` (dòng `approval.decided` của quyết định là vết); `raise_stale`
    chỉ khi đã duyệt mà mức đã đổi hay DW đã `retired`. Một sự kiện đã áp dụng giao lại thấy mức đã bằng `to_level` và
    không làm gì; một quyết định `raise_stale` giao lại (tiến trình chết giữa commit và đánh dấu) có thể ghi thêm một dòng
    `raise_stale`, mức không đổi.
  - `DwDecisionAdmission` nhận `deciders`: một lớp cho cả `dw.decision` (Validator hay BO) và `dw.autonomy.raise`
    (Validator hay TO), không hai bản. Worker cũng đăng ký luật đó và tiền tố strict cho đường quyết qua chat.
  - Phía worker là `RaiseSettler` riêng (không cần đọc DW theo người gọi), handler `dw.autonomy.raise.decided`.
  - Giới hạn biết trước: một đề nghị nâng đang chờ chặn đề nghị nâng khác của loại đó tới khi Validator hay TO quyết;
    BO không rút được (luật strict cấm người đề nghị quyết, kể cả từ chối). Hạ mức không bị chặn.
- 2026-10-30 (agent): resolved (`d340030` cột chi phí, `a6963ad` scorecard và nâng hạ, `8e02ff1` mutation).
  - `reviewing-feature-security`: tenant (mọi câu dưới `tenant_session` theo tenant và workspace của người gọi hay của
    sự kiện; approval lọc workspace rõ vì RLS chỉ theo tenant; tenant khác đọc scorecard 404, ghi chi phí cho lượt của
    tenant khác không cộng gì); phân quyền (chủ DW kiểm ở service nơi ghi; Validator hạ 403, TO nâng 403, người ngoài DW
    giữ `approvals.decide` quyết 409); tự chủ (nâng không đổi gì tới khi người thứ hai duyệt; settle đóng khi thiếu lớp
    hay DW; CHECK `earned_level <= ceiling` vẫn giữ ở DB); đầu vào (mức kiểm theo `AUTONOMY_LEVELS`, khóa loại chỉ tìm
    trong lớp của DW); audit (`lowered`, `raise_requested` cùng giao dịch ghi; `raised`, `raise_stale` cùng giao dịch
    settle, đứng tên người duyệt với `details.lane`); vòng đời (giới hạn ở dòng trên).
  - Mutation `mutations/03.yaml`: 18/18 đỏ, đối chứng xanh. Trước đó bỏ điều kiện `earned_level = from_level` lặp ở
    câu UPDATE của settle (dòng lớp đã giữ `FOR UPDATE` từ lúc đọc; một chỗ giữ luật, failure-modes #3).
  - Độ trễ (200 lời gọi ấm, ứng dụng ASGI thật, PostgreSQL thật; ba DW, 3.000 việc trong 120 ngày, 1.500 approval
    `dw.decision`, 3.000 lượt chạy): `GET scorecard?days=30` P50/P95/P99 49,5/60,7/70,3 ms, `days=90`
    49,9/61,0/69,2 ms, `POST .../autonomy` (hạ) 49,4/64,9/69,2 ms (route mới, không số gốc); `GET /work-items` cha
    `e50bbb6` 33,6/44,2/50,9 ms, sau 33,9/42,3/48,2 ms. Trong ngân sách, không index mới cho scorecard.
  - Cổng: ruff, format, mypy, `make test-unit`, `test-contract` (snapshot OpenAPI và client sinh lại),
    `test-architecture`; integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker`: 820 passed, 3 skipped (uv run pytest -m unit -n auto
bringing up nodes...
bringing up nodes...

........................................................................ [  4%]
........................................................................ [  8%]
........................................................................ [ 12%]
........................................................................ [ 16%]
........................................................................ [ 20%]
........................................................................ [ 24%]
........................................................................ [ 28%]
........................................................................ [ 32%]
........................................................................ [ 36%]
........................................................................ [ 40%]
........................................................................ [ 44%]
........................................................................ [ 48%]
........................................................................ [ 52%]
........................................................................ [ 56%]
........................................................................ [ 60%]
........................................................................ [ 64%]
........................................................................ [ 68%]
........................................................................ [ 72%]
........................................................................ [ 76%]
........................................................................ [ 80%]
........................................................................ [ 84%]
...........................................s....s.ss....s............... [ 88%]
.....ss.......................s......................................... [ 93%]
........................................................................ [ 97%]
....................................................                     [100%]
============================== warnings summary ===============================
apps\api\src\dw_api\bootstrap\wiring.py:179: 16 warnings
apps/api/tests/unit/test_api_packs_fail_fast.py: 1 warning
apps/api/tests/unit/test_dev_endpoints.py: 6 warnings
apps/api/tests/unit/test_idempotency_declarations.py: 5 warnings
apps/api/tests/unit/test_list_and_write_conventions.py: 2 warnings
apps/api/tests/unit/test_zalo_endpoint.py: 3 warnings
apps/api/tests/unit/test_memory_review_wiring.py: 1 warning
apps/api/tests/unit/test_metrics_endpoint.py: 1 warning
  C:\code\codebase\apps\api\src\dw_api\bootstrap\wiring.py:179: UserWarning: Api key is used with an insecure connection.
    AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

apps\api\src\dw_api\bootstrap\knowledge.py:75: 16 warnings
apps/api/tests/unit/test_api_packs_fail_fast.py: 1 warning
apps/api/tests/unit/test_dev_endpoints.py: 6 warnings
apps/api/tests/unit/test_idempotency_declarations.py: 5 warnings
apps/api/tests/unit/test_list_and_write_conventions.py: 2 warnings
apps/api/tests/unit/test_zalo_endpoint.py: 3 warnings
apps/api/tests/unit/test_memory_review_wiring.py: 1 warning
  C:\code\codebase\apps\api\src\dw_api\bootstrap\knowledge.py:75: UserWarning: Api key is used with an insecure connection.
    client=AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),

apps\api\src\dw_api\bootstrap\runtime.py:124: 16 warnings
apps/api/tests/unit/test_api_packs_fail_fast.py: 1 warning
apps/api/tests/unit/test_dev_endpoints.py: 6 warnings
apps/api/tests/unit/test_idempotency_declarations.py: 5 warnings
apps/api/tests/unit/test_list_and_write_conventions.py: 2 warnings
apps/api/tests/unit/test_zalo_endpoint.py: 3 warnings
apps/api/tests/unit/test_memory_review_wiring.py: 1 warning
  C:\code\codebase\apps\api\src\dw_api\bootstrap\runtime.py:124: UserWarning: Api key is used with an insecure connection.
    client=AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),

.venv\Lib\site-packages\starlette\testclient.py:53: 16 warnings
  C:\code\codebase\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_a_business_refusal_reaches_the_model_instead_of_ending_the_run
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_a_business_refusal_reaches_the_model_instead_of_ending_the_run
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_a_business_refusal_reaches_the_model_instead_of_ending_the_run
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_the_error_details_are_never_handed_to_the_model
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_an_upstream_failure_reaches_the_model_instead_of_ending_the_run
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_an_upstream_failure_reaches_the_model_instead_of_ending_the_run
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_a_crashing_tool_hands_over_its_type_and_not_its_message
packages/python/dw_agent_runtime/tests/unit/test_langchain_tools.py::test_a_crashing_tool_hands_over_its_type_and_not_its_message
  C:\Users\phung\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py:88: LangChainDeprecationWarning: Calling .text() as a method is deprecated. Use .text as a property instead (e.g., message.text).
    self._context.run(self._callback, *self._args)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1772 passed, 8 skipped, 127 warnings in 100.17s (0:01:40) 1772, contract 24, architecture 32).
