# 02 — `ModelResolver` theo công ty, `ModelProfile` v2, `plan_model_profiles`

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5

## Mục tiêu

Thay ba chỗ đọc hồ sơ lệch nhau bằng một `ModelResolver` theo công ty trả lời mọi cửa model, lọc hồ sơ theo gói, ghim route vào bản kê và mang trường tuyến dữ liệu. Chứng minh R1, R2, R3 của spec và cài MR1–MR5. Nền móng chạy được ngay, không chờ BYOM.

## Việc cần làm

1. Dựng `ModelResolver` làm nguồn route duy nhất cho `StudioModelSelection`, `RunBudgetMiddleware`, `LangchainUsageMeter`, `RoutingModelGateway` và nén ngữ cảnh; P1 đọc lớp nền tảng lọc theo gói (lớp công ty khi `tenant-config` có phiên bản cấu hình), phân giải rơi về nền tảng, không bao giờ sang công ty khác (mẫu `test_tenant_overlay.py`).
2. `ModelProfile` v2: thêm số phiên bản, cờ năng lực `strict_tools`, `max_strict_tools`, `numeric_bounds`, và trường `data_location`, `processor`, `retention_days`, `no_training` (không mặc định); đổi giá sang số thập phân dạng chuỗi; giá vẫn đọc qua một hàm mà ticket bảng giá của `usage-and-limits` thay. Thực hiện trường tuyến dữ liệu cùng một thay đổi với ticket của `compliance-pdpl`.
3. Migration `platform.plan_model_profiles` (revision hex): cột `plan_id`, `profile_id`, khóa chính tổng hợp `(plan_id, profile_id)`; RLS lớp nền tảng; FK `ON DELETE` tường minh và chỉ mục; grant cho `dw_app`, `dw_agent_ro`; tên ràng buộc theo `NAMING_CONVENTION`.
4. `make check-model` thăm dò mỗi route nền tảng và so sánh cờ năng lực khai với kết quả thăm dò, chênh thì báo lỗi và CI đỏ; `tools-and-skills` đọc `strict_tools`, `max_strict_tools`, `numeric_bounds`.
5. Ghim route đã phân giải vào bản kê lượt chạy lúc nhận lượt; đọc route cho mọi lời gọi trong lượt từ bản kê, không phân giải lại giữa lượt.

## Tiêu chí chấp nhận

- [ ] R1.1 (MR1): mọi cửa model (chọn, ngân sách, đo, gateway, nén, giám khảo) trả cùng route cho một công ty có hồ sơ riêng; một cửa bỏ `tenant_id` → test đỏ.
- [ ] R1.2: hai cửa model bất kỳ trả cùng route cho một công ty có hồ sơ riêng; sai nếu hai cửa trả khác nhau.
- [ ] R1.3 (MR2): công ty A hỏi hồ sơ mà chỉ công ty B có bản riêng nhận hồ sơ nền tảng, không bao giờ bản của B; gỡ bước rơi về nền tảng → test đỏ.
- [ ] R1.4 (MR4): hồ sơ đổi giữa một lượt chạy không đổi route đã ghim trong bản kê; gỡ đọc route từ bản kê → test đỏ.
- [ ] R2.1: bộ phân giải chỉ trả hồ sơ mà gói của công ty cho phép; sai nếu trả hồ sơ ngoài gói.
- [ ] R2.2 (MR3): lượt chạy xin hồ sơ ngoài danh sách gói nhận `model_profile_unavailable` và không gọi model; gỡ lọc gói → test đỏ.
- [ ] R2.3: `ModelProfile` v2 mang số phiên bản, `strict_tools`, `numeric_bounds`, `data_location`, `processor`; sai nếu thiếu một trường.
- [ ] R2.4: `ModelProfile` biểu diễn giá bằng số thập phân dạng chuỗi; sai nếu còn số thực dấu phẩy động.
- [ ] R2.5: `make check-model` báo lỗi khi một cờ năng lực khai khác kết quả thăm dò; sai nếu chênh mà vẫn xanh.
- [ ] R3.1 (MR5): một YAML hồ sơ nền tảng thiếu `data_location` làm bộ nạp từ chối và CI đỏ; gỡ kiểm `data_location` → test đỏ.
- [ ] R3.2 (MR5): một alias không khai `data_location` được coi là nước ngoài; sai nếu coi là trong nước.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "model_resolver or model_profile" && make check-model` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py:62`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:138`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:113`; `apps/api/src/dw_api/bootstrap/runtime.py:117`; spec: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5.

## Comments
