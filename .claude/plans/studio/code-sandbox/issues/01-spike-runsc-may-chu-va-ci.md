# 01 — Spike: runsc systrap dưới engine rootless trên máy chủ và trên runner CI

Status: ready-for-agent
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, CS1, CS2

## Mục tiêu

Dựng harness đo runsc trên systrap dưới Docker rootless và chạy nó trên runner CI Ubuntu, để có cột CI của bảng số đo mười mục (R1.1), các test của CS1 và CS2 đã thấy đỏ khi gỡ guard, và một script dựng host mà ticket 02 chạy y nguyên trên host mục tiêu. Cột host, lựa chọn Docker hay Podman, ngân sách hạ tầng và việc chốt ADR-0119 (Proposed) là ticket 02. Spike làm trên `main` như mọi ticket (`.claude/rules/wave-close.md`), không tạo bảng, route hay migration nào và không thêm workspace member: `apps/sandbox-runner` là W2 (ADR-0119 (Proposed) quyết định 1).

## Việc cần làm

1. Thư mục `tests/spike/sandbox/` (ngoài `testpaths` của `pyproject.toml:193`, nên `pytest` mặc định không gom nó; chỉ chạy khi gọi đích danh):
    - `setup_rootless.sh`: dựng Docker rootless cho user hiện tại (`dockerd-rootless-setuptool.sh` của `docker-ce-rootless-extras`, linger, drop-in systemd `Delegate=cpu cpuset io memory pids` cho `user@.service`), tải runsc bản phát hành ghim theo ngày bằng `curl --fail` và kiểm `sha512sum -c` với `runsc.sha512` của đúng bản đó, rồi đăng ký runtime `runsc-dw` trong `~/.config/docker/daemon.json` với `runtimeArgs` `--platform=systrap` và `--network=none`. Không dùng đường `latest` nào (CLAUDE.md "Required stack": "never `latest`"); bản runsc, digest ảnh và bản pandas ghi ở đầu script và vào bảng số đo. Script là chủ duy nhất của cách dựng: CI và ticket 02 cùng gọi nó.
    - `harness.py`: gọi Docker CLI qua `subprocess` (không Docker SDK). Mọi container đo dùng ảnh `python:3.12-slim@sha256:<digest>` cộng pandas ghim `==`, dựng một lần trong bước dựng; cờ trần nằm trong một tuple `CAPPED_FLAGS` theo hồ sơ `py-small` của ADR-0119 (Proposed) quyết định 3: `--runtime=runsc-dw`, `--network=none`, `--cpus=0.5`, `--memory=256m`, `--memory-swap=256m`, `--pids-limit=64`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--user 10001`, tmpfs `/work` và `/tmp` `noexec,nosuid,nodev`, nhãn `dw.spike=1`. Mỗi container được xóa sau lượt đo.
    - `test_runsc_spike.py` cho R1.2-R1.4, và một lệnh ghi bảng mười mục ra `results-<nơi chạy>.json`.
    - `conftest.py`: khi `DW_SANDBOX_SPIKE=1` mà engine không có runtime `runsc-dw`, mọi test ĐỎ (không skip); thiếu biến đó thì skip. Như thế lệnh Xong không thể xanh trên một máy không có runsc (`failure-modes.md` #3).
2. Mười mục của R1.1, mỗi mục một hàng với số đo, đơn vị và `đạt`, `không đạt` hay `không áp dụng` kèm lý do:
    1. ủy quyền cgroup v2: `cgroup.controllers` của `user@<uid>.service` chứa `cpu cpuset io memory pids`;
    2. fork bomb dưới runsc (xem CS1 ở bước 3);
    3. `docker stats` cạnh `memory.peak` và `cpu.stat` `usage_usec` đọc từ cgroup của container sau khung kết quả và trước khi xóa;
    4. `--log-driver none` với stdin: một payload 1 MiB qua `docker run -i` quay về nguyên vẹn trên stdout;
    5. tmpfs `noexec`: chạy một tệp vừa ghi vào `/work` bị từ chối;
    6. độ trễ lạnh (20 lần `docker run --rm ... true`) và ấm (20 lần ghi stdin vào một container đã khởi động sẵn đang chờ stdin), P50 và P95 tính bằng ms;
    7. pandas dưới gVisor: `import pandas` và `describe()` trên 100 000 dòng xong dưới trần `py-small`, ghi thời gian;
    8. reaper sau `kill -9`: giết harness đang giữ ba container, rồi `docker rm -f` theo nhãn `dw.spike=1` xóa hết và trên host không còn tiến trình `runsc` nào sau 10 s;
    9. engine rootless chung máy với daemon rootful của runner: cả hai chạy container cùng lúc, và socket rootless không do root sở hữu;
    10. `/dev/kvm`: ghi có hay không; trên host mục tiêu đây là việc của vận hành (ticket 02).
3. CS1: một trần được tôn trọng khi, với `CAPPED_FLAGS`: CPU, vòng lặp bận hai tiến trình trong 10 s cho `usage_usec` chia thời gian thực ≤ 0,55 vCPU; bộ nhớ, cấp phát 512 MiB theo bước 16 MiB kết thúc bằng `OOMKilled: true` hoặc mã thoát 137 trong 30 s và `memory.peak` ≤ 268 435 456 byte × 1,05; pids, fork bomb trong 10 s có số tiến trình đếm từ `/proc` bên trong container (như `apps/docgen/tests/integration/test_sandbox_image.py:55`) không lần nào quá 64 khi lấy mẫu mỗi 0,5 s, và `pids.peak` của cgroup trên host được ghi riêng vì tiến trình khách của gVisor không phải tiến trình host. Trần nào không được tôn trọng: test của nó mang `pytest.mark.xfail(strict=True, reason=...)` dẫn tới hàng chặn trong ADR-0119 (Proposed) theo R1.2, không bị xóa hay nới.
4. R1.3: trong lúc fork bomb và memory bomb chạy, harness khởi một container `runsc-dw` thứ hai chạy `python -c "print(1)"` mỗi giây, 10 lần; mỗi lần trả `1` trong ≤ 5 s, và `docker info` trả lời trong ≤ 2 s sau khi container bomb bị xóa.
5. CS2: `HostConfig.Runtime` từ `docker inspect` bằng `runsc-dw` VÀ `dmesg` bên trong container có chữ `gVisor`, vì `HostConfig.Runtime` chỉ nhắc lại runtime mà chính harness yêu cầu (`failure-modes.md` #0).
6. Job CI mới `sandbox-spike` trong `.github/workflows/ci.yml` (cạnh job `integration`, `.github/workflows/ci.yml:215`), `runs-on: ubuntu-24.04`, `needs: [contracts]`, chạy trên mỗi lần push: gọi `setup_rootless.sh`, chạy lệnh Xong với `DW_SANDBOX_SPIKE=1` dưới user của runner, và tải `results-ci.json` lên làm artifact. Nếu runsc không chạy được trên runner GitHub, job đỏ, và bảng ghi lỗi đó cùng đề xuất runner tự host cho ticket 02.
7. Viết `.claude/plans/studio/code-sandbox/mutations/01.yaml`, mỗi kiểm soát một mutation: bỏ `--pids-limit=64` khỏi `CAPPED_FLAGS` (CS1, test pids đỏ), bỏ `--memory=256m` và `--memory-swap=256m` (CS1, test bộ nhớ đỏ), đổi `--runtime=runsc-dw` thành `--runtime=runc` (CS2, test `dmesg` đỏ). Chạy chúng ở lúc đóng hàng đợi (`wave-close.md`).
8. Thêm mục `## Measurements (code-sandbox 01, 02)` vào `docs/adr/0119-each-code-execution-gets-a-fresh-gvisor-container.md` với bảng mười hàng, cột CI điền từ `results-ci.json`, cột host để trống cho ticket 02; trần nào không được tôn trọng ghi là điều kiện chặn bước mã (R1.2). ADR vẫn Proposed.
9. Máy dev Windows (Docker Desktop, daemon rootful trong VM `docker-desktop`) không cài được runtime vào engine đó: ở đây chỉ chạy lint và thấy lệnh Xong đỏ khi có `DW_SANDBOX_SPIKE=1` và skip khi không. Số đo chỉ lấy từ CI (ticket này) và host mục tiêu (ticket 02).

## Tiêu chí chấp nhận

- [ ] R1.1: `results-ci.json` của một lần chạy job `sandbox-spike` có đủ mười hàng của bước 2, mỗi hàng một trạng thái, và cột CI của ADR-0119 (Proposed) khớp với nó; sai nếu thiếu một hàng hay một hàng không có trạng thái.
- [ ] R1.2 (CS1): test CPU, test bộ nhớ và test pids xanh với `CAPPED_FLAGS`, và đỏ khi bỏ cờ trần tương ứng; một trần không đạt ngưỡng của bước 3 có hàng chặn trong ADR-0119 (Proposed) và test `xfail(strict=True)` của nó; sai nếu một trần không đạt mà không có hàng chặn.
- [ ] R1.3 (CS1): cả 10 lần thăm dò của bước 4 trả `1` trong ≤ 5 s trong lúc bomb chạy; sai nếu một lần quá hạn.
- [ ] R1.4 (CS2): `HostConfig.Runtime` bằng `runsc-dw` và `dmesg` bên trong có `gVisor`; cùng test với `--runtime=runc` đỏ.
- [ ] Xong: `DW_SANDBOX_SPIKE=1 uv run python -m pytest tests/spike/sandbox` xanh.

## Nguồn

- `apps/docgen/src/dw_docgen/settings.py:38`; `infra/compose/docker-compose.yml:355-382`; `apps/docgen/tests/integration/test_sandbox_image.py:189`; `infra/compose/docker-compose.prod.yml:24`; `.github/workflows/ci.yml:215`; `pyproject.toml:193`; spec: R1.1, R1.2, R1.3, R1.4, CS1, CS2.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check, không có migration hay route mới) sửa tám HIGH: (1) lệnh Xong trỏ `packages/python/dw_studio/tests/spike` và Trong phạm vi trỏ `apps/sandbox-runner`, cả hai không tồn tại, còn test skip khi thiếu runsc thì xanh trên mọi máy: harness và test ở `tests/spike/sandbox/`, `DW_SANDBOX_SPIKE=1` biến thiếu runtime thành đỏ, lệnh theo dạng `uv run python -m pytest`; (2) host mục tiêu chưa có (VM thứ hai chưa đặt mua, DO-24, R2.2): tách phần host sang ticket 02 `ready-for-human`, ticket này là CI và harness; (3) "tôn trọng trần" không có ngưỡng và pids của gVisor không thấy ở cgroup host: ngưỡng ở bước 3, đếm pids bên trong khách; (4) "host vẫn phục vụ" không đo được: thăm dò ở bước 4; (5) `HostConfig.Runtime` không thể đỏ vì chỉ nhắc lại yêu cầu: thêm `dmesg` có `gVisor`; (6) không nói ghim bản: runsc theo ngày với `sha512`, ảnh theo digest, pandas `==`, `curl --fail`; (7) "nhánh thử" trái `wave-close.md`: làm trên `main`; (8) bảng số đo ở spec Quyết định trái spec Trong phạm vi: một chủ là ADR-0119 (Proposed), mục Measurements. Nếu sai thì: (2) gộp 02 lại khi đã có host, (3) đổi ngưỡng ở bước 3 và ghi lý do cạnh số đo, các mục khác sửa ở bước tương ứng.
- 2026-11-02 (agent, tạm theo ủy quyền 31/10/2026): Docker rootless cho cột CI (ADR-0119 (Proposed) quyết định 1 cho phép Docker hay Podman); job `sandbox-spike` chạy mỗi lần push để thấy nó chạy thật (`failure-modes.md` #1). Nếu sai thì: thêm Podman rootless vào `setup_rootless.sh` và một cột, hoặc chuyển job sang `workflow_dispatch` khi W2 thay nó bằng `sandbox-hostile`.
- 2026-11-02 (agent): MEDIUM để lại, không sửa: neo Hiện trạng của spec đã trôi (`settings.py:38` giờ là chú thích trên `max_concurrency` ở dòng 43 và docgen đã có pool uid theo phiên, ADR 0025; khối docgen ở `docker-compose.yml:367-425`; `test_sandbox_image.py:189` không còn dùng `pgrep`, dòng 55 đếm từ `/proc`); mục 8 và 9 của bảng là định nghĩa của ticket này, chưa có trong spec; không nói gì xóa engine rootless và runsc trên host sau spike (ticket 02 giữ chúng làm nền cho W2); `ubuntu-latest` ở các job khác của `ci.yml`; khi ADR-0119 (Proposed) Accepted thì "Required stack" của `CLAUDE.md` cần thêm runsc (sửa đổi A10).
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
