# 04 — Người được dùng tối thiểu: dw.audience/v1 chỉ điều kiện workspace

Status: resolved (2026-11-03, main)
Blocked by: 02
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, OP12, OP13

## Mục tiêu

Lát W1 của người được dùng (R8; ADR-0102 (Accepted) quyết định 7; DO-40): tài liệu `dw.audience/v1` chỉ có điều kiện
`workspace_subtree`, một bộ kiểm trả 422 cho tài liệu rỗng hay sai, và hàm `platform.audience_matches` trả khớp theo từng
lần gọi, đọc `platform.tenant_members` và `platform.memberships` dưới RLS, không vật chất hóa. Người được dùng chỉ quyết
ai thấy và mở được agent, không bao giờ nới tầm dữ liệu. agent-builder/04 chờ ticket này và chỉ gọi bộ kiểm cùng hàm
(agent-builder:R1.5, agent-builder:R5.1, agent-builder:R5.2); điều kiện thuộc tính, nhóm và màn ngược đến ở W2 mà không
đổi dạng tài liệu.

## Việc cần làm

1. Mô hình thuần `AudienceDocument` trong `packages/python/dw_platform/src/dw_platform/domain/audience.py` (Pydantic,
   `extra="forbid"`), dạng đúng một kiểu:
   `{"schema": "dw.audience/v1", "any_of": [{"all_of": [{"workspace_subtree": "<uuid>"}, ...]}, ...]}`. Tài liệu khớp khi
   **một** nhóm của `any_of` khớp, và một nhóm khớp khi **mọi** điều kiện trong `all_of` của nó khớp (ADR-0102 (Accepted)
   quyết định 7: `any_of` của các danh sách `all_of`); ở W1 chỉ nhận loại điều kiện `{"workspace_subtree": "<uuid>"}`;
   tối đa 20 điều kiện đếm trên cả tài liệu; xuất JSON Schema cho bên dùng.
2. Bộ kiểm `AudienceValidator.validate(context, document, *, at="")` ở tầng application của `dw_platform`
   (`application/audience.py`) nhận giá trị JSON thô, trả `AudienceDocument`, và từ chối bằng
   `AudienceInvalidError(DomainError)` (khai ở `domain/audience.py`; 422 `validation_failed`) mang `details.reason_code` và `problems`, mỗi vấn đề một
   `pointer` RFC 6901 (`at` cộng đường trong tài liệu, ví dụ `/any_of/0/all_of/1`), một `code` và một câu cố định:
   - không có điều kiện nào trên cả tài liệu (`any_of` rỗng, hay mọi `all_of` rỗng) → `reason_code = "audience_empty"`;
   - mọi lỗi khác → `reason_code = "audience_invalid"`, với `code` của từng vấn đề: `audience_malformed` (sai dạng, khóa
     lạ, `schema` khác, giá trị không phải uuid; lỗi Pydantic đổi sang vấn đề có pointer), `audience_condition_unsupported`
     (điều kiện là đối tượng một khóa mà khóa khác `workspace_subtree`; xét trước Pydantic, để `extra="forbid"` không
     biến nó thành `audience_malformed`), `audience_too_many_conditions` (pointer ở điều kiện thứ 21),
     `audience_group_empty` (một `all_of` rỗng trong tài liệu có điều kiện: nhóm rỗng đúng với mọi người, nên bị từ
     chối), `audience_workspace_unknown` (workspace không tồn tại hay của tenant khác, cùng `code` và cùng câu).
   Workspace được kiểm qua cổng hẹp `AudienceWorkspacesPort.known(context, ids) -> frozenset[UUID]` khai cùng tệp; adapter
   `adapters/persistence/audience_workspaces.py` đọc `platform.workspaces` trong `tenant_session` với
   `tenant_id = context.tenant_id` nêu tường minh, không chỉ dựa RLS (`workspaces_self_select` mở workspace của tenant khác
   cho người đó khi `app.principal_id` được đặt). Một handler trong `apps/api/src/dw_api/exception_handlers.py` đổi
   `problems` thành `errors[]` (`pointer`, `code`, `detail`) như handler của `QueryError`, để agent-builder/04 chỉ gọi
   `validate(..., at="/audience")` và để lỗi đi qua; không route mới.
3. Migration (id hex của `alembic revision`): hàm
   `platform.audience_matches(p_tenant_id uuid, p_user_id uuid, p_audience jsonb) RETURNS boolean`,
   `LANGUAGE sql STABLE SECURITY INVOKER`, `SET search_path = pg_catalog, pg_temp`: trả `true` khi và chỉ khi người đó có
   dòng `platform.tenant_members` `tenant_id = p_tenant_id`, `status = 'active'`, **và** có một nhóm trong `any_of` mà
   `all_of` không rỗng và mọi điều kiện của nó là `workspace_subtree` có membership
   `(tenant_id = p_tenant_id, workspace_id = <giá trị>, user_id = p_user_id)` (cây W1 phẳng nên cây con của một workspace
   là chính nó; W2 đổi sang `platform.workspace_subtree` khi cây đến). Đóng khi lỗi, không ném lỗi: `schema` khác
   `dw.audience/v1`, `any_of` hay `all_of` không phải mảng, `all_of` rỗng, loại điều kiện khác hay giá trị không phải
   uuid (kiểm bằng biểu thức chính quy trước khi ép kiểu) làm nhóm đó `false`, và tài liệu không có nhóm khớp trả `false`;
   một tài liệu đã lưu mà sai chỉ ẩn agent, không làm hỏng danh sách. Cả hai bảng lọc `tenant_id = p_tenant_id` tường minh,
   và hàm trả `false` khi `p_tenant_id IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid` (kể cả
   khi `app.tenant_id` không đặt), vì
   `tenant_members_self_select` và `memberships_self_select` cho một kết nối có `app.principal_id` thấy dòng của chính
   người đó ở tenant khác.
   `REVOKE EXECUTE ... FROM PUBLIC`, `GRANT EXECUTE` cho `dw_app`. Không bảng và không cache kết quả.
4. Test: unit cho mô hình, bộ kiểm (với cổng giả trả tập workspace) và handler `errors[]`; integration cho adapter cổng
   workspace và cho hàm dưới `dw_app` với `app.tenant_id` đặt theo giao dịch; khẳng định `EXECUTE` trong
   `test_privileges.py`.

## Tiêu chí chấp nhận

- [x] R8.1 (OP12): `{"schema": "dw.audience/v1", "any_of": []}` và `{"schema": "dw.audience/v1", "any_of": [{"all_of": []}]}` → `AudienceInvalidError` với `details.reason_code = "audience_empty"`, và cổng workspace không được gọi; gỡ kiểm rỗng → test đỏ.
- [x] R8.2 (OP12): điều kiện `{"team": "<uuid>"}` ở `/any_of/0/all_of/0` → `reason_code = "audience_invalid"`, `problems[0]` là `audience_condition_unsupported` tại `/any_of/0/all_of/0`; 21 điều kiện → `audience_too_many_conditions` tại `/any_of/0/all_of/20`; một `all_of` rỗng cạnh một nhóm có điều kiện → `audience_group_empty` tại `/any_of/1/all_of`; workspace của tenant B và workspace không tồn tại → cùng `reason_code`, `code` và câu (integration với adapter thật); handler đổi lỗi thành 422 có `errors[0].pointer` bằng `at` cộng pointer; gỡ kiểm nhóm rỗng hay kiểm tenant → test đỏ.
- [x] R8.3: (`[[W1, W2], [W3]]` viết tắt `any_of` gồm một nhóm `all_of` W1 và W2 và một nhóm `all_of` W3) người `active` có membership ở W1 khớp tài liệu `[[W1]]`, khớp `[[W2], [W1]]`, không khớp `[[W2]]`, và không khớp `[[W1, W2]]` (một nhóm đòi cả hai); người có membership ở cả W1 và W2 khớp `[[W1, W2]]`; đổi phép "mọi điều kiện của nhóm" thành "một điều kiện bất kỳ" → test đỏ.
- [x] R8.4 (OP13): người `suspended` có membership ở W1 → `false`; với `app.tenant_id` của tenant A: `p_tenant_id` = A và người chỉ thuộc tenant B → `false`, `p_tenant_id` = B và người của B có membership ở workspace được nêu → `false`, kể cả khi giao dịch đặt `app.principal_id` là người đó; tài liệu `{"any_of": [{"all_of": []}]}`, loại điều kiện `team` và giá trị không phải uuid → `false`, không lỗi; gỡ điều kiện `status = 'active'` khỏi hàm, gỡ phép so `p_tenant_id` với `app.tenant_id`, hay cho nhóm rỗng là `true` → test đỏ.
- [x] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:103-106`; spec: R8.4.
- ADR-0102 (Accepted) quyết định 7 và phần Consequences về phân đợt; spec: R8, OP12, OP13; agent-builder:R1.5,
  agent-builder:R5.1, agent-builder:R5.2.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate CRITICAL C1 ([Mâu thuẫn] với ADR-0102 (Accepted) quyết định 7):
  bước 3 cũ cho `true` khi người đó có membership ở workspace mà **một** điều kiện nêu, bỏ phép "và" của `all_of`, nên
  `[[W1, W2]]` khớp người chỉ ở W1, và ở W2 `[[workspace A, team T]]` khớp người của A ngoài T; dạng phần tử của `any_of`
  và nhóm `all_of` rỗng (đúng với mọi người) không được nói. Sửa: bước 1 nêu dạng
  `{"schema", "any_of": [{"all_of": [...]}]}` và phép khớp; bước 3 khớp theo nhóm, nhóm rỗng, tài liệu sai dạng và giá trị
  không phải uuid là `false` không lỗi, hai bảng lọc `p_tenant_id` tường minh, `false` khi `p_tenant_id` khác
  `app.tenant_id` (`tenant_members_self_select`, `memberships_self_select` mở dòng của chính người đó ở tenant khác khi
  `app.principal_id` được đặt); tiêu chí R8.1-R8.4 thêm ca nhóm và phép đột biến; spec R8.2-R8.4, OP12, OP13 sửa theo.
  Nếu sai thì: ADR-0102 (Accepted) quyết định 7 được sửa trước thành danh sách phẳng "một điều kiện bất kỳ", rồi bước 3 về chữ cũ.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH H1 ([Thiếu], tiêu chí không thử được): `errors[0].pointer` của
  R8.2 không có đường nào: `handle_dw_error` chỉ gửi `details` (`apps/api/src/dw_api/exception_handlers.py:136-141`), chỉ
  `QueryError`, `RequestValidationError` và `IdempotencyKeyRequiredError` điền `errors[]`; ticket không có route; R8.2
  không có `reason_code` trong khi agent-builder:R1.5 trả "`reason_code` của bộ kiểm"; bộ kiểm workspace không có cổng, và
  "kết nối không đọc được" phụ thuộc kết nối đặt GUC nào (`workspaces_self_select`). Sửa: bước 2 nêu
  `AudienceInvalidError`, `reason_code` `audience_empty`/`audience_invalid`, năm `code` của vấn đề, pointer RFC 6901 cộng
  tiền tố `at`, cổng `AudienceWorkspacesPort` và adapter lọc tenant tường minh, một handler `errors[]`; tiêu chí R8.1,
  R8.2 kiểm trên lỗi và trên handler. Nếu sai thì: agent-builder/04 đổi vấn đề thành `errors[]` ở route của nó và handler
  rút khỏi ticket này.
- 2026-11-02 (agent): ghi chú MEDIUM của gate cho người dựng, chưa sửa: (M1) Pydantic v2 cảnh báo trường tên `schema`
  ("shadows an attribute in parent BaseModel", đo 2/11/2026; thành lỗi dưới `-W error`): dùng `schema_` với
  `Field(alias="schema")`, `populate_by_name`, xuất theo alias. (M2) neo đã trôi: `membership_lookup.py:103-106` nay là
  phép join `status == "active"` ở `:97-104` và phép kiểm đóng khi lỗi ở `:114-118` của `_access_in`. (M3) nửa "không lưu
  gì" của R8.1, R8.2 không đỏ được ở ticket này (không người ghi); nó là của agent-builder (AB10, agent-builder:R1.5).
  (M4) tài khoản dịch vụ (`users.kind = 'service'`, thành viên công ty `active` từ ticket 02, membership ở workspace sở
  hữu, `be93e0c26a4c`) khớp người được dùng như người; ADR-0102 (Accepted) loại nó khỏi nhóm và tuyến quản lý nhưng im về người được
  dùng; W1 vô hại (không đăng nhập được, R6.2; chat chạy dưới người gọi, ADR-0103 (Accepted) quyết 4); quyết khi lượt
  agent-tool chạy dưới tài khoản dịch vụ ở W2. (M5) workspace có `archived_at` vẫn được nhận; lưu trữ có hiệu lực là W2
  (Ngoài phạm vi). (M6) hàm SQL có mệnh đề `SET` không được planner nội tuyến, nên danh sách của agent-builder/04 gọi nó
  từng dòng: đo P50/P95/P99 cùng route đó ở cuối wave (ticket này không đổi đường request nào). (M7) bảng cặp (03, 04),
  không đường phụ thuộc: không chung bảng, route, tệp migration, config hay prompt; cả hai thêm một revision từ head hiện
  tại và sửa `test_privileges.py`, nên ticket xong sau trỏ lại `down_revision`; cảnh báo đụng độ của `check_plans.py` (`platform.tenant_members`, `platform.workspaces`) là đọc ở ticket này, không ghi, nên không phải đụng độ. (M8) MEDIUM 4 của gate ticket 02 (Business
  Owner, Validator của DW không `active`: `platform.guard_accountable_owner()` của `be93e0c26a4c` đọc `memberships`
  không xét `tenant_members.status`, `SqlDwMembershipCheck._standing` ở `digital_workers_repo.py:448-467` cũng vậy)
  không thuộc ticket này: người được dùng quyết ai thấy và mở agent, còn người chịu trách nhiệm là ADR-0103 (Accepted) quyết 3;
  ticket 02 giao nó cho ticket 03 nhưng ticket 03 không mang, và dòng Ngoài phạm vi "Người chịu trách nhiệm bắt buộc…"
  (W2) còn ghi "Tài khoản dịch vụ W1 chưa có `owner_user_id`", đã cũ từ `be93e0c26a4c`: việc của gate ticket 03 hay một
  ticket tiếp của digital-worker. (M9) dòng Ngoài phạm vi "Cây workspace" (W2) không nêu việc đổi `audience_matches` sang
  `platform.workspace_subtree`; bước 3 nêu, W2 phải mang theo. (M10) agent-builder ghi lỗi trường là
  `{path, code, message}` (agent-builder spec, API) trong khi lỗi ở đây là `errors[]` `pointer`: việc của
  checking-plan-consistency.
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc chỗ sửa C1, H1: không CRITICAL mới; C1, H1 đóng. Ba làm rõ thêm
  trong lượt: `AudienceInvalidError` khai ở `domain/audience.py`; điều kiện một khóa lạ được xét trước Pydantic để ra
  `audience_condition_unsupported`, không `audience_malformed`; phép so tenant dùng `IS DISTINCT FROM` để `app.tenant_id`
  không đặt cũng ra `false`. Handler riêng thắng `handle_dw_error` vì Starlette chọn handler theo MRO của lớp lỗi, như
  `QueryError` đã dựa vào.
- 2026-11-02 (agent): ticket này thêm một revision Alembic (một hàm, không bảng) và không thêm route; đường request tới
  DB: cổng workspace đọc `platform.workspaces` một câu mỗi lần kiểm, hàm đọc `platform.tenant_members` theo khóa chính và
  `platform.memberships` theo `uq_memberships_scope_user`; chưa route nào gọi chúng tới agent-builder/04.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): không nối `AudienceValidator` ở composition root: ticket không có route
  và chưa ai gọi nó (failure-modes #1); agent-builder/04 nối `AudienceValidator(SqlAudienceWorkspaces(session_factory))`
  ở `wiring.py` cùng route của nó. Nếu sai thì: thêm một thuộc tính container ở `wiring.py` ngay, không đổi lớp nào.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): M1 làm khác gợi ý của gate: `schema_` với `Field(alias="schema")` nhưng
  `validate_by_alias=True, validate_by_name=False` thay cho `populate_by_name`, vì `populate_by_name` nhận cả
  `{"schema_": ...}`, tài liệu mà `platform.audience_matches` luôn đọc là `false` (đo 3/11/2026, Pydantic 2.13.5); có test.
  Nếu sai thì: trả lại `populate_by_name=True` và bỏ ca `schema_ by field name`.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): bộ kiểm nhận uuid ở dạng Pydantic chấp nhận (chữ hoa, không gạch nối)
  và trả `AudienceDocument` mà `as_json()` là dạng chuẩn có gạch nối, dạng hàm SQL đọc; bên lưu (agent-builder/04) lưu
  `as_json()`, không lưu giá trị thô. Tối đa 20 vấn đề mỗi lần từ chối (`MAX_PROBLEMS`), để tài liệu nghìn điều kiện sai
  không thành câu trả lời nghìn dòng. Nếu sai thì: từ chối dạng không chuẩn bằng `audience_malformed`.
- 2026-11-03 (agent): resolved. Làm: `domain/audience.py` (mô hình, `parse_audience`, `AudienceInvalidError`),
  `application/audience.py` (`AudienceValidator`, `AudienceWorkspacesPort`), adapter `audience_workspaces.py` lọc
  `tenant_id` tường minh, handler `AudienceInvalidError` → 422 `errors[]` trong `exception_handlers.py`, migration
  `555dad01f629` (`platform.audience_matches`, EXECUTE chỉ `dw_app`). Khác ticket: thêm một ca R8.4 (người `suspended` ở A
  nhưng `active` ở B, `app.principal_id` là người đó → `false`), vì không có nó thì gỡ `tm.tenant_id = p_tenant_id` khỏi
  hàm vẫn xanh. Test mới: unit `dw_platform/tests/unit/test_audience.py` 20, `apps/api/tests/unit/test_audience_errors.py`
  4; integration `test_audience.py` 25, `test_privileges.py` +1. Cổng nhanh: ruff, format, mypy (592 tệp), lint-imports
  xanh; integration `test_audience`, `test_privileges`, `test_rls_coverage`, `test_offboarding_coverage` 110 xanh
  (`_lane1`); unit dw_platform + api 633 xanh, 2 đỏ không do ticket này (`test_digital_workers_endpoint.py`, hai test
  trợ lý wf-ai đỏ vì thay đổi chưa commit của lane 2 ở `wflite/assistant.py`). Đột biến: `mutations/04.yaml` 15 phép,
  viết chưa chạy (cuối wave); hai phép đã thử tay và đỏ đúng (gỡ phép so `app.tenant_id`, gỡ `tm.tenant_id`).
  reviewing-feature-security, đọc: tenant (adapter và hàm lọc tenant tường minh, hàm so `app.tenant_id`, test cho
  self-select của `app.principal_id`), người không có quyền (EXECUTE thu khỏi PUBLIC, chỉ `dw_app`; SECURITY INVOKER nên
  RLS vẫn áp), lỗi không lộ giá trị (pointer, code, câu cố định). Chưa làm (đúng wave-close): mutate.py, cả
  `make test-integration`, P50/P95/P99 (M6, cùng route agent-builder/04).
