# 04 — Ngữ cảnh actor ở mọi cửa và biên dữ liệu của agent và workflow

Status: resolved
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, R6.12, R6.13, R6.14, R6.15, RA18, RA19, RA20, RA21, RA27

## Mục tiêu

Agent và quy trình đọc, ghi bản ghi bằng tầm sống của người kích hoạt hay tài khoản dịch vụ chạy dưới danh nghĩa,
giao với giới hạn dữ liệu cố định khi phát hành, nên một yêu cầu bị chèn prompt đòi lead của người khác thất bại ở
RLS, không ở prompt (spec R6.3 tới R6.9; ADR-0103 (Accepted) mục 4 và 5; ADR-0105 (Accepted) mục 6). Lane
offboarding xuất rồi xóa giới hạn dữ liệu của một công ty rời nền tảng như mọi dữ liệu Studio của nó (spec R6.10). Một
lượt `simulate` có gốc chưa phát hành (bản Nháp, hay Bản ứng viên mà một lần thử của Lượt kiểm định chạy) đọc dưới giới
hạn tạm mà `RunRequestService` ghi qua `ActorBoundaryPort`, giao với tầm của chủ thể của lượt (người thử, hay người gửi
Bản ứng viên), và cơ sở dữ liệu không để lượt nào khác `simulate` dùng nó (spec R6.11 tới R6.15; ADR-0109 (Accepted)
quyết 6, ADR-0111 (Accepted) quyết 3).

## Việc cần làm

1. Migration trong schema `studio`, RLS ENABLE và FORCE, policy `tenant_isolation_<bảng>` theo tenant. `dw_app` chỉ
   SELECT và DELETE trên ba bảng (DELETE giới hạn đã phát hành chỉ qua được ở lượt xóa của offboarding, DELETE giới hạn
   tạm qua được mọi lúc, nhờ trigger dưới); không INSERT, không UPDATE: mọi lần ghi giới hạn đi qua hàm SECURITY
   DEFINER của bước 2, nên một giới hạn đã phát hành không thể nới thêm dòng sau giao dịch ghi nó (gate 4/11/2026 (i));
   khẳng định trong `packages/python/dw_platform/tests/integration/test_privileges.py`:
    - `studio.actor_boundaries`: `tenant_id` (FK `platform.tenants` `ON DELETE CASCADE`), `id` (PK `(tenant_id, id)`),
      `kind text NOT NULL` với `ck_actor_boundaries_kind` (`agent`, `workflow`), `source_id uuid NOT NULL`,
      `source_version text NOT NULL`, `run_id uuid NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, chỉ mục duy
      nhất `(tenant_id, kind, source_id, source_version)` `WHERE run_id IS NULL` và chỉ mục duy nhất
      `(tenant_id, run_id)` `WHERE run_id IS NOT NULL`. Ở mọi giới hạn, `source_id` là `version_id` (id của dòng
      `studio.artifact_versions`) và `source_version` là mã băm của phiên bản đó: `definition_hash` ở giới hạn đã phát
      hành và ở Bản ứng viên, mã băm tạm mà bản kê ghim ở bản Nháp (`pinned_hash`); `run_id` khác NULL đúng ở giới hạn
      tạm (gate (a)). `run_id` không có khóa ngoại (Quyết định 24/10/2026 của spec): trigger BEFORE INSERT
      `ck_actor_boundaries_provisional_run` đọc `platform.worker_runs` theo `(tenant_id, run_id)` với
      `tenant_id = NEW.tenant_id` nêu tường minh, vì nó chạy dưới hàm definer của bước 2, và từ chối với 23514 khi không
      có dòng nào hay `run_mode` của dòng khác `simulate` (spec R6.14; cột của tenant-config/03).
    - `studio.actor_boundary_objects`: `tenant_id`, `boundary_id` (FK `(tenant_id, boundary_id)` tới
      `studio.actor_boundaries` `ON DELETE CASCADE`), `object_id` (FK `(tenant_id, object_id)` tới `studio.object_defs`
      `ON DELETE RESTRICT`), `can_read`, `can_create`, `can_update`, `can_delete`, `can_assign` (`boolean NOT NULL`),
      PK `(tenant_id, boundary_id, object_id)`, index trên `(tenant_id, object_id)`.
    - `studio.actor_boundary_fields`: `tenant_id`, `boundary_id` (FK như trên), `field_id` (FK `(tenant_id, field_id)`
      tới `studio.field_defs` `ON DELETE RESTRICT`), `access text NOT NULL` với `ck_actor_boundary_fields_access`
      (`read`, `edit`), PK `(tenant_id, boundary_id, field_id)`, index trên `(tenant_id, field_id)`; field-security đọc
      bảng này.
    - Trigger BEFORE UPDATE OR DELETE trên ba bảng gọi lỗi 23514 `ck_actor_boundaries_frozen`: UPDATE luôn bị từ chối,
      kể cả ở giới hạn tạm và dưới vai sở hữu; DELETE qua khi `platform.tenants.status` của công ty của dòng là
      `offboarding`, cùng hình với `platform.guard_control_switch()` của agent-lifecycle (spec R6.8; agent-lifecycle:R7.5),
      hay khi dòng là một giới hạn tạm; ở hai bảng con, DELETE cũng qua khi dòng cha là giới hạn tạm hay không còn, tức
      cascade từ một DELETE dòng cha mà trigger của dòng cha đã cho qua, nên trigger kết thúc lượt của workflow-engine xóa
      được giới hạn tạm bằng một DELETE dòng cha (workflow-engine:R3.14; spec R6.15); trigger không đọc
      `app.workspace_scope`.
    - Lane `offboarding` xóa ba bảng bằng bước mặc định của sổ bước xóa (foundations-hardening/07,
      foundations-hardening:R11.4), không đăng ký bước riêng: `dw_app` có DELETE, trigger cho qua khi công ty ở
      `offboarding`, và thứ tự suy từ khóa ngoại `ON DELETE RESTRICT` của hai bảng con tới `studio.object_defs` và
      `studio.field_defs` trong `pg_constraint` đặt chúng trước bước của custom-objects/02 (spec R6.10;
      studio-skeleton:R4.2) (gate (h)).
    - Ba bảng không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant của
      `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý do "giới hạn dữ liệu của một phiên bản
      agent hay quy trình đã phát hành, hay giới hạn tạm của một lượt `simulate` có gốc chưa phát hành, thuộc định nghĩa
      toàn tenant" (DO-01).
2. `ActorBoundaryPort` (Protocol trong gói truy cập của `dw_studio`, cùng hai kiểu giá trị của nó, một chỗ khai) với
   hai phương thức chạy trên phiên của giao dịch người gọi, nhận làm tham số đầu: `record(session, kind, version_id,
definition_hash, objects, fields) -> boundary_id` cho phiên bản đã phát hành và `record_provisional(session, kind,
run_id, version_id, pinned_hash, objects, fields) -> boundary_id` cho giới hạn tạm. `objects` là các
   `ObjectBoundary(api_name, can_read, can_create, can_update, can_delete, can_assign)`, `fields` là các
   `FieldBoundary(object_api_name, field_api_name, access)`: đúng hình mà phép dẫn của agent-builder/05 và
   workflow-engine/03 trả, theo `api_name`, không kiểu thứ hai (gate (c)). Adapter SQL gọi một hàm SECURITY DEFINER
   `studio.record_actor_boundary(...)` thuộc `dw_migrator` (`search_path` cố định, EXECUTE thu khỏi PUBLIC và cấp cho
   `dw_app`, tenant lấy từ `app.tenant_id`, không từ tham số), ghi dòng cha và mọi dòng con trong một lời gọi, đổi
   `api_name` ra id theo `studio.object_defs`, `studio.field_defs` của tenant; một `api_name` không có → lỗi, giao dịch
   phát hành lùi; ở `record_provisional` một `api_name` chưa áp (đối tượng hay trường mới của một bản Nháp) bị bỏ khỏi
   giới hạn tạm, nên lượt thử đọc 0 bản ghi của nó thay vì bị từ chối (lượt xác nhận (o)). Nối ở composition root của
   API và worker. Móc phát hành của loại `agent` (agent-builder) và của loại
   `workflow` (workflow-engine) gọi `record`, trong giao dịch phát hành mà agent-lifecycle mở khi gọi móc của mục
   `ArtifactKindRegistry` (ADR-0109 (Accepted) quyết 1); `RunRequestService` của workflow-engine gọi
   `record_provisional` trong giao dịch nhận lượt, sau dòng `platform.worker_runs` (spec R6.11; workflow-engine:R3.13).
   Port không có phương thức xóa: trigger kết thúc lượt của workflow-engine xóa giới hạn tạm (workflow-engine:R3.14).
3. Hàm SQL `studio.boundary_chain(p_run_id uuid) RETURNS uuid[]` (`LANGUAGE sql STABLE`, SECURITY INVOKER,
   `search_path` cố định, đọc dưới RLS của tenant đang gắn), một chỗ trả lời "lượt này đọc dưới giới hạn nào"; là hàm
   SQL vì `bind_actor` ở `dw_platform` và phiên của runtime ở `dw_agent_runtime` không được import `dw_studio`
   (import-linter), nên không lớp Python nào làm việc này (lượt xác nhận (k)). Không đọc tầm hay giới hạn đóng dấu: với
   lượt và mọi lượt cha theo `platform.worker_runs.parent_run_id` (workflow-engine/02), gốc trước, giới hạn tạm theo
   `run_id` khi có, không thì giới hạn đã phát hành theo `(kind, artifact_version_id, definition_hash)` của dòng lượt
   (workflow-engine:R4.9); một mắt xích không có giới hạn → mảng rỗng; lượt không có gốc Studio (worker của pack) → mảng
   rỗng, không lỗi, nên nó đọc 0 bản ghi Studio (gate (b), lượt xác nhận (l)). Lượt con (Bước agent trong quy trình, `flow.subworkflow` của
   workflow-engine:R8.1) mang giới hạn của cả chuỗi, vì ADR-0103 (Accepted) quyết 5 đòi giao mọi giới hạn trên chuỗi
   (gate (f)).
4. Setting: một helper `bind_actor(session, kind, ...)` trong `tenant_session.py` (ticket 03 dựng nó cho `user`) là chỗ
   duy nhất đặt `app.actor_kind`, `app.boundary_id` và `app.run_mode`, mỗi cái bằng `set_config(..., true)`; với `agent`
   và `workflow` nó nhận `run_id`, đọc dòng `platform.worker_runs` của lượt dưới RLS của tenant đang gắn, gắn
   `app.run_mode` là `run_mode` của dòng đó, không bao giờ một giá trị mặc định của `RunContext`, và `app.boundary_id`
   là `studio.boundary_chain(run_id)`, gốc trước, nối bằng dấu phẩy; nó không đặt `app.user_id` (chỗ đặt là
   `bind_tenant`) mà từ chối khi `app.user_id` khác `coalesce(run_as_principal_id, requested_by)` của dòng lượt
   (ADR-0103 (Accepted)), nên phiên của lượt mở bằng `TenantScope` có người dùng là chủ thể đó; dòng lượt không có → lỗi,
   không gắn gì (gate (d), (e); lượt xác nhận (m)). `TenantScope`
   không mang trường nào của ba setting này. Test kiến trúc giữ bảng cho phép: `user` từ helper phiên Studio của ticket
   03, `agent` từ phiên công cụ của `dw_agent_runtime`, `workflow` từ module runner của workflow-engine; test quét mã đỏ
   với mọi `set_config('app.actor_kind'`, `'app.boundary_id'`, `'app.run_mode'` hay `SET [LOCAL]` của chúng ngoài
   `bind_actor`, như RA22 làm với `app.workspace_scope` (gate (g)). `_TRUSTED_SETTINGS` của `test_rls_coverage.py`
   nhận `app.run_mode` như hai setting kia.
5. `RunContext` không thêm trường giới hạn nào: giới hạn đi từ dòng lượt qua `studio.boundary_chain`, không qua ngữ
   cảnh đóng dấu hay checkpoint. Ticket này dựng `bind_actor` và một helper phiên cho công cụ đối tượng Studio (mở giao
   dịch, gắn `agent`, gọi cửa sổ tầm, ở mỗi giao dịch, kể cả lần đầu sau khi tiếp tục từ phê duyệt), thử bằng một công
   cụ fixture; nối helper vào đường gọi công cụ đối tượng thật là của agent-builder/03 và tools-and-skills/03, và công cụ
   của pack code không đổi. Một phiên không gọi `bind_actor` đọc 0 bản ghi, vì setting của giao dịch trước không còn
   (lượt xác nhận (n)).
6. `studio.acl_boundary_objects(cmd text)` (`LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định), `cmd` một
   trong `select`, `insert`, `update`, `delete`, `assign`, ứng với `can_read`, `can_create`, `can_update`, `can_delete`,
   `can_assign`: trả giao của các object có cờ đó qua mọi id của `app.boundary_id`, `'{}'` khi chuỗi rỗng, khi một id
   không trỏ tới giới hạn của tenant đang gắn, hay khi một id là giới hạn tạm mà `app.run_mode` khác `simulate` hay
   không gắn (spec R6.13). Dựng lại policy từ module mẫu của ticket 03 với `actor_ok` mới: loại `user`, hoặc loại
   `agent` hay `workflow` với `object_id` trong `studio.acl_boundary_objects(<lệnh>)`; WITH CHECK xóa mềm của `_update`
   (ticket 03 bước 4) dùng `delete`. `assign` có bên đọc là `studio.assign_record` của ticket 05 (gate (j)).
7. Lượt chạy không người kích hoạt: chủ thể là tài khoản dịch vụ của org-and-principals ticket 03, gắn theo phiên bản
   qua điểm gắn `principal` đã duyệt (DO-12 (a); chưa gắn thì workflow-triggers từ chối phát hành với `binding_unset`),
   với loại actor `workflow`; sổ tầm của nó tính như của một người, không nhánh riêng.

## Tiêu chí chấp nhận

- [x] R6.3 (RA18): phiên công cụ của một lượt chạy agent có `app.actor_kind = 'agent'`, `app.user_id` là
      `coalesce(run_as_principal_id, requested_by)` của dòng lượt và `app.boundary_id` của phiên bản; test kiến trúc: một
      module ngoài bảng cho phép gọi `bind_actor` với `agent` → đỏ; thêm `set_config('app.boundary_id', ...)` ngoài
      `bind_actor` → test quét mã đỏ.
- [x] R6.3: dòng lượt có `run_mode` `live` mà `RunContext` mang `simulate` → giao dịch gắn `live`; gắn theo
      `RunContext` → test đỏ.
- [x] R6.4 (RA19): giới hạn chỉ có `mkt_lead` với `can_read`: bản ghi của object khác → 0 dòng dù chủ thể thấy nó;
      DELETE và xóa mềm một lead khi giới hạn không có `can_delete` → 0 dòng bị ảnh hưởng hay 42501; gỡ nhánh giới hạn
      khỏi policy → test đỏ.
- [x] R6.4 (RA19): lượt chạy agent của người U, giới hạn `mkt_lead`, gọi công cụ đọc lead của người V theo id như một
      lời nhắc bị chèn yêu cầu → 0 dòng, công cụ trả không tìm thấy.
- [x] R6.4 (RA19): lượt quy trình cha có giới hạn chỉ `mkt_lead` `can_read`, lượt con có giới hạn `mkt_lead`
      và `mkt_campaign` với mọi cờ → lượt con đọc `mkt_campaign` 0 dòng và không sửa được lead; chỉ gắn giới hạn của lượt
      con → test đỏ.
- [x] R6.5 (RA19): loại `agent` không có `app.boundary_id` → 0 dòng; `app.boundary_id` của một giới hạn thuộc tenant B
      → 0 dòng; một mắt xích của chuỗi thuộc tenant B → 0 dòng.
- [x] R6.6 (RA19): lượt chạy dừng chờ phê duyệt, chủ thể mất lần gán vai trò, lượt chạy tiếp tục → câu lệnh kế tiếp
      0 dòng; đọc tầm đóng dấu thay vì gọi cửa sổ tầm → test đỏ.
- [x] R6.6: giao dịch `agent` commit trên một kết nối, giao dịch kế tiếp trên cùng kết nối gắn tenant mà
      không gọi `bind_actor` → 0 bản ghi; đặt setting bằng `set_config(..., false)` → test đỏ.
- [x] R6.7: `ActorBoundaryPort.record` ghi đúng một giới hạn cho mỗi bộ (loại, `version_id`, `definition_hash`), với
      `ObjectBoundary` theo `api_name` đổi ra đúng `object_id`; ghi lần hai cho cùng phiên bản → 23505, không có dòng thứ
      hai; một `api_name` không có → lỗi, không dòng nào.
- [x] R6.7: `dw_app` INSERT một dòng `studio.actor_boundary_objects` vào giới hạn của một phiên bản `live` →
      permission denied; cấp lại INSERT cho `dw_app` → test đỏ.
- [x] R6.8 (RA20): UPDATE `studio.actor_boundary_objects` của phiên bản đã ghi, hay của một giới hạn tạm, bằng vai sở hữu
      bảng → 23514 `ck_actor_boundaries_frozen`, bằng `dw_app` → permission denied; `dw_app` DELETE một dòng của mỗi bảng
      thuộc giới hạn đã phát hành khi công ty `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding` → xóa được;
      gỡ phép kiểm DELETE khỏi trigger → test đỏ.
- [x] R6.9 (RA21): tài khoản dịch vụ chỉ có `read` lead ở mức Của tôi, chạy với loại `workflow`: thấy lead của chính
      nó, 0 lead của người phát hành có mức Toàn công ty; gắn người phát hành làm chủ thể → test đỏ.
- [x] R6.10: công ty `offboarding` có một giới hạn dữ liệu trỏ tới một đối tượng và một trường của nó → lane
      `offboarding` xuất mỗi dòng của ba bảng một lần rồi xóa hết, cùng định nghĩa đối tượng và trường, không lỗi khóa
      ngoại; dòng của công ty khác còn nguyên; test phủ offboarding (studio-skeleton:R4.1, studio-skeleton:R4.2) xanh;
      thu DELETE của `dw_app` trên `studio.actor_boundary_objects` → test phủ offboarding đỏ (gate (h)).
- [x] R6.11 (RA27): với một dòng `platform.worker_runs` `run_mode = 'simulate'` của fixture, `record_provisional` cho
      một bản Nháp ghi đúng một giới hạn tạm có `run_id` của lượt, `source_id` là `version_id`, `source_version` là
      `pinned_hash`, cùng dòng đối tượng và trường của nó; gọi lần hai cho cùng lượt → 23505, không dòng thứ hai; hai
      lượt `simulate` của cùng bản Nháp, cùng mã băm → hai giới hạn tạm, không đụng chỉ mục duy nhất của giới hạn đã
      phát hành; cùng lời gọi cho một lượt `simulate` có gốc là một Bản ứng viên ở `evaluating` (một lần thử của Lượt
      kiểm định), dưới `(version_id, definition_hash)` → đúng một giới hạn tạm như trên; thu hẹp `record_provisional`
      hay trigger về gốc ở `draft` → lần ghi cho Bản ứng viên bị từ chối, test đỏ.
- [x] R6.12 (RA27): lượt `simulate` có giới hạn tạm chỉ có `mkt_lead` với `can_read`, giao dịch gắn
      `app.run_mode = 'simulate'`: bản ghi `mkt_campaign` → 0 dòng dù người thử thấy nó; lead người thử không thấy →
      0 dòng; lead người thử thấy → 1 dòng; cùng ba ca ở lần thử của Lượt kiểm định trên một Bản ứng viên, giới hạn tạm
      dưới `(version_id, definition_hash)`, chủ thể là người gửi: lead người gửi thấy → 1 dòng, lead người gửi không
      thấy và bản ghi `mkt_campaign` → 0 dòng.
- [x] R6.13 (RA27): cùng `app.boundary_id` của giới hạn tạm trong giao dịch có `app.run_mode = 'live'`, hay không gắn
      `app.run_mode` → 0 dòng, INSERT bị từ chối; gỡ kiểm `simulate` khỏi `studio.acl_boundary_objects` → test đỏ.
- [x] R6.14 (RA27): `record_provisional` với `run_id` của một lượt `live`, hay của một lượt thuộc tenant B → 23514
      `ck_actor_boundaries_provisional_run`, 0 dòng ở ba bảng; gỡ kiểm `run_mode`, hay kiểm `tenant_id` tường minh, khỏi
      trigger → test đỏ.
- [x] R6.15 (RA27): hai lượt `simulate` X, Y có giới hạn tạm, cạnh một giới hạn đã phát hành của công ty `active`:
      `dw_app` DELETE dòng cha của giới hạn tạm của X → dòng đối tượng và trường của nó đi theo cascade, không lỗi
      `ck_actor_boundaries_frozen`, giới hạn tạm của Y và giới hạn đã phát hành còn nguyên; sau commit,
      `app.boundary_id` cũ của X → 0 dòng (R6.5); bỏ nhánh "dòng cha là giới hạn tạm hay không còn" khỏi trigger của bảng
      con → lần xóa đó lỗi 23514, test đỏ.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:106-128`; spec: R6.3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:289-294`; spec: R6.6.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160-174`; spec: R6.4.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:67-68`; spec: R6.3.
- `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:67-82`; spec: R6.4, R6.6, R6.9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:93-96`; spec: R6.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-114`; spec: R6.8, R6.10.
- ADR-0109 (Accepted) quyết 6 (gốc là bản Nháp chỉ ở `simulate`), ADR-0111 (Accepted) quyết 3 (đọc dưới tầm của
  người thử), ADR-0120 (Accepted) quyết 3 (lần thử của Lượt kiểm định là lượt `simulate` bình thường),
  `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md` (`run_mode` trên dòng
  lượt và trên `RunContext`); spec: R6.11 tới R6.15.

## Comments

- 2026-10-23 (agent): needs-info chờ DO-12 (Đạt và người yêu cầu): lượt chạy không người kích hoạt chạy dưới danh
  nghĩa tài khoản dịch vụ gắn theo phiên bản, không bao giờ người phát hành; R6.9 và RA21 viết theo khuyến nghị đó.
- 2026-10-23 (agent): DO-12 (a) đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage; thêm dòng lớp bảng toàn tenant
  cho ba bảng giới hạn dữ liệu (DO-01).
- 2026-10-24 (agent): vòng sửa 4, lượt ba: bước 2 thôi nói "dịch vụ phát hành của agent-lifecycle và workflow-engine":
  móc phát hành của loại `agent` và `workflow` gọi `ActorBoundaryPort` trong giao dịch phát hành mà agent-lifecycle mở
  (ADR-0109 (Accepted) quyết 1; Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): bước 1 cấp DELETE cho `dw_app` trên ba bảng, trigger cho DELETE qua chỉ khi công ty ở
  `offboarding` thay cho phạm vi toàn tenant, và hai bảng con vào `_ORDERED_FIRST` trước định nghĩa đối tượng và trường,
  vì lane offboarding chỉ xóa bảng mà `dw_app` có DELETE; tiêu chí R6.8 mang ca âm của công ty `active`, tiêu chí mới
  R6.10 thử lượt xóa (CLAUDE.md, Data model rules; Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt sáu: giới hạn tạm của lượt `simulate` có gốc là bản Nháp (V4.22): bước 1 thêm
  `run_id`, hai chỉ mục duy nhất một phần và trigger `ck_actor_boundaries_provisional_run`, trigger
  `ck_actor_boundaries_frozen` cho xóa giới hạn tạm, kể cả qua cascade từ dòng cha mà trigger kết thúc lượt của
  workflow-engine xóa (workflow-engine:R3.14); bước 2 thêm `record_provisional`; bước 3 gắn `app.run_mode`; bước 5 chỉ
  nhận giới hạn tạm ở `simulate`; tiêu chí R6.11 tới R6.15 (RA27). Blocked by thêm
  tenant-config/03, nơi `run_mode` của dòng lượt và của `RunContext` ra đời, cạnh mà chuỗi chờ hiện có đã ngầm có (hai
  dòng Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): kiểm lượt sáu của vòng sửa 4: bước 1 thôi nói DELETE chỉ dùng được ở lượt xóa của offboarding, vì
  giới hạn tạm xóa được ở mọi lúc (spec R6.8, R6.15), và lý do trong danh sách bảng toàn tenant nêu cả giới hạn tạm,
  như mục Dữ liệu của spec (V4.22).
- 2026-10-24 (agent): lượt g của vòng sửa 4, theo dòng Quyết định tạm cùng ngày của spec: giới hạn tạm phủ mọi lượt
  `simulate` có gốc chưa phát hành, kể cả lần thử của Lượt kiểm định trên một Bản ứng viên đã niêm phong, ghi dưới
  `(version_id, definition_hash)` và giao với tầm của người gửi, danh nghĩa mà lane `studio_gate` xin lần thử
  (agent-lifecycle:R4.12); Mục tiêu, bước 1 và 4 nói gốc chưa phát hành thay bản Nháp, tiêu chí R6.11, R6.12 thêm ca
  Bản ứng viên với đột biến thu hẹp về `draft`. Không thêm cạnh: `record_provisional` và trigger không đổi hình, chỉ
  không được thu hẹp về `draft`.
- 2026-10-26 (agent): lượt h, theo H-2 (foundations-hardening/07, R11.4, R11.5, FH33): `_ORDERED_FIRST` đã bỏ, nên bước 1 đăng ký một bước xóa cho ba bảng vào sổ bước xóa ở composition root của worker và để lane suy thứ tự từ khóa ngoại RESTRICT của `pg_constraint`, thay cho hai mục chèn tay vào `_ORDERED_FIRST`; tiêu chí R6.10 đỏ khi gỡ bước và có ca khai trùng bảng. Ticket đã chờ foundations-hardening/07 qua ticket 03; không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  migration), đọc cùng `contracts.py`, `tenant_session.py`, agent-builder/05 và workflow-engine/03: 0 CRITICAL, 11 HIGH,
  sửa theo khuyến nghị (Quyết định 4/11/2026 của spec): (a) `source_id`, `source_version`; (b) một chỗ tìm giới hạn của
  lượt; (c) kiểu theo `api_name`, port nhận phiên; (d), (e) chủ thể và chế độ từ dòng lượt; (f) chuỗi giới hạn của lượt
  con; (g) quét ba setting, dư lượng trên kết nối; (h) bước xóa mặc định; (i) ghi giới hạn qua hàm definer; (j) `cmd`
  `assign`; R6.8 thử bằng vai sở hữu.
- 2026-11-04 (agent): MEDIUM để lại: (M1) một lượt `simulate` khác cùng công ty gắn được giới hạn tạm của lượt X chỉ
  khi mã gắn sai, vì `bind_actor` chỉ gắn chuỗi của chính lượt; không thêm `app.run_id`; (M2) giới hạn tạm của lượt kẹt
  xóa khi lượt tới hạn chót 30 ngày và kết thúc (workflow-engine:R3.14, R5.22); (M3) agent-builder/03 bước 4 nói đọc
  `RunContext.boundary_id`: ticket này không thêm trường đó, agent-builder/03 gắn qua `bind_actor` khi dựng (ghi ở đây
  vì khu vực đó không thuộc lần gate này); (M4) workflow-nodes/04 bước 6 nói ứng viên là thành viên workspace sở hữu,
  ticket 05 không đòi điều đó khi không đổi workspace.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 6 HIGH, sửa: (k) `studio.boundary_chain` là hàm SQL vì import-linter; (l)
  chờ workflow-engine/02 (`parent_run_id`), lượt không gốc Studio đọc 0; (m) `bind_actor` không đặt `app.user_id`, từ
  chối khi lệch chủ thể; (n) không trường `RunContext` mới, helper phiên cho công cụ đối tượng, nối thật ở
  agent-builder/03; (o) `api_name` chưa áp bị bỏ khỏi giới hạn tạm; mục Dữ liệu của spec theo `dw_app` không INSERT và
  bước xóa mặc định. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây khi dựng. Thứ tự
  dựng: sau 03, workflow-engine/02, org-and-principals/03, tenant-config/03; trước 05, custom-objects/03,
  workflow-engine/03.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): quyết khi dựng, mỗi điều một dòng. (D1) `ActorBoundaryPort`,
  `ObjectBoundary`, `FieldBoundary` khai một chỗ ở `dw_studio.core.application.boundaries`, không ở gói `records`: móc
  của `workflow` (`dw_studio.workflows`), của `agent` và `RunRequestService` (`dw_studio.core`) không được import
  `dw_studio.records` (hợp đồng độc lập và "Studio core imports no capability"); adapter `SqlActorBoundaries` ở
  `dw_studio.records.adapters.actor_boundaries`. Nếu sai thì: port về `records` và core khai một Protocol hẹp của riêng
  nó. (D2) tham số phiên của port kiểu `Any`, vì lớp application không import SQLAlchemy. Nếu sai thì: một Protocol
  `execute`/`scalar`. (D3) nối ở composition root của API (`StudioContainer.actor_boundaries`); worker chưa có
  composition Studio và không phụ thuộc `dw-studio`, nên nối ở đó là một phụ thuộc không ai đọc (failure-modes #1): lane
  Studio đầu tiên của worker (workflow-engine/04, /05) nối nó. Nếu sai thì: thêm `dw-studio` vào worker và dựng
  `SqlActorBoundaries` ở `dw_worker/main.py`. (D4) `studio.record_actor_boundary` kiểm thêm phiên bản: là của công ty,
  và ở giới hạn đã phát hành `definition_hash` của nó bằng mã băm truyền vào (23514 `ck_actor_boundaries_source`);
  `api_name` không có → 23503 mang tên khóa ngoại của bảng con. Nếu sai thì: bỏ phép kiểm nguồn. (D5) trigger
  `refuse_boundary_change` là SECURITY DEFINER, đọc `platform.tenants` và dòng cha không qua setting của người gọi;
  công ty không còn (cascade của chính dòng công ty) thì cho qua, như `platform.guard_control_switch()`. Nếu sai thì:
  invoker. (D6) `app.boundary_id`, `app.run_mode` vào `_REACH_READS` của `test_rls_coverage.py`, không vào
  `_TRUSTED_SETTINGS` như bước 4 viết: theo D6 của ticket 03, `app.actor_kind` và `app.user_id` là `_REACH_READS`, và
  một setting tin cậy sẽ để lọt policy chỉ hẹp theo nó; không policy nào đọc thẳng hai setting này. Nếu sai thì: thêm
  vào `_TRUSTED_SETTINGS`. (D7) `bind_actor(session, kind, *, run_id=None)`: `user` xóa `app.boundary_id` và
  `app.run_mode` về rỗng; `agent`, `workflow` đọc chế độ, chủ thể và chuỗi trong một SELECT rồi từ chối
  (`ActorBindingRefusedError`) trước khi đặt gì; loại không so với `artifact_kind` của dòng. Nếu sai thì: từ chối loại
  khác `artifact_kind`. (D8) helper phiên công cụ là
  `dw_agent_runtime.adapters.record_session.agent_record_session(session_factory, run)`, chủ thể lấy từ `RunContext`
  (`run_as_principal_id`, rồi `requested_by`, rồi `actor_id`) và `bind_actor` đối chiếu dòng lượt; danh sách cho phép
  của phép quét: `user_session.py` {`user`}, `record_session.py` {`agent`}, `dw_studio.testing.records` {`user`,
  `agent`, `workflow`} (helper `act_as_run`); `workflow` chưa có người gắn sản xuất, module runner của workflow-engine
  thêm dòng của nó khi dựng. Nếu sai thì: một dòng cho runner ngay bây giờ. (D9) `studio.boundary_chain` đòi chuỗi tới
  được một gốc (`parent_run_id` NULL) qua `chain_depth` giảm hẳn, không thì `'{}'`; `studio.acl_boundary_objects` trả
  `'{}'` cho một danh sách sai dạng thay vì lỗi ép kiểu. Nếu sai thì: lỗi. (D10) revision `ALTER POLICY` bốn policy
  PERMISSIVE tại chỗ trên bảng cha và mọi partition, văn bản chép từ `record_policy.actor_sql`; `test_record_policies.py`
  so catalog với module. Nếu sai thì: DROP rồi CREATE. (D11) test trồng phiên bản là bản Nháp đã niêm phong của loại
  `workflow`, và lượt `artifact_kind = 'agent'` trỏ tới chúng, vì loại `agent` chưa đăng ký tới agent-builder/02; mã
  giới hạn đọc id và mã băm, không đọc giai đoạn, trừ ca Lượt kiểm định dời Bản ứng viên sang `evaluating` theo đường
  hợp lệ. Nếu sai thì: trồng lại khi loại `agent` có.
- 2026-11-05 (agent): reviewing-feature-security: tách tenant (giới hạn và mắt xích của công ty B → 0 dòng, lượt của
  công ty B ở `record_provisional` → 23514, trigger đọc lượt theo `tenant_id` nêu tường minh, RLS FORCE ba bảng); phân
  quyền (giới hạn giao tầm sống, cửa sổ tầm ở mỗi giao dịch, chủ thể từ dòng lượt, `dw_app` không INSERT/UPDATE, xóa
  giới hạn đã phát hành chỉ khi offboarding); tác tử (lời nhắc bị chèn đòi lead của V → không tìm thấy; lượt con giao
  chuỗi); nội dung không tin cậy không áp dụng (không model, không prompt); audit: không lần ghi nào của ticket là bản
  ghi một người làm, giới hạn đi trong giao dịch phát hành có audit của agent-lifecycle; vòng đời: setting sống một
  giao dịch, giới hạn tạm xóa theo lượt (workflow-engine:R3.14), thiếu hay sai dạng → `'{}'`. `mutations/04.yaml` 25
  mục, chưa chạy `scripts/mutate.py`.
- 2026-11-05 (agent): MEDIUM. (M5) thứ tự xóa của offboarding: `studio.actor_boundary_fields` RESTRICT tới
  `studio.field_defs`, mà `field_defs` cũng mất dòng qua CASCADE từ `studio.object_defs`; `order_purge_steps` không
  mang cascade vào một bảng có bước riêng, nên bước của bảng trường chạy trước `object_defs` chỉ vì nó không có bước
  nào đứng trước (vòng đầu). Xanh hôm nay (R6.10), ẩn họa nếu sau này một khóa ngoại trỏ tới bảng trường giới hạn.
  (M6) port, adapter và `agent_record_session` chưa có người gọi sản xuất: agent-builder/03, /05 và workflow-engine/03
  đọc chúng; failure-modes #1 đứng mở tới đó. (M7) `studio.acl_boundary_objects` thành InitPlan ở mọi câu lệnh, kể cả
  của `user` (trả `'{}'` nhanh); đo ở lần đo trễ của hàng.
- 2026-11-05 (agent): resolved. Revision `996c234cfde3`. Test: `test_actor_boundaries.py` 19 ca (R6.3 ba ca gồm lượt
  của pack và (m), R6.4 ba ca gồm lời nhắc bị chèn và chuỗi con, R6.5 gồm mắt xích thiếu, của B và sai dạng, R6.6 hai,
  R6.7 hai, R6.8, R6.9, R6.10 qua lane offboarding thật, R6.11-R6.15); `test_privileges.py` (ba bảng, hàm, definer);
  `test_rls_coverage.py` (bảng toàn tenant, hàm của policy, `_REACH_READS`); đơn vị: quét setting (+3 dạng, người gắn
  `agent`/`workflow`), `bind_actor` (+3), mẫu policy (+1). Phá tay 9 mục của `mutations/04.yaml` (kiểm `simulate`, nhánh
  dòng cha của bảng con, tenant nêu tường minh của trigger lượt, `bool_and` của chuỗi, phép giao `HAVING`, `coalesce`
  chủ thể, cửa sổ tầm của phiên công cụ, quét người gắn `agent`, quét `app.boundary_id`), cả 9 đỏ. Cổng: đơn vị toàn
  repo xanh, phủ 77,06%; tích hợp: platform (privileges, rls_coverage, offboarding_coverage, offboarding,
  offboarding_registry) 170 qua, studio (metadata, record_policies, actor_boundaries, principal_scopes) 98 qua; mypy 851
  tệp, lint-imports 15 hợp đồng, verify_invariants, verify_architecture, check_hygiene, `release_manifest --check`,
  `check_plans.py` của khu vực 24 Đạt xanh. Không route nên không OpenAPI, không kiểu TS.
- 2026-11-05 (agent): nợ lúc đóng hàng: `scripts/mutate.py` cho `mutations/04.yaml` (25); `make test-integration` đầy
  đủ; P50/P95/P99 so với `d5ca66e` của mọi đường đọc và ghi bản ghi dưới policy mới (InitPlan
  `studio.acl_boundary_objects` thêm vào mỗi câu lệnh, kể cả của `user`), `bind_actor` của `agent`/`workflow` (một
  SELECT dòng lượt cùng `studio.boundary_chain`) và xuất, xóa của offboarding (ba bảng mới); `/code-review`; không
  route, ảnh hay dịch vụ nên không reviewing-deployment-security.
