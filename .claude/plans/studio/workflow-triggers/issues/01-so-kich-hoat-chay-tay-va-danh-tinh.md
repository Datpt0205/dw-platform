# 01 — Sổ kích hoạt, chạy tay và chạy mô phỏng, chạy dưới danh nghĩa tài khoản dịch vụ qua điểm gắn

Status: needs-info (DO-06, DO-12)
Blocked by: .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, R3.3, R3.4, R3.5, TR8, TR9, TR12

## Mục tiêu

Dựng sổ kích hoạt (đăng ký và lần kích hoạt), chạy tay và chạy thử qua `RunRequestService`, và danh tính chạy là tài khoản dịch vụ gắn qua điểm gắn `principal` duyệt bởi người khác, không bao giờ người phát hành (R1, R2, R3 của spec).

## Việc cần làm

1. `studio.trigger_subscriptions` sinh khi kích hoạt và thu hồi (`retired`) khi đổi phiên bản trong cùng giao dịch; `studio.trigger_deliveries` phân vùng tháng có DEFAULT và RLS từng phân vùng; đăng ký bảng cha vào `platform.time_partitioned_tables` (studio-skeleton/01). Freeze giữ (`held_frozen`), kill từ chối (`refused_killed`).
2. Trình kích hoạt xin lượt chạy qua `RunRequestService` (workflow-engine/02) và ghi một dòng `trigger_deliveries` mỗi kết quả; chống trùng là `request_key` của dòng lượt chạy (workflow-engine/04).
3. `POST /api/v1/studio/workflows/{artifact_id}/runs` (quyền `studio.workflow.run`, bản đang dùng, chế độ `live`) và `POST .../versions/{version_id}/test-runs` (quyền `runs.test`, chỉ `test` hoặc `simulate`); form đầu vào từ schema của trình kích hoạt; `Idempotency-Key` bắt buộc (app-standards/02).
4. Điểm gắn kind `principal` vào `ConfigKindRegistry` của tenant-config/05; kiểm `grants_cover` khi đề xuất giá trị (org-and-principals/03); kích hoạt từ chối khi thiếu (`binding_unset`); runner gắn tài khoản dịch vụ làm chủ thể mỗi giao dịch; `requested_by` là người hoặc actor của làn, không bao giờ người phát hành (MP18).

## Tiêu chí chấp nhận

- [ ] R1.1: kích hoạt phiên bản mới → đăng ký cũ `retired`, mới `active` trong cùng giao dịch.
- [ ] R1.2: một trình kích hoạt xin lượt chạy qua `RunRequestService` và ghi một dòng `trigger_deliveries`; trình kích hoạt không gọi runner.
- [ ] R1.3: phạm vi bị đóng băng → lần kích hoạt `held_frozen`, không lượt chạy; sự kiện vẫn được giữ.
- [ ] R1.4 (TR9): sự kiện sau tắt khẩn → lần kích hoạt `refused_killed`, không lượt chạy; bỏ kiểm tắt khẩn → test đỏ.
- [ ] R1.5: hai lần kích hoạt cùng `request_key` → một dòng lượt chạy.
- [ ] R2.1: `POST .../runs` của người giữ `studio.workflow.run` → một lượt chạy bản đang dùng ở `live`; thiếu `Idempotency-Key` → 422.
- [ ] R2.2 (TR12): `test-runs` với chế độ `live` → 422, không lượt chạy; bỏ kiểm chế độ → test đỏ.
- [ ] R2.3: `test-runs` với `test` hay `simulate` → một lượt chạy ở đúng chế độ đó.
- [ ] R2.4: đầu vào sai schema của trình kích hoạt → 422 theo trường, không lượt chạy.
- [ ] R2.5: tenant B gọi `artifact_id` của tenant A → 404, không lượt chạy.
- [ ] R3.1: đề xuất điểm gắn `principal` cho một tài khoản dịch vụ mà Người đề xuất không giữ đủ quyền → 403 `rbac_escalation`.
- [ ] R3.2 (TR8): người phát hành rời tenant → lượt chạy vẫn chạy bằng tài khoản dịch vụ; gắn người phát hành làm chủ thể → test đỏ.
- [ ] R3.3: lượt chạy thử `test` → runner chạy dưới danh nghĩa người thử.
- [ ] R3.4 (TR8): kích hoạt một phiên bản thiếu giá trị điểm gắn `principal` → 409 `binding_unset`, không tạo đăng ký.
- [ ] R3.5: tài khoản dịch vụ mất quyền đọc trường điều kiện của trình kích hoạt → kích hoạt bị từ chối, không tạo đăng ký.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`; `apps/api/src/dw_api/routes/v1/zalo.py:212-213`; spec: R1, R2, R3, TR8, TR9, TR12.
- workflow-engine:R3.3, R3.6; org-and-principals:R6.5, R6.7; tenant-config:R7.2; ADR-0103 (Proposed) quyết 4, ADR-0113 (Proposed) quyết 4.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-12 (chủ thể của lượt chạy không người) và DO-06 (tên điểm gắn so với id trong phiên bản) chưa được Đạt chốt; thiết kế theo khuyến nghị (a) của cả hai.
