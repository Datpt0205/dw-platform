# 01 — Spike: runsc systrap dưới engine rootless trên máy chủ và trên runner CI

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, CS1, CS2

## Mục tiêu

Đo được rằng runsc trên systrap dưới một engine rootless tôn trọng trần CPU, bộ nhớ và pids trên host mục tiêu, và chạy được một container `runsc-dw` không mạng trên runner CI, để chốt ADR-0119 (Proposed) và ngân sách hạ tầng. Chứng minh R1 và cài CS1, CS2. Spike chạy trên một nhánh thử, không tạo bảng, route hay migration nào.

## Việc cần làm

1. Trên host mục tiêu, dựng một engine rootless (Docker hoặc Podman) với cgroup v2 ủy quyền và runtime `runsc-dw` (gVisor trên systrap, `--network=none`); đo mười mục của nghiên cứu: ủy quyền cgroup v2, fork bomb dưới runsc, `docker stats` và `memory.peak`, `--log-driver none` với stdin, tmpfs `noexec`, độ trễ lạnh và ấm, pandas dưới gVisor, reaper sau `kill -9`, engine rootless chung máy với daemon rootful, và kiểm `/dev/kvm` là việc của vận hành.
2. Chạy một fork bomb và một memory bomb trong một container `runsc-dw` có trần, đo host vẫn phục vụ các lượt khác; lặp lại sau khi gỡ trần pids để thấy bomb thoát.
3. Trên runner CI Ubuntu, cài gVisor và chạy một container `runsc-dw` không mạng; nếu không chạy được, ghi phương án runner tự host.
4. Ghi bảng số đo và quyết định Docker hay Podman rootless vào mục Quyết định của `spec.md`; đánh dấu trần nào không được tôn trọng (nếu có) là điều kiện chặn bước mã.

## Tiêu chí chấp nhận

- [ ] R1.1: bảng số đo mười mục có trong tài liệu quyết định của spike; sai nếu thiếu một mục.
- [ ] R1.2 (CS1): khi một trần không được tôn trọng, kết quả spike đánh dấu chặn bước mã; gỡ trần pids làm fork bomb thoát khỏi container → test đỏ.
- [ ] R1.3 (CS1): fork bomb và memory bomb trong container `runsc-dw` có trần không làm host ngừng phục vụ các lượt khác; sai nếu host treo.
- [ ] R1.4 (CS2): `HostConfig.Runtime` của container đo bằng `runsc-dw`; chạy cùng script bằng `runc` cho hành vi khác → test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/spike -k sandbox` xanh.

## Nguồn

- `apps/docgen/src/dw_docgen/settings.py:38`; `infra/compose/docker-compose.yml:355-382`; `apps/docgen/tests/integration/test_sandbox_image.py:189`; `infra/compose/docker-compose.prod.yml:24`; spec: R1.1, R1.2, R1.3, R1.4, CS1, CS2.

## Comments
