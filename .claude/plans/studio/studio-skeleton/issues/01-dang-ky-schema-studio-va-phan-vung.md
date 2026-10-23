# 01 — Kiểm tra đăng ký phân phối, schema studio chỉ SELECT mặc định và sổ bảng phân vùng

Status: needs-info (DO-01, DO-02)
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R4.1, R4.2, G1, G2, SKEL1, SKEL2, SKEL3, SKEL4, SKEL5, SKEL6, SKEL7, SKEL8

## Mục tiêu

Lát này cho người viết mọi spec Studio sau một nền đã được kiểm: gói mới không lọt khỏi chỗ đăng ký nào (R1), schema `studio` đóng quyền ghi khi không ai cấp (R2), bảng phân vùng theo tháng vào qua một sổ thay vì viết lại hàm (R3), và offboarding không bỏ sót bảng `studio` nào (R4). Chưa có bảng Studio thật ở đây; các test chạy trên bảng thử để chứng minh chúng đỏ được.

## Việc cần làm

1. `scripts/verify_architecture.py`: thêm `check_registration()` vào `main()`, và tham số `--root` (mặc định gốc repo, hôm nay cố định ở `REPO_ROOT`) để test chạy trên cây thử. Hàm đọc `members` của `[tool.uv.workspace]` (mở glob `packages/python/*`), tên distribution và tên import của từng thành viên, rồi in một dòng nêu tên gói và chỗ thiếu cho mỗi chỗ vắng: `[tool.uv.sources]`, `known-first-party`, `mypy_path`, coverage `source`, `root_packages`, `IMPORT_TO_DIST`; với gói trong `packages/python`, dòng `COPY` manifest của nó trong `infra/docker/api.Dockerfile`, `infra/docker/worker.Dockerfile` và `infra/docker/docgen.Dockerfile`; với gói có thư mục `domain`, gói con đó trong `source_modules` của hợp đồng "Domain layers never import frameworks or providers".
2. `pyproject.toml`: thêm `dw_docgen` vào `root_packages`; `uv run lint-imports` vẫn xanh.
3. `scripts/test_verify_architecture.sh` theo mẫu `scripts/test_check_plans.sh`: ca đầu chạy kiểm tra trên checkout và phải xanh; mỗi ca sau chép `pyproject.toml`, ba Dockerfile Python và `scripts/verify_architecture.py` vào thư mục tạm, trồng đúng một chỗ thiếu và đòi kiểm tra thoát 1 với dòng nêu chỗ đó; ca nào không trồng được lỗi thì cả test đỏ (failure-modes #3). Gọi nó từ `make test-architecture` và bước "Architecture tests" của CI.
4. Migration mới, id hex ngẫu nhiên của `alembic revision -m "studio schema and grants"`, theo kiểu khối DO cảnh báo khi thiếu `dw_app`: `CREATE SCHEMA studio`; `REVOKE ALL ON SCHEMA studio FROM PUBLIC`; `GRANT USAGE ON SCHEMA studio TO dw_app`; `ALTER DEFAULT PRIVILEGES IN SCHEMA studio GRANT SELECT ON TABLES TO dw_app`. Không gì cho `dw_provisioner`, `dw_agent_ro` hay PUBLIC.
5. Migration mới thứ hai, `alembic revision -m "time partition registry"`: bảng `platform.time_partitioned_tables` với `schema_name text NOT NULL`, `table_name text NOT NULL`, `append_only boolean NOT NULL`, `registered_by text NOT NULL`, khóa chính `(schema_name, table_name)`; không `tenant_id`, không RLS, chỉ migration ghi, `REVOKE ALL ON platform.time_partitioned_tables FROM dw_app`; dòng đầu `('platform', 'audit_events', true, 'platform')`. Viết lại `platform._ensure_one_partition(schema_name text, parent text, month date)` và bỏ bản hai tham số: `%I.%I` ở mọi chỗ đang ghi cứng `platform.`; ENABLE, FORCE, policy tenant của partition và việc chuyển dòng kẹt ở DEFAULT vẫn ở trong một hàm; thu hồi UPDATE, DELETE của `dw_app` khi dòng sổ có `append_only = true`, thay cho phép so tên `audit_events`. Viết lại `platform.ensure_time_partitions(months_ahead integer)` lặp sổ theo `schema_name, table_name`. `REVOKE EXECUTE ... FROM PUBLIC` trên hai hàm, `GRANT EXECUTE` hàm `ensure_time_partitions` cho `dw_app` như migration `0012`. `platform.drop_expired_partitions` giữ nguyên, nên thời hạn `audit_events` vẫn đọc từ tệp chính sách.
6. `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`: thêm `STUDIO_EXCLUSIONS` (tên bảng sang lý do), rỗng ở ticket này, cạnh `_ORDERED_FIRST`; offboarding không đọc nó, test phủ đọc nó.
7. Test tích hợp trong `packages/python/dw_platform/tests/integration/`:
    - `test_privileges.py`: bảng thử `studio.grant_probe` do migrator tạo, `dw_app` SELECT được, INSERT, UPDATE, DELETE bị từ chối; truy vấn catalog (`has_schema_privilege`, `has_table_privilege`, `has_function_privilege`, `aclexplode`) trả rỗng cho PUBLIC, `dw_provisioner`, `dw_agent_ro` trên schema `studio` và mọi đối tượng trong đó; không hàm `studio` nào PUBLIC chạy được; không sequence hay cột identity nào trong `studio`; `dw_app` không giữ quyền nào trên sổ.
    - `test_partition_maintenance.py`: bảng thử `studio.partition_probe` (phân vùng theo khoảng trên `created_at`, có `tenant_id`, policy tenant và DEFAULT) đăng ký trong giao dịch test; lượt bảo trì tạo tháng hiện tại và `months_ahead` tháng sau với RLS ENABLE, FORCE và policy; bảng thử `append_only = true` từ chối UPDATE, DELETE của `dw_app`; bảng thử ở `platform` với `append_only = false` giữ UPDATE; `PARENTS` đọc từ sổ thay vì hằng.
    - Test catalog trong cùng tệp: tập bảng phân vùng theo khoảng có DEFAULT bằng đúng tập dòng của sổ; mọi bảng trong sổ chỉ mang policy tenant mà hàm nhân bản.
    - `test_offboarding_coverage.py`: duyệt `pg_class` tìm bảng tenant của `studio` (có `tenant_id`, `relkind IN ('r', 'p')`, bỏ partition con); mỗi bảng phải xuất được và xóa được theo đúng hai truy vấn catalog của offboarding, hoặc nằm trong `STUDIO_EXCLUSIONS`; mỗi khóa ngoại `RESTRICT` hay `NO ACTION` chạm một bảng tenant của `studio` phải được `_ORDERED_FIRST` xếp bảng tham chiếu trước.

## Tiêu chí chấp nhận

- [ ] R1.1 (SKEL1): ca trồng lỗi bỏ `dw_evals` khỏi coverage `source` làm `verify_architecture.py` thoát 1 với dòng nêu `dw_evals` và coverage `source`; mỗi chỗ khác của R1.1 có ca riêng; gỡ lời gọi `check_registration()` khỏi `main()` thì các ca trồng lỗi đỏ.
- [ ] R1.2 (SKEL1): cây thử có gói `dw_probe` với thư mục `domain` không có trong hợp đồng domain làm kiểm tra đỏ, nêu `dw_probe.domain`.
- [ ] R1.3: `uv run python scripts/verify_architecture.py` và `uv run lint-imports` xanh trên checkout; bỏ `dw_docgen` khỏi `root_packages` thì kiểm tra đỏ.
- [ ] R2.1 (SKEL2): `dw_app` đọc được `studio.grant_probe` do migrator tạo mà không cần GRANT nào thêm.
- [ ] R2.2 (SKEL2): INSERT, UPDATE, DELETE của `dw_app` trên `studio.grant_probe` bị từ chối; đổi quyền mặc định sang DML đầy đủ trong DB test thì INSERT thành công và test đỏ.
- [ ] R2.3 (SKEL3): `GRANT SELECT ON studio.grant_probe TO dw_provisioner` làm test catalog đỏ, nêu vai và bảng.
- [ ] R2.4 (SKEL4): hàm thử `studio.probe_fn()` tạo không kèm `REVOKE EXECUTE ... FROM PUBLIC` làm test đỏ.
- [ ] R2.5: sequence thử `studio.probe_seq` làm test đỏ.
- [ ] R3.1: lượt bảo trì tạo partition tháng hiện tại và 3 tháng sau cho `studio.partition_probe` đã đăng ký; bảng thử không đăng ký không được tạo gì.
- [ ] R3.2 (SKEL5): partition mới có `relrowsecurity`, `relforcerowsecurity` và policy tenant của nó; bỏ ENABLE trong hàm thì `dw_app` đọc partition theo tên mà không đặt `app.tenant_id` thấy dòng và test đỏ; bỏ FORCE thì kiểm `relforcerowsecurity` đỏ.
- [ ] R3.3 (SKEL5): partition mới của bảng `append_only = true` từ chối UPDATE và DELETE của `dw_app`; partition của bảng thử `append_only = false` ở `platform` vẫn cho UPDATE.
- [ ] R3.4 (SKEL6): bảng phân vùng thử có DEFAULT mà không có dòng trong sổ làm test catalog đỏ, nêu tên bảng.
- [ ] R3.5 (SKEL7): INSERT của `dw_app` vào `platform.time_partitioned_tables` bị từ chối; `GRANT INSERT` cho `dw_app` thì test quyền đỏ.
- [ ] R3.6 (SKEL5): bảng thử trong sổ mang thêm một policy ngoài policy tenant làm test catalog đỏ, nêu tên bảng.
- [ ] R4.1 (SKEL8): bảng thử `studio.offboarding_probe` có `tenant_id`, policy `tenant_isolation_offboarding_probe` và chỉ SELECT theo cột cho `dw_app` làm test phủ đỏ, nêu tên bảng; thêm nó vào `STUDIO_EXCLUSIONS` kèm lý do thì xanh.
- [ ] R4.2 (SKEL8): hai bảng thử `studio` nối bằng khóa ngoại `ON DELETE RESTRICT` mà `_ORDERED_FIRST` không xếp làm test phủ đỏ, nêu tên khóa ngoại.
- [ ] G1: `test_a_term_drops_only_the_months_entirely_behind_it` xanh trước và sau thay đổi.
- [ ] G2: `test_a_partition_made_at_runtime_keeps_the_audit_log_append_only` xanh trước và sau thay đổi.
- [ ] Xong: `make test-architecture test-integration` xanh.

## Nguồn

- `pyproject.toml:12`, `pyproject.toml:14-25`, `pyproject.toml:101-113`, `pyproject.toml:139-155`, `pyproject.toml:208-220`, `pyproject.toml:238-249`, `pyproject.toml:278-281`; spec: R1.
- `scripts/verify_architecture.py:18`, `scripts/verify_architecture.py:21-59`, `scripts/verify_architecture.py:135-158`; spec: R1.1.
- `infra/docker/api.Dockerfile:21-31`, `infra/docker/worker.Dockerfile:17-27`, `infra/docker/docgen.Dockerfile:20-31`; spec: R1.1.
- `db/migrations/sql/0001_platform_grants.sql:18-25`, `db/migrations/sql/0001_platform_grants.sql:45-46`; spec: R2.
- `packages/python/dw_platform/tests/integration/test_privileges.py:187-205`; spec: SKEL2.
- `db/migrations/sql/0013_partition_maintenance.sql:21-104`, `db/migrations/sql/0013_partition_maintenance.sql:106-134`, `db/migrations/sql/0012_partition_maintenance.sql:209-226`; spec: R3.
- `packages/python/dw_platform/tests/integration/test_partition_maintenance.py:54`; spec: R3.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-114`; spec: R4.
- `configs/policies/retention@1.7.0.yaml:91-122`; spec: G1.
- ADR-0100 (Proposed) điểm 4 và 7.

## Comments
