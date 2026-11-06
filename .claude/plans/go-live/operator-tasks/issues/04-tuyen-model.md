# 04 — Tuyến model cho khách đầu

Status: ready-for-human
Area: go-live
Yêu cầu: không (việc chỉ Đạt làm được, không có spec)

## Mục tiêu

Chốt model khách đầu dùng, vì mọi hồ sơ model thật khai nước ngoài trong khi mặc định công ty là `vn_only` (`packages/python/dw_platform/src/dw_platform/application/admin_console.py:103`), nên hôm nay công ty mới không gọi được model nào.

## Việc cần làm

1. Hỏi nhà cung cấp model xử lý trong Việt Nam, giá và hợp đồng; hoặc
2. Hỏi luật sư có được dùng tuyến nước ngoài với đồng ý của khách, rồi công ty đổi lớp bằng hai người theo ADR-0123 (Accepted).
3. Giao khóa và khai `data_location`, `processor` thật; làm tiếp `.claude/plans/studio/model-connections/issues/03-spike-nha-cung-cap-that.md` nếu cần.
4. Khi xong: `make check-model` xanh trên tuyến đã chọn, hoặc lệnh tương đương, ghi ở Comments.

## Tiêu chí chấp nhận

- [ ] Xong: `python scripts/check_plans.py --area go-live` xanh.

## Nguồn

- `requirements.md`, Q2; ADR-0123 (Accepted).

## Comments
