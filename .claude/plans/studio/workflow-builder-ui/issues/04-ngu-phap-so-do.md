# 04 — Ngữ pháp sơ đồ: nhánh, song song, vòng lặp, nhánh lỗi

Status: needs-triage
Blocked by: 02
Area: studio
Yêu cầu: R1.5, R1.7, R2.5, R2.6, BU7, BU8, BU11, BU14

## Mục tiêu

Sơ đồ vẽ mọi cấu trúc của cây Bước theo bảng ngữ pháp của R1.5, trên năm khối chung mà ticket 02 đặt chỗ: các làn của
`logic.switch` với làn "Khác", làn "Duyệt" và "Từ chối" của Bước phê duyệt, khung "Song song" với Điểm nối, khung vòng
lặp với mũi tên "Lặp lại", và làn lỗi khi Khi lỗi là `route`; khung chứa thu gọn được; bàn phím và Dạng danh sách đi qua
làn và khung (workflow-builder-ui R1.5, R1.7, R2.5, R2.6, BU7, BU8, BU11, BU14). Đây là bậc A của V4.26: ngữ pháp có
trước bộ máy chạy song song và vòng lặp có trần của bậc B, nên ticket không chờ các Loại bước của bậc B; bảng Loại bước
chỉ đưa chúng khi workflow-nodes đăng ký.

## Việc cần làm

1. Dưới `apps/web/app/studio/**/canvas/**`, vẽ mỗi cấu trúc bằng antd từ hình mà `apps/web/lib/workflow-layout.ts`
   (ticket 02) trả, đúng bảng ngữ pháp của R1.5:
    - `logic.switch`: thẻ điều kiện; các làn treo dưới thẻ, cạnh nhau theo thứ tự tài liệu, mỗi làn dưới một antd `Tag`
      mang tóm tắt điều kiện của nhánh ("Điểm ≥ 70"); làn "Khác" luôn vẽ, cả khi trống (ô "Thêm Bước"); các làn gộp ở
      một điểm dưới các làn, không phải Điểm nối.
    - Bước phê duyệt: thẻ người duyệt nêu người được giao và phạm vi, "Cần cả N người duyệt" khi Bước đòi từ hai người
      duyệt bắt buộc trở lên (quy tắc duyệt `all`, workflow-nodes:R12.1); làn "Duyệt" và "Từ chối" cho Nhánh ra
      `approved`, `rejected` (workflow-nodes:R9.9, workflow-nodes:R9.16) treo dưới thẻ, gộp ở một điểm dưới các làn.
    - Bước song song: khung "Song song" N làn cạnh nhau, đáy khung là Điểm nối, một thanh "Chờ tất cả nhánh xong"; không
      có Bước gộp riêng.
    - Bước vòng lặp: khung "Lặp lại khi … (tối đa N lần)" quanh thân; mũi tên "Lặp lại" dọc rãnh trái; làn "Đã đủ N lần"
      cho Nhánh ra `max_reached` khi Bước có làn đó; Bước "Thoát vòng lặp" vẽ mũi tên tới lối ra dưới khung.
    - Làn lỗi (Khi lỗi là `route`): làn nét đứt ở rãnh phải của Bước, nhãn "Khi lỗi" theo token lỗi của theme, gộp lại
      dưới Bước, trừ khi làn kết thúc bằng `flow.stop`. Trong một làn song song, bộ kiểm của workflow-engine từ chối làn
      lỗi kết thúc và `flow.stop` (workflow-engine:R2.15); Sơ đồ chỉ hiện lỗi đó trên Bước như R3.4, không tự kiểm
      (ADR-0101 (Accepted) quyết 3).
    - Nhãn lấy từ khóa thông điệp (DO-57) và nhãn Nhánh ra của `GET /api/v1/studio/node-types` (workflow-nodes:R1.2);
      màu, biểu tượng, cỡ thẻ và kiểu đường nối chỉ từ bộ từ vựng mà ticket 01 ghi trong theme của `@dw/ui`.
2. Thu gọn: mỗi khung chứa ("Song song", "Lặp lại khi …") thu gọn và mở từ một antd `Button` ở đầu khung; trạng thái
   giữ theo người xem trong bộ nhớ trình duyệt (mọi lần đọc, ghi bọc `try/catch`, trang vẽ đủ, mọi khung mở, khi bộ nhớ
   không dùng được), không bao giờ vào tài liệu; `workflow-layout.ts` đo khung thu gọn như một thẻ.
3. Bàn phím và Dạng danh sách qua cấu trúc: ←/→ đi giữa các làn kề nhau của một Bước; ↓ từ thẻ của một Bước có làn
   vào Bước đầu của làn đầu, ↑ từ Bước đầu của một làn về thẻ đó; `Tree` vẽ mỗi làn là một node lồng dưới Bước của nó,
   mang `aria-level`, `aria-posinset`, `aria-setsize`, để NVDA đọc "nhánh 2 trên 3: Điểm ≥ 70".
4. Fixture F2, F3, F4, F5 và F9 của ticket 01 thành snapshot test; Playwright chỉ bàn phím dựng F5. Cả hai chạy trên
   một `GET /api/v1/studio/node-types` giả mang mọi Loại bước mà các fixture dùng, với đúng Nhánh ra và cấu hình mà
   workflow-nodes khai, kể cả `human.approval@1` với quy tắc duyệt `all` và các loại của bậc B `logic.parallel@1`,
   `logic.loop@1`, `logic.break@1` (workflow-nodes:R10.1, workflow-nodes:R11.2, workflow-nodes:R12.1), vì ticket này
   chỉ chờ danh mục của workflow-nodes/02 qua ticket 02, không chờ workflow-nodes đăng ký các loại đó (V4.26).
5. Học mẫu, không chép: đặc tả OpenFlow của Windmill (Apache-2.0) và luồng của Power Automate là danh sách kiểm cho ngữ
   pháp; không chép giao diện Dify, không chép mã Windmill hay n8n (V4.24, V4.29).

## Tiêu chí chấp nhận

- [ ] R1.5: snapshot F2 (`logic.switch` 8 làn lồng 2 tầng): mỗi làn dưới Tag điều kiện của nó, làn "Khác" có mặt, các
      làn của mỗi Bước gộp ở đúng một điểm; F3: khung "Song song" có thanh "Chờ tất cả nhánh xong" nằm trong khung "Lặp
      lại khi … (tối đa N lần)" có mũi tên "Lặp lại" và làn "Đã đủ N lần"; F4: mỗi Bước có làn "Khi lỗi" nét đứt ở rãnh
      phải, gộp lại dưới Bước; F5: làn "Duyệt" và "Từ chối", thẻ "Cần cả 3 người duyệt"; F9 vẽ xong, mỗi Bước "Thoát
      vòng lặp" có mũi tên tới lối ra dưới khung của nó, không hai thẻ chồng nhau; vẽ một điểm gộp của `logic.switch`
      bằng thanh "Chờ tất cả nhánh xong" → snapshot đỏ.
- [ ] R1.5 (BU14): một màu literal trong thành phần ngữ pháp → test đỏ; một nhãn làn hay đầu khung chỉ có màu, không
      chữ → test đỏ.
- [ ] R1.7 (BU8): thu gọn một khung → khung vẽ như một thẻ, tài liệu và Mã băm nội dung không đổi; tải lại → khung vẫn
      thu gọn với cùng người xem; bộ nhớ trình duyệt không dùng được → trang vẽ đủ, mọi khung mở; ghi trạng thái thu
      gọn vào tài liệu → test đỏ.
- [ ] R2.5 (BU7): Playwright dựng F5 chỉ bằng bàn phím: đặt Bước vào làn "Từ chối" của một Bước phê duyệt và vào thân
      vòng lặp, dời một Bước sang làn kế, vào và ra khung chứa, thu gọn rồi mở một khung, xóa khung "Lặp lại khi …" rồi
      hoàn tác; phím mũi tên không bao giờ dời node; bỏ đường bàn phím vào làn → test đỏ.
- [ ] R2.6 (BU11): `Tree` của F2 mang `aria-level`, `aria-posinset`, `aria-setsize` đúng cấp và vị trí của mỗi làn và
      mỗi Bước; bỏ một thuộc tính ở node làn → test đỏ.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- ADR-0101 (Accepted) quyết 2, 3; ADR-0112 (Accepted) quyết 1; spec: R1.5, R1.7.
- workflow-nodes:R1.2, workflow-nodes:R9.9, workflow-nodes:R9.16; spec: R1.5 (Nhánh ra và nhãn của Loại bước, từ vựng
  `approved`, `rejected` và làn của mỗi kết quả phê duyệt).
- workflow-nodes:R10.1, workflow-nodes:R11.2, workflow-nodes:R12.1; spec: R1.5 (Nhánh ra của Bước song song và Bước
  vòng lặp, quy tắc duyệt `all`, cho danh mục giả của bước 4).
- workflow-engine:R1.1, workflow-engine:R2.15; spec: R1.5 (làn lồng theo Nhánh ra; trong làn song song, làn lỗi chỉ gộp
  lại).
- `.claude/rules/ui-quality.md:230-231`, `.claude/rules/ui-quality.md:370-376`; spec: R1.5 (không chỉ màu, tương phản).
- `packages/typescript/ui/src/theme.ts:3-6`; spec: R1.5 (một chủ của màu).

## Comments

- 2026-10-25 (agent): tạo ở lượt g theo V4.24, V4.26 (bậc A) và V4.27 của Đạt ngày 24/10/2026. Không cạnh tới spec khác: ngữ pháp vẽ từ cây tài liệu và danh mục Loại bước mà ticket 02 đã chờ (workflow-engine/01, workflow-nodes/02), không chờ Loại bước của bậc B.
