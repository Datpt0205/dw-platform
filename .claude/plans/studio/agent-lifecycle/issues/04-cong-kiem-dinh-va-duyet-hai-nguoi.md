# 04 — Cổng chất lượng mô phỏng với bộ an ninh nền tảng và duyệt phát hành hai người

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.9, R2.8, R2.9, R2.10, R2.11, R2.12, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R6.1, R6.2, R6.3, R7.9, R7.12, R7.13, AL4, AL5, AL6, AL7, AL8, AL9, AL10, AL11, AL19, AL20, AL21, AL22

## Mục tiêu

Lượt kiểm định chạy ở chế độ Mô phỏng với Bộ kiểm định an ninh nền tảng (đạt 100%; bộ đề của tenant là
W2) dưới trần chi phí giữ trước qua `LimitsPort`; phát hành cần một người không phải Tác giả duyệt, mọi Điểm gắn
bắt buộc đã có giá trị duyệt, và không đè một bản Đang dùng mới hơn bản đã so lúc gửi; cổng không mở phê duyệt khi
Phân tích năng lực thiếu hay chưa đạt (spec R2, R4, R5, R6). Phân tích năng lực do
compliance-pdpl giữ và trả 422 lúc gửi kiểm định; lát này chỉ đọc kết quả đã ghi làm chốt chặn.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `studio.gate_runs` (`status` CHECK `queued`, `running`,
   `passed`, `failed`, `error`, `cancelled`; `purpose` CHECK `gate`, `dry`; khóa bằng chứng
   `effective_hash`, `gate_policy_ref`, `security_suite_ref`, danh sách mã băm bộ đề của tenant (rỗng ở
   W1); `definition_hash` cho trigger giai đoạn; `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb,
   `verdict` jsonb; `created_at timestamptz NOT NULL`; `uq_gate_runs_tenant_id_id UNIQUE (tenant_id, id)`; index
   `(tenant_id, created_at DESC, id DESC)` cho keyset của `GET /api/v1/studio/gate-runs`); cùng revision thêm FK ghép
   `(tenant_id, gate_run_id)` của `studio.artifact_versions` (cột của ticket 03) tới `studio.gate_runs (tenant_id, id)`
   ON DELETE RESTRICT có index riêng (spec R1.9); `studio.gate_case_results` có `gate_run_id` FK ghép
   `(tenant_id, gate_run_id)` tới `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT, để một DELETE lên Lượt kiểm
   định không kéo theo xóa dòng chỉ thêm, và index `(tenant_id, gate_run_id, case_id)` trên bảng cha mang khóa ngoại
   đó và keyset của `GET .../{id}/cases` (CLAUDE.md, Data model rules), phân vùng theo tháng với DEFAULT, đăng ký bằng một dòng
   `platform.time_partitioned_tables` (`append_only = true`), không sửa thân hàm; ENABLE/FORCE RLS và policy
   tenant trên cha và DEFAULT cùng migration; `dw_app` không giữ quyền nào trên partition nào, kể cả
   DEFAULT (DO-02.2), chỉ SELECT, INSERT trên bảng cha. `studio.gate_run_datasets` là W2 cùng bộ đề của tenant.
   Policy drain `app.worker_drain` để lane nhận việc. Cùng thay đổi đăng ký: thêm khóa
   `studio.gate_case_results` (395 ngày, số tạm UNVERIFIED, DROP PARTITION qua
   `platform.drop_expired_partitions` của usage-and-limits/02) vào bản kế tiếp của tệp chính sách retention theo
   định dạng của telemetry-and-audit:R5.6, nên studio-skeleton:R3.7 xanh ngay khi đăng ký; trong chuỗi phiên bản của
   tệp, bản của ticket này đứng ngay sau bản của telemetry-and-audit/03, ticket này chờ ticket đó; một dòng
   `STUDIO_EXCLUSIONS` cho `studio.gate_case_results` với lý do "xóa khi offboarding bằng
   `platform.purge_tenant_append_only`" (usage-and-limits:R3.10); hàm đó chạy trước mọi bảng thường
   (usage-and-limits:R3.11), nên khóa ngoại `gate_run_id` (RESTRICT) của `studio.gate_case_results` được thỏa không
   cần dòng `_ORDERED_FIRST`, còn khóa ngoại `gate_run_id` (RESTRICT) của `studio.artifact_versions` cần
   `_ORDERED_FIRST` xóa `studio.artifact_versions` trước `studio.gate_runs` (studio-skeleton:R4.2).
2. Lane `studio_gate` (tối đa một Lượt kiểm định mỗi tenant, một `ReapTarget` cho lượt treo): mỗi lần
   thử là một run `run_mode='simulate'` dùng ngữ cảnh truy cập đóng dấu của người gửi; lane cấp cho mỗi Bước
   `human.approval` của lần thử quyết định `approved` hay `rejected` (từ vựng của workflow-nodes:R9.9, bước 3) mà Câu
   kiểm định khai trong `input`, Bước không chờ người thật, ghi `studio.step.approval.simulated` và không mở dòng
   `platform.approval_requests` nào (spec R4.7; hành vi của Bước là của workflow-nodes, ticket này thử hợp đồng với
   một Bước giả); ở ToolExecutor chế độ chạy đứng trước phê duyệt của công cụ (tools-and-skills:R2.6), nên công cụ
   `approval_policy: always` trong lần thử không mở yêu cầu phê duyệt thật (spec R4.3). Lượt kiểm định xin
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
   khai quyết định giả lập trong `input` theo từ vựng `approved` hay `rejected` mà workflow-nodes:R9.9 làm chủ; câu
   thiếu khai báo đó bị bộ sinh từ chối. Bộ chấm
   `studio.*` hợp nhất bằng `merge_graders` ở composition root của worker; `dw_evals` không biết chúng.
4. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations`
   (`studio.evals.run`) nhận phiên bản `draft` (spec R4.8): lane chạy Kiểm định thử, dòng `studio.gate_runs` có
   `purpose` `dry`, với trần và lease `eval_offline` của bước 2; mỗi lần thử là một run `run_mode='simulate'` có gốc là
   bản Nháp, xin qua `RunRequestService`, nơi bản kê ghim giai đoạn `draft` và mã băm tạm của nội dung nháp và bộ kiểm
   trả mọi lỗi của loại chạy trên nội dung đó (workflow-engine:R3.9, workflow-engine:R3.11; tenant-config:R6.1;
   ADR-0109 (Accepted) quyết 6); graph biên dịch theo mã băm ghim (workflow-engine:R4.2 cho quy trình;
   agent-builder:R3.1, agent-builder:R3.3 cho agent, ADR-0117 (Accepted) quyết 5). `RunRequestService` từ chối lần thử
   → Kiểm định thử `error` kèm mọi lỗi, không xin thêm lần thử (spec R4.9). Kiểm định thử không niêm phong, không đổi
   giai đoạn, không mở phê duyệt. Test dùng bản Nháp quy trình thật và một nguồn graph agent giả theo khóa
   `(tenant_id, agent_version_id, mã băm ghim)`; đường thật của agent là agent-builder/03.
   `GET /api/v1/studio/gate-runs` (keyset `(created_at DESC, id DESC)`), `/{id}`, `/{id}/cases`
   (keyset `case_id`) (`studio.lifecycle.read`), mỗi thứ tự đi trên index của bước 1. Cùng migration của ticket: đăng
   ký khóa `studio.publish.approve`, `studio.lifecycle.read`, `studio.evals.run` trong `platform.permissions` của
   tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket đó);
   INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` (`true`) của
   tenant-rbac/02, ticket này chờ ticket đó.
5. Phát hành hai người: mọi chuyển sang `awaiting_approval` (lane khi gate đạt, bước 7 với loại không cổng) đi
   qua `LifecycleService`, mở trong cùng giao dịch một yêu cầu phê duyệt `studio.publish.<kind>` (`agent`,
   `workflow`, `object`, `endpoint`; loại phê duyệt `studio.publish.object` là của custom-objects, Nguồn dữ liệu mở
   `studio.publish.endpoint` theo workflow-triggers:R4.8), `requested_by` là
   `submitted_by` của dòng phiên bản, `required_scope` `studio.publish.approve`, payload chỉ id và mã gồm
   `author_ids` dựng từ `contributor_ids` và `submitted_by` của dòng phiên bản trong cùng giao dịch. Thêm
   `studio.publish.` vào `strict_approval_prefixes` bằng đúng một dòng `|=` ở composition root của API và worker
   (kèm chú thích), không sửa dòng của ticket khác (`studio.lifecycle.` của ticket 01, `config.` của
   tenant-config/05, `studio.step.` của workflow-nodes/06), và test khẳng định tập tiền tố nghiêm ở cả hai chỗ
   chứa `studio.publish.`; một khóa `decision_guards` `require_not_author` từ chối người quyết trong `author_ids`
   và từ chối payload thiếu `author_ids`. Kiểm tiền tố nghiêm chạy trước mọi guard (ADR-0104 (Accepted) quyết 11),
   nên người gửi, là `requested_by`, tự duyệt nhận 409 `conflict` với `details.reason_code` `second_person_required`
   mà tenant-config/05 đặt ở `_enforce_strict_rules`, còn guard chỉ gặp người đóng góp không phải người xin và trả
   `author_cannot_approve` (spec R5.2; V4.P9). Người xin đọc được yêu cầu của mình với `can_decide` false qua
   `ApprovalAudience` của ADR-0004 (Accepted) sửa đổi 07/10/2026 (spec R5.8). Handler worker
   `studio.publish.<kind>.decided` đăng ký cho mọi loại trong `ArtifactKindRegistry`, idempotent trên id yêu cầu:
   hỏi `RunControlPort`, Đóng băng của công ty hay nền tảng đang mở thì không đưa phiên bản sang `live` và từ
   chối lần xử lý với `tenant_frozen` hay `platform_frozen` (spec R7.12); hỏi lại `PublishBindingsCheck` (bước 8),
   `binding_unset` thì không đưa phiên bản sang `live` và từ chối lần xử lý với `binding_unset` (spec R5.10);
   `compared_live_hash` khác mã của phiên bản Đang dùng mà lần phát hành này sẽ thay, hay khác NULL khi không có bản
   nào, thì không phát hành: phiên bản về `draft` với
   `details.reason_code` `base_changed`, audit `studio.version.returned_to_draft` với actor là người quyết định và
   `details.lane` là tên lane, cùng giao dịch (spec R5.9); không thì, actor là người quyết định
   với `details.lane` là tên lane và `details.path` `approved` (ADR-0011 (Accepted)), `LifecycleService`, bên duy nhất
   ghi `live` (ADR-0120 (Accepted) quyết 1), gỡ bản cũ (`superseded`) rồi đưa phiên bản sang Đang dùng và gọi móc
   phát hành `publish_hook` mà mục `ArtifactKindRegistry` của loại mang (tenant-config:R2.15, tenant-config/02;
   ADR-0109 (Accepted) quyết 1), đúng một audit
   `studio.version.published` (móc phát hành của loại làm phần việc của loại, như áp định nghĩa của `object` hay ghi
   giới hạn dữ liệu của `agent`, `workflow` vào `studio.actor_boundaries` qua `ActorBoundaryPort` của record-access,
   agent-builder:R1.9, workflow-engine:R1.7, ADR-0117 (Accepted) quyết 3, và không ghi audit), outbox
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
7. Nhánh gửi của loại có `has_quality_gate = false` trên route của ticket 03 (spec R2.8, R2.9;
   ADR-0120 (Accepted) quyết 1-2): trong giao dịch gửi, gọi bước niêm phong của tenant-config, bước cấp `version_no`,
   ghi mã băm và so `row_version` mà không đổi giai đoạn (tenant-config:R2.7, tenant-config:R2.17), với
   `expected_row_version` là giá trị `If-Match` mà route của ticket 03 nhận, như nhánh có
   cổng (spec R2.12), gọi bộ so sánh mà mục `ArtifactKindRegistry` của loại cấp (của custom-objects cho
   `object`; loại không có bộ so sánh, như Nguồn dữ liệu `endpoint`, luôn `tighten_only` false) rồi ghi
   `tighten_only` và `compared_live_hash` (spec R2.10). Hỏi `RunControlPort` sau khi so: Đóng băng của nền tảng → 409
   `platform_frozen`; Đóng băng của công ty → 409 `tenant_frozen` trừ khi bộ so sánh báo chỉ siết, vì nhánh chỉ siết
   đi qua được Đóng băng của công ty (spec R7.9, R7.13); giao dịch lùi, phiên bản giữ `draft`. Chỉ siết →
   `LifecycleService` gỡ bản cũ (`superseded`) rồi đưa phiên bản `draft → live` trong giao dịch của người gửi,
   `publish_hook` của mục `ArtifactKindRegistry` của loại chạy trong cùng giao dịch, đúng một audit
   `studio.version.published` với actor là người gửi và `details.path` `tighten_only`, outbox `studio.version.live`,
   không mở phê duyệt (spec R2.9). Không chỉ siết, hay chưa có bản `live` → `LifecycleService` đưa phiên bản sang
   `awaiting_approval` với yêu cầu phê duyệt của bước 5. Test với loại `object`
   đăng ký trong test cùng một bộ so sánh giả, và một loại không cổng đăng ký trong test không có bộ so sánh (hình của
   `endpoint`); đường thật với loại và bộ so sánh của custom-objects/02 là custom-objects/06, với loại `endpoint` là
   workflow-triggers/02, hai ticket chờ ticket này.
8. Protocol `PublishBindingsCheck` do spec này khai, cạnh Protocol `SubmitCheck` của ticket 03: `satisfied(version_id)`
   trả đạt, hay `binding_unset` kèm tên các Điểm gắn bắt buộc chưa có giá trị trong Bộ giá trị gắn đã duyệt;
   tenant-config/05 đáp ứng bằng `BindingStatus.satisfied` ở composition root (tenant-config:R7.2). Route gửi của
   ticket 03 hỏi nó cho mọi loại trước khi chuyển phiên bản khỏi `draft`: `binding_unset` → 409 `binding_unset` với
   tên các Điểm gắn trong `details`, giao dịch lùi, phiên bản giữ `draft` (spec R2.11); handler của bước 5 hỏi lại.

## Tiêu chí chấp nhận

- [ ] R4.1 (AL7): một Câu an ninh trượt → cổng trượt, phiên bản về `draft`; tất cả đạt → `awaiting_approval`;
      không route nào ghi Câu an ninh.
- [ ] R4.2 (AL7): một bộ chấm trả `unknown` chặn như trượt; gỡ luật `unknown` trong `evaluate_gate` → test đỏ.
- [ ] R4.3 (AL8): agent có công cụ gửi Zalo `approval_policy: always` trong Lượt kiểm định → egress giả không
      nhận lời gọi, 0 dòng `platform.approval_requests` mới; gỡ chặn `simulate` ở executor hay đặt phê duyệt trước
      chế độ chạy → test đỏ.
- [ ] R4.7 (AL8): lần thử của quy trình có một Bước `human.approval` (Bước giả theo hợp đồng của workflow-nodes)
      với Câu kiểm định khai `rejected` → nhánh từ chối chạy, audit `studio.step.approval.simulated` mang
      `rejected`, 0 dòng `platform.approval_requests`; Câu khai `approved` → nhánh duyệt chạy; Câu thiếu khai báo →
      bộ sinh từ chối câu đó.
- [ ] R4.4 (AL9): chi phí xấu nhất vượt trần mỗi lượt → Lượt kiểm định `error` `limit_exceeded` trước mọi
      `worker_runs`; `LimitsPort` giả từ chối lease `eval_offline` → như trên, 0 lời gọi model.
- [ ] R4.5 (AL9): một lần thử chạm trần mỗi lần thử → Câu đó trượt với `cost_bound`, các câu khác vẫn
      chấm; gỡ trần mỗi lần thử → test đỏ.
- [ ] R4.6: hai Lượt kiểm định cùng khóa bằng chứng → lượt sau dùng lại, không tạo run.
- [ ] R4.8 (AL22): Kiểm định thử một bản Nháp quy trình → mỗi lần thử là run `simulate` mà bản kê ghim giai đoạn
      `draft` và mã băm tạm, phiên bản vẫn `draft`, `gate_run_id` NULL, 0 dòng `platform.approval_requests`; sửa nháp
      rồi Kiểm định thử lại → lần thử ghim mã băm tạm mới và chạy nội dung mới; cùng hai ca với một bản Nháp agent
      qua nguồn graph giả theo khóa có mã băm ghim; bỏ mã băm ghim khỏi khóa cache graph → lần sau chạy nội dung cũ,
      test đỏ.
- [ ] R4.9 (AL22): `RunRequestService` từ chối lần thử vì nội dung nháp trượt bộ kiểm của loại → Kiểm định thử `error`
      kèm mọi lỗi, 0 `worker_runs`, không lần thử nào được xin thêm; nuốt lần từ chối rồi xin lần thử kế → test đỏ.
- [ ] R1.9 (AL21): bằng vai migrator, dòng phiên bản của tenant A đặt `gate_run_id` là id một Lượt kiểm định của
      tenant B, và một dòng `studio.gate_case_results` của A trỏ tới Lượt kiểm định đó → FK ghép từ chối cả hai, không
      ghi; cùng id của tenant A → nhận; đổi một FK sang một cột → test đỏ.
- [ ] R5.1 (AL5): khi gate đạt, yêu cầu phê duyệt mở trong cùng giao dịch `evaluating → awaiting_approval`,
      payload chỉ id và mã, `requested_by` bằng `submitted_by`; `author_ids` bằng đúng `contributor_ids` cộng
      `submitted_by` của dòng phiên bản; dựng thiếu một người → test khớp đỏ; gửi một phiên bản `object` không chỉ
      siết → yêu cầu `studio.publish.object` mở trong giao dịch gửi với cùng payload.
- [ ] R5.2 (AL5): người đóng góp không phải người xin, có scope duyệt → 409 `author_cannot_approve`; người gửi tự
      duyệt → 409 `conflict` với `details.reason_code` `second_person_required`, vì kiểm tiền tố nghiêm chạy trước
      guard; bỏ `studio.publish.` khỏi tiền tố nghiêm → người gửi nhận `author_cannot_approve`, test đỏ.
- [ ] R5.3 (AL5): payload thiếu `author_ids` → quyết định bị từ chối; gỡ guard → test đỏ.
- [ ] R5.4 (AL6): `platform_admin` không giữ tem `studio.publish.approve` và không phải người xin → 404 khi đọc
      và khi quyết định.
- [ ] R5.8 (AL6): người gửi không giữ tem mở yêu cầu phê duyệt phát hành của mình → 200 với `can_decide` false;
      gỡ luật người xin → 404, test đỏ.
- [ ] R5.5: duyệt → bản mới Đang dùng qua `LifecycleService`, bản cũ Đã gỡ (`superseded`)
      trong một vòng outbox, audit có `details.path` `approved`; với loại `object` móc phát hành trên mục
      `ArtifactKindRegistry` của loại chạy trong cùng giao dịch và có đúng một dòng `studio.version.published`; bỏ lời
      gọi móc khỏi handler → móc giả không được gọi, test đỏ; giao hai lần cùng sự kiện → một kết quả;
      từ chối → `draft`.
- [ ] R5.9 (AL19): một phiên bản `object` chỉ siết lên `live` trong lúc một Bản ứng viên của cùng thành phần chờ
      duyệt, rồi duyệt Bản ứng viên → nó về `draft` với `details.reason_code` `base_changed` và một audit
      `studio.version.returned_to_draft` đứng tên người quyết định, bản `live` vẫn là bản chỉ siết; gỡ kiểm khỏi
      handler → handler hỏng ở 23514 của trigger, phiên bản không về `draft`, test đỏ.
- [ ] R5.10 (AL20): `PublishBindingsCheck` giả trả `binding_unset` khi giao `studio.publish.workflow.decided` của một
      quyết định duyệt → phiên bản vẫn `awaiting_approval`, lần xử lý từ chối `binding_unset`; gỡ kiểm trong handler
      → test đỏ.
- [ ] R5.6 (AL4): chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514;
      `draft → live` của `object` với `tighten_only` false, hay với `compared_live_hash` cũ sau khi bản `live`
      đổi → 23514; gỡ CHECK hay luật nhánh → test đỏ.
- [ ] R2.8 (AL4): phiên bản `object` mà bộ so sánh giả báo chỉ siết → `live` trong giao dịch gửi với
      `tighten_only` và `compared_live_hash` đã ghi; báo không chỉ siết, hay chưa có bản `live` → `awaiting_approval`
      kèm yêu cầu phê duyệt; loại không cổng không có bộ so sánh (hình của `endpoint`), kể cả thay đổi chỉ siết →
      luôn `awaiting_approval` kèm yêu cầu phê duyệt.
- [ ] R2.9: nhánh chỉ siết → bản cũ Đã gỡ (`superseded`), móc phát hành của loại được gọi, đúng một dòng
      `studio.version.published` với actor là người gửi và `details.path` `tighten_only`, outbox `studio.version.live`,
      cùng giao dịch; rollback → không audit.
- [ ] R2.10: gửi một phiên bản `object` khi đã có bản `live` → `compared_live_hash` bằng `definition_hash` của bản đó
      ở cả nhánh chỉ siết lẫn nhánh Chờ duyệt; phiên bản đầu → NULL, sang `awaiting_approval`.
- [ ] R2.12: gửi một phiên bản `object` chỉ siết với `If-Match` cũ → 412 `precondition_failed` với `stale_version`,
      phiên bản vẫn `draft`, không `version_no` nào được cấp, không audit; đưa `row_version` hiện có của nháp thay giá
      trị `If-Match` cho `seal` ở nhánh này → test đỏ.
- [ ] R2.11 (AL20): phiên bản quy trình khai Điểm gắn `principal` bắt buộc chưa có giá trị đã duyệt → gửi kiểm định
      409 `binding_unset` nêu `principal`, phiên bản vẫn `draft`, không audit; có giá trị đã duyệt → gửi được; gỡ
      kiểm ở route → test đỏ.
- [ ] R7.9 (AL11): Đóng băng của công ty rồi gửi một phiên bản `object` không chỉ siết → 409 `tenant_frozen`, phiên
      bản vẫn `draft`; Đóng băng của nền tảng rồi gửi một phiên bản `object` chỉ siết → 409 `platform_frozen`.
- [ ] R7.13 (AL11): chỉ Đóng băng của công ty đang mở, gửi một phiên bản `object` chỉ siết → `live` theo nhánh chỉ
      siết, audit `details.path` `tighten_only`; gỡ ngoại lệ chỉ siết khỏi kiểm Đóng băng → 409, test đỏ.
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
- 2026-10-24 (agent): vòng sửa thứ tư, quyết định của Đạt ngày 24/10/2026: handler đưa phiên bản về `draft` với
  `base_changed` khi bản `live` đã đổi kể từ lúc gửi (spec R5.9, AL19), và nhánh chỉ siết đi qua được Đóng băng của
  công ty, không qua Đóng băng của nền tảng (spec R7.9, R7.13). Áp thêm: Protocol `PublishBindingsCheck` hỏi ở lệnh
  gửi và ở handler (spec R2.11, R5.10, AL20; tenant-config/05 đáp, cạnh giữ nguyên); đúng một dòng
  `studio.version.published` mỗi lần phát hành, móc phát hành của loại không ghi audit; từ vựng `approved`,
  `rejected` của workflow-nodes:R9.9 cho quyết định giả lập; index cho keyset của hai route danh sách. Chờ
  telemetry-and-audit/03 (bản tệp retention của ticket này đứng sau bản của ticket đó) và tenant-rbac/02 (INSERT khóa
  nêu `tenant_grantable`), theo hai Quyết định tạm của spec.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các Quyết định tạm cùng ngày của spec: người gửi tự duyệt nhận
  `second_person_required` vì kiểm tiền tố nghiêm chạy trước guard, chỉ người đóng góp nhận `author_cannot_approve`
  (V4.P9; spec R5.2); phê duyệt `studio.publish.endpoint` cho Nguồn dữ liệu và loại không bộ so sánh có hình của
  `endpoint` thay cho công cụ, vốn là W2 (V4.1, V4.3); móc phát hành đọc từ mục `ArtifactKindRegistry` của loại ở cả
  hai nhánh (ADR-0109 (Accepted) quyết 1); câu so `compared_live_hash` nói phiên bản Đang dùng mà lần phát hành này
  thay. Chuỗi tệp retention bắt đầu từ usage-and-limits/02 (V4.P1), bản của ticket này vẫn đứng ngay sau bản của
  telemetry-and-audit/03.
- 2026-10-24 (agent): kiểm lượt b: nhánh không cổng của bước 7 cũng đưa giá trị `If-Match` cho `seal` và có tiêu chí
  R2.12 riêng, để một lần gửi chỉ siết với nháp cũ không lên `live` qua nhánh này mà test của ticket 03 không thấy
  (failure-modes #5; Quyết định tạm của spec về `If-Match`).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các Quyết định tạm cùng ngày của spec: `LifecycleService` là bên
  duy nhất ghi `live` ở handler và ở nhánh chỉ siết, gọi `publish_hook` của mục registry, thay "dịch vụ phát hành của
  tenant-config" ở bước 5 và tiêu chí R5.5 (ADR-0120 (Accepted) quyết 1; ADR-0109 (Accepted) quyết 1); bước 1 thêm
  `uq_gate_runs_tenant_id_id`, FK ghép `gate_run_id` của `studio.artifact_versions` và FK ghép ON DELETE RESTRICT của
  `studio.gate_case_results` (spec R1.9, AL21; CLAUDE.md, Data model rules); lý do `STUDIO_EXCLUSIONS` dẫn
  usage-and-limits:R3.10 cho hợp đồng xóa và usage-and-limits:R3.11 cho thứ tự, thay R3.8.
- 2026-10-24 (agent): kiểm lượt c: spec R2.8, R2.9, R7.13 nay nêu `LifecycleService` là bên đưa phiên bản lên `live` ở
  nhánh chỉ siết, và R5.5 nêu thứ tự gỡ bản cũ rồi đặt bản mới, khớp bước 5 và bước 7; bước 7 dẫn spec R2.9.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo các Quyết định tạm cùng ngày của spec: bước 7 gọi bước niêm phong
  của tenant-config chỉ để cấp số, ghi mã băm và so `row_version` (tenant-config:R2.7, tenant-config:R2.17), còn
  `LifecycleService` đưa phiên bản sang `live` hay `awaiting_approval`, thay dẫn chiếu tenant-config:R2.13,
  tenant-config:R2.16 cho việc chuyển giai đoạn (ADR-0120 (Accepted) quyết 1); bước 4 nhận bản Nháp ở route
  `dry-evaluations` với tiêu chí R4.8, R4.9 (AL22), không thêm cạnh: phần agent thử bằng nguồn graph giả, đường thật ở
  agent-builder/03; bước 5 nói móc của loại `agent` và `workflow` ghi giới hạn dữ liệu của phiên bản
  (agent-builder:R1.9, workflow-engine:R1.7; ADR-0117 (Accepted) quyết 3).
