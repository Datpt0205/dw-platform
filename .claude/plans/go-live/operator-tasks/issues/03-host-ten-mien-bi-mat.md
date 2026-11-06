# 03 — Host production, tên miền và bí mật triển khai

Status: ready-for-human
Area: go-live
Yêu cầu: không (việc chỉ Đạt làm được, không có spec)

## Mục tiêu

Có nơi thật để triển khai, vì không agent nào giữ host, tên miền hay bí mật (Chờ Đạt 20, D14).

## Việc cần làm

1. Thuê host ở Việt Nam: ít nhất 4 vCPU / 16 GB cho production và một host uat; một VM riêng khi bật bước mã của công ty.
2. Mua tên miền, trỏ ba tên của ADR-0009 (Accepted) cho uat và production.
3. Đặt bí mật vào `.env` của từng host: `QDRANT_API_KEY`, `REDIS_PASSWORD`, `LANGFUSE_REDIS_PASSWORD`, `DW_DB_MONITOR_PASSWORD`, khóa ký, khóa model.
4. Cài runner tự host nhãn `uat`, `prod` theo `.github/workflows/deploy.yml`.
5. Chọn đích sao lưu ngoài host, rồi làm `.claude/plans/studio/connections-and-vault/issues/08-openbao-tren-host-trien-khai.md`.
6. Khi xong: `docker compose config` trên host uat chạy không lỗi, ghi ở Comments.

## Tiêu chí chấp nhận

- [ ] Xong: `python scripts/check_plans.py --area go-live` xanh.

## Nguồn

- `.github/workflows/deploy.yml:61`; `.claude/plans/go-live/production-deploy/spec.md`.

## Comments
