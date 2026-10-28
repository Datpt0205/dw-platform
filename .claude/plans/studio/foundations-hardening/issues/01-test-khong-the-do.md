# 01 — Test không thể đỏ: walker route và tiến trình nền sandbox

Status: ready-for-agent
Area: studio
Yêu cầu: R1.1, R1.2, FH1

## Mục tiêu

Hai test đang xanh mà không thể đỏ được sửa để đỏ khi điều chúng canh bị gỡ (R1.1, R1.2, FH1). Làm
trước các ticket khác của spec: chúng thêm route và dựa vào walker route, nên walker phải thấy route
trong router được include trước khi có route mới.

## Việc cần làm

1. `apps/api/tests/unit/test_support_routes.py`: `support_routes` duyệt
   `fastapi.routing.iter_route_contexts(app.routes)` như `test_every_platform_route_refuses_a_non_operator`
   đang làm, thay vòng `isinstance(route, APIRoute)` trên `app.routes` (hàm `_calls` giữ nguyên).
2. Cùng tệp, thêm khẳng định sàn để walker không mù trở lại: trên app thật, walker thấy
   `GET /api/v1/runs/{run_id}`; trên một app thử, walker thấy một route nhận
   `RequireAccessContextOrSupport` nằm trong một `APIRouter` được `include_router` với prefix
   `/api/v1` (bổ sung cho `test_the_walker_sees_a_route_that_opts_in`, vốn gắn route thẳng vào app).
3. `apps/docgen/tests/integration/test_sandbox_image.py`, test
   `test_a_backgrounded_command_does_not_outlive_its_session`: thay `pgrep -c -f 'sleep 300' || echo NONE`
   bằng một lệnh `python3 -c` quét `/proc/*/cmdline` và in số tiến trình có `sleep 300`; khẳng định
   số đó bằng 0 sau khi request chạy `sleep 300 &` đã trả lời.
4. Cùng test, thêm đối chứng dương trong cùng phiên: một request chạy `sleep 300 &` rồi quét ngay
   trong cùng lệnh phải in số lớn hơn 0, để bộ quét được chứng minh là thấy tiến trình đang sống.
5. Rà repo tìm mẫu cùng họ và ghi kết quả vào Comments: lệnh test kết thúc bằng `|| echo` rồi khẳng
   định trên chuỗi in ra (`grep -rn "|| echo" apps packages --include=test_*.py`), và vòng duyệt
   `app.routes` lọc `APIRoute` ở cấp đầu (`grep -rn "in app.routes" apps packages --include=*.py`).
   Mỗi chỗ tìm thấy được sửa trong ticket này, hoặc được ghi kèm lý do nó vẫn đỏ được.
6. Nếu test tiến trình nền đã sửa đỏ vì tiến trình thật sự sống sót sau request, ghi vào Comments và
   báo Đạt để mở ticket sửa docgen; ticket này chỉ làm test thấy được lỗi.

## Tiêu chí chấp nhận

- [ ] R1.1 (FH1): thêm `RequireAccessContextOrSupport` vào `GET /api/v1/runs/{run_id}` mà không thêm
      vào `SUPPORT_ALLOWED_ROUTES` → `test_only_the_allowed_routes_take_a_support_context` đỏ; hoàn
      tác → xanh; kết quả ghi Comments. Sai nếu walker vẫn chỉ thấy route gắn thẳng vào app.
- [ ] R1.1: đổi walker về vòng `APIRoute` cũ → khẳng định sàn ở bước 2 đỏ (walker không thấy
      `GET /api/v1/runs/{run_id}`).
- [ ] R1.2 (FH1): chạy khẳng định "không còn tiến trình" trên lần quét trong cùng request với
      `sleep 300 &` → test đỏ; đối chứng dương ở bước 4 thấy tiến trình; kết quả ghi Comments. Sai
      nếu bộ quét in 0 khi tiến trình đang sống.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/tests/unit/test_support_routes.py:44-52`
- `apps/api/tests/unit/test_support_routes.py:65-67`
- `apps/api/src/dw_api/bootstrap/wiring.py:110`
- `apps/api/tests/unit/test_platform_endpoint.py:271`
- `apps/docgen/tests/integration/test_sandbox_image.py:182-191`
- `infra/docker/docgen.Dockerfile:70-76`
- `uv.lock:1283-1284`
- spec: R1, FH1.

## Comments

- 2026-10-23 (agent): Đo ngày 23/10/2026: với `fastapi==0.141.1`, router được include hiện ra ở cấp
  đầu là `_IncludedRouter`, vòng `APIRoute` không thấy route nào, `iter_route_contexts` thấy
  `/api/v1/runs/{run_id}`; `dw-docgen:local` không có `pgrep`.
- 2026-10-28 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-28 (agent): câu hỏi của gate chạm ticket này, đã trả lời bằng đo trên `dw-docgen:local` và FastAPI 0.141.1, cho người làm: (a) `RouteContext.dependant` của `iter_route_contexts` mang cả phụ thuộc gắn ở `include_router(..., dependencies=[...])`, và `path` mang đủ prefix, nên `_calls` giữ nguyên thấy ngữ cảnh support gắn ở cấp router; API không có `app.mount` sub-app nào; (b) hai request của một phiên docgen dùng chung một PID namespace (`readlink /proc/self/ns/pid` như nhau), nên lần quét ở request sau thấy được tiến trình của request trước, và đối chứng dương trong cùng request thấy 1; (c) R1.2 nói "sau khi request khởi chạy nó đã được trả lời", không phải khi phiên đóng; đo hôm nay: 0 tiến trình ở request sau, nên test đã sửa xanh thật và bước 6 không xảy ra; (d) `pgrep` không có trong image, xác nhận test cũ luôn xanh.
- 2026-10-28 (Đạt): Bước 5 tìm thêm một test cùng họ không thấy điều nó canh: `test_one_session_cannot_reach_another` chỉ `ls secret.txt` trong thư mục của chính phiên, còn đo qua gateway cho thấy shell của một phiên đọc được `../<phiên khác>/secret.txt` (`/work` chung, cùng uid `dw`), mà tên phiên mang tenant (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sandbox.py:155`). Đạt chọn: ticket này thêm ca đó vào test, đánh `xfail(strict=True)` kèm lý do trỏ tới ticket sửa docgen, và push như thường; ticket sửa docgen mở riêng.
