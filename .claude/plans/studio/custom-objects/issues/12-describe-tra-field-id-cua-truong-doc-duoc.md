# 12 — Describe trả `field_id` của mỗi trường người gọi đọc được

Status: ready-for-agent
Blocked by: 03, 06, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md
Area: studio
Yêu cầu: R3.1, R3.2, CO7

## Mục tiêu

`PUT /api/v1/admin/roles/{role_id}/permissions` nhận quyền trường theo `field_permissions[].field_id` (tenant-rbac:R9.13,
R9.14), mà không route công khai nào trả id của một trường: describe (R3.1) trả `object_id` của đối tượng và `api_name`
của trường, `GET /api/v1/admin/permissions` liệt kê khóa `obj.*` kèm `object_id` nhưng không khóa `fld.*` nào, và chi tiết
vai trò chỉ trả `field_id` của quyền trường vai trò đã có. Nên một người quản trị chỉ dùng API (lần gieo của
marketing-pilot/02, bước 3, R1.4) không đưa được `fld.mkt_lead.<trường>.read` vào vai trò nào; build lane của ticket đó
dừng ở đây (6/11/2026, đo trên API thật). Lát này cho describe trả thêm `field_id` cho mỗi trường người gọi đọc được
(`access` là `read` hay `edit`), còn trường Đã ẩn giữ đúng ba thuộc tính của R3.2 (CO7). Người cấp được một quyền trường
là người giữ chính khóa đó (tenant-rbac:R9.5, R6.1); chủ sở hữu công ty giữ mọi khóa `fld.*` (tenant-rbac:R9.7) và
`obj.*.read`, nên describe của chủ có id của mọi trường mà describe liệt kê (hai trường hệ thống `owner`, `workspace`
không có trong describe và field-security cũng không xét chúng), đủ cho lần gieo của marketing-pilot/02. Người giữ khóa `fld.*` mà
không giữ `obj.<api_name>.read` thì describe trả 403 (R3.4) và người đó không lấy được id qua API: ngoài lát này (Comments).

## Việc cần làm

Đọc ở `bb622179` (6/11/2026):

- `_description` (`packages/python/dw_studio/src/dw_studio/records/application/record_service.py:1125`) dựng mỗi trường
  từ `obj.definition.fields` và `obj.storage[api_name]`; `FieldStorage.field_id`
  (`packages/python/dw_studio/src/dw_studio/records/application/ports.py:42-45`) là id của dòng `studio.field_defs`, đã có
  trong tay ở đó. Trường Đã ẩn đi nhánh riêng (`record_service.py:1134`) chỉ với `api_name`, nhãn, `access`.
- `FieldView` (`packages/python/dw_studio/src/dw_studio/records/application/record_views.py:88`), `FieldOut` và
  `description_view` (`packages/python/dw_studio/src/dw_studio/records/presentation/views.py:168`, `:250`); route
  `GET /api/v1/studio/objects/{api_name}/describe` (`apps/api/src/dw_api/routes/v1/studio_records.py:113`) có
  `response_model_exclude_none=True`, nên thuộc tính `None` không có trong JSON.
- Chỗ tiêu thụ duy nhất của `Description` là route đó (không công cụ agent nào chiếu describe cho mô hình).

Việc:

1. `FieldView` thêm `field_id: uuid.UUID | None = None`; `_description` đặt `field_id=obj.storage[api_name].field_id` chỉ
   ở nhánh trường đọc được, nhánh Đã ẩn không đổi. Luật một câu cho mọi `action` của describe: `field_id` có mặt khi và
   chỉ khi `access` của trường trong chính câu trả lời đó khác `hidden`. Với `?action=create` (cửa là khóa
   `obj.<api_name>.create`, không `read`, R3.1), mức truy cập theo nhánh `create` của field-security như hôm nay, nên người
   chỉ giữ khóa `create` nhận `field_id` của các trường biểu mẫu tạo cho họ thấy: có chủ ý, id không phải bí mật mà
   R3.2 giấu ở trường Đã ẩn để lộ ít nhất (quyết định ở Comments).
2. `FieldOut` thêm `field_id: uuid.UUID | None = Field(default=None, description=...)`, mô tả: id của trường như
   `field_permissions[].field_id` của `PUT /api/v1/admin/roles/{role_id}/permissions` nhận; vắng ở trường Đã ẩn.
   `description_view` chuyển `field_id` ở nhánh đọc được; nhánh Đã ẩn giữ `FieldOut(api_name, label, access)`. Không thêm
   `field_id` vào JSON Schema của R3.6 hay vào `hidden_fields` của bản ghi.
3. `make generate-contracts` (ảnh chụp OpenAPI và kiểu TS); web không đổi (thuộc tính tùy chọn mới).
4. Test ở hai lớp, vì luật Đã ẩn nằm ở cả `_description` lẫn `description_view` và mỗi lớp cần một test đỏ được khi lớp
   đó hỏng (failure-modes #3, lần năm): (i) mức dịch vụ, một test mới trong
   `packages/python/dw_studio/tests/integration/test_record_service.py` gọi `RecordService.describe` cho người không có
   quyền trường `phone` và khẳng định `FieldView` của `phone` có `field_id` là `None` (giữ đột biến (a)), còn trường đọc
   được có `field_id` bằng `studio.field_defs.id`; (ii) mức trình bày, một test đơn vị mới
   `packages/python/dw_studio/tests/unit/test_description_view.py` dựng thẳng một `Description` có một `FieldView` Đã ẩn
   mang `field_id` (không qua dịch vụ) và khẳng định `FieldOut` của nó không có `field_id` (giữ đột biến (b)); (iii) mức
   HTTP, trong mục R3 của `apps/api/tests/integration/test_studio_records.py` (fixture của tệp gieo hai tenant A, B, mỗi
   tenant một `mkt_lead` phát hành thật cùng `api_name`, nên id của hai bên khác nhau): xem tiêu chí. Vế
   `PUT .../permissions` gieo dưới `dw_migrator` bằng `dw_platform.testing.rbac` (`role_id`, `assign`, `plant_role`) hai
   người giữ `tenant_owner` ở workspace `main` của A (người thứ hai để R7.3 có người xác nhận) và một vai trò đích; người
   gọi là một trong hai chủ, gọi describe dưới `X-Workspace-Id` của `main` rồi gửi `field_id` đọc được.
5. `reviewing-feature-security` (ranh giới 1, 2 và 6; 3, 4, 5 không áp: không bộ nhớ, công cụ hay nội dung mới),
   `mutations/12.yaml` một đột biến mỗi dòng ở cột "Đột biến" dưới đây có đột biến, không chạy `scripts/mutate.py` (lúc
   đóng hàng đợi). Độ trễ: không thêm câu truy vấn (id đã đọc cùng định nghĩa); đo P50/P95/P99 của describe lúc đóng hàng
   đợi (`.claude/rules/latency.md`).

Kiểm soát của ticket này (mã K chỉ dùng trong ticket):

| #   | Kiểm soát                                                      | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Đột biến (`mutations/12.yaml`)                                                                                                                                                                                                                                                                         |
| --- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| K1  | Trường Đã ẩn không lộ id (CO7, R3.2)                           | Mức dịch vụ: `RecordService.describe` cho người chỉ `read`, không quyền trường `phone` → `FieldView` của `phone` có `field_id` `None`. Mức HTTP: cùng người describe → `phone` đúng `{"api_name", "label", "access"}` (khẳng định có sẵn của `test_r3_1_r3_2_r3_7_co25_...`), và id của dòng `studio.field_defs` của `phone` (đọc dưới `dw_migrator`) không có ở đâu trong văn bản phản hồi; cùng với `?action=create` cho người chỉ giữ khóa `create` và một trường Đã ẩn ở nhánh `create` | (a) `_description` đặt `field_id` cả ở nhánh Đã ẩn (test mức dịch vụ đỏ; test HTTP vẫn xanh vì `description_view` bỏ nó); (b) nhánh Đã ẩn của `description_view` chuyển `field_id=f.field_id` (một tệp, `views.py`; test đơn vị của mức trình bày đỏ, test HTTP vẫn xanh vì `_description` đưa `None`) |
| K2  | Id chỉ của trường thuộc công ty người gọi (RB47)               | Người của B describe `mkt_lead` → mỗi trường đọc được mang `field_id` bằng id `studio.field_defs` của B cùng `api_name`, không id nào của A; một chủ của A gửi `PUT .../permissions` với một `field_id` lấy từ describe của B → 422 `validation_failed` với `errors[].pointer` tới phần tử, giống hệt một UUID ngẫu nhiên, 0 dòng đề xuất                                                                                                                                                   | Không đột biến riêng: id đọc từ định nghĩa dưới RLS của công ty đang gắn, và vế 422 là của tenant-rbac:R9.13 (RB47, ticket 04 có đột biến)                                                                                                                                                             |
| K3  | Người không giữ khóa mà describe hỏi không nhận id (R3.4, CO8) | Người của A không giữ `obj.mkt_lead.read` gọi describe → 403 `permission_denied`, thân lỗi không có `field_id`; người chỉ giữ `obj.mkt_lead.read` gọi `?action=create` → 403 (ca hồi quy của ticket 03, giữ trong tiêu chí R3.1)                                                                                                                                                                                                                                                            | Không đột biến riêng: cửa của R3.4 có trước ticket này (ticket 03), không đổi                                                                                                                                                                                                                          |

## Tiêu chí chấp nhận

- [ ] R3.1: một chủ của A describe `mkt_lead` → mỗi trường có `access` `read` hay `edit` mang `field_id` bằng id dòng
      `studio.field_defs` của A cùng `api_name` (so với dòng đọc dưới `dw_migrator`); gửi
      `{"field_permissions": [{"field_id": <id của phone>, "access": "read"}]}` tới `PUT /api/v1/admin/roles/{role_id}/permissions`
      với `If-Match` → 202 và một đề xuất mà `payload` mang đúng id đó; người của B describe → mỗi trường đọc được mang
      `field_id` bằng id dòng `field_defs` của B, không id nào của A, và id đó gửi vào `PUT .../permissions` của A → 422
      `validation_failed` có con trỏ, giống hệt UUID ngẫu nhiên, 0 dòng đề xuất (K2); người chỉ giữ khóa `create` gọi
      `?action=create` → mỗi trường biểu mẫu không Đã ẩn mang `field_id`; người không giữ khóa mà describe hỏi → 403,
      không `field_id` (K3). Sai nếu một trường đọc được thiếu `field_id`, id khác dòng `field_defs` của công ty người gọi,
      hay lần `PUT` của A không phải 202; ở commit gốc không trường nào có `field_id`.
- [ ] R3.2 (CO7): K1, ở mức dịch vụ `FieldView` của trường Đã ẩn có `field_id` `None`, ở mức HTTP trường Đã ẩn trả đúng
      `api_name`, `label`, `access` và id của nó không có trong văn bản phản hồi, ở describe thường và describe
      `?action=create`; sai nếu đột biến (a) (test mức dịch vụ) hay (b) (test đơn vị mức trình bày) của K1 vẫn xanh.
- [ ] Xong: `uv run python -m pytest packages/python/dw_studio/tests/unit/test_description_view.py packages/python/dw_studio/tests/integration/test_record_service.py apps/api/tests/integration/test_studio_records.py apps/api/tests/integration/test_record_privileges_api.py apps/api/tests/contract/test_openapi_snapshot.py` xanh.

## Nguồn

- `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:1125`, `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:1134`; spec: R3.1, R3.2, CO7.
- `packages/python/dw_studio/src/dw_studio/records/application/ports.py:42`; `packages/python/dw_studio/src/dw_studio/records/application/record_views.py:88`.
- `packages/python/dw_studio/src/dw_studio/records/presentation/views.py:168`, `packages/python/dw_studio/src/dw_studio/records/presentation/views.py:250`; `apps/api/src/dw_api/routes/v1/studio_records.py:113`.
- `apps/api/src/dw_api/routes/v1/admin_roles.py:98` (`FieldPermissionView.field_id`); `apps/api/src/dw_api/routes/v1/admin_console.py:93` (`object_id` của khóa `obj.*`).
- `apps/api/tests/integration/test_studio_records.py:577` (khẳng định Đã ẩn có sẵn); `apps/api/tests/integration/test_record_privileges_api.py:199` (R9.13).
- tenant-rbac: R6.1, R9.5, R9.7, R9.13, R9.14, RB47; marketing-pilot: R1.4; Quyết định 23/10/2026 của spec (R3.2 lộ ít nhất về trường Đã ẩn; `B:custom-objects:R6.5~field-security:R3.3`).

## Comments

- 2026-11-06 (agent, theo ủy quyền 31/10/2026): cắt từ phát hiện 1 của build lane marketing-pilot/02 (6/11/2026, đo trên
  API thật: describe, `/admin/permissions` và chi tiết vai trò không trả id trường nào). Chọn A (describe trả `field_id`
  của trường đọc được) thay B (`GET /api/v1/admin/permissions` liệt kê khóa `fld.*` kèm `field_id` như `obj.*` kèm
  `object_id`): B nhân danh mục lên hai khóa mỗi trường của mọi đối tượng ở cỡ D12 và cho người chỉ giữ
  `platform.roles.read` thấy tên mọi trường của mọi đối tượng, kể cả đối tượng họ không đọc; A chỉ cho id của trường
  người gọi đã đọc được, mà người cấp được quyền trường thì phải giữ khóa đó (tenant-rbac:R9.5), nên không thiếu id nào
  cần cho một lần cấp hợp lệ. Văn bản R3.1 chưa nêu `field_id`: dòng Quyết định cùng ngày của spec ghi phần thêm này,
  người sửa spec kế tiếp qua `writing-plan-specs` thêm `field_id` vào danh sách của R3.1. Nếu sai thì: B, một khóa
  `fld.<object>.<field>.<access>` mỗi dòng của `/admin/permissions` với `field_id`, lọc theo `obj.<object>.read` của người
  gọi; describe không đổi.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk một
  subagent, ranh giới 1, 2, 6; 3, 4, 5 không áp). Một HIGH, sửa ở ticket: (1) đột biến (a) của K1 không đỏ được bằng test
  HTTP, vì nhánh Đã ẩn của `description_view` bỏ `field_id` mà `_description` đặt: thêm test mức dịch vụ trong
  `packages/python/dw_studio/tests/integration/test_record_service.py` và đưa tệp đó vào dòng `Xong`. MEDIUM, sửa: (2)
  `?action=create` cho người chỉ giữ khóa `create` nhận `field_id` của trường biểu mẫu họ thấy, có chủ ý (bước 1); K3 đổi
  thành "không giữ khóa mà describe hỏi". Nếu sai thì: `?action=create` không trả `field_id`, chỉ describe thường. (3)
  Mục tiêu bỏ câu "không thiếu id nào": người giữ `fld.*` mà không giữ `obj.<api_name>.read` không lấy được id qua API
  (R3.4 trả 403), ngoài lát này, không chặn marketing-pilot/02 vì chủ giữ cả hai. (4) R3.3 dùng lệch nghĩa (404 của đối
  tượng công ty khác): K2 gộp vào tiêu chí R3.1 và khẳng định có mặt id của B, nên đỏ ở commit gốc; bỏ R3.3 khỏi Yêu cầu.
  LOW, sửa: (5) tiêu chí R3.4 đúng sẵn ở commit gốc: gộp vào R3.1, bỏ R3.4, CO8 khỏi Yêu cầu. `Blocked by` thêm 06 (đối
  tượng phát hành qua vòng đời là nguồn của `studio.field_defs` mà test đọc). MEDIUM, không sửa, người dựng đọc trước:
  (a) `GET /api/v1/admin/roles/{role_id}` trả `field_permissions[].field_id` cho người giữ `platform.roles.read`, kể cả id
  của trường người đó không đọc được: id không phải bí mật (tên trường Đã ẩn đã công khai,
  `B:custom-objects:R6.5~field-security:R3.3`), K1 giữ R3.2 "lộ ít nhất" ở describe chứ không làm id thành bí mật; chủ
  của route đó là tenant-rbac. (b) Cặp không đường phụ thuộc mà script báo chạm `studio.field_defs`: 07 và 08
  (`ready-for-human`, đo D12 và DDL của `studio.records`) đổi lược đồ hay dữ liệu đo, 12 chỉ đọc cột `id` qua định nghĩa đã
  nạp, không đổi bảng, route chung, migration, config hay prompt; 05 (`ready-for-agent`, web) đọc describe, 12 thêm một
  thuộc tính tùy chọn và tái sinh kiểu TS, 05 không đổi route. Không chạy song song với tenant-rbac/16 (cả hai đổi ảnh
  chụp OpenAPI). (c) Người giữ khóa neo ở workspace khác: gọi describe dưới `X-Workspace-Id` của workspace neo (họ có
  membership ở đó vì lần gán neo ở đó).
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (người đọc mới). Một HIGH, sửa ở ticket: (1) đột biến (b)
  của K1 như đã viết sửa hai tệp, `scripts/mutate.py` nhận một tệp mỗi đột biến, và bản một tệp ở `views.py` không test
  nào giết được (`FieldView` Đã ẩn luôn mang `None`, JSON bỏ `None`): thêm test đơn vị mức trình bày
  `packages/python/dw_studio/tests/unit/test_description_view.py` dựng thẳng `Description`, (b) thành đột biến một tệp ở
  nhánh Đã ẩn của `description_view`, tệp vào dòng `Xong`. MEDIUM, không sửa: (2) văn bản R3.1 và CO7 của spec chưa nêu
  `field_id`; dòng Quyết định 6/11/2026 giữ tới lần sửa spec kế tiếp qua `writing-plan-specs` (lane gate chỉ ghi dòng
  đó). LOW, sửa: (3) "mọi trường" thành mọi trường describe liệt kê (không `owner`, `workspace`). Sửa sau lượt này không
  được người đọc mới đọc lại (hai lượt mỗi phiên bản); người dựng đọc bước 4 và cột "Đột biến" của K1 trước.
- 2026-11-06 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
