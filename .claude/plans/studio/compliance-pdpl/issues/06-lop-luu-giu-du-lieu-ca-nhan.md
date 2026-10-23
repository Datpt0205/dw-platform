# 06 — Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13

Status: needs-info (DO-52: số tạm cho hội thoại)
Blocked by: 04, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, CP16, CP17

## Mục tiêu

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa đã đăng ký trong `retention@1.9.0`, nâng
từ bản 1.8.0 của telemetry-and-audit; Danh sách chặn gửi không bao giờ hết hạn theo thời gian; chú thích thời
hạn dẫn Nghị định 356 thay Nghị định 13/2023 (spec R5; ADR-0106 (Accepted), ADR-0123 (Accepted)).

## Việc cần làm

1. `configs/policies/retention@1.9.0.yaml` nâng từ `retention@1.8.0.yaml` của telemetry-and-audit/03 (một chủ
   mỗi bản, DO-52), thêm lớp và bộ xóa cho kho mới của lát, số ghi UNVERIFIED tới khi luật sư xác nhận trước
   chạy bóng: Bản ghi đồng ý (theo quan hệ cộng 5 năm, lane xóa theo dòng, không DROP PARTITION), Danh sách
   chặn gửi (suốt quan hệ với công ty; bộ xóa là offboarding của công ty và, ở W2, yêu cầu của chủ thể dữ
   liệu; không hạn theo thời gian), nhật ký gửi marketing (13 tháng), hội thoại (số tạm do Đạt đặt). Lịch sử
   sự kiện Data Hub đã ở bản 1.8.0 của telemetry-and-audit/03.
2. Sửa chú thích thời hạn Nhật ký kiểm toán trong `configs/policies/retention@1.9.0.yaml` và
   `.claude/plans/ops-hardening.md:22` sang PDPL và Nghị định 356 (điều khoản do luật sư xác nhận), bỏ dẫn
   Nghị định 13/2023.
3. Test tập bộ xóa: mỗi lớp dữ liệu cá nhân có một bộ xóa đã đăng ký; một lớp thiếu bộ xóa → đỏ. Test riêng
   cho Danh sách chặn gửi: lane lưu giữ chạy qua một dòng chặn gửi 10 năm tuổi mà dòng còn (spec R5.4).

## Tiêu chí chấp nhận

- [ ] R5.1 (CP16): mỗi kho mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi marketing, hội thoại)
      có một thời hạn trong `retention@1.9.0` và một bộ xóa đã đăng ký.
- [ ] R5.2 (CP16): một kho dữ liệu cá nhân không có bộ xóa đăng ký → test tập bộ xóa đỏ.
- [ ] R5.3: chú thích thời hạn Nhật ký kiểm toán dẫn PDPL và Nghị định 356, không dẫn Nghị định 13/2023.
- [ ] R5.4 (CP17): dòng chặn gửi 10 năm tuổi còn sau một lượt lane lưu giữ, lần gửi sau vẫn
      `blocked:suppressed`; thêm hạn theo thời gian cho lớp chặn gửi → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13/2023 đã hết hiệu lực).
- ADR-0106 (Accepted) quyết 7; ADR-0123 (Accepted) quyết 1.

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 10. `needs-info` vì DO-52 (thời hạn mỗi kho) chờ counsel
  và Đạt. `retention@1.8.0` đồng sở hữu với telemetry-and-audit (lát đó giữ lớp run, Bước chạy, Sổ sử
  dụng); lát này thêm lớp đồng ý, gửi, sự kiện Data Hub.
- 2026-10-23 (agent): áp DO-52 (Đạt, 23/10/2026): telemetry-and-audit/03 là chủ bản 1.8.0, ticket này nâng
  lên 1.9.0 và chờ ticket đó (OPS-b); Danh sách chặn gửi giữ suốt quan hệ; sự kiện Data Hub chuyển sang
  telemetry-and-audit. Chờ ticket 04 và agent-builder/04 vì các kho của chúng là đối tượng của bộ xóa
  (I:agent-builder/04~compliance-pdpl/06). Còn `needs-info` vì DO-52 giao số tạm cho hội thoại cho Đạt mà sổ
  quyết định chưa ghi số.
