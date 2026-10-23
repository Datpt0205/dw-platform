# 02 — Cột run Studio, CHECK trạng thái và cửa RunRequestService

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md, .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, WE1

## Mục tiêu

Cho `platform.worker_runs` các cột một lượt chạy Studio cần và đặt `RunRequestService` làm cửa nhận duy nhất: ghim bản kê và chế độ chạy, đặt run-as và khóa chống trùng, xếp vào hàng mà không gọi runner (R3 của spec).

## Việc cần làm

1. Migration (revision hex ngẫu nhiên) thêm các cột R3.1 vào `platform.worker_runs`: `root_run_id`, `parent_run_id`, `chain_depth`, `artifact_kind`, `artifact_id`, `artifact_version_id`, `definition_hash`, `trigger_kind`, `run_as_principal_id`, `request_key`, `priority`, `available_at`, `lease_expires_at`, `attempts`, `dead_at`. CHECK `status` là của foundations-hardening/06 (gồm `queued`, `waiting`, `blocked`); ticket này không tạo lại CHECK đó.
2. `uq_worker_runs_tenant_id_id UNIQUE (tenant_id, id)`; partial unique `(tenant_id, request_key) WHERE request_key IS NOT NULL`; index `(tenant_id, priority, available_at) WHERE status = 'queued'`, `(tenant_id, artifact_id, created_at DESC, id DESC)`, `(tenant_id, root_run_id)`. FK `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` là của tenant-config/04. Grant trong migration.
3. `RunRequestService` (`dw_studio.core.run_request`): nhận một yêu cầu chạy của mọi loại (chat, manual, agent_node, agent_link, workflow-as-tool, eval, trigger), đặt `run_mode` do cửa quyết (tenant-config/03), dựng và ghi `run_manifest_hash` qua `RunManifestBuilder` (tenant-config/04), đặt `run_as_principal_id`, `trigger_kind`, `request_key`, chèn dòng `worker_runs` ở `queued` trong một giao dịch; không gọi runner.
4. Test kiến trúc `RunRequestService` là chỗ duy nhất chèn `worker_runs` `status='queued'` mang `artifact_kind` Studio (WE1).

## Tiêu chí chấp nhận

- [ ] R3.1: migration thêm đủ 15 cột; mô tả bảng khớp catalog sau `alembic upgrade head`.
- [ ] R3.2: `dw_app` ghi `status='bogus'` → CHECK của foundations-hardening/06 từ chối (ticket này không đặt lại CHECK, chỉ dựa vào nó).
- [ ] R3.3: `RunRequestService` tạo một dòng `queued` mang `run_mode`, `run_manifest_hash`, `run_as_principal_id`, `trigger_kind`, `request_key` đúng; thiếu `run_manifest_hash` → giao dịch lùi.
- [ ] R3.4: `RunRequestService` không gọi runner hay `graph.ainvoke` (kiểm bằng spy ở test).
- [ ] R3.5 (WE1): thêm một module chèn `worker_runs` `status='queued'` với `artifact_kind` Studio ngoài `RunRequestService` → test kiến trúc đỏ; gỡ khẳng định → ca trồng lỗi qua.
- [ ] R3.6: hai yêu cầu cùng `request_key` song song → đúng một dòng `worker_runs`.
- [ ] R3.7: `dw_app` gắn tenant A SELECT dòng `worker_runs` của tenant B → 0 dòng.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:447`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:388`; spec: R3, WE1.
- foundations-hardening:R9.3 (CHECK `status`); tenant-config:R4, R6.1 (chế độ chạy, bản kê); ADR-0113 (Proposed) quyết 1.

## Comments
