# 04 — Ngữ cảnh actor ở mọi cửa và biên dữ liệu của agent và workflow

Status: needs-triage
Blocked by: 03, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md
Area: studio
Yêu cầu: R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, RA18, RA19, RA20, RA21

## Mục tiêu

Agent và quy trình đọc, ghi bản ghi bằng tầm sống của người kích hoạt hay tài khoản dịch vụ chạy dưới danh nghĩa,
giao với giới hạn dữ liệu cố định khi phát hành, nên một yêu cầu bị chèn prompt đòi lead của người khác thất bại ở
RLS, không ở prompt (spec R6.3 tới R6.9; ADR-0103 (Accepted) mục 4 và 5; ADR-0105 (Accepted) mục 6).

## Việc cần làm

1. Migration trong schema `studio`, RLS ENABLE và FORCE, policy `tenant_isolation_<bảng>` theo tenant, `dw_app` chỉ
   SELECT và INSERT:
    - `studio.actor_boundaries`: `tenant_id` (FK `platform.tenants` `ON DELETE CASCADE`), `id` (PK `(tenant_id, id)`),
      `kind text NOT NULL` với `ck_actor_boundaries_kind` (`agent`, `workflow`), `source_id uuid NOT NULL`,
      `source_version text NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, UNIQUE
      `(tenant_id, kind, source_id, source_version)`.
    - `studio.actor_boundary_objects`: `tenant_id`, `boundary_id` (FK `(tenant_id, boundary_id)` tới
      `studio.actor_boundaries` `ON DELETE CASCADE`), `object_id` (FK `(tenant_id, object_id)` tới `studio.object_defs`
      `ON DELETE RESTRICT`), `can_read`, `can_create`, `can_update`, `can_delete`, `can_assign` (`boolean NOT NULL`),
      PK `(tenant_id, boundary_id, object_id)`, index trên `(tenant_id, object_id)`.
    - `studio.actor_boundary_fields`: `tenant_id`, `boundary_id` (FK như trên), `field_id` (FK `(tenant_id, field_id)`
      tới `studio.field_defs` `ON DELETE RESTRICT`), `access text NOT NULL` với `ck_actor_boundary_fields_access`
      (`read`, `edit`), PK `(tenant_id, boundary_id, field_id)`, index trên `(tenant_id, field_id)`; field-security đọc
      bảng này.
    - Trigger BEFORE UPDATE OR DELETE trên ba bảng gọi lỗi 23514 `ck_actor_boundaries_frozen`: UPDATE luôn bị từ chối,
      DELETE chỉ qua khi giao dịch ở phạm vi toàn tenant của lane offboarding.
    - Ba bảng không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant của
      `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý do "giới hạn dữ liệu của một phiên bản
      agent hay quy trình đã phát hành, thuộc định nghĩa toàn tenant" (DO-01).
2. `ActorBoundaryPort` (Protocol trong gói truy cập của `dw_studio`) với một phương thức
   `record(kind, source_id, source_version, objects, fields) -> boundary_id` chạy trong giao dịch của người gọi, và
   adapter SQL; nối ở composition root. Dịch vụ phát hành của agent-lifecycle và workflow-engine gọi nó trong giao dịch
   phát hành.
3. Setting: `TenantScope` thêm `boundary_id`; `_BIND_SCOPE` gắn `app.boundary_id`; một helper `bind_actor` trong
   `tenant_session.py` là chỗ duy nhất đặt `app.actor_kind` và `app.boundary_id`. Test kiến trúc giữ bảng cho phép:
   `user` từ `TenantScope.from_access_context` (cửa API), `agent` từ phiên công cụ của `dw_agent_runtime`, `workflow`
   từ module runner của workflow-engine.
4. `RunContext` thêm `boundary_id: UUID | None`; phiên công cụ của runtime gắn loại actor `agent`, `app.user_id` là
   chủ thể của lượt chạy và `app.boundary_id` của phiên bản rồi gọi cửa sổ tầm ở mỗi giao dịch, kể cả lần đầu sau khi
   tiếp tục từ phê duyệt; không đọc tầm đóng dấu nào từ dòng lượt chạy.
5. `studio.acl_boundary_objects(cmd text)` (`LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định): trả các
   object của giới hạn có cờ ứng với lệnh khi `app.boundary_id` trỏ tới một giới hạn của tenant đang gắn, `'{}'` khi
   không. Dựng lại policy từ module mẫu của ticket 03 với `actor_ok` mới: loại `user`, hoặc loại `agent` hay `workflow`
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
- [ ] R6.8 (RA20): UPDATE `studio.actor_boundary_objects` của phiên bản đã ghi → 23514 `ck_actor_boundaries_frozen`;
      DELETE ngoài phạm vi toàn tenant → 23514; DELETE qua lane offboarding → thành công.
- [ ] R6.9 (RA21): tài khoản dịch vụ chỉ có `read` lead ở mức Của tôi, chạy với loại `workflow`: thấy lead của chính
      nó, 0 lead của người phát hành có mức Toàn công ty; gắn người phát hành làm chủ thể → test đỏ.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:106-128`; spec: R6.3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:289-294`; spec: R6.6.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160-174`; spec: R6.4.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:67-68`; spec: R6.3.
- `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:67-82`; spec: R6.4, R6.6, R6.9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:93-96`; spec: R6.

## Comments

- 2026-10-23 (agent): needs-info chờ DO-12 (Đạt và người yêu cầu): lượt chạy không người kích hoạt chạy dưới danh
  nghĩa tài khoản dịch vụ gắn theo phiên bản, không bao giờ người phát hành; R6.9 và RA21 viết theo khuyến nghị đó.
- 2026-10-23 (agent): DO-12 (a) đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage; thêm dòng lớp bảng toàn tenant
  cho ba bảng giới hạn dữ liệu (DO-01).
