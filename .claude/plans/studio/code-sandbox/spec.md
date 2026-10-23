# Mỗi lần chạy mã một container gVisor mới

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mã do công ty viết phải chạy cách ly ở mức nhân, mỗi lần một container mới; nhưng điều đó chỉ đứng vững nếu runsc dưới một engine rootless thật sự tôn trọng trần tài nguyên trên host và chạy được trên runner CI. W1 chỉ là spike đo hai điều đó và chốt ADR-0119 (Proposed) cùng ngân sách hạ tầng; không lát nào chạy mã của công ty ở W1. Ảnh, runner, bộ script thù địch, `CodeExecutionService` và máy thứ hai là W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Sandbox duy nhất hôm nay là `apps/docgen`: một container sống lâu, một uid, `max_concurrency = 1`, cô lập phiên bằng kiểm đường dẫn chứ không phải ranh giới nhân (`apps/docgen/src/dw_docgen/settings.py:38`). Ràng buộc: không dùng được cho mã của công ty (D7).
- Phần làm cứng của docgen là mẫu đáng giữ: mạng `dw-sandbox`, `read_only`, `cap_drop: [ALL]`, `mem_limit`, `pids_limit`, `init` (`infra/compose/docker-compose.yml:355-382`). Ràng buộc: giữ làm mẫu cho ảnh mã.
- `DocgenSandbox` audit `sandbox.execute` với `policy_decision="no_policy"` và chỉ được dựng bởi test (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sandbox.py:55`). Thiếu: chưa có `CodeExecutionService` hay port cho mã của công ty.
- Một test tích hợp của docgen không thể đỏ: `pgrep` vắng khỏi ảnh nên khẳng định tiến trình còn sống luôn đúng (`apps/docgen/tests/integration/test_sandbox_image.py:189`). Ràng buộc: bộ script thù địch phải có bản chứng minh đỏ khi gỡ guard (`failure-modes.md` #0, #3).
- Overlay production ghi cỡ cho một hộp 2 vCPU và khoảng 8 GB (`infra/compose/docker-compose.prod.yml:24`). Ràng buộc: cần một máy thứ hai trước khi chạy mã của công ty (D14).
- `net_guard` từ chối địa chỉ riêng, loopback và link-local sau một lần phân giải DNS, và hôm nay chỉ gác URL model (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:21-46`). Ràng buộc: container mã phải không có mạng, không chỉ dựa một lớp phân giải.

## Mục tiêu

### R1 — Spike đo runsc dưới engine rootless và chốt ADR cùng ngân sách

Spike đo trên host mục tiêu và runner CI rằng runsc trên systrap dưới engine rootless tôn trọng trần tài nguyên, rồi chốt ADR-0119 (Proposed) và ngân sách hạ tầng (D7, D14, YC69).

- R1.1 KHI spike chạy trên host mục tiêu và trên runner CI, spike PHẢI ghi bảng số đo mười mục nghiên cứu vào tài liệu quyết định của spike.
- R1.2 NẾU runsc dưới engine rootless không tôn trọng trần CPU, bộ nhớ hay pids, THÌ kết quả spike PHẢI chặn bước mã và không ship khi chưa đo.
- R1.3 KHI spike chạy một script thù địch là fork bomb hoặc memory bomb trong một container `runsc-dw`, host PHẢI tiếp tục phục vụ các lượt khác.
- R1.4 KHI spike tạo một container đo, runtime của container PHẢI là `runsc-dw`, không phải `runc`.

### R2 — Hợp đồng cô lập v1 cho mã của công ty

Mỗi lần chạy mã dùng một container mới dùng một lần, không mạng, không bí mật, có trần tài nguyên, trên một máy riêng, chỉ sau quyền và quyền lợi gói (YC69, ADR-0119 (Proposed)). Toàn bộ R2 là W2 và liệt kê ở Ngoài phạm vi.

- R2.1 Mỗi lần chạy mã của công ty PHẢI dùng một container mới dùng một lần, không mạng, không bí mật, có trần CPU, bộ nhớ, pids, đĩa, thời gian và đầu ra.
- R2.2 TRONG KHI `settings.is_deployed`, bước mã PHẢI chạy trên một máy riêng không chứa dữ liệu nền tảng.
- R2.3 NẾU gói của công ty không có quyền lợi `code_node`, hoặc người gọi thiếu `studio.code.author`, THÌ bước mã PHẢI trả 403 trước khi gọi runner.
- R2.4 Bộ script thù địch PHẢI đạt 100% ở cổng phát hành trước khi runner hoặc một ảnh mã được phát hành.

## Trong phạm vi

- Spike host: `apps/sandbox-runner` harness thử đo runsc trên systrap dưới Docker hoặc Podman rootless với cgroup v2 ủy quyền (khởi động lạnh và ấm, `memory.peak`, fork bomb, tmpfs `noexec`, pandas, reaper sau `kill -9`, engine rootless chung máy với daemon rootful).
- Spike CI: chạy một container `runsc-dw` không mạng trên runner Ubuntu.
- Tài liệu quyết định của spike: bảng số đo, lựa chọn Docker hay Podman rootless, và ngân sách hạ tầng vào ADR-0119 (Proposed).

## Ngoài phạm vi

| Việc                                                                                                                         | Vì sao                                                                                                                                                  | Chủ                                   |
| ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| R2.1: ảnh `dw-code-python`, harness, container mới dùng một lần, không mạng, không bí mật, trần tài nguyên                   | Dựng cùng runner sau khi spike chốt                                                                                                                     | đợt sau (W2)                          |
| R2.4: bộ script thù địch 100% ở cổng phát hành, service `sandbox-runner`, job CI `sandbox-hostile`                           | Dựng sau ảnh                                                                                                                                            | đợt sau (W2)                          |
| R2.3: `CodeExecutionService`, `CodeSandboxPort`, quyền lợi `code_node`, quyền `studio.code.author`, hạn mức, đo usage, audit | Dựng sau runner                                                                                                                                         | đợt sau (W2)                          |
| R2.2: hạ tầng engine rootless, slice `dw-sandbox.slice`, VM thứ hai khi `settings.is_deployed`                               | Đặt mua VM mất thời gian                                                                                                                                | đợt sau (W2), đặt mua ready-for-human |
| Container theo phiên agent cho công cụ mã của agent; backend Kubernetes với RuntimeClass `gvisor`; kill dừng container       | Ngoài v1: v1 mỗi lần chạy mã một container mới (D7); vòng đời container theo phiên agent quyết ở W3 (DO-45.2)                                           | đợt sau (W3)                          |
| Loại công cụ `code`                                                                                                          | Công cụ là dữ liệu tenant qua một executor                                                                                                              | tools-and-skills                      |
| Node mã trong quy trình                                                                                                      | Node gọi `CodeSandboxPort` qua `CodeExecutionService`                                                                                                   | workflow-nodes                        |
| Sổ usage, lease, `SandboxUsagePort`                                                                                          | Hạn mức và đo; đơn vị tính tiền là vCPU và GB đặt trước theo Cấu hình chạy mã nhân thời gian chạy, CPU đo từ cgroup chỉ để phát hiện lạm dụng (DO-45.1) | usage-and-limits                      |
| Lối ra mạng cho mã                                                                                                           | Cần proxy và duyệt                                                                                                                                      | đợt sau (W2)                          |

## Kiểm soát

| #   | Kiểm soát                                            | Yêu cầu    | Test âm                                                                                                                        |
| --- | ---------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------ |
| CS1 | runsc dưới engine rootless tôn trọng trần tài nguyên | R1.2, R1.3 | fork bomb và memory bomb trong container `runsc-dw` → host phục vụ, container bị trần chặn; gỡ trần pids → bomb thoát, test đỏ |
| CS2 | Runtime là `runsc-dw`, không phải `runc`             | R1.4       | đọc `HostConfig.Runtime` của container đo bằng `runsc-dw`; chạy cùng script bằng `runc` → hành vi khác, test đỏ                |

## Tiêu chí xong

- Bảng số đo mười mục của R1.1 trên host mục tiêu và trên runner CI có trong tài liệu quyết định của spike; mọi tiêu chí R1 có test; CS1, CS2 có test âm đã thấy đỏ khi gỡ guard (ghi ở Comments của ticket 01).
- ADR-0119 (Proposed) và ngân sách hạ tầng (VM thứ hai, cỡ host) được chốt theo số đo; trần nào không được tôn trọng thì ghi là điều kiện chặn bước mã (R1.2).
- `uv run pytest packages/python/dw_studio/tests/spike -k sandbox` xanh.
- Tiêu chí W2 (bộ script thù địch đạt 100% ở cổng phát hành, job `sandbox-hostile`, `/health` của runner trên VM báo `rootless: true` và `runtime: runsc-dw`) thuộc R2 ở Ngoài phạm vi và không chặn việc đóng spec này ở W1.

## Phụ thuộc

- `studio-skeleton`: seam hạ tầng compose và danh sách mạng cho một service mới.
- Seam do bên khác dựng, tham chiếu bằng slug: `usage-and-limits` (`SandboxUsagePort` ghi sự kiện `sandbox_exec` mang Cấu hình chạy mã và thời gian chạy, một đơn vị cho cả hạn mức và hóa đơn là vCPU và GB đặt trước nhân thời gian (DO-45.1), cộng CPU đo từ cgroup để phát hiện lạm dụng; lease và giới hạn chạy đồng thời trong `platform.plan_limits`).
- Kiểm lại khi: DO-24/D14 chốt máy thứ hai và cỡ host → R2.2; kết quả spike F1, F3, F4 → R1, ADR-0119 (Proposed); người đặt yêu cầu quyết vòng đời container theo phiên agent ở W3 → Ngoài phạm vi.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (agent, tạm theo D14): một VM riêng cho `sandbox-runner` trước khi chạy mã của công ty ở môi trường triển khai (DO-24, O11, `settings.is_deployed`), đo cỡ trước. Sửa: R2.2. Nếu sai thì: nếu dùng chung host với engine rootless, bỏ R2.2.
- 23/10/2026 (agent, tạm): Python 3.12, bộ gói dữ liệu tối thiểu thêm bằng phiên bản ảnh mới, không JavaScript, không chạy skill script ở v1; đơn vị tính tiền là vCPU và GB giữ trước nhân thời gian treo (DO-45 khuyến nghị a). Vế "một container mỗi phiên agent, hủy lúc hết lượt chạy hoặc sau 15 phút rảnh hoặc 2 giờ" đã bỏ theo DO-45.2 ngày 23/10/2026 bên dưới. Sửa: Ngoài phạm vi. Nếu sai thì: theo ghi chú DO-45.
- 23/10/2026 (agent, tạm): bộ script thù địch phải đạt 100% ở cổng phát hành với mỗi test kèm bản chứng minh đỏ khi gỡ guard (`failure-modes.md` #0, #3). Sửa: R1.2, R2.4. Nếu sai thì: giữ nguyên.
- 23/10/2026 (Đạt): DO-45.1 theo (a): chỉ Python 3.12, không JavaScript, không script của kỹ năng; tính tiền theo vCPU và GB đặt trước nhân thời gian, vì container giữ một chỗ trong pool suốt lúc chạy; CPU đo được để phát hiện lạm dụng; sự kiện usage mang Cấu hình chạy mã và thời gian chạy. Sửa: Ngoài phạm vi, Phụ thuộc.
- 23/10/2026 (Đạt): DO-45.2 theo (A): v1 mỗi lần chạy mã một container mới (D7); container theo phiên agent chỉ ở W3 và quyết lúc đó. Sửa: dòng tạm DO-45 cùng ngày (bỏ vế container theo phiên agent), Ngoài phạm vi, Phụ thuộc.
- 23/10/2026 (Đạt): Tiêu chí xong của W1 theo (a): viết lại theo R1 (bảng số đo, CS1, CS2 thấy đỏ, ADR-0119 (Proposed) và ngân sách hạ tầng chốt); phần còn lại là tiêu chí W2 của R2, không đổi phạm vi. Sửa: Tiêu chí xong.
- 23/10/2026 (Đạt): ADR-0119 (Proposed) giữ Proposed tới khi ticket 01 báo số; khi chấp nhận, quyết 10 chuyển sang Open W3. Spec giữ trích dẫn ADR-0119 (Proposed).

## Danh sách ticket

| #   | Ticket                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------ |
| 01  | [Spike: runsc systrap dưới engine rootless trên máy chủ và trên runner CI](issues/01-spike-runsc-may-chu-va-ci.md) |
