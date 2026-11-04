# Bộ phân giải model theo công ty, BYOM qua model proxy

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: agent, tạm theo ủy quyền 2/11/2026
Sẵn sàng: ĐẠT (5/11/2026; 0 CRITICAL, 0 HIGH; ticket 01-03)

Mọi cửa model của Studio cần một bộ phân giải theo công ty để chọn đúng hồ sơ model mà gói cho phép, ghim vào bản kê lượt chạy và đi theo lộ trình dữ liệu chặt nhất, thay cho ba chỗ đọc hồ sơ lệch nhau hôm nay; và công ty cần kết nối model của chính mình qua model proxy LiteLLM không trạng thái. W1 làm `ModelResolver` và hồ sơ nền tảng lọc theo gói cho bước AI và trợ lý, cùng một spike đo model proxy trước khi dựng; kết nối model đầy đủ (BYOM) là W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `ChatModelFactory.resolve(profile_id)` không nhận công ty, và `OpenAICompatibleChatModelFactory` dựng một client trên URL và khóa của deployment (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/chat_model.py:33`). Thiếu: chưa phân giải model theo công ty.
- Ba chỗ đọc hồ sơ lệch nhau: `RunBudgetMiddleware` phân giải có công ty, còn `LangchainUsageMeter._record` phân giải không công ty (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py:62`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:138`). Ràng buộc: cần một bộ phân giải cho mọi cửa.
- Adapter nhà cung cấp dựng một lần mỗi tiến trình từ một khóa và một URL, mock bị từ chối ở profile triển khai (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/model_stack.py:92`). Thiếu: không có khóa theo công ty ở đâu cả.
- `ModelProfile` mang giá số thực dấu phẩy động và `schema_version` cố định `"1.0"`, không có cờ năng lực hay trường nơi xử lý dữ liệu; `resolve(profile_id, *, tenant_id=None)` có sẵn nhưng không mã sản xuất nào nạp lớp công ty (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:113`, `apps/api/src/dw_api/bootstrap/runtime.py:117`). Thiếu: thiếu phiên bản v2, cờ năng lực và trường tuyến dữ liệu.
- Breaker ghi một lỗi cho mọi `httpx.HTTPError` kể cả 4xx, mở sau 5 lỗi liên tục trong 30 giây, một breaker mỗi tiến trình (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:76`, `packages/python/dw_kernel/src/dw_kernel/resilience.py:39`). Ràng buộc: breaker phải theo kết nối và 4xx không mở breaker.
- Guard chi tiêu ngày bỏ qua mọi lời gọi có chi phí bằng hoặc dưới 0 (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/spend_guard.py:79`). Ràng buộc: route chưa định giá không được coi là miễn phí.
- `configs/models/gateway.yaml` định tuyến mọi lời gọi qua một gateway OpenAI-compatible, và `.env.example` nêu FPT AI Gateway mà dự án đang chạy trên đó (`configs/models/gateway.yaml:4`, `.env.example:171`). Ràng buộc: gateway nền tảng giữ model của nền tảng; model của công ty cần một lane riêng.

## Mục tiêu

### R1 — Một `ModelResolver` theo công ty trả lời mọi cửa model

Mọi cửa model đọc một bộ phân giải theo công ty, trả cùng một route và ghim nó vào bản kê, không bao giờ phân giải sang công ty khác (YC32, YC85, ADR-0118 (Accepted)).

- R1.1 `ModelResolver` PHẢI là nguồn route model duy nhất cho mọi cửa model của một lượt chạy (ngân sách lượt chạy, đo usage, gateway có cấu trúc, nén ngữ cảnh; chọn model và giám khảo khi hai cửa đó ra đời), và lấy công ty, gói và workspace từ `RunContext` của lượt, không bao giờ từ request.
- R1.2 KHI hai cửa model khác nhau phân giải cho một công ty có hồ sơ riêng, `ModelResolver` PHẢI trả cùng một route cho cả hai.
- R1.3 NẾU một công ty hỏi một hồ sơ mà chỉ công ty khác có bản riêng, THÌ `ModelResolver` PHẢI rơi về hồ sơ nền tảng và không bao giờ trả bản của công ty khác.
- R1.4 KHI một lượt chạy có gốc là thành phần Studio được nhận, `ModelResolver` PHẢI ghim mỗi hồ sơ model mà lượt được dùng, theo giá trị và với mọi route của hồ sơ kể cả route dự phòng, vào mục `engine` của bản kê lượt chạy, không kèm phiên bản bí mật nào (ADR-0118 (Accepted) quyết 1; ADR-0109 (Accepted) quyết 8; V4.35).
- R1.5 TRONG KHI một lượt chạy Studio gọi model, NẾU hồ sơ mà lời gọi hỏi không có trong bản kê, hay nội dung hiện hành của hồ sơ đã ghim khác nội dung đã ghim, hay gói của công ty không còn cho phép một hồ sơ nền tảng đã ghim, THÌ `ModelResolver` PHẢI từ chối lời gọi trước khi gửi, kết thúc lượt `failed` với `model_profile_unavailable`, và không phân giải sang route hiện hành.
- R1.6 NẾU một cửa model hỏi `ModelResolver` mà không có `RunContext` của một lượt chạy, THÌ `ModelResolver` PHẢI từ chối; bước ghim lúc nhận lượt (R1.4) đưa công ty và gói từ ngữ cảnh đã xác minh mà cửa nhận lượt giữ, và lớp nền tảng chưa lọc theo gói chỉ đọc được qua một hàm riêng mà composition root và script gọi.

### R2 — Hồ sơ model trong danh sách gói cho phép, `ModelProfile` v2

Bộ phân giải chỉ trả hồ sơ mà gói cho phép; hồ sơ mang phiên bản và cờ năng lực, còn giá do Bảng giá của usage-and-limits giữ (YC85, ADR-0118 (Accepted)).

- R2.1 `ModelResolver` PHẢI chỉ trả hồ sơ nền tảng mà gói của công ty cho phép, đọc từ `platform.plan_model_profiles`; hồ sơ của lớp công ty không qua lọc gói (ADR-0118 (Accepted) quyết 1).
- R2.2 NẾU một lượt chạy xin một hồ sơ model ngoài danh sách gói, hay gói của công ty không có dòng nào trong `platform.plan_model_profiles`, THÌ `ModelResolver` PHẢI từ chối với `model_profile_unavailable` và không gọi model.
- R2.3 `ModelProfile` v2 PHẢI mang số phiên bản, cờ năng lực `strict_tools` và `numeric_bounds`, và trường `data_location` và `processor`.
- R2.4 [Bỏ] 23/10/2026: giá chỉ có một chủ là Bảng giá (usage-and-limits:R2.1); `ModelProfile` v2 không mang giá, chỉ dẫn chiếu mục của Bảng giá (DO-21.5).
- R2.5 KHI `make check-model` chạy, lệnh `make check-model` PHẢI thăm dò mỗi route không phải mock của hồ sơ mà deployment chọn (hay hồ sơ nêu bằng `PROFILE=`) và báo lỗi khi một cờ năng lực khai khác kết quả thăm dò.
- R2.6 NẾU `ModelResolver` không đọc được danh sách hồ sơ của gói, THÌ `ModelResolver` PHẢI từ chối như R2.2 và không bao giờ coi mọi hồ sơ nền tảng là được phép.

### R3 — Trường tuyến dữ liệu, mặc định coi là nước ngoài

Hồ sơ model khai nơi xử lý dữ liệu; thiếu khai là nước ngoài, không fail-open (YC85, ADR-0123 (Accepted)).

- R3.1 NẾU một route của tệp YAML hồ sơ model nền tảng thiếu `data_location` hay `processor`, hay khai `data_location` khác `vn` và `foreign`, THÌ bộ nạp hồ sơ model PHẢI từ chối nạp và báo lỗi.
- R3.2 Hồ sơ model PHẢI coi `data_location` không khai là nước ngoài: `ModelRoute` không có giá trị mặc định cho `data_location`, và một route trên gateway nền tảng mà FOG-18 chưa định vị khai `foreign`, không bao giờ `vn`.

## Trong phạm vi

- `ModelResolver`: một cổng cho cửa ngân sách lượt chạy (`RunBudgetMiddleware` hôm nay, rồi `LimitsMiddleware` thay nó ở usage-and-limits/03 và đọc cùng bộ phân giải, ADR-0118 (Accepted) quyết 1), `LangchainUsageMeter`, `RoutingModelGateway` và nén ngữ cảnh; `StudioModelSelection` (agent-builder/03) và bộ chấm LLM đầu tiên của `dw_evals` nhận nó qua constructor khi ra đời. Đọc lớp công ty (W1: chỉ lớp trong bộ nhớ của `ModelProfileRegistry`, không mã sản xuất nào nạp; nguồn thật là phiên bản cấu hình của `tenant-config` ở W2), rồi lớp nền tảng lọc theo gói; hồ sơ `None` là hồ sơ mặc định của deployment, cũng lọc theo gói.
- `ModelProfile` v2: số phiên bản, cờ năng lực (`strict_tools`, `max_strict_tools`, `numeric_bounds`), trường `data_location`, `processor`, `retention_days`, `no_training` (không mặc định). Spec này là chủ duy nhất của các trường tuyến dữ liệu và luật "không khai là nước ngoài" (R3); compliance-pdpl chỉ đọc. Hồ sơ không mang giá: giá ở Bảng giá (DO-21.5); ticket 02 bỏ `price_per_million_input`, `price_per_million_output` khỏi `ModelRoute` và `configs/models/*.yaml` sau khi `route_cost` thôi đọc chúng ở usage-and-limits/02 (H-4), và chuyển `temperature`, `max_cost_usd_per_run` sang `Decimal` (ADR-0109 (Accepted) Consequences).
- `ResolvedRoute` không mang `secret_version`: route ghim trong bản kê, khóa của kết nối model là phiên bản mới nhất chưa thu hồi lúc gọi (V4.35).
- Bảng `platform.plan_model_profiles` (gói của công ty tới hồ sơ cho phép).
- `make check-model` thăm dò và so cờ năng lực khai với kết quả thăm dò.

## Ngoài phạm vi

| Việc                                                                                                                       | Vì sao                                                                                                                                  | Chủ                                               |
| -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Bảng `platform.model_connections`, API quản trị, quyền lợi `byom`                                                          | YC58; kết nối model đầy đủ dựng sau bộ phân giải                                                                                        | model-connections đợt sau (W2)                    |
| Dịch vụ compose `model-proxy` (Model proxy), transport tiêm khóa, breaker, lọc lỗi                                         | YC58; Model proxy dựng sau spike ở ticket 01                                                                                            | model-connections đợt sau (W2)                    |
| Lane `model_probe`, đo usage BYOM, màn "Kết nối model"                                                                     | YC58; phụ thuộc kết nối model và sổ usage                                                                                               | model-connections đợt sau (W2)                    |
| W2: lời gọi model của công ty ghi phiên bản khóa đã dùng trên sự kiện sử dụng của nó (`platform.usage_events`)             | H-25; W1 không có kết nối model của công ty, nên không lời gọi nào có khóa của công ty để ghi; khóa không ghim trong bản kê (V4.35)     | model-connections; usage-and-limits, đợt sau (W2) |
| Route dự phòng trong cùng công ty                                                                                          | Cần breaker theo kết nối trước                                                                                                          | đợt sau (W3)                                      |
| Embedding BYOM cho tri thức                                                                                                | Độ rộng vector mới cần collection mới                                                                                                   | đợt sau (W2)                                      |
| Kho bí mật, kết nối, `egress_allowed_hosts`, smokescreen                                                                   | Kết nối và lối ra mạng                                                                                                                  | connections-and-vault                             |
| Bảng giá, sổ usage, lease                                                                                                  | Hạn mức và đo; Bảng giá là chủ duy nhất của giá (DO-21.5)                                                                               | usage-and-limits                                  |
| `ResidencyGate` và chính sách lớp tuyến dữ liệu                                                                            | Cổng tuyến dữ liệu; chỉ đọc `data_location`, `processor` mà spec này giữ                                                                | compliance-pdpl                                   |
| Lưu và duyệt phiên bản cấu hình kind `model_profile`                                                                       | Vỏ phiên bản và hai người duyệt                                                                                                         | tenant-config                                     |
| Ghim route cho lượt không có gốc Studio (đồ thị mã, workflow của gói, trợ lý nền tảng)                                     | Chỉ lượt có gốc Studio có bản kê (ADR-0109 (Accepted) quyết 6); lượt khác phân giải mỗi lời gọi qua `ModelResolver` theo công ty và gói | không làm ở W1                                    |
| W2: luật của lớp hồ sơ công ty (chỉ trỏ kết nối model của chính công ty, không tự khai `data_location` cho route nền tảng) | W1 không có đường ghi lớp công ty; luật đi cùng đường ghi đó                                                                            | model-connections; tenant-config, đợt sau (W2)    |
| `StudioModelSelection` và chọn model theo công ty cho agent biên dịch một lần                                              | Cửa chọn model là của agent Studio; agent của gói biên dịch từ lớp nền tảng                                                             | agent-builder                                     |

## Dữ liệu

- `platform.plan_model_profiles`: `plan_id text NOT NULL` với FK tới `platform.plans (plan_id)` ON DELETE CASCADE, như `platform.plan_limits` của usage-and-limits (dòng của gói đi theo gói; `platform.entitlements.plan_id` giữ ON DELETE RESTRICT nên gói còn công ty dùng thì không xóa được); `profile_id text NOT NULL`, khóa văn bản của một hồ sơ trong `configs/models`, không FK vì hồ sơ nền tảng là tệp cấu hình chứ không là bảng, và một test đỏ khi một `profile_id` của bảng không có trong `configs/models` (failure-modes #2); khóa chính tổng hợp `(plan_id, profile_id)`, dẫn đầu bằng `plan_id` nên cũng là chỉ mục của FK; migration revision hex; bảng danh mục toàn cục như `platform.plan_limits` (`db/migrations/versions/764b0e239f95_plan_limits.py`): không `tenant_id` (nên ngoài tập bảng mà `test_rls_coverage.py` đọc), không RLS, chỉ migration ghi; `dw_app` chỉ có SELECT, INSERT, UPDATE, DELETE và TRUNCATE bị thu hồi khỏi mọi vai ứng dụng và `test_privileges.py` khẳng định điều đó; tên ràng buộc theo `NAMING_CONVENTION`. Migration gieo một dòng cho mỗi gói có trong `platform.plans` nhân mỗi hồ sơ có trong `configs/models` ở commit của migration, nên không công ty nào mất model khi bảng ra đời; một hồ sơ thêm sau đó không thuộc gói nào tới khi một migration liệt kê nó. Hồ sơ nền tảng ngoài gói không bao giờ phân giải cho công ty giữ gói đó.

## Kiểm soát

| #   | Kiểm soát                              | Yêu cầu          | Test âm                                                                                                                                                                                           |
| --- | -------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MR1 | Một bộ phân giải cho mọi cửa           | R1.1, R1.2       | mọi cửa trả cùng route cho công ty có hồ sơ riêng; một cửa bỏ `tenant_id` → test đỏ; một lời gọi `ModelProfileRegistry.resolve` thêm ngoài bộ phân giải và các chỗ được liệt kê → test quét mã đỏ |
| MR2 | Không phân giải sang công ty khác      | R1.3             | hồ sơ của công ty B không bao giờ trả cho A (mẫu `test_tenant_overlay.py`); gỡ bước rơi về nền tảng → test đỏ                                                                                     |
| MR3 | Lọc theo gói                           | R2.1, R2.2, R2.6 | hồ sơ nền tảng ngoài gói, gói không có dòng nào, danh mục không đọc được → `model_profile_unavailable`; gỡ lọc gói, hay đổi lỗi đọc thành "mọi hồ sơ" → test đỏ                                   |
| MR4 | Route đã ghim không đổi giữa lượt chạy | R1.4, R1.5       | hồ sơ đổi giữa lượt chạy → lời gọi bị từ chối, không gửi theo route mới hay route cũ; hồ sơ không ghim → từ chối; gỡ đọc route từ bản kê, hay gỡ so nội dung đã ghim → test đỏ                    |
| MR5 | `data_location` mặc định đóng          | R3.1, R3.2       | YAML thiếu `data_location` hay `processor`, hay `data_location: VN` → bộ nạp từ chối, CI đỏ; `ModelRoute` dựng không có `data_location` → lỗi kiểm; gỡ kiểm → test đỏ                             |
| MR6 | Không có lượt chạy thì không phân giải | R1.6             | cửa model gọi bộ phân giải không có `RunContext` → từ chối; cho rơi về lớp nền tảng chưa lọc → test đỏ                                                                                            |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát MR1–MR6 có test âm đã thấy đỏ khi gỡ guard.
- `make ci` xanh, gồm test `test_tenant_overlay.py` cho model và kiểm CI đỏ khi một YAML hồ sơ thiếu `data_location`.

## Phụ thuộc

- `tenant-config`: bản kê lượt chạy ghim route model (`tenant-config:R6.1`); phiên bản cấu hình kind `model_profile` cho hồ sơ công ty (W2). Ticket `.claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md`.
- usage-and-limits: ticket 02 chờ `.claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md`, nơi Bảng giá ra đời và `route_cost` thôi đọc giá trên route, rồi bỏ hai trường giá khi dựng `ModelProfile` v2; mỗi tệp `model/profiles.py`, `configs/models/*.yaml` có một ticket sửa (H-4).
- Seam do bên khác dựng, tham chiếu bằng slug: `usage-and-limits` (Bảng giá là chủ duy nhất của giá, kể cả mục giá của công ty `platform.tenant_price_entries` cho BYOM (usage-and-limits:R2.1); hồ sơ chỉ dẫn chiếu; sổ usage); `compliance-pdpl` (`ResidencyGate` gọi bởi mọi caller của bộ phân giải, lớp tuyến chặt nhất của công ty, workspace và agent, chỉ đọc trường tuyến dữ liệu của R2.3 và R3; ticket 03 của compliance-pdpl không thêm lại các trường đó); `connections-and-vault` (kho bí mật, kết nối `llm_<kind>`, `egress_allowed_hosts`, smokescreen trên mạng `dw-llm`).
- Lát thí điểm chạy dưới `vn_only` nên cần ít nhất một route nền tảng khai `data_location` là Việt Nam trước bước AI đầu tiên (ADR-0118 (Accepted); FOG-10 ở `.claude/plans/studio/discovery/issues/19-vietnamese-model-quality.md`, FOG-18 ở `.claude/plans/studio/discovery/issues/18-requester-questions.md`).
- Kiểm lại khi: một sự cố mới của LiteLLM sau báo cáo cuối ngày 23/10/2026, hay một advisory mới chạm bản ghim → ticket 01 và bản ghim; FOG-18 khai nơi xử lý của từng alias trên gateway nền tảng → R3.2; FOG-10 không tìm được model xử lý tại Việt Nam đủ chất lượng → bước AI đầu tiên của thí điểm; luật sư đổi kết luận DO-54.2 → R3.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (agent, tạm): ghim LiteLLM 1.106.1 cho lane BYOM tới khi có báo cáo sự cố cuối (O6/DO-19, theo D13). Sửa: ticket 01, Ngoài phạm vi. Nếu sai thì: nếu báo cáo cho phép 1.106.2, nâng theo quy trình 14 ngày. (Từ 5/11/2026 bản ghim là 1.106.5, xem dòng 5/11/2026 bên dưới.)
- 23/10/2026 (agent, tạm): `data_location` không khai coi là nước ngoài, và YAML thiếu `data_location` làm CI đỏ (ADR-0123 (Accepted), `failure-modes.md` #7). Sửa: R3.1, R3.2. Nếu sai thì: nếu có mặc định khác do counsel chốt, đổi R3.2.
- 23/10/2026 (agent, tạm): không fallback từ model của công ty sang model nền tảng; token BYOM chỉ trừ hạn mức công ty đặt (DO-43 khuyến nghị a). Sửa: Ngoài phạm vi. Nếu sai thì: theo ghi chú DO-43.
- 23/10/2026 (Đạt): DO-21.5 theo (a): Bảng giá là chủ duy nhất của giá; bỏ R2.4 và phần giá khỏi `ModelProfile` v2, hồ sơ chỉ dẫn chiếu. Sửa: R2, R2.4 (rút), Trong phạm vi, Ngoài phạm vi, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): DO-43 theo (a), cả bốn ý của dòng tạm cùng ngày ở trên: không chuyển sang route của nền tảng hay công ty khác, model của công ty trên kết nối của workspace được dùng công cụ, không endpoint tại chỗ ở v1, token BYOM chỉ tính vào trần do công ty đặt; BYOM ở W2. Hỏi: Q1.
- 23/10/2026 (Đạt): DO-54.2 theo (a): nền tảng là bên xử lý, công ty là bên kiểm soát, DPA ký trước chạy bóng; sản phẩm xuất đầu vào cho hồ sơ, luật sư quyết ai nộp DPIA và CTIA; nới lộ trình dữ liệu cần hai người (D11), siết một người. Hỏi: Q2.
- 23/10/2026 (Đạt): ADR-0118 (Accepted) kèm sửa: LiteLLM ghim 1.106.1 và chỉ nâng sau 14 ngày cùng một lần kiểm advisory; alias chưa khai nơi xử lý là nước ngoài; lát thí điểm cần một route xử lý tại Việt Nam trước bước AI đầu tiên (FOG-10). Dòng tạm về bản LiteLLM cùng ngày ở trên thành quyết định có ngày. Sửa: Phụ thuộc, ticket 01. (Từ 5/11/2026 bản ghim là 1.106.5, xem dòng 5/11/2026 bên dưới.)
- 23/10/2026 (agent, tạm): spec và ticket 01 gọi lane LiteLLM là model proxy, đúng thuật ngữ glossary; tên tệp ticket 01 giữ nguyên để không gãy liên kết (phát hiện kiểm nhất quán 23/10/2026). Sửa: tiêu đề, đoạn đầu, Ngoài phạm vi, ticket 01. Nếu sai thì: đổi lại tên trong cùng các chỗ đó.
- 23/10/2026 (agent, tạm): trường tuyến dữ liệu (`data_location`, `processor`, `retention_days`, `no_training`) và luật "không khai là nước ngoài" chỉ ở spec này (R2.3, R3); compliance-pdpl chỉ đọc; ticket 02 chờ tenant-config/04 vì ghim route vào bản kê lượt chạy (phát hiện kiểm nhất quán 23/10/2026). Sửa: Trong phạm vi, Ngoài phạm vi, Phụ thuộc, ticket 02. Nếu sai thì: chuyển trường sang compliance-pdpl và đổi chiều Blocked by của compliance-pdpl/03.
- 24/10/2026 (Đạt): dịch vụ compose của Model proxy tên `model-proxy` ở mọi tài liệu, tên của glossary, không còn `litellm-byom`; ADR-0118 (Accepted) quyết 8 sửa cùng ngày. Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): YC58 ghi ở các dòng W2 của Ngoài phạm vi, để lần ngược được từ roadmap. Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): ticket 02 đi trước usage-and-limits/02, vì cả hai sửa `model/profiles.py` và `configs/models/*.yaml`: ticket 02 dựng `ModelProfile` v2, usage-and-limits/02 chờ nó rồi mới dời giá sang Bảng giá. Sửa: ticket 02.
- 24/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11: W1 chưa có đường hai người cho việc nới lộ trình dữ liệu, nên thao tác đó bị khóa ở W1 (409 `conflict`, `second_person_required`; ADR-0110 (Accepted) quyết 2); vế "nới lộ trình dữ liệu cần hai người" của dòng DO-54.2 ở trên chỉ có đường từ W2. Spec này không có thao tác nới lộ trình nào. Sửa: không mục nào ngoài dòng này; áp ở compliance-pdpl và tenant-config.
- 24/10/2026 (agent, tạm): `platform.plan_model_profiles.plan_id` có FK tới `platform.plans (plan_id)` ON DELETE CASCADE, như `platform.plan_limits` của usage-and-limits, với chỉ mục là khóa chính `(plan_id, profile_id)`; `profile_id` là khóa văn bản kiểm theo `configs/models` bằng một test, không FK, vì hồ sơ nền tảng nằm trong tệp cấu hình (CLAUDE.md, Data model rules: khóa ngoại nào cũng nêu `ON DELETE` và có chỉ mục ở phía của nó; failure-modes #2). Sửa: Dữ liệu, ticket 02. Nếu sai thì: FK là `ON DELETE RESTRICT`, và xóa một gói phải xóa trước các dòng của nó ở bảng này.
- 24/10/2026 (agent, tạm): cửa ngân sách lượt chạy mà `ModelResolver` phục vụ là `RunBudgetMiddleware` lúc ticket 02 dựng, rồi `LimitsMiddleware` của usage-and-limits/03 thay nó, như ADR-0118 (Accepted) quyết 1 nêu `LimitsMiddleware` thay `RunBudgetMiddleware`; R1.1 và MR1 giữ, vì cửa thay thế đọc cùng bộ phân giải. Sửa: Trong phạm vi, ticket 02. Nếu sai thì: `LimitsMiddleware` không đọc route, và danh sách cửa của R1.1 bỏ nó.
- 25/10/2026 (Đạt): V4.35: bản kê lượt chạy ghim id kết nối và phiên bản Bộ giá trị gắn, không ghim `secret_version`; lời gọi dùng phiên bản mới nhất chưa thu hồi của kết nối và ghi phiên bản đã dùng; xoay tách khỏi thu hồi vì lộ. Ở spec này: `ResolvedRoute` ghim trong bản kê không mang phiên bản bí mật (ADR-0118 (Accepted) quyết 1). Sửa: R1.4, Trong phạm vi, ticket 02.
- 25/10/2026 (agent, tạm): H-4: usage-and-limits/02 dựng Bảng giá theo ngày hiệu lực và chuyển `route_cost` sang đọc nó, không sửa `model/profiles.py` hay `configs/models/*.yaml`; ticket 02, nay chờ ticket đó, bỏ hai trường giá đã không còn ai đọc khi dựng `ModelProfile` v2, còn `temperature`, `max_cost_usd_per_run` vẫn sang `Decimal`; thay dòng ngày 24/10/2026 ở trên ("ticket 02 đi trước usage-and-limits/02"). Sửa: Trong phạm vi, Phụ thuộc, ticket 02. Nếu sai thì: usage-and-limits/02 chờ ticket 02 như trước.
- 25/10/2026 (agent, tạm): H-25: lời gọi model của công ty (W2) ghi phiên bản khóa đã dùng trên sự kiện sử dụng của nó, `platform.usage_events` của usage-and-limits, là một dòng Ngoài phạm vi W2. Sửa: Ngoài phạm vi. Nếu sai thì: chỉ audit ghi phiên bản khóa.
- 2/11/2026 (agent, theo ủy quyền 31/10/2026): sửa ticket 01 theo gate `checking-plan-readiness`. Đây là builder check, không có boundary walk vì ticket không có migration hay route; đo trên `6593e0e`. Gate tìm ra 10 HIGH, đã sửa hết:
    - spike nằm ở `infra/spikes/model-proxy/` trên `main`, không dưới gói `dw_studio` chưa tồn tại;
    - phần cần khóa thật hay GPU tách sang ticket 03 (Chờ Đạt 21);
    - một proxy ghi kết nối đứng thay smokescreen, vì smokescreen thật chờ discovery/21;
    - tham số cấm được liệt kê;
    - thêm phép đo regex `api_base` lồng nhau và phép đo cooldown, retry tắt;
    - log của proxy và callback của LangChain được quét ở bốn dạng mã hóa;
    - luật 14 ngày tính từ lúc 1.106.1 lên PyPI ngày 20/10/2026, nên chỉ chạy được từ 4/11/2026 (từ 5/11/2026: 1.106.5,
      chạy được từ 2026-11-10 19:45 UTC);
    - bỏ câu "một model proxy hay hai", vì D13 đã chốt;
    - không tự nới cấu hình của ADR-0118 (Accepted) quyết định 8.

    Chi tiết ở Comments của ticket 01. Sửa: ticket 01, ticket 03, Danh sách ticket. Nếu sai thì: như dòng `Nếu sai thì` ở Comments của ticket 01.

- 2/11/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01. Ticket 01 chỉ chạm `infra/spikes/model-proxy/` và Comments của nó, không bảng, route, migration, config hay prompt nào của ticket 02; ticket 03 chờ nó và chạm cùng thư mục. Cách chia 02 và 03 được duyệt khi gate chạy cho chúng. Theo `## Ủy quyền` của studio.md (Đạt, 31/10/2026). Nếu sai thì: hạ ticket 01 về `needs-triage` và chia lại.
- 4/11/2026 (agent, theo ủy quyền 31/10/2026): sửa spec và ticket 02 theo gate `checking-plan-readiness` của ticket 02 và 03 (builder check và boundary walk, vì ticket 02 có migration; đo trên `c8dab56`). Mỗi ý dưới đây là khuyến nghị của gate:
    - R1.1: cửa đọc công ty, gói và workspace từ `RunContext`; `StudioModelSelection` và giám khảo chưa có trong mã, nên ticket 02 nối bốn cửa đang có và một test quét mã, còn hai cửa kia nhận bộ phân giải qua constructor ở ticket dựng chúng (agent-builder/03; bộ chấm LLM đầu tiên của `dw_evals`). Nếu sai thì: ticket 02 dựng thêm hai cửa đó.
    - R1.4, R1.5: chỉ lượt có gốc Studio có bản kê (ADR-0109 (Accepted) quyết 6), nên chỉ lượt đó ghim; ghim theo giá trị, mọi route kể cả route dự phòng, vào `engine.model_routes` như ADR-0109 (Accepted) quyết 8 đã nêu "the model route". Một lời gọi trong lượt Studio gặp hồ sơ không ghim, nội dung hiện hành khác bản ghim, hay gói không còn cho phép thì bị từ chối: lượt không đổi route giữa chừng, và cũng không gửi theo một khai báo đã bị sửa (chẳng hạn alias khai lại `foreign` sau FOG-18). Lượt khác phân giải mỗi lời gọi (dòng Ngoài phạm vi). Nếu sai thì: lượt Studio tiếp tục trên bản ghim dù hồ sơ đã đổi, và cổng lộ trình đọc khai báo hiện hành.
    - R1.6: bộ phân giải không có `tenant_id=None`; lớp nền tảng chưa lọc chỉ qua `platform_profile` cho composition root (độ rộng embedding, adapter) và script (`check-model`, eval). Gói là `RunContext.plan_id` của lượt, như `RunAllowancePort`; một gói giả không có dòng bị từ chối (`background` của `apps/worker/src/dw_worker/consumers/memory.py:67` là gói của một `AccessContext` không gọi model nào), và composition root của eval và test tiêm một danh mục trong bộ nhớ liệt kê hồ sơ chúng dùng. Nếu sai thì: `tenant_id=None` trả lớp nền tảng chưa lọc như hôm nay.
    - R2.2, R2.6, Dữ liệu: gói không có dòng, hay danh mục không đọc được, là từ chối; bảng là danh mục toàn cục như `platform.plan_limits` (không RLS, chỉ SELECT cho `dw_app`), thay câu "RLS theo lớp nền tảng" và quyền của `dw_agent_ro`, vì không bên nào đọc nó dưới `dw_agent_ro`; migration gieo mọi gói nhân mọi hồ sơ hiện có, để không công ty nào mất model khi bảng ra đời. Nếu sai thì: gieo chỉ hồ sơ mặc định của deployment cho mỗi gói.
    - R2.5: `make check-model` gọi gateway thật bằng khóa trong `.env`, nên không chạy trong CI; nó thăm dò hồ sơ mà deployment chọn hay `PROFILE=`, và phép so cờ là một hàm có test đơn vị với bản thăm dò giả chạy trong CI. Nếu sai thì: thêm một job CI có khóa gateway.
    - R3.1, R3.2: bộ nạp từ chối cả thiếu `processor` và giá trị ngoài `vn`, `foreign` (ADR-0123 (Accepted) quyết 5); `ModelRoute` không có mặc định cho `data_location`, và route trên gateway nền tảng chưa định vị (FOG-18) khai `foreign`, nên "không khai là nước ngoài" không còn là một nhánh đọc mà là không có đường nào ra `vn` khi chưa khai. Nếu sai thì: `data_location` nhận `None` và một hàm duy nhất đọc `None` là `foreign`.
    - Lớp công ty ở W1 chỉ là lớp trong bộ nhớ mà test đăng ký; luật của lớp đó là dòng W2 của Ngoài phạm vi. Nếu sai thì: ticket 02 dựng đường đọc `platform.config_versions` kind `model_profile`.
- 4/11/2026 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của cùng gate tìm thêm năm chỗ, sửa như khuyến nghị:
    - R1.6: bước ghim lúc nhận lượt chưa có `RunContext`, nên `ModelResolver.pin` nhận công ty và gói từ ngữ cảnh đã xác
      minh của cửa nhận lượt; R1.6 nói rõ điều đó. Nếu sai thì: cửa nhận lượt dựng một `RunContext` của lượt trước khi ghim.
    - R2.1: lớp công ty không qua lọc gói, như ADR-0118 (Accepted) quyết 1; R1.5 chỉ xét gói cho hồ sơ nền tảng.
    - R1.5: lời gọi bị từ chối kết thúc lượt `failed`, không `blocked`, vì không có đường "sửa" nào ngoài việc trả YAML về
      bản cũ; `content_hash` tính trên các route được ghim, không gồm `embedding`; ghi ở ADR-0118 (Accepted), Amendments
      2026-11-04. Nếu sai thì: lượt `blocked` với `incompatible_resume` như ADR-0109 (Accepted) quyết 8.
    - Hồ sơ mặc định: bản kê ghi hồ sơ nào là mặc định lúc nhận, và `profile_id` `None` trong lượt Studio đọc hồ sơ đó,
      không đọc `DW_API_MODEL_PROFILE` hiện hành; hồ sơ mặc định ngoài gói không làm hỏng việc nhận lượt, chỉ không được
      ghim. Nếu sai thì: nhận lượt từ chối khi gói không có hồ sơ mặc định.
    - Cờ năng lực: `ModelProfile` v2 mang đủ tập đóng mười hai cờ của ADR-0118 (Accepted) quyết 2, cờ không khai là không
      hỗ trợ, tên ngoài tập là lỗi nạp; dẫn chiếu giá là cặp (`provider`, `model`) của route, đúng khóa mà `PricingPort`
      đã dùng; hồ sơ model vào release manifest. Nếu sai thì: chỉ ba cờ có bên đọc, và hồ sơ ngoài release manifest.
- 4/11/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 02-03. Ticket 02 chờ workflow-engine/02, vì ghim lúc nhận lượt cần `RunRequestService` và cả hai sửa `apps/api/src/dw_api/bootstrap/studio.py` và lời gọi `RunManifestBuilder.build`; workflow-engine/05 sửa cùng `EngineSection` nhưng đã chờ ticket 02 qua workflow-engine/04, usage-and-limits/03 và compliance-pdpl/03. Ticket 03 chỉ chạm `infra/spikes/model-proxy/` sau ticket 01 và cần khóa thật (Chờ Đạt 21), nên `ready-for-human`. Theo `## Ủy quyền` của studio.md (Đạt, 31/10/2026). Nếu sai thì: hạ hai ticket về `needs-triage` và chia lại.
- 5/11/2026 (agent, theo ủy quyền 31/10/2026): ticket 01 dừng ở bước 0, vì GHSA-w4c7-34wj-hqm8 (Critical, 27/10/2026) có khoảng `< 1.106.5` chứa bản ghim 1.106.1; chưa chạy LiteLLM. Ticket về `needs-triage`, chờ sửa bản ghim ở ADR-0118 (Accepted) quyết định 8 (khuyến nghị: 1.106.5, chạy từ 11/11/2026 02:45 giờ Việt Nam) rồi gate lại; số đo và đề xuất ở Comments của ticket 01. Sửa: ticket 01, ticket 03. Nếu sai thì: ticket 01 chạy trên 1.106.1 như đã gate, và bước 0 của nó ghi cách đọc "chạm" theo điều kiện tiên quyết.
- 5/11/2026 (agent, theo ủy quyền 31/10/2026): nhận đề xuất bốn ý ở Comments của ticket 01; thay bản ghim của hai dòng 23/10/2026 ở trên.
    - ADR-0118 (Accepted) quyết định 8 ghim LiteLLM 1.106.5, bản sửa thấp nhất của nhánh 1.106 cho GHSA-w4c7-34wj-hqm8;
      chạy sớm nhất 2026-11-10 19:45 UTC (11/11/2026 02:45 giờ Việt Nam) theo luật 14 ngày, sau một lần kiểm advisory
      lúc đó (Amendments 2026-11-05 của ADR). Nếu sai thì: nếu Đạt đọc "chạm" là "khoảng chứa bản đó và điều kiện
      tiên quyết có thể xảy ra với cấu hình của quyết định 8", ticket 01 chạy lại trên 1.106.1 mà không đổi gì khác, và
      bước 0 của nó ghi rõ cách đọc đó.
    - Bản ghi "attack chain" ngày 23/10/2026 của nhà cung cấp là báo cáo sự cố cuối mà bản ghim và FOG-19 chờ. Nếu sai
      thì: chờ nhà cung cấp gọi rõ một báo cáo là báo cáo cuối, và ticket 01 chờ theo.
    - Tiêu chí thiếu khóa của ticket 01 cấm thêm `LITELLM_LICENSE` trong môi trường của `model-proxy`, và quyết định 8
      cấm biến đó cho `model-proxy` thật ở W2, để mã Enterprise mà advisory cần không bao giờ được nạp. Nếu sai thì:
      bỏ biến đó khỏi danh sách cấm, không đổi gì khác.

    Sửa: ticket 01 (Mục tiêu, bước 0, 1, 6, hai tiêu chí), ticket 03 (bước 0), Phụ thuộc (Kiểm lại khi).

- 5/11/2026 (agent, theo ủy quyền 31/10/2026): gate lại ticket 01 bằng `checking-plan-readiness` (builder check và một lượt
  xác nhận, không boundary walk vì ticket không có migration hay route): 0 CRITICAL, 14 HIGH đã sửa như khuyến nghị; chi tiết
  ở Comments của ticket 01. Hai lần gọi tạm: luật 14 ngày áp cả cho gói phụ thuộc của LiteLLM (cờ `--exclude-newer`), và `max_retries: 0` theo từng model chỉ được thêm khi đo thấy client bên trong LiteLLM tự retry, như
  một lần siết của quyết định 8. Sửa: ticket 01. Nếu sai thì: luật 14 ngày chỉ áp cho `litellm`, và retry của client làm
  ticket dừng và đề xuất như bước 6 của nó.

## Danh sách ticket

| #   | Ticket                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------- |
| 01  | [Spike: model proxy LiteLLM theo nhà cung cấp và tiêm khóa ở transport](issues/01-spike-lane-litellm.md)          |
| 02  | [`ModelResolver` theo công ty, `ModelProfile` v2, `plan_model_profiles`](issues/02-model-resolver-theo-tenant.md) |
| 03  | [Spike: model proxy với từng nhà cung cấp thật](issues/03-spike-nha-cung-cap-that.md)                             |
