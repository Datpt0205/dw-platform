# Tuân thủ PDPL, Luật AI và an toàn agent cho Studio

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio xử lý dữ liệu cá nhân của khách hàng của công ty khách (lead, khách hàng) trên nền tảng đặt tại
Việt Nam, gọi model có thể ở nước ngoài và gửi tin marketing qua Zalo và email. Lát này biến các nghĩa vụ
PDPL (Luật 91/2025/QH15 và Nghị định 356/2025/ND-CP, hiệu lực 1/1/2026) và Luật AI (134/2025/QH15, hiệu
lực 1/3/2026) thành kiểm soát của sản phẩm: phân loại dữ liệu cá nhân một chủ, Lộ trình dữ liệu ở model
gateway, Sàn gửi tin có đồng ý, phân tích bộ ba nguy hiểm khi gửi kiểm định, và lớp lưu giữ
(ADR-0106 (Accepted), ADR-0123 (Accepted), ADR-0124 (Accepted), ADR-0125 (Accepted)). Khi chưa có ý kiến luật sư
(ticket 02), lát Marketing chỉ chạy trên lead giả lập (YC89, do marketing-pilot ép). W1 phục vụ YC71,
YC84, YC85, YC86 và YC88, một phần YC82. DO-53 (Studio có phải dịch vụ xử lý dữ liệu cá nhân cần giấy
chứng nhận trước tenant trả phí đầu tiên) không chặn W1: tới khi có văn bản của luật sư chỉ dùng dữ liệu
giả lập hay nội bộ, và câu trả lời là một điều kiện vào chạy bóng (YC99).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Định nghĩa công cụ khai `data_classification` nhưng không quyết định nào đọc
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:54`). Thiếu: không trường nào phân
  loại dữ liệu cá nhân, một cờ khai mà không đọc (`failure-modes.md` #1).
- Thang mật `internal`, `confidential`, `restricted` chấm tài liệu và trí nhớ, không chấm trường
  (`packages/python/dw_knowledge/src/dw_knowledge/contracts.py:23-27`). Ràng buộc: Loại dữ liệu cá nhân là
  một trục riêng, không phải thang mật.
- `redaction` hứa "secrets/PII" nhưng chỉ che bí mật
  (`packages/python/dw_observability/src/dw_observability/redaction.py:1`). Thiếu: che dữ liệu cá nhân.
- `ModelRoute` mang nhà cung cấp, model, giá nhưng không `data_location`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`). Thiếu: nơi xử lý mỗi
  tuyến; không có nơi xử lý nghĩa là nước ngoài.
- Chép lời gửi tới một URL nước ngoài cố định
  (`packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`). Ràng buộc: một đường gọi
  model ra ngoài không qua cổng lộ trình.
- Thang tự chủ cho A3 chạy công cụ `external` khi không có người, A4 luôn vậy; hai sàn `critical` và
  `approval_policy: always` giữ ở mọi mức
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`). Ràng buộc: sàn bộ ba nguy
  hiểm chỉ siết thêm trên hai sàn này.
- `autonomy_level` khai mà không đọc (`configs/workers/README.md:14-17`). Ràng buộc: chú thích cũ,
  foundations-hardening sửa; sàn bộ ba đọc phân tích khi gửi kiểm định, không ở runtime.
- Chặng nội bộ chạy plaintext: DSN PostgreSQL không TLS (`infra/compose/docker-compose.yml:256`), Qdrant
  qua http (`:279`). Ràng buộc: TLS chặng nội bộ là W2.
- Chỉ có đường gửi tới thành viên qua `platform.channel_deliveries`, kiểm lại tư cách thành viên khi gửi
  (`db/migrations/versions/5a25154e0296_platform_channel_deliveries.py:125-132`). Thiếu: đường tới lead,
  Sàn gửi tin và các Bản ghi đồng ý.
- Gateway hiện định tuyến lên các nhà cung cấp chưa ai định vị (`.env.example:177-178`). Chưa rõ: nơi xử
  lý mỗi bí danh (FOG-18); chưa khai thì coi là nước ngoài.

## Mục tiêu

### R1 — Loại dữ liệu cá nhân là một chủ, mọi trường mang loại

Mọi trường (đối tượng, nguồn dữ liệu, thuộc tính lược đồ công cụ) mang một Loại dữ liệu cá nhân từ một
module kernel, và tạo trường thiếu loại bị từ chối (YC84).

- R1.1 NẾU một yêu cầu tạo một trường không có `pd_category`, THÌ API chủ bảng PHẢI trả 422 `validation_failed`
  với `errors[].code` `pd_category_required` và con trỏ tới trường đó (app-standards:R1.3), và không tạo trường.
- R1.2 Một ràng buộc CHECK `pd_category` của một bảng định nghĩa trường PHẢI bằng đúng danh sách của
  `dw_kernel.personal_data` (`none`, `basic`, `sensitive`).
- R1.3 NẾU một bảng định nghĩa trường nhận một giá trị `pd_category` hay `sensitive_type` ngoài danh sách
  kernel, hay một giá trị thiếu nhãn tiếng Việt, THÌ test drift PHẢI đỏ.
- R1.4 ĐỐI VỚI một trường `Nhạy cảm`, bảng định nghĩa trường PHẢI mang `sensitive_type` từ danh sách Nghị
  định 356 Điều 4.1, còn trường `Cơ bản` hay `Không` thì không mang.

### R2 — Lộ trình dữ liệu ở model gateway, mọi lời gọi model qua cùng cổng

Mọi lời gọi model của Studio theo Lộ trình dữ liệu chặt nhất của công ty, workspace và agent, mặc định
Chỉ trong Việt Nam, ghi lộ trình trên từng lời gọi (YC85; ADR-0123 (Accepted)).

- R2.1 KHI một adapter chạm model chuẩn bị gửi nội dung, `ResidencyGate` PHẢI lấy Lộ trình dữ liệu chặt
  nhất của công ty, workspace và agent, và ghi `data_route_class`, `data_location` và `processor` lên lời
  gọi, lượt chạy và span.
- R2.2 NẾU Lộ trình là Chỉ trong Việt Nam và tuyến model có `data_location` là `foreign` hay không khai,
  THÌ `ResidencyGate` PHẢI từ chối trước khi gửi byte nào, và adapter không gọi nhà cung cấp.
- R2.3 Mọi adapter chạm model (hai cửa của ModelResolver, embedding, rerank, trích xuất tài liệu, chép
  lời, tóm tắt, chấm eval) PHẢI qua `ResidencyGate` trước khi gửi nội dung ra ngoài.
- R2.4 NẾU một workspace hay phiên bản agent đặt Lộ trình lỏng hơn Lộ trình của công ty, THÌ API cấu hình
  PHẢI trả 422 và không đổi dòng nào.
- R2.5 NẾU một người nới Lộ trình của công ty hay workspace về phía ra nước ngoài mà không có người duyệt
  thứ hai, hay không có Xác nhận chuyển dữ liệu ra nước ngoài còn hạn nêu `processor`, THÌ API cấu hình
  PHẢI từ chối và không đổi lộ trình.
- R2.6 NẾU một phiên bản có đường đưa giá trị trường dữ liệu cá nhân vào prompt trên một tuyến ra nước
  ngoài, THÌ thao tác gửi kiểm định PHẢI trả 422 `residency_refused` kèm đường đó và không chuyển phiên bản
  khỏi Nháp.
- R2.7 NẾU một người gửi `PATCH /api/v1/admin/tenant` nới `data_route_class` của công ty về phía ra nước
  ngoài, THÌ API quản trị PHẢI trả 409 `second_person_required` và không đổi lộ trình, vì W1 không có đường
  nới (nới qua tenant-config là W2, R2.5).
- R2.8 KHI quản trị viên siết `data_route_class` của công ty hay workspace, API quản trị PHẢI áp thay đổi với
  một người và ghi audit `residency.class_changed` trong cùng giao dịch.

### R3 — Sàn gửi tin kiểm trong ToolExecutor

Một tin marketing tới một người chỉ rời đi khi qua Sàn gửi tin kiểm trong ToolExecutor so với các Bản ghi
đồng ý của nền tảng (YC86; ADR-0124 (Accepted)).

- R3.1 NẾU một lead không có Bản ghi đồng ý đúng mục đích và kênh còn hiệu lực, đang ở Danh sách chặn gửi,
  ngoài Khung giờ không gửi, hay vượt Giới hạn tần suất gửi, THÌ ToolExecutor PHẢI trả `blocked:<lý do>`,
  ghi `marketing.send_refused` và không gọi nhà cung cấp.
- R3.2 KHI ToolExecutor chạy một hành động connector mà manifest đánh dấu là gửi tin, nó PHẢI hỏi
  `SendAdmissionPort` trước khi egress client gửi, cho mọi đường (node `tool.call`, lời gọi công cụ của
  agent, quy trình dùng như công cụ).
- R3.3 KHI một tin rời đi, ToolExecutor PHẢI ghi một dòng nhật ký gửi mang `consent_record_id` đã dựa vào
  và một sự kiện `marketing.sent`.
- R3.4 KHI một người bấm link hủy đăng ký, route công khai hủy đăng ký PHẢI ghi một dòng Danh sách chặn gửi
  trong vòng 5 phút, để Sàn gửi tin kiểm lại một tin đang chờ trước khi gửi (từ khóa hủy trên Zalo là W2).
- R3.5 NẾU một overlay công ty đặt Giới hạn tần suất gửi, Khung giờ không gửi hay số người nhận tối đa mỗi lượt
  lỏng hơn Sàn gửi tin, THÌ bộ nạp overlay PHẢI trả 422 và không nhận overlay.
- R3.6 NẾU `GET /api/v1/public/unsubscribe/{token}` nhận một token sai chữ ký HMAC, THÌ route công khai
  PHẢI trả 404 và không ghi dòng nào, không lộ địa chỉ có tồn tại hay không.
- R3.7 KHI Sàn gửi tin chặn một tin, ToolExecutor PHẢI ghi một dòng nhật ký gửi với `outcome` `blocked` và lý do
  chặn trong cùng giao dịch với `marketing.send_refused`, vì ở W1 mỗi Tương tác là một dòng nhật ký gửi (N4).
- R3.8 NẾU một lượt chạy gốc đã gửi tới số người nhận tối đa mỗi lượt (200 ở thí điểm, số tạm UNVERIFIED, hay số
  thấp hơn công ty đặt) mà một tin tới thêm một người nhận khác, THÌ ToolExecutor PHẢI trả
  `blocked:recipient_cap` và không gọi nhà cung cấp (ADR-0124 (Accepted) quyết 1, 6).

### R4 — Phân tích bộ ba nguy hiểm khi gửi kiểm định

Mỗi phiên bản agent và quy trình được phân tích khi gửi kiểm định; một đường nối đầu vào không tin cậy,
dữ liệu riêng và tác động ra ngoài phải qua người trước tác động (YC71; ADR-0125 (Accepted)).

- R4.1 KHI một phiên bản được gửi kiểm định, `capability_analysis` PHẢI đọc nhãn `untrusted_source`,
  `private_data` và `external_effect` từ một bảng điều phối theo loại node và loại công cụ, coi một loại
  lạ là mang cả ba nhãn.
- R4.2 NẾU một quy trình có một đường từ đầu vào bên ngoài qua dữ liệu riêng tới tác động ra ngoài mà
  không có node phê duyệt chi phối node tác động, THÌ thao tác gửi kiểm định PHẢI trả 422
  `trifecta_path_unapproved` kèm đường vi phạm.
- R4.3 NẾU một agent mang cả ba nhãn khai Mức tự chủ trên A2, THÌ thao tác gửi kiểm định PHẢI trả 422
  `capability_trifecta_autonomy` kèm hai cách sửa.
- R4.4 NẾU một phiên bản dùng một công cụ thiếu một trong ba phân loại, THÌ thao tác gửi kiểm định PHẢI
  trả 422 `tool_unclassified`.
- R4.5 NẾU một overlay công ty hay một Mức tự chủ muốn hạ sàn bộ ba (bỏ node phê duyệt, nâng Mức tự chủ
  trên A2), THÌ thao tác gửi kiểm định PHẢI trả 422 `trifecta_path_unapproved` hay
  `capability_trifecta_autonomy` và không chuyển phiên bản khỏi Nháp, vì sàn chỉ siết được.
- R4.6 KHI Phân tích năng lực chạy cho một phiên bản lúc gửi kiểm định, `capability_analysis` PHẢI ghi kết
  quả (tín hiệu, đường, kết luận, phiên bản bộ phân tích) vào `studio.version_assessments` theo Mã băm định
  nghĩa của phiên bản trong giao dịch gửi kiểm định, để lane `studio_gate` đọc (agent-lifecycle:R6.1).
- R4.7 NẾU một dòng `studio.version_assessments` mang `tenant_id` của một công ty mà `version_id` trỏ tới phiên bản
  của công ty khác, THÌ PostgreSQL PHẢI từ chối dòng đó với SQLSTATE 23503 qua FK ghép `(tenant_id, version_id)` tới
  `uq_artifact_versions_tenant_id_id` (tenant-config:R2.18).

### R5 — Lưu giữ cho kho dữ liệu cá nhân của lát, dẫn Nghị định 356

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa, và dẫn chiếu đổi từ Nghị định 13/2023
sang Nghị định 356 (YC88). Lát này thêm dòng của kho mình vào tệp chính sách retention theo định dạng khóa
`schema.table` của telemetry-and-audit (telemetry-and-audit:R5.6): ticket 04 thêm hai bảng `append_only` trong
cùng thay đổi đăng ký, ticket 06 thêm phần còn lại, mỗi ticket một bản trong chuỗi các ticket sửa tệp ở mục Phụ
thuộc; thời hạn của sự kiện vào Data Hub do workflow-triggers/02 thêm, lane của telemetry-and-audit thi hành
(DO-52).

- R5.1 ĐỐI VỚI mỗi kho dữ liệu cá nhân mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi
  marketing, hội thoại 90 ngày), tệp chính sách retention đang ghim PHẢI khai dưới khóa của kho một thời hạn và
  một bộ xóa đã đăng ký.
- R5.2 NẾU một kho dữ liệu cá nhân không có bộ xóa đăng ký, THÌ test tập bộ xóa PHẢI đỏ.
- R5.3 Chú thích thời hạn Nhật ký kiểm toán trong tệp chính sách retention đang ghim PHẢI dẫn PDPL và Nghị
  định 356, không dẫn Nghị định 13/2023.
- R5.4 Lane lưu giữ PHẢI không xóa dòng `platform.contact_suppressions` nào theo thời gian; chỉ offboarding
  của công ty hay yêu cầu của chủ thể dữ liệu (W2) xóa dòng chặn gửi.
- R5.5 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng của công ty đó trong `platform.consent_records`, `platform.marketing_send_log` (hai bảng qua
  `platform.purge_tenant_append_only`, usage-and-limits:R3.10), `platform.contact_suppressions` và
  `studio.version_assessments` (theo FK ON DELETE CASCADE khi `studio.artifact_versions` của công ty bị xóa) (YC6).
- R5.6 NẾU `dw_app` xóa một dòng `platform.contact_suppressions` của một công ty có `platform.tenants.status` khác
  `offboarding`, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không xóa dòng nào.
- R5.7 KHI lane lưu giữ gọi bộ xóa hội thoại, lane lưu giữ PHẢI xóa ở mọi công ty mọi tin nhắn
  `studio.conversation_messages` tạo trước mốc 90 ngày tính trong thân `studio.purge_expired_conversations()`, rồi mọi
  hội thoại `studio.conversations` không còn tin nào và có hoạt động cuối trước mốc, và giữ nguyên mọi tin và hội thoại
  có hoạt động từ mốc trở đi (DO-52; ADR-0122 (Accepted) quyết 7).
- R5.8 KHI lane lưu giữ xóa tin nhắn hay hội thoại của một workspace theo R5.7, lane lưu giữ PHẢI ghi trong cùng
  giao dịch, ở công ty và workspace đó, một sự kiện audit `studio.conversation.expired` đứng tên chính lane
  (`system:<lane>`), mang số tin và số hội thoại đã xóa ở workspace đó (ADR-0011 (Accepted)).
- R5.9 NẾU thời hạn viết trong thân `studio.purge_expired_conversations()` khác thời hạn dưới khóa
  `studio.conversation_messages` hay `studio.conversations` của tệp chính sách retention đang ghim, THÌ test ranh
  giới của bộ xóa hội thoại PHẢI đỏ, để hai bản sao của một thời hạn lệch ồn ào (`failure-modes.md` #2).

## Trong phạm vi

- Bảng, cột và ràng buộc ở mục Dữ liệu; route ở mục API.
- Mã: `dw_kernel.personal_data` (từ vựng `pd_category`, `sensitive_type`, Trường định danh chủ thể, helper
  CHECK và helper test catalog); `ResidencyGate` và `effective_route_class`; `MarketingSendPolicy` thỏa
  `SendAdmissionPort`; module thuần `capability_analysis`, bảng điều phối nhãn ở composition root và kiểm
  đăng ký vào bảng kiểm theo loại lúc gửi kiểm định của agent-lifecycle (agent-lifecycle:R2.7);
  `configs/policies/marketing_send@1.0.0.yaml` (gồm số người nhận tối đa mỗi lượt), `configs/policies/studio_risk@1.0.0.yaml`
  và dòng thời hạn của kho lát này trong tệp chính sách retention; bộ xóa hội thoại hết hạn, hàm SECURITY DEFINER
  hẹp không đối số `studio.purge_expired_conversations()` mà lane lưu giữ gọi, và test ranh giới so hạn trong thân
  hàm với tệp chính sách retention (R5.7, R5.8, R5.9).
- Bảng mới ở W1: `platform.consent_records`, `platform.contact_suppressions`, `platform.marketing_send_log`,
  `studio.version_assessments`; cột `data_route_class` trên `platform.tenants` và `platform.workspaces`.
  `platform.cross_border_attestations` đến ở W2 cùng R2.5 (Ngoài phạm vi).
- Route công khai `GET /api/v1/public/unsubscribe/{token}`; `PATCH /api/v1/admin/tenant` thêm
  `data_route_class` (W1 chỉ siết).
- Audit: `marketing.sent`, `marketing.send_refused` (chỉ lát này ghi, trong giao dịch của executor),
  `residency.class_changed`, `studio.conversation.expired` (lane lưu giữ ghi, đứng tên chính lane; R5.8).

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                        | Vì sao                                                                                                                                    | Chủ                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| W2: Hạn chế xử lý và Từ chối xử lý tự động trên bản ghi (YC49, YC67)                                                                                                                                                                                                                        | cần đầu bản ghi của custom-objects và node của workflow-nodes                                                                             | compliance-pdpl, đợt sau (W2)                        |
| R2.5: nới Lộ trình dữ liệu của công ty hay workspace qua kind `policy` của tenant-config, với người duyệt thứ hai và Xác nhận chuyển dữ liệu ra nước ngoài còn hạn nêu `processor` (bảng `platform.cross_border_attestations`, chỉ có bên ghi và bên đọc ở đây); audit `residency.attested` | YC91 là W2; W1 không có đường nới (R2.7; D:tenant-config/05~tenant-rbac:R7.1)                                                             | compliance-pdpl; tenant-config, đợt sau (W2)         |
| R3.4 phần từ khóa hủy trả lời trên Zalo qua inbound router                                                                                                                                                                                                                                  | router sự kiện nhà cung cấp và kênh Zalo là W2 (connections-and-vault)                                                                    | compliance-pdpl; connections-and-vault, đợt sau (W2) |
| W2: Sổ sự cố dữ liệu cá nhân `platform.pd_incidents` và runbook 72 giờ (YC90); DPA hứa báo công ty trong 24 giờ từ khi nền tảng biết (DO-56.2)                                                                                                                                              | trước dữ liệu thật; chỉ Người vận hành đọc                                                                                                | compliance-pdpl, đợt sau (W2)                        |
| W2: Presidio tiếng Việt có số đo; tối thiểu hóa trước khi gọi (`cross_border_minimised`)                                                                                                                                                                                                    | bộ dò là kiểm soát phụ, đo recall trước khi dựa vào                                                                                       | compliance-pdpl, đợt sau (W2)                        |
| W2: Yêu cầu của chủ thể dữ liệu — màn, API, cổng xóa theo kho (YC90), gồm đường xóa dòng chặn gửi thêm vào trigger `platform.guard_contact_suppression()` của R5.6                                                                                                                          | `DataSubjectPort` đăng ký một bản theo kho ở composition root                                                                             | compliance-pdpl, đợt sau (W2)                        |
| W2: Mã hóa checkpoint theo khóa công ty; TLS chặng nội bộ; cache chia theo công ty (YC92)                                                                                                                                                                                                   | sau khóa vault; đo nhà cung cấp cache trước                                                                                               | compliance-pdpl; connections-and-vault               |
| W2: Mức rủi ro AI trên `studio.version_assessments` (công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1), tờ giải thích, thông báo AI ở kênh chat (v1.5), nhãn "do AI soạn" bật mặc định trên tin AI soạn gửi lead tới khi luật sư trả lời (YC93); sổ xử lý (YC91)                  | DO-60; tiêu chí tầng và nhãn chờ luật sư; bảng có từ W1 cho kết quả Phân tích năng lực (R4.6); nguồn gốc tin AI soạn đã ghi ở nhật ký gửi | compliance-pdpl; agent-lifecycle                     |
| W2: Khoanh vùng sự cố, audit đọc trường `Nhạy cảm`, taint động; gửi hoãn tới Khung giờ không gửi                                                                                                                                                                                            | sau sổ sự cố và taint ở executor                                                                                                          | compliance-pdpl, đợt sau (W2)                        |
| W3: Hồ sơ công ty được quản lý, gói bằng chứng, khóa do khách quản lý, báo cáo sự cố AI                                                                                                                                                                                                     | v2                                                                                                                                        | compliance-pdpl, đợt sau (W3)                        |
| Ép lát Marketing chỉ chạy trên lead giả lập tới khi đủ điều kiện rời dữ liệu giả lập của YC99 (DO-53, DO-54.2 gồm DPA, sổ sự cố, cờ Hạn chế xử lý)                                                                                                                                          | YC89; ý kiến luật sư ở ticket 02; sổ sự cố và cờ là W2                                                                                    | marketing-pilot; tenant-config                       |
| Thời hạn và bộ xóa của sự kiện vào Data Hub (`studio.inbound_events`, `studio.trigger_deliveries`, `studio.inbound_dedupe`)                                                                                                                                                                 | workflow-triggers/02 thêm thời hạn và bộ xóa đó vào tệp chính sách retention, lane lưu giữ của telemetry-and-audit thi hành (DO-52)       | workflow-triggers; telemetry-and-audit               |
| Telemetry và log không mang nội dung                                                                                                                                                                                                                                                        | một chủ là telemetry-and-audit/01                                                                                                         | telemetry-and-audit                                  |
| Checkpoint chỉ dựng lại kiểu trong allowlist                                                                                                                                                                                                                                                | gộp vào foundations-hardening/02                                                                                                          | foundations-hardening                                |
| RecordService, bảng bản ghi và cờ trên đầu bản ghi                                                                                                                                                                                                                                          | lát này đọc bản ghi qua Object Service                                                                                                    | custom-objects                                       |
| ToolExecutor, loại công cụ, bọc StructuredTool, cờ taint lượt chạy                                                                                                                                                                                                                          | lát này tiêu `SendAdmissionPort` trong executor                                                                                           | tools-and-skills                                     |
| Egress client, vault và kết nối                                                                                                                                                                                                                                                             | lát này khai `data_location` trên manifest kết nối                                                                                        | connections-and-vault                                |
| Nộp hồ sơ, xin giấy chứng nhận, bổ nhiệm DPO; SOC 2, ISO 27001/27701/42001                                                                                                                                                                                                                  | quy trình pháp lý; sản phẩm chỉ sinh bằng chứng                                                                                           | không làm                                            |

## Dữ liệu

Mọi bảng gắn công ty: RLS ENABLE và FORCE theo công ty, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `dw_kernel.personal_data`: module thuần stdlib; `PdCategory` (`none`, `basic`, `sensitive`),
  `SensitiveType` (danh sách Nghị định 356 Điều 4.1), `SubjectIdentifierKind` (email, phone, national_id,
  zalo_user_id, facebook_psid, tax_code, bank_account); helper `assert_field_tables_classified` và JSON
  Schema `contracts/jsonschema/pd_classification.json` sinh ra, `--check` trong CI; nhãn tiếng Việt
  `apps/web/lib/pd-labels.ts`.
- `platform.tenants`: thêm `data_route_class text NOT NULL DEFAULT 'vn_only'` CHECK (`vn_only`,
  `cross_border_minimised`, `cross_border_full`).
- `platform.workspaces`: thêm `data_route_class text NULL` cùng CHECK (NULL kế thừa công ty; chỉ siết).
- Hai bảng `platform.consent_records`, `platform.contact_suppressions` thuộc lớp bảng toàn tenant: RLS chỉ theo
  công ty, không cột `workspace_id`, có tên và lý do trong danh sách bảng toàn tenant mà `test_rls_coverage.py`
  giữ (`CLAUDE.md` mục 'Tenancy and authorization', ngoại lệ của DO-01); công ty là bên kiểm soát nên một lần rút
  đồng ý ghi ở workspace nào cũng chặn gửi ở mọi workspace trong ≤ 5 phút (YC86).
- `platform.consent_records`: chỉ thêm; phân vùng theo tháng trên `captured_at` với DEFAULT, đăng ký bằng một
  dòng `platform.time_partitioned_tables` (`append_only = true`), `dw_app` không giữ quyền nào trên phân vùng
  nào, kể cả DEFAULT (DO-02.2); `subject_ref` (E.164, email thường hay Zalo user id), `purpose` CHECK
  (`marketing`, `transactional`), `channel` CHECK (`zns`, `email`, `sms`, `messenger`, `zalo_oa`), `state`,
  `captured_at`, `source`, `evidence_ref`, `notice_version`, `withdrawn_at`; đồng ý hiện hành là dòng mới
  nhất theo `(subject_ref, purpose, channel)`; index `(tenant_id, subject_ref, channel, purpose, captured_at DESC)`;
  thời hạn theo quan hệ cộng 5 năm (số tạm UNVERIFIED) dưới khóa `platform.consent_records`, thêm trong cùng thay
  đổi đăng ký (ticket 04), bộ xóa xóa theo dòng, không bằng DROP PARTITION.
- `platform.contact_suppressions`: PK `(tenant_id, channel, address_hash)`; không hết hạn theo thời gian,
  chỉ offboarding hay yêu cầu của chủ thể dữ liệu (W2) xóa (R5.4); `dw_app` có DELETE chỉ dùng được ở lượt xóa của
  offboarding (R5.5): trigger `platform.guard_contact_suppression()` BEFORE DELETE từ chối với SQLSTATE 23514 mọi
  DELETE khi `platform.tenants.status` của công ty khác `offboarding` (R5.6), cùng hình với
  `platform.guard_control_switch()` của agent-lifecycle (agent-lifecycle:R7.5); đường xóa theo yêu cầu của chủ thể
  dữ liệu thêm vào trigger đó ở W2.
- `platform.marketing_send_log`: phân vùng theo tháng, đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`); RLS dạng workspace của `CLAUDE.md` trên bảng cha; `dw_app` không giữ quyền nào trên
  phân vùng nào, đọc ghi qua bảng cha, nên đọc một phân vùng theo tên không lộ dòng của workspace khác
  (DO-02.2); một dòng mỗi Tương tác ở W1 (N4): `outcome` CHECK (`sent`, `blocked`), `blocked_reason` (NULL khi
  `sent`, CHECK theo lý do của Sàn gửi tin), `root_run_id` để đếm người nhận mỗi lượt (R3.8), `consent_record_id`
  khi `sent`, nguồn gốc tin AI soạn (lượt chạy soạn, model); thời hạn 13 tháng (số tạm UNVERIFIED) dưới khóa
  `platform.marketing_send_log`, thêm trong cùng thay đổi đăng ký (ticket 04), xóa bằng DROP PARTITION qua
  `platform.drop_expired_partitions`.
- Khi offboarding, `dw_app` không có DELETE trên `platform.consent_records` và `platform.marketing_send_log`, nên
  mỗi bảng có một dòng `STUDIO_EXCLUSIONS` nêu cách xóa, `platform.purge_tenant_append_only` (R5.5;
  studio-skeleton:R4.3).
- `studio.version_assessments`: một dòng mỗi phiên bản và Mã băm định nghĩa, ghi trong giao dịch gửi kiểm
  định: tín hiệu A, B, C, đường vi phạm, kết luận, phiên bản bộ phân tích; bảng toàn tenant như vỏ phiên bản (RLS
  chỉ theo công ty, không cột `workspace_id`), có tên và lý do trong danh sách bảng toàn tenant mà
  `test_rls_coverage.py` giữ, lý do là đánh giá đi theo phiên bản toàn tenant của nó (`CLAUDE.md` mục 'Tenancy and
  authorization'; studio-skeleton:R9.1); FK ghép `(tenant_id, version_id)` tới
  `studio.artifact_versions (tenant_id, id)`, đích là `uq_artifact_versions_tenant_id_id` của tenant-config/02, ON
  DELETE CASCADE, có index `(tenant_id, version_id)`, nên một dòng không trỏ được tới phiên bản của công ty khác
  (R4.7) và lượt xóa `studio.artifact_versions` khi offboarding xóa luôn dòng đánh giá; `dw_app` SELECT, INSERT,
  không DELETE, nên bảng có một dòng `STUDIO_EXCLUSIONS` nêu cách xóa đó, cascade từ `studio.artifact_versions`
  (R5.5; studio-skeleton:R4.1); Mức rủi ro AI (`suggested_tier`, `declared_tier`) thêm ở W2 (ADR-0125 (Accepted)
  quyết 6).
- `studio.purge_expired_conversations()`: hàm SECURITY DEFINER hẹp của ticket 06 theo mẫu xóa dữ liệu hết hạn của
  ADR-0122 (Accepted) quyết 7, vì `dw_app` chỉ SELECT, INSERT trên `studio.conversation_messages` (agent-builder);
  hàm không nhận đối số và giữ hạn 90 ngày trong thân (mốc `now() - interval '90 days'`), theo tiền lệ
  `platform.prune_notifications()` ("It takes no argument, so no caller can widen it to recent rows",
  `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:28-29`), nên không bên gọi nào nới hàm tới tin
  còn hạn; REVOKE ALL FROM PUBLIC rồi GRANT EXECUTE cho `dw_app`, vai mà lane lưu giữ của worker dùng. Ở mọi công ty,
  hàm xóa tin nhắn có `created_at` trước mốc, rồi xóa hội thoại không còn tin nào và có `created_at` trước mốc (hoạt
  động cuối của nó trước mốc, vì mọi tin của nó đã quá hạn), theo thứ tự đó vì FK ghép của tin nhắn tới
  `studio.conversations` là `ON DELETE RESTRICT`; trả một dòng mỗi workspace có dòng bị xóa (`tenant_id`,
  `workspace_id`, số tin, số hội thoại), vì một sự kiện audit luôn mang `workspace_id`. Hạn trong thân hàm là bản sao
  thứ hai của thời hạn dưới khóa `studio.conversation_messages` và `studio.conversations` trong tệp chính sách
  retention, nên một test ranh giới đỏ khi hai bên khác nhau (R5.9; `failure-modes.md` #2). Lane lưu giữ gọi hàm
  (R5.7) và, trong cùng giao dịch, ghi cho mỗi dòng trả về một sự kiện `studio.conversation.expired` của chính lane, ở
  công ty và workspace của dòng đó, qua `lane_audit.append_across_tenants`; không ghi được sự kiện thì không dòng nào
  bị xóa (R5.8; ADR-0011 (Accepted)).

## API

- `PATCH /api/v1/admin/tenant` (`platform.tenant.settings.write`): thêm `data_route_class`; W1 chỉ siết,
  một người cộng audit `residency.class_changed` (R2.8); nới về ra nước ngoài → 409 `second_person_required`
  (R2.7); đường nới hai người với Xác nhận là W2 qua tenant-config (R2.5).
- `GET /api/v1/public/unsubscribe/{token}`: route công khai, HMAC một địa chỉ, idempotent, rate-limited,
  không lộ địa chỉ có tồn tại.
- Lỗi theo vỏ `application/problem+json` của ADR-0108 (Accepted). Lát này là chủ mã `pd_category_required`, một
  `errors[].code` của 422 `validation_failed` có con trỏ tới trường thiếu loại (app-standards:R1.3), không phải
  `details.reason_code`; spec chủ bảng trả nó cùng hình (custom-objects:R2.2, workflow-triggers:R4.1).
  `details.reason_code`: `residency_refused`, `blocked:<lý do>` (lý do của Sàn gửi tin ở ADR-0124 (Accepted)
  quyết 1, gồm `recipient_cap`; `processing_restricted` đến ở W2 cùng Hạn chế xử lý), `capability_trifecta_autonomy`,
  `tool_unclassified`, `trifecta_path_unapproved`, `second_person_required`. Mã 422 lúc gửi kiểm định đi qua
  route gửi kiểm định của agent-lifecycle (agent-lifecycle:R2.7).

## Kiểm soát

| #    | Kiểm soát                                                                               | Yêu cầu          | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---- | --------------------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CP1  | Trường thiếu `pd_category` không tạo được                                               | R1.1, R1.2, R1.3 | POST một trường không có `pd_category` → 422 `validation_failed`, `errors[].code` `pd_category_required` có con trỏ tới trường; thêm một giá trị CHECK ngoài enum kernel → test drift đỏ                                                                                                                                                                                                                                                                                       |
| CP2  | `vn_only` không gửi byte nào ra nước ngoài                                              | R2.2             | Agent `vn_only` với tuyến `foreign` → từ chối trước khi gửi, adapter giả ghi 0 lời gọi; gỡ cổng → test đỏ                                                                                                                                                                                                                                                                                                                                                                      |
| CP3  | Mọi đường gọi model qua cùng cổng                                                       | R2.3             | Chép lời khi `vn_only` tới URL `foreign` → job `failed` lý do `residency_refused`, 0 request; gỡ cổng ở embedding → test đỏ                                                                                                                                                                                                                                                                                                                                                    |
| CP4  | Workspace, agent không nới lộ trình                                                     | R2.4             | Đặt `cross_border_full` ở workspace khi công ty `vn_only` → 422, không đổi dòng                                                                                                                                                                                                                                                                                                                                                                                                |
| CP5  | Không nới lộ trình bằng một người                                                       | R2.5, R2.7       | W1: `PATCH` nới công ty sang `cross_border_full` → 409 `second_person_required`, lộ trình giữ nguyên; gỡ chặn → test đỏ (đường hai người và Xác nhận của R2.5 thử ở W2)                                                                                                                                                                                                                                                                                                        |
| CP6  | Trường cá nhân vào prompt trên tuyến ra nước ngoài bị chặn lúc gửi kiểm định            | R2.6             | Gắn `full_name` vào prompt trên tuyến `cross_border_full` → gửi kiểm định 422 `residency_refused`, phiên bản vẫn Nháp; gỡ kiểm → test đỏ (MP7)                                                                                                                                                                                                                                                                                                                                 |
| CP7  | Không gửi marketing khi thiếu đồng ý; lần chặn để lại Tương tác                         | R3.1, R3.7       | Lead không có Bản ghi đồng ý → `blocked:no_consent`, 0 tin, `marketing.send_refused` và một dòng nhật ký gửi `outcome` `blocked` cùng giao dịch; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                             |
| CP8  | Sàn gửi kiểm trong ToolExecutor, không ở node                                           | R3.2             | Gọi hành động gửi qua node, qua công cụ agent, qua quy trình-như-công-cụ không đồng ý → cả ba bị chặn; gỡ kiểm ở executor → test đỏ (MP1, MP12, MP15)                                                                                                                                                                                                                                                                                                                          |
| CP9  | Hủy đăng ký có hiệu lực trong 5 phút                                                    | R3.4             | Bấm link hủy → lần gửi sau `blocked:suppressed` trong ≤ 5 phút; tin đang chờ bị kiểm lại                                                                                                                                                                                                                                                                                                                                                                                       |
| CP10 | Token hủy sai trả 404 không lộ tồn tại                                                  | R3.6             | `GET /api/v1/public/unsubscribe/{token}` token sai chữ ký → 404, không dòng nào, không lộ địa chỉ                                                                                                                                                                                                                                                                                                                                                                              |
| CP11 | Công ty không nới sàn gửi                                                               | R3.5             | Overlay đặt tần suất lỏng hơn Sàn gửi tin → 422; overlay đặt 300 người nhận mỗi lượt → 422, đặt 50 → nhận; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                   |
| CP12 | Bộ ba nguy hiểm không gửi kiểm định được                                                | R4.2             | Bỏ node phê duyệt khỏi workflow pilot → gửi kiểm định 422 `trifecta_path_unapproved` nêu đường; đường `score → send` không qua `approve` → 422 nêu đường (MP2)                                                                                                                                                                                                                                                                                                                 |
| CP13 | Agent bộ ba phải tự chủ ≤ A2                                                            | R4.3             | Agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy`; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                               |
| CP14 | Công cụ thiếu phân loại không gửi kiểm định được                                        | R4.4             | Dùng công cụ thiếu một phân loại → 422 `tool_unclassified`; node loại lạ → coi như cả ba nhãn                                                                                                                                                                                                                                                                                                                                                                                  |
| CP15 | Không cấu hình nào hạ sàn bộ ba                                                         | R4.5             | Overlay bỏ node phê duyệt hay nâng Mức tự chủ trên A2 cho phiên bản bộ ba → gửi kiểm định 422, phiên bản vẫn Nháp                                                                                                                                                                                                                                                                                                                                                              |
| CP16 | Mỗi lớp retention mới có bộ xóa                                                         | R5.1, R5.2       | Một lớp retention thiếu bộ xóa đăng ký → test tập bộ xóa đỏ                                                                                                                                                                                                                                                                                                                                                                                                                    |
| CP17 | Danh sách chặn gửi không tự hết hạn                                                     | R5.4             | Dòng chặn gửi 10 năm tuổi qua một lượt lane lưu giữ → dòng còn, lần gửi sau vẫn `blocked:suppressed`; thêm hạn theo thời gian cho lớp chặn gửi → test đỏ                                                                                                                                                                                                                                                                                                                       |
| CP18 | Một lượt chạy không gửi quá số người nhận tối đa                                        | R3.8             | Lượt chạy gốc đã gửi tới 200 người nhận, tin tới người thứ 201 → `blocked:recipient_cap`, SMTP giả 0 lời gọi, dòng nhật ký gửi `blocked`; tin thứ 200 → gửi; overlay hạ còn 50 → người thứ 51 bị chặn; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                       |
| CP19 | Chỉ lượt xóa của offboarding xóa được dòng chặn gửi                                     | R5.6             | `dw_app` DELETE một dòng chặn gửi của công ty `active` → 23514, dòng còn, lần gửi sau vẫn `blocked:suppressed`; cùng lệnh khi công ty `offboarding` → xóa được; gỡ phép kiểm DELETE khỏi trigger → test đỏ                                                                                                                                                                                                                                                                     |
| CP20 | Bộ xóa hội thoại chỉ xóa phần quá hạn, có audit, không trả DELETE tin nhắn cho `dw_app` | R5.7, R5.8       | Hai công ty, mỗi công ty có tin 91 ngày và 89 ngày: một lượt lane xóa tin 91 ngày của cả hai, tin 89 ngày còn; hội thoại còn một tin 89 ngày giữ nguyên; hội thoại tạo 10 ngày trước chưa có tin giữ nguyên; mỗi workspace có dòng bị xóa một sự kiện `studio.conversation.expired` đứng tên lane ở đúng công ty và workspace đó, với đúng hai số; `dw_app` DELETE thẳng một tin → `permission denied`; ghi audit hỏng → không dòng nào bị xóa; hàm bỏ điều kiện mốc → test đỏ |
| CP21 | Dòng đánh giá không trỏ được tới phiên bản của công ty khác                             | R4.7             | Chèn một dòng `studio.version_assessments` mang `tenant_id` của công ty A và `version_id` của một phiên bản công ty B → 23503, không dòng nào; đổi FK ghép về FK một cột `version_id` → test đỏ                                                                                                                                                                                                                                                                                |
| CP22 | Hạn trong hàm xóa hội thoại khớp tệp chính sách retention                               | R5.9             | Thân `studio.purge_expired_conversations()` giữ 60 ngày trong khi khóa `studio.conversation_messages` của tệp ghi 90 → test ranh giới đỏ, nêu khóa; khóa `studio.conversations` ghi 120 trong khi khóa tin nhắn ghi 90 → đỏ; thân hàm và hai khóa cùng 90 → xanh                                                                                                                                                                                                               |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của ticket).
- Lát Marketing chạy hết đường với `vn_only` trên một tuyến model khai `vn` (FOG-10, FOG-18); có Bản ghi
  đồng ý, có hủy đăng ký, có node phê duyệt.
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- field-security: hàm quyết quyền đọc trường, dấu `Đã ẩn`, chế độ `Mở`/`Bảo vệ` dùng `pd_category` của lát
  này (`.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`), đang viết đợt này; dẫn
  theo đường dẫn.
- model-connections: `ModelResolver` theo công ty và trường `data_location`, `processor` trên tuyến và bí
  danh model cùng luật "không khai là nước ngoài", một chủ; lát này chỉ đọc
  (`.claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md`); ADR-0118 (Accepted).
- usage-and-limits: cột `data_route_class`, `data_location`, `processor` của `platform.usage_events`
  (`.claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md`); `ResidencyGate` đứng
  trước `LimitsMiddleware` (usage-and-limits:R6.5), và usage-and-limits/03 chờ ticket 03 (OPS-b);
  `platform.drop_expired_partitions` và `platform.purge_tenant_append_only` cho nhật ký gửi và Bản ghi đồng ý
  (usage-and-limits:R3.10).
- Thứ tự cửa trong gateway có cấu trúc: công tắc Đóng băng và Tắt khẩn cấp của
  `.claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md` đứng đầu, rồi `ResidencyGate`
  của ticket 03, rồi `LimitsMiddleware`; ticket 03 chờ agent-lifecycle/01.
- Thứ tự ngăn xếp agent: `ResidencyGate` là một middleware ngay sau `StudioModelSelection` và trước
  `LimitsMiddleware`, theo thứ tự mà `.claude/plans/studio/agent-builder/issues/03-runtime-agent.md` bước 2 ghi
  (ADR-0117 (Accepted) quyết 5; usage-and-limits:R6.5); ticket 03 cấp cổng, agent-builder/03 chờ nó.
- custom-objects: RecordService và tham chiếu chủ thể cho đồng ý
  (`.claude/plans/studio/custom-objects/issues/03-record-service.md`).
- tools-and-skills: ToolExecutor tiêu `SendAdmissionPort` và phân loại công cụ theo ADR-0116 (Accepted),
  đang viết đợt này
  (`.claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md`).
- workflow-engine: lược đồ `dw.workflow/v1` và cổng phát hành cho phân tích bộ ba
  (`.claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md`).
- agent-lifecycle: bảng kiểm theo loại lúc gửi kiểm định, nơi lát này đăng ký Phân tích năng lực và kiểm
  R2.6 (agent-lifecycle:R2.7), và phát hành hai người
  (`.claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md`); lane `studio_gate`
  đọc kết quả ở `studio.version_assessments` làm chốt chặn (agent-lifecycle:R6.1).
- tenant-config: khóa đích `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)` của
  `studio.artifact_versions` cho FK ghép của `studio.version_assessments`
  (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`, mà ticket 05 chờ); kind
  `policy` cho đường nới Lộ trình dữ liệu hai người ở W2 (R2.5).
- agent-builder: hai bảng hội thoại mà hàm xóa của ticket 06 xóa, với `dw_app` chỉ SELECT, INSERT trên
  `studio.conversation_messages`, `workspace_id NOT NULL` trên cả hai bảng (R5.8 đếm theo workspace) và FK ghép của
  tin nhắn tới `studio.conversations` `ON DELETE RESTRICT`
  (`.claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md`).
- agent-builder: loại agent và khung prompt cho nhãn năng lực
  (`.claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md`).
- connections-and-vault: egress client và `data_location` trên manifest kết nối, đang viết đợt này; dẫn
  theo đường dẫn.
- Tệp chính sách retention: telemetry-and-audit là chủ định dạng (khóa `schema.table`, telemetry-and-audit:R5.6)
  và lane lưu giữ, và các ticket sửa tệp đi thành một chuỗi ở mục Phụ thuộc của spec đó
  (`.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md` đứng trước); lát này thêm dòng
  của Bản ghi đồng ý và nhật ký gửi ở ticket 04 (cùng thay đổi đăng ký, sau
  `.claude/plans/studio/workflow-triggers/issues/02-data-hub-endpoint-va-ingress.md`, ticket thêm thời hạn của sự
  kiện vào Data Hub), rồi của Danh sách chặn gửi và `studio.conversations` ở ticket 06, bản cuối của chuỗi, sau
  `.claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md` (DO-52).
- studio-skeleton: R3.7 đọc thời hạn của mỗi bảng `append_only` (studio-skeleton:R3.7); test phủ offboarding và
  `STUDIO_EXCLUSIONS` cho bảng `platform` (studio-skeleton:R4.3) và cho `studio.version_assessments`
  (studio-skeleton:R4.1).
- Kiểm lại khi: `pd_category` của `dw_kernel.personal_data` đổi hình → R1, field-security; cửa model của
  model-connections đổi hợp đồng → R2; ToolExecutor của tools-and-skills đổi điểm chèn → R3.2; bảng kiểm theo
  loại hay lane `studio_gate` của agent-lifecycle đổi → R2.6, R4; ý kiến luật sư (DO-53, DO-54.2, DO-55,
  DO-60) → số trong `marketing_send@1.0.0.yaml`, một bản mới của tệp chính sách retention và điều kiện vào chạy
  bóng (YC99), không đổi tiêu chí W1; agent-builder đổi thứ tự ngăn xếp agent → R2.3, ticket 03; chuỗi các ticket
  sửa tệp chính sách retention đổi thứ tự → ticket 04, 06; tenant-config đổi khóa hay cách xóa
  `studio.artifact_versions` → R4.7, R5.5, ticket 05; agent-lifecycle đổi hình trigger chặn DELETE của nó
  (agent-lifecycle:R7.5) → R5.6, ticket 04; agent-builder đổi quyền của `dw_app`, cột hay FK của hai bảng hội thoại →
  R5.7, R5.8, ticket 06; luật sư hay Đạt đổi thời hạn hội thoại (DO-52) → một migration sửa thân
  `studio.purge_expired_conversations()` cùng bản mới của tệp chính sách retention, vì test của R5.9 đỏ tới khi hai
  bên khớp, ticket 06.

## Câu hỏi còn mở

- Q1. Studio có phải dịch vụ xử lý dữ liệu cá nhân cần giấy chứng nhận Bộ Công an trước tenant trả phí đầu
  tiên, và bên nào giữ? Chủ: luật sư. Không đổi: W1 chỉ dùng dữ liệu giả lập hay nội bộ; câu trả lời là điều
  kiện vào chạy bóng (YC99), hỏi ở ticket 02 (DO-53).
- Q2. Số chống spam cuối cùng (tần suất, khung giờ, số người nhận mỗi lượt) và ai nộp DPIA, CTIA? Chủ: luật
  sư. Không đổi: số tạm UNVERIFIED nằm ở `marketing_send@1.0.0.yaml` (gồm tối đa 200 người nhận mỗi lượt ở thí
  điểm) và công ty chỉ siết; nền tảng là bên xử
  lý, công ty là bên kiểm soát, DPA trước chạy bóng; câu trả lời chỉ đổi số và hồ sơ, hỏi ở ticket 02
  (DO-54.2, DO-55).

## Quyết định

- 23/10/2026 (người yêu cầu): D4: lát Marketing là ví dụ chạy và gói nghiệp vụ đầu tiên; kết thúc bằng một
  tin Zalo hay email sau một phê duyệt của người. Sửa: R3, R4.
- 23/10/2026 (người yêu cầu): D11 (DO-07): nới Lộ trình dữ liệu cần một người đề xuất và một người duyệt
  khác. Sửa: R2.5.
- 23/10/2026 (người yêu cầu): D13 (DO-19): model của công ty khách đi qua `model-proxy` riêng (bản LiteLLM
  không trạng thái); `data_location` khai theo bí danh, không khai thì coi là nước ngoài. Sửa: R2.1, R2.2.
- 23/10/2026 (agent, tạm): DO-54 theo khuyến nghị (a): nền tảng là bên xử lý, công ty là bên kiểm soát,
  xác nhận lúc onboarding với DPA ký trước khi chạy ngầm; mặc định `vn_only` cho mọi công ty. Hỏi: Q2.
  Sửa: R2. Nếu sai thì: đổi mặc định lộ trình và ai nộp DPIA, CTIA.
- 23/10/2026 (agent, tạm): DO-55 theo khuyến nghị (a): số Sàn gửi tin là giữ chỗ thận trọng, ghi UNVERIFIED
  (1 tin mỗi địa chỉ mỗi kênh mỗi 24 giờ, gửi 08:00-20:00 Asia/Ho_Chi_Minh) tới khi luật sư xác nhận. Hỏi:
  Q2. Sửa: R3.1, R3.5. Nếu sai thì: đổi số trong `marketing_send@1.0.0.yaml`, không đổi cơ chế.
- 23/10/2026 (agent, tạm): DO-52 theo khuyến nghị (a): thời hạn kho mới vào `retention@1.8.0` (nhật ký gửi
  13 tháng, sự kiện Data Hub 30 ngày, Bản ghi đồng ý theo quan hệ cộng 5 năm). Sửa: R5.1. Nếu sai thì: đổi
  số trong `retention@1.8.0`.
- 23/10/2026 (agent, tạm): config-chang.md ghi Data Hub đối thủ không có trường phân loại dữ liệu cá nhân
  (mục 5); Studio cải tiến là mọi trường mang `pd_category`, thiếu thì từ chối (YC84) — quan sát học được,
  không phải mã của họ. Sửa: R1.
- 23/10/2026 (agent, tạm): config-chang.md ghi đối thủ chọn model theo agent có nhà cung cấp nước ngoài mà
  không kiểm lộ trình (mục 1); Studio cải tiến là áp Lộ trình dữ liệu chặt nhất và ghi mỗi lời gọi (YC85)
  — quan sát học được, không phải mã của họ. Sửa: R2.
- 23/10/2026 (Đạt): DO-53 theo (a): gửi luật sư tuần đầu W1; tới khi có văn bản chỉ dữ liệu giả lập hay nội
  bộ; DO-53 là điều kiện vào chạy bóng (YC99), không chặn W1. Hỏi: Q1. Sửa: Status, mở đầu, Q1.
- 23/10/2026 (Đạt): DO-54.1 theo (a), thay dòng DO-54 tạm ở trên: mặc định `vn_only`, bí danh chưa khai là
  nước ngoài, nới cần hai người và Xác nhận; demo trên uat cần một tuyến khai `vn` (FOG-10, FOG-18). DO-54.2
  theo (a): nền tảng là bên xử lý, công ty là bên kiểm soát, DPA trước chạy bóng, sản phẩm xuất đầu vào hồ
  sơ; luật sư quyết ai nộp DPIA, CTIA. DO-55 theo (a), thay dòng DO-55 tạm ở trên: số tạm UNVERIFIED (1 tin
  mỗi địa chỉ mỗi kênh mỗi 24 giờ, 08:00-20:00 Asia/Ho_Chi_Minh), công ty chỉ siết. Hỏi: Q2. Sửa: Q2, Tiêu
  chí xong, ticket 03, 04.
- 23/10/2026 (Đạt): D:tenant-config/05~tenant-rbac:R7.1 theo (b): cấu hình ngoài vai trò, kể cả Lộ trình dữ
  liệu, đi qua tenant-config; W1 bỏ đường nới trên `PATCH /api/v1/admin/tenant`, nới là W2 qua kind `policy`
  (YC91). Sửa: R2.5 (W2), R2.7, CP5, API, Ngoài phạm vi, ticket 03.
- 23/10/2026 (người đặt yêu cầu và Đạt): D11 xác nhận 23/10/2026, phạm vi "đóng một người, mở hai người":
  siết Lộ trình dữ liệu một người cộng audit; nới luôn hai người. Sửa: R2.7, R2.8.
- 23/10/2026 (Đạt): E:CLAUDE.md#tenancy-and-authorization~compliance-pdpl:platform.consent_records theo (a)
  và ADR-0124 (Accepted) theo "tenant": `platform.consent_records`, `platform.contact_suppressions`,
  `platform.cross_border_attestations` vào lớp bảng toàn tenant (RLS chỉ tenant); `consent_records` phân vùng
  tháng có DEFAULT; chỉ `marketing_send_log` hình workspace, partition không cấp quyền `dw_app` (DO-02.2); cả
  hai bảng phân vùng đăng ký bằng một dòng sổ. Sửa: Dữ liệu, ticket 04.
- 23/10/2026 (Đạt): B:agent-lifecycle:R6.1~compliance-pdpl:R4.2 theo (a) và ADR-0125 (Accepted) nhận kèm sửa:
  Phân tích năng lực chạy lúc gửi kiểm định và trả 422; lát này giữ module và ghi kết quả vào
  `studio.version_assessments`, không thêm cột `capability_report`; lane `studio_gate` chỉ đọc làm chốt chặn;
  đường quy trình trả `trifecta_path_unapproved`; R2.6 và R4.5 cũng chạy lúc gửi kiểm định. Sửa: R2.6, R4.2,
  R4.5, R4.6, Dữ liệu, CP6, CP12, CP15, ticket 05.
- 23/10/2026 (Đạt): DO-52 theo (a) cộng hai dòng, thay dòng DO-52 tạm ở trên: Danh sách chặn gửi giữ suốt
  quan hệ với công ty, chỉ offboarding hay yêu cầu của chủ thể xóa; hội thoại theo một số tạm UNVERIFIED do
  Đạt đặt; sự kiện vào Data Hub do telemetry-and-audit khai; lát này nâng `retention@1.8.0` lên `1.9.0` sau
  telemetry-and-audit/03. Sửa: R5, R5.1, R5.3, R5.4, CP17, Phụ thuộc, Ngoài phạm vi, ticket 06.
- 23/10/2026 (Đạt): DO-34.2 theo (a): thêm hai câu Điều 4.2 và 4.1(l) Nghị định 356 vào câu hỏi luật sư tuần
  một; câu trả lời chỉ đổi `pd_category` của trường thí điểm qua một phiên bản `dw.object/v1` mới. DO-48.2
  theo (a): không bật định tuyến sự kiện nhà cung cấp (W2) trước ý kiến luật sư về gửi tới cả hai công ty.
  DO-56.2 theo (a): DPA hứa báo công ty trong 24 giờ từ khi nền tảng biết. DO-60 theo (a) cho phân hạng, cộng
  nhãn "do AI soạn" bật mặc định trên tin AI soạn gửi lead tới khi luật sư trả lời; nguồn gốc ghi ở nhật ký
  gửi. Q9 theo (a): cờ Hạn chế xử lý, sổ sự cố, yêu cầu của chủ thể ở W2; điều kiện rời dữ liệu giả lập là
  danh sách của YC99. Sửa: Ngoài phạm vi, ticket 02.
- 23/10/2026 (Đạt): OPS-b: ticket 06 chờ telemetry-and-audit/03 (1.8.0 rồi 1.9.0); usage-and-limits/03 chờ
  ticket 03; ticket 03 chỉ thêm cột trên `platform.tenants`, không thêm trigger. Sửa: ticket 03, 06.
- 23/10/2026 (agent, tạm): H:compliance-pdpl/04~connections-and-vault: R3.4 ở W1 chỉ phủ link hủy đăng ký;
  từ khóa hủy trên Zalo vào W2. Sửa: R3.4, Ngoài phạm vi, ticket 04. Nếu sai thì: kéo router sự kiện nhà
  cung cấp và kênh Zalo vào W1.
- 23/10/2026 (agent, tạm): A:compliance-pdpl:R2.2\~model-connections:R3.2: model-connections là chủ trường
  `data_location`, `processor` và luật "không khai là nước ngoài"; ticket 03 chỉ đọc.
  B:compliance-pdpl/03\~usage-and-limits: lộ trình ghi vào cột của `platform.usage_events`, ticket 03 chờ
  usage-and-limits/02. A:compliance-pdpl:R3.1\~tools-and-skills:R3.2: chỉ lát này ghi `marketing.send_refused`,
  trong giao dịch của executor. Sửa: Trong phạm vi, Phụ thuộc, ticket 03, 04. Nếu sai thì: trả trường về
  ticket 03 và bỏ ghi lộ trình lên sổ.
- 23/10/2026 (agent, tạm): G:CONTEXT.md#capability-analysis\~compliance-pdpl/05: đổi `CapabilityReport`,
  `capability_report` sang tên của glossary (`version_assessments`). I:agent-builder/04\~compliance-pdpl/06:
  ticket 06 chờ agent-builder/04 và ticket 04. B:agent-builder:R1.1\~compliance-pdpl:R2.4: kiểm R2.6 chạy
  trong Phân tích năng lực lúc gửi kiểm định với `residency_refused`. Sửa: R2.6, ticket 05, 06. Nếu sai thì:
  kiểm R2.6 thành một kiểm riêng của bảng kiểm theo loại.
- 24/10/2026 (Đạt): DO-55, số tạm UNVERIFIED chờ luật sư khi có dữ liệu thật: Sàn gửi tin cho tối đa 200 người
  nhận mỗi lượt chạy ở thí điểm, công ty chỉ hạ thấp hơn (ADR-0124 (Accepted) quyết 6); số này có bên đọc ở
  ToolExecutor (H:ADR-0124 (Accepted)\~compliance-pdpl/04). Hỏi: Q2. Sửa: R3.5, thêm R3.8, CP11, CP18, Trong
  phạm vi, API, Q2, ticket 04.
- 24/10/2026 (Đạt): lý do chặn khi vượt số người nhận mỗi lượt là `recipient_cap`, một lý do của
  ADR-0124 (Accepted) quyết 1 cho trần 200 người nhận mỗi lượt của quyết 6, đếm người nhận khác nhau đã gửi theo
  `root_run_id` trên nhật ký gửi, công ty chỉ hạ thấp hơn; lần chặn cũng ghi một dòng nhật ký gửi `outcome`
  `blocked` (N4) (F:ADR-0124 (Accepted)\~compliance-pdpl:R3.8). Sửa: R3.8, Dữ liệu, API, ticket 04.
- 24/10/2026 (Đạt): DO-52, số tạm UNVERIFIED chờ luật sư khi có dữ liệu thật: hội thoại với trợ lý giữ 90 ngày;
  ticket 06 về `needs-triage` (H:compliance-pdpl:R5.1\~requirements.md:419). Sửa: R5.1, ticket 06.
- 24/10/2026 (Đạt): N4: ở W1 mỗi Tương tác là một dòng `platform.marketing_send_log` của lát này, nên một lần Sàn
  gửi tin chặn cũng ghi một dòng nhật ký gửi `blocked` kèm lý do (YC86); đối tượng Tương tác đến ở W2. Sửa: thêm
  R3.7, CP7, Dữ liệu, ticket 04.
- 24/10/2026 (Đạt): telemetry-and-audit sở hữu định dạng tệp chính sách retention (khóa `schema.table`) và lane;
  mỗi ticket đăng ký một bảng `append_only` tự thêm thời hạn của bảng mình, nên ticket 04 thêm Bản ghi đồng ý và
  nhật ký gửi, ticket 06 thêm Danh sách chặn gửi và hội thoại; ticket 04 chờ telemetry-and-audit/03 để các ticket
  sửa tệp có một thứ tự (I:studio-skeleton:R3.7\~usage-and-limits/02). Sửa: R5, R5.1, R5.3, Dữ liệu, Trong phạm
  vi, Phụ thuộc, ticket 04, 06.
- 24/10/2026 (Đạt): offboarding xuất rồi xóa Bản ghi đồng ý, nhật ký gửi và Danh sách chặn gửi; hai bảng chỉ thêm
  vào `STUDIO_EXCLUSIONS` với cách xóa `platform.purge_tenant_append_only`, theo cách sửa mà studio-skeleton:R4.3
  nhận (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu). Sửa: thêm R5.5, Dữ liệu, ticket 04.
- 24/10/2026 (Đạt): `platform.cross_border_attestations` chỉ có bên ghi và bên đọc ở đường nới R2.5 nên sang W2
  cùng R2.5 (H:compliance-pdpl:dữ-liệu\~compliance-pdpl:ngoài-phạm-vi). Sửa: Trong phạm vi, Ngoài phạm vi, Dữ
  liệu, ticket 03.
- 24/10/2026 (Đạt): thứ tự cửa trong gateway có cấu trúc là công tắc, Lộ trình dữ liệu, rồi hạn mức; ticket 03 chờ
  agent-lifecycle/01 (C:agent-lifecycle/01\~compliance-pdpl/03). Sửa: Phụ thuộc, ticket 03.
- 24/10/2026 (người đặt yêu cầu và Đạt): D11, W1 chưa có đường hai người cho việc nới Lộ trình dữ liệu, nên lệnh
  nới bị khóa ở W1 (R2.7 như đã viết). Sửa: không đổi R2.7.
- 24/10/2026 (Đạt): dịch vụ proxy model của tenant tên `model-proxy` ở mọi nơi. Sửa: dòng D13.
- 24/10/2026 (agent, tạm): tệp chính sách retention giữ là một tệp có phiên bản
  `configs/policies/retention@<semver>.yaml`; các ticket sửa tệp đi thành một chuỗi theo `Blocked by`, mỗi ticket
  ra một bản mới: ticket 04 đứng sau workflow-triggers/02 và trước agent-builder/04, ticket 06 là bản cuối sau
  agent-builder/04 (C:configs:spec\~telemetry-and-audit/03). Sửa: R5, Phụ thuộc, ticket 04, 06. Nếu sai thì: tách
  tệp thành một tệp mỗi bảng, sửa telemetry-and-audit:R5.6 và ADR-0122 (Accepted) quyết 7, và ticket 04 bỏ cạnh chờ
  workflow-triggers/02.
- 24/10/2026 (agent, tạm): `studio.version_assessments` bị xóa khi offboarding qua FK ghép
  `(tenant_id, version_id)` tới `studio.artifact_versions` ON DELETE CASCADE, có index; vì `dw_app` chỉ SELECT,
  INSERT, bảng nằm ngoài tập `_CATALOG_PURGEABLE` và có một dòng `STUDIO_EXCLUSIONS` nêu cách xóa đó, theo luật của
  studio-skeleton/01 cho bảng `dw_app` không DELETE (H:compliance-pdpl:spec\~studio-skeleton:R4.1). FK ghép trỏ tới
  `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)` mà tenant-config/02 thêm, để một dòng đánh giá không
  trỏ được tới phiên bản của công ty khác, nên ticket 05 chờ tenant-config/02; bảng không có `workspace_id` nên có
  một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py` (`CLAUDE.md` mục 'Tenancy and
  authorization'). Sửa: thêm R4.7, CP21, R5.5, Dữ liệu, Phụ thuộc, ticket 05. Nếu sai thì: offboarding xóa bảng qua
  một hàm riêng mà dòng `STUDIO_EXCLUSIONS` nêu, FK ghép và R4.7 giữ nguyên.
- 24/10/2026 (agent, tạm): chỉ lượt xóa của offboarding xóa được dòng `platform.contact_suppressions`, bằng trigger
  `platform.guard_contact_suppression()` từ chối DELETE với 23514 khi công ty khác `offboarding`, cùng hình với
  trigger công tắc của agent-lifecycle:R7.5, thay cho một hàm SECURITY DEFINER của offboarding
  (D:agent-lifecycle:R7.5\~compliance-pdpl:R5.4). Sửa: thêm R5.6, CP19, Dữ liệu, Ngoài phạm vi, Phụ thuộc,
  ticket 04. Nếu sai thì: thu DELETE của `dw_app` trên bảng, offboarding xóa qua một hàm SECURITY DEFINER hẹp và
  bảng vào `STUDIO_EXCLUSIONS`.
- 24/10/2026 (agent, tạm): hội thoại hết hạn (90 ngày, DO-52) xóa qua hàm SECURITY DEFINER hẹp
  `studio.purge_expired_conversations()` của ticket 06, theo mẫu xóa dữ liệu hết hạn của
  ADR-0122 (Accepted) quyết 7, vì `dw_app` không DELETE trên `studio.conversation_messages` và FK ghép của tin nhắn
  tới `studio.conversations` là `ON DELETE RESTRICT` (agent-builder): hàm xóa tin quá mốc rồi hội thoại không còn
  tin nào và có hoạt động cuối trước mốc, ở mọi công ty; lane lưu giữ gọi hàm và ghi trong cùng giao dịch một sự
  kiện `studio.conversation.expired` đứng tên chính lane kèm số dòng cho mỗi workspace có dòng bị xóa, ở công ty và
  workspace đó, vì `platform.audit_events.workspace_id` là NOT NULL
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:299`) (ADR-0011 (Accepted)). Sửa:
  thêm R5.7, R5.8, CP20, Trong phạm vi, Dữ liệu, Phụ thuộc, ticket 06. Nếu sai thì: hàm và ticket 06 đổi cách xóa
  (ví dụ DROP PARTITION của tháng đã quá hạn) mà R5.7 giữ nguyên; audit mỗi hội thoại một sự kiện thì hàm trả một
  dòng mỗi hội thoại và R5.8, CP20 đổi theo.
- 24/10/2026 (agent, tạm): `pd_category_required` là một `errors[].code` của 422 `validation_failed` có con trỏ tới
  trường (app-standards:R1.3), không phải `details.reason_code`; lát này là chủ mã, custom-objects:R2.2,
  workflow-triggers:R4.1 và marketing-pilot/02 dẫn cùng hình. Sửa: R1.1, CP1, API, ticket 01. Nếu sai thì: mã về
  `details.reason_code` của 422 và bốn chỗ dẫn đổi theo.
- 24/10/2026 (agent, tạm): R5.5 và mục Phụ thuộc dẫn usage-and-limits:R3.10, hợp đồng của
  `platform.purge_tenant_append_only` trên mọi bảng `append_only` của sổ, thay usage-and-limits:R3.8, tiêu chí
  offboarding của chính các bảng usage-and-limits. Sửa: R5.5, Phụ thuộc. Nếu sai thì: R5.5 dẫn lại số tiêu chí mà
  usage-and-limits đặt cho hàm.
- 24/10/2026 (agent, tạm): `studio.purge_expired_conversations()` không nhận đối số và giữ hạn 90 ngày trong thân
  hàm, theo tiền lệ `platform.prune_notifications()` ("It takes no argument, so no caller can widen it to recent rows",
  `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:28-29`), nên không bên gọi nào nới hàm tới tin
  còn hạn; REVOKE ALL FROM PUBLIC rồi EXECUTE cho `dw_app`, vai mà lane lưu giữ của worker dùng, như tiền lệ đó làm.
  Hạn trong thân hàm là bản sao thứ hai của thời hạn dưới khóa `studio.conversation_messages` và
  `studio.conversations` của tệp chính sách retention, nên một test ranh giới đỏ khi hai bên khác nhau
  (`failure-modes.md` #2). Dòng tạm cùng ngày về hội thoại hết hạn ở trên bỏ chữ ký `(p_cutoff timestamptz)` theo
  dòng này. Sửa: R5.7, thêm R5.9, CP22, Trong phạm vi, Dữ liệu, Phụ thuộc, ticket 06. Nếu sai thì: hàm nhận lại mốc do lane
  tính từ tệp chính sách retention, kèm một kiểm từ chối mốc muộn hơn thời hạn của tệp, và R5.9, CP22 thành test của
  kiểm đó.

## Danh sách ticket

| #   | Ticket                                                                                                        |
| --- | ------------------------------------------------------------------------------------------------------------- |
| 01  | [Từ vựng loại dữ liệu cá nhân một chủ](issues/01-tu-vung-du-lieu-ca-nhan.md)                                  |
| 02  | [Ý kiến luật sư Việt Nam cho PDPL và Luật AI](issues/02-y-kien-luat-su.md)                                    |
| 03  | [Lớp lộ trình dữ liệu ở model gateway, mọi lời gọi qua cùng cổng](issues/03-tuyen-du-lieu-o-model-gateway.md) |
| 04  | [Sàn gửi tin marketing: đồng ý, chặn gửi, khung giờ, tần suất](issues/04-san-gui-tin-marketing.md)            |
| 05  | [Phân tích bộ ba nguy hiểm và năng lực khi gửi kiểm định](issues/05-phan-tich-bo-ba-khi-xuat-ban.md)          |
| 06  | [Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13](issues/06-lop-luu-giu-du-lieu-ca-nhan.md)      |
