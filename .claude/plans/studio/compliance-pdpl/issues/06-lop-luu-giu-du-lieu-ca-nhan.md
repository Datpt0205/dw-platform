# 06 — Lớp lưu giữ cho kho dữ liệu cá nhân mới, bỏ dẫn Nghị định 13

Status: needs-info (DO-52)
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, CP16

## Mục tiêu

Mỗi kho dữ liệu cá nhân lát này thêm có một thời hạn và một bộ xóa đã đăng ký trong `retention@1.8.0`, và
chú thích thời hạn dẫn Nghị định 356 thay Nghị định 13/2023
(spec R5; ADR-0106 (Proposed), ADR-0123 (Proposed)).

## Việc cần làm

1. `configs/policies/retention@1.8.0.yaml` thêm lớp và bộ xóa cho kho mới của lát: Bản ghi đồng ý (theo
   quan hệ cộng 5 năm), Danh sách chặn gửi, nhật ký gửi marketing (13 tháng), lịch sử sự kiện Data Hub (30
   ngày), hội thoại; mỗi lớp một bộ xóa (lane xóa hoặc DROP PARTITION).
2. Sửa chú thích thời hạn Nhật ký kiểm toán trong `configs/policies/retention@1.8.0.yaml` và
   `.claude/plans/ops-hardening.md:22` sang PDPL và Nghị định 356 (điều khoản do luật sư xác nhận), bỏ dẫn
   Nghị định 13/2023.
3. Test tập bộ xóa: mỗi lớp dữ liệu cá nhân có một bộ xóa đã đăng ký; một lớp thiếu bộ xóa → đỏ.

## Tiêu chí chấp nhận

- [ ] R5.1 (CP16): mỗi kho mới của lát (Bản ghi đồng ý, Danh sách chặn gửi, nhật ký gửi marketing, lịch sử
      sự kiện Data Hub, hội thoại) có một thời hạn và một bộ xóa đã đăng ký.
- [ ] R5.2 (CP16): một kho dữ liệu cá nhân không có bộ xóa đăng ký → test tập bộ xóa đỏ.
- [ ] R5.3: chú thích thời hạn Nhật ký kiểm toán dẫn PDPL và Nghị định 356, không dẫn Nghị định 13/2023.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13/2023 đã hết hiệu lực).
- ADR-0106 (Proposed) quyết 7; ADR-0123 (Proposed) quyết 1.

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 10. `needs-info` vì DO-52 (thời hạn mỗi kho) chờ counsel
  và Đạt. `retention@1.8.0` đồng sở hữu với telemetry-and-audit (lát đó giữ lớp run, Bước chạy, Sổ sử
  dụng); lát này thêm lớp đồng ý, gửi, sự kiện Data Hub.
