# 10 — Kiểm trùng lead và sự tồn tại dưới RLS: chuẩn hóa số điện thoại, trường duy nhất, upsert theo từng lệnh

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-11 `dedupe-phone`, FOG-42 `upsert-under-rls`

## Câu hỏi

1. Kiểm trùng chính xác tới đâu sau khi chuẩn hóa số điện thoại Việt Nam (số 11 chữ số cũ, `+84`, nhiễu định dạng);
   thư viện `phonenumbers` có hợp không (giấy phép, kích thước, đợt đổi đầu số 2018) (FOG-11)?
2. Trường `phone_e164` duy nhất có thành cách dò sự tồn tại cho một vai trò không đọc được số điện thoại không
   (FOG-11)?
3. `INSERT ... ON CONFLICT DO UPDATE` và `UPDATE ... RETURNING` chạy thế nào dưới policy quyền trên bản ghi theo từng
   lệnh (policy SELECT áp cho cả dòng có sẵn và dòng mới), khi nhập và kiểm trùng (FOG-42)?

## Vì sao

Gộp nhầm làm mất lead; một cách dò tồn tại làm lộ dữ liệu cá nhân qua bảo mật trường; nhập và kiểm trùng có thể hỏng
trong im lặng hoặc lộ sự tồn tại của bản ghi không đọc được.

## Mở khóa

- Spec: `marketing-pilot` (01, 03), `custom-objects` (03: trường duy nhất và upsert, trên đường găng),
  `workflow-nodes` (hàm `phone.e164`), `record-access` (tính duy nhất).
- ADR: 0105 (Open 3), 0107 (Open 3).
- DO: DO-35 (chấp nhận cách dò tồn tại là rủi ro còn lại, với lỗi chung, giới hạn theo người và audit).
- Ticket W1: `marketing-pilot/01` (P0) đo câu 1; `custom-objects/03` dựng upsert theo câu 3.

## Dựng tối thiểu

Bộ sinh lead giả lập có hạt giống của `marketing-pilot/01` với nhiều dạng số; chuẩn hóa bằng `phonenumbers`; một vai
trò không có quyền trường số điện thoại thử tạo Lead trùng số. Câu 3 chạy trên bộ policy nguyên mẫu của ticket 05, nên
làm sau khi ticket 05 dựng xong policy; câu 1 không phải chờ.

## Phép đo quyết định

| Đo                                          | Ngưỡng                                                                | Quyết định                                |
| ------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------- |
| Trùng lọt; gộp nhầm                         | KQ3: ≤ 1%; 0. YC95: "0901 234 567" và "+84901234567" là một Lead      | Khóa kiểm trùng của quy trình             |
| Phản hồi khi vai trò không đọc số tạo trùng | Lỗi chung, không nêu bản ghi trùng; có audit                          | Giữ DO-35 hay thu hẹp trường duy nhất     |
| Upsert dưới policy theo từng lệnh           | Không ghi lọt, không lộ dòng không đọc được; test âm đỏ khi bỏ policy | Upsert trong `RecordService` dựng thế nào |

## Nguồn

- Brief B4, B7b, B12.
- [research.md](../research.md) mục 2 (upsert dưới policy theo từng lệnh chưa kiểm).

## Comments
