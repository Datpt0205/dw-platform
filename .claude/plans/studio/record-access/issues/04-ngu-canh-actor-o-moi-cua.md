# 04 — Ngữ cảnh actor ở mọi cửa và biên dữ liệu của agent và workflow

Status: needs-triage
Blocked by: 03, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
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

1. Migration trong schema `studio`, RLS ENABLE và FORCE, policy `tenant_isolation_<bảng>` theo tenant, `dw_app`
   SELECT, INSERT và DELETE (DELETE giới hạn đã phát hành chỉ dùng được ở lượt xóa của offboarding, DELETE giới hạn
   tạm dùng được ở mọi lúc, nhờ trigger dưới; khẳng định trong
   `packages/python/dw_platform/tests/integration/test_privileges.py`):
    - `studio.actor_boundaries`: `tenant_id` (FK `platform.tenants` `ON DELETE CASCADE`), `id` (PK `(tenant_id, id)`),
      `kind text NOT NULL` với `ck_actor_boundaries_kind` (`agent`, `workflow`), `source_id uuid NOT NULL`,
      `source_version text NOT NULL`, `run_id uuid NULL` (khác NULL đúng ở giới hạn tạm: id của lượt `simulate` mà nó
      gắn, `source_id` là `version_id` của gốc chưa phát hành, `source_version` là `pinned_hash` mà bản kê của lượt ghim:
      mã băm tạm của bản Nháp, `definition_hash` của Bản ứng viên),
      `created_at timestamptz NOT NULL DEFAULT now()`, chỉ mục duy nhất `(tenant_id, kind, source_id, source_version)`
      `WHERE run_id IS NULL` và chỉ mục duy nhất `(tenant_id, run_id)` `WHERE run_id IS NOT NULL`. `run_id` không có
      khóa ngoại (Quyết định 24/10/2026 của spec): trigger BEFORE INSERT `ck_actor_boundaries_provisional_run` đọc
      `platform.worker_runs` theo `(tenant_id, run_id)` dưới RLS của tenant đang gắn và từ chối với 23514 khi không có
      dòng nào hay `run_mode` của dòng khác `simulate` (spec R6.14; cột của tenant-config/03).
    - `studio.actor_boundary_objects`: `tenant_id`, `boundary_id` (FK `(tenant_id, boundary_id)` tới
      `studio.actor_boundaries` `ON DELETE CASCADE`), `object_id` (FK `(tenant_id, object_id)` tới `studio.object_defs`
      `ON DELETE RESTRICT`), `can_read`, `can_create`, `can_update`, `can_delete`, `can_assign` (`boolean NOT NULL`),
      PK `(tenant_id, boundary_id, object_id)`, index trên `(tenant_id, object_id)`.
    - `studio.actor_boundary_fields`: `tenant_id`, `boundary_id` (FK như trên), `field_id` (FK `(tenant_id, field_id)`
      tới `studio.field_defs` `ON DELETE RESTRICT`), `access text NOT NULL` với `ck_actor_boundary_fields_access`
      (`read`, `edit`), PK `(tenant_id, boundary_id, field_id)`, index trên `(tenant_id, field_id)`; field-security đọc
      bảng này.
    - Trigger BEFORE UPDATE OR DELETE trên ba bảng gọi lỗi 23514 `ck_actor_boundaries_frozen`: UPDATE luôn bị từ chối,
      kể cả ở giới hạn tạm; DELETE qua khi `platform.tenants.status` của công ty của dòng là `offboarding`, cùng hình với
      `platform.guard_control_switch()` của agent-lifecycle (spec R6.8; agent-lifecycle:R7.5), hay khi dòng là một giới
      hạn tạm; ở hai bảng con, DELETE cũng qua khi dòng cha là giới hạn tạm hay không còn, tức cascade từ một DELETE dòng
      cha mà trigger của dòng cha đã cho qua, nên trigger kết thúc lượt của workflow-engine xóa được giới hạn tạm bằng
      một DELETE dòng cha (workflow-engine:R3.14; spec R6.15); trigger không đọc `app.workspace_scope`.
    - Đăng ký một bước xóa khai `studio.actor_boundaries`, `studio.actor_boundary_objects` và
      `studio.actor_boundary_fields` vào sổ bước xóa của lane `offboarding` ở composition root của worker
      (foundations-hardening/07, foundations-hardening:R11.4, foundations-hardening:R11.5; H-2); không viết thứ tự tay:
      lane suy từ khóa ngoại `ON DELETE RESTRICT` của hai bảng con tới `studio.object_defs` và `studio.field_defs` trong
      `pg_constraint` rằng bước này chạy trước bước của custom-objects/02 (spec R6.10; studio-skeleton:R4.2); trên phần
      đọc catalog và `export_rows` mà foundations-hardening/07 đã viết lại.
    - Ba bảng không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant của
      `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý do "giới hạn dữ liệu của một phiên bản
      agent hay quy trình đã phát hành, hay giới hạn tạm của một lượt `simulate` có gốc chưa phát hành, thuộc định nghĩa
      toàn tenant" (DO-01).
2. `ActorBoundaryPort` (Protocol trong gói truy cập của `dw_studio`) với hai phương thức chạy trong giao dịch của người
   gọi: `record(kind, source_id, source_version, objects, fields) -> boundary_id` cho phiên bản đã phát hành và
   `record_provisional(kind, run_id, version_id, pinned_hash, objects, fields) -> boundary_id` cho giới hạn tạm; adapter
   SQL; nối ở composition root. Móc phát hành của loại `agent` (agent-builder) và của loại `workflow` (workflow-engine)
   gọi `record`, trong giao dịch phát hành mà agent-lifecycle mở khi gọi móc của mục `ArtifactKindRegistry`
   (ADR-0109 (Accepted) quyết 1); `RunRequestService` của workflow-engine gọi `record_provisional` trong giao dịch nhận
   lượt, sau dòng `platform.worker_runs` (spec R6.11; workflow-engine:R3.13). Port không có phương thức xóa: trigger kết
   thúc lượt của workflow-engine xóa giới hạn tạm (workflow-engine:R3.14).
3. Setting: `TenantScope` thêm `boundary_id`; `_BIND_SCOPE` gắn `app.boundary_id`; một helper `bind_actor` trong
   `tenant_session.py` là chỗ duy nhất đặt `app.actor_kind`, `app.boundary_id` và `app.run_mode`, chép `run_mode` từ
   `RunContext.run_mode` của tenant-config/03 với loại `agent` và `workflow`. Test kiến trúc giữ bảng cho phép:
   `user` từ `TenantScope.from_access_context` (cửa API), `agent` từ phiên công cụ của `dw_agent_runtime`, `workflow`
   từ module runner của workflow-engine. `_TRUSTED_SETTINGS` của `test_rls_coverage.py` nhận `app.run_mode` như hai
   setting kia.
4. `RunContext` thêm `boundary_id: UUID | None`; phiên công cụ của runtime gắn loại actor `agent`, `app.user_id` là
   chủ thể của lượt chạy và `app.boundary_id` của phiên bản, hay của giới hạn tạm của lượt khi gốc chưa phát hành (spec
   R6.11), rồi gọi cửa sổ tầm ở mỗi giao dịch, kể cả lần đầu sau khi tiếp tục từ phê duyệt; không đọc tầm đóng dấu nào
   từ dòng lượt chạy.
5. `studio.acl_boundary_objects(cmd text)` (`LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định): trả các
   object của giới hạn có cờ ứng với lệnh khi `app.boundary_id` trỏ tới một giới hạn của tenant đang gắn, `'{}'` khi
   không, và `'{}'` khi giới hạn đó là giới hạn tạm mà `app.run_mode` khác `simulate` hay không gắn (spec R6.13).
   Dựng lại policy từ module mẫu của ticket 03 với `actor_ok` mới: loại `user`, hoặc loại `agent` hay `workflow`
   với `object_id` trong `studio.acl_boundary_objects(<lệnh>)`.
6. Lượt chạy không người kích hoạt: chủ thể là tài khoản dịch vụ của org-and-principals ticket 03, gắn theo phiên bản
   qua điểm gắn `principal` đã duyệt (DO-12 (a); chưa gắn thì workflow-triggers từ chối phát hành với `binding_unset`),
   với loại actor `workflow`; sổ tầm của nó tính như của một người, không nhánh riêng.

## Tiêu chí chấp nhận

- [ ] R6.3 (RA18): phiên công cụ của một lượt chạy agent có `app.actor_kind = 'agent'`, `app.user_id` là chủ thể và
      `app.boundary_id` của phiên bản; test kiến trúc: một module ngoài bảng cho phép gọi `bind_actor` với `agent` →
      đỏ.
- [ ] R6.4 (RA19): giới hạn chỉ có `mkt_lead` với `can_read`: bản ghi của object khác → 0 dòng dù chủ thể thấy nó;
      DELETE một lead khi giới hạn không có `can_delete` → 0 dòng bị ảnh hưởng; gỡ nhánh giới hạn khỏi policy → test
      đỏ.
- [ ] R6.4 (RA19): lượt chạy agent của người U, giới hạn `mkt_lead`, gọi công cụ đọc lead của người V theo id như một
      lời nhắc bị chèn yêu cầu → 0 dòng, công cụ trả không tìm thấy.
- [ ] R6.5 (RA19): loại `agent` không có `app.boundary_id` → 0 dòng; `app.boundary_id` của một giới hạn thuộc tenant B
      → 0 dòng.
- [ ] R6.6 (RA19): lượt chạy dừng chờ phê duyệt, chủ thể mất lần gán vai trò, lượt chạy tiếp tục → câu lệnh kế tiếp
      0 dòng; đọc tầm đóng dấu thay vì gọi cửa sổ tầm → test đỏ.
- [ ] R6.7: `ActorBoundaryPort.record` ghi đúng một giới hạn cho mỗi bộ (loại, nguồn, phiên bản); ghi lần hai cho
      cùng phiên bản → 23505, không có dòng thứ hai.
- [ ] R6.8 (RA20): UPDATE `studio.actor_boundary_objects` của phiên bản đã ghi, hay của một giới hạn tạm → 23514
      `ck_actor_boundaries_frozen`; `dw_app` DELETE một dòng của mỗi bảng thuộc giới hạn đã phát hành khi công ty
      `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding` → xóa được; gỡ phép kiểm DELETE khỏi trigger →
      test đỏ.
- [ ] R6.9 (RA21): tài khoản dịch vụ chỉ có `read` lead ở mức Của tôi, chạy với loại `workflow`: thấy lead của chính
      nó, 0 lead của người phát hành có mức Toàn công ty; gắn người phát hành làm chủ thể → test đỏ.
- [ ] R6.10: công ty `offboarding` có một giới hạn dữ liệu trỏ tới một đối tượng và một trường của nó → lane
      `offboarding` xuất mỗi dòng của ba bảng một lần rồi xóa hết, cùng định nghĩa đối tượng và trường, không lỗi khóa
      ngoại; dòng của công ty khác còn nguyên; test phủ offboarding (studio-skeleton:R4.1, studio-skeleton:R4.2) xanh;
      gỡ bước đã đăng ký khỏi sổ bước xóa → test đỏ; khai `studio.actor_boundary_objects` ở cả bước này và một
      bước khác → lane từ chối trước câu xóa đầu (foundations-hardening:R11.5).
- [ ] R6.11 (RA27): với một dòng `platform.worker_runs` `run_mode = 'simulate'` của fixture, `record_provisional` cho
      một bản Nháp ghi đúng một giới hạn tạm có `run_id` của lượt, `source_id` là `version_id`, `source_version` là
      `pinned_hash`, cùng dòng đối tượng và trường của nó; gọi lần hai cho cùng lượt → 23505, không dòng thứ hai; hai
      lượt `simulate` của cùng bản Nháp, cùng mã băm → hai giới hạn tạm, không đụng chỉ mục duy nhất của giới hạn đã
      phát hành; cùng lời gọi cho một lượt `simulate` có gốc là một Bản ứng viên ở `evaluating` (một lần thử của Lượt
      kiểm định), dưới `(version_id, definition_hash)` → đúng một giới hạn tạm như trên; thu hẹp `record_provisional`
      hay trigger về gốc ở `draft` → lần ghi cho Bản ứng viên bị từ chối, test đỏ.
- [ ] R6.12 (RA27): lượt `simulate` có giới hạn tạm chỉ có `mkt_lead` với `can_read`, giao dịch gắn
      `app.run_mode = 'simulate'`: bản ghi `mkt_campaign` → 0 dòng dù người thử thấy nó; lead người thử không thấy →
      0 dòng; lead người thử thấy → 1 dòng; cùng ba ca ở lần thử của Lượt kiểm định trên một Bản ứng viên, giới hạn tạm
      dưới `(version_id, definition_hash)`, chủ thể là người gửi: lead người gửi thấy → 1 dòng, lead người gửi không
      thấy và bản ghi `mkt_campaign` → 0 dòng.
- [ ] R6.13 (RA27): cùng `app.boundary_id` của giới hạn tạm trong giao dịch có `app.run_mode = 'live'`, hay không gắn
      `app.run_mode` → 0 dòng, INSERT bị từ chối; gỡ kiểm `simulate` khỏi `studio.acl_boundary_objects` → test đỏ.
- [ ] R6.14 (RA27): `record_provisional` với `run_id` của một lượt `live`, hay của một lượt thuộc tenant B → 23514
      `ck_actor_boundaries_provisional_run`, 0 dòng ở ba bảng; gỡ kiểm `run_mode` khỏi trigger → test đỏ.
- [ ] R6.15 (RA27): hai lượt `simulate` X, Y có giới hạn tạm, cạnh một giới hạn đã phát hành của công ty `active`:
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
