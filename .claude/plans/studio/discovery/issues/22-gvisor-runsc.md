# 22 — runsc systrap trên host thứ hai và trên runner CI

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-24 `gvisor`

## Câu hỏi

1. gVisor `runsc` ở chế độ systrap có chạy trên kernel và hypervisor của host thứ hai đã chọn không; host đó có
   `/dev/kvm` không?
2. Dưới engine rootless với cgroup v2 được ủy quyền, `--cpus`, `--memory` và `--pids-limit` có được tôn trọng không?
3. `docker stats` và `memory.peak` (nguồn của `sandbox_cpu_seconds`) có số trước khi container bị xóa không?
4. Runner CI có chạy được `runsc` không, để bộ script tấn công chạy trong CI?

## Vì sao

Cách ly của D7 và bộ script tấn công chỉ thật khi đo trên `runsc`, không âm thầm trên `runc`. Môi trường chạy mã hiện có
của docgen là một container, một uid, tmpfs dùng chung và `max_concurrency` bằng 1
(`apps/docgen/src/dw_docgen/settings.py:41`); D7 không chấp nhận nó cho bước mã.

## Mở khóa

- Spec: `code-sandbox` (01), `usage-and-limits` (đo phí lần chạy mã), `workflow-nodes` (bước mã Python, W2).
- ADR: 0119 (đang viết).
- DO: DO-24 (D14: VM riêng cho `sandbox-runner` trước khi mã tenant chạy ở uat hay production), DO-45 (agent, tạm: chỉ
  Python 3.12; mỗi phiên agent một container; tính phí theo vCPU và GB đặt trước nhân thời gian).
- Ticket W1: `code-sandbox/01` (P0) là phép đo này.

## Dựng tối thiểu

Một VM ứng viên cho host thứ hai với Docker rootless, cgroup v2 ủy quyền và `runsc` systrap; một container Python 3.12
không mạng chạy bộ script tấn công (fork bomb, cấp phát bộ nhớ, ghi đĩa, vòng lặp vô hạn); cùng bộ đó trên một runner CI.

## Phép đo quyết định

| Đo                                          | Ngưỡng                                                         | Quyết định                                   |
| ------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------- |
| Runtime thật của container                  | `runsc`, kiểm từ trong container; test đỏ khi chạy trên `runc` | Host thứ hai dùng được không                 |
| Trần CPU, bộ nhớ, pids, đĩa, thời gian      | Mỗi trần chặn đúng script tương ứng                            | Cấu hình chạy mã                             |
| `memory.peak`, `docker stats` trước khi xóa | Có số                                                          | Cách đo phí của `usage-and-limits`           |
| Thời gian khởi động một container           | Chưa có ngưỡng; ghi p95                                        | Chi phí mỗi phiên (DO-45)                    |
| `runsc` trên runner CI                      | Chạy hay không                                                 | Bộ test tấn công chạy trong CI hay trên host |

## Nguồn

- Brief B1, B9, B10b.
- [research.md](../research.md) mục 10 (host có `/dev/kvm` không, engine rootless, `runsc` với cgroup rootless: chưa
  kiểm).

## Comments
