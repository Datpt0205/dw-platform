# Bản đồ khám phá Studio

**Đích:** requirements.md được duyệt, bộ ADR 0100-0127 được Đạt xem, và W1 sẵn sàng cắt ticket.

Area: studio · Viết: 23/10/2026

Bản đồ wayfinder cho phần Studio còn chưa biết. Blueprint gom 80 ticket khám phá `FOG-NN` từ mục fog của 15 brief, và
Đạt thêm hai mục ngày 24/10/2026 (FOG-81 theo N10, FOG-82 theo N8); ở đây chúng thành 30 ticket con trong `issues/` và
5 mục còn ở mục Fog cuối file. Id `FOG-NN` giữ nguyên vì [research.md](research.md),
[teardown-chang.md](teardown-chang.md) và các ADR 01NN đã trích chúng. `requirements.md` nằm ở
`.claude/plans/studio/requirements.md`; ADR ở `docs/adr/01NN-*.md`. Đạt chấp nhận mọi ADR 0100-0125 ngày 23/10/2026,
trừ 0119 giữ Proposed tới khi `code-sandbox/01` báo số, và 0126, 0127 ngày 24/10/2026.

## Notes

### Cách đi bản đồ

Theo mục "Wayfinding operations" của `docs/agents/issue-tracker.md`:

- **Frontier:** theo thứ tự chạy ở mục "Thứ tự"; trong cùng một nhóm, ticket trong `issues/` còn mở, không bị chặn, chưa
  ai nhận, số nhỏ nhất thắng. Chưa ticket nào có dòng `Blocked by:`; thứ tự bên trong một ticket ghi ở thân ticket.
- **Nhận:** đặt `Status: claimed` và lưu trước khi làm.
- **Xong:** thêm `## Answer` (kết luận; số đo kèm phiên bản và máy đo; nguồn kèm loại và ngày), đặt `Status: resolved`,
  rồi thêm một dòng (ý chính và link) vào "Trả lời từ ticket" dưới Decisions so far.
- Câu trả lời đổi một ADR thì sửa mục Open của ADR đó trong cùng lần. Câu trả lời chạm một DO thì ghi ở ticket; DO do
  người blueprint ghi tên chốt (Đạt, bên yêu cầu hay luật sư), không do người làm ticket.

### Thứ tự

Số nhỏ là hệ quả lớn. 01 là chang.fpt.net (D10). 02-04 có thời gian chờ dài: khách thí điểm, tình trạng luật, duyệt
ứng dụng của nhà cung cấp (thời gian duyệt là đường găng thật của W2). 05-10 nằm trên thân chung của đường găng,
`studio-skeleton/01` tới `custom-objects/04`, hoặc trả lời DO-12 trước W1. 11-12 là sàn gửi tin và phê duyệt của lát
thí điểm. 13-25 là công cụ, runtime, model, hạ tầng và các spike P0. 26-29 chủ yếu phục vụ W2, và 30 phục vụ báo cáo
tổng hợp ở W3.

Thứ tự chạy, Đạt chốt ngày 23/10/2026 (OPS-j):

- Thân đường găng trước: 07, 05, 08, 09, rồi 16. Số đo của chúng (nền lưu trữ bản ghi và modulus phân vùng, quyền trên
  bản ghi ở quy mô D12, quyền hiệu lực và trigger chống leo thang, quyền ghi và partition tạo sau, runtime CEL) là điều
  kiện kèm của ADR 0107 và 0114 và đầu vào cho mẫu policy của ADR 0105 và trigger của ADR 0104; chúng xác nhận DO-15
  và DO-38.
- Chạy ngay, song song với thân: 02, 03 và 04, bắt đầu tuần này vì thời gian chờ (khách thí điểm, luật, duyệt ứng dụng
  của nhà cung cấp); grilling 06; 18 (một buổi hỏi bên yêu cầu) và phần FOG-10 của 19, vì hai việc này quyết bước AI
  đầu tiên của P1 dưới `vn_only`.
- 24 chạy cùng `workflow-builder-ui/01`, vì Đạt đã cho thư viện sơ đồ (DO-42) và chọn sơ đồ có cấu trúc trên cây Bước,
  không dagre (V4.24, V4.25); fixture F9 của nó thử giới hạn của cây trước khi `workflow-engine/01` dựng trên tài liệu.
- 14 là spike runtime S-RT từ ngày 25/10/2026 (V4.34, H-9), ngoài thứ tự OPS-j: 2 tuần ở đầu W1, song song với
  `foundations-hardening` và `app-standards` nên không kéo dài đường găng, và trả lời trước khi `workflow-engine/03` bắt
  đầu, vì dòng `Blocked by:` của ticket đó trỏ tới tệp của 14; câu 7-9 của nó (bậc B của V4.26, thêm ngày
  24/10/2026 từ số đo trong bộ nhớ) và câu 11 (quy trình con, V4.33) đo trong cùng spike, trước khi `workflow-engine/06`,
  `/07` và `/09` bắt đầu (ADR-0112 (Accepted), Consequences).
- 23 chạy trước `foundations-hardening/02` nếu kịp, vì luật nối danh tính tạm dựa vào `email_verified`.
- 22 chạy trước khi chấp nhận ADR 0119.
- 21 chạy trước khi OpenBao và smokescreen ra, vì ADR 0115 được nhận kèm điều kiện số đo của nó (FOG-25).
- 01 chạy khi tài khoản thử của D10 có, theo luật quan sát của DO-23.
- 30 thêm ngày 24/10/2026 (N10), ngoài thứ tự OPS-j: nó dùng lại bộ dữ liệu gieo D12 của 05 nên chạy sau 05, và xong
  trước khi spec báo cáo W3 được viết (ADR 0127 quyết định 2).

Nguyên mẫu trùng ticket P0 không chặn việc cắt W1, vì phép đo nằm trong W1: phép đo chạy một lần trong ticket W1, và
ticket khám phá đóng bằng một dòng trỏ tới kết quả (mục dưới).

### Một câu hỏi, một chỗ trả lời

Nhiều ticket ở đây hỏi đúng điều một ticket P0 hay ready-for-human của roadmap sẽ làm (cột "Ticket W1"). Mỗi phép đo
chạy một lần và kết quả có một chỗ: `## Answer` của ticket khám phá, rồi mục Open hay Consequences của ADR liên quan.
Đo trước khi W1 được cắt thì ticket W1 trỏ về Answer và chỉ giữ phần chưa đo; W1 cắt trước thì ticket W1 làm phép đo
và ticket khám phá đóng bằng một dòng trỏ tới kết quả. Ticket W1 chưa có file: đường dẫn
`.claude/plans/studio/<spec>/issues/NN-<slug>.md` có khi W1 được cắt. Số ticket W1 theo roadmap; mục "unblocks" của
blueprint đôi chỗ dùng số riêng của brief (`tenant-rbac` 04-07 của brief B3 là `tenant-rbac/02` và `/03`;
`foundations-hardening` 08 của brief B11 là `foundations-hardening/03`).

### Ticket con

Bảng là chỉ mục; trạng thái nằm ở dòng `Status:` của từng ticket.

| #   | Ticket                                                                                              | Loại      | FOG                                    | ADR                                      | Ticket W1                                                                                                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------- | --------- | -------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Quan sát chang.fpt.net bằng tài khoản thử](issues/01-chang-teardown.md)                            | research  | FOG-01                                 | 0104, 0110, 0112, 0120, 0121             | -                                                                                                                                                                                                          |
| 02  | [Khách thí điểm: số liệu, nguồn lead, file mẫu](issues/02-pilot-customer.md)                        | grilling  | FOG-02, FOG-06, FOG-14, FOG-15, FOG-68 | 0107, 0117, 0121                         | `marketing-pilot/02`, `agent-builder/04`                                                                                                                                                                   |
| 03  | [Chứng nhận xử lý dữ liệu cá nhân và Luật AI](issues/03-legal-status.md)                            | research  | FOG-73, FOG-74                         | 0106, 0122, 0123, 0125                   | `compliance-pdpl/02`                                                                                                                                                                                       |
| 04  | [Zalo OA và ZNS, Meta Lead Ads, Google](issues/04-channel-providers.md)                             | research  | FOG-04, FOG-05, FOG-79                 | 0113, 0115                               | `connections-and-vault/01`                                                                                                                                                                                 |
| 05  | [Quyền trên bản ghi ở quy mô D12](issues/05-record-access-scale.md)                                 | prototype | FOG-40, FOG-43, FOG-44                 | 0102, 0105                               | `record-access/01`, `foundations-hardening/03`                                                                                                                                                             |
| 06  | [Chủ thể lồng nhau, mức truy cập trên định nghĩa, khóa vai](issues/06-principals-and-roles.md)      | grilling  | FOG-45, FOG-46, FOG-49                 | 0102, 0103, 0104, 0105, 0116             | `record-access/04`, `org-and-principals/03`, `tenant-rbac/02`                                                                                                                                              |
| 07  | [Nền lưu trữ bản ghi](issues/07-records-storage.md)                                                 | prototype | FOG-41, FOG-55                         | 0107                                     | `custom-objects/01`                                                                                                                                                                                        |
| 08  | [Chi phí quyền hiệu lực và trigger chống leo thang](issues/08-rbac-cost.md)                         | prototype | FOG-38                                 | 0104                                     | `tenant-rbac/02`, `tenant-rbac/03`                                                                                                                                                                         |
| 09  | [Quyền ghi, partition tạo sau, offboarding](issues/09-grants-partitions-offboarding.md)             | prototype | FOG-31, FOG-32, FOG-33                 | 0100, 0105, 0107                         | `studio-skeleton/01`                                                                                                                                                                                       |
| 10  | [Kiểm trùng lead và sự tồn tại dưới RLS](issues/10-dedupe-and-upsert.md)                            | prototype | FOG-11, FOG-42                         | 0105, 0107                               | `marketing-pilot/01`, `custom-objects/03`                                                                                                                                                                  |
| 11  | [Đồng ý lúc tiếp nhận và chống tin rác](issues/11-send-floor-law.md)                                | research  | FOG-03, FOG-75                         | 0124                                     | `compliance-pdpl/02`, `compliance-pdpl/04`                                                                                                                                                                 |
| 12  | [Phê duyệt, tách nhiệm, tác giả, taint](issues/12-approvals-and-authorship.md)                      | grilling  | FOG-12, FOG-47, FOG-48, FOG-63, FOG-66 | 0109, 0110, 0112, 0120, 0125             | `workflow-nodes/06`, `agent-lifecycle/04`, `tenant-config/05`                                                                                                                                              |
| 13  | [Công cụ trên bản đã ghim](issues/13-pinned-toolchain.md)                                           | prototype | FOG-28, FOG-29, FOG-30, FOG-54         | 0100, 0108                               | `studio-skeleton/01`, `studio-skeleton/02`, `app-standards/01`                                                                                                                                             |
| 14  | [Spike runtime S-RT](issues/14-workflow-runtime.md)                                                 | prototype | FOG-37, FOG-56, FOG-59                 | 0106, 0108, 0109, 0112, 0113, 0115, 0116 | `workflow-engine/03`, `workflow-engine/04`, `foundations-hardening/02`, `tenant-config/04`, `runtime-hardening/01`, `workflow-engine/06`, `workflow-engine/07`, `workflow-engine/08`, `workflow-engine/09` |
| 15  | [Agent của tenant trên runner hiện có](issues/15-agent-runtime.md)                                  | prototype | FOG-34, FOG-35, FOG-36                 | 0116, 0117, 0120                         | `agent-builder/01`, `agent-lifecycle/01`                                                                                                                                                                   |
| 16  | [Runtime CEL và chi phí JSON Schema](issues/16-cel-and-jsonschema.md)                               | prototype | FOG-50, FOG-58                         | 0114, 0116                               | `workflow-nodes/01`, `tools-and-skills/01`                                                                                                                                                                 |
| 17  | [Model proxy LiteLLM và gateway](issues/17-litellm-model-proxy.md)                                  | prototype | FOG-19, FOG-20, FOG-21, FOG-22         | 0118, 0121                               | `model-connections/01`, `usage-and-limits/02`, `usage-and-limits/03`                                                                                                                                       |
| 18  | [Hỏi bên yêu cầu: gateway và Page, OA dùng chung](issues/18-requester-questions.md)                 | grilling  | FOG-07, FOG-18                         | 0115, 0118, 0123                         | `compliance-pdpl/03`                                                                                                                                                                                       |
| 19  | [Chất lượng model trên tiếng Việt](issues/19-vietnamese-model-quality.md)                           | prototype | FOG-09, FOG-10, FOG-64, FOG-67         | 0116, 0117, 0118, 0120, 0123             | `agent-lifecycle/02`, `agent-lifecycle/04`, `marketing-pilot/03`                                                                                                                                           |
| 20  | [Đo trên host cỡ thí điểm](issues/20-host-capacity.md)                                              | prototype | FOG-13, FOG-23, FOG-65, FOG-70, FOG-72 | 0115, 0118, 0120, 0121, 0122             | `agent-lifecycle/01`, `usage-and-limits/03`                                                                                                                                                                |
| 21  | [Kho bí mật và egress](issues/21-vault-and-egress.md)                                               | prototype | FOG-25, FOG-26, FOG-27                 | 0115                                     | `connections-and-vault/02`, `connections-and-vault/03`                                                                                                                                                     |
| 22  | [runsc systrap trên host thứ hai và CI](issues/22-gvisor-runsc.md)                                  | prototype | FOG-24                                 | 0119                                     | `code-sandbox/01`                                                                                                                                                                                          |
| 23  | [Keycloak 26.8: Organizations, brokering, lời mời](issues/23-keycloak-organizations.md)             | prototype | FOG-78                                 | 0102, 0103                               | `foundations-hardening/02`, `org-and-principals/01`                                                                                                                                                        |
| 24  | [Sơ đồ quy trình: `@xyflow/react` với bố cục cấu trúc dưới CSP nonce](issues/24-workflow-canvas.md) | prototype | FOG-51                                 | 0101, 0112                               | `workflow-builder-ui/01`                                                                                                                                                                                   |
| 25  | [Presidio trên dữ liệu cá nhân tiếng Việt](issues/25-presidio-vietnamese.md)                        | prototype | FOG-77                                 | 0106, 0122, 0123                         | `compliance-pdpl/03`                                                                                                                                                                                       |
| 26  | [Kho giữ dữ liệu cá nhân, lưu giữ, telemetry](issues/26-personal-data-stores.md)                    | research  | FOG-57, FOG-71, FOG-76                 | 0106, 0122                               | `telemetry-and-audit/01`, `compliance-pdpl/06`                                                                                                                                                             |
| 27  | [Dữ liệu tham chiếu Việt Nam](issues/27-vietnam-reference-data.md)                                  | research  | FOG-08, FOG-16, FOG-17                 | 0113, 0121                               | `usage-and-limits/03`                                                                                                                                                                                      |
| 28  | [SDK `mcp` 2.x sau cổng MCP](issues/28-mcp-sdk.md)                                                  | prototype | FOG-69                                 | 0116                                     | - (W2)                                                                                                                                                                                                     |
| 29  | [Màn quản trị W2](issues/29-w2-admin-screens.md)                                                    | prototype | FOG-39, FOG-52, FOG-53                 | 0104, 0110, 0120                         | - (W2)                                                                                                                                                                                                     |
| 30  | [Truy vấn tổng hợp dưới RLS ở quy mô D12](issues/30-aggregate-queries-under-rls.md)                 | prototype | FOG-81                                 | 0105, 0107, 0127                         | - (W3)                                                                                                                                                                                                     |

77 FOG nằm trong 30 ticket; FOG-60, FOG-61, FOG-62, FOG-80 và FOG-82 ở mục Fog. Không FOG nào nằm ở hai chỗ.

### Quy tắc chung

- Nguồn ngoài repo ghi loại (_documented_, _measured_, _vendor claim_) và ngày như [research.md](research.md); điều
  chưa kiểm ghi "chưa kiểm". `path:line` trong repo kiểm lại trước khi trích.
- Không chép tên người hay email từ ảnh chụp đối thủ; không dữ liệu cá nhân thật trong repo: đo trên dữ liệu giả lập
  (DO-22, DO-54).
- Số đo ghi phiên bản thư viện, image và máy đo. Chưa số nào của đợt nghiên cứu đo trên host 2 vCPU / 8 GB hay ở quy
  mô D12, nên số đo trên máy dev phải nói rõ là máy dev.
- Ticket không chốt thay người quyết: ngưỡng chưa có trong blueprint thì ghi số đo và để ADR hay DO chốt.

## Decisions so far

### Quyết định của bên yêu cầu

Hướng đã chọn. Đạt chấp nhận các ADR dựa trên chúng ngày 23/10/2026, trừ ADR 0119 giữ Proposed (`docs/agents/domain.md`).

- D1 (22/10/2026): dữ liệu thuộc về workspace, và workspace lồng thành cây; bản ghi có người phụ trách (người hay nhóm) và workspace sở hữu; vai trò cấp quyền theo mức truy cập. ADR 0102, 0104, 0105.
- D2 (22/10/2026): người dựng là quản trị nghiệp vụ làm no-code; bước mã chỉ có sau một quyền riêng và quyền lợi của gói dịch vụ. ADR 0101, 0112, 0117, 0119.
- D3 (22/10/2026): quyền trên bản ghi v1 đủ bốn lớp: người phụ trách và mặc định truy cập, quản lý thấy cấp dưới, quy tắc chia sẻ và chia sẻ tay có hạn, bảo mật trường áp cả agent và tìm kiếm. ADR 0105, 0106.
- D4 (22/10/2026): lát thí điểm đầu là Marketing: lead từ form, Facebook, Zalo, chấm điểm bằng AI, giao Sales, tin Zalo hay email sau phê duyệt. Spec `marketing-pilot`; ADR 0100, 0124.
- D5 (22/10/2026): si-platform là tham chiếu cộng port có chọn lọc; mọi chỗ khác si ghi trong ADR, trích si bằng repo và tên file. ADR 0100, 0105, 0107, 0114.
- D6 (22/10/2026): sổ sử dụng theo lượt gọi quay lại (partition tháng, 13 tháng), gồm embedding, rerank và môi trường chạy mã, có người đọc từ ngày đầu; cần Đạt đồng ý vì đảo migration `aefe7c1f5d9b`. ADR 0121, DO-21.
- D7 (22/10/2026): v1 có bước mã; mỗi lần chạy mã của tenant một container mới, không mạng, có trần CPU, bộ nhớ, pids, đĩa và thời gian. ADR 0119.
- D8 (22/10/2026): công ty kết nối model và khóa của chính mình qua LiteLLM; hồ sơ model của nền tảng vẫn chọn theo gói dịch vụ. ADR 0118, 0123.
- D9 (22/10/2026): mọi tài liệu kế hoạch Studio nằm trong repo này, area `studio`. ADR 0100.
- D10 (22/10/2026): bên yêu cầu sẽ có tài khoản thử trên chang.fpt.net; teardown mang danh sách kiểm. Ticket 01, [teardown-chang.md](teardown-chang.md).
- D11 (23/10/2026, DO-07): hai người luôn luôn cho mọi thay đổi cấu hình, phát hành, bật lại sau tắt khẩn cấp, duyệt công cụ MCP và nới lộ trình dữ liệu; công ty một quản trị viên không phát hành được. ADR 0110, 0120.
- Phạm vi D11 (23/10/2026, người đặt yêu cầu và Đạt): "đóng một người, mở hai người". Mọi thay đổi và gán vai trò từ W1 cần hai người, kể cả gán khi mời, và công ty một chủ sở hữu không đổi được vai trò tới khi có người thứ hai; mở trường dữ liệu cá nhân Cơ bản, đổi mặc định truy cập và phát hành định nghĩa đối tượng cần hai người; siết quyền (thu hẹp quyền, đóng trường, hạ hạn mức, siết lộ trình dữ liệu, tắt khẩn cấp) cần một người cộng audit. ADR 0104, 0106, 0110.
- D12 (23/10/2026, DO-14): quy mô v1 là 10 triệu bản ghi mỗi đối tượng, 50 triệu mỗi tenant, 5.000 người dùng, 200 workspace, cây sâu 6; bản ghi partition băm theo tenant từ revision đầu. ADR 0102, 0105, 0107.
- D13 (23/10/2026, DO-19): model của tenant đi qua một lane LiteLLM riêng, không trạng thái (model proxy), không khóa trong môi trường; gateway hiện có chỉ phục vụ model của nền tảng; alias chưa khai nơi xử lý coi là nước ngoài. ADR 0118.
- D14 (23/10/2026, DO-24): nâng host chính lên ít nhất 4 vCPU / 16 GB trước khi OpenBao và egress proxy ra, thêm VM riêng cho `sandbox-runner` trước khi mã tenant chạy ở uat hay production; đo trước khi chốt cỡ. ADR 0115, 0119.

### DO Đạt đã chốt

Hai mươi DO mà agent ghi tạm ngày 23/10/2026 ("agent, tạm theo khuyến nghị") theo phương án khuyến nghị của blueprint
(19 mục là (a), DO-20 là (c)). Đạt chốt cùng ngày: giữ nguyên 15 mục, đổi hay làm rõ 5 mục (DO-20, DO-26, DO-28, DO-31,
DO-45); các dòng dưới đã theo bản chốt, và mỗi quyết định có dòng của Đạt ở mục Quyết định của `requirements.md`.

- DO-04: giữ "workspace" làm từ trên giao diện. ADR 0102.
- DO-08: tên API bất biến sau lần phát hành đầu. ADR 0109.
- DO-10: bộ quyền bổ sung là một loại vai trò; mức "Của nhóm tôi" là bản ghi của tôi và nhóm tôi; tách nhiệm xét theo người trên cả công ty. ADR 0102, 0104.
- DO-11: mặc định truy cập công khai có nghĩa toàn công ty; quản lý trực tiếp xem và sửa bắc cầu, không xóa, có công tắc theo đối tượng; khi giao, người giao chọn, mặc định giữ workspace sở hữu; chia sẻ tay còn sau khi đổi người phụ trách. ADR 0105.
- DO-18: chăm sóc lead ở W2; mọi tin gửi ra trong thí điểm đều được duyệt, mỗi tin một phê duyệt trong hàng chờ thao tác nhanh bằng bàn phím. ADR 0112; spec `marketing-pilot`.
- DO-20 (phương án (c)): ứng dụng nền tảng cho Meta và Zalo, Page và OA của khách nối bằng OAuth, ứng dụng Google nội bộ của khách, nền tảng không giữ ứng dụng Google nào; pháp nhân vận hành nộp App Review và Business Verification từ tuần một. Spec `connections-and-vault`.
- DO-22: khách thí điểm là một đội marketing thật, dữ liệu giả lập tới khi ký DPA; đích xác nhận với khách trước chạy bóng. Spec `marketing-pilot`.
- DO-23: chang.fpt.net chỉ quan sát như người dùng thường; không quét, tải hay dò; không chép dữ liệu cá nhân. Ticket 01, [teardown-chang.md](teardown-chang.md).
- DO-26: W1 chỉ mở chế độ Mô phỏng; `test` trả 422 tới W2, khi có Danh sách người nhận thử; từ W1 lời gọi ra ngoài của mọi chế độ khác `live` bị chặn; tên `test` giữ; vùng tạm theo lượt chạy ở v1.5. ADR 0111; spec `workflow-triggers`, `tenant-config`.
- DO-28 (phương án C): đóng băng tách theo loại lượt như hạn mức: lượt tương tác bị từ chối ngay với `tenant_frozen`, lượt do trình kích hoạt giữ `queued` như sự kiện đã giữ và chạy theo thứ tự sau khi gỡ; tắt khẩn cấp vẫn hủy lượt đang chờ. ADR 0113, 0120.
- DO-30: phiên bản quy trình con và bước agent ghim lúc gửi kiểm định; lệch cấu hình đề xuất cập nhật. ADR 0109, 0112, 0117.
- DO-31: phê duyệt hết hạn làm lượt chạy thất bại với `approval_expired`; không gì tự duyệt khi hết giờ; hết hạn đến ở W2 cùng YC52 và lane hẹn giờ; ở W1 phê duyệt của Bước phê duyệt không có hạn riêng, nhưng hạn chót của lượt chạy (mặc định 30 ngày, có từ W1 theo V4.14 ngày 24/10/2026) kết thúc lượt với `deadline_exceeded` và hủy phê duyệt đang mở cùng nó. ADR 0112, 0113.
- DO-36: người duyệt phải đọc được các trường phê duyệt hiển thị; ứng viên duyệt theo mức truy cập của vai trò. ADR 0106.
- DO-37: điều kiện để lưu được nghĩa là "phải đúng", viết bằng CEL với vector thử port từ si-platform. ADR 0107, 0114.
- DO-39: link nhận lời mời do quản trị viên chép; MFA cho người vận hành, nhân viên hỗ trợ và người giữ quyền trọng yếu; sự kiện nhận trả 503 khi công ty bị khóa; người chịu trách nhiệm rời đi thì chặn phát hành, phiên bản đang dùng vẫn chạy. ADR 0102, 0113.
- DO-43: không chuyển từ model của tenant sang model nền tảng trả phí; model của tenant cấp công ty được dùng công cụ; không endpoint tại chỗ ở v1; token BYOM chỉ tính vào trần do công ty đặt. ADR 0118, 0121.
- DO-45: chỉ Python 3.12, không JavaScript, không chạy script của kỹ năng ở v1; ở v1 mỗi lần chạy mã một container mới (D7), container theo phiên agent chỉ ở W3 và quyết lúc đó; tính phí theo vCPU và GB đặt trước nhân thời gian. ADR 0112, 0116, 0119.
- DO-48: SMTP chung là đường email P1; chỉ kết nối dùng chung theo workspace; cùng Page hay OA nối bởi hai công ty thì gửi tới cả hai, luật sư xác nhận. ADR 0113, 0115.
- DO-50: kỳ tính theo múi giờ công ty; chạm hạn mức cứng giữa lượt chạy thì dừng; dựng có AI, chạy mô phỏng và chạy thử, kiểm định trả từ ngân sách công ty với trần mục đích riêng; chỉ lượt chạy gốc tính vào số lượt mỗi ngày. ADR 0121.
- DO-57: chỉ giao diện tiếng Việt, dùng khóa thông điệp từ đầu; demo và thí điểm trên host uat ở Việt Nam có chứng chỉ hợp lệ và HSTS. Spec `marketing-pilot`, `studio-skeleton`.

### Trả lời từ ticket

Chưa có. Mỗi ticket xong thêm một dòng: số ticket, ý chính, link tới `## Answer`.

## Fog

Năm mục chưa nói được chính xác; mỗi mục ghi vì sao và khi nào quay lại.

- **FOG-60 `test-scratch` (prototype).** Vùng tạm theo lượt chạy cho các lần ghi bản ghi bị chặn, để lượt chạy thử đọc
  lại thứ mình vừa ghi giả lập qua cổng bản ghi. DO-26 (Đạt chốt 23/10/2026) để nó ở v1.5, và hình của nó phụ thuộc
  `RecordService` (`custom-objects/03`) và executor Mô phỏng (`tenant-config/03`) chưa có. Quay lại khi lập kế hoạch
  v1.5; spec chủ `tenant-config`.
- **FOG-61 `pack-merge` (prototype).** Độ mịn của hợp nhất ba chiều cho `dw.workflow/v1` và tài liệu agent (theo bước
  hay theo trường, id bước đổi tên, chỗ của Bước trong cây); phần dùng trường có cấu trúc so với văn bản tự do; xuất và
  nhập không mất mát giữa hai công ty với mã băm như nhau. Cần hai phiên bản thật của gói nghiệp vụ Marketing, mà bộ cài
  gói nghiệp vụ ở W2 và W1 chỉ có script gieo. Phần điểm mù của chỉ mục phụ thuộc ước được từ script gieo W1. Quay lại khi
  gói nghiệp vụ Marketing có phiên bản thứ hai; spec chủ `domain-packs`.
- **FOG-62 `v2-transport` (prototype).** Làn chuyển gói cài đặt từ công ty thử nghiệm sang công ty thật dưới hai giao
  dịch RLS và một mối nối giữa hai công ty do người vận hành tạo; sẽ là làn ghi chéo công ty đầu tiên ngoài offboarding. Thuộc v2
  (W3); công ty thử nghiệm mới có nguyên tắc của DO-62 (chỉ người vận hành tạo, chỉ dữ liệu giả lập, hạn mức riêng),
  chưa có spec. Quay lại khi spec công ty thử nghiệm mở.
- **FOG-80 `agent-identities` (grilling).** Danh tính agent có quyền riêng (Entra Agent ID, bản nháp SCIM cho agent) có
  thành yêu cầu không, kéo theo mở lại việc tài khoản dịch vụ là một dòng `platform.users` (DO-17, ADR 0103). Câu trả
  lời phụ thuộc các chuẩn còn ở dạng nháp (chưa kiểm); W3. Quay lại khi một khách đòi hay một chuẩn ra bản chính
  thức; spec chủ `org-and-principals`.
- **FOG-82 `tiktok-leadgen` (research).** TikTok Lead Generation có API hay webhook nhận lead mà một công ty dùng được
  không, cần duyệt ứng dụng và xác minh doanh nghiệp gì, xử lý dữ liệu ở đâu (`data_location`), và có đối soát được để
  không mất lead khi webhook rớt như Meta Lead Ads không; [research.md](research.md) ghi API của TikTok Lead Gen chưa
  kiểm. Đạt rút TikTok khỏi phần W2 của YC97 và cho vào W3 chỉ sau một ticket khám phá kiểm API (N8, 24/10/2026); mục
  này thành ticket khi lập kế hoạch W3. Spec chủ `connections-and-vault`, cùng `marketing-pilot` cho nguồn lead.
