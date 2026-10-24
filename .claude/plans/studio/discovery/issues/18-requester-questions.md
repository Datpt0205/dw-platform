# 18 — Hỏi bên yêu cầu: gateway LiteLLM hiện có, Page và OA dùng chung giữa hai công ty

Type: grilling
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-18 `requester-gateway`, FOG-07 `shared-accounts`

## Câu hỏi

1. Gateway LiteLLM hiện có của bên yêu cầu: ai vận hành, bản nào, có database không, log request nằm ở đâu, cấu hình
   cache ra sao, có kéo gì về trong cửa sổ sự cố 21/10/2026 không (FOG-18)?
2. Với từng alias model sau gateway đó: gateway gọi lên nhà cung cấp nào, và model được xử lý ở Việt Nam hay nước ngoài?
   Câu này cũng trả phần "gateway đi ra đâu" của FOG-10 (ticket 19).
3. Có trường hợp thật hai công ty nối cùng một Page hay OA (agency và khách của agency) không; có khách nào cần hủy bí
   mật của riêng một workspace, tức xóa bằng hủy khóa theo workspace, không (FOG-07)?

D13 (23/10/2026) đã trả phần "gateway có là đường BYOM không": không; model của tenant đi qua model proxy riêng, gateway
hiện có chỉ phục vụ model của nền tảng. Câu 1-3 còn mở.

## Vì sao

Gateway có thể giữ bản sao thứ hai của prompt ngoài thời hạn lưu giữ của nền tảng, nên là một kho dữ liệu cá nhân trong
sổ xử lý. Nơi xử lý theo alias quyết lộ trình dữ liệu; alias chưa khai coi là nước ngoài (D13). Câu 3 quyết gửi tới cả
hai hay từ chối, và cây khóa có cần khóa theo workspace không.

## Mở khóa

- Spec: `model-connections`, `compliance-pdpl` (03, lộ trình dữ liệu; sổ xử lý), `usage-and-limits` (đối soát chi
  phí), `connections-and-vault` (định tuyến sự kiện nhận, cây khóa), `telemetry-and-audit`.
- ADR: 0118 (Open 1), 0123, 0115.
- DO: DO-19 (D13), DO-48 (Đạt chốt 23/10/2026: gửi tới cả hai, luật sư xác nhận), DO-54.

## Đầu ra

- Bảng alias: alias, nhà cung cấp, nơi xử lý (VN hay nước ngoài), ai trả lời và ngày; ghi vào ADR 0118 (Open 1).
- Nơi giữ log và cache của gateway chuyển sang bản kiểm kê kho dữ liệu cá nhân của ticket 26.
- Câu 3: số trường hợp và loại khách, không ghi tên người hay tên khách.

## Nguồn

- Brief B1, B8a (F11, F12), B9, B11.
- [research.md](../research.md) mục 9 (gateway hiện có của bên yêu cầu là gì: chưa kiểm).

## Comments
