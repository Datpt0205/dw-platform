# 09 — Offboarding nhận yêu cầu có đếm, yêu cầu chết mãi thành `failed`

Status: ready-for-agent
Blocked by: 08
Area: studio
Yêu cầu: R11.15, R11.20, FH42

## Mục tiêu

Một yêu cầu offboarding làm worker chết mỗi lần xuất (discovery/09 đo một lần OOM; `_STALE_CLAIM_MINUTES` nhận lại nó
mỗi 30 phút và mỗi lần kéo mọi lane khác của worker chết theo) dừng sau ba lần nhận, thành `failed` với lý do mà người
vận hành đọc được, và một audit của chính lane nêu người đã yêu cầu (R11.15; `CLAUDE.md`, "Agent and tool rules":
lane tự dừng lần thử lại thì audit như chính nó; ADR-0011 (Accepted)). Ticket 08 bỏ nguyên nhân OOM đã đo; ticket này
chặn mọi nguyên nhân khác của cùng vòng lặp ở `exporting`. Yêu cầu ở `purging` không bị dừng: nó theo R11.11 và được
thử lại mỗi `_STALE_CLAIM_MINUTES` (Quyết định 5/11/2026, gate ticket 09 và 10).

## Việc cần làm

1. Migration mới (`alembic revision -m "..."`, id ngẫu nhiên, `down_revision` là head lúc commit): cột
   `claims integer DEFAULT 0 NOT NULL` trên `platform.tenant_offboarding_requests` với `CHECK (claims >= 0)`, như
   `attempts` của `platform.channel_deliveries`; dòng có trước migration bắt đầu từ 0. `dw_app` giữ UPDATE trên bảng
   (đã có), quyền khẳng định trong `packages/python/dw_platform/tests/integration/test_privileges.py`.
2. `claim_requested` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:788-830`):
    - trước câu nhận, lane đọc `id` của mọi yêu cầu quá hạn ở `exporting` có `claims >= 3`, rồi dừng từng yêu cầu
      trong một giao dịch riêng của nó (R11.20), để audit hỏng của một yêu cầu không lăn ngược lần dừng của yêu cầu
      khác: `UPDATE ... WHERE id = :id AND status = 'exporting' AND claims >= 3 AND updated_at < ... RETURNING` chuyển
      `failed`, `error` là chữ của lane nêu số lần nhận (không chép lỗi của lượt trước), `claims` giữ nguyên; audit chỉ
      cho dòng câu đó trả về, nên hai worker cùng dừng một yêu cầu ghi một audit;
    - câu nhận tăng `claims` của mọi dòng nó nhận (lần nhận đầu từ `requested` tính là một) và không nhận dòng
      `exporting` nào có `claims >= 3`; dòng `purging` được nhận như hôm nay, kể cả khi `claims >= 3`.
3. Audit của lần dừng: hành động `tenant.offboarding.stopped` trong một fragment mới
   `configs/copy/audit_actions.d/foundations-hardening.yaml`, dựng bằng `lane_audit_event(lane="offboarding", ...)`
   (actor `system_actor('offboarding')`, `details.actor` bằng `system:offboarding`), `details.requested_by` là
   `requested_by` của yêu cầu và `details.claims` là số lần nhận, `workspace_id` là một workspace của tenant như
   `_record_purge_audit` (`offboarding.py:753-756`), ghi bằng `append_across_tenants` cuối giao dịch của lần dừng. Ở
   `exporting` công ty luôn còn workspace (Quyết định 5/11/2026, gate ticket 09 và 10); không tìm được workspace nào thì
   giao dịch ném lỗi, yêu cầu giữ `exporting`, lane log và đi tiếp tới câu nhận.
4. Test trong `packages/python/dw_platform/tests/integration/test_offboarding.py`: các ca của FH42; bỏ phép đếm, đứng
   tên `requested_by`, hay dừng trong giao dịch của câu nhận → đỏ.

## Tiêu chí chấp nhận

- [ ] R11.15 (FH42): yêu cầu `exporting` đã nhận ba lần, quá hạn → lần nhận kế trả danh sách không có tenant đó, trạng
      thái `failed`, `error` nêu 3 lần nhận, một audit `tenant.offboarding.stopped` với actor `system_actor('offboarding')`,
      `details.actor` bằng `system:offboarding` và `details.requested_by` là người yêu cầu; sai nếu yêu cầu được nhận
      lần thứ tư, hay audit đứng tên người yêu cầu.
- [ ] R11.15 (FH42): yêu cầu `purging` đã nhận ba lần, quá hạn → lần nhận kế trả nó với `resume_export_key`, trạng thái
      giữ `purging`; sai nếu nó thành `failed`.
- [ ] R11.20 (FH42): yêu cầu `requested` của tenant B được nhận cùng lượt A bị dừng, `claims` của B bằng 1, và yêu cầu
      của B không đổi gì khác; sai nếu B đổi hay không được nhận.
- [ ] R11.20 (FH42): tenant A không còn workspace nào (xóa trong test bằng vai migrator) và tenant C cũng có yêu cầu
      `exporting` đã nhận ba lần, quá hạn → A giữ `exporting`, không được nhận, không có audit; C thành `failed` với
      audit; B vẫn được nhận; sai nếu A thành `failed` không audit, C không thành `failed`, hay B không được nhận.
- [ ] Xong: `uv run pytest -m integration packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_rls_coverage.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py`
      xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:81`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:788-830`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:753-756`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/lane_audit.py:24-32`
- `packages/python/dw_platform/src/dw_platform/domain/audit.py:67-93`
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:44-58`
- `db/migrations/versions/5a25154e0296_platform_channel_deliveries.py:205`
- `db/bench/offboarding/RESULTS.md` (Phát hiện 1).
- spec: R11.15, R11.20, FH42; Quyết định 5/11/2026.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): tách từ ticket 08 vì cột đếm là migration (Quyết định 5/11/2026 của
  spec). Chưa gate.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và đường biên, rồi lượt xác
  nhận). Đã sửa: actor của audit dừng là `system_actor('offboarding')`, không là người yêu cầu (CRITICAL, `CLAUDE.md`
  "Agent and tool rules"); chỉ `exporting` bị dừng, `purging` theo R11.11 (HIGH, R11.15 trái R11.11); lần dừng có giao
  dịch riêng mỗi yêu cầu, trước câu nhận (HIGH, R11.20); neo `offboarding.py:80` và `:736-767` về `:81` và `:788-830`
  sau ticket 08. MEDIUM, không sửa: (1) một worker chỉ tạm dừng quá `_STALE_CLAIM_MINUTES` rồi chạy tiếp vẫn làm mới
  được dòng của lần nhận mới, vì `keep_claim` và `mark_status` không so `claims`; dùng `claims` làm fencing token là
  việc của R11.17 và R11.19, ngoài ticket này. Nếu sai thì: `keep_claim` và `mark_status` thêm `AND claims = :claims`
  của lần nhận. (2) Ba lần triển khai lại trong một lượt xuất cũng tính ba lần nhận và dừng yêu cầu; người vận hành tạo
  yêu cầu mới (`uq_tenant_offboarding_requests_active` bỏ qua `failed`,
  `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:62-66`), tenant giữ `offboarding`, `claims` của
  yêu cầu mới bắt đầu từ 0. (3) Hai worker dừng cùng lúc một yêu cầu: khóa dòng của `UPDATE ... RETURNING` cho đúng một
  audit; không cần test đồng thời riêng. LOW: yêu cầu không ghi được audit chỉ hiện trong log.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
