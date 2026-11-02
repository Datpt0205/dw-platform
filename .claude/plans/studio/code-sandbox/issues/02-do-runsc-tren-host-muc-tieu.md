# 02 — Đo runsc trên host mục tiêu và chốt ADR-0119 (Proposed)

Status: ready-for-human
Blocked by: 01
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, CS1, CS2

## Mục tiêu

Chạy harness của ticket 01 y nguyên trên host mục tiêu để có cột host của bảng mười mục (R1.1) và các test CS1, CS2 trên chính kernel và hypervisor sẽ chạy mã của công ty (ADR-0119 (Proposed) Open 3, FOG-24); rồi chọn Docker hay Podman rootless, ghi ngân sách hạ tầng (cỡ VM thứ hai, cỡ host chính) và chốt ADR-0119 (Proposed). Việc của người vì host mục tiêu chưa tồn tại: đặt VM cần tài khoản nhà cung cấp và tiền (DO-24, D14), thứ chỉ Đạt có.

## Việc cần làm

1. Người vận hành (Đạt): dựng một VM cùng lớp với VM thứ hai của D14 (Ubuntu 24.04 LTS, cgroup v2, ít nhất 2 vCPU và 4 GB, đặt ở Việt Nam theo ADR-0123 (Accepted) vì nó sẽ chạy mã trên dữ liệu của công ty), không chứa PostgreSQL, Qdrant, kho đối tượng hay bí mật nào (ADR-0119 (Proposed) quyết định 9), và một user `dwsandbox` không phải root có sudo cho lúc dựng; ghi nhà cung cấp, loại máy, kernel và có `/dev/kvm` hay không (mục 10, việc của vận hành).
2. Trên VM, dưới `dwsandbox`: chạy `tests/spike/sandbox/setup_rootless.sh` của ticket 01, rồi lệnh Xong; giữ `results-host.json`. Không sửa harness hay ngưỡng của ticket 01 trên host; một ngưỡng sai thì sửa ở ticket 01 bằng một commit mới.
3. Agent: điền cột host của mục `## Measurements (code-sandbox 01, 02)` trong ADR-0119 (Proposed) từ `results-host.json`; trần nào không được tôn trọng ghi là điều kiện chặn bước mã (R1.2). Nếu Docker rootless trượt một trần mà Podman rootless đạt, thêm Podman vào `setup_rootless.sh` (ticket mới), chạy lại và chọn Podman; không thì chọn Docker. Ghi lựa chọn và cỡ VM thứ hai, cỡ host chính vào mục Quyết định của `spec.md` và vào ADR-0119 (Proposed) Open 2.
4. Agent: khi mọi trần đạt, chuyển ADR-0119 (Proposed) sang Accepted (theo ủy quyền 31/10/2026, ghi ở mục Review của ADR), chuyển quyết định 10 sang Open W3 theo Quyết định 23/10/2026 của spec, và thêm runsc vào "Required stack" của `CLAUDE.md` (sửa đổi A10); khi rootless trượt, ghi phương án dự phòng của quyết định 2 (daemon rootful với `runsc-dw`, socket chỉ ở runner) cùng rủi ro còn lại vào ADR, và giữ Proposed.

## Tiêu chí chấp nhận

- [ ] R1.1: `results-host.json` có đủ mười hàng, mỗi hàng một trạng thái, và cột host của ADR-0119 (Proposed) khớp với nó; sai nếu thiếu một hàng.
- [ ] R1.2 (CS1): trên host, test CPU, test bộ nhớ và test pids xanh với `CAPPED_FLAGS` của ticket 01, hoặc trần không đạt có hàng chặn trong ADR-0119 (Proposed) và ADR vẫn Proposed; sai nếu ADR thành Accepted khi còn một trần không đạt.
- [ ] R1.3 (CS1): trên host, cả 10 lần thăm dò của ticket 01 bước 4 trả `1` trong ≤ 5 s trong lúc bomb chạy; sai nếu một lần quá hạn.
- [ ] R1.4 (CS2): trên host, `HostConfig.Runtime` bằng `runsc-dw` và `dmesg` bên trong có `gVisor`.
- [ ] Xong: `DW_SANDBOX_SPIKE=1 uv run python -m pytest tests/spike/sandbox` xanh.

## Nguồn

- `infra/compose/docker-compose.prod.yml:24`; spec: R1.1, R1.2, R1.3, R1.4, CS1, CS2.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): tách từ ticket 01 theo gate `checking-plan-readiness`: host mục tiêu chưa có, và dựng nó cần tài khoản và tiền của Đạt ("việc cần khóa hay bí mật thật thì bỏ qua"), nên `ready-for-human`. Nếu sai thì: khi Đạt giao một host có sẵn và quyền SSH, agent chạy bước 2-4 và ticket thành `ready-for-agent` sau một lượt gate.
