# 01 — Một chủ cho danh mục gói dịch vụ: platform.plan_limits thay DEFAULT_PLANS

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, UL1

## Mục tiêu

Số giới hạn của một Gói dịch vụ về một chủ trong database, đóng drift `failure-modes.md` #2 giữa
`DEFAULT_PLANS` và `platform.plans` (spec R1). Mọi bên đọc giới hạn gói đọc từ `platform.plan_limits`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên) tạo `platform.plan_limits`: `plan_id text` khóa chính và FK
   `platform.plans ON DELETE CASCADE`; không `tenant_id`, không RLS; `dw_app` chỉ SELECT (grant trong
   migration, khẳng định ở `test_privileges.py`); cột `CHECK (>= 0)` `runs_per_day`, `cost_usd_per_day`,
   `cost_usd_per_month`, `tokens_per_month`, `max_concurrent_runs`, `requests_per_minute`,
   `tokens_per_minute` (NULL = không giới hạn); trần mỗi lượt NOT NULL `max_cost_usd_per_run`,
   `max_tokens_per_run`, `max_steps_per_run` CHECK (BETWEEN 1 AND 500), `max_model_calls_per_run`,
   `max_tool_calls_per_run`, `max_run_seconds`.
2. Seed giữ số hiện tại: `runs_per_day` 20, 200, 2000; tiền NULL (chờ DO-59); trần mỗi lượt lấy từ mặc
   định `ModelBudgets` (USD 2.0, 120000 token), 50 bước, số giây và số lời gọi theo đề xuất ghi ở
   Comments.
3. Migration mới chuyển dữ liệu `platform.plans.quotas` sang cột rồi bỏ cột `quotas` (không sửa
   baseline); tính năng đọc từ `platform.plans.features`.
4. `PlanCatalogPort` đọc database (cache tiến trình, TTL ngắn); `PlanEntitlementService` lấy số và tính
   năng từ một nguồn; xóa `DEFAULT_PLANS` (`entitlement.py:13-36`) và nhánh đôi ở `has_feature`
   (`entitlement.py:45-49`).

## Tiêu chí chấp nhận

- [ ] R1.1 (UL1): mọi bên đọc giới hạn gói đọc `platform.plan_limits`; test kiến trúc không còn dict
      danh mục gói trong mã; khai lại dict → test kiến trúc đỏ.
- [ ] R1.2 (UL1): thiếu dòng gói → `QuotaExceededError` khi nhận lượt chạy, không hiểu thành "không giới
      hạn"; gỡ kiểm thiếu dòng → test đỏ.
- [ ] R1.3: `dw_app` ghi `platform.plan_limits` → bị từ chối (chỉ migration ghi).
- [ ] R1.4: đổi `runs_per_day` trong database → lần nhận lượt chạy sau dùng số mới; `max_steps_per_run`
      501 → migration từ chối, 1 → nhận.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:13-36`; spec: R1.1 (DEFAULT_PLANS).
- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:45-49`; spec: R1.1
  (`has_feature` đọc hai nguồn).
- `db/migrations/sql/0001_platform_baseline.sql:332-337`; spec: R1.1, R1.3 (`platform.plans`);
  ADR-0121 (Proposed) quyết 6.

## Comments

- 2026-10-23 (agent): từ B10b usage-and-limits 01. custom-objects thêm giới hạn metadata (object,
  trường, index) làm cột của cùng bảng — một danh mục gói cho nền tảng.
