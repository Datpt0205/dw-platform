# 01 — Hồ sơ ứng dụng và duyệt của nhà cung cấp: Meta, Zalo OA và ZNS

Status: ready-for-human (DO-20: chủ ứng dụng nhà cung cấp)
Area: studio
Yêu cầu: không (ticket vận hành: tạo và nộp duyệt ứng dụng nhà cung cấp; đường găng thời gian của W2, không chứng minh mã R nào của W1)

## Mục tiêu

Thời gian App Review và Business Verification là đường găng thật của W2 (OAuth, Zalo, Meta Lead Ads), nên
việc này bắt đầu ngay tuần đầu W1. Ticket cấp cho đội vận hành danh sách việc tạo ứng dụng, nộp duyệt và
theo dõi trạng thái; không có mã phần mềm của W1 phụ thuộc nó. Gộp từ B8a-connections connections-and-vault
05 và B12-product marketing-pilot 03.

## Việc cần làm

1. Mỗi nhà cung cấp, mỗi môi trường (uat, production) một ứng dụng, với URL callback cố định đúng từng
   ký tự `https://<DW_API_HOST>/api/v1/connections/oauth/callback/<provider>` (dành sẵn cho W2).
2. Meta: tạo ứng dụng và Business Manager; Business Verification; nộp App Review Advanced Access cho
   `leads_retrieval`, `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`,
   `pages_manage_ads`, `ads_management` kèm screencast; trong lúc chờ, thêm quản trị Page của khách pilot
   làm tester.
3. Zalo: tạo ứng dụng, liên kết OA, xác thực OA doanh nghiệp, đăng ký mẫu ZNS của pilot.
4. Google: nền tảng không tạo và không giữ ứng dụng Google nào (DO-20 (c)); khách dùng ứng dụng Google nội
   bộ của chính họ, và hướng dẫn khách tạo ứng dụng đó là việc W2.
5. Secret của mỗi ứng dụng vào `.env` của môi trường triển khai dạng `${...:?}`, không vào repo; ghi
   ngày nộp, trạng thái và hạn dự kiến vào bảng trạng thái duyệt trong `.claude/plans/studio.md`.

## Tiêu chí chấp nhận

- [ ] URL callback của mỗi ứng dụng khớp chính xác từng ký tự với
      `https://<DW_API_HOST>/api/v1/connections/oauth/callback/<provider>`.
- [ ] Secret ứng dụng không có trong git (`gitleaks` xanh).
- [ ] `.claude/plans/studio.md` có bảng trạng thái duyệt cho hai nhà cung cấp Meta và Zalo (ngày nộp, trạng
      thái, hạn dự kiến).
- [ ] Xong: `gitleaks detect` xanh.

## Nguồn

- `apps/api/src/dw_api/settings.py:206`; spec: R5 (callback dành cho OAuth của W2).
- Brief B8a-connections ticket 05; B12-product marketing-pilot ticket 03.

## Comments

- 2026-10-23 (agent): `ready-for-human` vì đây là việc của người (nộp App Review, Business Verification),
  không phải mã. DO-20 còn mở về chủ ứng dụng; tạm theo khuyến nghị (a): nền tảng sở hữu ứng dụng Meta và
  Zalo, khách dùng Page và OA của họ, ứng dụng Google nội bộ của khách.
- 2026-10-23 (agent): Đạt chốt DO-20 theo (c) ngày 23/10/2026 (nhãn "(a)" ở dòng trên ghi lệch; nội dung
  vẫn là (c)): ứng dụng nền tảng cho Meta và Zalo, pháp nhân vận hành nộp App Review và Business
  Verification từ tuần một, nền tảng không giữ ứng dụng Google nào. Bỏ bước nền tảng xác minh Google
  (bước 4), bảng trạng thái còn hai nhà cung cấp.
