# Agent là dữ liệu của tenant: định nghĩa, chỉ dẫn, runtime, chat

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Một quản trị Marketing cần tạo trợ lý bằng biểu mẫu (chỉ dẫn, hồ sơ model trong gói, bộ công cụ ghim theo phiên bản, `Người được dùng`), chạy trong runner hiện có theo (công ty, phiên bản) với quyền của người kích hoạt, rồi nhân viên trong `Người được dùng` hỏi về lead qua chat và chỉ nhận dữ liệu mình được đọc, có trích dẫn. W1 làm trợ lý chỉ đọc chạy ở worker và chat qua polling; màn dựng agent, trích dẫn, "Hỏi trước", agent liên kết và truyền phát là W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Không context nghiệp vụ nào được ship và `build_agent` chưa có caller sản xuất; hai seam cắm context còn trống (`apps/api/src/dw_api/bootstrap/wiring.py:332`). Thiếu: chưa có nơi nào dựng hay chạy agent của tenant.
- `build_agent` dựng trên `create_agent`, không phải `create_deep_agent`, nên nền tảng chỉ cài công cụ nó kiểm soát (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:28-36`). Ràng buộc: runtime Studio giữ nguyên nền `create_agent`, không lấy builtin của deepagents.
- `GraphRegistry` khóa theo `(worker_id, graph_version)` không có công ty, và runner cache graph đã biên dịch mà không bao giờ dọn (`packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-30`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`). Thiếu: khóa biên dịch chưa có công ty và cache chưa có trần.
- `RunContext` mang công ty, workspace, actor và số phiên bản worker, nhưng không có tham chiếu thành phần, chế độ chạy hay model (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:98`). Thiếu: chưa có `RunContext.artifact`.
- `PromptRegistry.render` bọc mỗi giá trị bằng `contain_untrusted` trừ khi nằm trong `raw_variables`, rồi mới `str.format`, và `has()` chỉ xét lớp nền tảng (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`). Ràng buộc: văn bản tenant không bao giờ tới `str.format`; bộ ráp của Studio theo đúng cơ chế này.
- API lượt chạy chỉ có đọc và hủy; không route nào truyền phát chat (`apps/api/src/dw_api/routes/v1/runs.py:41`). Thiếu: chưa có hội thoại và màn chat.
- Có tiền lệ RLS theo người: `platform.notifications` siết theo `app.user_id`, do `tenant_session` gắn từ ngữ cảnh truy cập đã xác thực (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:46`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:26`). Ràng buộc: hội thoại riêng dùng lại hình policy RESTRICTIVE này.

## Mục tiêu

### R1 — Agent là tài liệu `dw.agent/v1` cấu hình bằng biểu mẫu

Người dựng tạo agent gồm chỉ dẫn, hồ sơ model trong gói, bộ công cụ ghim theo phiên bản và `Người được dùng`, không viết mã (YC54, ADR-0117 (Proposed)).

- R1.1 KHI người giữ `studio.agent.author` gửi `POST /api/v1/studio/agents` hợp lệ, API Studio agent PHẢI tạo một tài liệu kind `agent` trong vỏ phiên bản và một dòng `studio.agent_settings` kèm audit `studio.agent.created`.
- R1.2 NẾU người giữ `studio.agent.author` sửa nháp với `row_version` không còn mới, THÌ API Studio agent PHẢI trả 409 và không ghi.
- R1.3 NẾU tài liệu agent mang một khóa ngoài lược đồ `dw.agent/v1`, THÌ validator PHẢI trả 422 kèm `{path, code, message}` và không tạo phiên bản.
- R1.4 NẾU một dòng `studio.agent_settings` được thêm mà thiếu `enabled`, THÌ PostgreSQL PHẢI từ chối và không ghi.
- R1.5 NẾU `Người được dùng` của agent rỗng lúc tạo, THÌ API Studio agent PHẢI trả 422 và không tạo.

### R2 — Khung prompt nền tảng; chỉ dẫn tenant không bao giờ là template

Chỉ dẫn là một khối văn bản có lint trong khung `studio.agent_frame@1.0.0`; biến hệ thống là một tập đóng; mọi giá trị chèn là dữ liệu từ bên ngoài (YC48, ADR-0117 (Proposed)).

- R2.1 Bộ ráp prompt PHẢI đưa chỉ dẫn và mọi giá trị chèn tới model nguyên văn trong một khối dữ liệu ngoài, cắt ở 16 KiB mỗi giá trị.
- R2.2 NẾU chỉ dẫn chứa một chuỗi đóng khối dữ liệu ngoài của khung, THÌ bộ ráp prompt PHẢI trả 422 và không dựng prompt.
- R2.3 NẾU prompt tham chiếu một biến ngoài tập biến hệ thống đóng, THÌ bộ ráp prompt PHẢI trả 422 và không dựng prompt.

### R3 — Runtime theo (công ty, phiên bản): cache có trần, kiểm mã băm, actor trong giới hạn dữ liệu

Graph dựng từ phiên bản ghim trong runner hiện có; agent chạy với quyền người kích hoạt giao với giới hạn dữ liệu của phiên bản; mọi lời gọi model chịu trần của lượt (YC19, YC78, YC85, ADR-0103 (Proposed), ADR-0117 (Proposed)).

- R3.1 KHI runtime nạp một phiên bản agent, runtime PHẢI dựng graph theo khóa `(tenant_id, agent_version_id)` trong một cache LRU có trần.
- R3.2 KHI hai công ty dùng cùng `api_name` và cùng số phiên bản, runtime PHẢI giữ hai mục cache tách biệt.
- R3.3 NẾU `document` của một phiên bản đã niêm phong lệch mã băm định nghĩa lúc nạp, THÌ runtime PHẢI từ chối biên dịch và không chạy.
- R3.4 KHI runtime mở phiên công cụ cho một lượt chạy agent, phiên công cụ PHẢI chạy với quyền của người kích hoạt giao với giới hạn dữ liệu của phiên bản đã phát hành.
- R3.5 KHI một lượt chạy agent gọi model, runtime PHẢI dùng đúng route model đã ghim trong bản kê lượt chạy của lượt.
- R3.6 Mọi lời gọi model của một lượt chạy agent PHẢI chịu trần chi phí và giới hạn hành vi hữu hạn của lượt đó.

### R4 — Hội thoại riêng của chủ, một lượt chạy mỗi lượt

Hội thoại và tin nhắn chỉ chủ đọc; mỗi lượt hội thoại sinh đúng một lượt chạy ở worker, trả kết quả qua polling (YC55, ADR-0117 (Proposed)).

- R4.1 `studio.conversations` và `studio.conversation_messages` PHẢI chỉ cho chủ hội thoại đọc, bằng policy RLS RESTRICTIVE theo `app.user_id` cạnh hình workspace.
- R4.2 NẾU một người mở hội thoại của người khác cùng công ty, THÌ API chat PHẢI trả 404 như với hội thoại không tồn tại.
- R4.3 NẾU hai `POST /api/v1/studio/agents/{id}/conversations/{conversation_id}/messages` tới cùng một hội thoại chạy song song, THÌ API chat PHẢI nhận đúng một lượt chạy với 202 và trả 409 cho lượt còn lại.
- R4.4 `worker_runs.input` của một lượt chạy chat PHẢI chỉ chứa id, không chứa nội dung tin nhắn.
- R4.5 KHI một lượt chạy chat hoàn tất ở worker, API chat PHẢI trả tin nhắn trợ lý mới cho lần `GET` tiếp theo của chủ hội thoại.

### R5 — `Người được dùng` quyết ai mở agent, mặc định đóng

Audience chỉ chặn cửa mở agent, không quyết agent đọc được gì; không khớp là không tồn tại, không bao giờ fail-open (YC55).

- R5.1 KHI một người liệt kê agent, API chat PHẢI chỉ trả agent mà `Người được dùng` của phiên bản đang dùng khớp người đó.
- R5.2 NẾU một người ngoài `Người được dùng` gọi một agent, THÌ API chat PHẢI trả 404 như với agent không tồn tại.

## Trong phạm vi

- Loại thành phần `agent` (`dw.agent/v1`): validator `extra="forbid"` với số thập phân dạng chuỗi, extractor phụ thuộc, đăng ký trong `ArtifactKindRegistry` của `tenant-config`.
- Bảng `studio.agent_settings` (audience, người chịu trách nhiệm, `enabled`).
- Bảng `studio.conversations` và `studio.conversation_messages` (RLS RESTRICTIVE theo chủ).
- Khóa quyền `studio.agent.read`, `studio.agent.author`, `studio.agent.settings.manage`.
- Khung `studio.agent_frame@1.0.0` trong `configs/prompts/studio/` và bộ ráp prompt cạnh `contain_untrusted`.
- Runtime theo (công ty, phiên bản) trong runner: nguồn graph, cache LRU, middleware đóng băng và hạn mức, `RunContext.artifact`, cổng mã băm, actor `agent`.
- Route `/api/v1/studio/agents` và route chat; cửa nhận run `trigger_kind=chat`; polling.
- Màn `/chat` antd (danh sách agent theo audience, hội thoại, tin nhắn, nhãn AI cố định, lời chào và tối đa sáu gợi ý).

## Ngoài phạm vi

| Việc                                                                    | Vì sao                                                        | Chủ                           |
| ----------------------------------------------------------------------- | ------------------------------------------------------------- | ----------------------------- |
| Trích dẫn và phản hồi (link bản ghi, gỡ dấu ngoài bằng chứng, feedback) | Dựng sau runtime và công cụ đối tượng ghi bằng chứng          | đợt sau (W2)                  |
| "Hỏi trước", giới hạn kẹp gói, kiểm khi publish                         | Phụ thuộc cổng publish và phân tích năng lực                  | đợt sau (W2)                  |
| Màn dựng agent `/studio/agents`                                         | Dựng sau loại agent và kiểm khi publish                       | đợt sau (W2)                  |
| Agent liên kết, agent con, nguồn tri thức, `AgentInvocationPort`        | Cần chờ `child_run` và node quy trình                         | đợt sau (W2)                  |
| Truyền phát SSE; "Chạy quy trình ..." trong chat                        | Polling đủ cho W1; quy trình như công cụ ở `tools-and-skills` | đợt sau (W2)                  |
| Bộ nhớ ("Brain"), A2A, chat với khách hàng qua kênh công khai           | Ngoài v1                                                      | đợt sau (W3)                  |
| Trạng thái phiên bản, cổng đánh giá, duyệt publish, kill, freeze        | Vòng đời thành phần                                           | agent-lifecycle               |
| Loại công cụ, `dw.toolset/v1`, executor, quy trình như công cụ          | Công cụ là dữ liệu tenant qua một executor                    | tools-and-skills              |
| `platform.audience_matches`, thuộc tính thành viên, chủ sở hữu          | Danh tính và audience                                         | org-and-principals            |
| Bảng giới hạn dữ liệu, chặn trường                                      | Quyền trên bản ghi và trường                                  | record-access, field-security |
| Phân giải model theo công ty, BYOM                                      | Bộ phân giải model                                            | model-connections             |
| Hàng đợi run, chờ `child_run`, saver, `RunRequestService`               | Động cơ lượt chạy                                             | workflow-engine               |
| Sổ usage, lease, `platform.plan_limits`                                 | Hạn mức và đo                                                 | usage-and-limits              |
| Phân tích bộ ba nguy hiểm, lớp tuyến dữ liệu, công bố AI                | Tuân thủ PDPL                                                 | compliance-pdpl               |

## Dữ liệu

- `studio.agent_settings`: `tenant_id`, `workspace_id`, `agent_id`, `audience` (jsonb `dw.audience/v1`), `accountable_user_id` (guard người chịu trách nhiệm), `enabled boolean NOT NULL` (không mặc định), `row_version`, `created_at/updated_at timestamptz` (trigger `updated_at`). RLS bật và FORCE, policy siết theo `tenant_id` và hình workspace. FK `ON DELETE` tường minh và chỉ mục trên phía của nó. Tên ràng buộc theo `NAMING_CONVENTION`.
- `studio.conversations`: `tenant_id`, `workspace_id`, `owner_user_id NOT NULL`, `agent_id`, `agent_version_id`, `active_run_id` (unique cục bộ để chiếm chỗ một lượt), `created_at timestamptz`. Chỉ mục phân trang dẫn đầu bằng `(tenant_id, owner_user_id, created_at DESC)`.
- `studio.conversation_messages`: `tenant_id`, `conversation_id`, `role`, `content`, `run_id`, `created_at timestamptz`. Append-only.
- Hai bảng hội thoại mang thêm policy RLS RESTRICTIVE siết `owner_user_id = current_setting('app.user_id')`, cạnh policy permissive của hình workspace, theo tiền lệ `platform.notifications`.

## API

- `POST /api/v1/studio/agents` (`studio.agent.author`): tạo agent, 422 `{path, code, message}` cho trường sai, 422 `reason_code=audience_empty` khi `Người được dùng` rỗng.
- `GET /api/v1/studio/agents` (`studio.agent.read`): chỉ agent mà audience của người gọi khớp.
- `PATCH /api/v1/studio/agents/{id}` (`studio.agent.author`): sửa nháp, 409 `reason_code=stale_row_version`.
- `PATCH /api/v1/studio/agents/{id}/settings` (`studio.agent.settings.manage`): audit `studio.agent.settings_changed`.
- `POST /api/v1/studio/agents/{id}/conversations` và `.../conversations/{conversation_id}/messages`: 404 khi ngoài audience hoặc không phải chủ; 202 nhận lượt, 409 `reason_code=conversation_busy` khi đang chạy.
- `GET /api/v1/studio/agents/{id}/conversations/{conversation_id}/messages`: polling tin nhắn của chủ.

## Màn hình

- `/chat` (antd, `vi_VN`): danh sách agent lọc theo `Người được dùng`; danh sách hội thoại của chính người dùng; khung tin nhắn cập nhật qua polling; nhãn "đang tương tác với AI" cố định; lời chào và tối đa sáu gợi ý. Người ngoài audience không thấy agent. Kiểm Playwright ở 320 px.

## Kiểm soát

| #    | Kiểm soát                                           | Yêu cầu          | Test âm                                                                                                                        |
| ---- | --------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| AB1  | Văn bản tenant không dùng làm khuôn định dạng       | R2.1, R2.3       | chỉ dẫn `{x.__class__.__mro__}` tới model nguyên văn, JSON `{"a": 1}` nguyên văn; biến ngoài tập → 422; gỡ kiểm biến → test đỏ |
| AB2  | Chỉ dẫn không thoát được khối dữ liệu ngoài         | R2.2             | chỉ dẫn chứa chuỗi đóng khối của khung → 422; gỡ thoát ký tự → test đỏ                                                         |
| AB3  | `Người được dùng` kiểm ở mọi cửa gọi, mặc định đóng | R5.1, R5.2       | người ngoài audience: không thấy trong `GET /api/v1/studio/agents`, mở hội thoại → 404; gỡ kiểm audience → thấy agent          |
| AB4  | Hội thoại riêng của chủ                             | R4.1, R4.2       | người B đọc hội thoại của A → 404; câu SQL thiếu `app.user_id` → 0 dòng; gỡ policy RESTRICTIVE → test đỏ                       |
| AB5  | Agent không vượt quyền người kích hoạt              | R3.4             | lead người hỏi không đọc được không có trong câu trả lời; thiếu actor context → 0 bản ghi; gỡ gán actor → test đỏ              |
| AB6  | Cache biên dịch theo (công ty, phiên bản)           | R3.1, R3.2       | hai công ty cùng `api_name` và số phiên bản → hai mục cache; gỡ `tenant_id` khỏi khóa → test đỏ                                |
| AB7  | Mã băm định nghĩa kiểm khi nạp                      | R3.3             | sửa `document` bằng role migrator → biên dịch từ chối; gỡ kiểm băm → test đỏ                                                   |
| AB8  | Một lượt chạy mỗi lượt hội thoại                    | R4.3             | hai `POST .../messages` song song → một 202, một 409; gỡ chiếm `active_run_id` → hai lượt chạy                                 |
| AB9  | Chọn model trước ngân sách; mọi lời gọi chịu trần   | R3.6             | đảo thứ tự bước chọn model và bước ngân sách → test chi phí đỏ                                                                 |
| AB10 | Mặc định đóng cho cài đặt agent                     | R1.3, R1.4, R1.5 | INSERT thiếu `enabled` → từ chối; khóa lạ → 422; `Người được dùng` rỗng → 422; gỡ `NOT NULL` → test đỏ                         |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát AB1–AB10 có test âm đã thấy đỏ khi gỡ guard.
- `make ci` xanh, gồm test RLS hội thoại theo người, hai test hợp đồng thư viện (langchain, deepagents) và Playwright `/chat` ở 320 px.

## Phụ thuộc

- `tenant-config`: vỏ phiên bản và `ArtifactKindRegistry` cho kind `agent`; bản kê lượt chạy ghim route model (`tenant-config:R6.1`); phân giải phiên bản cấu hình. Ticket `.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`.
- `record-access`: ngữ cảnh actor `agent` và giới hạn dữ liệu ở mọi cửa (`record-access:R6.3`, `record-access:R6.4`, `record-access:R6.5`). Ticket `.claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md`.
- `custom-objects`: mọi đọc và ghi bản ghi qua RecordService, công cụ đối tượng trả id (`custom-objects:R5.6`, `custom-objects:R5.7`).
- `model-connections`: một `ModelResolver` theo công ty ghim route vào bản kê (`model-connections:R1.4`); hồ sơ model trong gói (`model-connections:R2.2`).
- `org-and-principals`: `platform.audience_matches`, thuộc tính thành viên; lượt chạy không người kích hoạt chạy dưới tài khoản dịch vụ (`org-and-principals:R6.7`).
- `tenant-rbac`: đăng ký khóa `studio.agent.read`, `studio.agent.author`, `studio.agent.settings.manage` vào danh mục quyền.
- Seam nền tảng do bên khác dựng, tham chiếu bằng slug và đường dẫn: `workflow-engine` (`RunRequestService` nhận `trigger_kind=chat`, saver, chờ `child_run`); `agent-lifecycle` (hợp đồng stage, `RunControlMiddleware`); `tools-and-skills` (executor, `dw.toolset/v1`, prefix `studio.agent.tool.`); `compliance-pdpl` (lớp tuyến dữ liệu, bộ ba nguy hiểm).
- Kiểm lại khi: O1/DO-05 chốt nơi phiên bản sống → R1, R3, ticket 02; DO-40 chốt dạng audience → R5; DO-44 chốt vị trí chạy chat và truyền phát → R4, ticket 04; hợp đồng stage của `agent-lifecycle` đổi → R3.

## Câu hỏi còn mở

- Q1. DO-05: Phiên bản agent sống trong vỏ chung `studio.artifact_versions` hay bảng theo loại, và ai làm chủ "phiên bản nào chạy"? Chủ: Đạt. Chặn: 02, R1.
- Q2. DO-44: Chạy chat ở worker với polling có đủ cho người dùng thử ở P1, hay cần truyền phát SSE ngay ở W1? Chủ: Đạt với counsel. Chặn: 04, R4.

## Quyết định

- 23/10/2026 (Đạt): chat chạy ở worker qua `RunRequestService` với polling ở P1 (O4); không vai nào đọc hội thoại của người khác ở v1 (O5). Hỏi: Q2. Sửa: R4, R5.
- 23/10/2026 (agent, tạm): `Người được dùng` mặc định đóng — audience rỗng bị từ chối lúc tạo, không khớp trả 404, không fail-open. Nguồn: phân tích đối thủ `.claude/plans/studio/discovery/config-chang.md` (mẫu học từ bộ chọn audience YC54, không phải mã của họ) và `failure-modes.md` #7. Sửa: R1.5, R5.2. Nếu sai thì: nếu Đạt muốn audience rỗng nghĩa là mọi người, đổi R1.5 và R5.
- 23/10/2026 (agent, tạm): phiên bản agent node và agent liên kết ghim lúc gửi kiểm định, không "theo bản đang dùng" (DO-30). Sửa: R3. Nếu sai thì: nếu "theo bản đang dùng", bỏ ghim phiên bản con khỏi bản kê.

## Danh sách ticket

| #   | Ticket                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------ |
| 01  | [Nguyên mẫu: agent Studio chạy trong runner theo (công ty, phiên bản)](issues/01-nguyen-mau-agent-studio.md) |
| 02  | [Loại `agent`, cài đặt agent, khung và bộ ráp prompt](issues/02-loai-agent-va-khung-prompt.md)               |
| 03  | [Runtime agent: nguồn graph, cache, middleware, actor](issues/03-runtime-agent.md)                           |
| 04  | [Chat: hội thoại, tin nhắn, cửa nhận run, polling và màn chat](issues/04-chat-va-man-chat.md)                |
