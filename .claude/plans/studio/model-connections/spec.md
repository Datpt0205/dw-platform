# Bộ phân giải model theo công ty, BYOM qua lane LiteLLM

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi cửa model của Studio cần một bộ phân giải theo công ty để chọn đúng hồ sơ model mà gói cho phép, ghim vào bản kê lượt chạy và đi theo lộ trình dữ liệu chặt nhất, thay cho ba chỗ đọc hồ sơ lệch nhau hôm nay; và công ty cần kết nối model của chính mình qua một lane LiteLLM không trạng thái. W1 làm `ModelResolver` và hồ sơ nền tảng lọc theo gói cho bước AI và trợ lý, cùng một spike chốt ADR BYOM; kết nối model đầy đủ (BYOM) là W2.

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

Mọi cửa model đọc một bộ phân giải theo công ty, trả cùng một route và ghim nó vào bản kê, không bao giờ phân giải sang công ty khác (YC32, YC85, ADR-0118 (Proposed)).

- R1.1 `ModelResolver` PHẢI là nguồn route model duy nhất cho mọi cửa model, gồm chọn model, ngân sách lượt chạy, đo usage, gateway có cấu trúc, nén ngữ cảnh và giám khảo.
- R1.2 KHI hai cửa model khác nhau phân giải cho một công ty có hồ sơ riêng, `ModelResolver` PHẢI trả cùng một route cho cả hai.
- R1.3 NẾU một công ty hỏi một hồ sơ mà chỉ công ty khác có bản riêng, THÌ `ModelResolver` PHẢI rơi về hồ sơ nền tảng và không bao giờ trả bản của công ty khác.
- R1.4 KHI một lượt chạy được nhận, `ModelResolver` PHẢI ghim route model đã phân giải vào bản kê lượt chạy của lượt.

### R2 — Hồ sơ model trong danh sách gói cho phép, `ModelProfile` v2

Bộ phân giải chỉ trả hồ sơ mà gói cho phép; hồ sơ mang phiên bản, cờ năng lực và giá chính xác (YC85, ADR-0118 (Proposed)).

- R2.1 `ModelResolver` PHẢI chỉ trả hồ sơ model mà gói của công ty cho phép, đọc từ `platform.plan_model_profiles`.
- R2.2 NẾU một lượt chạy xin một hồ sơ model ngoài danh sách gói, THÌ `ModelResolver` PHẢI từ chối với `model_profile_unavailable` và không gọi model.
- R2.3 `ModelProfile` v2 PHẢI mang số phiên bản, cờ năng lực `strict_tools` và `numeric_bounds`, và trường `data_location` và `processor`.
- R2.4 `ModelProfile` PHẢI biểu diễn giá bằng số thập phân dạng chuỗi, không phải số thực dấu phẩy động.
- R2.5 KHI `make check-model` chạy, lệnh `make check-model` PHẢI thăm dò mỗi route nền tảng và báo lỗi khi một cờ năng lực khai khác kết quả thăm dò.

### R3 — Trường tuyến dữ liệu, mặc định coi là nước ngoài

Hồ sơ model khai nơi xử lý dữ liệu; thiếu khai là nước ngoài, không fail-open (YC85, ADR-0123 (Proposed)).

- R3.1 NẾU một tệp YAML hồ sơ model nền tảng thiếu `data_location`, THÌ bộ nạp hồ sơ model PHẢI từ chối nạp và báo lỗi.
- R3.2 Hồ sơ model PHẢI coi `data_location` không khai là nước ngoài.

## Trong phạm vi

- `ModelResolver`: một cổng cho `StudioModelSelection`, `RunBudgetMiddleware`, `LangchainUsageMeter`, `RoutingModelGateway` và nén ngữ cảnh; đọc lớp nền tảng lọc theo gói (lớp công ty khi `tenant-config` có phiên bản cấu hình).
- `ModelProfile` v2: số phiên bản, cờ năng lực (`strict_tools`, `max_strict_tools`, `numeric_bounds`), trường `data_location`, `processor`, `retention_days`, `no_training` (không mặc định), giá dạng `Decimal`.
- Bảng `platform.plan_model_profiles` (gói của công ty tới hồ sơ cho phép).
- `make check-model` thăm dò và so cờ năng lực khai với kết quả thăm dò.

## Ngoài phạm vi

| Việc                                                              | Vì sao                                     | Chủ                   |
| ----------------------------------------------------------------- | ------------------------------------------ | --------------------- |
| Bảng `platform.model_connections`, API quản trị, quyền lợi `byom` | Kết nối model đầy đủ dựng sau bộ phân giải | đợt sau (W2)          |
| Service `litellm-byom`, transport tiêm khóa, breaker, lọc lỗi     | Lane BYOM dựng sau spike chốt ADR          | đợt sau (W2)          |
| Lane `model_probe`, đo usage BYOM, màn "Kết nối model"            | Phụ thuộc kết nối model và sổ usage        | đợt sau (W2)          |
| Route dự phòng trong cùng công ty                                 | Cần breaker theo kết nối trước             | đợt sau (W3)          |
| Embedding BYOM cho tri thức                                       | Độ rộng vector mới cần collection mới      | đợt sau (W2)          |
| Kho bí mật, kết nối, `egress_allowed_hosts`, smokescreen          | Kết nối và lối ra mạng                     | connections-and-vault |
| Bảng giá, sổ usage, lease                                         | Hạn mức và đo                              | usage-and-limits      |
| `ResidencyGate` và chính sách lớp tuyến dữ liệu                   | Cổng tuyến dữ liệu                         | compliance-pdpl       |
| Lưu và duyệt phiên bản cấu hình kind `model_profile`              | Vỏ phiên bản và hai người duyệt            | tenant-config         |

## Dữ liệu

- `platform.plan_model_profiles`: `plan_id`, `profile_id`, cùng khóa chính tổng hợp; migration revision hex; RLS theo lớp nền tảng đọc được bởi `dw_app` và `dw_agent_ro`; FK `ON DELETE` tường minh và chỉ mục; tên ràng buộc theo `NAMING_CONVENTION`. Hồ sơ nền tảng ngoài gói không bao giờ phân giải cho công ty giữ gói đó.

## Kiểm soát

| #   | Kiểm soát                              | Yêu cầu    | Test âm                                                                                                       |
| --- | -------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------- |
| MR1 | Một bộ phân giải cho mọi cửa           | R1.1, R1.2 | mọi cửa trả cùng route cho công ty có hồ sơ riêng; một cửa bỏ `tenant_id` → test đỏ                           |
| MR2 | Không phân giải sang công ty khác      | R1.3       | hồ sơ của công ty B không bao giờ trả cho A (mẫu `test_tenant_overlay.py`); gỡ bước rơi về nền tảng → test đỏ |
| MR3 | Lọc theo gói                           | R2.1, R2.2 | hồ sơ nền tảng ngoài gói → `model_profile_unavailable`; gỡ lọc gói → test đỏ                                  |
| MR4 | Route đã ghim không đổi giữa lượt chạy | R1.4       | hồ sơ đổi giữa lượt chạy → route đã ghim không đổi; gỡ đọc route từ bản kê → test đỏ                          |
| MR5 | `data_location` mặc định đóng          | R3.1, R3.2 | YAML thiếu `data_location` → bộ nạp từ chối, CI đỏ; alias không khai coi là nước ngoài; gỡ kiểm → test đỏ     |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát MR1–MR5 có test âm đã thấy đỏ khi gỡ guard.
- `make ci` xanh, gồm test `test_tenant_overlay.py` cho model và kiểm CI đỏ khi một YAML hồ sơ thiếu `data_location`.

## Phụ thuộc

- `tenant-config`: bản kê lượt chạy ghim route model (`tenant-config:R6.1`); phiên bản cấu hình kind `model_profile` cho hồ sơ công ty (W2). Ticket `.claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md`.
- Seam do bên khác dựng, tham chiếu bằng slug: `usage-and-limits` (bảng giá `platform.tenant_price_entries`, sổ usage — giá đọc qua một hàm mà ticket bảng giá thay); `compliance-pdpl` (`ResidencyGate` gọi bởi mọi caller của bộ phân giải, lớp tuyến chặt nhất của công ty, workspace và agent); `connections-and-vault` (kho bí mật, kết nối `llm_<kind>`, `egress_allowed_hosts`, smokescreen trên mạng `dw-llm`).
- Kiểm lại khi: DO-19/D13 chốt lane BYOM và bản LiteLLM → ticket 01, Ngoài phạm vi; DO-54 chốt vai trò bảo vệ dữ liệu và nới lộ trình → R3.

## Câu hỏi còn mở

- Q1. DO-43: Model của công ty có được rơi về model nền tảng khi lỗi, có được gắn công cụ, có endpoint nội bộ ở v1, và token BYOM có trừ hạn mức token của gói không? Chủ: Đạt với người đặt yêu cầu. Không đổi: W1 chỉ có bộ phân giải và hồ sơ nền tảng; BYOM là W2.
- Q2. DO-54: Ai nộp DPIA và CTIA, và nới lộ trình dữ liệu có cần hai người không? Chủ: counsel với người đặt yêu cầu. Không đổi: W1 mặc định `vn_only`; nới lộ trình và BYOM là W2.

## Quyết định

- 23/10/2026 (agent, tạm): ghim LiteLLM 1.106.1 cho lane BYOM tới khi có báo cáo sự cố cuối (O6/DO-19, theo D13). Sửa: ticket 01, Ngoài phạm vi. Nếu sai thì: nếu báo cáo cho phép 1.106.2, nâng theo quy trình 14 ngày.
- 23/10/2026 (agent, tạm): `data_location` không khai coi là nước ngoài, và YAML thiếu `data_location` làm CI đỏ (ADR-0123 (Proposed), `failure-modes.md` #7). Sửa: R3.1, R3.2. Nếu sai thì: nếu có mặc định khác do counsel chốt, đổi R3.2.
- 23/10/2026 (agent, tạm): không fallback từ model của công ty sang model nền tảng; token BYOM chỉ trừ hạn mức công ty đặt (DO-43 khuyến nghị a). Sửa: Ngoài phạm vi. Nếu sai thì: theo ghi chú DO-43.

## Danh sách ticket

| #   | Ticket                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------- |
| 01  | [Spike: lane LiteLLM theo nhà cung cấp và tiêm khóa ở transport](issues/01-spike-lane-litellm.md)                 |
| 02  | [`ModelResolver` theo công ty, `ModelProfile` v2, `plan_model_profiles`](issues/02-model-resolver-theo-tenant.md) |
