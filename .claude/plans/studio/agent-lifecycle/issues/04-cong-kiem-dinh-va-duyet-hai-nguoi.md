# 04 — Cổng chất lượng mô phỏng với bộ an ninh nền tảng và duyệt phát hành hai người

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R6.1, R6.2, R6.3, AL4, AL5, AL6, AL7, AL8, AL9, AL10

## Mục tiêu

Lượt kiểm định chạy ở chế độ Mô phỏng với Bộ kiểm định an ninh nền tảng (đạt 100%; bộ đề của tenant là
W2) dưới trần chi phí giữ trước qua `LimitsPort`; phát hành cần một người không phải Tác giả duyệt; cổng
không mở phê duyệt khi Phân tích năng lực thiếu hay chưa đạt (spec R4, R5, R6). Phân tích năng lực do
compliance-pdpl giữ và trả 422 lúc gửi kiểm định; lát này chỉ đọc kết quả đã ghi làm chốt chặn.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `studio.gate_runs` (`status` CHECK `queued`, `running`,
   `passed`, `failed`, `error`, `cancelled`; `purpose` CHECK `gate`, `dry`; khóa bằng chứng
   `effective_hash`, `gate_policy_ref`, `security_suite_ref`, danh sách mã băm bộ đề của tenant (rỗng ở
   W1); `definition_hash` cho trigger giai đoạn; `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb,
   `verdict` jsonb); `studio.gate_case_results` phân vùng theo tháng với DEFAULT, đăng ký bằng một dòng
   `platform.time_partitioned_tables` (`append_only = true`), không sửa thân hàm; ENABLE/FORCE RLS và policy
   tenant trên cha và DEFAULT cùng migration; `dw_app` không giữ quyền nào trên partition nào, kể cả
   DEFAULT (DO-02.2). `studio.gate_run_datasets` là W2 cùng bộ đề của tenant. Policy drain
   `app.worker_drain` để lane nhận việc.
2. Lane `studio_gate` (tối đa một Lượt kiểm định mỗi tenant, một `ReapTarget` cho lượt treo): mỗi lần
   thử là một run `run_mode='simulate'` dùng ngữ cảnh truy cập đóng dấu của người gửi. Lượt kiểm định xin
   lease `purpose` `eval_offline` qua `LimitsPort` của usage-and-limits/03 với trần mỗi lượt
   `max_gate_worst_case_usd`, mỗi lần thử dùng lease đó với trần `max_trial_cost_usd`; không đọc
   `profile.max_cost_usd_per_run` (DO-21.4). Trước lời gọi model đầu tiên: chi phí xấu nhất vượt trần mỗi
   lượt, hay `LimitsPort` từ chối lease → Lượt kiểm định `error` với `limit_exceeded`, không run nào (spec
   R4.4). Audit `studio.gate_run.started`, `studio.gate_run.completed` (actor `system:studio_gate`); thông
   báo người gửi.
3. Bộ sinh Bộ kiểm định an ninh nền tảng ở `configs/evals/studio_security_suite@1.0.0.yaml` và Chính
   sách cổng ở `configs/policies/studio_gate@1.0.0.yaml`, chỉ các trường có bên đọc ở W1 (DO-29.1):
   `security_pass_rate` cố định 1.0, `pass_k` = 3, `max_trial_cost_usd` = 0.10, `max_gate_worst_case_usd`
   = 10, `publish_approval_ttl_days` = 14; `min_cases_total`, `pass_rate_min`, `stale_draft_days` vào chính
   sách ở W2 cùng bên đọc. Cả hai ghim trong release manifest; `scripts/release_manifest.py` đã được
   usage-and-limits/02 sửa trước (nối qua usage-and-limits/03). Bộ chấm `studio.*` hợp nhất bằng
   `merge_graders` ở composition root của worker; `dw_evals` không biết chúng.
4. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations`
   (`studio.eval.run`); `GET /api/v1/studio/gate-runs`, `/{id}`, `/{id}/cases` (`studio.lifecycle.read`).
5. Phát hành hai người: KHI gate đạt, lane mở một yêu cầu phê duyệt trong giao dịch `evaluating →
awaiting_approval` (loại `studio.publish.agent` hay `studio.publish.workflow`, `required_scope`
   `studio.publish.approve`, payload chỉ id và mã gồm `author_ids` dựng từ `contributor_ids` và
   `submitted_by` của dòng phiên bản trong cùng giao dịch). Thêm `studio.publish.` vào
   `strict_approval_prefixes` bằng `|=` (kèm chú thích; `studio.lifecycle.` đã thêm ở ticket 01);
   `decision_guards` `require_not_author` từ chối người quyết trong `author_ids` và từ chối payload thiếu
   `author_ids`. Handler worker `studio.publish.agent.decided`, `studio.publish.workflow.decided` idempotent
   trên id yêu cầu, actor là người quyết định với `details.lane` là tên lane (ADR-0011 (Accepted)): đưa phiên
   bản Đang dùng, bản cũ Đã gỡ (`superseded`), audit `studio.version.published`, outbox
   `studio.version.live`; từ chối → `draft`. Nhãn loại approval và liên kết "Xem diff" ở điểm cắm
   `apps/web/components/tool-approval.tsx`. Lane hết hạn phê duyệt phát hành: hủy yêu cầu quá
   `publish_approval_ttl_days`, đưa phiên bản về `draft`, audit qua `lane_audit_event` với actor
   `system:<lane>` vì lane tự làm (spec R5.7).
6. Chốt chặn Phân tích năng lực: trước khi mở yêu cầu phê duyệt, lane đọc kết quả Phân tích năng lực mà
   compliance-pdpl/05 ghi ở `studio.version_assessments` cho Mã băm định nghĩa của Bản ứng viên; thiếu kết
   quả, đường bộ ba chưa giải quyết, Mức tự chủ vượt mức hay công cụ chưa phân loại → cổng trượt, không mở
   yêu cầu phê duyệt, phiên bản về `draft` (spec R6.1, R6.2). Mã 422 lúc gửi kiểm định là của compliance-pdpl
   (compliance-pdpl:R4.2, R4.3, R4.4). Mức sàn duyệt của công cụ không bị hạ bởi cấu hình công ty, người
   dựng hay Mức tự chủ (ADR-0125 (Accepted)).

## Tiêu chí chấp nhận

- [ ] R4.1 (AL7): một Câu an ninh trượt → cổng trượt, phiên bản về `draft`; tất cả đạt → `awaiting_approval`;
      không route nào ghi Câu an ninh.
- [ ] R4.2 (AL7): một bộ chấm trả `unknown` chặn như trượt; gỡ luật `unknown` trong `evaluate_gate` → test đỏ.
- [ ] R4.3 (AL8): agent có công cụ gửi Zalo trong Lượt kiểm định → egress giả không nhận lời gọi; gỡ chặn
      `simulate` ở executor → test đỏ.
- [ ] R4.4 (AL9): chi phí xấu nhất vượt trần mỗi lượt → Lượt kiểm định `error` `limit_exceeded` trước mọi
      `worker_runs`; `LimitsPort` giả từ chối lease `eval_offline` → như trên, 0 lời gọi model.
- [ ] R4.5 (AL9): một lần thử chạm trần mỗi lần thử → Câu đó trượt với `cost_bound`, các câu khác vẫn
      chấm; gỡ trần mỗi lần thử → test đỏ.
- [ ] R4.6: hai Lượt kiểm định cùng khóa bằng chứng → lượt sau dùng lại, không tạo run.
- [ ] R5.1 (AL5): khi gate đạt, yêu cầu phê duyệt mở trong cùng giao dịch `evaluating → awaiting_approval`,
      payload chỉ id và mã; `author_ids` bằng đúng `contributor_ids` cộng `submitted_by` của dòng phiên bản;
      dựng thiếu một người → test khớp đỏ.
- [ ] R5.2 (AL5): Tác giả có scope duyệt → 409 `author_cannot_approve`; người gửi → 409.
- [ ] R5.3 (AL5): payload thiếu `author_ids` → quyết định bị từ chối; gỡ guard → test đỏ.
- [ ] R5.4 (AL6): `platform_admin` không giữ tem `studio.publish.approve` → 404 khi đọc và khi quyết định.
- [ ] R5.5: duyệt → bản mới Đang dùng, bản cũ Đã gỡ (`superseded`) trong một vòng outbox; giao hai lần
      cùng sự kiện → một kết quả; từ chối → `draft`.
- [ ] R5.6 (AL4): chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514;
      gỡ CHECK → test đỏ.
- [ ] R5.7: yêu cầu phê duyệt phát hành quá 14 ngày → lane hủy nó, phiên bản về `draft`, audit với actor
      `system:<lane>`; yêu cầu 13 ngày tuổi còn nguyên.
- [ ] R6.1 (AL10): `dw_app` ghi thẳng một Bản ứng viên không có dòng `studio.version_assessments` sang
      `evaluating` → cổng trượt, không yêu cầu phê duyệt nào, phiên bản về `draft`; dòng ghi đường bộ ba chưa
      giải quyết → như trên; gỡ đọc kết quả ở lane → yêu cầu phê duyệt mở (đỏ).
- [ ] R6.2 (AL10): kết quả ghi một công cụ thiếu phân loại → cổng trượt, không yêu cầu phê duyệt nào.
- [ ] R6.3 (AL10): cấu hình công ty không hạ được mức sàn duyệt của công cụ trọng yếu; chỉ siết thêm được.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:244`; spec: R5.1, R5.5 (yêu cầu
  phê duyệt không lượt chạy phát `<type>.decided` qua outbox).
- `apps/api/src/dw_api/bootstrap/runtime.py:237`; spec: R5.2 (prefix nghiêm thêm bằng `|=`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R6.2 (phân loại công
  cụ là bên đọc đầu tiên); ADR-0120 (Accepted) quyết 2-3, ADR-0125 (Accepted).

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 07 và 09, cộng seam eval của B1 studio-skeleton 10.
  `needs-info` vì DO-29 (số của cổng, ai trả chi phí kiểm định) còn mở; số nằm ở
  `configs/policies/studio_gate@1.0.0.yaml` nên không chặn mã. Phân tích năng lực Bộ ba nguy hiểm do
  compliance-pdpl/05 giữ; ticket chờ nó. Trần mỗi lần thử mang trên `RunContext`, thay bằng lease khi
  usage-and-limits có.
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026: DO-29.1 và DO-29.2 có lời đáp cho W1 nên
  `needs-triage`; chi tiêu đi qua lease `eval_offline` của `LimitsPort` (DO-21.4, chờ usage-and-limits/03),
  W1 chỉ Bộ kiểm định an ninh nền tảng (H:agent-lifecycle:R4.1), lane chỉ đọc kết quả Phân tích năng lực
  (B:agent-lifecycle:R6.1~compliance-pdpl:R4.2), actor của handler theo OPS-a.1, chờ tenant-config/05 theo
  OPS-b.
