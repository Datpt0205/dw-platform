# 04 — Nhà cung cấp kênh của thí điểm: Zalo OA và ZNS, Meta Lead Ads, Google

Type: research
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-04 `zalo-zns`, FOG-05 `meta-google`, FOG-79 `lock-retries`

## Câu hỏi

1. Zalo OA v4 trên một OA thật: thời hạn token, refresh dùng một lần, một cặp token cho mỗi ứng dụng và OA, công thức
   `X-ZEvent-Signature`, thu hồi, API nào cần OA trả phí (FOG-04)?
2. ZNS: có chế độ phát triển hay thử không, thời gian duyệt mẫu, giá và hạn mức thật, mẫu marketing khác mẫu giao dịch
   ra sao, cửa sổ tin tư vấn, số không dùng Zalo có báo lỗi ngay để chuyển email hay SMS không (FOG-04)?
3. Meta: yêu cầu và thời gian của App Review và Business Verification cho quyền lead, Business Manager của ai, có PKCE
   không, một lô webhook nặng bao nhiêu byte so với trần 64 KB của ADR 0008, giới hạn của Lead Ads Testing Tool
   (FOG-05)?
4. Google: `iss` trong phản hồi cấp quyền và refresh token của ứng dụng ở trạng thái Testing (FOG-05)? Thời gian
   Google xác minh `gmail.send` là của khách, vì ứng dụng Google là ứng dụng nội bộ của khách và nền tảng không giữ
   ứng dụng Google nào (DO-20 (c)); Google Sheets không ở v1 (`requirements.md` mục Không làm).
5. Meta Lead Ads, Zalo OA và form website thử lại trong bao lâu khi nhận 503 lúc công ty bị khóa (FOG-79)?

## Vì sao

Thời gian duyệt ứng dụng là đường găng thật của W2. Đoán sai công thức chữ ký thì từ chối mọi sự kiện; đoán sai vòng
đời token thì đốt kết nối; trần thân nhỏ hơn một lô thật thì rơi lead; 503 dài hơn cửa sổ thử lại của nguồn thì mất
lead.

## Mở khóa

- Spec: `connections-and-vault` (01; trình kết nối Zalo, Meta, Google ở W2), `workflow-triggers` (trần thân, 503 khi
  công ty bị khóa), `tenant-config` (cách ly ZNS khi chạy thử), `org-and-principals` (khóa công ty),
  `marketing-pilot` (lịch).
- ADR: 0113 (công thức `X-ZEvent-Signature` chưa kiểm), 0115, 0008 (trần 64 KB).
- DO: DO-20 (Đạt chốt 23/10/2026, phương án (c): ứng dụng nền tảng cho Meta và Zalo, ứng dụng Google nội bộ của
  khách, nền tảng không giữ ứng dụng Google nào), DO-39 (Đạt chốt 23/10/2026: trả 503 và không lưu khi công ty bị khóa).
- Ticket W1: `connections-and-vault/01` (ready-for-human, tuần một) nộp hồ sơ duyệt; ticket này cấp dữ kiện cho hồ sơ.

## Đầu ra

- Mỗi dữ kiện kèm URL tài liệu, ngày đọc và loại (_documented_, hay _measured_ trên OA thật). OA và ứng dụng thử thuộc
  bên yêu cầu; không dùng dữ liệu người thật.
- Thời gian duyệt và điều kiện duyệt chép vào `connections-and-vault/01` khi ticket đó được cắt.
- Cửa sổ thử lại theo nguồn, để bên yêu cầu xét lại DO-39 nếu một nguồn thử lại ngắn hơn thời gian khóa thường gặp.

## Nguồn

- Brief B6, B8a, B11, B12; `docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md:38` (64 KB, 413).
- [research.md](../research.md) mục 8 (Zalo, Meta, Google chưa kiểm), mục 14 (chế độ phát triển của ZNS chưa kiểm).

## Comments

- 2026-10-24 (agent, tạm): vòng sửa thứ tư, lượt c: câu 4 bỏ phần spreadsheets, vì Google Sheets không ở v1
  (`requirements.md` mục Không làm, N8), và ghi thời gian Google xác minh `gmail.send` là của khách, vì nền tảng không
  giữ ứng dụng Google nào (DO-20 (c), `connections-and-vault/01` bước 4). Sửa: Câu hỏi (câu 4). Nếu sai thì: nền tảng
  giữ một ứng dụng Google, và câu 4 hỏi lại thời gian xác minh cho hồ sơ của nền tảng.
