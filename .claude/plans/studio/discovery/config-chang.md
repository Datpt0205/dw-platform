# Phân tích mô hình cấu hình của chang.fpt.net (từ ảnh chụp)

Status: needs-triage
Area: studio · Viết: 23/10/2026

File này đọc **mô hình cấu hình** của chang.fpt.net từ tám ảnh chụp demo: mỗi bề mặt cấu hình có những trường
và điều khiển nào, ngụ ý mô hình dữ liệu và luồng gì, để lái batch 2 của các spec Studio (nhất là `workflow-nodes`,
`workflow-triggers`, `agent-builder`, `agent-lifecycle`). Đây là **suy luận từ ảnh, chưa kiểm**: phải xác nhận bằng
tài khoản thử FOG-01; không phải mã của họ, không dịch ngược, không đăng nhập. Phần so sánh năng lực tổng thể và
danh sách kiểm đã nằm ở [teardown-chang.md](../discovery/teardown-chang.md) — file này **không lặp lại**, chỉ đọc
riêng góc cấu hình.

Quy ước che như teardown: không chép tên người, email, mã ban / mã chức danh / mã văn phòng nội bộ, tên quy trình
nghiệp vụ hay số định danh bảng; chỉ nói "một người dùng", "mã ban", "một quy trình". "Bề mặt" dưới đây là một **màn
cấu hình con**, nên một màn chụp (ví dụ cài đặt agent) sinh ra nhiều bề mặt.

## 1. Cài đặt agent — menu trái là mô hình cấu hình của một agent (Màn 2)

**Thấy gì**

- URL `/ai-agent/admin/chatbot/<id số nguyên>/setting?from=chatbot`; đường dẫn còn chữ `chatbot`.
- Đầu trang: tên agent, ô chọn model "GPT-4.1 mini · OpenAI" (một dòng model + nhà cung cấp), một công tắc bật/tắt.
- Menu trái chia nhóm:
    - **(không nhãn nhóm)**: Profile; Thông tin chung; Quản lý phiên bản.
    - **LOGIC & NĂNG LỰC**: Persona & Prompt; Knowledge; Agent Tool; Liên kết Agent.
    - **CẤU HÌNH**: Phân quyền & hành vi; Ủy quyền hành động; Brain (Beta); Bộ đề kiểm định; Trò chuyện.
    - **HẠN MỨC & USAGE**: Cấu hình limit; Mức độ sử dụng.

**Suy luận**

- Một agent là **một tài liệu cấu hình** sửa trong một vỏ cài đặt, menu trái là các mục của tài liệu đó (suy luận).
  Trùng hướng với Studio: agent cũng là tài liệu cấu hình bằng biểu mẫu (ADR 0117).
- Model chọn **theo agent**, một trường "model · nhà cung cấp", không thấy danh sách dự phòng hay định tuyến (suy
  luận: một model một agent). Có nhà cung cấp nước ngoài → lời gọi nhiều khả năng ra nước ngoài (suy luận).
- Công tắc ở đầu trang là **công tắc chạy ở phạm vi agent** (bật/tắt), khác với giai đoạn vòng đời ở control plane
  (suy luận).
- Nhóm menu tách **LOGIC** (làm được gì) khỏi **CẤU HÌNH** (quản trị) khỏi **HẠN MỨC** — một cách bố cục mạch lạc,
  đáng tham khảo cho sườn trang agent của Studio (suy luận).
- "Phân quyền & hành vi" gộp cả **ai được dùng** lẫn **hành vi** trong một mục; ảnh chỉ mở phần audience, các núm
  hành vi (mức tự chủ?) không thấy (suy luận: còn núm ẩn).
- Id số nguyên + đường dẫn `chatbot` → mô hình dữ liệu lớn lên từ một bảng chatbot cũ (suy luận; teardown điểm 6).

**Luồng**

Tạo agent → Profile/Thông tin chung → Persona & Prompt → gắn Knowledge, Agent Tool, Liên kết Agent → đặt Phân quyền
& hành vi và Ủy quyền hành động → chạy Bộ đề kiểm định → lên phiên bản ở Quản lý phiên bản → đặt Cấu hình limit →
theo dõi ở Mức độ sử dụng. Toàn bộ agent cấu hình tại chỗ; phát hành nhiều khả năng từ control plane (Màn 6).

## 2. Phân quyền & hành vi — audience theo thuộc tính nhân sự (Màn 2)

**Thấy gì**

- Ba danh sách chọn nhiều, mỗi danh sách có ô "Tìm kiếm...", "Chọn tất cả" / "Bỏ chọn tất cả", mỗi dòng một ô tích,
  thanh cuộn, và chỉ báo bên phải "Đã chọn tất cả": **Branch** (mã ban + tên ban), **Job Code** (mã chức danh + tên),
  **Office Code** (mã văn phòng).
- Trong ảnh không ô tích nào được tích trong khi chỉ báo ghi "Đã chọn tất cả".

**Suy luận**

- Audience = **ai được dùng agent**, lọc theo ba chiều thuộc tính nhân sự; chưa rõ ba chiều kết hợp bằng AND hay OR
  (suy luận).
- Thuộc tính lấy từ một hệ thống nhân sự; mã là định danh ổn định (suy luận).
- "Đã chọn tất cả" khi không ô nào tích → nhiều khả năng **để trống nghĩa là tất cả** (mặc định mở, `failure-modes`
  #7) (suy luận; kiểm ở FOG-01).
- Đây là **quyền thô**: chỉ chặn cửa mở agent, không có quyền trên bản ghi hay trường để quyết agent đọc được gì
  (suy luận từ chỗ vắng).

**Luồng**

Admin chọn tổ hợp thuộc tính → lưu thành audience của agent → người có thuộc tính khớp mới mở/dùng được agent. Không
thấy bước nào gắn audience với phạm vi dữ liệu mà agent truy cập.

## 3. Bước "AI Agent" trong quy trình — node có ba mặt, đầu ra kiểu hóa (Màn 4)

**Thấy gì**

- Ba cột: **Input** (0 biến, "No upstream variables — connect nodes to see available inputs"), **Setup**, **Output**
  (5 biến "available for downstream nodes").
- Setup:
    - **Chọn Trợ lý** (Required), dropdown "Chọn một trợ lý AI..."; gợi ý "có thể tạo và cấu hình trợ lý trong mục Trợ lý".
    - **Kiểu đầu vào** (Required) = "Câu Hỏi Đơn" (dropdown).
    - **Nội dung câu hỏi** (Required), textarea, placeholder dạng `#{{node_id.ma_don_hang}}`; gợi ý "Dùng
      `{{nodeId.ten_bien}}` để chèn dữ liệu từ các bước trước".
    - **Dữ liệu bổ sung (Bối cảnh)** với "+ Add Item"; mỗi mục gồm **biến nguồn** (`{{nodeId.bien}}`) + **nhãn mô tả
      cho AI**.
    - **Tệp đính kèm** với "+ Add Item"; ảnh jpg/png/gif/webp; tài liệu PDF, DOCX, XLSX, TXT, CSV, JSON, XML, HTML,
      Markdown; **không nhận** Office cũ (.doc, .ppt); cho dùng biến; tài liệu **cắt ở 100.000 ký tự**; ảnh base64
      **tối đa 5 MB**.
- Output (5 biến, mỗi biến có kiểu và mô tả in sẵn):
    - `error` (object) — "Lỗi khi chọn 'Bỏ qua và trả lỗi làm kết quả': { message, errorStatus, errorData }".
    - `response` (any) — "Phản hồi từ AI".
    - `toolCalls` (array) — "Danh sách các công cụ đã gọi (tool, input, output, isSuccess)".
    - `documentReferences` (array) — "Danh sách tài liệu được trích xuất (fileId, chunkId, fileName, link)".
    - `metadata` (object) — "Thông tin bổ sung".
- Nút Hủy bỏ / Lưu thay đổi. Id bước = tiền tố loại + số thứ tự (`agent_3`).

**Suy luận**

- Node có **ba mặt rõ ràng**: Input (biến kiểu hóa từ bước trước), Setup (biểu mẫu), Output (biến có tên và kiểu) —
  một mô hình cổng kiểu hóa sạch (suy luận). Trùng hướng Studio: `workflow-nodes` khai chính sách lỗi trong sổ đăng
  ký loại bước (ADR 0112).
- **Đầu ra cố định theo loại bước và mô tả tại chỗ.** `documentReferences` cho thấy có trả về trích dẫn RAG
  (fileId, chunkId, fileName, link); `toolCalls` lộ tool/input/output/isSuccess để quan sát; `error` chỉ có khi chọn
  chính sách lỗi "Bỏ qua và trả lỗi làm kết quả" (suy luận: chính sách lỗi theo bước, chọn rồi mới có biến `error`).
- Chèn biến `{{nodeId.ten_bien}}` là **chuỗi mẫu**, không thấy kiểm kiểu khi lưu (suy luận). Studio khác: CEL kiểm
  kiểu khi phát hành (ADR 0114), giá trị bọc trong khối `<input>` (ADR 0010, YC48), đầu ra kiểm phía server (YC47).
- "Dữ liệu bổ sung" mỗi mục là (biến nguồn + nhãn mô tả cho AI) — **cùng ý "mô tả ngữ nghĩa cho AI"** như Data Hub
  (suy luận): nhãn đi vào prompt để model hiểu bối cảnh.
- Giới hạn tệp là **kiểm cụ thể**: cắt 100.000 ký tự (mất dữ liệu âm thầm — rủi ro), ảnh base64 5 MB.
- "Kiểu đầu vào = Câu Hỏi Đơn" ngụ ý còn kiểu khác (suy luận: ví dụ nhiều câu / theo lô).

**Luồng**

Builder thêm bước AI Agent → chọn một trợ lý có sẵn → viết câu hỏi mẫu tham chiếu biến bước trước → thêm mục bối cảnh
và tệp → bước sau đọc các biến đầu ra kiểu hóa. Trợ lý là thực thể tách rời, bước chỉ **tham chiếu** nó.

## 4. Danh sách quy trình và trình kích hoạt (Màn 3)

**Thấy gì**

- `/ai-agent/admin/option/workflow`, ứng dụng "AIAgent"; nút "Tạo Flow".
- Lọc: ô tìm kiếm, **Trạng thái** ("Tất cả"), **Loại trigger** ("Tất cả"), **Chọn bộ phận**, **Email người tạo**;
  nút chuyển lưới/danh sách.
- Thẻ quy trình: tên, mô tả, **trạng thái "Active"** (chấm xanh), **nhãn trình kích hoạt** (DataHub Event / Manual /
  Webhook / Schedule), **nhãn "Công khai"**, **số lượt chạy**, **lần chạy cuối** (dấu thời gian), email người tạo +
  giờ tạo; nút chạy / sửa / bật-tắt / xóa.
- Vài thẻ là công cụ kiểm định dựng bằng chính quy trình: mô tả tự ghi "(private)" và "no side effects" nhưng thẻ
  vẫn mang nhãn "Công khai".

**Suy luận**

- Mô hình dữ liệu một quy trình (suy luận): tên, mô tả, trạng thái (Active / tắt), **đúng một loại trình kích hoạt**,
  một cờ hiển thị ("Công khai"), bộ đếm lượt chạy, người tạo, các dấu thời gian.
- **"Công khai" là một boolean hiển thị trên quy trình** (suy luận); nhãn và cấu hình thật là hai nguồn (thẻ EVAL
  ghi "private" mà nhãn "Công khai" — teardown điểm 7). Studio không có cờ này: tầm thấy theo vai và workspace sở
  hữu (ADR 0113).
- Bốn trình kích hoạt; DataHub Event và Webhook đều vào từ ngoài → suy luận DataHub Event là endpoint **có schema**
  (Màn 5), Webhook là thô; Schedule là theo lịch; Manual là nút/được gọi như công cụ.
- "Không tác động" của bản EVAL chỉ là **quy ước văn bản**, không ép ở máy (suy luận). Studio ép tại executor bằng
  chế độ Mô phỏng (YC34, ADR 0111).
- Lọc theo bộ phận và email người tạo → quy trình gắn người tạo và lọc theo bộ phận (suy luận), hợp với một tổ chức.

**Luồng**

Tạo Flow → chọn trình kích hoạt → vẽ trên canvas → bật Active → lượt chạy cộng vào bộ đếm. Danh sách là bề mặt vận
hành (chạy/bật-tắt/xóa ngay trên thẻ).

## 5. Data Hub — nguồn dữ liệu và schema có "mô tả ngữ nghĩa AI" (Màn 5)

**Thấy gì**

- `/ai-agent/admin/option/data/<id chuỗi ngẫu nhiên>` — id **ngẫu nhiên**, khác id agent (số nguyên).
- "Data Hub › Chỉnh sửa nguồn dữ liệu — Thiết lập một endpoint để nhận dữ liệu và cấu hình các Agent nhằm hiểu dữ
  liệu đầu vào". Hai bước: **1. Cơ bản**, **2. Schema**.
- Nút đầu trang: **Lịch sử Event**, **Sao chép CURL**, **Vô hiệu hóa**, **Xóa**.
- Bước 2 "Định nghĩa schema": nút **Tải lên tệp JSON** / **Dán JSON**. Bảng cột:
    - **KHÓA TRƯỜNG** (key).
    - **KIỂU DỮ LIỆU**: thấy "Text (String)", "Date/Time (Number)".
    - **MÔ TẢ NGỮ NGHĨA AI (QUAN TRỌNG!)** — mô tả ngôn ngữ tự nhiên cho mỗi trường.
    - **BẮT BUỘC** (ô tích, mọi dòng ví dụ đều tích).
    - nút xóa dòng.

**Suy luận**

- Nguồn dữ liệu = **một endpoint vào + một schema khai báo**, trình thuật sĩ hai bước (suy luận).
- Schema là **danh sách trường phẳng** `{khóa, kiểu, mô tả ngữ nghĩa AI, bắt buộc}`. Tập kiểu nhỏ; "Date/Time
  (Number)" gợi ý lưu mốc thời gian dạng số (epoch) (suy luận).
- **"Mô tả ngữ nghĩa AI (QUAN TRỌNG!)"** nhấn mạnh rằng mô tả **đi vào prompt** để agent hiểu payload tùy ý (suy
  luận). Đây là mẫu cấu hình nổi bật nhất của họ.
- Dán/tải JSON mẫu để **suy ra khóa và kiểu** (suy luận).
- "Sao chép CURL" cấp sẵn một request đúng cho integrator; **không thấy** xác thực/chữ ký trên màn này (suy luận).
  Studio khác: chữ ký Standard Webhooks hoặc token tĩnh, chống trùng, từ chối sai chữ ký/lệch giờ/sai lược đồ mà
  không tạo lượt chạy (YC42, YC43).
- "Vô hiệu hóa" = tắt mềm (giữ, ngừng nhận) khác "Xóa" (suy luận).
- Mọi dòng bắt buộc đều tích → mặc định "bắt buộc" có thể là true (suy luận).
- **Không thấy trường phân loại dữ liệu cá nhân.** Studio bắt mỗi trường mang `pd_category`, thiếu thì từ chối tạo
  (YC84, ADR 0106).
- Id nguồn ngẫu nhiên trong khi id agent là số nguyên → **hai quy ước id trong một sản phẩm** (teardown điểm 3).

**Luồng**

Tạo nguồn → bước Cơ bản → bước Schema (dán JSON hoặc thêm trường, viết mô tả ngữ nghĩa AI, đánh bắt buộc) → Sao chép
CURL → integrator gửi sự kiện → sự kiện chạy một quy trình kích hoạt kiểu DataHub Event → xem lại ở "Lịch sử Event".

## 6. Control plane — vòng đời agent, cổng phát hành, đóng băng (Màn 6, 7)

**Thấy gì**

- "Agent Studio — Control plane — toàn bộ nhân sự số theo vòng đời. Ưu tiên xử lý: chờ duyệt & lệch dependency."; nút
  **Đóng băng hệ thống**, **Tạo agent**.
- **Tổng quan đội ngũ**, bấm ô để lọc: **22 Nháp**, **0 Kiểm định**, **0 Chờ duyệt**, **52 Đang chạy (live)**, **0
  Đã gỡ**, **4 Bị kill**.
- "**Đã kiểm định thật: 8/52**", chữ nhỏ "chỉ tính lượt có bộ đề và có chấm điểm" (và đọc như "sơ bộ 0 · trượt 9",
  ảnh mờ).
- "**Cảnh báo cần chú ý (27)**" — chip theo loại: **Đã bị tắt (kill)**, **Nháp để lâu chưa publish**, **Lệch cấu
  hình chưa xử lý**, **Kiểm định dưới ngưỡng**.
- "**Agent chờ xử lý (17)**": trái "Kiểm định đầy đủ Đạt — chờ publish (1)"; phải "Cần xử lý — chưa / đang / trượt
  Kiểm định đầy đủ (5)". Mỗi dòng có **Xem diff** và nút **Publish** (xanh). Năm dòng phải đều ghi "Kiểm định đầy đủ
  trượt"; một trong số đó cũng nằm trong cảnh báo "Đã bị tắt (kill)".
- "**Component chờ xử lý (41)**".

**Suy luận**

- **Giai đoạn vòng đời**: Nháp → Kiểm định → Chờ duyệt → Đang chạy (live) → Đã gỡ, cộng trạng thái Bị kill (suy
  luận: 6 ô). Studio: Nháp, Đang kiểm định, Chờ duyệt, **Đang dùng**, Đã gỡ (YC70) — Studio đổi "live" thành "Đang
  dùng" và để "Đang chạy" cho lượt chạy (YC75).
- **Cổng phát hành có vẻ chỉ là khuyến nghị**: dòng "Kiểm định đầy đủ trượt" vẫn có nút Publish bật, một agent đang
  bị kill cũng vậy (suy luận: server không chặn; một lần publish có thể bật lại agent bị kill mà không qua người thứ
  hai). Studio: server từ chối phát hành khi cổng trượt, cần người khác tác giả duyệt (YC70, YC73, ADR 0120).
- "**Đã kiểm định thật 8/52**" = chỉ 8/52 agent live thực sự được chấm trên bộ đề — một **chỉ số độ tin** mà control
  plane phơi ra (đáng học).
- "**Lệch cấu hình chưa xử lý**" là cảnh báo hạng nhất → có tín hiệu lệch phiên bản/phụ thuộc (suy luận). Studio: so
  sánh phiên bản + lệch cấu hình (YC75), bằng chứng gắn mã băm định nghĩa (ADR 0120, 0109).
- **Đóng băng là công tắc toàn cục; kill theo agent** (suy luận). Studio: đóng băng nền tảng + theo tenant (YC72),
  tắt khẩn cấp theo agent/quy trình (YC73).
- **Số đếm không khớp**: "Chờ duyệt = 0" trong khi có agent "chờ publish" → ô đếm và danh sách việc đọc hai nguồn
  (teardown điểm 9). Studio: tổng quan đọc dữ liệu theo quyền người xem, không từ trace (YC75).
- "**Component chờ xử lý (41)**" → thành phần (prompt, công cụ, tri thức) có vòng đời/hộp việc riêng (suy luận).

**Luồng**

Tác giả dựng → chạy kiểm định đầy đủ → nếu đạt thì vào "chờ publish" kèm Xem diff → Publish (lẽ ra cần đạt + người
thứ hai) → live → có thể bị kill → "Đóng băng hệ thống" dừng toàn hệ.

## 7. Mục thiết lập — Agent Tool, Skills, Credentials, Plugin, MCP; agent gọi quy trình (Màn 2, 3, 1)

**Thấy gì**

- Nav "THIẾT LẬP AGENT": **Skills**, **Credentials**, **Workflow** (Danh sách, Lịch sử, Quản lý Task), **Plugin**;
  nhóm "KHO DỮ LIỆU & TRI THỨC" bên dưới; **MCP** xuất hiện trên các màn sau. Còn "Thư viện Agent (Deprecated)".
- Trong cài đặt agent: **Agent Tool**, **Liên kết Agent**, **Knowledge**.
- Màn 1 (chat người dùng cuối): agent hiện "Đã suy nghĩ · 1 bước" rồi "Chạy quy trình ..." — **agent gọi một quy
  trình đã phát hành như một công cụ**. Còn nút "Hỏi trước" trong ô soạn, "Nhật ký audit" và "Lịch sử" ở nav.

**Suy luận**

- Năng lực **tách theo module**: Skills, Credentials, Agent Tool, Plugin, MCP là các sổ đăng ký riêng (suy luận).
  Studio gom khác đi: `tools-and-skills` (công cụ là dữ liệu tenant qua một executor, ADR 0116), `connections-and-vault`
  (kho bí mật + một client ra ngoài, ADR 0115), `mcp-client` (cổng MCP); **không có "plugin"** — công cụ theo loại
  và bộ công cụ có phiên bản.
- **Credentials là kho bí mật** (suy luận); phạm vi không thấy. Studio: mã hóa dưới khóa riêng tenant, kết nối dùng
  chung theo workspace (YC61, YC62).
- **Agent gọi quy trình như công cụ** (Màn 1) → điều phối bằng agent gọi quy trình/agent liên kết (suy luận). Studio:
  quy trình dùng như công cụ (W2), agent điều phối không giữ công cụ tác động, sâu ≤ 3, không vòng (YC57); đường trộn
  đầu vào ngoài + dữ liệu riêng + tác động ra ngoài phải qua người (YC67, ADR 0125).
- **"Liên kết Agent"** = nối agent–agent (agent con / liên kết) (suy luận). Studio: liên kết/con luôn hẹp hơn người
  gọi (YC57).
- **MCP là mục riêng** → máy chủ MCP đăng ký tập trung (suy luận). Studio: định nghĩa công cụ MCP ghim + người khác
  người đăng ký duyệt, cổng tách không giữ bí mật (YC68).
- **"Plugin"** — chưa rõ nội dung; Studio cố ý không có khái niệm này (bỏ qua).

**Luồng**

Admin đăng ký Credentials → dựng Skills/Agent Tool/Plugin/MCP → gắn vào agent (Agent Tool, Liên kết Agent, Knowledge)
hoặc vào bước quy trình → ở chat agent gọi công cụ/quy trình. "Nhật ký audit" và "Lịch sử" là bề mặt quan sát.

## Đối chiếu sang Studio

Mỗi dòng là một bề mặt cấu hình con (theo thứ tự màn), ánh xạ tới spec Studio sở hữu nó. "Bỏ qua" là nơi Studio cố ý
khác vì nền tảng đã giải (đa tenant, workspace, quyền trên bản ghi/trường, phiên bản có bản kê, hai người). Mã YC ở
`requirements.md`, ADR ở `docs/adr/0100`–`0125`.

| Bề mặt của họ                                                                          | Studio làm ở spec       | Học theo / Cải tiến / Bỏ qua | Vì sao                                                                                                                                                  |
| -------------------------------------------------------------------------------------- | ----------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cài đặt agent: Persona & Prompt, Trò chuyện, công tắc bật/tắt (1)                      | `agent-builder`         | Học theo                     | Agent là tài liệu cấu hình bằng biểu mẫu (ADR 0117); YC54, YC56; lời chào + tối đa 6 gợi ý + "Hỏi trước"                                                |
| Ô chọn model theo agent (1)                                                            | `agent-builder`         | Cải tiến                     | Hồ sơ model trong danh sách gói cho phép (YC54, YC85); lộ trình dữ liệu VN áp và ghi mỗi lời gọi (ADR 0123, 0118)                                       |
| Bộ đề kiểm định + Quản lý phiên bản trong cài đặt agent (1)                            | `agent-lifecycle`       | Học theo                     | Có bộ đề + phiên bản; Studio gắn bằng chứng vào mã băm định nghĩa, đổi phụ thuộc là mất bằng chứng (ADR 0120, 0109)                                     |
| Phân quyền & hành vi: audience theo mã ban / chức danh / văn phòng (2)                 | `tenant-rbac`           | Cải tiến                     | Audience chỉ quyết **ai mở** agent (YC55); đọc gì theo quyền người hỏi trên bản ghi (ADR 0105) và trường (ADR 0106); thuộc tính là `org-and-principals` |
| Bước "AI Agent": Input/Setup/Output, đầu ra kiểu hóa, chính sách lỗi, tệp đính kèm (3) | `workflow-nodes`        | Học theo                     | Đầu ra kiểu hóa + chính sách lỗi khai ở sổ loại bước (ADR 0112); Studio kiểm server và bọc `<input>` (YC47, YC48)                                       |
| Ba cột node + chèn `{{nodeId.var}}` (3)                                                | `workflow-builder-ui`   | Học theo                     | Canvas là ngoại lệ UI được duyệt (ADR 0101), YC39; nhưng biểu thức là CEL kiểm kiểu khi phát hành (ADR 0114)                                            |
| Danh sách quy trình + 4 trình kích hoạt + cờ "Công khai" (4)                           | `workflow-triggers`     | Cải tiến + Bỏ qua            | Trình kích hoạt chỉ xin lượt chạy (ADR 0113); **bỏ cờ "Công khai"** — tầm thấy theo vai và workspace sở hữu                                             |
| Data Hub: schema + mô tả ngữ nghĩa AI + Sao chép CURL + Lịch sử Event (5)              | `workflow-triggers`     | Học theo + Cải tiến          | Học mô tả ngữ nghĩa AI; thêm chữ ký/chống trùng, id ≥128 bit, `pd_category` trên trường (YC42, YC43, YC84)                                              |
| Control plane: ô giai đoạn, 8/52, chip cảnh báo, Publish, đóng băng (6)                | `agent-lifecycle`       | Học theo + Cải tiến          | Học "đã kiểm định thật" + drift + Xem diff; cổng chặn ở server + hai người (YC70, YC73); tổng quan đọc theo quyền (YC75)                                |
| Agent Tool / Skills / Plugin + agent gọi quy trình (7)                                 | `tools-and-skills`      | Học theo + Bỏ qua            | Công cụ là dữ liệu tenant qua một executor (ADR 0116); **không có "plugin"**; bộ ba nguy hiểm qua người (YC67, ADR 0125)                                |
| Credentials (7)                                                                        | `connections-and-vault` | Cải tiến                     | Bí mật mã hóa dưới khóa tenant, kết nối dùng chung theo workspace, tắt/thu hồi có hiệu lực trước lần gọi sau (YC61, YC62)                               |
| MCP là mục riêng (7)                                                                   | `mcp-client`            | Cải tiến                     | Định nghĩa công cụ MCP ghim + người thứ hai duyệt trên đúng văn bản model đọc; cổng tách không giữ bí mật (YC68)                                        |
| Cấu hình limit + Mức độ sử dụng theo agent (1)                                         | `usage-and-limits`      | Học theo + Cải tiến          | Sổ theo lượt gọi + màn Mức độ sử dụng (YC76); Studio giữ trước bằng lease và một chuỗi phạm vi hạn mức (YC77, ADR 0121)                                 |
| Nhật ký audit + Lịch sử chạy (7)                                                       | `telemetry-and-audit`   | Cải tiến                     | Tenant đọc lịch sử/sử dụng/audit từ Postgres dưới RLS, không từ trace (ADR 0122); span không nội dung (YC80, YC82, YC83)                                |
| Quy trình nghiệp vụ dựng sẵn (ví dụ của họ) (4)                                        | `marketing-pilot`       | Cải tiến                     | Studio ship gói Marketing **chỉ qua bề mặt tenant** (YC2), không mã nghiệp vụ trong nền tảng (ADR 0100), YC94–YC100                                     |

## Đang học theo mạnh nhất

Các mẫu cấu hình đáng lấy, kèm chỗ đưa vào spec:

1. **Mô tả ngữ nghĩa AI cho từng trường** (Data Hub, Màn 5; và "nhãn mô tả cho AI" ở mục bối cảnh của node, Màn 4).
   Mỗi trường mang một câu mô tả để model hiểu payload/bản ghi tùy ý. Đưa vào `custom-objects` (mô tả trường),
   `workflow-triggers` (schema nguồn dữ liệu) và `workflow-nodes` (mục bối cảnh). Lưu ý: ở Studio mô tả đó cũng là
   dữ liệu từ ngoài, phải bọc `<input>` khi vào prompt (YC48).
2. **Đầu ra node kiểu hóa, có tên, mô tả tại chỗ**: `response` / `toolCalls` / `documentReferences` / `metadata` /
   `error`. Đặc biệt `documentReferences` (fileId, chunkId, fileName, link) cho trích dẫn, `toolCalls` (tool, input,
   output, isSuccess) cho quan sát, và `error` là đầu ra **tùy chọn** theo chính sách lỗi của bước. Đưa vào
   `workflow-nodes` (sổ đăng ký loại bước, YC47) và `agent-builder` (trích dẫn bằng link, YC56).
3. **Control plane với chỉ số kiểm định thật và cảnh báo lệch cấu hình**: ô "Đã kiểm định thật 8/52" (chỉ đếm lượt
   có bộ đề và có chấm) là một chỉ số độ tin thẳng thắn; các chip "kill / nháp để lâu / lệch cấu hình / kiểm định
   dưới ngưỡng" là một phân loại cảnh báo gọn. Đưa vào `agent-lifecycle` (tổng quan đội ngũ, YC75) — nhưng đọc theo
   quyền người xem và cổng chặn ở server.
4. **Cấu hình limit và mức độ sử dụng theo agent** đặt ngay trong cài đặt agent. Đưa vào `usage-and-limits` (YC76,
   YC77) — Studio mở rộng thành một chuỗi phạm vi (gói, tenant, workspace, agent/quy trình, người dùng, lượt chạy)
   giữ trước bằng lease Postgres (ADR 0121).
5. **Audience bằng thuộc tính tổ chức** (mã ban / chức danh / văn phòng) dưới dạng chọn-nhiều có tìm kiếm và chọn
   tất cả — một UX mục tiêu tốt. Đưa vào `agent-builder` làm bộ chọn "Người được dùng" (YC54) — nhưng ở Studio nó
   **chỉ quyết ai mở agent** (YC55), và mặc định phải đóng (không khớp = không tìm thấy), không fail-open.

(Kế đến, nếu còn chỗ: ba cột Input/Setup/Output với tự khám phá biến bước trước và chèn `{{nodeId.var}}`; nút "Sao
chép CURL" cấp request đúng cho integrator; "Xem diff" trước publish và hộp "Component chờ xử lý".)

## Cần tài khoản thử để xác nhận (FOG-01)

Chi tiết cấu hình ảnh không cho thấy; mỗi mục để account research chụp lại:

- **Cài đặt agent.** Kiểm và mặc định của Persona & Prompt (bắt buộc? giới hạn độ dài?); "Brain (Beta)" cấu hình gì;
  "Ủy quyền hành động" đặt những hành động/ngưỡng duyệt/mức tự chủ nào; "Trò chuyện" đặt gì (lời chào, số gợi ý);
  "Phân quyền & hành vi" còn núm hành vi nào ngoài audience; ba chiều audience kết hợp AND hay OR; để trống audience
  nghĩa là ai cũng dùng hay không ai (fail-open?); ô model gồm nhà cung cấp nào, dùng khóa riêng của công ty được không.
- **Bước quy trình.** Danh mục đầy đủ loại node và Setup/Output từng loại; các lựa chọn "Kiểu đầu vào" ngoài "Câu Hỏi
  Đơn"; đủ các lựa chọn chính sách lỗi; đầu ra có kiểm kiểu khi lưu không; cú pháp biểu thức và có kiểm kiểu không;
  vòng lặp / song song / quy trình con cấu hình thế nào.
- **Data Hub.** Tập kiểu đầy đủ; "Date/Time (Number)" có phải epoch; xác thực/chữ ký endpoint; schema có **ép** không
  (gửi sai kiểu tới endpoint của chính mình xem có bị từ chối); cửa sổ chống trùng; lịch sử event giữ bao lâu; giới
  hạn tần suất/kích thước; "mô tả ngữ nghĩa AI" **có thực sự vào prompt** không và ở chỗ nào.
- **Vòng đời / control plane.** Định dạng bộ đề và cấu hình bộ chấm; ngưỡng quality gate cấu hình ở đâu và cổng **có
  chặn publish ở server** không (thử Publish một agent của mình đang trượt); định nghĩa "lệch cấu hình" và cái gì
  kích nó; định nghĩa "Component chờ xử lý"; đóng băng có dừng lượt đang chạy không; kill có hủy phê duyệt đang chờ,
  publish lại có bật lại agent bị kill không.
- **Hạn mức / usage.** Chiều hạn mức (token/tiền/lượt), cứng hay mềm, phạm vi (agent/người dùng), "Mức độ sử dụng"
  vẽ số gì, chu kỳ reset.
- **Skills / Credentials / Plugin / MCP.** Mô hình dữ liệu và phạm vi mỗi loại; bí mật có hiện lại sau khi lưu không;
  MCP dùng transport nào và luồng đăng ký/duyệt lại khi đổi; Skills có cấp thêm công cụ không; "Plugin" thực chất là gì.
- **Quản lý phiên bản.** Cách đánh số phiên bản; độ chi tiết của "Xem diff"; khôi phục.
- **Thuộc tính audience.** Branch / Job Code / Office Code đồng bộ từ hệ thống nhân sự ra sao (đẩy/kéo, nhịp nào).
