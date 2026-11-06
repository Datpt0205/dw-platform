# Thuê bao của công ty: gói, kỳ, hạn và đối soát

Status: needs-triage
Area: go-live · Nhánh: `main` · Viết: 6/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người vận hành cần ghi mỗi công ty đang thuê gói nào tới ngày nào và lấy được số để lập hóa đơn, còn chủ sở hữu cần thấy hạn dùng, vì khách trả tiền ngoài hệ thống nhưng dịch vụ phải biết ai đang còn hạn.

## Hiện trạng (đã kiểm ở `6fe88f7b` ngày 6/11/2026)

- `platform.entitlements` chỉ gắn công ty với một `plan_id` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:431`). Thiếu: không có kỳ, hạn hay giá.
- `platform.plans` chỉ còn `plan_id`, `name`, `features`; các số nằm ở `platform.plan_limits` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:323`). Thiếu: chưa có giá bán.
- `LimitsPort` đã kiểm `plan_limits.cost_usd_per_month` (`packages/python/dw_usage/src/dw_usage/domain/limits.py:69`), nhưng cột này rỗng ở cả ba gói (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:331`). Thiếu: trần chi phí của gói chưa có số.
- Một lần từ chối không có `resets_at` kết thúc mọi loại lượt (`packages/python/dw_agent_runtime/src/dw_agent_runtime/studio_dispatch.py:197`). Ràng buộc: hết hạn thuê bao không thể là một từ chối trần, nếu không lượt do sự kiện sẽ hỏng thay vì chờ.
- Hạng mục của DW đi lane `dw_work`, gặp giới hạn thì về `open` năm phút (`apps/worker/src/dw_worker/consumers/dw_work.py:72`). Ràng buộc: lead không mất, nhưng trạng thái không phải `queued`.
- `PlanEntitlementService` trả lời có tính năng hay không (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:12`). Ràng buộc: entitlement và authorization là hai việc riêng theo `CLAUDE.md`.
- Người vận hành khóa được một công ty (`apps/api/src/dw_api/routes/v1/platform.py:203`). Ràng buộc: khóa là thao tác an toàn của người, không phải hết hạn thuê bao.

## Mục tiêu

### R1 — Sổ thuê bao

Người vận hành ghi hợp đồng của mỗi công ty.

- R1.1 KHI người vận hành ghi một kỳ, nền tảng PHẢI lưu gói, ngày bắt đầu, ngày hết hạn, giá theo tháng và mã hợp đồng.
- R1.2 NẾU hai kỳ của một công ty chồng ngày nhau, THÌ nền tảng PHẢI trả 409 `subscription_period_overlap` và không đổi gì.
- R1.3 NẾU người gọi không phải `platform_operator`, THÌ nền tảng PHẢI trả 403 và không đổi gì.
- R1.4 KHI một kỳ được ghi hay sửa, nền tảng PHẢI ghi audit với người làm, giá trị cũ và giá trị mới.
- R1.5 KHI ghi một kỳ cho gói khác gói hiện tại, `platform.entitlements` PHẢI đổi sang gói đó trong cùng giao dịch.

### R2 — Hết hạn

Công ty hết hạn không chạy lượt mới, và không mất gì.

- R2.1 TRONG KHI hôm nay nằm trong một kỳ, công ty PHẢI ở trạng thái thuê bao `active`.
- R2.2 TRONG KHI đã qua ngày hết hạn không quá 14 ngày, công ty PHẢI ở trạng thái `grace` và lượt chạy vẫn được bắt đầu.
- R2.3 TRONG KHI đã qua ngày hết hạn hơn 14 ngày, hoặc công ty chưa có kỳ nào, công ty PHẢI ở trạng thái `expired`.
- R2.4 TRONG KHI công ty ở `expired`, `LimitsPort` PHẢI từ chối lượt tương tác với `subscription_expired`.
- R2.5 TRONG KHI công ty ở `expired`, nền tảng PHẢI cho đọc và xuất dữ liệu của công ty.
- R2.6 KHI người vận hành ghi kỳ mới bao phủ hôm nay, lượt đang giữ PHẢI chạy tiếp mà không cần thao tác nào khác.
- R2.7 TRONG KHI công ty ở `expired`, lượt `datahub`, `provider_app` và `record_event` PHẢI chờ trong hàng đợi, kèm một `resets_at` để lane kiểm lại.
- R2.8 TRONG KHI công ty ở `expired`, lần chạy theo lịch PHẢI ghi `limit_refused` và bị bỏ qua, không dồn lại.
- R2.9 TRONG KHI công ty ở `expired`, hạng mục của Digital Worker PHẢI về `open` và không mất.
- R2.10 TRONG KHI công ty ở `expired`, `admit_operation` PHẢI từ chối lời gọi model ngoài lượt.

### R3 — Chủ sở hữu thấy hạn

Chủ sở hữu không bị bất ngờ.

- R3.1 Trang sử dụng PHẢI hiện gói, ngày hết hạn, trạng thái thuê bao và mức đã dùng so với trần của gói.
- R3.2 KHI còn 14, 7 và 1 ngày tới ngày hết hạn, nền tảng PHẢI gửi thông báo cho chủ sở hữu.
- R3.3 NẾU người gọi không giữ quyền xem sử dụng của công ty, THÌ route PHẢI trả 403.

### R4 — Trần chi phí của gói

Chi phí AI không vượt giá gói. Dùng `plan_limits.cost_usd_per_month` có sẵn, không thêm cột.

- R4.1 NẾU gói của kỳ đang ghi có `cost_usd_per_month` rỗng, THÌ nền tảng PHẢI trả 409 `plan_ceiling_missing` và không đổi gì.
- R4.2 Migration của spec này PHẢI đặt `cost_usd_per_month` cho cả ba gói bằng số Đạt chốt ở `operator-tasks/01`.

### R5 — Đối soát theo tháng

Kế toán có số để lập hóa đơn tay.

- R5.1 KHI người vận hành xuất đối soát một tháng, nền tảng PHẢI trả một dòng mỗi công ty với gói, giá, số lượt và chi phí AI theo sổ sử dụng.
- R5.2 Bảng đối soát PHẢI ghi rõ là sổ đo lường, không phải chứng từ hóa đơn.

## Trong phạm vi

- Bảng `platform.subscriptions`, giá trị `plan_limits.cost_usd_per_month`, trạng thái thuê bao, route người vận hành, thẻ thuê bao ở `apps/web/app/usage`, cột thuê bao ở `apps/web/app/platform`.

## Ngoài phạm vi

| Việc                        | Vì sao                              | Chủ                      |
| --------------------------- | ----------------------------------- | ------------------------ |
| Cổng thanh toán             | Quyết định của `requirements.md`    | đợt sau                  |
| Hóa đơn điện tử             | Kế toán lập tay ở khách đầu         | đợt sau                  |
| Số giá thật                 | Đạt chốt                            | `go-live/operator-tasks` |
| Xóa dữ liệu khi hết hạn lâu | Offboarding là quyết định của người | `studio`, đợt sau        |

## Dữ liệu

- `platform.subscriptions`: `id uuid`, `tenant_id uuid` (FK `ON DELETE CASCADE`, chỉ mục riêng), `plan_id text` (FK `ON DELETE RESTRICT`, chỉ mục riêng), `starts_on date`, `ends_on date` với CHECK `ends_on >= starts_on`, `monthly_price_vnd bigint` với CHECK `>= 0`, `contract_ref text` độ dài 1-120, `created_by uuid`, `created_at timestamptz`, `updated_at timestamptz` theo trigger nhường giá trị câu lệnh nêu. EXCLUDE theo `tenant_id` trên `daterange(starts_on, ends_on, '[]')`. RLS ENABLE, FORCE; policy tenant; `dw_app` chỉ SELECT; người vận hành ghi qua `dw_provisioner`. Là bảng cấp công ty, liệt kê lý do ở `test_rls_coverage.py`.
- Trạng thái thuê bao không lưu: `platform.subscription_state(tenant_id, today)` là một chủ duy nhất, cả `LimitsPort` lẫn route đọc nó, ngày theo `Asia/Ho_Chi_Minh`.
- `dw_provisioner` chưa có quyền đọc `usage_daily`; migration cấp `SELECT` cho nó để R5.1 đọc được, kiểm ở `test_privileges.py`. Bảng mới cấp quyền tường minh trong migration.

## API

- `GET /api/v1/platform/tenants/{tenant_id}/subscriptions`, `POST` cùng đường, `PATCH .../{subscription_id}`: `RequireProvisioningContext`.
- `GET /api/v1/platform/billing-statement?month=YYYY-MM`: `RequireProvisioningContext`, CSV.
- `GET /api/v1/usage/subscription`: quyền xem sử dụng của công ty.

## Màn hình

- `apps/web/app/platform`: cột "Hạn thuê bao", ngăn ghi kỳ.
- `apps/web/app/usage`: thẻ gói, hạn, trạng thái, mức dùng; trạng thái `grace` và `expired` có thông báo rõ. Theo design v3, token của `@dw/ui`.

## Kiểm soát

| #    | Kiểm soát                                      | Yêu cầu    | Test âm                                                                                                                         |
| ---- | ---------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------- |
| TS1  | Hai kỳ không chồng ngày, kể cả ghi đồng thời   | R1.2       | Hai kết nối ghi kỳ chồng; một bên 409 theo EXCLUDE; gỡ ràng buộc thì cả hai qua, đỏ                                             |
| TS2  | Chỉ người vận hành ghi kỳ                      | R1.3       | Chủ sở hữu gọi POST; 403, 0 dòng; `dw_app` INSERT thẳng bị từ chối; gỡ kiểm thì đỏ                                              |
| TS3  | Công ty này không đọc kỳ của công ty khác      | R3.3       | Token công ty B đọc của A và đọc thẳng bảng dưới `dw_app`; 0 dòng; gỡ policy thì đỏ                                             |
| TS4  | Hết hạn chặn ở cửa bắt đầu lượt, không ở API   | R2.7, R2.9 | Lượt do sự kiện giữ hàng đợi và hạng mục DW về `open`; gỡ kiểm trong runner thì chạy, đỏ; mất `resets_at` thì lượt `failed`, đỏ |
| TS9  | Lịch không dồn sau khi hết hạn                 | R2.8       | Lịch chạy của công ty `expired` ghi `limit_refused`; gia hạn không tạo lượt dồn; gỡ kiểm thì đỏ                                 |
| TS10 | Lời gọi model ngoài lượt cũng bị chặn          | R2.10      | Nạp tri thức của công ty `expired`; từ chối, 0 lời gọi; gỡ kiểm thì gọi, đỏ                                                     |
| TS5  | Chưa có kỳ nào là `expired`, không mở mặc định | R2.3       | Công ty không có dòng nào; trạng thái `expired`; đổi mặc định thành `active` thì đỏ                                             |
| TS6  | Hết hạn không xóa, không khóa đọc              | R2.5       | Công ty `expired` đọc và xuất được; thêm chặn đọc thì đỏ                                                                        |
| TS7  | Gói không trần không ghi kỳ được               | R4.1       | Ghi kỳ cho gói có trần rỗng; 409, 0 dòng; gỡ kiểm thì ghi, đỏ                                                                   |
| TS8  | Một chủ của trạng thái thuê bao                | R2.1       | Quét nguồn: không nơi nào khác tính từ `ends_on`; thêm một phép so ngày thì đỏ                                                  |

## Tiêu chí thành công

- Góp vào KQ1 và KQ5 của `requirements.md`.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` xanh; ảnh hai màn hình sáng, tối, desktop và dưới 992px ở Comments.

## Phụ thuộc

- `LimitsPort` (ADR-0113 (Accepted), ADR-0121 (Accepted)): nơi duy nhất từ chối lượt.
- Sổ sử dụng của `studio/usage-and-limits`: nguồn của mức dùng và đối soát.
- Kiểm lại khi: đổi cách đóng gói của DO-59 → R1, R4.

## Câu hỏi còn mở

## Quyết định

- 6/11/2026 (agent, tạm): Hạn cho phép sau ngày hết hạn là 14 ngày, không phải ngày tắt. Sửa: R2.2, R2.3. Nếu sai thì: đổi một hằng ở `platform.subscription_state` bằng một revision.
- 6/11/2026 (agent, tạm): Công ty `expired` không bị `lock`, để lượt do sự kiện giữ hàng đợi thay vì mất, theo luật "waits in the queue, never dropped" của `CLAUDE.md`. Nếu sai thì: hết hạn gọi `lock` của người vận hành.
- 6/11/2026 (agent, tạm): Giá ghi theo VND, sổ sử dụng giữ USD như hiện có; bảng đối soát hiện cả hai và không tự quy đổi. Nếu sai thì: thêm tỷ giá vào `price_book`.
- 6/11/2026 (agent, tạm): Công ty có sẵn trên production lúc áp migration không có; migration không tự gieo kỳ nào. Nếu sai thì: revision gieo một kỳ thử.
- 6/11/2026 (agent, tạm): `eval` và lượt con không qua `admit`, nên không bị chặn riêng: lượt con theo lượt cha, eval do người vận hành. Nếu sai thì: thêm kiểm ở hai cửa đó.

## Danh sách ticket
