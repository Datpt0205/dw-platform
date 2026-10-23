# Khung Studio: gói, schema, seam, CI

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi spec Studio khác cần một chỗ để đặt mã và bảng đầu tiên: một distribution `dw_studio`, schema `studio` đóng quyền ghi khi không ai cấp, một sổ cho bảng phân vùng theo thời gian, seam API và web có nội dung thật, và luật nhận dịch vụ compose mới. Spec này dựng chỗ ở đó theo ADR-0100 (Proposed) và ADR-0101 (Proposed), trước mọi năng lực Studio. Ý định: cho Studio một chỗ ở trong repo mà mọi spec khác xây lên, không seam rỗng.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Một distribution được ghi tay ở `[tool.uv.sources]` (`pyproject.toml:14-25`), `known-first-party` (`pyproject.toml:101-113`), `mypy_path` (`pyproject.toml:139-155`), coverage `source` (`pyproject.toml:208-220`), `root_packages` (`pyproject.toml:238-249`), `IMPORT_TO_DIST` (`scripts/verify_architecture.py:21-59`) và dòng COPY manifest của ba Dockerfile Python (`infra/docker/api.Dockerfile:21-31`, `infra/docker/worker.Dockerfile:17-27`, `infra/docker/docgen.Dockerfile:20-31`). Ràng buộc: `dw_studio` phải có mặt ở đủ các chỗ này.
- Kiểm tra kiến trúc chỉ so import bên thứ ba với phụ thuộc đã khai (`scripts/verify_architecture.py:107-132`); trình sinh context dắt các chỗ đăng ký cho context, không có `docgen.Dockerfile` (`scripts/new_context.py:11-27`). Thiếu: không gì kiểm một distribution có mặt đủ chỗ.
- `dw_docgen` là thành viên workspace (`pyproject.toml:12`) và có trong `known-first-party` (`pyproject.toml:111`) nhưng vắng trong `root_packages` (`pyproject.toml:238-249`). Thiếu: import-linter không nhìn vào gói này (failure-modes #0).
- Baseline cấp USAGE trên `platform`, `knowledge`, `memory` (`db/migrations/sql/0001_platform_grants.sql:27`) và quyền mặc định DML đầy đủ cho `dw_app` (`db/migrations/sql/0001_platform_grants.sql:45-46`), trong khối DO cảnh báo khi thiếu `dw_app` (`db/migrations/sql/0001_platform_grants.sql:18-25`). Ràng buộc: schema mới tự cấp USAGE và quyền mặc định của nó.
- `test_privileges.py` kiểm USAGE trên mọi schema tenant dò từ catalog (`packages/python/dw_platform/tests/integration/test_privileges.py:59-84`) và chứng minh quyền mặc định bằng bảng thử `platform.grant_probe` (`packages/python/dw_platform/tests/integration/test_privileges.py:187-205`). Ràng buộc: test của `studio` theo cùng cách.
- Test phủ RLS dò bảng tenant qua cột `tenant_id`, kể cả partition (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:44-59`), và đòi một sàn schema cố định (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:64`). Ràng buộc: bảng `studio` tự vào test này; sàn chỉ gồm `studio` khi có bảng tenant đầu tiên.
- Offboarding chỉ xuất bảng mà `dw_app` có SELECT cả bảng (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`), chỉ xóa bảng có DELETE (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`), theo thứ tự RESTRICT ghi tay (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`). Thiếu: bảng chỉ có SELECT theo cột, hay không có DELETE, bị bỏ qua không một lời.
- `_ensure_one_partition` ghi cứng schema `platform` (`db/migrations/sql/0013_partition_maintenance.sql:35`, `db/migrations/sql/0013_partition_maintenance.sql:63-76`) và chỉ thu hồi ghi cho `audit_events` (`db/migrations/sql/0013_partition_maintenance.sql:81-83`); `ensure_time_partitions` lặp một mảng một phần tử (`db/migrations/sql/0013_partition_maintenance.sql:123`). Thiếu: không phân vùng được bảng `studio`, và mỗi bảng mới phải viết lại hàm.
- Thời hạn xóa partition `audit_events` nằm ở tệp chính sách, 1095 ngày với `enforced: true` (`configs/policies/retention@1.7.0.yaml:111-122`), và adapter đọc nó (`packages/python/dw_platform/src/dw_platform/adapters/persistence/partition_maintenance.py:93-95`). Ràng buộc: thời hạn này đã có chủ.
- API gán `container.runtime` (`apps/api/src/dw_api/bootstrap/wiring.py:307`) trước seam context (`apps/api/src/dw_api/bootstrap/wiring.py:332-337`); router có điều kiện chỉ gắn khi có phụ thuộc (`apps/api/src/dw_api/main.py:149-163`), trước seam router context (`apps/api/src/dw_api/main.py:165-167`). Ràng buộc: Studio dựng giữa hai chỗ này.
- Body bị chặn theo luồng chỉ ở webhook Zalo, trần `MAX_WEBHOOK_BYTES` (`apps/api/src/dw_api/routes/v1/zalo.py:155`, `apps/api/src/dw_api/routes/v1/zalo.py:186-192`). Ràng buộc: mẫu cho trần body của nhóm Studio.
- Thanh điều hướng gộp manifest ở một chỗ (`apps/web/lib/nav/registry.ts:134-137`); mục có `anyScope` rỗng bị ẩn (`apps/web/lib/nav/visibility.ts:18-24`). Ràng buộc: mục Studio vào qua một manifest và một spread, và ẩn khi chưa có khu vực nào.
- Guard antd-only là denylist (`apps/web/lib/__tests__/antd-only.test.ts:16-18`), kiểm manifest bằng cùng danh sách (`apps/web/lib/__tests__/antd-only.test.ts:128-141`), ESLint cũng vậy (`apps/web/.eslintrc.json:4-37`); phụ thuộc runtime hiện có trùng allowlist của ADR-0101 (Proposed) (`apps/web/package.json:14-26`). Thiếu: một thư viện UI mới qua được mọi kiểm tra (failure-modes #0).
- Docgen ở mạng riêng vì Qdrant và Valkey chạy không xác thực trên `dw-internal` (`infra/compose/docker-compose.yml:343-355`), với `read_only`, `cap_drop`, `no-new-privileges`, user không root, `mem_limit`, `pids_limit` (`infra/compose/docker-compose.yml:356-370`). Ràng buộc: tiền lệ cho dịch vụ mới.
- Dịch vụ hiện có publish cổng ở tệp gốc trên 127.0.0.1 (`infra/compose/docker-compose.yml:81-83`); không ảnh nào ghim digest, và `postgres:16-alpine`, `valkey:8-alpine`, `langfuse:3` dùng tag trôi (`infra/compose/docker-compose.yml:45`, `infra/compose/docker-compose.yml:94`, `infra/compose/docker-compose.yml:532`, `infra/compose/docker-compose.yml:563`). Ràng buộc: luật áp cho dịch vụ mới; dịch vụ cũ đứng trong danh sách ngoại lệ có tên.
- CI kiểm `docker compose config` theo profile (`.github/workflows/ci.yml:32-46`), smoke ba dịch vụ (`.github/workflows/ci.yml:281-290`) và chạy trivy trên bốn ảnh (`.github/workflows/ci.yml:309-313`). Ràng buộc: dịch vụ mới phải vào ba bước này.

## Mục tiêu

### R1 — Một distribution có mặt ở mọi chỗ đăng ký, được kiểm chứ không nhớ

Người thêm `dw_studio`, `dw_usage` hay một app mới không để gói nào lọt khỏi import-linter, mypy, coverage hay ảnh container.

- R1.1 NẾU một thành viên workspace uv vắng ở `[tool.uv.sources]`, `known-first-party`, `mypy_path`, coverage `source`, `root_packages` hay `IMPORT_TO_DIST`, hoặc một gói trong `packages/python` thiếu dòng COPY manifest ở một trong ba Dockerfile Python, THÌ kiểm tra đăng ký của job kiến trúc PHẢI đỏ và nêu tên gói cùng chỗ thiếu.
- R1.2 NẾU một thành viên workspace có gói con `domain` vắng trong `source_modules` của hợp đồng domain, THÌ kiểm tra đăng ký PHẢI đỏ và nêu tên gói con đó.
- R1.3 Kiểm tra đăng ký PHẢI xanh trên mọi thành viên workspace của commit gộp ticket 01, gồm 8 gói thư viện và 3 app.

### R2 — Schema `studio` cho `dw_app` đọc và không cho ghi khi không ai cấp

Người viết bảng Studio cấp quyền ghi theo từng bảng; bảng quên cấp hỏng ngay ở lần ghi đầu thay vì mở quyền (ADR-0100 (Proposed) điểm 4).

- R2.1 Vai `dw_app` PHẢI có USAGE trên schema `studio` và SELECT trên mọi bảng `dw_migrator` tạo trong đó.
- R2.2 NẾU migration tạo một bảng trong `studio` mà không cấp quyền ghi, THÌ PostgreSQL PHẢI từ chối INSERT, UPDATE và DELETE của `dw_app` trên bảng đó.
- R2.3 Vai `dw_provisioner`, `dw_agent_ro` và PUBLIC PHẢI không giữ quyền nào trên schema `studio` và trên bảng, hàm, sequence trong đó.
- R2.4 Mọi hàm trong schema `studio` PHẢI không cho PUBLIC quyền EXECUTE.
- R2.5 Schema `studio` PHẢI không chứa cột identity, cột serial hay sequence nào.
- R2.6 KHI schema `studio` có bảng tenant đầu tiên, sàn dò schema của test phủ RLS PHẢI gồm `studio`.

### R3 — Một sổ điều khiển việc tạo partition theo thời gian

Spec có bảng append-only phân vùng theo tháng thêm một dòng vào sổ trong migration tạo bảng, không viết lại hàm (ADR-0100 (Proposed) điểm 7).

- R3.1 KHI lane `partitions` chạy, lane `partitions` PHẢI tạo partition của tháng hiện tại và của `months_ahead` tháng sau cho mọi bảng có dòng trong `platform.time_partitioned_tables`, trong schema của chính bảng đó.
- R3.2 KHI lane `partitions` tạo một partition, partition đó PHẢI có RLS ENABLE, FORCE và policy tenant đọc `app.tenant_id`.
- R3.3 ĐỐI VỚI bảng đăng ký `append_only = true`, lane `partitions` PHẢI thu hồi UPDATE và DELETE của `dw_app` trên partition mới.
- R3.4 NẾU một bảng phân vùng theo khoảng có partition DEFAULT mà không có dòng trong sổ, THÌ test catalog PHẢI đỏ và nêu tên bảng.
- R3.5 Vai `dw_app` PHẢI không giữ quyền nào trên `platform.time_partitioned_tables`.
- R3.6 NẾU một bảng trong sổ mang policy nào khác policy tenant mà hàm tạo partition nhân bản, THÌ test catalog PHẢI đỏ và nêu tên bảng.

### R4 — Offboarding không bỏ sót bảng tenant nào của `studio`

Lane offboarding xuất rồi xóa mọi dữ liệu Studio của tenant (YC6); bảng nó không thấy được làm test đỏ trước khi bảng có dữ liệu thật.

- R4.1 NẾU một bảng tenant của schema `studio` không được lane `offboarding` xuất hay không được xóa, và không có trong danh sách loại trừ kèm lý do, THÌ test phủ offboarding PHẢI đỏ và nêu tên bảng.
- R4.2 NẾU một khóa ngoại `RESTRICT` hay `NO ACTION` chạm một bảng tenant của `studio` mà thứ tự xóa của lane `offboarding` không xóa bảng tham chiếu trước bảng được tham chiếu, THÌ test phủ offboarding PHẢI đỏ và nêu tên khóa ngoại.

### R5 — `dw_studio` dựa vào lõi nền tảng, lõi không bao giờ dựa vào nó

Một distribution; các gói con năng lực chỉ gặp nhau qua `dw_studio.core` và module `api` của nhau, và import-linter canh từng đường (ADR-0100 (Proposed) điểm 3).

- R5.1 KHI một module của `dw_kernel`, `dw_platform`, `dw_agent_runtime`, `dw_knowledge`, `dw_memory`, `dw_connectors`, `dw_observability` hay `dw_evals` import `dw_studio`, `lint-imports` PHẢI đỏ.
- R5.2 KHI một gói con năng lực của Studio import một module của gói con năng lực khác ngoài module `api` của gói đó, `lint-imports` PHẢI đỏ.
- R5.3 KHI `dw_studio.core` import một gói con năng lực, `lint-imports` PHẢI đỏ.
- R5.4 KHI tầng `domain`, `application` hay `presentation` của Studio import tầng `adapters` của Studio, `lint-imports` PHẢI đỏ.
- R5.5 KHI một module Studio ngoài `dw_studio.workflows.workflows` và `dw_studio.agents.workflows` import LangGraph hay LangChain, `lint-imports` PHẢI đỏ.
- R5.6 KHI một module Studio ngoài `dw_studio.core.adapters.cel` import thư viện CEL, `lint-imports` PHẢI đỏ.
- R5.7 NẾU một gói con trực tiếp của `dw_studio` vắng trong một hợp đồng mà R5.2 đến R5.5 đòi cho nó, THÌ kiểm tra đăng ký PHẢI đỏ và nêu tên gói con cùng hợp đồng.

### R6 — Seam API: một nhóm route `/api/v1/studio` có nội dung thật

Studio cắm vào API trên seam context, trong một nhóm route, và seam chỉ vào nhánh cùng route thật đầu tiên (ADR-0100 (Proposed) điểm 6).

- R6.1 KHI người gọi không có token gọi một đường dưới `/api/v1/studio/`, API PHẢI trả 401, không phải 404.
- R6.2 Tài liệu OpenAPI của API PHẢI liệt kê ít nhất một đường dưới `/api/v1/studio/`.
- R6.3 Mọi operation mang tag `studio` trong tài liệu OpenAPI PHẢI có đường bắt đầu bằng `/api/v1/studio/`.
- R6.4 TRONG KHI API chạy không có cơ sở dữ liệu, API PHẢI trả 404 cho mọi đường dưới `/api/v1/studio/` và không trả 500 cho đường nào.
- R6.5 NẾU body của một yêu cầu tới `/api/v1/studio/` dài hơn 1.048.576 byte (1 MiB), THÌ API PHẢI trả 413 `payload_too_large` trước khi handler chạy và không đổi gì; body đúng 1.048.576 byte được nhận.
- R6.6 KHI CI chạy smoke compose, bước smoke PHẢI gọi một đường dưới `/api/v1/studio/` không token trên container đã dựng và nhận 401.
- R6.7 Mô tả bảng của `dw_studio` trong mã PHẢI khớp catalog sau `alembic upgrade head` về bảng, cột, kiểu, nullable, khóa và index của schema `studio`.

### R7 — Seam web: một mục Studio, và guard UI thành allowlist

Người dùng thấy đúng một mục "Studio" trên thanh điều hướng (YC1); thư viện UI ngoài antd chỉ vào qua một ADR, theo đúng đường dẫn (ADR-0101 (Proposed) điểm 4).

- R7.1 Thanh điều hướng trên cùng PHẢI có đúng một mục trỏ tới `/studio`, nhãn "Studio".
- R7.2 TRONG KHI người xem không giữ khóa đọc nào của các khu vực Studio đã đăng ký, thanh điều hướng PHẢI ẩn mục Studio.
- R7.3 KHI người xem giữ khóa đọc của khu vực cấu hình mở `/studio`, trang `/studio` PHẢI liệt kê các artifact mà `GET /api/v1/studio/artifacts` trả cho người đó, nhãn tiếng Việt và giờ theo Asia/Ho_Chi_Minh.
- R7.4 KHI người xem mở `/studio` ở bề rộng 320 px, trang `/studio` PHẢI không cuộn ngang.
- R7.5 NẾU `apps/web` hay `@dw/ui` khai một phụ thuộc không có trong allowlist, trong danh sách công cụ dev hay trong một ngoại lệ có ADR, THÌ test allowlist UI PHẢI đỏ và nêu tên phụ thuộc.
- R7.6 NẾU một tệp nguồn của `apps/web` hay `@dw/ui` import một module ngoài allowlist, hoặc import module của một ngoại lệ ở ngoài glob đường dẫn của ngoại lệ đó, THÌ test allowlist UI PHẢI đỏ và nêu tệp cùng module.
- R7.7 KHI một tệp của `apps/web` import một module ngoài allowlist, ESLint PHẢI báo lỗi ở dòng import đó.

### R8 — Dịch vụ compose mới vào qua một bộ luật được test

Dịch vụ mới là dịch vụ không có tên trong danh sách "có trước luật" mà kiểm chính sách compose giữ, mỗi tên kèm lý do; OpenBao của connections-and-vault là dịch vụ đầu tiên chịu luật.

- R8.1 NẾU một dịch vụ không có trong danh sách được vào `dw-internal` nối vào mạng `dw-internal`, THÌ kiểm chính sách compose PHẢI đỏ và nêu tên dịch vụ.
- R8.2 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi dịch vụ nối vào một mạng không `internal: true`, hay một mạng có thành viên ngoài danh sách bên gọi khai cho dịch vụ đó.
- R8.3 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi ảnh kéo về không ghim `@sha256:`, hay khi Dockerfile của ảnh tự dựng có dòng `FROM` không ghim `@sha256:`.
- R8.4 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi dịch vụ publish cổng ở tệp compose nào ngoài overlay dev.
- R8.5 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi dịch vụ thiếu một trong `healthcheck`, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`, `user` không phải root, `mem_limit`, `pids_limit`, hay thiếu `deploy.resources` ở overlay uat và prod.
- R8.6 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi `profiles` của dịch vụ không có profile mang tên chính dịch vụ.
- R8.7 ĐỐI VỚI dịch vụ mới, kiểm chính sách compose PHẢI đỏ khi `.github/workflows/ci.yml` không chạy `docker compose config` với profile của dịch vụ, không có bước smoke gọi healthcheck của dịch vụ, hay không đưa ảnh của dịch vụ vào vòng trivy.
- R8.8 Kiểm chính sách compose PHẢI xanh trên các tệp compose của commit gộp ticket 04, với mỗi dịch vụ có trước luật mà vi phạm một luật được nêu tên trong danh sách ngoại lệ của luật đó.

## Hành vi giữ nguyên

- G1 KHI lane `partitions` chạy, lane `partitions` PHẢI TIẾP TỤC chỉ xóa những tháng `audit_events` nằm trọn sau thời hạn mà `configs/policies/retention@1.7.0.yaml` ghi (test: `test_a_term_drops_only_the_months_entirely_behind_it`).
- G2 KHI lane `partitions` tạo partition của `platform.audit_events`, partition đó PHẢI TIẾP TỤC không cho `dw_app` UPDATE hay DELETE (test: `test_a_partition_made_at_runtime_keeps_the_audit_log_append_only`).
- G3 KHI một tệp import `sonner`, `radix-ui`, `@radix-ui/*`, `class-variance-authority`, `lucide-react` hay một primitive đã gỡ khỏi `@dw/ui`, test allowlist UI PHẢI TIẾP TỤC đỏ (test: `catches each way the old system could come back`).

## Trong phạm vi

- Kiểm tra đăng ký trong `scripts/verify_architecture.py` và test trồng lỗi của nó.
- Schema `studio` và quyền của nó; `platform.time_partitioned_tables`; bản viết lại của `platform._ensure_one_partition` và `platform.ensure_time_partitions`.
- Test phủ offboarding cho `studio` và danh sách loại trừ mà test đọc.
- Distribution `packages/python/dw_studio` và các hợp đồng import-linter của Studio.
- `apps/api/src/dw_api/bootstrap/studio.py`, nhóm route `/api/v1/studio` với trần body, bước smoke 401 trong CI, đối chiếu mô tả bảng `studio` với catalog.
- `apps/web/app/studio/` (layout, `_meta/nav.ts`, `_meta/sections.ts`, trang `/studio`), allowlist UI trong `antd-only.test.ts` và ESLint.
- Kiểm chính sách compose `scripts/verify_compose_policy.py` và test trồng lỗi của nó.

## Ngoài phạm vi

| Việc                                                                                                                                                                            | Vì sao                                                                                                                                         | Chủ                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| R5.2: hợp đồng độc lập giữa các gói con năng lực                                                                                                                                | import-linter đỏ với module chưa có (`pyproject.toml:232-234`), nên hợp đồng vào cùng thay đổi tạo gói con năng lực thứ hai; R5.7 buộc điều đó | spec tạo gói con năng lực thứ hai                                  |
| R5.3: cấm `dw_studio.core` import gói con năng lực                                                                                                                              | cùng lý do; vào cùng gói con năng lực đầu tiên                                                                                                 | custom-objects (`dw_studio.records`)                               |
| R5.6: hợp đồng của thư viện CEL                                                                                                                                                 | thư viện CEL chưa chọn (ADR-0114 (Proposed))                                                                                                   | workflow-nodes                                                     |
| Seam worker `build_studio_lanes` và lane `studio_*` đầu tiên                                                                                                                    | seam vào cùng lane thật đầu tiên                                                                                                               | workflow-engine, ticket 04                                         |
| Seam eval: grader `studio.<gate>` ở seam của `scripts/run_evals.py`                                                                                                             | seam vào cùng bộ cổng thật đầu tiên                                                                                                            | agent-lifecycle, ticket 04                                         |
| Thứ tự xóa offboarding của từng bảng `studio`                                                                                                                                   | R4 buộc mỗi ticket tạo bảng tự thêm thứ tự của bảng đó                                                                                         | spec tạo bảng                                                      |
| Xóa partition hết hạn theo sổ, và cột thời hạn của sổ [CAN LAM RO: Q5]                                                                                                          | thời hạn `audit_events` đã có chủ ở tệp chính sách                                                                                             | studio-skeleton, đợt sau                                           |
| Khối số ADR 0100-0199, kiểm trùng số ADR, sửa `CLAUDE.md` và `.claude/PLAN.md` theo từng ADR                                                                                    | việc của Stage 0 và Stage 4 trong pipeline lập kế hoạch; `CLAUDE.md` chỉ sửa khi ADR được chấp nhận                                            | pipeline lập kế hoạch                                              |
| Nội dung từng năng lực Studio                                                                                                                                                   | khung chỉ cho chỗ đặt và luật                                                                                                                  | spec chủ của năng lực                                              |
| Dựng smokescreen, OpenBao, `mcp-gateway`, `model-proxy`, `sandbox-runner`; luật bản thay dev từ chối chạy khi đã triển khai, sao lưu có diễn tập khôi phục, dòng bộ nhớ đo được | mỗi dịch vụ chứng minh ở ticket dựng nó                                                                                                        | connections-and-vault, mcp-client, model-connections, code-sandbox |
| Khu vực con của mục Studio (đối tượng, quy trình, agent, kết nối, mức sử dụng)                                                                                                  | mỗi khu vực vào `_meta/sections.ts` cùng spec chủ                                                                                              | spec chủ của khu vực                                               |
| Ngoại lệ canvas `@xyflow/react` và `@dagrejs/dagre`                                                                                                                             | thêm cùng commit với import canvas đầu tiên (ADR-0101 (Proposed))                                                                              | workflow-builder-ui, ticket 01                                     |
| Distribution `dw_usage`                                                                                                                                                         | phải qua kiểm tra đăng ký của R1                                                                                                               | usage-and-limits                                                   |
| Máy chạy mã riêng: dự án compose `coderun` và triển khai hai máy                                                                                                                | W2                                                                                                                                             | studio-skeleton, đợt sau (W2), cùng code-sandbox                   |

## Dữ liệu

- Schema `studio`: `REVOKE ALL ON SCHEMA studio FROM PUBLIC`; `GRANT USAGE ON SCHEMA studio TO dw_app`; `ALTER DEFAULT PRIVILEGES IN SCHEMA studio GRANT SELECT ON TABLES TO dw_app`. Quyền ghi cấp theo từng bảng trong migration tạo bảng; id là UUIDv7 từ `IdGenerator`.
- `platform.time_partitioned_tables`: `schema_name text NOT NULL`, `table_name text NOT NULL`, `append_only boolean NOT NULL`, `registered_by text NOT NULL`, khóa chính `(schema_name, table_name)`; không `tenant_id`, không RLS, chỉ migration ghi, `REVOKE ALL ... FROM dw_app`. Dòng đầu: `('platform', 'audit_events', true, 'platform')`.
- `platform._ensure_one_partition(schema_name text, parent text, month date)` thay bản hai tham số; `platform.ensure_time_partitions(months_ahead integer)` lặp sổ theo `schema_name, table_name`; EXECUTE thu hồi khỏi PUBLIC trên cả hai, `ensure_time_partitions` cấp cho `dw_app`.

## API

- `APIRouter(prefix="/studio", tags=["studio"])` gắn ở `/api/v1` khi `container.studio` khác `None`; bản ghi ở `/api/v1/studio/objects/{api_name}/records` (ADR-0100 (Proposed) điểm 6).
- Không token: 401 kèm `WWW-Authenticate: Bearer`. Không cơ sở dữ liệu: nhóm không gắn, 404. Body quá 1.048.576 byte: 413 `payload_too_large`, trước handler.

## Màn hình

- Một mục "Studio" trên thanh điều hướng `@dw/ui`, `anyScope` gộp khóa đọc của mọi khu vực trong `_meta/sections.ts`; ẩn khi người xem không giữ khóa nào. Đây là điều hướng, không phải phân quyền: API vẫn kiểm.
- `/studio`: layout antd với menu khu vực của Studio; trang liệt kê artifact, nhãn tiếng Việt, giờ Asia/Ho_Chi_Minh, không cuộn ngang ở 320 px.

## Kiểm soát

| #      | Kiểm soát                                                                                              | Yêu cầu                            | Test âm                                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------ | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SKEL1  | Thành viên workspace thiếu một chỗ đăng ký làm job kiến trúc đỏ                                        | R1.1, R1.2                         | Trồng lỗi bỏ `dw_evals` khỏi coverage `source` → kiểm tra đỏ, nêu chỗ; gỡ lời gọi kiểm tra khỏi `main()` → ca trồng lỗi đỏ                                                                                           |
| SKEL2  | Quyền mặc định của `studio` chỉ là SELECT                                                              | R2.1, R2.2                         | Bảng thử `studio.grant_probe` do migrator tạo: `dw_app` đọc được, INSERT bị từ chối; đổi quyền mặc định sang DML đầy đủ → INSERT thành công, test đỏ                                                                 |
| SKEL3  | Không vai nào khác giữ quyền trên `studio`                                                             | R2.3                               | `GRANT SELECT` một bảng `studio` cho `dw_provisioner` → test catalog đỏ, nêu vai và bảng                                                                                                                             |
| SKEL4  | Hàm `studio` không cho PUBLIC chạy                                                                     | R2.4                               | Tạo hàm trong `studio` không `REVOKE EXECUTE ... FROM PUBLIC` → test đỏ                                                                                                                                              |
| SKEL5  | Partition mới mang RLS, FORCE, policy tenant và thu hồi append-only; sổ chỉ nhận bảng có policy tenant | R3.2, R3.3, R3.6                   | Bỏ ENABLE khỏi hàm → `dw_app` đọc partition mới của bảng thử `studio` theo tên khi chưa đặt `app.tenant_id` thấy dòng, test đỏ; bỏ FORCE → kiểm `relforcerowsecurity` đỏ; bảng thử trong sổ có thêm policy → test đỏ |
| SKEL6  | Bảng phân vùng có DEFAULT phải có dòng trong sổ                                                        | R3.4                               | Tạo bảng phân vùng thử có DEFAULT, không thêm dòng → test catalog đỏ, nêu tên                                                                                                                                        |
| SKEL7  | `dw_app` không ghi được sổ phân vùng                                                                   | R3.5                               | `GRANT INSERT` trên sổ cho `dw_app` → test quyền đỏ                                                                                                                                                                  |
| SKEL8  | Offboarding phủ mọi bảng tenant `studio`                                                               | R4.1, R4.2                         | Bảng thử `studio` chỉ có SELECT theo cột, không trong danh sách loại trừ → đỏ; khóa ngoại `RESTRICT` giữa hai bảng thử không có trong thứ tự → đỏ                                                                    |
| SKEL9  | Lõi nền tảng không import Studio                                                                       | R5.1                               | Thêm `import dw_studio` vào một module `dw_platform` → `lint-imports` đỏ                                                                                                                                             |
| SKEL10 | Tầng trong của Studio không import adapter Studio; LangGraph chỉ ở trình biên dịch                     | R5.4, R5.5                         | Module `presentation` của `dw_studio.core` import `adapters` → đỏ; module `dw_studio.core` import `langgraph` → đỏ                                                                                                   |
| SKEL11 | Gói con mới không lọt khỏi hợp đồng                                                                    | R5.7                               | Cây thử có `dw_studio.probe` với `adapters` không vào hợp đồng adapter → kiểm tra đăng ký đỏ                                                                                                                         |
| SKEL12 | Seam API tới được và không rỗng                                                                        | R6.1, R6.2                         | Bỏ lệnh gắn nhóm Studio → gọi không token trả 404, test đỏ; nhóm không có route → test OpenAPI đỏ                                                                                                                    |
| SKEL13 | Body vượt trần bị chặn trước handler                                                                   | R6.5                               | Body 1.048.577 byte → 413, handler không chạy; gỡ dependency trần → test đỏ                                                                                                                                          |
| SKEL14 | Mô tả bảng `studio` khớp catalog                                                                       | R6.7                               | Thêm một cột bằng migration mà không vào mô tả bảng → test đối chiếu đỏ                                                                                                                                              |
| SKEL15 | Allowlist UI đóng khi chưa có ADR, ngoại lệ chỉ đúng đường dẫn                                         | R7.5, R7.6                         | Thêm thư viện UI lạ vào `apps/web/package.json` → đỏ; import `@xyflow/react` trong `apps/web/app` khi chưa có ngoại lệ → đỏ; ngoại lệ thử import ngoài glob → đỏ                                                     |
| SKEL16 | Dịch vụ mới không vào `dw-internal`                                                                    | R8.1                               | Thêm dịch vụ thử nối `dw-internal` → kiểm chính sách đỏ, nêu tên dịch vụ                                                                                                                                             |
| SKEL17 | Dịch vụ mới theo luật mạng, ảnh, cổng, cứng hóa, profile và CI                                         | R8.2, R8.3, R8.4, R8.5, R8.6, R8.7 | Dịch vụ thử có ảnh không digest, hay cổng publish trong tệp gốc, hay thiếu `read_only` → kiểm chính sách đỏ, nêu luật                                                                                                |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` và `make test-integration` xanh; `pnpm --filter @dw/web test` và `bash scripts/test_compose_policy.sh` xanh.
- Ticket 02 merge trong cùng nhánh với tenant-config ticket 02, nên không seam nào vào `main` khi rỗng.

## Phụ thuộc

- `container.runtime` (`RuntimeSeam`) và các seam đánh dấu mà `CLAUDE.md` mục "Adding a bounded context" liệt kê; Studio dựng trên seam context.
- tenant-config ticket 02: module thật đầu tiên của `dw_studio.core`, bảng tenant đầu tiên của `studio` và `GET /api/v1/studio/artifacts`, cùng nhánh với ticket 02 (ADR-0100 (Proposed), Consequences).
- tenant-rbac: khóa đọc của từng khu vực Studio mà `anyScope` gộp.
- app-standards ticket 01: vỏ problem+json; 413 của R6.5 giữ `code` `payload_too_large` ở cả vỏ cũ lẫn vỏ mới.
- foundations-hardening: sửa offboarding (partition xuất một lần, xuất theo lô); test của R4 bổ sung, không thay.
- Kiểm lại khi: ADR-0100 (Proposed) hay ADR-0101 (Proposed) đổi trạng thái hay nội dung → cả spec; một spec thêm dịch vụ compose → R8, ticket 04; tenant-config đổi route đọc artifact → R7.3, ticket 03; một spec đăng ký bảng phân vùng có policy riêng → R3.6, ticket 01.

## Câu hỏi còn mở

- Q1. DO-01: Đạt có nhận Studio là năng lực nền tảng của repo này, định nghĩa trải toàn tenant mang `owning_workspace_id` mà RLS không đọc, và `CLAUDE.md` sửa theo từng ADR khi ADR đó được chấp nhận? Chủ: Đạt. Chặn: ticket 01, 02.
- Q2. DO-02: Một distribution `dw_studio` với hợp đồng import theo năng lực, và quy tắc đặt bảng ở `studio` hay `platform` với quyền mặc định chỉ SELECT cho `studio`? Chủ: Đạt. Chặn: R2.1, R2.2, R5.1, ticket 01, 02.
- Q3. DO-16: Mọi route Studio, kể cả bản ghi, nằm dưới `/api/v1/studio/`? Chủ: Đạt. Chặn: R6.1, R6.3, ticket 02.
- Q4. DO-03: Khối số ADR 0100-0199 gán trước trong area file, và điều khoản port mã si-platform (thỏa thuận viết, commit ghim, dòng nguồn gốc, không đồng bộ)? Chủ: Đạt, với PO và SA của si-platform. Không đổi: không ticket W1 nào của spec này port mã si-platform hay đánh số ADR.
- Q5. Thời hạn giữ một bảng phân vùng có chủ là cột `retention_months` của sổ (ADR-0100 (Proposed) điểm 7) hay `configs/policies/retention@1.7.0.yaml`, nơi đang giữ thời hạn 1095 ngày và cổng `enforced` của `audit_events`? Chủ: Đạt. Chặn: hàng "Xóa partition hết hạn theo sổ" ở Ngoài phạm vi.

## Quyết định

- 22/10/2026 (người đặt yêu cầu): D9: tài liệu kế hoạch Studio nằm trong repo này, area `studio`.
- 22/10/2026 (người đặt yêu cầu): D5: si-platform là tham chiếu và nguồn port chọn lọc; ticket W1 của spec này không port tệp nào.
- 22/10/2026 (người đặt yêu cầu): D1: workspace là đơn vị sở hữu dữ liệu; theo ADR-0100 (Proposed) điểm 5, bảng định nghĩa trải toàn tenant còn bảng nghiệp vụ giữ `workspace_id`.
- 23/10/2026 (người đặt yêu cầu): D14: máy chính lên ít nhất 4 vCPU / 16 GB trước khi OpenBao và egress proxy chạy; VM riêng cho `sandbox-runner` trước khi mã tenant chạy ở uat hay production (hàng W2 ở Ngoài phạm vi).
- 23/10/2026 (agent, tạm): DO-57 theo khuyến nghị (a): giao diện v1 chỉ tiếng Việt, chữ đi qua khóa thông điệp từ đầu. Nếu sai thì: thêm bản dịch theo cùng khóa ở R7.3, không đổi cấu trúc trang.
- 23/10/2026 (agent, tạm): trần body của nhóm `/api/v1/studio/` là 1 MiB, theo ví dụ route JSON của thiết kế app-standards; app-standards đợt W2 gom trần theo loại route và dùng lại cơ chế này. Nếu sai thì: đổi một hằng ở R6.5 và test SKEL13.
- 23/10/2026 (agent, tạm): `dw_docgen` vào `root_packages` trong ticket 01, vì R1.3 không xanh khi nó vắng. Nếu sai thì: `dw_docgen` vào danh sách ngoại lệ có lý do của kiểm tra đăng ký.
- 23/10/2026 (agent, tạm): `dw_studio` ở W1 chỉ có `core`; mỗi gói con năng lực ra đời cùng ticket đầu tiên đặt mã thật vào nó, vì `CLAUDE.md` "Work style" mục 6 cấm module chỉ có chỗ trống, và R5.7 buộc gói con mới vào hợp đồng. Nếu sai thì: ticket 02 tạo đủ bảy gói con, mỗi gói một module thật.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0100 (Proposed) điểm 7 nói sổ có cột `retention_months`, `configs/policies/retention@1.7.0.yaml:111-122` nói thời hạn `audit_events` do tệp chính sách giữ; theo mã hiện có, sổ ở W1 chưa có cột thời hạn (failure-modes #1, #2). Hỏi: Q5. Nếu sai thì: cột vào sổ cùng bản viết lại `platform.drop_expired_partitions`.
- 23/10/2026 (agent, tạm): một bảng trong sổ chỉ được mang policy tenant mà hàm nhân bản (R3.6), vì partition gọi thẳng theo tên chỉ có policy đó. Nếu sai thì: spec cần policy riêng mở rộng hàm để nhân bản policy của nó.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: YC1 xếp mức độ sử dụng vào mục Studio, thiết kế của spec này đặt trang mức sử dụng ở `/admin`; theo YC1 cho cấu trúc điều hướng, còn trang thuộc usage-and-limits.

## Danh sách ticket

| #   | Ticket                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Kiểm tra đăng ký phân phối, schema studio chỉ SELECT mặc định và sổ bảng phân vùng](issues/01-dang-ky-schema-studio-va-phan-vung.md) |
| 02  | [Gói dw_studio, hợp đồng import và seam API /api/v1/studio](issues/02-goi-dw-studio-va-seam-api.md)                                   |
| 03  | [Seam web Studio và guard antd-only thành allowlist](issues/03-seam-web-va-allowlist-antd.md)                                         |
| 04  | [Chính sách compose cho dịch vụ mới](issues/04-chinh-sach-compose-dich-vu-moi.md)                                                     |
