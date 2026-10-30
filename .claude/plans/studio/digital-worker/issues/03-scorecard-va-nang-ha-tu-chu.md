# 03 — Scorecard tính từ dữ liệu, nâng hạ mức đã kiếm

Status: ready-for-agent
Blocked by: 02, .claude/plans/studio/wf-lite/issues/02-bien-dich-va-chay.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, DWK17, DWK18, DWK19, DWK20

## Mục tiêu

Business Owner đọc scorecard của DW tính từ hàng đợi, quyết định duyệt và chi phí của lượt chạy, và
đổi mức đã kiếm: hạ ngay, nâng khi người thứ hai duyệt (R7, R8, ADR-0128 (Proposed) quyết 5, 9).

## Việc cần làm

1. Migration mới: `platform.worker_runs.model_cost_usd numeric(12,6) NOT NULL DEFAULT 0` CHECK `>= 0`.
2. `dw_agent_runtime/adapters/run_cost_recorder.py`: một `UsageRecorderPort` cộng `cost_usd` của lời
   gọi vào `model_cost_usd` của lượt chạy bằng `UPDATE ... SET model_cost_usd = model_cost_usd + :c`;
   đăng ký trong `CompositeUsageRecorder` ở composition root của worker và API.
3. `dw_platform/application/scorecard.py` và repository: `GET /v1/digital-workers/{id}/scorecard?days=`
   (1-90, mặc định 30, cửa sổ cuộn `now() - n × 24 giờ`), một truy vấn tổng hợp mỗi nguồn theo R7.1: việc
   có `dw_id` là DW theo `created_at`, approval `dw.decision` có `payload->>'dw_id'` là DW theo `decided_at`
   (duyệt nguyên văn, duyệt có sửa theo `edited`, từ chối), tổng `model_cost_usd` của lượt chạy có
   `run_as_principal_id` là principal của DW theo `created_at`.
4. `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy` `{level}`: hạ (BO hay TO) ghi ngay
   với audit `dw.autonomy.lowered`; nâng (chỉ BO, không quá trần, không khi đã có approval nâng đang chờ
   cho loại đó) mở approval `dw.autonomy.raise` không lượt chạy với `from_level`, `to_level`, trả 202 với
   id approval; thêm `dw.autonomy.` vào `strict_approval_prefixes` và một `DecisionAdmission` chỉ nhận
   Validator hay Technical Owner hiện tại của DW (R8.3).
5. Handler outbox `dw.autonomy.raise.decided` ở worker: duyệt, `earned_level` hiện tại bằng `from_level` và
   DW chưa `retired` thì ghi `to_level` (`UPDATE ... WHERE earned_level = :from_level`) và audit
   `dw.autonomy.raised` đứng tên người duyệt với `details.lane`; không thì audit `dw.autonomy.raise_stale`
   và không đổi mức (R8.6).
6. Đo P50/P95/P99 của route scorecard và danh sách việc (ticket đổi cách truy cập DB, `latency.md`).
7. Test âm DWK17-DWK20.
8. Theo gate lượt 2: index unique một phần trên `platform.approval_requests ((payload->>'dw_id'), (payload->>'decision_class'))`
   `WHERE approval_type = 'dw.autonomy.raise' AND status = 'pending'` (R8.4); bắt vi phạm unique thành 409 `raise_pending`.

## Tiêu chí chấp nhận

- [ ] R7.1: với 3 việc `done`, 1 `handed_off`, 2 approval duyệt (1 có sửa), 1 từ chối và chi phí 0,012 + 0,003, scorecard trả đúng số; việc của DW khác không tính.
- [ ] R7.2: `days=0` và `days=91` → 422 `days_out_of_range`; `days=1` và `days=90` → 200.
- [ ] R7.3: hai lời gọi model của một lượt chạy cộng đúng vào `model_cost_usd`; lời gọi của lượt khác không chạm.
- [ ] R8.1: BO hạ A3 xuống A2 → mức mới ngay, `effective_level` trả A2 ở lần hỏi kế tiếp, có audit.
- [ ] R8.2 (DWK17): BO nâng A2 lên A3 → 202, mức vẫn A2; người thứ hai từ chối → vẫn A2; duyệt → A3.
- [ ] R8.6 (DWK17): từ chối không đổi mức; duyệt ghi mức mới và audit; hạ khẩn xuống A0 rồi duyệt đề nghị A2→A3 → mức giữ A0, audit `dw.autonomy.raise_stale`.
- [ ] R8.3 (DWK18): BO tự duyệt đề nghị của mình, người ngoài DW giữ `approvals.decide` duyệt, hay duyệt không lý do → 409, mức không đổi.
- [ ] R8.4 (DWK19): đề nghị A4 với trần A3 → 422 `above_ceiling`; đề nghị thứ hai khi một đang chờ → 409 `raise_pending`; không approval mới.
- [ ] R8.5 (DWK20): Validator hạ → 403 `not_dw_owner`; TO nâng → 403.
- [ ] R8.4 (DWK19): hai đề nghị nâng cùng lúc cho một loại → đúng một approval, lời gọi kia 409 `raise_pending`.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/usage_recorders.py:1-40`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:304-305`; spec: R7, R8, DWK17-DWK20.

## Comments

- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): đang làm. Xong bước 1-2 (`d340030`: cột `model_cost_usd`, `RunCostRecorder` trong
  `build_model_stack`, nên cả API và worker ghi). Còn: bước 3 scorecard, 4 route nâng hạ, 5 handler outbox, 8 index
  unique một phần, 6 độ trễ, 7 test âm; mutation, rà bảo mật.
- 2026-10-30 (agent): đang đóng. Xong bước 1-8, mutation 18/18 (`8e02ff1`), độ trễ trong ngân sách; còn chạy
  integration của bốn gói chạm tới trước khi đánh dấu resolved.
