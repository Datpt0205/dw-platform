# 04 — Cổng chất lượng mô phỏng với bộ an ninh nền tảng và duyệt phát hành hai người

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md
Area: studio
Yêu cầu: R2.8, R2.9, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R6.1, R6.2, R6.3, R7.12, AL4, AL5, AL6, AL7, AL8, AL9, AL10, AL11

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
   DEFAULT (DO-02.2), chỉ SELECT, INSERT trên bảng cha. `studio.gate_run_datasets` là W2 cùng bộ đề của tenant.
   Policy drain `app.worker_drain` để lane nhận việc. Cùng thay đổi đăng ký: thêm khóa
   `studio.gate_case_results` (395 ngày, số tạm UNVERIFIED, DROP PARTITION qua
   `platform.drop_expired_partitions` của usage-and-limits/02) vào bản kế tiếp của tệp chính sách retention theo
   định dạng của telemetry-and-audit:R5.6, nên studio-skeleton:R3.7 xanh ngay khi đăng ký; một dòng
   `STUDIO_EXCLUSIONS` cho `studio.gate_case_results` với lý do "xóa khi offboarding bằng
   `platform.purge_tenant_append_only`" (usage-and-limits:R3.8); khóa ngoại `gate_run_id` (RESTRICT) của
   `studio.artifact_versions` cần `_ORDERED_FIRST` xóa `studio.artifact_versions` trước `studio.gate_runs`
   (studio-skeleton:R4.2).
2. Lane `studio_gate` (tối đa một Lượt kiểm định mỗi tenant, một `ReapTarget` cho lượt treo): mỗi lần
   thử là một run `run_mode='simulate'` dùng ngữ cảnh truy cập đóng dấu của người gửi; lane cấp cho mỗi Bước
   `human.approval` của lần thử quyết định duyệt hay từ chối mà Câu kiểm định khai trong `input`, Bước không chờ
   người thật, ghi `studio.step.approval.simulated` và không mở dòng `platform.approval_requests` nào (spec R4.7;
   hành vi của Bước là của workflow-nodes, ticket này thử hợp đồng với một Bước giả); ở ToolExecutor chế độ chạy
   đứng trước phê duyệt của công cụ (tools-and-skills:R2.6), nên công cụ `approval_policy: always` trong lần thử
   không mở yêu cầu phê duyệt thật (spec R4.3). Lượt kiểm định xin
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
   usage-and-limits/02 sửa trước (nối qua usage-and-limits/03). Mỗi Câu kiểm định chạm một Bước `human.approval`
   khai quyết định giả lập (`approve` hay `reject`) trong `input`; câu thiếu khai báo đó bị bộ sinh từ chối. Bộ chấm
   `studio.*` hợp nhất bằng `merge_graders` ở composition root của worker; `dw_evals` không biết chúng.
4. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations`
   (`studio.evals.run`); `GET /api/v1/studio/gate-runs`, `/{id}`, `/{id}/cases` (`studio.lifecycle.read`). Cùng
   migration của ticket: đăng ký khóa `studio.publish.approve`, `studio.lifecycle.read`, `studio.evals.run` trong
   `platform.permissions` của tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo
   bảng phân loại của ticket đó).
5. Phát hành hai người: mọi chuyển sang `awaiting_approval` (lane khi gate đạt, bước 7 với loại không cổng) đi
   qua `LifecycleService`, mở trong cùng giao dịch một yêu cầu phê duyệt `studio.publish.<kind>` (`agent`,
   `workflow`, `object`; loại phê duyệt `studio.publish.object` là của custom-objects), `requested_by` là
   `submitted_by` của dòng phiên bản, `required_scope` `studio.publish.approve`, payload chỉ id và mã gồm
   `author_ids` dựng từ `contributor_ids` và `submitted_by` của dòng phiên bản trong cùng giao dịch. Thêm
   `studio.publish.` vào `strict_approval_prefixes` bằng đúng một dòng `|=` ở composition root của API và worker
   (kèm chú thích), không sửa dòng của ticket khác (`studio.lifecycle.` của ticket 01, `config.` của
   tenant-config/05, `studio.step.` của workflow-nodes/06), và test khẳng định tập tiền tố nghiêm ở cả hai chỗ
   chứa `studio.publish.`; một khóa `decision_guards` `require_not_author` từ chối người quyết trong `author_ids`
   và từ chối payload thiếu `author_ids`. Người xin đọc được yêu cầu của mình với `can_decide` false qua
   `ApprovalAudience` của ADR-0004 (Accepted) sửa đổi 07/10/2026 (spec R5.8). Handler worker
   `studio.publish.<kind>.decided` đăng ký cho mọi loại trong `ArtifactKindRegistry`, idempotent trên id yêu cầu:
   hỏi `RunControlPort`, Đóng băng của công ty hay nền tảng đang mở thì không đưa phiên bản sang `live` và từ
   chối lần xử lý với `tenant_frozen` hay `platform_frozen` (spec R7.12); không thì, actor là người quyết định
   với `details.lane` là tên lane và `details.path` `approved` (ADR-0011 (Accepted)), đưa phiên bản Đang dùng qua
   dịch vụ phát hành của tenant-config cùng móc phát hành của loại, bản cũ Đã gỡ (`superseded`), audit
   `studio.version.published`, outbox `studio.version.live`; từ chối → `draft`. Nhãn loại approval và liên kết "Xem diff" ở điểm cắm
   `apps/web/components/tool-approval.tsx`. Lane hết hạn phê duyệt phát hành: hủy yêu cầu quá
   `publish_approval_ttl_days`, đưa phiên bản về `draft`, audit qua `lane_audit_event` với actor
   `system:<lane>` vì lane tự làm (spec R5.7).
6. Chốt chặn Phân tích năng lực: trước khi mở yêu cầu phê duyệt, lane đọc kết quả Phân tích năng lực mà
   compliance-pdpl/05 ghi ở `studio.version_assessments` cho Mã băm định nghĩa của Bản ứng viên; thiếu kết
   quả, đường bộ ba chưa giải quyết, Mức tự chủ vượt mức hay công cụ chưa phân loại → cổng trượt, không mở
   yêu cầu phê duyệt, phiên bản về `draft` (spec R6.1, R6.2). Mã 422 lúc gửi kiểm định là của compliance-pdpl
   (compliance-pdpl:R4.2, R4.3, R4.4). Mức sàn duyệt của công cụ không bị hạ bởi cấu hình công ty, người
   dựng hay Mức tự chủ (ADR-0125 (Accepted)).
7. Nhánh gửi của loại có `has_quality_gate = false` trên route của ticket 03 (spec R2.8, R2.9;
   ADR-0120 (Accepted) quyết 1-2): trong giao dịch gửi, niêm phong qua tenant-config (tenant-config:R2.13,
   tenant-config:R2.16), gọi bộ so sánh mà mục `ArtifactKindRegistry` của loại cấp (của custom-objects cho
   `object`; loại không có bộ so sánh, như công cụ, luôn `tighten_only` false) rồi ghi `tighten_only` và
   `compared_live_hash`. Chỉ siết → `draft → live` trong giao dịch của người gửi, bản cũ Đã gỡ (`superseded`),
   audit `studio.version.published` với actor là người gửi và `details.path` `tighten_only`, outbox
   `studio.version.live`, không mở phê duyệt. Không chỉ siết, hay chưa có bản `live` → sang
   `awaiting_approval` với yêu cầu phê duyệt của bước 5. Test với loại `object` đăng ký trong test cùng một bộ so
   sánh giả; đường thật với loại và bộ so sánh của custom-objects/02 là custom-objects/06, ticket chờ ticket này.

## Tiêu chí chấp nhận

- [ ] R4.1 (AL7): một Câu an ninh trượt → cổng trượt, phiên bản về `draft`; tất cả đạt → `awaiting_approval`;
      không route nào ghi Câu an ninh.
- [ ] R4.2 (AL7): một bộ chấm trả `unknown` chặn như trượt; gỡ luật `unknown` trong `evaluate_gate` → test đỏ.
- [ ] R4.3 (AL8): agent có công cụ gửi Zalo `approval_policy: always` trong Lượt kiểm định → egress giả không
      nhận lời gọi, 0 dòng `platform.approval_requests` mới; gỡ chặn `simulate` ở executor hay đặt phê duyệt trước
      chế độ chạy → test đỏ.
- [ ] R4.7 (AL8): lần thử của quy trình có một Bước `human.approval` (Bước giả theo hợp đồng của workflow-nodes)
      với Câu kiểm định khai `reject` → nhánh từ chối chạy, audit `studio.step.approval.simulated` mang `reject`,
      0 dòng `platform.approval_requests`; Câu thiếu khai báo → bộ sinh từ chối câu đó.
- [ ] R4.4 (AL9): chi phí xấu nhất vượt trần mỗi lượt → Lượt kiểm định `error` `limit_exceeded` trước mọi
      `worker_runs`; `LimitsPort` giả từ chối lease `eval_offline` → như trên, 0 lời gọi model.
- [ ] R4.5 (AL9): một lần thử chạm trần mỗi lần thử → Câu đó trượt với `cost_bound`, các câu khác vẫn
      chấm; gỡ trần mỗi lần thử → test đỏ.
- [ ] R4.6: hai Lượt kiểm định cùng khóa bằng chứng → lượt sau dùng lại, không tạo run.
- [ ] R5.1 (AL5): khi gate đạt, yêu cầu phê duyệt mở trong cùng giao dịch `evaluating → awaiting_approval`,
      payload chỉ id và mã, `requested_by` bằng `submitted_by`; `author_ids` bằng đúng `contributor_ids` cộng
      `submitted_by` của dòng phiên bản; dựng thiếu một người → test khớp đỏ; gửi một phiên bản `object` không chỉ
      siết → yêu cầu `studio.publish.object` mở trong giao dịch gửi với cùng payload.
- [ ] R5.2 (AL5): Tác giả có scope duyệt → 409 `author_cannot_approve`; người gửi → 409.
- [ ] R5.3 (AL5): payload thiếu `author_ids` → quyết định bị từ chối; gỡ guard → test đỏ.
- [ ] R5.4 (AL6): `platform_admin` không giữ tem `studio.publish.approve` và không phải người xin → 404 khi đọc
      và khi quyết định.
- [ ] R5.8 (AL6): người gửi không giữ tem mở yêu cầu phê duyệt phát hành của mình → 200 với `can_decide` false;
      gỡ luật người xin → 404, test đỏ.
- [ ] R5.5: duyệt → bản mới Đang dùng qua dịch vụ phát hành của tenant-config, bản cũ Đã gỡ (`superseded`)
      trong một vòng outbox, audit có `details.path` `approved`; với loại `object` móc phát hành của loại chạy
      trong cùng giao dịch; giao hai lần cùng sự kiện → một kết quả; từ chối → `draft`.
- [ ] R5.6 (AL4): chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514;
      `draft → live` của `object` với `tighten_only` false, hay với `compared_live_hash` cũ sau khi bản `live`
      đổi → 23514; gỡ CHECK hay luật nhánh → test đỏ.
- [ ] R2.8 (AL4): phiên bản `object` mà bộ so sánh giả báo chỉ siết → `live` trong giao dịch gửi với
      `tighten_only` và `compared_live_hash` đã ghi; báo không chỉ siết, hay chưa có bản `live` → `awaiting_approval`
      kèm yêu cầu phê duyệt; công cụ (không bộ so sánh) → luôn `awaiting_approval`.
- [ ] R2.9: nhánh chỉ siết → bản cũ Đã gỡ (`superseded`), audit `studio.version.published` với actor là người
      gửi và `details.path` `tighten_only`, outbox `studio.version.live`, cùng giao dịch; rollback → không audit.
- [ ] R7.12 (AL11): Đóng băng công ty rồi giao `studio.publish.agent.decided` của một quyết định duyệt →
      phiên bản vẫn `awaiting_approval`, lần xử lý từ chối `tenant_frozen`; gỡ kiểm trong handler → test đỏ.
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
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: nhánh gửi của loại không cổng và nhánh chỉ siết
  (Q-R6; spec R2.8, R2.9), phê duyệt và handler `studio.publish.<kind>` cho mọi loại (custom-objects/06 chờ ticket
  này), `requested_by` và người xin chỉ đọc (spec R5.8, ADR-0004 (Accepted)), Bước `human.approval` giả lập trong
  lần thử (N2; spec R4.7), handler từ chối khi Đóng băng (spec R7.12), đăng ký ba khóa của ticket và đổi tên
  `studio.evals.run`, thời hạn và dòng `STUDIO_EXCLUSIONS` của `studio.gate_case_results`. Một dòng `|=` cho
  `studio.publish.` kèm test tập tiền tố thay cho cạnh tới workflow-nodes/06, cùng cách tenant-config/05 làm, để
  ticket này không phải chờ Bước `tool.call` và `human.approval`.
