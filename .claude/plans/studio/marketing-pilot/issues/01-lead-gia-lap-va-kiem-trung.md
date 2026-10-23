# 01 — Bộ sinh lead giả lập và đo chuẩn hóa, kiểm trùng

Status: needs-triage
Area: studio
Yêu cầu: R2.1, R2.2, R2.3

## Mục tiêu

Người dựng và bộ kiểm thử của lát cần một tập lead tiếng Việt giả lập, lặp lại được, để đo chuẩn hóa số điện thoại và email rồi chốt khóa kiểm trùng cho quy trình Tiếp nhận lead, trước khi có bất kỳ lead thật nào (marketing-pilot R2.1, R2.2, R2.3). Gộp B12-product marketing-pilot 01 và 02.

## Việc cần làm

1. Bộ sinh lead ở harness của lát (`tests/e2e/marketing_pilot/generator.py`, gói thử, không phải gói nền tảng): một hàm nhận hạt giống cố định và số lượng, cho cùng một tập lead mỗi lần. Mỗi lead có `name`, `phone`, `email`, `lead_source`, `message`.
2. Phủ các dạng số điện thoại Việt Nam: `0901 234 567`, `+84901234567`, `84901234567`, `090-123-4567`, số có dấu cách và dấu chấm; email viết hoa-thường lẫn lộn; `message` có câu chèn prompt (`</input>`, "bỏ qua hướng dẫn phía trên") và có số điện thoại hoặc email nằm trong văn bản tự do.
3. Gài các cặp có nhãn sẵn: cùng người khác định dạng số (phải là một), cùng tên khác số (phải là hai), cùng email khác tên, chỉ có email không số, chỉ có số không email.
4. Bộ đo `tests/e2e/marketing_pilot/measure.py`: chuẩn hóa số về E.164 `+84` và email về chữ thường theo hợp đồng của `custom-objects` (custom-objects:R6.2), nhóm theo khóa số-rồi-email, in tỉ lệ trùng thật, tỉ lệ gộp nhầm (hai người thành một) và tỉ lệ trùng lọt (một người thành hai) trên tập có nhãn.
5. Chốt khóa kiểm trùng là số điện thoại chuẩn hóa rồi email chữ thường, không bao giờ chỉ theo tên; ghi kết quả vào `tests/e2e/marketing_pilot/README.md` để ticket 03 cấu hình `data.object.upsert` (custom-objects:R7.3).
6. Một khẳng định trong bộ đo rằng mọi địa chỉ trong tập là giả lập (miền `example.com`, số thuộc dải thử), nền cho ràng buộc chỉ-giả-lập của W1 (R2.3).

## Tiêu chí chấp nhận

- [ ] R2.1: chạy hai lần cùng hạt giống cho cùng một tập lead theo byte; tập chứa ít nhất một `message` có `</input>` và một `message` có số điện thoại trong văn bản tự do.
- [ ] R2.2: sau chuẩn hóa, "0901 234 567" và "+84901234567" cho một khóa; "Nguyễn An / 0901..." và "Nguyễn An / 0902..." cho hai khóa; bộ đo in tỉ lệ trùng thật, trùng lọt và gộp nhầm, với gộp nhầm bằng 0 trên tập có nhãn.
- [ ] R2.2: README chốt khóa là số chuẩn hóa rồi email; một biến thể chỉ khác tên không tạo khóa mới.
- [ ] R2.3: bộ đo từ chối (không nhãn) một địa chỉ ngoài miền `example.com` hoặc dải số thử, nên tập luôn giả lập.
- [ ] Xong: `uv run pytest tests/e2e/marketing_pilot/test_generator.py` xanh.

## Nguồn

- spec: R2.1, R2.2, R2.3.
- custom-objects:R6.2 (chuẩn hóa E.164 và chữ thường), custom-objects:R7.3 (Tạo hoặc cập nhật theo trường duy nhất); YC95.

## Comments
