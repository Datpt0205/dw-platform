# 02 — Gói dw_studio, hợp đồng import và seam API /api/v1/studio

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R2.6, R5.1, R5.4, R5.5, R5.7, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, SKEL9, SKEL10, SKEL11, SKEL12, SKEL13, SKEL14, SKEL23

## Mục tiêu

Lát này cho Studio một distribution và một cửa vào API: `dw_studio` đăng ký đủ chỗ với các hợp đồng import mà lõi nền tảng không vượt được (R5), và nhóm route `/api/v1/studio` dựng từ `container.runtime` trên seam context (R6). Ticket này vào cùng nhánh với tenant-config ticket 02, nơi có module thật đầu tiên của `dw_studio.core`, bảng tenant đầu tiên của `studio` và route `GET /api/v1/studio/artifacts`, nên seam không vào `main` khi rỗng (ADR-0100 (Accepted), Consequences).

## Việc cần làm

1. `packages/python/dw_studio/`: `pyproject.toml` (distribution `dw-studio`), `src/dw_studio/__init__.py` và gói con `src/dw_studio/core/` với các tầng của `CLAUDE.md` mà tenant-config ticket 02 lấp. Không tạo gói con năng lực rỗng: `records`, `workflows`, `agents`, `tools`, `lifecycle`, `testing` ra đời cùng ticket đầu tiên đặt mã thật vào chúng (`CLAUDE.md` "Work style" mục 6). Mô tả bảng là `sa.MetaData(schema="studio", naming_convention=NAMING_CONVENTION)` trong tầng `adapters` của `dw_studio.core`.
2. Đăng ký `dw_studio` ở mọi chỗ mà kiểm tra của ticket 01 đọc: `[tool.uv.sources]` (`dw-studio = { workspace = true }`), `known-first-party`, `mypy_path`, coverage `source`, `root_packages`, `IMPORT_TO_DIST` (`"dw_studio": "dw-studio"`), dòng `COPY` manifest ở ba Dockerfile Python; khai `dw-studio` trong `apps/api/pyproject.toml` (`CLAUDE.md` bước 8); chạy `uv lock`.
3. Hợp đồng trong `pyproject.toml`: "Platform core does not import Studio" (forbidden; nguồn `dw_kernel`, `dw_platform`, `dw_agent_runtime`, `dw_knowledge`, `dw_memory`, `dw_connectors`, `dw_observability`, `dw_evals`; cấm `dw_studio`); "Studio inner layers never import Studio adapters" (forbidden; nguồn là các tầng `domain`, `application`, `workflows`, `presentation` của `dw_studio.core`; cấm tầng `adapters` của nó); "LangGraph only in Studio compilers" (forbidden; nguồn `dw_studio`; cấm `langgraph`, `langchain`, `langchain_core`; chưa có ngoại lệ vì chưa có trình biên dịch); tầng `domain` của `dw_studio.core` vào `source_modules` của hợp đồng domain. Đo trước xem import-linter 2.15 có nhận `**` trong `source_modules` và `ignore_imports` không: nhận thì viết hợp đồng theo mẫu, không nhận thì liệt kê từng module và để bước 4 canh (failure-modes #4).
4. Mở rộng `check_registration()` của ticket 01: với mỗi gói con trực tiếp của `dw_studio`, tầng `domain` có trong hợp đồng domain; tầng `domain`, `application`, `workflows`, `presentation` có trong nguồn và tầng `adapters` có trong danh sách cấm của hợp đồng adapter; gói con khác `core` và `testing` có trong danh sách cấm của một hợp đồng "Studio core imports no capability" và, từ gói con năng lực thứ hai, trong một hợp đồng `independence`. Thêm ca trồng lỗi vào `scripts/test_verify_architecture.sh`.
5. `apps/api/src/dw_api/bootstrap/studio.py`: `build_studio(container, settings)` trả `StudioContainer` hoặc `None` khi không có cơ sở dữ liệu; gọi trong `build_container` ngay sau dòng gán `container.runtime` và trước seam context; thêm trường `studio` vào `ApiContainer`. Mã của năng lực dựng từ `container.runtime` (`RuntimeSeam`).
6. `apps/api/src/dw_api/main.py`: một `APIRouter(prefix="/studio", tags=["studio"], dependencies=[<dependency xác thực>])` gắn ở `/api/v1` khi `container.studio is not None`, nên mọi route của nhóm, kể cả route `include_in_schema=False`, thừa hưởng xác thực (R6.9), cạnh các router có điều kiện; router của từng năng lực vào nhóm qua `build_studio`. Trần body của cả nhóm đếm byte thực đọc theo luồng, bất kể `Content-Length` khai gì hay có khai không, và dừng ở byte thứ 1048577 với `PayloadTooLargeError`; `Content-Length` khai lớn hơn 1048576 thì từ chối mà không đọc (R6.5, ADR-0108 (Accepted) quyết 3). Xác thực chạy trước khi đọc body, trong một middleware ASGI theo tiền tố `/api/v1/studio/`, gắn cùng nhóm route bởi một hàm `mount_studio(app, container)` chỉ khi `container.studio is not None`, gọi đúng bộ xác minh token mà dependency xác thực của API dùng (một hàm, không viết lại), và dependency cấp nhóm dựng `AccessContext` từ kết quả middleware để lại trong `request.state`, trả 401 khi không thấy kết quả đó: người gọi không mang token đã xác minh nhận 401 mà API không đọc byte nào của body; `Content-Encoding` khác `identity` nhận 415 mà không giải nén (R6.10) (R6.8; Quyết định 27/10/2026, câu 3). Đo trước FastAPI đã đọc body vào bộ nhớ hay chưa khi một dependency chạy (failure-modes #4): đã đọc thì trần là một middleware ASGI bọc `receive` của các đường dưới `/api/v1/studio/`, đặt sau bước xác thực, và kết quả đo ghi vào Comments.
7. Test đơn vị và hợp đồng trong `apps/api/tests/`: lấy mọi đường dưới `/api/v1/studio/` từ `app.openapi()`, không duyệt `app.routes`; gọi không token mỗi đường với method của nó và khẳng định 401; khẳng định có ít nhất một đường; khẳng định mọi operation tag `studio` có tiền tố đó; dựng app không cơ sở dữ liệu thì `GET /api/v1/studio/artifacts` trả 404 và không đường nào trả 500; body 1048577 byte trả 413 `payload_too_large` mà handler giả không được gọi, với `Content-Length` đúng, không `Content-Length` (chunked) và `Content-Length` khai 10 byte, bộ đếm của nguồn body không vượt 1048577 byte; body 1048576 byte qua được trần; body 2 MiB không token trả 401 và bộ đếm của nguồn bằng 0.
8. CI, job `containers`: bước "Smoke: Studio answers 401" sau "Smoke: API health", gọi `curl` không token tới `http://localhost:8000/api/v1/studio/artifacts` và đòi mã 401, rồi gọi `http://localhost:8000/api/v1/studio-missing` và đòi 404.
9. `packages/python/dw_studio/tests/integration/test_metadata_matches_catalog.py`: so mô tả bảng của `dw_studio` với database sau `alembic upgrade head` bằng `compare_metadata` của alembic, lọc schema `studio`, và khẳng định không có khác biệt. Đo trước những gì `compare_metadata` không thấy (policy, quyền theo cột, index một phần) và ghi chúng vào docstring của test.
10. `packages/python/dw_platform/tests/integration/test_rls_coverage.py`: thêm `studio` vào `_PLATFORM_SCHEMAS` trong cùng nhánh với bảng tenant đầu tiên của tenant-config ticket 02; bảng đó là bảng toàn tenant, nên tenant-config ticket 02 thêm dòng của nó vào `_TENANT_WIDE_ON_PURPOSE` của ticket 01 (R9.1).

## Tiêu chí chấp nhận

- [ ] R5.1 (SKEL9): thêm `import dw_studio` vào một module của `dw_platform` trong nhánh thử làm `lint-imports` đỏ với hợp đồng "Platform core does not import Studio"; bỏ dòng đó thì xanh.
- [ ] R5.4 (SKEL10): một module tầng `presentation`, và một module tầng `workflows`, của `dw_studio.core` import tầng `adapters`, mỗi cái làm `lint-imports` đỏ.
- [ ] R5.5 (SKEL10): một module của `dw_studio.core` import `langgraph` làm `lint-imports` đỏ.
- [ ] R5.7 (SKEL11): cây thử có `dw_studio.probe` với tầng `adapters` không có trong hợp đồng adapter làm kiểm tra đăng ký đỏ, nêu `dw_studio.probe` và tên hợp đồng.
- [ ] R6.1 (SKEL12): app có cơ sở dữ liệu: mọi đường dưới `/api/v1/studio/` trong OpenAPI, gọi không token, trả 401; bỏ lời gọi `mount_studio` thì cùng lời gọi trả 404 và test đỏ; app thử gắn nhóm mà không middleware: dependency cấp nhóm trả 401 khi thiếu kết quả xác minh, và đổi nó sang cho qua thì route của nhóm trả 200, test đỏ.
- [ ] R6.9 (SKEL12): route thử `include_in_schema=False` gắn dưới tiền tố ngoài nhóm, không dependency nào, gọi không token trả 401; gỡ middleware thì route thử trả 200 và test đỏ; đường không tồn tại dưới tiền tố, không token, trả 401.
- [ ] R6.2 (SKEL12): test OpenAPI đỏ khi nhóm Studio không có route nào.
- [ ] R6.3: một operation tag `studio` đặt ở `/api/v1/objects` trong app thử làm test đỏ.
- [ ] R6.4 (SKEL23): app dựng không cơ sở dữ liệu trả 404 cho `GET /api/v1/studio/artifacts` và không trả 500 cho đường nào của nhóm; gắn nhóm cả khi `container.studio is None` thì test đỏ.
- [ ] R6.5 (SKEL13): body 1048577 byte, với `Content-Length` đúng, không `Content-Length` và `Content-Length` khai 10 byte, trả 413 `payload_too_large` mà handler giả không chạy và nguồn body không bị đọc quá 1048577 byte; body 1048576 byte tới handler; gỡ trần thì test đỏ.
- [ ] R6.8 (SKEL13): body 2 MiB không token, với token hết hạn, sai chữ ký và sai audience, trả 401 và nguồn body không bị đọc byte nào; đặt trần trước xác thực, hay chuyển xác thực vào dependency với route thử khai tham số body, thì test đỏ; thay bộ xác minh của middleware bằng một bản chỉ kiểm chữ ký thì ca sai audience đỏ.
- [ ] R6.10 (SKEL13): body có token và `Content-Encoding: gzip` trả 415, nguồn body không bị đọc quá 1048577 byte; gỡ phép kiểm thì test đỏ.
- [ ] R6.6: bước smoke của job `containers` nhận 401 từ `/api/v1/studio/artifacts` trên container đã dựng, và 404 từ `/api/v1/studio-missing` ngoài tiền tố; bỏ `mount_studio` thì bước đầu nhận 404 và đỏ.
- [ ] R6.7 (SKEL14): thêm một cột vào bảng `studio` bằng migration thử mà không vào mô tả bảng làm test đối chiếu đỏ.
- [ ] R2.6: khi `_PLATFORM_SCHEMAS` có `studio`, một truy vấn dò bỏ sót `studio` (lọc trong test thử) làm test sàn đỏ.
- [ ] Xong: `make test-architecture test-unit test-contract test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/bootstrap/wiring.py:307`, `apps/api/src/dw_api/bootstrap/wiring.py:332-337`; spec: R6.
- `apps/api/src/dw_api/main.py:129-167`; spec: R6.1, R6.4.
- `apps/api/src/dw_api/routes/v1/zalo.py:155`, `apps/api/src/dw_api/routes/v1/zalo.py:186-192`; spec: R6.5.
- `pyproject.toml:232-234`, `pyproject.toml:278-296`, `pyproject.toml:384-395`; spec: R5.
- `uv.lock:1785-1786`; spec: R5.
- `packages/python/dw_kernel/src/dw_kernel/naming.py:23`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:15`; spec: R6.7.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:61-74`; spec: R2.6.
- `.github/workflows/ci.yml:281-290`; spec: R6.6.
- ADR-0100 (Accepted) điểm 3 và 6.

## Comments

- 2026-10-27 (agent): sửa theo Quyết định 27/10/2026 của spec: R6.1 chỉ trong khi có cơ sở dữ liệu và cho mọi đường của OpenAPI; trần body đếm theo luồng bất kể `Content-Length` (R6.5); người gọi không token nhận 401 trước khi body được đọc (R6.8); thêm SKEL23 cho R6.4.
- 2026-10-27 (agent): sửa theo Quyết định 27/10/2026 của spec sau gate chạy lại trên `fa812f9`: tầng `workflows` trong hợp đồng adapter (R5.4), xác thực là dependency cấp nhóm và route ẩn khỏi OpenAPI cũng nhận 401 (R6.9).
- 2026-10-27 (agent): sửa theo khuyến nghị của gate chạy lại trên `bce52d4` (Đạt ủy quyền 27/10/2026): token chưa xác minh nhận 401 trước khi đọc body (R6.8), body nén nhận 415 (R6.10).
- 2026-10-27 (agent): sửa theo khuyến nghị của gate trên `d9fc4da` (Đạt chọn phương án A): xác thực trước body bằng middleware gọi bộ xác minh token duy nhất của nền tảng (R6.8). Ticket này vào `main` cùng một lần push với tenant-config/02, vì repo làm thẳng trên `main` (ADR-0100 (Accepted) điểm 6).
- 2026-10-27 (agent): sau bước xác nhận trên `e9084eb`: middleware và nhóm gắn bởi `mount_studio` chỉ khi có cơ sở dữ liệu (giữ R6.4), dependency đóng khi thiếu kết quả xác minh, smoke đối chứng ngoài tiền tố (R6.6).
- 2026-10-27 (agent): sau lần xác nhận thứ hai trên `2639c06`: mỗi lớp xác thực một ca trồng lỗi riêng, middleware qua route ngoài nhóm, dependency qua app thử không middleware (R6.1, R6.9).
