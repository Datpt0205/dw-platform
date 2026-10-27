# 04 — Dọn khóa chống lặp quá hạn qua chính sách lưu giữ

Status: needs-triage
Blocked by: 02, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R2.8, R2.9, R2.13, R2.15, APS14

## Mục tiêu

Lát này cho `platform.idempotency_keys` một bộ xóa, để khóa và body đã lưu không ở lại mãi (R2.8, failure-modes #6), theo một chính sách lưu giữ có một chủ (ADR-0122 (Accepted) quyết định 7): một mảnh lưu giữ, một hàm không đối số đọc hạn từ `platform.retention_terms`, và một bộ xóa đăng ký vào sổ mà lane lưu giữ của telemetry-and-audit chạy. Không policy drain nào mở đọc bảng này xuyên tenant (R2.12). Ticket này chờ ticket 02, vì hai ticket cùng sửa `platform.idempotency_keys` qua migration, và chờ telemetry-and-audit/01, nơi có định dạng mảnh, `platform.retention_terms`, `platform.retention_term_days` và `RetentionPurgerRegistry`.

## Việc cần làm

1. Mảnh `configs/policies/retention.d/platform.idempotency_keys.yaml`: `days: 1`, `purger: row_delete`, `enforced: true`, `description` nói đây là bộ đệm phát lại của `Idempotency-Key`, 24 giờ (ADR-0108 (Accepted) điểm 4); `make release-manifest` sinh lại manifest.
2. Migration mới, id hex ngẫu nhiên của `alembic revision -m "idempotency keys purge function"`: hàm `platform.purge_expired_idempotency_keys() RETURNS integer`, SECURITY DEFINER, không đối số, `search_path` cố định; đọc hạn qua `platform.retention_term_days('platform.idempotency_keys')`, nên thiếu dòng hạn thì RAISE và không xóa gì (R2.15); xóa các dòng có `created_at < now() - make_interval(days => <hạn>)` ở mọi tenant và trả số dòng, không trả cột nào (R2.13). REVOKE ALL FROM PUBLIC và GRANT EXECUTE cho `dw_app` trong khối kiểm vai tồn tại, như `platform.prune_notifications()` (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:184-190`); dòng của hàm trong `packages/python/dw_platform/tests/integration/test_privileges.py`.
3. Adapter trong `dw_platform` gọi hàm đó trong giao dịch của chính nó và ghi số dòng vào log, không ghi audit (R2.9; ADR-0011 (Accepted), mục "Not applied"); đăng ký adapter vào `RetentionPurgerRegistry` với khóa `platform.idempotency_keys` ở composition root của worker.
4. `README.md`, mục "Idempotent requests": khóa và câu trả lời đã lưu bị xóa sau hạn của mảnh (24 giờ); một lần thử lại sau đó chạy như yêu cầu mới.

## Tiêu chí chấp nhận

- [ ] R2.8 (APS14): dòng có `created_at` 25 giờ trước bị xóa, dòng 1 giờ trước còn, ở hai tenant khác nhau trong cùng một lần gọi bộ xóa; nới điều kiện tuổi thì test tích hợp đỏ.
- [ ] R2.9: lần gọi bộ xóa ghi số dòng đã xóa vào log và không thêm dòng nào vào `platform.audit_events`.
- [ ] R2.13 (APS14): `platform.purge_expired_idempotency_keys()` trả một số nguyên và không trả cột nào của dòng; đổi hàm để trả dòng thì test đỏ.
- [ ] R2.15 (APS14): xóa dòng `platform.idempotency_keys` khỏi `platform.retention_terms` trong giao dịch test thì hàm thất bại và không dòng nào bị xóa; cho hàm rơi về một hạn mặc định thì test đỏ.
- [ ] R2.8 (APS14): test ở composition root của worker khẳng định `RetentionPurgerRegistry` có khóa `platform.idempotency_keys`; gỡ đăng ký thì test đỏ.
- [ ] Xong: `make test-unit test-integration release-manifest-check` xanh.

## Nguồn

- `db/migrations/sql/0002_http_idempotency.sql:67-70`; spec: R2.8.
- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:27-29`; spec: R2.13.
- `docs/adr/0011-a-background-lane-audits-as-itself.md:38-43`; spec: R2.9.
- `.claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md`, bước 9 và 12; spec: R2.8, R2.15.
- ADR-0122 (Accepted) quyết định 7; ADR-0108 (Accepted) điểm 4.

## Comments

- 2026-10-27 (agent): tách từ ticket 02 theo câu trả lời của Đạt cho Q2.
- 2026-10-27 (agent): EXECUTE cho `dw_app` theo tiền lệ `platform.prune_notifications()`; thêm test đăng ký bộ xóa.
