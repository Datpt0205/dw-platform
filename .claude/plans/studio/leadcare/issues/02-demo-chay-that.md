# 02 — Demo chạy thật: một lead đi trọn vòng trên compose, ảnh chụp từng màn

Status: ready-for-agent
Blocked by: 01, .claude/plans/studio/digital-worker/issues/04-man-hinh-dw.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, LCP12

## Mục tiêu

Đạt và Business Owner thấy DW chăm sóc lead làm việc thật: docker compose với API, worker, web,
PostgreSQL, Mailpit và model `luna`, một lead đi từ form tới sales, mỗi màn có ảnh chụp (R4, KQ15).

## Việc cần làm

1. `scripts/demo_dw_seed.py`: gieo một tenant demo, năm người (Business Owner, Technical Owner, Work
   Assigner, Validator, sales) với membership và vai, và DW `lead_care` chạy `lead_care@1.0.0` ở
   `operating`, `reply_wait_seconds` 60, `sender_address` `dw-leadcare@demo.local`.
2. `scripts/demo_dw_run.py`: gửi một lead có chữ ký, chờ approval `dw.decision`, kiểm Mailpit chưa có
   thư (R4.4), duyệt bằng Validator qua API, chờ thư tới Mailpit, gửi thư trả lời vào Mailpit qua SMTP,
   chờ việc `handed_off` cho sales, in thời gian mỗi chặng; thoát mã khác 0 ở mọi sai lệch.
3. `make demo-dw`: `docker compose -f infra/compose/docker-compose.yml -f
infra/compose/docker-compose.dev.yml up -d --build` cho postgres, api, worker, web, mailpit với
   model `luna` từ `.env`, migration, seed, rồi script chạy.
4. `apps/web/e2e/demo-digital-worker.spec.ts` (Playwright): đăng nhập dev bằng Business Owner rồi
   Validator, chụp `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ trên `/approvals`, và
   `Drawer` của việc đã bàn giao, vào `docs/demo/digital-worker/<NN>-<màn>.png`.
5. Ghi đường dẫn ảnh và thời gian các chặng vào `.claude/plans/studio.md` và Comments.

## Tiêu chí chấp nhận

- [ ] R4.1: `make demo-dw` dựng đủ năm dịch vụ và một DW `operating`.
- [ ] R4.2: lead đi tới `handed_off` cho sales với gói đủ bốn trường, dưới 10 phút không kể chờ người.
- [ ] R4.3: năm ảnh có trong `docs/demo/digital-worker/`, mỗi ảnh hiện dữ liệu của lượt demo.
- [ ] R4.4 (LCP12): bộ kiểm của script với Mailpit giả đã có thư trước approval → thoát mã khác 0; gỡ phép kiểm thì test đỏ.
- [ ] Xong: `make demo-dw` xanh.

## Nguồn

- `./Makefile:122`; `infra/compose/docker-compose.dev.yml:62-87`; spec: R4, LCP12.

## Comments

- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
