# 14 — Runtime quy trình: rào lease trong saver, độ trễ đánh thức, công bằng, allowlist checkpoint, bản kê lượt chạy

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-56 `runtime-mechanics`, FOG-37 `checkpoint-allowlist`, FOG-59 `run-manifest-cost`

## Câu hỏi

1. Saver có rào được lần ghi của bên giữ lease đã cũ ngay trong `aput` và `aput_writes`, không thêm một lượt đi về
   không (FOG-56)?
2. p95 từ lúc endpoint Data Hub trả 2xx tới bước đầu tiên khi dồn tải, với đánh thức bằng NOTIFY (FOG-56)?
3. Hàng outbox FIFO có làm trigger bản ghi của công ty khác chờ sau một lần nhập 100.000 bản ghi không (FOG-56)?
4. Chạy tách từ bước gieo bằng `aupdate_state(as_node=...)` sau một bước map và một điểm nối có đúng không (FOG-56)?
5. Allowlist msgpack tường minh nào đủ cho các kiểu state checkpoint thật của nền tảng dưới langgraph-checkpoint 4.2.0
   (`uv.lock:2091`); checkpoint và lịch sử chạy chỉ giữ tham chiếu bản ghi, hay chiếu lại khi đọc (FOG-37)?
6. Dựng và ghi bản kê lượt chạy lúc nhận run (đi closure, JCS, hai lệnh insert) tốn bao nhiêu ở khối lượng Studio, và
   dựng lại ảnh đã ghim khi resume ở tiến trình khác tốn bao nhiêu (FOG-59)?

## Vì sao

Công bằng giữa các công ty và hiệu ứng đúng một lần phụ thuộc câu 1-4. Allowlist quá chặt làm hỏng resume, quá lỏng
giữ rủi ro giải tuần tự; giá trị bản ghi lưu trong checkpoint đi vòng qua bảo mật trường. Câu 6 đặt ngân sách độ trễ
lúc nhận run và chứng minh resume được ở bất kỳ tiến trình nào.

## Mở khóa

- Spec: `workflow-engine` (03, 04, 05), `workflow-triggers` (02), `foundations-hardening` (02, checkpoint an toàn),
  `field-security` (02), `tenant-config` (04, bản kê lượt chạy).
- ADR: 0109, 0112 (Open 5), 0113, 0106.
- DO: DO-05, DO-41. Ticket W1: `foundations-hardening/02` (allowlist checkpoint), `workflow-engine/04`.

## Dựng tối thiểu

Một làn `studio_runs` nguyên mẫu trên PostgreSQL: bảng run có lease, saver bọc có rào, NOTIFY để đánh thức, hai công ty
giả lập (một nhập 100.000 bản ghi, một gửi sự kiện), một quy trình map rồi nối; chạy với langgraph 1.2.11
(`uv.lock:2074`) và langgraph-checkpoint 4.2.0 của repo.

## Phép đo quyết định

| Đo                                                          | Ngưỡng                                                                          | Quyết định                         |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------- |
| Resume ở worker khác; số lần nhà cung cấp nhận một tác động | YC41: ≤ 90 giây, đúng 1 lần, không chờ sau 10.000 lượt đang xếp của một công ty | Rào trong saver hay một bước riêng |
| 2xx tới bước đầu khi dồn tải                                | YC44 và KQ8: 2xx p95 ≤ 1 giây; YC100: tiếp nhận p95 ≤ 60 giây (W2)              | NOTIFY đủ hay cần thêm             |
| Trigger của công ty khác sau lần nhập lớn                   | Không bị chặn sau hàng của công ty kia                                          | Outbox FIFO chung hay theo công ty |
| Resume với allowlist                                        | Mọi kiểu state thật qua; kiểu lạ bị từ chối                                     | Nội dung allowlist                 |
| Bản kê lượt chạy lúc nhận và khi resume                     | Chưa có ngưỡng; ghi p95                                                         | Ngân sách lúc nhận run             |

## Nguồn

- Brief B4, B6 (F2), B7a, B11.
- [research.md](../research.md) mục 4 và 5 (rào lease trong saver, allowlist msgpack chưa kiểm).

## Comments
