# 01 — Khách trả tiền đầu tiên và giá thử

Status: ready-for-human
Area: go-live
Yêu cầu: không (việc chỉ Đạt làm được, không có spec)

## Mục tiêu

Chốt một công ty thật sẽ dùng và trả tiền, cùng giá thử, vì không ticket nào trả lời thay được câu có ai mua không (`requirements.md`, Q1, KQ1).

## Việc cần làm

1. Chọn một đội marketing thật có ít nhất 200 lead mỗi tháng, có người duyệt và người tài trợ có tên (DO-22).
2. Chốt số giá cho gói đầu: phí tháng và trần chi phí AI (DO-59), ghi vào Comments.
3. Ghi tên khách, giá và ngày dự kiến vào `.claude/plans/go-live.md`.
4. Khi xong: có khách có tên và giá trong `.claude/plans/go-live.md`.

## Tiêu chí chấp nhận

- [ ] Xong: `python scripts/check_plans.py --area go-live` xanh.

## Nguồn

- `.claude/plans/go-live/requirements.md`, Q1, KQ1.

## Comments
