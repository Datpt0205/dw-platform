# 02 — `ModelResolver` theo công ty, `ModelProfile` v2, `plan_model_profiles`

Status: needs-triage
Blocked by: .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.5, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5

## Mục tiêu

Thay ba chỗ đọc hồ sơ lệch nhau bằng một `ModelResolver` theo công ty trả lời mọi cửa model, lọc hồ sơ theo gói, ghim route vào bản kê và mang trường tuyến dữ liệu. Chứng minh R1, R2, R3 của spec và cài MR1–MR5. Nền móng chạy được ngay, không chờ BYOM.

## Việc cần làm

1. Dựng `ModelResolver` làm nguồn route duy nhất cho `StudioModelSelection`, `RunBudgetMiddleware` (cửa ngân sách mà `LimitsMiddleware` của usage-and-limits/03 thay sau ticket này, đọc cùng bộ phân giải; ADR-0118 (Accepted) quyết 1), `LangchainUsageMeter`, `RoutingModelGateway` và nén ngữ cảnh; P1 đọc lớp nền tảng lọc theo gói (lớp công ty khi `tenant-config` có phiên bản cấu hình), phân giải rơi về nền tảng, không bao giờ sang công ty khác (mẫu `test_tenant_overlay.py`).
2. `ModelProfile` v2: thêm số phiên bản, cờ năng lực `strict_tools`, `max_strict_tools`, `numeric_bounds`, và trường `data_location`, `processor`, `retention_days`, `no_training` (không mặc định). Ticket này là nơi duy nhất thêm các trường tuyến dữ liệu và luật "không khai là nước ngoài"; `compliance-pdpl/03` chờ ticket này và chỉ đọc chúng. Hồ sơ không mang giá: Bảng giá của `usage-and-limits` là chủ duy nhất (DO-21.5), ticket này không thêm, không đổi trường giá nào.
3. Migration `platform.plan_model_profiles` (revision hex): cột `plan_id text NOT NULL` với FK tới `platform.plans (plan_id)` ON DELETE CASCADE (như `platform.plan_limits`), `profile_id text NOT NULL` là khóa văn bản của một hồ sơ trong `configs/models`, không FK; khóa chính tổng hợp `(plan_id, profile_id)`, cũng là chỉ mục của FK; một test đọc bảng và đỏ khi một `profile_id` không có trong `configs/models`; RLS lớp nền tảng; grant cho `dw_app`, `dw_agent_ro`; tên ràng buộc theo `NAMING_CONVENTION`.
4. `make check-model` thăm dò mỗi route nền tảng và so sánh cờ năng lực khai với kết quả thăm dò, chênh thì báo lỗi và CI đỏ; `tools-and-skills` đọc `strict_tools`, `max_strict_tools`, `numeric_bounds`.
5. Ghim route đã phân giải vào bản kê lượt chạy lúc nhận lượt; đọc route cho mọi lời gọi trong lượt từ bản kê, không phân giải lại giữa lượt.

## Tiêu chí chấp nhận

- [ ] R1.1 (MR1): mọi cửa model (chọn, ngân sách, đo, gateway, nén, giám khảo) trả cùng route cho một công ty có hồ sơ riêng; một cửa bỏ `tenant_id` → test đỏ.
- [ ] R1.2: hai cửa model bất kỳ trả cùng route cho một công ty có hồ sơ riêng; sai nếu hai cửa trả khác nhau.
- [ ] R1.3 (MR2): công ty A hỏi hồ sơ mà chỉ công ty B có bản riêng nhận hồ sơ nền tảng, không bao giờ bản của B; gỡ bước rơi về nền tảng → test đỏ.
- [ ] R1.4 (MR4): hồ sơ đổi giữa một lượt chạy không đổi route đã ghim trong bản kê; gỡ đọc route từ bản kê → test đỏ.
- [ ] R2.1: bộ phân giải chỉ trả hồ sơ mà gói của công ty cho phép; một dòng `platform.plan_model_profiles` có `profile_id` không có trong `configs/models` → test đọc bảng đỏ; sai nếu trả hồ sơ ngoài gói.
- [ ] R2.2 (MR3): lượt chạy xin hồ sơ ngoài danh sách gói nhận `model_profile_unavailable` và không gọi model; gỡ lọc gói → test đỏ.
- [ ] R2.3: `ModelProfile` v2 mang số phiên bản, `strict_tools`, `numeric_bounds`, `data_location`, `processor`; sai nếu thiếu một trường.
- [ ] R2.5: `make check-model` báo lỗi khi một cờ năng lực khai khác kết quả thăm dò; sai nếu chênh mà vẫn xanh.
- [ ] R3.1 (MR5): một YAML hồ sơ nền tảng thiếu `data_location` làm bộ nạp từ chối và CI đỏ; gỡ kiểm `data_location` → test đỏ.
- [ ] R3.2 (MR5): một alias không khai `data_location` được coi là nước ngoài; sai nếu coi là trong nước.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "model_resolver or model_profile" && make check-model` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py:62`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:138`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:113`; `apps/api/src/dw_api/bootstrap/runtime.py:117`; spec: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5.

## Comments

- 2026-10-23 (agent): Đạt chốt DO-21.5 (a) ngày 23/10/2026: R2.4 rút, ticket không đổi giá trên hồ sơ (bước 2). Theo phát hiện kiểm nhất quán cùng ngày: thêm Blocked by tenant-config/04 vì bước 5 ghim route vào bản kê lượt chạy; trường tuyến dữ liệu chỉ thêm ở đây, compliance-pdpl/03 chỉ đọc.
- 2026-10-24 (agent): thứ tự với usage-and-limits/02 theo quyết định Đạt ngày 24/10/2026: cả hai ticket sửa `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py` và `configs/models/*.yaml`, nên ticket này đi trước và dựng `ModelProfile` v2 (bước 2); usage-and-limits/02 ghi Blocked by ticket này rồi dời giá sang Bảng giá trên bản v2. Ticket này không chờ usage-and-limits/02.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: `plan_id` có FK tới `platform.plans` ON DELETE CASCADE như `platform.plan_limits`, `profile_id` là khóa văn bản kiểm theo `configs/models` bằng test, không FK (bước 3, R2.1; CLAUDE.md, Data model rules); cửa ngân sách là `RunBudgetMiddleware` lúc ticket này dựng, rồi `LimitsMiddleware` của usage-and-limits/03 thay nó như ADR-0118 (Accepted) quyết 1 nêu (bước 1).
