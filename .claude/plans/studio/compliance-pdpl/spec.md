# Tuân thủ PDPL, Luật AI và an toàn agent cho Studio

Status: needs-info (DO-53)
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio xử lý dữ liệu cá nhân của khách hàng của công ty khách (lead, khách hàng) trên nền tảng đặt tại
Việt Nam, gọi model có thể ở nước ngoài và gửi tin marketing qua Zalo và email. Lát này biến các nghĩa vụ
PDPL (Luật 91/2025/QH15 và Nghị định 356/2025/ND-CP, hiệu lực 1/1/2026) và Luật AI (134/2025/QH15, hiệu
lực 1/3/2026) thành kiểm soát của sản phẩm: phân loại dữ liệu cá nhân một chủ, Lộ trình dữ liệu ở model
gateway, Sàn gửi tin có đồng ý, phân tích bộ ba nguy hiểm khi gửi kiểm định, và lớp lưu giữ
(ADR-0106 (Proposed), ADR-0123 (Proposed), ADR-0124 (Proposed), ADR-0125 (Proposed)). Khi chưa có ý kiến luật sư
(ticket 02), lát Marketing chỉ chạy trên lead giả lập (YC89, do marketing-pilot ép). W1 phục vụ YC71,
YC84, YC85, YC86 và YC88, một phần YC82. Status needs-info vì DO-53 (Studio có phải dịch vụ xử lý dữ liệu
cá nhân cần giấy chứng nhận trước tenant trả phí đầu tiên) có thể chặn việc bán.

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

- R1.1 NẾU một yêu cầu tạo một trường không có `pd_category`, THÌ API chủ bảng PHẢI trả 422
  `pd_category_required` và không tạo trường.
- R1.2 Một ràng buộc CHECK `pd_category` của một bảng định nghĩa trường PHẢI bằng đúng danh sách của
  `dw_kernel.personal_data` (`none`, `basic`, `sensitive`).
- R1.3 NẾU một bảng định nghĩa trường nhận một giá trị `pd_category` hay `sensitive_type` ngoài danh sách
  kernel, hay một giá trị thiếu nhãn tiếng Việt, THÌ test drift PHẢI đỏ.
- R1.4 ĐỐI VỚI một trường `Nhạy cảm`, bảng định nghĩa trường PHẢI mang `sensitive_type` từ danh sách Nghị
  định 356 Điều 4.1, còn trường `Cơ bản` hay `Không` thì không mang.

### R2 — Lộ trình dữ liệu ở model gateway, mọi lời gọi model qua cùng cổng

Mọi lời gọi model của Studio theo Lộ trình dữ liệu chặt nhất của công ty, workspace và agent, mặc định
Chỉ trong Việt Nam, ghi lộ trình trên từng lời gọi (YC85; ADR-0123 (Proposed)).

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
  ngoài, THÌ cổng phát hành PHẢI từ chối và không phát hành.

### R3 — Sàn gửi tin kiểm trong ToolExecutor

Một tin marketing tới một người chỉ rời đi khi qua Sàn gửi tin kiểm trong ToolExecutor so với các Bản ghi
đồng ý của nền tảng (YC86; ADR-0124 (Proposed)).

- R3.1 NẾU một lead không có Bản ghi đồng ý đúng mục đích và kênh còn hiệu lực, đang ở Danh sách chặn gửi,
  ngoài Khung giờ không gửi, hay vượt Giới hạn tần suất gửi, THÌ ToolExecutor PHẢI trả `blocked:<lý do>`,
  ghi `marketing.send_refused` và không gọi nhà cung cấp.
- R3.2 KHI ToolExecutor chạy một hành động connector mà manifest đánh dấu là gửi tin, nó PHẢI hỏi
  `SendAdmissionPort` trước khi egress client gửi, cho mọi đường (node `tool.call`, lời gọi công cụ của
  agent, quy trình dùng như công cụ).
- R3.3 KHI một tin rời đi, ToolExecutor PHẢI ghi một dòng nhật ký gửi mang `consent_record_id` đã dựa vào
  và một sự kiện `marketing.sent`.
- R3.4 KHI một người bấm link hủy đăng ký hay trả từ khóa hủy, nền tảng PHẢI ghi một dòng Danh sách chặn
  gửi trong vòng 5 phút và kiểm lại một tin đang chờ trước khi gửi.
- R3.5 NẾU một overlay công ty đặt Giới hạn tần suất gửi hay Khung giờ không gửi lỏng hơn Sàn gửi tin, THÌ
  bộ nạp overlay PHẢI trả 422 và không nhận overlay.
- R3.6 NẾU `GET /api/v1/public/unsubscribe/{token}` nhận một token sai chữ ký HMAC, THÌ route công khai
  PHẢI trả 404 và không ghi dòng nào, không lộ địa chỉ có tồn tại hay không.

### R4 — Phân tích bộ ba nguy hiểm khi gửi kiểm định

Mỗi phiên bản agent và quy trình được phân tích khi gửi kiểm định; một đường nối đầu vào không tin cậy,
dữ liệu riêng và tác động ra ngoài phải qua người trước tác động (YC71; ADR-0125 (Proposed)).

- R4.1 KHI một phiên bản được gửi kiểm định, `capability_analysis` PHẢI đọc nhãn `untrusted_source`,
  `private_data` và `external_effect` từ một bảng điều phối theo loại node và loại công cụ, coi một loại
  lạ là mang cả ba nhãn.
- R4.2 NẾU một quy trình có một đường từ đầu vào bên ngoài qua dữ liệu riêng tới tác động ra ngoài mà
  không có node phê duyệt chi phối node tác động, THÌ thao tác gửi kiểm định PHẢI trả 422 kèm đường vi
  phạm.
- R4.3 NẾU một agent mang cả ba nhãn khai Mức tự chủ trên A2, THÌ thao tác gửi kiểm định PHẢI trả 422
  `capability_trifecta_autonomy` kèm hai cách sửa.
- R4.4 NẾU một phiên bản dùng một công cụ thiếu một trong ba phân loại, THÌ thao tác gửi kiểm định PHẢI
  trả 422 `tool_unclassified`.
- R4.5 NẾU một overlay công ty hay một Mức tự chủ muốn hạ sàn bộ ba (bỏ node phê duyệt, nâng Mức tự chủ
  trên A2), THÌ cổng phát hành PHẢI từ chối, vì sàn chỉ siết được.

### R5 — Lưu giữ cho kho dữ liệu cá nhân của lát, dẫn Nghị định 356

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa, và dẫn chiếu đổi từ Nghị định 13/2023
sang Nghị định 356 (YC88).

- R5.1 ĐỐI VỚI mỗi kho dữ liệu cá nhân mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi
  marketing, lịch sử sự kiện Data Hub, hội thoại), `configs/policies/retention@1.8.0.yaml` PHẢI khai một
  thời hạn và một bộ xóa đã đăng ký.
- R5.2 NẾU một kho dữ liệu cá nhân không có bộ xóa đăng ký, THÌ test tập bộ xóa PHẢI đỏ.
- R5.3 Chú thích thời hạn Nhật ký kiểm toán trong `configs/policies/retention@1.8.0.yaml` PHẢI dẫn PDPL và
  Nghị định 356, không dẫn Nghị định 13/2023.

## Trong phạm vi

- Bảng, cột và ràng buộc ở mục Dữ liệu; route ở mục API.
- Mã: `dw_kernel.personal_data` (từ vựng `pd_category`, `sensitive_type`, Trường định danh chủ thể, helper
  CHECK và helper test catalog); `ResidencyGate` và `effective_route_class`; `MarketingSendPolicy` thỏa
  `SendAdmissionPort`; module thuần `capability_analysis` và bảng điều phối nhãn ở composition root;
  `configs/policies/marketing_send@1.0.0.yaml`, `configs/policies/studio_risk@1.0.0.yaml` và lớp mới trong
  `configs/policies/retention@1.8.0.yaml`.
- Bảng mới: `platform.cross_border_attestations`, `platform.consent_records`,
  `platform.contact_suppressions`, `platform.marketing_send_log`; cột `data_route_class` trên
  `platform.tenants` và `platform.workspaces`.
- Route công khai `GET /api/v1/public/unsubscribe/{token}`; `PATCH /api/v1/admin/tenant` thêm
  `data_route_class`.
- Audit: `marketing.sent`, `marketing.send_refused`, `residency.class_changed`, `residency.attested`.

## Ngoài phạm vi

| Việc                                                                                                | Vì sao                                                           | Chủ                                    |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------- |
| W2: Hạn chế xử lý và Từ chối xử lý tự động trên bản ghi (YC49, YC67)                                | cần đầu bản ghi của custom-objects và node của workflow-nodes    | compliance-pdpl, đợt sau (W2)          |
| W2: Sổ sự cố dữ liệu cá nhân `platform.pd_incidents` và runbook 72 giờ (YC90)                       | trước dữ liệu thật; chỉ Người vận hành đọc                       | compliance-pdpl, đợt sau (W2)          |
| W2: Presidio tiếng Việt có số đo; tối thiểu hóa trước khi gọi (`cross_border_minimised`)            | bộ dò là kiểm soát phụ, đo recall trước khi dựa vào              | compliance-pdpl, đợt sau (W2)          |
| W2: Yêu cầu của chủ thể dữ liệu — màn, API, cổng xóa theo kho (YC90)                                | `DataSubjectPort` đăng ký một bản theo kho ở composition root    | compliance-pdpl, đợt sau (W2)          |
| W2: Mã hóa checkpoint theo khóa công ty; TLS chặng nội bộ; cache chia theo công ty (YC92)           | sau khóa vault; đo nhà cung cấp cache trước                      | compliance-pdpl; connections-and-vault |
| W2: Mức rủi ro AI `studio.version_assessments`, tờ giải thích, thông báo AI (YC93); sổ xử lý (YC91) | chờ ý kiến luật sư về tiêu chí tầng rủi ro                       | compliance-pdpl; agent-lifecycle       |
| W2: Khoanh vùng sự cố, audit đọc trường `Nhạy cảm`, taint động; gửi hoãn tới Khung giờ không gửi    | sau sổ sự cố và taint ở executor                                 | compliance-pdpl, đợt sau (W2)          |
| W3: Hồ sơ công ty được quản lý, gói bằng chứng, khóa do khách quản lý, báo cáo sự cố AI             | v2                                                               | compliance-pdpl, đợt sau (W3)          |
| Ép lát Marketing chỉ chạy trên lead giả lập tới khi có ý kiến luật sư và DPA (YC89)                 | do Chế độ chạy và Danh sách người nhận thử ép; ticket 02 gỡ chặn | marketing-pilot; tenant-config         |
| Telemetry và log không mang nội dung                                                                | một chủ là telemetry-and-audit/01                                | telemetry-and-audit                    |
| Checkpoint chỉ dựng lại kiểu trong allowlist                                                        | gộp vào foundations-hardening/02                                 | foundations-hardening                  |
| RecordService, bảng bản ghi và cờ trên đầu bản ghi                                                  | lát này đọc bản ghi qua Object Service                           | custom-objects                         |
| ToolExecutor, loại công cụ, bọc StructuredTool, cờ taint lượt chạy                                  | lát này tiêu `SendAdmissionPort` trong executor                  | tools-and-skills                       |
| Egress client, vault và kết nối                                                                     | lát này khai `data_location` trên manifest kết nối               | connections-and-vault                  |
| Nộp hồ sơ, xin giấy chứng nhận, bổ nhiệm DPO; SOC 2, ISO 27001/27701/42001                          | quy trình pháp lý; sản phẩm chỉ sinh bằng chứng                  | không làm                              |

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
- `platform.cross_border_attestations`: RLS công ty; `processor`, `ctia_ref`, `attested_by`, `expires_at`,
  `revoked_at`; dùng khi Lộ trình là ra nước ngoài.
- `platform.consent_records`: chỉ thêm, RLS công ty; `subject_ref` (E.164, email thường hay Zalo user id),
  `purpose` CHECK (`marketing`, `transactional`), `channel` CHECK (`zns`, `email`, `sms`, `messenger`,
  `zalo_oa`), `state`, `captured_at`, `source`, `evidence_ref`, `notice_version`, `withdrawn_at`; đồng ý
  hiện hành là dòng mới nhất theo `(subject_ref, purpose, channel)`; index
  `(tenant_id, subject_ref, channel, purpose, captured_at DESC)`.
- `platform.contact_suppressions`: PK `(tenant_id, channel, address_hash)`; RLS công ty.
- `platform.marketing_send_log`: phân vùng theo tháng qua `platform.ensure_time_partitions`; mang
  `consent_record_id`, nguồn gốc tin AI soạn; RLS dạng workspace của `CLAUDE.md`.

## API

- `PATCH /api/v1/admin/tenant` (`platform.tenant.settings.write`): thêm `data_route_class`; audit
  `residency.class_changed`, `residency.attested`; nới về ra nước ngoài cần người duyệt thứ hai.
- `GET /api/v1/public/unsubscribe/{token}`: route công khai, HMAC một địa chỉ, idempotent, rate-limited,
  không lộ địa chỉ có tồn tại.
- Lỗi theo vỏ `application/problem+json` của ADR-0108 (Proposed); `details.reason_code`:
  `pd_category_required`, `residency_refused`, `blocked:<lý do>`, `capability_trifecta_autonomy`,
  `tool_unclassified`.

## Kiểm soát

| #    | Kiểm soát                                                            | Yêu cầu          | Test âm                                                                                                                                               |
| ---- | -------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| CP1  | Trường thiếu `pd_category` không tạo được                            | R1.1, R1.2, R1.3 | POST một trường không có `pd_category` → 422 `pd_category_required`; thêm một giá trị CHECK ngoài enum kernel → test drift đỏ                         |
| CP2  | `vn_only` không gửi byte nào ra nước ngoài                           | R2.2             | Agent `vn_only` với tuyến `foreign` → từ chối trước khi gửi, adapter giả ghi 0 lời gọi; gỡ cổng → test đỏ                                             |
| CP3  | Mọi đường gọi model qua cùng cổng                                    | R2.3             | Chép lời khi `vn_only` tới URL `foreign` → job `failed` lý do `residency_refused`, 0 request; gỡ cổng ở embedding → test đỏ                           |
| CP4  | Workspace, agent không nới lộ trình                                  | R2.4             | Đặt `cross_border_full` ở workspace khi công ty `vn_only` → 422, không đổi dòng                                                                       |
| CP5  | Nới lộ trình cần người thứ hai và xác nhận còn hạn                   | R2.5             | Nới công ty sang ra nước ngoài bởi một người, không xác nhận → từ chối, lộ trình giữ nguyên                                                           |
| CP6  | Trường cá nhân vào prompt trên tuyến ra nước ngoài bị chặn phát hành | R2.6             | Gắn `full_name` vào prompt trên tuyến `cross_border_full` → phát hành từ chối; gỡ kiểm → test đỏ (MP7)                                                |
| CP7  | Không gửi marketing khi thiếu đồng ý                                 | R3.1             | Lead không có Bản ghi đồng ý → `blocked:no_consent`, 0 tin, `marketing.send_refused`; gỡ kiểm → test đỏ                                               |
| CP8  | Sàn gửi kiểm trong ToolExecutor, không ở node                        | R3.2             | Gọi hành động gửi qua node, qua công cụ agent, qua quy trình-như-công-cụ không đồng ý → cả ba bị chặn; gỡ kiểm ở executor → test đỏ (MP1, MP12, MP15) |
| CP9  | Hủy đăng ký có hiệu lực trong 5 phút                                 | R3.4             | Bấm link hủy → lần gửi sau `blocked:suppressed` trong ≤ 5 phút; tin đang chờ bị kiểm lại                                                              |
| CP10 | Token hủy sai trả 404 không lộ tồn tại                               | R3.6             | `GET /api/v1/public/unsubscribe/{token}` token sai chữ ký → 404, không dòng nào, không lộ địa chỉ                                                     |
| CP11 | Công ty không nới sàn gửi                                            | R3.5             | Overlay đặt tần suất lỏng hơn Sàn gửi tin → 422; gỡ kiểm → test đỏ                                                                                    |
| CP12 | Bộ ba nguy hiểm không gửi kiểm định được                             | R4.2             | Bỏ node phê duyệt khỏi workflow pilot → gửi kiểm định 422 nêu đường; đường `score → send` không qua `approve` → 422 nêu đường (MP2)                   |
| CP13 | Agent bộ ba phải tự chủ ≤ A2                                         | R4.3             | Agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy`; gỡ kiểm → test đỏ                                                                      |
| CP14 | Công cụ thiếu phân loại không gửi kiểm định được                     | R4.4             | Dùng công cụ thiếu một phân loại → 422 `tool_unclassified`; node loại lạ → coi như cả ba nhãn                                                         |
| CP15 | Không cấu hình nào hạ sàn bộ ba                                      | R4.5             | Overlay bỏ node phê duyệt hay nâng Mức tự chủ trên A2 cho phiên bản bộ ba → phát hành từ chối                                                         |
| CP16 | Mỗi lớp retention mới có bộ xóa                                      | R5.1, R5.2       | Một lớp retention thiếu bộ xóa đăng ký → test tập bộ xóa đỏ                                                                                           |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của ticket).
- Lát Marketing chạy hết đường với `vn_only` hoặc với Xác nhận chuyển dữ liệu ra nước ngoài còn hạn; có
  Bản ghi đồng ý, có hủy đăng ký, có node phê duyệt.
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- field-security: hàm quyết quyền đọc trường, dấu `Đã ẩn`, chế độ `Mở`/`Bảo vệ` dùng `pd_category` của lát
  này (`.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`), đang viết đợt này; dẫn
  theo đường dẫn.
- model-connections: `ModelResolver` theo công ty và `data_location` trên bí danh model
  (`.claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md`); ADR-0118 (Proposed).
- custom-objects: RecordService và tham chiếu chủ thể cho đồng ý
  (`.claude/plans/studio/custom-objects/issues/03-record-service.md`).
- tools-and-skills: ToolExecutor tiêu `SendAdmissionPort` và phân loại công cụ theo ADR-0116 (Proposed),
  đang viết đợt này
  (`.claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md`).
- workflow-engine: lược đồ `dw.workflow/v1` và cổng phát hành cho phân tích bộ ba
  (`.claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md`).
- agent-lifecycle: cổng gửi kiểm định và phát hành hai người
  (`.claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md`).
- agent-builder: loại agent và khung prompt cho nhãn năng lực
  (`.claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md`).
- connections-and-vault: egress client và `data_location` trên manifest kết nối, đang viết đợt này; dẫn
  theo đường dẫn.
- `configs/policies/retention@1.8.0.yaml` đồng sở hữu với telemetry-and-audit: lát đó giữ lớp run, Bước
  chạy, Sổ sử dụng; lát này thêm lớp Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi, sự kiện Data Hub,
  hội thoại (`.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`).
- Kiểm lại khi: `pd_category` của `dw_kernel.personal_data` đổi hình → R1, field-security; cửa model của
  model-connections đổi hợp đồng → R2; ToolExecutor của tools-and-skills đổi điểm chèn → R3.2; cổng phát
  hành của agent-lifecycle đổi → R4; ý kiến luật sư (DO-53, DO-54, DO-55) → R2, R3, R5 và Status spec.

## Câu hỏi còn mở

- Q1. Studio có phải dịch vụ xử lý dữ liệu cá nhân cần giấy chứng nhận Bộ Công an trước tenant trả phí đầu
  tiên, và bên nào giữ? Chủ: luật sư. Chặn: Status spec, ticket 02 (DO-53).
- Q2. Số chống spam (tần suất, khung giờ, số người nhận mỗi lượt), và vai trò bên kiểm soát và bên xử lý
  của pilot là gì? Chủ: luật sư và người yêu cầu. Chặn: R3.1, R3.5, R2.5, ticket 02, 04 (DO-54, DO-55).

## Quyết định

- 23/10/2026 (người yêu cầu): D4: lát Marketing là ví dụ chạy và gói nghiệp vụ đầu tiên; kết thúc bằng một
  tin Zalo hay email sau một phê duyệt của người. Sửa: R3, R4.
- 23/10/2026 (người yêu cầu): D11 (DO-07): nới Lộ trình dữ liệu cần một người đề xuất và một người duyệt
  khác. Sửa: R2.5.
- 23/10/2026 (người yêu cầu): D13 (DO-19): model của công ty khách đi qua một lane LiteLLM riêng, không
  trạng thái; `data_location` khai theo bí danh, không khai thì coi là nước ngoài. Sửa: R2.1, R2.2.
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

## Danh sách ticket

| #   | Ticket                                                                                                        |
| --- | ------------------------------------------------------------------------------------------------------------- |
| 01  | [Từ vựng loại dữ liệu cá nhân một chủ](issues/01-tu-vung-du-lieu-ca-nhan.md)                                  |
| 02  | [Ý kiến luật sư Việt Nam cho PDPL và Luật AI](issues/02-y-kien-luat-su.md)                                    |
| 03  | [Lớp lộ trình dữ liệu ở model gateway, mọi lời gọi qua cùng cổng](issues/03-tuyen-du-lieu-o-model-gateway.md) |
| 04  | [Sàn gửi tin marketing: đồng ý, chặn gửi, khung giờ, tần suất](issues/04-san-gui-tin-marketing.md)            |
| 05  | [Phân tích bộ ba nguy hiểm và năng lực khi phát hành](issues/05-phan-tich-bo-ba-khi-xuat-ban.md)              |
| 06  | [Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13](issues/06-lop-luu-giu-du-lieu-ca-nhan.md)      |
