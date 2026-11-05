# 09 — Offboarding nhận yêu cầu có đếm, yêu cầu chết mãi thành `failed`

Status: needs-triage
Blocked by: 08
Area: studio
Yêu cầu: R11.15, FH42

## Mục tiêu

Một yêu cầu offboarding làm worker chết mỗi lần chạy (discovery/09 đo một lần OOM; `_STALE_CLAIM_MINUTES` nhận lại nó
mỗi 30 phút và mỗi lần kéo mọi lane khác của worker chết theo) dừng sau ba lần nhận, thành `failed` với lý do mà người
vận hành đọc được, và một audit đứng tên người đã yêu cầu nêu lane đã dừng nó (R11.15; `CLAUDE.md`, "Agent and tool
rules"; ADR-0011 (Accepted)). Ticket 08 bỏ nguyên nhân OOM đã đo; ticket này chặn mọi nguyên nhân khác của cùng vòng
lặp, và giới hạn luôn lần thử lại một bước xóa hỏng ở `purging` (Quyết định 5/11/2026).

## Việc cần làm

1. Migration mới (`alembic revision -m "..."`, id ngẫu nhiên): cột `claims integer DEFAULT 0 NOT NULL` trên
   `platform.tenant_offboarding_requests` với `CHECK (claims >= 0)`, như `attempts` của `platform.channel_deliveries`;
   `dw_app` giữ UPDATE trên bảng (đã có), quyền khẳng định trong
   `packages/python/dw_platform/tests/integration/test_privileges.py`.
2. `claim_requested` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`) tăng `claims`
   trong cùng câu `UPDATE` nhận yêu cầu; một yêu cầu quá hạn đã có `claims >= 3` thì câu đó chuyển nó sang `failed` với
   `error` nêu số lần nhận và không trả nó.
3. Audit cho yêu cầu bị dừng: hành động mới trong `configs/copy/audit_actions.d/`, actor là `requested_by`,
   `details.lane` bằng `offboarding`, ghi trong giao dịch của lần dừng. Còn phải quyết ở gate: `platform.audit_events`
   cần `workspace_id`, mà sau lần xóa SQL công ty không còn workspace nào (`_record_purge_audit` bỏ qua audit khi đó).
4. Test: ba lần nhận rồi lần thứ tư → `failed`, không trả tenant, audit có actor và `details.lane`; tenant khác không bị
   đếm; bỏ phép đếm → đỏ.

## Tiêu chí chấp nhận

- [ ] R11.15 (FH42): yêu cầu đã nhận ba lần, quá hạn → lần nhận kế trả danh sách không có tenant đó, trạng thái `failed`,
      `error` nêu số lần nhận, một audit đứng tên người yêu cầu với `details.lane` bằng `offboarding`; sai nếu yêu cầu
      được nhận lần thứ tư hay audit đứng tên `system_actor('offboarding')`.
- [ ] R11.15: yêu cầu của tenant B ở `requested` không bị đếm hay đổi khi yêu cầu của A bị dừng; sai nếu B đổi.
- [ ] Xong: `uv run pytest -m integration packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_privileges.py packages/python/dw_platform/tests/integration/test_rls_coverage.py`
      xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:80`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:736-767`
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:44-58`
- `db/migrations/versions/5a25154e0296_platform_channel_deliveries.py:205`
- `db/bench/offboarding/RESULTS.md` (Phát hiện 1).
- spec: R11.15, FH42; Quyết định 5/11/2026.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): tách từ ticket 08 vì cột đếm là migration (Quyết định 5/11/2026 của
  spec). Chưa gate.
