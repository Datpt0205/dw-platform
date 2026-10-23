# Phân tích đối thủ: chang.fpt.net (từ ảnh chụp demo)

Status: needs-triage
Area: studio · Viết: 23/10/2026

Tám ảnh chụp chang.fpt.net cho thấy gì, gợi ra gì về cách họ xây, Studio định làm khác ở đâu, và danh sách kiểm cho
tài khoản thử người đặt yêu cầu sẽ nhận (D10). Chưa ai dùng hệ thống này: mọi điều dưới đây đến từ ảnh. Đây là đầu
vào cho ticket khám phá FOG-01 `chang` và cho [brainstorm.md](brainstorm.md), không phải yêu cầu: yêu cầu nằm ở
`requirements.md` của area `studio` (mã `YC<n>`), quyết định ở ADR 0100-0125.

## Nguồn và cách đọc

- Tám ảnh người đặt yêu cầu chụp trong buổi demo của một nhóm khác, sáng 22/10/2026, không nằm trong repo. Màn 1
  chụp trên một máy macOS, màn 2 tới 8 trên một máy Windows; màn 6 và 7 giống hệt nhau; màn 8 cắt từ màn 2.
- _Quan sát_ là điều thấy trong ảnh; _suy luận_ là điều suy ra từ ảnh, chưa kiểm. Chưa câu nào kiểm bằng tài khoản.
- Ảnh có tên người, email, tên đăng nhập, mã chi nhánh và mã chức danh nội bộ: ở đây không chép lại, chỉ nói "một
  người dùng", "người tạo"; về id chỉ nói id trên URL quản trị là số nguyên, không chép giá trị nào.
- Chưa kiểm chang.fpt.net là sản phẩm nào của FPT; research ghi FPT bán một không gian agent doanh nghiệp trên
  [AWS Marketplace][fpt-aws] (hãng tự nhận), chưa nối được với trang này.

## Từng màn

- **Màn 1: chat của người dùng cuối.**
    - Hai cửa sổ của cùng một ứng dụng ("Digital Workforce", "Nhà của Chang"), URL `/chat/<uuid>?c=<uuid>`; thanh
      địa chỉ trên máy này không cảnh báo TLS. Thanh trái: "Quản lý nhân sự số", "Công việc" (huy hiệu 1), "Lịch sử
      hội thoại", persona điều phối "Chang — Điều phối", mục "Gần đây", danh sách "Nhân sự số" có chấm trực tuyến.
    - Đầu trang: tên agent, đếm thích và không thích, "Chat mới", nút VI, đổi sáng tối, chuông. Màn trống: lời chào,
      bốn gợi ý (tiền điện, thống kê vé, đối soát vé máy bay, tổng quan tháng), ô soạn có "+", nút "Hỏi trước", micro.
    - Hội thoại: agent hỏi lại kỳ cần xem, người dùng trả lời, agent hiện "Đã suy nghĩ · 1 bước" và "Chạy quy trình"
      kèm tên một quy trình thống kê hóa đơn điện, rồi trả số liệu. Mỗi tin có thích, không thích, sao chép và giờ.
- **Màn 2: cài đặt agent, trang "Phân quyền & hành vi".**
    - URL `/ai-agent/admin/chatbot/<id>/setting?from=chatbot`, id là số nguyên; thanh địa chỉ "Not secure",
      `https` bị gạch. Đầu trang: tên agent, ô chọn model "GPT-4.1 mini · OpenAI", công tắc bật.
    - Menu: Profile, Thông tin chung, Quản lý phiên bản; "LOGIC & NĂNG LỰC": Persona & Prompt, Knowledge, Agent
      Tool, Liên kết Agent; "CẤU HÌNH": Phân quyền & hành vi, Ủy quyền hành động, Brain (Beta), Bộ đề kiểm định, Trò
      chuyện; "HẠN MỨC & USAGE": Cấu hình limit, Mức độ sử dụng.
    - Trang đang mở lọc ai được dùng agent theo thuộc tính nhân sự: ba danh sách chọn nhiều có tìm kiếm, "Chọn tất
      cả", "Bỏ chọn tất cả": Branch (mã kèm tên ban), Job Code (mã kèm tên chức danh), Office Code. Mỗi danh sách
      ghi "Đã chọn tất cả" trong khi không ô nào nhìn thấy được tích.
- **Màn 3: danh sách quy trình.**
    - URL `/ai-agent/admin/option/workflow`, "Not secure". Menu của ứng dụng quản trị "AIAgent": "Agent Studio (v2)"
      (Tổng quan; Kiểm định: Lịch sử kiểm định, Kiểm định Retrieval; Cấu hình: Bộ đề kiểm định, Ngân hàng câu hỏi,
      Cấu hình Quality Gate), Ủy quyền (huy hiệu 1), Brain (Beta), Nhật ký audit, "Thư viện Agent" nhãn "Deprecated";
      "THIẾT LẬP AGENT": Skills, Credentials, Workflow (Danh sách, Lịch sử, Quản lý Task), Plugin; màn 5, 6 có thêm MCP.
    - Lọc theo tìm kiếm, trạng thái, loại trigger, "Chọn bộ phận", email người tạo; nút "Tạo Flow". Thẻ: tên,
      "Active", nhãn trigger (DataHub Event, Manual, Webhook, Schedule), nhãn "Công khai", số lượt chạy, lần chạy
      cuối, email người tạo; nút chạy, sửa, bật tắt, xóa.
    - Quy trình thấy được: xử lý ticket dịch vụ khách hàng qua DataHub Event (hơn 1.500 lượt), ghi yêu cầu vào
      DataTable rồi báo qua FChat, nhận Webhook rồi gửi email và cảnh báo FChat, cảnh báo tháng theo lịch, lọc CV.
      Ba thẻ là công cụ kiểm định: mô tả ghi "Eval tooling (private)", hai thẻ ghi thêm "Manual trigger, no side
      effects", nhãn trên thẻ lại là "Công khai". Mô tả nhắc id quy trình, agent, DataTable, đều là số nguyên.
- **Màn 4: cấu hình bước "AI Agent".**
    - Ba cột: Input (biến từ bước trước, trống khi chưa nối), Setup, Output (5 biến cho bước sau).
    - Setup: "Chọn Trợ lý" (bắt buộc); kiểu đầu vào ("Câu Hỏi Đơn"); câu hỏi chèn biến bằng `{{nodeId.ten_bien}}`;
      dữ liệu bổ sung; tệp đính kèm: ảnh jpg, png, gif, webp, tài liệu PDF, DOCX, XLSX, TXT, CSV, JSON, XML, HTML,
      Markdown, không nhận Office cũ, tài liệu quá 100.000 ký tự bị cắt, ảnh base64 tối đa 5 MB.
    - Output: `error` (`message`, `errorStatus`, `errorData`; chỉ có khi chọn "Bỏ qua và trả lỗi làm kết quả"),
      `response`, `toolCalls` (tool, input, output, isSuccess), `documentReferences` (fileId, chunkId, fileName,
      link), `metadata`. Id bước là tiền tố loại cộng số thứ tự (`agent_3`).
- **Màn 5: "Data Hub", sửa nguồn dữ liệu.**
    - URL `/ai-agent/admin/option/data/<id>`, id là chuỗi ngẫu nhiên, khác agent; "Not secure". Mô tả: "Thiết lập
      một endpoint để nhận dữ liệu và cấu hình các Agent nhằm hiểu dữ liệu đầu vào"; hai bước Cơ bản và Schema; nút
      "Lịch sử Event", "Sao chép CURL", "Vô hiệu hóa", "Xóa".
    - Schema: tải lên hoặc dán JSON; bảng khóa trường, kiểu ("Text (String)", "Date/Time (Number)"), "Mô tả ngữ
      nghĩa AI (quan trọng!)", bắt buộc, xóa. Ví dụ là bảy trường của một email báo cáo (địa chỉ QA, tiêu đề, nội
      dung, người nhận, cc, ngày báo cáo, đơn vị báo cáo), đều bắt buộc.
- **Màn 6 và 7: "Agent Studio", control plane.**
    - "Control plane — toàn bộ nhân sự số theo vòng đời. Ưu tiên xử lý: chờ duyệt & lệch dependency."; nút "Đóng
      băng hệ thống", "Tạo agent". "Cảnh báo cần chú ý (27)" theo loại: "Đã bị tắt (kill)", "Nháp để lâu chưa
      publish", "Lệch cấu hình chưa xử lý", "Kiểm định dưới ngưỡng". "Component chờ xử lý (41)" chưa mở rộng.
    - "Tổng quan đội ngũ", bấm ô để lọc: 22 Nháp, 0 Kiểm định, 0 Chờ duyệt, 52 "Đang chạy (live)", 0 Đã gỡ, 4 "Bị
      kill". "Đã kiểm định thật: 8/52", chỉ tính lượt có bộ đề và có chấm điểm; chữ nhỏ bên cạnh đọc như "sơ bộ 0 ·
      trượt 9" (ảnh mờ, chưa chắc).
    - "Agent chờ xử lý (17)": "Kiểm định đầy đủ Đạt — chờ publish (1)" và "Cần xử lý — chưa / đang / trượt Kiểm
      định đầy đủ (5)". Cả năm dòng thấy được đều ghi "Kiểm định đầy đủ trượt", mỗi dòng có "Xem diff" và nút
      "Publish" màu xanh; một trong năm agent đó cũng nằm trong cảnh báo "Đã bị tắt (kill)".
- **Màn 8: thanh địa chỉ.** Cắt từ màn 2: "Not secure", `https` gạch đỏ, URL cài đặt agent có id số nguyên.

## Kiến trúc của họ (suy luận)

- Một tổ chức, không tenant: không màn nào có chọn công ty hay workspace; người được dùng lọc theo dữ liệu nhân sự
  (nhiều khả năng đồng bộ từ hệ thống nhân sự), quy trình lọc theo bộ phận (màn 2, 3).
- Hai ứng dụng trên một tên miền, chat ở `/chat` và quản trị ở `/ai-agent/admin`; đường dẫn `chatbot` và "Thư viện
  Agent (Deprecated)" cho thấy agent lớn lên từ một sản phẩm chatbot, hai mô hình dữ liệu cùng sống (màn 2, 3).
- Quy trình là xương sống tích hợp: bốn loại trigger, đầu ra kiểu hóa và chính sách lỗi theo bước; quy trình gọi
  agent qua bước "AI Agent", agent gọi quy trình như công cụ trong chat; thông báo qua FChat (màn 1, 3, 4).
- Biểu thức là chuỗi có biến trên id bước đánh số, không thấy kiểm kiểu khi lưu (màn 4). "Mô tả ngữ nghĩa AI" của
  trường nhiều khả năng đi vào prompt để agent hiểu payload (màn 5).
- Lớp quản trị đủ khái niệm: phiên bản, bộ đề, ngân hàng câu hỏi, kiểm định retrieval, quality gate, mục "Ủy quyền",
  nhật ký audit, kill theo agent, đóng băng toàn hệ thống, lệch cấu hình, xem diff trước khi publish (màn 2, 3, 6).
- Cổng kiểm định có vẻ chỉ là khuyến nghị, và ô đếm giai đoạn không đọc từ cùng máy trạng thái với danh sách việc
  (màn 6; điểm yếu 5 và 9). Công cụ kiểm định dựng bằng chính quy trình, nên "không tác động" là quy ước (màn 3).
- Model chọn theo agent, có model OpenAI (màn 2): lời gọi của agent đó nhiều khả năng ra nước ngoài, trừ khi đi qua
  một điểm trung gian trong nước (chưa rõ).

## So sánh với Studio

Cột Studio ghi spec và đợt của roadmap (W1 là P0 cộng lát Marketing mỏng, W2 là v1 GA), kèm ticket W1 dạng `spec/NN`
khi có; `path:line` đã kiểm trên `main` ngày 23/10/2026. Cột cuối là chỗ Studio cố ý làm khác.

| Năng lực                             | chang.fpt.net như thấy                                                                                                                        | Studio dự kiến (spec, đợt)                                                                                                                                                                                                                            | Chỗ Studio cố ý khác                                                                                                                                                                               |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tenant, workspace                    | Không thấy tenant hay workspace; lọc theo bộ phận (màn 2, 3; suy luận)                                                                        | RLS FORCE có test cho mọi bảng tenant (có sẵn, `packages/python/dw_platform/tests/integration/test_rls_coverage.py:47`); hai workspace cùng cấp W1, cây workspace W2 (`org-and-principals`)                                                           | Workspace là nơi sở hữu dữ liệu, với sang nhau bằng quyền chứ không sao chép (D1, ADR 0102); tenant khác đọc 0 dòng ở mọi đường (YC3)                                                              |
| Phân quyền                           | Ai được dùng agent theo Branch, Job Code, Office Code (màn 2); không thấy quyền bản ghi hay trường                                            | Vai là dữ liệu, mỗi quyền có mức truy cập, W1 (`tenant-rbac`, YC12); lớp (a) quyền trên bản ghi W1, ba lớp còn lại W2 (`record-access`); bảo mật trường W1 (`field-security`, YC23); thuộc tính nhân sự và `dw.audience/v1` W2 (`org-and-principals`) | Người được dùng chỉ quyết ai mở agent; agent đọc gì theo quyền của chính người hỏi; người ngoài nhận "không tìm thấy" (YC55)                                                                       |
| Id trên URL quản trị                 | Agent: số nguyên (màn 2, 8); nguồn dữ liệu: chuỗi ngẫu nhiên (màn 5)                                                                          | UUID ở route hiện có (`apps/api/src/dw_api/routes/v1/approvals.py:154`); id công khai của nguồn dữ liệu 130 bit ngẫu nhiên W1 (`workflow-triggers/02`)                                                                                                | Quyền không dựa vào id khó đoán: thứ của tenant khác trả "không tìm thấy" (`.claude/rules/ui-quality.md:126`); UUIDv7 vẫn lộ thời điểm tạo (`packages/python/dw_kernel/src/dw_kernel/ports.py:67`) |
| TLS, header                          | "Not secure", `https` gạch trên trang quản trị ở một máy (màn 2, 3, 5, 8); máy kia không cảnh báo (màn 1)                                     | HSTS một năm ở edge (`infra/caddy/Caddyfile:23`); CSP có nonce mỗi request (`apps/web/middleware.ts:5`); TLS hợp lệ ở mọi chặng của uat và production W2 (`compliance-pdpl`, YC92)                                                                    | Chứng chỉ nội bộ chỉ cho máy thử không có DNS công khai, trình duyệt từ chối nó là có chủ ý (`infra/caddy/Caddyfile:12-15`); demo và thí điểm trên host uat ở Việt Nam có chứng chỉ hợp lệ (DO-57) |
| Danh sách quy trình, trình kích hoạt | Thẻ có trigger DataHub Event, Manual, Webhook, Schedule, số lượt chạy, "Công khai"; lọc bộ phận, email người tạo (màn 3)                      | Chạy tay, chạy thử, nguồn dữ liệu W1 (`workflow-triggers/01`, `/02`); lịch, sự kiện nhà cung cấp, sự kiện bản ghi, trang lịch sử sự kiện W2 (`workflow-triggers`)                                                                                     | Không có cờ "Công khai": ai thấy và chạy quy trình theo vai và workspace sở hữu; trình kích hoạt chỉ xin lượt chạy (ADR 0113)                                                                      |
| Bước AI                              | "AI Agent" với Input, Setup, Output; `response`, `toolCalls`, `documentReferences`, `metadata`, `error`; chính sách lỗi; giới hạn tệp (màn 4) | `ai.llm` W1 (`workflow-nodes/05`); chính sách lỗi khai trong sổ đăng ký loại bước W1 (`workflow-nodes/02`); `ai.agent` W2 (`workflow-nodes`)                                                                                                          | Đầu ra có cấu trúc kiểm phía server, sai thì không dùng; giá trị vào prompt bọc trong khối `<input>` (ADR 0010); biểu thức CEL kiểm kiểu khi phát hành (ADR 0114)                                  |
| Nguồn dữ liệu                        | Schema có mô tả ngữ nghĩa AI, trường bắt buộc; lịch sử event, sao chép cURL, vô hiệu hóa (màn 5)                                              | `dw.endpoint/v1` W1 (`workflow-triggers/02`): chữ ký Standard Webhooks hoặc token tĩnh, chống trùng (đề xuất 72 giờ), `pd_category` trên trường; trang lịch sử sự kiện W2                                                                             | Sai chữ ký, lệch giờ, sai lược đồ hay id không tồn tại bị từ chối mà không tạo lượt chạy (YC42); tenant lấy từ endpoint, không từ payload                                                          |
| Agent gọi quy trình                  | "Chạy quy trình" trong chat (màn 1)                                                                                                           | Quy trình dùng như công cụ W2 (`tools-and-skills`, `agent-builder`); phân tích bộ ba nguy hiểm khi phát hành W1 (`compliance-pdpl/05`)                                                                                                                | Đường nào trộn đầu vào không tin cậy, dữ liệu riêng và tác động ra ngoài phải qua người trước tác động (ADR 0125)                                                                                  |
| Kiểm định, phát hành                 | Bộ đề, ngân hàng câu hỏi, kiểm định retrieval, quality gate; "Đã kiểm định thật 8/52"; Publish hiện trên dòng trượt (màn 3, 6)                | Cổng gồm bộ kiểm định an ninh nền tảng đạt 100% ở Mô phỏng và một người duyệt khác tác giả W1 (`agent-lifecycle/04`, YC70); bộ đề của tenant, giám khảo LLM, kiểm định retrieval, kiểm định trực tuyến W2 (`agent-lifecycle`)                         | Cổng trượt thì server từ chối phát hành, nút khóa kèm lý do (`.claude/rules/ui-quality.md:140`); bằng chứng kiểm định gắn mã băm định nghĩa, đổi phụ thuộc là mất bằng chứng (ADR 0120)            |
| Vòng đời, tổng quan đội ngũ          | Nháp, Kiểm định, Chờ duyệt, Đang chạy (live), Đã gỡ, Bị kill; cảnh báo; Xem diff (màn 6)                                                      | Giai đoạn do database canh W1 (`agent-lifecycle/03`); tổng quan đội ngũ, trang phiên bản, so sánh, lệch cấu hình W2 (`agent-lifecycle`, YC75)                                                                                                         | Bản đang phục vụ gọi là "Đang dùng", "Đang chạy" để dành cho lượt chạy; tổng quan đọc dữ liệu theo quyền người xem, không từ trace (YC75)                                                          |
| Đóng băng, tắt khẩn cấp              | "Đóng băng hệ thống"; 4 agent "Bị kill" (màn 6)                                                                                               | Đóng băng nền tảng và theo tenant W1 (`agent-lifecycle/01`, YC72); tắt khẩn cấp agent và quy trình W1 (`agent-lifecycle/05`, YC73); đóng băng tiếp tục được W2                                                                                        | Kiểm ở mọi cửa, dừng trong ≤ 5 giây (YC72); tắt khẩn cấp hủy lượt và phê duyệt đang chờ, bật lại cần người thứ hai (YC73, D11)                                                                     |
| Chạy không tác động                  | Bản sao "EVAL", "no side effects" ghi trong mô tả (màn 3)                                                                                     | Chế độ chạy Mô phỏng chặn tại executor W1 (`tenant-config/03`, YC34); Chạy thử với người nhận thử W2 (`tenant-config`)                                                                                                                                | "Không tác động" được ép tại điểm tác động, không phải lời hứa trong mô tả (ADR 0111; BS10 trong brainstorm)                                                                                       |
| Hạn mức, mức độ sử dụng              | "Cấu hình limit", "Mức độ sử dụng" theo agent (màn 2)                                                                                         | Sổ sử dụng theo lượt gọi và màn Mức độ sử dụng W1 (`usage-and-limits/02`); hạn mức giữ trước khi nhận lượt chạy W1 (`usage-and-limits/03`, YC77); cảnh báo ngưỡng, hạn mức theo người và mục đích W2 (YC79)                                           | Một chuỗi phạm vi hạn mức (gói dịch vụ, tenant, workspace, agent hay quy trình, người dùng, lượt chạy), giữ trước bằng lease Postgres (ADR 0121)                                                   |
| Hỏi trước, hộp việc                  | "Ủy quyền hành động" trong cài đặt agent (màn 2), mục "Ủy quyền" có huy hiệu (màn 3), nút "Hỏi trước" trong ô chat (màn 1)                    | Yêu cầu phê duyệt có sẵn (`apps/api/src/dw_api/routes/v1/approvals.py:180`); "Hỏi trước" W2 (`agent-builder`, YC56); `human.task` và hộp Việc của tôi W2 (`workflow-nodes`, YC53)                                                                     | Một hộp cho phê duyệt và việc cần làm (YC53, BS27); "Ủy quyền dùng kết nối" của Studio là khái niệm khác: kết nối cá nhân cho lượt chạy nền, W2                                                    |
| Brain (Beta)                         | Mục menu, chưa rõ nội dung (màn 2, 3)                                                                                                         | Chưa có trong roadmap; nền tảng có bộ nhớ với hàng duyệt (`packages/python/dw_memory/src/dw_memory/review.py:21`)                                                                                                                                     | Chưa so được; kiểm ở nhóm D                                                                                                                                                                        |
| Kỹ năng, công cụ, MCP, bí mật        | Skills, Credentials, Plugin, MCP là mục riêng (màn 3, 5, 6)                                                                                   | Kho bí mật và kết nối dùng chung theo workspace W1 (`connections-and-vault/02`, `/04`, YC61); công cụ dữ liệu đối tượng W1 (`tools-and-skills/03`); công cụ HTTP, OpenAPI, kỹ năng W2 (YC66); máy chủ MCP W2 (`mcp-client`, YC68)                     | Không có "plugin": công cụ theo loại và bộ công cụ có phiên bản; định nghĩa công cụ MCP được ghim và một người khác người đăng ký duyệt (YC68)                                                     |
| Model theo agent                     | Ô chọn model ở đầu trang agent, có model OpenAI (màn 2)                                                                                       | Hồ sơ model trong danh sách gói dịch vụ cho phép W1 (`model-connections/02`, YC85); model của tenant qua model proxy W2 (`model-connections`, YC58)                                                                                                   | Lộ trình dữ liệu chặt nhất của tenant, workspace và agent được áp và ghi ở mỗi lời gọi (ADR 0123)                                                                                                  |
| Nhật ký kiểm toán, lịch sử chạy      | "Nhật ký audit", "Lịch sử" quy trình (màn 3)                                                                                                  | Nhật ký kiểm toán phân vùng tháng (có sẵn, `db/migrations/sql/0012_partition_maintenance.sql:133`); lịch sử chạy từng bước có che W1 (`telemetry-and-audit/03`, YC81); lọc và xuất nhật ký W2 (YC83)                                                  | Tenant đọc lịch sử chạy, sử dụng và nhật ký từ PostgreSQL dưới RLS, không từ trace (ADR 0122)                                                                                                      |
| Hai thế hệ cùng chạy                 | "Thư viện Agent (Deprecated)" cạnh "Agent Studio (v2)" (màn 3, 5, 6)                                                                          | Một vỏ phiên bản cho mọi thành phần W1 (`tenant-config/02`, YC30)                                                                                                                                                                                     | Thế hệ mới là `type@major` mới trong cùng vỏ, lượt chạy ghim thứ nó dùng (ADR 0109)                                                                                                                |
| Chat người dùng cuối, ngôn ngữ       | Persona điều phối, gợi ý, thích và không thích, "Đã suy nghĩ · 1 bước", nút VI (màn 1)                                                        | Chat qua polling W1 (`agent-builder/04`); trích dẫn, phản hồi, SSE, quy trình trong chat W2 (`agent-builder`); chỉ tiếng Việt, khóa chuỗi từ đầu (DO-57)                                                                                              | Điều phối bằng agent liên kết và agent con, agent điều phối không giữ công cụ tác động; không có siêu agent (BS24)                                                                                 |
| Kho bảng, kênh nội bộ                | DataTable, FChat (màn 3)                                                                                                                      | Đối tượng Lead, Campaign W1 (`custom-objects`); email SMTP W1 (`connections-and-vault/05`); Zalo OA, ZNS, Facebook W2; kênh chat Zalo có sẵn (ADR 0005)                                                                                               | Dữ liệu nghiệp vụ là đối tượng có quyền trên bản ghi và trường, không phải bảng tự do                                                                                                              |

## Điểm yếu quan sát được

Sáu điểm đầu là điểm chính, ba điểm sau thấy khi đọc lại từng ảnh; mỗi điểm kèm chỗ Studio tránh nó.

1. **Không có tenant hay workspace.** Không màn nào có chọn công ty hay workspace; phạm vi là thuộc tính nhân sự của
   một tổ chức (màn 2, 3; suy luận). Bán cho nhiều khách cần cách ly mà ảnh không cho thấy. Studio: YC3, ADR 0102.
2. **Quyền thô.** Chỉ thấy quyết định ai được dùng agent; không thấy quyền theo bản ghi, theo trường, hay ai sửa
   được agent của ai (màn 2; suy luận từ chỗ vắng). Studio: bốn lớp của D3, YC12, YC23.
3. **Id quản trị đoán được.** Id agent trên URL quản trị là số nguyên nhỏ (màn 2, 8), id trong mô tả thẻ quy trình
   cũng vậy (màn 3); suy luận là số tăng dần. Id đoán được biến mỗi chỗ quên kiểm quyền thành lộ hàng loạt; nguồn
   dữ liệu lại dùng id ngẫu nhiên (màn 5), tức hai quy ước trong một sản phẩm.
4. **Cảnh báo TLS trên trình duyệt.** Trang quản trị hiện "Not secure", `https` gạch trên máy Windows (màn 2, 3, 5,
   8), trang chat trên máy macOS thì không (màn 1). Ở Chromium đó thường là lỗi chứng chỉ đã bị bấm bỏ qua (chưa
   kiểm), có thể do CA nội bộ trên máy đó (suy luận); người quen bấm qua cảnh báo sẽ bấm qua cả trang giả (DO-57, YC92).
5. **Nút Publish hiện khi kiểm định trượt.** Năm dòng "Kiểm định đầy đủ trượt" đều có nút "Publish" màu xanh, một
   dòng là agent đang bị kill (màn 6). Nếu server không từ chối thì cổng chỉ là khuyến nghị, và một lần publish có
   thể bật lại agent bị kill mà không qua người thứ hai (suy luận). Studio: `agent-lifecycle/04`, YC70, YC73.
6. **Hai thế hệ thư viện agent cùng chạy.** "Thư viện Agent (Deprecated)" còn ở menu cạnh "Agent Studio (v2)" (màn
   3, 5, 6), đường dẫn quản trị agent còn chữ `chatbot` (màn 2). Hai mô hình dữ liệu cùng sống thì mỗi kiểm soát
   mới phải viết hai lần, và chỗ quên là chỗ lọt (`failure-modes.md` #5). Studio: ADR 0109, YC30.
7. **Nhãn nói ngược nhau.** Thẻ "EVAL" ghi "(private)" và "no side effects" trong mô tả nhưng mang nhãn "Công khai"
   (màn 3): nhãn và cấu hình thật không cùng một nguồn, còn "không tác động" chỉ là văn bản. Studio: YC34.
8. **Mặc định có thể mở.** Danh sách người được dùng ghi "Đã chọn tất cả" khi không ô nào nhìn thấy được tích (màn
   2); nếu để trống nghĩa là ai cũng dùng được thì mặc định đang mở (`failure-modes.md` #7; suy luận, kiểm ở nhóm A).
9. **Số đếm không khớp.** Ô "Chờ duyệt" bằng 0 khi một agent "chờ publish"; chỉ 8 trong 52 agent live được tính là
   đã kiểm định thật (màn 6). Ô đếm và danh sách việc có lẽ đọc từ hai nguồn (suy luận).

## Danh sách kiểm khi có tài khoản thử

Đầu vào cho FOG-01 `chang`: mỗi mục ghi một dòng `Quan sát | Màn | Hệ quả cho Studio | Độ chắc`, rồi cập nhật bảng
so sánh và mở câu hỏi trong spec liên quan. Câu trả lời gỡ chặn khóa quyền và mức rủi ro (`tenant-rbac`), cổng và
đóng băng (`agent-lifecycle`), chiều hạn mức (`usage-and-limits`), danh mục bước (`workflow-nodes`), phạm vi kết
nối (`connections-and-vault`) và tín hiệu lệch cấu hình (`tenant-config`).

- [ ] **A. Công ty, workspace và quyền.** Có khái niệm công ty, workspace hay bộ phận không; vai tùy chỉnh, vai quản trị nào;
      ai tạo được agent, quy trình, kết nối, ai sửa được agent của ai; có quyền theo đối tượng, bản ghi hay trường
      không; Branch, Job Code, Office Code lấy từ đâu; danh sách người được dùng để trống nghĩa là ai cũng dùng hay
      không ai; agent đọc knowledge và DataTable theo quyền của người hỏi hay của agent.
- [ ] **B. Quy trình.** Danh mục bước, cấu hình và đầu ra từng loại; cú pháp biểu thức, có kiểm kiểu khi lưu không;
      vòng lặp, song song, quy trình con; chính sách lỗi; chạy thử và lịch sử từng bước; phiên bản và khôi phục;
      "Công khai" nghĩa là gì; bản sao "EVAL" bị chặn tác động thật hay chỉ ghi trong mô tả.
- [ ] **C. Data Hub.** Xác thực endpoint; có chữ ký không; schema có được ép không (gửi sai kiểu tới endpoint của
      chính mình bằng lệnh cURL họ cấp); gửi lại cùng payload có tạo hai lượt chạy không; lịch sử event giữ bao
      lâu; giới hạn kích thước; phát lại; "Mô tả ngữ nghĩa AI" được dùng ở đâu.
- [ ] **D. Agent.** "Brain (Beta)" là gì; "Liên kết Agent" nghĩa là gì; "Ủy quyền hành động", mục "Ủy quyền" và nút
      "Hỏi trước" khác nhau thế nào; phiên bản và diff; "Cấu hình limit" theo phạm vi và đơn vị nào (token, tiền,
      lượt), cứng hay mềm, chạm trần thì sao; "Mức độ sử dụng" có những số nào; chọn model gồm nhà cung cấp nào,
      dùng khóa riêng được không.
- [ ] **E. Kiểm định.** Định dạng bộ đề và ngân hàng câu hỏi; kiểm định retrieval; kiểm định đầy đủ khác kiểm định
      nhẹ ở đâu; ngưỡng quality gate; "Đã kiểm định thật" đếm gì; agent của chính mình trượt thì Publish có bị chặn.
- [ ] **F. Skills, Plugin, MCP, Credentials.** Mô hình dữ liệu và phạm vi; ai tạo được; bí mật có hiện lại sau khi
      lưu không; OAuth có tự làm mới không; webhook gửi đi có ký không; MCP dùng transport nào; danh sách công cụ
      của máy chủ MCP có được ghim và duyệt lại khi đổi không.
- [ ] **G. Control plane.** "Lệch cấu hình" và "Component chờ xử lý" định nghĩa thế nào; đóng băng có dừng lượt
      đang chạy không, lượt đang chờ duyệt thì sao; kill có hủy phê duyệt đang chờ không; publish agent bị kill có
      bật lại nó không, có cần người thứ hai không; vì sao ô "Chờ duyệt" bằng 0 khi có agent chờ publish.
- [ ] **H. Bảo mật quan sát được, không thử tấn công.** Kiểu id trên URL của đối tượng mình tạo; chứng chỉ TLS (bên
      cấp, hạn) và cảnh báo có hiện trên máy, trình duyệt khác không; header HSTS, CSP trên trang mình được xem
      (devtools); nhật ký audit ghi gì về hành động của chính mình; phiên đăng nhập hết hạn sau bao lâu.
- [ ] **I. DataTable và kênh.** Kiểu trường, giới hạn, định dạng nhập của DataTable; ZNS có chế độ thử không; FChat
      dùng cho gì ngoài thông báo.
- [ ] **J. Thương mại.** Gói dịch vụ, đơn vị tính, giới hạn được công bố.

## Quy tắc khi dùng tài khoản thử

DO-23, agent, tạm theo khuyến nghị (a) ngày 23/10/2026; người quyết là người đặt yêu cầu cùng luật sư, trước W1.

- Chỉ dùng tài khoản được cấp, đúng mục đích thử tính năng; điều khoản của tài khoản thắng mọi dòng ở đây.
- Quan sát như người dùng thường: không quét, thu thập tự động, tạo tải hay dò lỗi, không đổi id trên URL để mở thứ
  không phải của mình, không thử vượt quyền; kiểm sâu hơn cần văn bản cho phép của chủ hệ thống.
- Chỉ thao tác trên thứ mình tạo (Publish agent của mình, gửi sự kiện tới endpoint của mình), chỉ với dữ liệu giả
  lập; không nhập dữ liệu khách hay dữ liệu cá nhân thật.
- Không chép tên người, email, prompt hay dữ liệu nghiệp vụ của họ vào repo; ảnh chụp che tên và email trước khi lưu.
- Mỗi kết luận ghi "quan sát" hay "suy luận", kèm ngày, trình duyệt và màn.

## Lựa chọn tạm mà tài liệu dựa vào

Mỗi dòng: agent, tạm theo khuyến nghị (a) ngày 23/10/2026; nếu sai thì phần nào đổi.

- DO-23: quy tắc ở mục trên. Nếu sai thì (b): nhóm H thêm phần dò bảo mật trong phạm vi và khung giờ của văn bản cho
  phép; chi tiết không vào repo, chỉ kết luận.
- DO-57: chỉ tiếng Việt với khóa chuỗi; demo và thí điểm trên host uat ở Việt Nam có chứng chỉ hợp lệ và HSTS. Nếu
  sai thì (b): song ngữ ở v1 và demo trên máy dev, nơi chứng chỉ nội bộ làm trình duyệt cảnh báo y như màn 8.

## Nguồn

- Tám ảnh chụp chang.fpt.net ngày 22/10/2026 (không nằm trong repo); brief sản phẩm B12 mục 11 (so sánh, danh sách
  kiểm, quy tắc dùng tài khoản thử) và mục 3.5 (CMP-01 tới CMP-05).
- Kế hoạch: roadmap, `requirements.md`, ADR 0100-0125, D10, D11, DO-23, DO-57, FOG-01 của area `studio`;
  [brainstorm.md](brainstorm.md) (BS10, BS24, BS27).

[fpt-aws]: https://aws.amazon.com/marketplace/pp/prodview-ljecakujwvbko
