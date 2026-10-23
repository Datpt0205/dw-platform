# 04 — Cổng chất lượng mô phỏng với bộ an ninh nền tảng và duyệt phát hành hai người

Status: needs-info (DO-29)
Blocked by: 02, 03, .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R6.1, R6.2, R6.3, AL4, AL5, AL6, AL7, AL8, AL9, AL10

## Mục tiêu

Lượt kiểm định chạy ở chế độ Mô phỏng với trần chi phí, bộ đề của tenant và Bộ kiểm định an ninh nền
tảng (đạt 100%); phát hành cần một người không phải Tác giả duyệt và bị chặn khi có Bộ ba nguy hiểm
hay công cụ chưa phân loại (spec R4, R5, R6). Phân tích năng lực do compliance-pdpl giữ; lát này gọi
nó ở cổng phát hành.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `studio.gate_runs` (`status` CHECK `queued`, `running`,
   `passed`, `failed`, `error`, `cancelled`; `purpose` CHECK `gate`, `dry`; khóa bằng chứng
   `definition_hash`, `gate_policy_ref`, `security_suite_ref`, mã băm nội dung bộ đề; `spend_cap_usd`,
   `spent_usd`, `resolved_at_gate` jsonb, `verdict` jsonb); `studio.gate_run_datasets` (FK bộ đề
   RESTRICT); `studio.gate_case_results` phân vùng theo tháng với DEFAULT, thêm vào
   `platform.ensure_time_partitions`, ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT cùng
   migration, thu hồi UPDATE/DELETE của `dw_app`. Policy drain `app.worker_drain` để lane nhận việc.
2. Lane `studio_gate` (tối đa một Lượt kiểm định mỗi tenant, một `ReapTarget` cho lượt treo): mỗi lần
   thử là một run `run_mode='simulate'` dùng ngữ cảnh truy cập đóng dấu của người gửi; trần mỗi lần thử
   `min(profile.max_cost_usd_per_run, policy.max_trial_cost_usd)` mang trên `RunContext`; trước lời gọi
   model đầu tiên lane tính chi phí xấu nhất và từ chối trên trần mỗi lượt. Audit `studio.gate_run.started`,
   `studio.gate_run.completed` (actor `system:studio_gate`); thông báo người gửi.
3. Bộ sinh Bộ kiểm định an ninh nền tảng ở `configs/evals/studio_security_suite@1.0.0.yaml` và Chính
   sách cổng ở `configs/policies/studio_gate@1.0.0.yaml` (fields: `security_pass_rate` cố định 1.0,
   `min_cases_total`, `pass_rate_min`, `pass_k`, `max_trial_cost_usd`, `max_gate_worst_case_usd`,
   `stale_draft_days`, `publish_approval_ttl_days`; số seed ghi ở Comments, DO-29); cả hai ghim trong
   release manifest. Bộ chấm `studio.*` hợp nhất bằng `merge_graders` ở composition root của worker;
   `dw_evals` không biết chúng.
4. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations`
   (`studio.eval.run`); `GET /api/v1/studio/gate-runs`, `/{id}`, `/{id}/cases` (`studio.lifecycle.read`).
5. Phát hành hai người: KHI gate đạt, lane mở một yêu cầu phê duyệt trong giao dịch `evaluating →
awaiting_approval` (loại `studio.publish.agent` hay `studio.publish.workflow`, `required_scope`
   `studio.publish.approve`, payload chỉ id và mã gồm `author_ids`). Thêm `studio.publish.`,
   `studio.lifecycle.` vào `strict_approval_prefixes` bằng `|=` (kèm chú thích); `decision_guards`
   `require_not_author` từ chối người quyết trong `author_ids` và từ chối payload thiếu `author_ids`.
   Handler worker `studio.publish.agent.decided`, `studio.publish.workflow.decided` idempotent trên id
   yêu cầu, actor là người quyết định: đưa phiên bản Đang dùng, bản cũ Đã gỡ (`superseded`), audit
   `studio.version.published`, outbox `studio.version.live`; từ chối → `draft`. Nhãn loại approval và
   liên kết "Xem diff" ở điểm cắm `apps/web/components/tool-approval.tsx`; lane hết hạn phê duyệt phát
   hành (v1).
6. Cổng Bộ ba nguy hiểm: trước khi mở yêu cầu phê duyệt, đọc kết quả Phân tích năng lực do compliance-pdpl
   ghi; nếu chưa giải quyết thì 422 `capability_trifecta_autonomy` kèm đường vi phạm; nếu có công cụ
   thiếu phân loại thì 422 `tool_unclassified`. Mức sàn duyệt của công cụ không bị hạ bởi cấu hình công
   ty, người dựng hay Mức tự chủ (ADR-0125 (Proposed)).

## Tiêu chí chấp nhận

- [ ] R4.1 (AL7): một Câu an ninh trượt → cổng trượt, phiên bản về `draft`; tất cả đạt → `awaiting_approval`;
      không route nào ghi Câu an ninh.
- [ ] R4.2 (AL7): một bộ chấm trả `unknown` chặn như trượt; gỡ luật `unknown` trong `evaluate_gate` → test đỏ.
- [ ] R4.3 (AL8): agent có công cụ gửi Zalo trong Lượt kiểm định → egress giả không nhận lời gọi; gỡ chặn
      `simulate` ở executor → test đỏ.
- [ ] R4.4 (AL9): chi phí xấu nhất vượt trần mỗi lượt → 422 trước mọi `worker_runs`.
- [ ] R4.5 (AL9): một lần thử chạm trần mỗi lần thử → Câu đó trượt với `cost_bound`, các câu khác vẫn
      chấm; gỡ trần mỗi lần thử → test đỏ.
- [ ] R4.6: hai Lượt kiểm định cùng khóa bằng chứng → lượt sau dùng lại, không tạo run.
- [ ] R5.1: khi gate đạt, yêu cầu phê duyệt mở trong cùng giao dịch `evaluating → awaiting_approval`,
      payload chỉ id và mã.
- [ ] R5.2 (AL5): Tác giả có scope duyệt → 409 `author_cannot_approve`; người gửi → 409.
- [ ] R5.3 (AL5): payload thiếu `author_ids` → quyết định bị từ chối; gỡ guard → test đỏ.
- [ ] R5.4 (AL6): `platform_admin` không giữ tem `studio.publish.approve` → 404 khi đọc và khi quyết định.
- [ ] R5.5: duyệt → bản mới Đang dùng, bản cũ Đã gỡ (`superseded`) trong một vòng outbox; giao hai lần
      cùng sự kiện → một kết quả; từ chối → `draft`.
- [ ] R5.6 (AL4): chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514;
      gỡ CHECK → test đỏ.
- [ ] R6.1 (AL10): agent đọc lead, nhận nội dung từ form, có công cụ gửi Zalo, khai A3 → 422
      `capability_trifecta_autonomy`; khai A2 → qua; gỡ kiểm → lượt `live` cho thấy công cụ gửi chạy không
      duyệt (đỏ).
- [ ] R6.2 (AL10): công cụ thiếu phân loại → 422 `tool_unclassified`.
- [ ] R6.3 (AL10): cấu hình công ty không hạ được mức sàn duyệt của công cụ trọng yếu; chỉ siết thêm được.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:244`; spec: R5.1, R5.5 (yêu cầu
  phê duyệt không lượt chạy phát `<type>.decided` qua outbox).
- `apps/api/src/dw_api/bootstrap/runtime.py:237`; spec: R5.2 (prefix nghiêm thêm bằng `|=`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R6.2 (phân loại công
  cụ là bên đọc đầu tiên); ADR-0120 (Proposed) quyết 2-3, ADR-0125 (Proposed).

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 07 và 09, cộng seam eval của B1 studio-skeleton 10.
  `needs-info` vì DO-29 (số của cổng, ai trả chi phí kiểm định) còn mở; số nằm ở
  `configs/policies/studio_gate@1.0.0.yaml` nên không chặn mã. Phân tích năng lực Bộ ba nguy hiểm do
  compliance-pdpl/05 giữ; ticket chờ nó. Trần mỗi lần thử mang trên `RunContext`, thay bằng lease khi
  usage-and-limits có.
