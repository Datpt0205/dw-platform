# Kết nối máy chủ MCP của tenant qua cổng MCP tách biệt

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Công ty muốn agent của mình dùng công cụ của máy chủ MCP bên ngoài (YC68). Nền tảng là client MCP qua
SDK chính thức `mcp` 2.x chạy trong Cổng MCP, một dịch vụ cô lập không có vai Postgres và không giữ bí
mật khi nghỉ; ở v1 công ty chỉ đăng ký máy chủ trong danh mục nền tảng (DO-46.1). Một công cụ MCP chỉ
thành phiên bản Đang dùng của loại `tool` sau khi một người khác người đăng ký duyệt đúng văn bản mô hình
sẽ đọc, ghim bằng Định nghĩa đã ghim; định nghĩa đổi thì lời gọi bị từ chối và công tắc của công cụ chặn
nó; mọi lời gọi đi qua ToolExecutor (ADR-0116 (Accepted) quyết 8-9). Lát Marketing của W1 không dùng MCP,
nên spec này chốt phạm vi W2 và chưa có ticket.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Workspace uv chỉ có `apps/api`, `apps/docgen`, `apps/worker` và các gói (`pyproject.toml:12`); `uv.lock`
  không có `mcp`, `fastmcp` hay `langchain-mcp-adapters` (grep, 0 dòng). Thiếu: chưa có Cổng MCP và
  chưa có client MCP nào.
- `ToolRegistry.resolve` không nhận tenant (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tools.py:45`),
  và executor phân giải công cụ không theo tenant
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:146`). Ràng buộc: công cụ MCP chỉ
  tới mô hình qua executor phân giải theo tenant của tools-and-skills (ADR-0116 (Accepted) quyết 3).
- `ensure_allowed_outbound_url` phân giải một lần lúc kiểm và chặn năm cờ địa chỉ
  (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:38-44`), còn máy chủ trong danh sách cho phép
  thì trả về không kiểm (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:68-69`); đo lại ngày
  23/10/2026 trên CPython 3.13.15, `100.64.0.1` và `100.100.100.200` lọt qua năm cờ đó. Thiếu: chưa
  chặn địa chỉ không toàn cục, chưa ghim địa chỉ lúc kết nối, chưa có luật chuyển hướng.
- `dw-internal` là mạng nội bộ (`infra/compose/docker-compose.yml:17-18`); `api` và `worker` ở cả
  `dw-internal` lẫn `dw-edge` có đường ra (`infra/compose/docker-compose.yml:309`,
  `infra/compose/docker-compose.yml:467`); `docgen` chỉ ở `dw-sandbox`, với `read_only`, `cap_drop`,
  `no-new-privileges`, `mem_limit`, `pids_limit` (`infra/compose/docker-compose.yml:355-370`). Ràng
  buộc: Cổng MCP chép mức siết của `docgen` và không vào `dw-internal`.
- Prefix nghiêm từ chối người yêu cầu và buộc ghi chú
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:118-129`); yêu cầu không lượt
  chạy ghi sự kiện quyết định vào outbox
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:245`); API đặt prefix nghiêm ở
  `apps/api/src/dw_api/bootstrap/runtime.py:237`. Ràng buộc: Duyệt công cụ dùng đúng cơ chế này với
  prefix `studio.mcp.`.
- Lane ghi audit bằng `system_actor` của chính nó
  (`packages/python/dw_platform/src/dw_platform/domain/audit.py:57`). Ràng buộc: lane `mcp_drift` ghi
  audit là `system:mcp_drift`.

## Mục tiêu

### R1 — Cổng MCP tách biệt

Mọi lưu lượng MCP đi qua một Cổng MCP không giữ bí mật, chỉ ra internet qua egress proxy (YC68;
ADR-0116 (Accepted) quyết 8).

- R1.1 Cổng MCP PHẢI không mở được kết nối nào tới PostgreSQL, Valkey hay Qdrant, và môi trường của nó
  không có biến kết nối database nào.
- R1.2 Cổng MCP PHẢI chỉ ra internet qua egress proxy.
- R1.3 KHI runtime gọi một công cụ MCP, Cổng MCP PHẢI dựng một client mới cho riêng lời gọi đó với
  credential ngắn hạn runtime trao kèm, không giữ credential nào sau khi lời gọi kết thúc.
- R1.4 Cổng MCP PHẢI chỉ nói Streamable HTTP qua HTTPS với máy chủ đời 2026-07-28 và đời 2025, không
  khai capability sampling, roots, logging hay elicitation (elicitation tới v1.5), và không chạy máy chủ
  stdio.
- R1.5 NẾU máy chủ gửi yêu cầu sampling, roots, elicitation hay một yêu cầu client không khai, THÌ Cổng
  MCP PHẢI từ chối yêu cầu đó và trả lượt chạy một lỗi có kiểu.
- R1.6 NẾU URL máy chủ, metadata tài nguyên được bảo vệ hay metadata máy chủ cấp quyền phân giải tới
  địa chỉ không toàn cục, hoặc DNS đổi giữa lúc kiểm và lúc dùng, THÌ Cổng MCP PHẢI từ chối kết nối.
- R1.7 NẾU máy chủ chuyển hướng sang origin khác, THÌ Cổng MCP PHẢI không theo chuyển hướng và không gửi
  header khóa API nào tới origin đó.
- R1.8 NẾU máy chủ trả quá 128 công cụ, mô tả quá 4 KiB, schema quá 64 KiB hay sâu quá 10 tầng, schema
  có `$id` hay `$ref` ngoài, hoặc kết quả quá 1 MiB, THÌ Cổng MCP PHẢI từ chối phần đó mà không tải gì
  theo `$ref` (128 công cụ thì nhận, 129 thì từ chối).
- R1.9 KHI Cổng MCP lưu đệm một danh sách, Cổng MCP PHẢI khóa mục đệm theo tenant, máy chủ, mã băm của
  người gọi và phương thức, giữ không quá 10 phút dù `ttlMs` lớn hơn, và không bao giờ phục vụ danh sách
  `cacheScope: private` cho người khác.
- R1.10 Cổng MCP PHẢI không chuyển `instructions` của máy chủ tới runtime.
- R1.11 NẾU Máy chủ MCP ở trạng thái `disabled`, hoặc nền tảng hay tenant đang đóng băng, THÌ Cổng MCP
  PHẢI không gửi request nào ra ngoài.
- R1.12 Cổng MCP PHẢI không gửi `traceparent` hay `baggage` tới máy chủ MCP nào, kể cả máy chủ trong
  danh mục nền tảng; `traceparent` chỉ đi tới Cổng MCP, một chặng nội bộ.

### R2 — Đăng ký Máy chủ MCP

Quản trị viên công ty đăng ký một máy chủ MCP và chụp định nghĩa công cụ của nó (ADR-0116 (Accepted)
quyết 8).

- R2.1 KHI người giữ `studio.mcp.manage` đăng ký một Máy chủ MCP, API Studio PHẢI ghi máy chủ với URL
  chuẩn hóa và audit `studio.mcp_server.registered` trong một giao dịch.
- R2.2 NẾU URL không phải `https`, chứa userinfo, là IP literal, hoặc có cổng khác 443 và ngoài 1024 tới
  65535 (1023 thì từ chối), THÌ API Studio PHẢI trả 422 và không ghi gì.
- R2.3 NẾU người gọi không giữ `studio.mcp.manage` ở workspace đang làm việc, THÌ API Studio PHẢI trả 403
  và không ghi gì.
- R2.4 NẾU URL đăng ký không khớp một mục của danh mục nền tảng `configs/mcp/catalog/`, THÌ API Studio
  PHẢI trả 422 và không ghi gì.
- R2.5 NẾU `region` của máy chủ nằm ngoài Việt Nam và công ty không giữ Xác nhận chuyển dữ liệu ra nước
  ngoài còn hiệu lực nêu `processor` của máy chủ đó, THÌ API Studio PHẢI trả 422 và không ghi gì.
- R2.6 KHI người giữ `studio.mcp.manage` yêu cầu khám phá một máy chủ đã đăng ký, API Studio PHẢI ghi
  một ảnh chỉ thêm của mọi định nghĩa công cụ máy chủ trả về.

### R3 — Duyệt công cụ hai người

Một công cụ MCP chỉ tới mô hình sau khi một người khác người đăng ký duyệt đúng văn bản mô hình đọc
(YC68; D11; ADR-0116 (Accepted) quyết 4, 9).

- R3.1 KHI một ảnh có công cụ mới hay công cụ đổi định nghĩa, API Studio PHẢI tạo cho mỗi công cụ đó một
  phiên bản loại `tool` ở `awaiting_approval` kèm một yêu cầu phê duyệt không lượt chạy
  `studio.mcp.tool_approval` có `required_scope` `studio.mcp.approve`, hiện tên `mcp_<alias>__<tool>` tối
  đa 64 ký tự, mô tả mô hình sẽ đọc, schema đã dựng, Gợi ý của máy chủ, kết quả lint và mã băm.
- R3.2 NẾU người quyết định là người đã đăng ký máy chủ và giữ `approvals.decide` cùng tem
  `studio.mcp.approve`, THÌ luồng phê duyệt PHẢI trả 409 và không ghi quyết định nào.
- R3.3 NẾU người quyết định không giữ `studio.mcp.approve`, THÌ luồng phê duyệt PHẢI trả 404 và không
  ghi quyết định nào.
- R3.4 KHI yêu cầu `studio.mcp.tool_approval` được duyệt kèm ghi chú, dịch vụ phát hành của loại `tool`
  PHẢI đưa phiên bản đó lên `live` qua máy giai đoạn, không cần `gate_run_id`, với Định nghĩa đã ghim là
  SHA-256 trên dạng RFC 8785 của `name`, `title`, `description`, `inputSchema`, `outputSchema`,
  `annotations`.
- R3.5 NẾU công cụ thiếu Gợi ý của máy chủ, THÌ API Studio PHẢI đề xuất mức tác động `external` với chính
  sách duyệt `always`, và không bao giờ để `readOnlyHint: true` tự hạ mức tác động xuống `none`.

### R4 — Gọi công cụ MCP và phát hiện lệch

Mỗi lời gọi đi qua ToolExecutor và chỉ chạy trên định nghĩa đã được duyệt (ADR-0116 (Accepted) quyết
3, 5, 9).

- R4.1 KHI lượt chạy gọi một công cụ MCP, ToolExecutor PHẢI kiểm quyền, chế độ chạy, phê duyệt và khóa
  chống lặp như mọi công cụ khác trước khi gọi Cổng MCP.
- R4.2 NẾU định nghĩa hiện tại của máy chủ khác Định nghĩa đã ghim, THÌ Cổng MCP PHẢI từ chối lời gọi
  với `mcp_tool_drifted` trước khi gửi `tools/call`.
- R4.3 KHI một lời gọi bị từ chối với `mcp_tool_drifted`, runtime PHẢI mở công tắc Tắt khẩn cấp
  `scope_type` `tool` cho công cụ đó, ghi audit `studio.mcp_tool.drift_detected` và một sự kiện outbox cho
  agent-lifecycle trong một giao dịch.
- R4.4 TRONG KHI công tắc của một công cụ đang mở, ToolExecutor PHẢI từ chối mọi lời gọi tới công cụ đó
  trước khi phân giải, với `artifact_killed`.
- R4.5 KHI lane `mcp_drift` liệt kê lại một máy chủ có công cụ đã duyệt, lane `mcp_drift` PHẢI ghi lệch
  cấu hình cho công cụ thêm, bớt, đổi định nghĩa, đổi đời giao thức hay đổi máy chủ cấp quyền, với
  actor `system:mcp_drift`.
- R4.6 NẾU `structuredContent` không khớp `outputSchema` đã ghim, THÌ ToolExecutor PHẢI trả lượt chạy
  lỗi `tool_output_invalid` và không đưa kết quả tới mô hình.
- R4.7 KHI một công cụ MCP trả kết quả, ToolExecutor PHẢI bọc nội dung là dữ liệu ngoài theo
  ADR-0010 (Accepted) và đánh dấu lượt chạy Đã tiếp xúc nội dung ngoài.
- R4.8 KHI gọi công cụ MCP, Cổng MCP PHẢI áp thời hạn mặc định 30 giây mỗi lời gọi, cấu hình được tới
  trần 120 giây (121 giây thì từ chối cấu hình).
- R4.9 KHI phiên bản mới của một công cụ đang có công tắc mở được duyệt và lên `live`, dịch vụ phát hành
  của loại `tool` PHẢI giữ công tắc đó mở, để chỉ một yêu cầu Bật lại do người khác người xin quyết gỡ được
  nó (agent-lifecycle:R8.6, agent-lifecycle:R8.7).

### R5 — Cấp quyền MCP trên broker của kết nối

Máy chủ cần OAuth được cấp quyền theo spec MCP 2026-07-28 trên broker của connections-and-vault, không
bao giờ bằng token của nền tảng (ADR-0116 (Accepted) quyết 8; ADR-0115 (Accepted)).

- R5.1 NẾU máy chủ cấp quyền không quảng bá PKCE `S256`, THÌ broker PHẢI từ chối luồng cấp quyền.
- R5.2 NẾU `iss` trong phản hồi cấp quyền khác máy chủ cấp quyền đã khám phá, THÌ broker PHẢI từ chối
  trước khi đổi mã.
- R5.3 KHI broker gửi yêu cầu cấp quyền hay yêu cầu đổi mã, broker PHẢI gửi tham số `resource` của RFC
  8707 trong cả hai.
- R5.4 NẾU máy chủ MCP đổi máy chủ cấp quyền, THÌ broker PHẢI buộc đăng ký và đồng ý lại, không gửi
  credential của issuer cũ tới issuer mới.
- R5.5 Cổng MCP PHẢI không bao giờ chuyển token Keycloak của người dùng hay token nền tảng tới máy chủ
  MCP.
- R5.6 KHI đăng ký client với máy chủ cấp quyền, broker PHẢI dùng client tenant đã tự đăng ký trước, rồi
  CIMD khi máy chủ quảng bá `client_id_metadata_document_supported`, rồi đăng ký động sau khi quản trị
  viên xác nhận.

## Trong phạm vi

- Dịch vụ `mcp-gateway` (`apps/mcp_gateway`), mạng `dw-mcp`, `McpGatewayPort` (runtime khai, adapter
  HTTP ở composition root), hợp đồng import-linter cấm `dw_platform`, `dw_agent_runtime` và SQLAlchemy
  trong cổng.
- Bảng, route và sự kiện ở mục Dữ liệu và API; danh mục nền tảng `configs/mcp/catalog/`, ở v1 là nguồn
  duy nhất của máy chủ được đăng ký (DO-46.1); đội nền tảng chọn máy chủ vào danh mục và thẩm định từng mục
  theo một checklist an ninh trước khi mục đó vào (ADR-0116 (Accepted) quyết 8).
- Khóa quyền `studio.mcp.manage`, `studio.mcp.approve`, đăng ký ở ticket W2 đầu tiên dùng chúng (quy ước của
  tenant-rbac/01).
- Factory công cụ `kind: mcp` trong executor của tools-and-skills; lane `mcp_drift`; mục span
  `mcp.server_id`, `mcp.tool_hash`, `mcp.protocol_version`, `mcp.era`, `mcp.result_type`; eval bảo mật
  MCP (mô tả nhiễm độc, chỉ dẫn trong kết quả, thử chéo tenant qua văn bản kết quả, định nghĩa lệch, yêu
  cầu sampling).

## Ngoài phạm vi

| Việc                                                                                                                     | Vì sao                                                                                                                                                                                          | Chủ                                             |
| ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| W2: nguyên mẫu SDK `mcp` 2.x hai đời qua proxy                                                                           | Đo trước khi dựng cổng: client `httpx2` tiêm proxy, chuyển hướng, `$ref`, capabilities, truststore                                                                                              | mcp-client, đợt sau (W2)                        |
| W2: dịch vụ `mcp-gateway` cô lập                                                                                         | R1; lát W1 không dùng MCP                                                                                                                                                                       | mcp-client, đợt sau (W2)                        |
| W2: đăng ký máy chủ, băm định nghĩa, danh mục nền tảng; duyệt hai người                                                  | R2, R3                                                                                                                                                                                          | mcp-client, đợt sau (W2)                        |
| W2: OAuth MCP trên broker; phát hiện lệch; giới hạn, telemetry, eval bảo mật                                             | R4, R5; cần broker OAuth, kho bí mật và egress proxy của connections-and-vault                                                                                                                  | mcp-client, đợt sau (W2); connections-and-vault |
| W3: Yêu cầu bổ sung thông tin vào hộp việc (v1.5, DO-46.2); Tasks extension; resources thành công cụ; client credentials | Cần biểu mẫu việc người dùng của workflow-nodes và OAuth của W2; tới khi đó cổng không khai capability elicitation và lượt chạy không có người thì từ chối; kiểm soát MC14 viết khi cắt đợt này | mcp-client, đợt sau (W3)                        |
| W3: URL máy chủ tùy ý sau quyền lợi gói `mcp_custom_servers` (v1.5)                                                      | DO-46.1: mở khi nguyên mẫu W2 qua một bộ máy chủ thù địch và cổng tách theo công ty                                                                                                             | mcp-client, đợt sau (W3)                        |
| Máy chủ stdio, gói npm hay pypi chạy trên hạ tầng nền tảng                                                               | Chạy lệnh của tenant trên máy nền tảng                                                                                                                                                          | không làm                                       |
| Sampling, roots, logging                                                                                                 | Sampling tiêu ngân sách model của tenant; roots và logging không có bên đọc                                                                                                                     | không làm                                       |
| Máy chủ MCP của nền tảng, A2A, MCP Apps trong chat                                                                       | v2; MCP Apps cần iframe sandbox và CSP riêng                                                                                                                                                    | đợt sau, spec riêng                             |

## Dữ liệu

- `studio.mcp_servers`: `canonical_url` CHECK `https`, host là tên DNS, cổng 443 hay từ 1024 tới 65535,
  không userinfo; `server_alias` unique theo tenant; `auth_mode` CHECK (`none`, `static_header`,
  `oauth_user`, `oauth_shared`); `status` CHECK (`active`, `disabled`); `era`, `protocol_version`,
  `as_issuer`, `egress_origins`, `region`; `catalog_entry_key` NOT NULL ở v1, trỏ một mục của
  `configs/mcp/catalog/` (DO-46.1); RLS tenant.
- `studio.mcp_server_snapshots`, `studio.mcp_tool_definitions`: chỉ thêm, `dw_app` chỉ SELECT và INSERT;
  mỗi định nghĩa mang `pinned_definition_sha256`.
- Công cụ MCP là thành phần loại `tool` trong vỏ phiên bản chung (`studio.artifacts`,
  `studio.artifact_versions`), không cột `status`: phiên bản chạy là Giai đoạn `live`, và ngưng do lệch là
  một dòng `platform.control_switches` có `scope_type` `tool` (ADR-0116 (Accepted) quyết 1;
  ADR-0120 (Accepted) quyết 1, 5). Không bí mật nào trong ba bảng trên.
- Ba bảng trên là bảng toàn tenant (DO-01): không `workspace_id`, mỗi bảng một dòng có lý do trong danh sách bảng
  toàn tenant của test phủ RLS (studio-skeleton:R9.1), thêm trong migration của ticket W2 tạo bảng.

## API

- `/api/v1/studio/mcp-servers`: tạo, xem, sửa, tắt, `discover`, `snapshots`; quyền `studio.mcp.manage`.
- Duyệt công cụ qua hộp phê duyệt của nền tảng, `required_scope` `studio.mcp.approve`, prefix nghiêm
  `studio.mcp.`, sự kiện `studio.mcp.tool_approval.decided`.
- Route OAuth dưới `/api` (ADR-0009 (Accepted)): `GET /api/v1/oauth/mcp-client-metadata.json`,
  `GET /api/v1/oauth/jwks.json`, `GET /api/v1/oauth/callback/mcp`.
- Mã lỗi: `mcp_tool_drifted`, `tool_output_invalid`, `artifact_killed` (công tắc của công cụ đang mở);
  audit `studio.mcp_server.registered`,
  `studio.mcp_server.snapshotted`, `studio.mcp_server.disabled`, `studio.mcp_tool.drift_detected`.

## Kiểm soát

| #    | Kiểm soát                                   | Yêu cầu                | Test âm                                                                                                                                                                                                                |
| ---- | ------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MC1  | Chỉ Streamable HTTP qua HTTPS               | R1.4, R2.2             | Đăng ký `http://`, `file://`, IP literal, URL có userinfo → 422; schema đăng ký không có trường lệnh                                                                                                                   |
| MC2  | Cổng cô lập                                 | R1.1, R1.2             | Từ container `mcp-gateway`: TCP tới `postgres:5432`, `valkey:6379`, `qdrant:6333` thất bại; môi trường không có biến database; request bỏ qua proxy thất bại                                                           |
| MC3  | Chặn SSRF                                   | R1.6                   | URL, metadata tài nguyên hay metadata máy chủ cấp quyền phân giải tới `169.254.169.254`, `10.0.0.0/8`, `100.64.0.0/10`, `::1`, hoặc DNS đổi giữa kiểm và dùng → từ chối                                                |
| MC4  | Ghim băm                                    | R4.2, R4.3, R4.4, R4.9 | Máy chủ đổi mô tả → lời gọi bị từ chối trước `tools/call`, công tắc `tool` mở, audit `studio.mcp_tool.drift_detected`; lời gọi sau đó → `artifact_killed`; duyệt định nghĩa mới → công tắc vẫn mở; gỡ so băm → test đỏ |
| MC5  | Hai người duyệt                             | R3.2, R3.3             | Người đăng ký giữ `approvals.decide` và tem tự duyệt → 409; người không có `studio.mcp.approve` → 404; bỏ `studio.mcp.` khỏi prefix nghiêm → test đỏ                                                                   |
| MC6  | Gợi ý của máy chủ không được tin            | R3.5                   | Công cụ thiếu `annotations` → đề xuất `external` và `always`; `readOnlyHint: true` không tự đặt `none`                                                                                                                 |
| MC7  | Không sampling, roots, logging, elicitation | R1.4, R1.5             | Capabilities gửi đi không có bốn mục đó; máy chủ gửi yêu cầu sampling hay elicitation → từ chối, lượt chạy nhận lỗi có kiểu                                                                                            |
| MC8  | Không chuyển tiếp token                     | R5.5                   | Transport ghi lại: header `Authorization` tới máy chủ MCP không bao giờ là token Keycloak của người dùng                                                                                                               |
| MC9  | OAuth đúng spec                             | R5.1, R5.2, R5.3, R5.4 | AS không quảng bá `S256` → từ chối; `iss` sai → từ chối trước khi đổi mã; credential của issuer cũ không tới AS mới; bỏ `resource` → test đỏ                                                                           |
| MC10 | Đệm theo tenant và người gọi                | R1.9                   | Danh sách `cacheScope: private` của người A không phục vụ người B; khóa đệm thiếu tenant → test đỏ                                                                                                                     |
| MC11 | Đầu ra là dữ liệu ngoài                     | R1.8, R4.6, R4.7       | `structuredContent` sai `outputSchema` → `tool_output_invalid`; `outputSchema` có `$ref` ngoài → không tải, lỗi đóng                                                                                                   |
| MC12 | Đóng băng và tắt chặn mọi request           | R1.11, R4.4            | Máy chủ `disabled` hay nền tảng đóng băng → không request nào rời cổng (proxy ghi lại không thấy gì)                                                                                                                   |
| MC13 | Không theo chuyển hướng khác origin         | R1.7                   | Máy chủ trả 302 sang origin khác → không theo; header khóa API không tới origin đó                                                                                                                                     |
| MC15 | Chỉ người giữ `studio.mcp.manage` đăng ký   | R2.3                   | Người thiếu `studio.mcp.manage` đăng ký hay khám phá → 403, không dòng nào; tenant B đọc máy chủ của tenant A → 404                                                                                                    |
| MC16 | Không gửi ngữ cảnh trace tới máy chủ MCP    | R1.12                  | Transport ghi lại mọi request tới máy chủ MCP, kể cả máy chủ danh mục: không có `traceparent` hay `baggage`; request tới Cổng MCP vẫn có `traceparent`; gỡ bộ lọc header → test đỏ                                     |
| MC17 | Ở v1 chỉ máy chủ trong danh mục nền tảng    | R2.4                   | Đăng ký URL không có mục trong `configs/mcp/catalog/` → 422, không dòng nào; URL của một mục → nhận; gỡ kiểm danh mục → test đỏ                                                                                        |
| MC18 | Máy chủ xử lý ngoài Việt Nam cần Xác nhận   | R2.5                   | Máy chủ có `region` nước ngoài, công ty không có Xác nhận còn hiệu lực cho bên xử lý đó → 422, không dòng nào; có Xác nhận → nhận; Xác nhận hết hạn → 422; gỡ kiểm → test đỏ                                           |

## Tiêu chí xong

- Mọi tiêu chí R có test; MC1-MC13 và MC15-MC18 có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments
  của ticket).
- Image `mcp-gateway` được quét; `reviewing-deployment-security` đã chạy cho route CIMD, JWKS, callback
  và dịch vụ mới; `make ci && make test-integration` xanh.

## Phụ thuộc

- tools-and-skills: thành phần `tool` với phiên bản ghim, executor phân giải theo tenant, kiểm schema của
  chính executor, một hàm `approval_required`, mức sàn theo loại và Bản mô hình nhìn thấy (ADR-0116 (Accepted)
  quyết 1-5).
- connections-and-vault: kho bí mật cấp credential ngắn hạn mỗi lời gọi, broker OAuth có hồ sơ MCP,
  egress proxy và mạng của nó (ADR-0115 (Accepted)); foundations-hardening/05: một chính sách địa chỉ từ
  chối `not is_global`.
- agent-lifecycle: máy giai đoạn với luật theo loại cho loại không có Cổng chất lượng (`awaiting_approval`
  chỉ cần người thứ hai, không `gate_run_id`), công tắc `scope_type` `tool` và Bật lại hai người
  (agent-lifecycle:R8.6, agent-lifecycle:R8.7), lệch cấu hình loại `mcp_tool_drifted` và công tắc đóng băng
  ở mọi cửa (ADR-0120 (Accepted)); usage-and-limits: `RateLimiterPort` và giới hạn chạy đồng thời theo
  `(tenant, server)`; telemetry-and-audit: thuộc tính span; compliance-pdpl: lớp tuyến cư trú và Xác nhận
  chuyển dữ liệu ra nước ngoài (ADR-0123 (Accepted)).
- Protocol do bên dùng khai: `McpGatewayPort` (runtime khai, adapter HTTP đáp ứng ở composition root).
- Kiểm lại khi: checklist an ninh của danh mục hay người thẩm định đổi → R2.4, `configs/mcp/catalog/`;
  kết quả FOG-25, FOG-26 đổi egress
  proxy hay kho bí mật → R1.2, R1.3, R5; luật sư đổi kết luận DO-54.2 → R2.5; một advisory mới của SDK
  `mcp` hay bản ghim đổi → R1; tools-and-skills đổi `dw.tool/v1` hay `approval_required` → R3, R4;
  agent-lifecycle đổi luật theo loại hay Bật lại → R3.4, R4.9.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (người yêu cầu): D11 (DO-07): người duyệt định nghĩa công cụ MCP khác người đăng ký máy chủ.
  Sửa: R3.2, R3.3.
- 23/10/2026 (người yêu cầu): D14 (DO-24): máy chủ chính lên ít nhất 4 vCPU / 16 GB trước khi OpenBao và
  egress proxy chạy, đo trước khi cố định kích thước; Cổng MCP là một dịch vụ thêm trên máy đó. Sửa: R1.
- 23/10/2026 (agent, tạm): không cắt ticket W1, vì lát Marketing của W1 không dùng MCP; ticket cắt khi
  W2 bắt đầu. Nếu sai thì: cắt ngay ticket nguyên mẫu SDK, vì nó chạy được độc lập.
- 23/10/2026 (Đạt): DO-46.1 theo (b): v1 chỉ máy chủ trong danh mục nền tảng, vẫn ghim băm và hai người
  duyệt; URL tùy ý ở v1.5 sau quyền lợi `mcp_custom_servers`, khi nguyên mẫu W2 qua bộ máy chủ thù địch
  và cổng tách theo công ty; ai chọn máy chủ vào danh mục còn nợ (Q5). Hỏi: Q1. Sửa: R2.4, Trong phạm vi,
  Dữ liệu, Ngoài phạm vi, MC17.
- 23/10/2026 (Đạt): DO-46.2 theo (a): Yêu cầu bổ sung thông tin ở v1.5; cổng không khai capability
  elicitation, lượt chạy không có người thì từ chối. Hỏi: Q2. Sửa: R1.4, R1.5, MC7, Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-46.3 theo (b): `traceparent` tới Cổng MCP (chặng nội bộ) nhưng không bao giờ tới
  máy chủ MCP nào, không bao giờ `baggage`. Hỏi: Q3. Sửa: R1.12, MC16.
- 23/10/2026 (Đạt): DO-54.2 theo (a): nền tảng là bên xử lý, công ty là bên kiểm soát; công cụ, máy chủ MCP
  và kết nối ở nước ngoài cần Xác nhận chuyển dữ liệu ra nước ngoài (ADR-0123 (Accepted) quyết 5); luật sư
  quyết ai nộp DPIA và CTIA. Hỏi: Q4. Sửa: R2.5, MC18, Phụ thuộc.
- 23/10/2026 (Đạt): công cụ MCP đi qua máy giai đoạn theo (a): dịch vụ phát hành của loại `tool` ghi
  `live` sau duyệt, không `gate_run_id`; ngưng do lệch là công tắc `scope_type` `tool`; bỏ cột `status`.
  Sửa: R3.1, R3.4, R4.3, R4.4, R4.9, Dữ liệu, API, MC4, Phụ thuộc.
- 23/10/2026 (Đạt): bảng mã từ chối người quyết, ghi một lần ở ADR-0104 (Accepted) quyết 11: ngoài tầm thấy 404;
  mọi luật tách nhiệm 409; thấy được mà thiếu `approvals.decide` hay tem, hoặc không được giao, 403. Sửa:
  R3.2 (409 khi người đăng ký giữ tem), MC5.
- 23/10/2026 (agent, tạm): sau lệch, công cụ chạy lại qua hai phê duyệt nối tiếp: trước hết người thứ hai
  duyệt định nghĩa mới (`studio.mcp.tool_approval`) và phiên bản mới lên `live` trong khi công tắc vẫn mở
  (R4.9); sau đó một yêu cầu Bật lại do người khác người xin quyết gỡ công tắc (agent-lifecycle:R8.6). Bật
  lại trước khi định nghĩa mới được duyệt thì lời gọi kế tiếp lại bị R4.2 từ chối và công tắc mở lại. Sửa:
  R4.9. Nếu sai thì: lần duyệt định nghĩa mới gỡ luôn công tắc, R4.9 đổi theo.
- 23/10/2026 (Đạt): DO-01 theo (a): bảng không có `workspace_id` là bảng toàn tenant, ghi lý do trong danh sách của
  test phủ RLS. Sửa: Dữ liệu (ba bảng MCP).
- 24/10/2026 (Đạt): DO-46.1: đội nền tảng chọn máy chủ vào `configs/mcp/catalog/` và thẩm định từng mục theo
  một checklist an ninh trước khi mục đó vào (ADR-0116 (Accepted) quyết 8). Hỏi: Q5. Sửa: Trong phạm vi, Phụ
  thuộc, Câu hỏi còn mở.
- 24/10/2026 (Đạt): bảng mã từ chối người quyết nằm ở ADR-0104 (Accepted) quyết 11, không ở ADR-0004 (Accepted)
  vốn không có bảng đó; dòng ngày 23/10/2026 về bảng mã ở trên đổi chỗ dẫn, nội dung giữ nguyên. Sửa:
  Quyết định.

## Danh sách ticket

Chưa có ticket: ticket được cắt khi đợt W2 bắt đầu.
