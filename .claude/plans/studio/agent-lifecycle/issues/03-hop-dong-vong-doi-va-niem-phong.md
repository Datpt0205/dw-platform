# 03 — Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong

Status: ready-for-agent
Blocked by: 01, .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R1.9, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.10, R2.12, R2.13, R7.9, AL1, AL2, AL3, AL10, AL19, AL21, AL36

## Mục tiêu

Cài hợp đồng Giai đoạn trên vỏ phiên bản dùng chung: trigger canh chuyển trạng thái, cột vòng đời và route
gửi kiểm định niêm phong nội dung qua `seal` đã dựng, để máy trạng thái thuộc database và "đã kiểm định" tính được
(spec R1, R2). Đứng trên vỏ `studio.artifact_versions` của tenant-config/02 (`09c344d`): cột `stage` với CHECK
`ck_artifact_versions_stage`, enum `Stage` (`packages/python/dw_studio/src/dw_studio/core/domain/artifacts.py:36`),
trigger `studio.refuse_sealed_content_change()` và `ArtifactService.seal` cùng `closure_of`
(`packages/python/dw_studio/src/dw_studio/core/application/service.py:544`, `:587`). Ticket này không viết lại cái nào.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên), thêm cột vòng đời trên `studio.artifact_versions` (vỏ chung
   của tenant-config, DO-05 chọn vỏ chung): `gate_run_id uuid` NULL (bắt buộc khi
   `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng, luôn NULL với loại có
   `has_quality_gate = false`; ADR-0120 (Accepted) quyết 1: bắt buộc từ `awaiting_approval`, không từ `evaluating`);
   `publish_approval_id uuid` NULL, FK ghép `(tenant_id, publish_approval_id)` tới
   `platform.approval_requests (tenant_id, id)` ON DELETE RESTRICT có index riêng (bắt buộc cùng điều kiện, trừ phiên
   bản lên Đang dùng theo nhánh chỉ siết), và cùng revision thêm
   `uq_approval_requests_tenant_id_id UNIQUE (tenant_id, id)` trên `platform.approval_requests`, vì UNIQUE đã có của
   bảng đó, `uq_approval_requests_tenant_id_workspace_id_id`, mang `workspace_id` mà vỏ phiên bản toàn tenant không
   có; `tighten_only boolean NOT NULL DEFAULT false` và `compared_live_hash text` NULL
   với CHECK `NOT tighten_only OR compared_live_hash IS NOT NULL`, do `LifecycleService` ghi lúc gửi:
   `compared_live_hash` ở mọi lần gửi, là `definition_hash` của bản `live` lúc gửi, NULL khi chưa có (spec R2.10),
   còn `tighten_only` do ticket 04 tính bằng bộ so sánh của loại;
   `contributor_ids uuid[] NOT NULL CHECK (cardinality(contributor_ids) >= 1)`; `submitted_by`, `submitted_at`,
   `published_by`, `published_at`, `retired_by`, `retired_at`; `retire_reason_code` CHECK (`superseded`,
   `explicit`). Không cột `stage_changed_at` và không index `(tenant_id, stage, stage_changed_at DESC, id DESC)` ở W1:
   không bên đọc nào ở W1 (failure-modes #1); chúng đến cùng cảnh báo nháp để lâu ở W2 (spec, Ngoài phạm vi, YC75).
   Ở ticket này cột `gate_run_id` chưa có FK: ticket 06, trong revision tạo `studio.gate_runs` cùng
   `uq_gate_runs_tenant_id_id`, thêm FK ghép `(tenant_id, gate_run_id)` tới `studio.gate_runs (tenant_id, id)`
   ON DELETE RESTRICT có index riêng, nên ticket 06 không chặn ticket này. Mọi FK tới một bảng theo tenant ở đây là FK
   ghép vì kiểm khóa ngoại không đi qua RLS (ADR-0109 (Accepted) quyết 1; ADR-0120 (Accepted) quyết 1;
   tenant-config:R2.18 cùng luật).
   Quyền là một phần của lược đồ: `dw_app` chỉ giữ UPDATE theo cột trên bảng này
   (`db/migrations/versions/67071483caa6_studio_artifact_envelope.py`, `_APP_GRANTS`), nên cùng revision
   `GRANT UPDATE (gate_run_id, publish_approval_id, tighten_only, compared_live_hash, contributor_ids, submitted_by,
submitted_at, published_by, published_at, retired_by, retired_at, retire_reason_code)` cho `dw_app`, và
   `test_privileges.py` khẳng định đúng danh sách đó.
   Backfill dòng đã có trong cùng revision, trước `SET NOT NULL`: `contributor_ids` của mỗi dòng là mọi `actor_id`
   khác nhau của audit `studio.artifact.*` có `resource_id` là thành phần của dòng, theo `occurred_at`; dòng không có
   audit nào nhận `ARRAY[]` và revision dừng với lỗi nêu dòng đó, không đặt một người tùy ý. Thừa người là đóng khi
   lỗi: người thừa chỉ mất quyền duyệt phiên bản đó (R5.2).
2. Người ghi `contributor_ids` (spec R5.1, R5.2; ADR-0120 (Accepted) quyết 1 "`contributor_ids` never empty"):
   `ArtifactService.create` (bản Nháp đầu, `POST /api/v1/studio/artifacts`) và `ArtifactService.create_draft`
   (`POST .../draft`) ghi `[người gọi]`; `ArtifactService.save_draft` thêm người gọi vào cuối khi chưa có, trong cùng
   lệnh UPDATE lưu nội dung; lần rút (bước 6) giữ nguyên danh sách. `VersionRow` và `ArtifactTx.update_version` mang
   thêm các cột của bước 1 (`packages/python/dw_studio/src/dw_studio/core/application/ports.py:40`). Không đường ghi
   nội dung nào bỏ qua bước này.
3. Hàm `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE, quyền người gọi: RLS của
   `platform.approval_requests` và `platform.approval_decisions` chỉ lọc theo tenant
   (`db/migrations/sql/0001_platform_baseline.sql:836-839`), nên `dw_app` ở API và ở worker đọc được dòng của chính
   công ty; `REVOKE ALL ... FROM PUBLIC` trên hàm). Cho đúng:
   chèn là `draft`; `draft → evaluating` (đã niêm phong, CHECK `ck_artifact_versions_sealed` có sẵn, và
   `submitted_by`, `submitted_at` khác NULL; không đòi `gate_run_id`); `evaluating → draft`;
   `awaiting_approval → draft`; `awaiting_approval → live` (dòng `publish_approval_id` có `approval_type` bằng
   `'studio.publish.' || kind` của thành phần, `payload->>'version_id'` bằng id của chính phiên bản, `status =
'approved'`, và
   `decided_by` của dòng `platform.approval_decisions` có `request_id` đó và `outcome` `approved` không nằm trong
   `contributor_ids` và khác `submitted_by`); `live → retired`. Luật theo loại (spec R1.6), đọc
   `studio.artifact_kinds.has_quality_gate` qua `studio.artifacts.kind` của dòng (tenant-config:R2.14): với loại không
   cổng (đối tượng `dw.object/v1` và Nguồn dữ liệu `dw.endpoint/v1` ở W1, công cụ ở W2), cho `draft →
awaiting_approval` không qua `evaluating`, `gate_run_id` NULL, `publish_approval_id` đòi có, và `→ live` như trên.
   Với loại có cổng, ở ticket này `evaluating → awaiting_approval` luôn bị từ chối: phép kiểm cổng (`gate_run_id` trỏ
   một Lượt kiểm định `passed` trên đúng `definition_hash` của phiên bản) đọc `studio.gate_runs`, bảng mà ticket 06 tạo,
   nên ticket 06 `CREATE OR REPLACE` hàm này để thêm đúng nhánh đó và kiểm cổng vẫn đạt ở `awaiting_approval → live`;
   tới lúc đó một loại có cổng không lên được `awaiting_approval`, đóng khi thiếu. Nhánh chỉ siết (spec R1.7): chỉ với
   loại `object`, cho `draft → live` khi `tighten_only` là true và `compared_live_hash` bằng `definition_hash` của
   phiên bản Đang dùng mà lần phát hành này thay; Nguồn dữ liệu và công cụ không bao giờ đi nhánh này, vì hai loại đó
   không đăng ký bộ so sánh (ADR-0120 (Accepted) quyết 1). Mọi `awaiting_approval → live`, ở mọi loại, còn đòi
   `compared_live_hash IS NOT DISTINCT FROM` `definition_hash` của phiên bản Đang dùng mà lần phát hành này thay, hay
   NULL khi không có bản nào (spec R1.8). Ở cả hai luật, phiên bản mà lần phát hành này thay là bản mà cùng giao dịch
   vừa đưa sang `retired` với `superseded`, vì chỉ mục một Đang dùng buộc `LifecycleService`, bên duy nhất ghi `live`,
   gỡ bản cũ trước (ADR-0120 (Accepted) quyết 1). Từ chối: SQLSTATE 23514, ràng buộc
   `ck_artifact_versions_stage_transition`. Cột vòng đời chỉ đổi ở đúng bước của chúng, cả khi `stage` không đổi:
   `contributor_ids` chỉ khi `OLD.stage = 'draft'` và `NEW.stage = 'draft'`; `submitted_by`, `submitted_at`,
   `compared_live_hash`, `tighten_only` chỉ ở một chuyển tiếp ra khỏi `draft` hay về `draft`; `publish_approval_id` chỉ
   ở chuyển tiếp vào `awaiting_approval` (đặt) hay về `draft` (xóa); `gate_run_id` chỉ khi `OLD.stage = 'evaluating'`,
   ở chuyển tiếp ra khỏi `draft` (Lượt kiểm định của ticket 06 xếp trong giao dịch gửi) hay về `draft`;
   `published_by`, `published_at` chỉ ở chuyển tiếp vào `live`; `retired_by`, `retired_at`, `retire_reason_code` chỉ ở
   `live → retired`; một UPDATE khác → 23514 cùng ràng buộc, nên SQL thẳng không sửa được `contributor_ids` hay
   `compared_live_hash` của một Bản ứng viên trước `→ live`. Hàm không kiểm cột nội dung: `studio.refuse_sealed_content_change()` đã
   giữ nội dung niêm phong (`ck_artifact_versions_sealed_content`, tenant-config:R2.9), không bản sao thứ hai.
   Chỉ mục từng phần một Đang dùng `uq_artifact_versions_live` (`(artifact_id) WHERE stage='live'`). Không tạo chỉ mục
   một Bản ứng viên: `uq_artifact_versions_unreleased` của tenant-config/02 đã phủ luật đó (spec R1.2;
   tenant-config:R2.20; ADR-0120 (Accepted) quyết 1).
4. Bảng chuyển đổi thuần cạnh `Stage` có sẵn trong `dw_studio.core.domain.artifacts` (enum mà ADR-0120 (Accepted)
   quyết 1 gọi `VersionStage`; không enum thứ hai); `LifecycleService` chỉ dùng chuyển đổi hợp lệ, dịch 23514 theo tên
   ràng buộc (như `ConflictError` theo tên ở ADR-0012 (Accepted)), và mỗi lần đưa về `draft` (rút ở ticket này; trượt
   cổng, từ chối, hết hạn, không áp được ở ticket 04, 06) xóa `gate_run_id`, `publish_approval_id`, `submitted_by`,
   `submitted_at`, `compared_live_hash` và đặt `tighten_only` false trong cùng lệnh, giữ `version_no` và mã băm tới lần
   lưu nháp kế tiếp, mà `save_draft` đã xóa (`service.py:430-436`). View `studio.artifact_display_stage`
   (`WITH (security_invoker = true)`, nên RLS của bảng nền áp cho người đọc) tính Giai đoạn hiển thị theo thứ tự Bị
   kill (công tắc `kill` mở của thành phần trong `platform.control_switches` của ticket 01), Đang dùng, Chờ duyệt,
   Đang kiểm định, Nháp, Đã gỡ; bên đọc ở W1 là trường mới `display_stage` mà ticket này thêm vào `ArtifactView` của
   `GET /api/v1/studio/artifacts` và `GET .../{id}` (`apps/api/src/dw_api/routes/v1/studio_artifacts.py:44`), đọc từ
   view trong cùng truy vấn, không tính lại trong Python; snapshot OpenAPI và kiểu TS sinh lại.
5. Không bảng điều phối bao đóng mới: bao đóng của mọi loại là `entry.extract` của mục `ArtifactKindRegistry` cộng
   `closure_of`, mà `seal` tự gọi (`service.py:563-566`); agent-builder/02 và workflow-engine/01 cung cấp `extract` của
   loại mình trên mục đó. Bảng kiểm theo loại lúc gửi kiểm định ở composition root: Protocol `SubmitCheck` của spec này,
   nhận giao dịch, dòng phiên bản đã niêm phong và bao đóng, trả từ chối với `reason_code` hay cho qua;
   compliance-pdpl/05 đăng ký Phân tích năng lực, workflow-nodes đăng ký kiểm người duyệt (workflow-nodes:R9.5);
   ticket này kiểm bằng một kiểm fixture. Một kiểm ném lỗi thay vì trả kết quả làm giao dịch lùi (500, phiên bản giữ
   `draft`), không bao giờ coi là cho qua.
6. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/submit` (`Idempotency-Key`
   tùy chọn như các route tạo của vỏ, ADR-0108 (Accepted) quyết 4; `If-Match`). Ticket này chỉ gắn hai đoạn của loại có
   cổng; đoạn `objects` và `data-sources` đến cùng nhánh gửi của loại không cổng ở ticket 04, nên không có lúc nào
   route nhận một loại không cổng mà không có nhánh của nó. Đoạn đường dẫn ánh xạ đúng một loại (`agents` → `agent`,
   `workflows` → `workflow`; ticket 04: `objects` → `object`, `data-sources` → `endpoint`); thành phần mà `kind` lưu khác loại của đoạn, khác
   công ty, bị xóa mềm, hay mà người gọi không đọc được ở độ sâu của khóa đọc tại `owning_workspace_id` → 404 như không
   tồn tại; đọc được mà thiếu khóa gửi mà mục `ArtifactKindRegistry` của `kind` lưu khai, ở độ sâu tới
   `owning_workspace_id` (`platform.workspace_reach`, cùng phép kiểm mà `ArtifactService` làm cho khóa ghi) → 403
   `permission_denied` (tenant-config:R2.15: `studio.versions.submit` cho agent và quy trình, `studio.objects.manage`
   cho đối tượng, `studio.datahub.manage` cho Nguồn dữ liệu, workflow-triggers:R4.7). Thiếu `If-Match` → 428
   `precondition_required` trước mọi lần ghi (spec R2.13). Trong một giao dịch, theo thứ tự: (a) hỏi
   `RunControlPort.admission_state(tenant_id, ())` của ticket 01: `tenant_frozen`, `platform_frozen` hay
   `control_state_unavailable` → 409 với mã đó, không niêm phong gì (spec R7.9; ngoại lệ chỉ siết là của ticket 04,
   spec R7.13); (b) `ArtifactService.seal(tx, artifact_id, expected_row_version)` với giá trị `If-Match`, ETag của nháp
   tức `row_version` (tenant-config/02; `seal` khóa dòng thành phần `FOR UPDATE`, chạy `validate` của loại, tính bao
   đóng, cấp `version_no`, ghi mã băm, bản kê và Nơi đang dùng, không đổi giai đoạn, tenant-config:R2.7). `seal` trả
   404 `no_draft` khi thành phần không có bản Nháp: route đọc lại phiên bản dưới cùng khóa, và khi `version_id` là Bản
   ứng viên của thành phần (giai đoạn trong `CANDIDATE_STAGES`) thì trả 409 `candidate_exists` (spec R1.3), còn lại
   404; `version_id` khác id bản Nháp mà `seal` niêm phong → 404, giao dịch lùi. Phép kiểm giai đoạn đứng trước phép so
   `If-Match` (thứ tự của `seal`), nên hai lần gửi song song cùng `If-Match` cho một 202 và một 409
   `candidate_exists`, không 412; `If-Match` lệch trên một bản Nháp → 412 `precondition_failed` với `stale_version`,
   giao dịch lùi, phiên bản giữ `draft` (spec R2.12; ADR-0108 (Accepted) quyết 3); tài liệu sai → 422 của `seal`
   (`DocumentInvalidError`, `errors[]`). (c) Chạy các kiểm của bảng kiểm theo loại (một kiểm từ chối → 422 với
   `reason_code` của nó, giao dịch lùi, phiên bản giữ `draft`; spec R2.7). (d) Ghi `compared_live_hash` (spec R2.10),
   `submitted_by`, `submitted_at`. (e) Loại có cổng: `LifecycleService` chuyển `draft → evaluating` (spec R2.1; ADR-0120 (Accepted) quyết 1), ticket 06 xếp Lượt
   kiểm định hoặc dùng lại bằng chứng trong cùng giao dịch. (f) Audit `studio.version.submitted`. Câu trả lời 202 là
   `VersionView` đã có (`studio_artifacts.py:65`) của phiên bản vừa gửi, `stage` mới; ticket 04 thêm `binding_unset[]`. Mã 412, 428 và header
   là của app-standards/03, ticket này nhận qua tenant-config/04. Ticket 04 thêm vào route này `PublishBindingsCheck`:
   409 `binding_unset` chỉ ở lần gửi đi nhánh chỉ siết, còn ở nhánh có phê duyệt danh sách `binding_unset` đi trong câu
   trả lời thành công (spec R2.11, sửa ở gate tenant-config/05, `4470be0`).
7. `POST .../versions/{version_id}/withdraw` (`Idempotency-Key`; cùng ánh xạ đoạn, 404 và 403 như bước 6, khóa gửi
   của loại), cách người dựng sửa tiếp khi route tạo nháp của tenant-config trả 409 `candidate_pending` vì thành phần
   đang có Bản ứng viên (tenant-config:R2.22): bất kỳ người giữ khóa gửi ở độ sâu đó rút được, không chỉ người gửi, để
   một thành phần không kẹt khi người gửi vắng; audit đứng tên người rút. Trong một giao dịch, dưới khóa dòng thành phần
   `FOR UPDATE` (cùng luật khóa của `ArtifactService`): yêu cầu phê duyệt đọc và hủy theo `publish_approval_id` của dòng
   phiên bản qua adapter SQL của Studio dưới RLS theo tenant, không qua repository của nền tảng vốn lọc theo
   `workspace_id` của người gọi (`approval_flow.py:235-238`), vì quyền rút đến từ khóa gửi ở độ sâu tới
   `owning_workspace_id`, không từ workspace của yêu cầu; `version_id` không phải Bản ứng viên (`evaluating`,
   `awaiting_approval`) → 409 `conflict` với `details.reason_code` `not_a_candidate`; ở `awaiting_approval`, hủy yêu
   cầu phê duyệt `publish_approval_id` bằng `ApprovalRequest.cancel()` (một yêu cầu đã quyết thì lần rút trả 409
   `conflict` với `not_a_candidate`, giao dịch lùi); `LifecycleService` đưa phiên bản về `draft` (bước 4), thành bản
   chưa phát hành duy nhất của thành phần; audit `studio.version.returned_to_draft` với `details.reason_code`
   `withdrawn` (spec R2.4). Rút ở `evaluating` ở ticket này chỉ đổi giai đoạn; hủy Lượt kiểm định đang chạy là của
   ticket 06.
8. `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/retire` (`Idempotency-Key` tùy chọn;
   `studio.versions.retire` ở độ sâu tới `owning_workspace_id`, cùng ánh xạ đoạn, 404 và 403 như bước 6; không thân,
   không lý do chữ: audit chỉ id và mã): `live → retired` (`explicit`), `retired_by`, `retired_at`; phiên bản không ở
   `live` → 409 `conflict` với `details.reason_code` `not_live`. Bên phụ thuộc theo đúng phiên bản (spec R2.6): một
   phương thức mới của `ArtifactTx` đọc `studio.dependencies` theo `to_version_id` nối giai đoạn `live` của phiên bản
   bên phụ thuộc, trong chính giao dịch gỡ sau khóa dòng thành phần; `closure_of` đọc phiên bản đích `FOR SHARE`, nên
   một lần niêm phong song song ghim phiên bản này và lệnh gỡ chạy nối tiếp. `ArtifactService.dependents()` theo thành
   phần và tự mở giao dịch (`service.py:523-531`), nên không dùng được ở đây; ticket này dùng lại hình `DependentGroup`
   của nó (`service.py:89`: tên bên đọc được, số bên ẩn) cho 409 `artifact_in_use` (spec R2.6); audit
   `studio.version.retired`. Đối tượng và Nguồn dữ liệu không có route gỡ ở W1 (spec, API).
9. Test catalog `test_version_stage_contract.py`: hỏi `pg_catalog` rằng `studio.artifact_versions` có trigger
   `guard_version_stage`, các CHECK và hai chỉ mục từng phần (`uq_artifact_versions_live` của ticket này,
   `uq_artifact_versions_unreleased` của tenant-config/02), rằng view `studio.artifact_display_stage` có
   `security_invoker`; test đọc CHECK `ck_artifact_versions_stage` so với `Stage`.
10. Cùng migration: đăng ký khóa `studio.versions.submit` và `studio.versions.retire` trong `platform.permissions`
    của tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket
    đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` (`true`)
    của tenant-rbac/02 (cùng khối INSERT mà revision `16357d3dbff8` dùng cho `studio.objects.manage`). Khóa ngoại
    `publish_approval_id` (RESTRICT) tới `platform.approval_requests` cần lane `offboarding` xóa
    `studio.artifact_versions` trước: thứ tự đó không viết tay mà suy từ khóa ngoại trong `pg_constraint` qua sổ bước
    xóa ở composition root của worker mà foundations-hardening/07 dựng (foundations-hardening:R11.4; H-2), nên ticket
    này không đăng ký bước nào; test phủ của studio-skeleton:R4.2 đọc sổ đó và đỏ khi một bước đi trái cạnh này.
11. Test đã dựng ghi giai đoạn thẳng sẽ bị trigger từ chối, nên chuyển trong cùng thay đổi sang một helper
    `dw_studio.testing.lifecycle.publish_for_test(...)` đi đúng đường hợp lệ bằng vai migrator: loại không cổng qua
    `draft → awaiting_approval → live` với một yêu cầu phê duyệt `approved` và một quyết định của người không trong
    `contributor_ids`, loại `object` qua nhánh chỉ siết hay đường đó; loại có cổng (`fixture`) chưa lên được
    `awaiting_approval` tới ticket 06, nên test cần một bản `live` dùng `fixture_gateless`, và ticket 06 mở rộng helper
    với một Lượt kiểm định `passed`. Các chỗ phải chuyển: `stage()`, `published()` và câu INSERT `'live'` của
    `packages/python/dw_studio/tests/integration/test_artifact_envelope.py` (dòng 132-144, 179, 459, 483);
    `go_live()` và câu UPDATE `'live'` của `packages/python/dw_studio/tests/integration/test_object_definitions.py`
    (dòng 180-193, 958); `published(..., stage=)` của `packages/python/dw_studio/src/dw_studio/testing/run_manifests.py`
    và người gọi nó trong `packages/python/dw_studio/tests/integration/test_run_manifest.py`. Test nào khẳng định
    chính trigger (một chuyển tiếp bị từ chối) giữ câu SQL thẳng.

## Tiêu chí chấp nhận

- [ ] R1.1 (AL1): mọi chuyển tiếp bất hợp lệ bằng `dw_app` trực tiếp (bảng liệt kê từng cặp) → 23514
      `ck_artifact_versions_stage_transition`; INSERT một dòng `live` → 23514; gỡ trigger khỏi bảng → test catalog đỏ.
- [ ] R1.2 (AL2): INSERT phiên bản `live` thứ hai cho một thành phần (bằng helper hợp lệ) → lỗi
      `uq_artifact_versions_live`; gỡ chỉ mục → test đỏ.
- [ ] R1.3 (AL2): hai lệnh gửi kiểm định song song bản Nháp duy nhất của một thành phần, cùng `If-Match` → một 202,
      một 409 `candidate_exists` (không 412, không 404), đúng một audit `studio.version.submitted`; gỡ phép đọc lại
      giai đoạn sau `no_draft` của route → lần thứ hai nhận 404, test đỏ.
- [ ] R1.4: `LifecycleService` đưa một phiên bản `fixture_gateless` lên `live` khi đã có bản `live` → bản cũ
      `retired` (`superseded`) trong cùng giao dịch; đảo thứ tự hai lệnh → lỗi chỉ mục, test đỏ.
- [ ] R1.5: view cho đúng thứ tự ưu tiên (bản `live` của thành phần có công tắc `kill` mở → Bị kill);
      `GET /api/v1/studio/artifacts/{id}` trả `display_stage` từ view; `dw_app` với `app.tenant_id` của tenant A đọc
      view → 0 dòng của tenant B; tạo lại view không `security_invoker` → test đỏ; không cột nào lưu Giai đoạn hiển thị.
- [ ] R1.6: một phiên bản `fixture_gateless` đi `draft → awaiting_approval → live` không có `gate_run_id`; cùng
      đường với loại `fixture` (có cổng) → 23514; `fixture` ở `evaluating → awaiting_approval` → 23514 (tới ticket 06);
      `→ live` khi approval còn `pending` → 23514; người quyết nằm trong `contributor_ids` hay là `submitted_by` →
      23514; `publish_approval_id` trỏ một yêu cầu `approved` khác loại hay của phiên bản khác → 23514; ở
      `awaiting_approval`, `dw_app` UPDATE `contributor_ids` hay `compared_live_hash` không đổi `stage` → 23514; đổi cờ của `fixture_gateless` sang true → `draft → awaiting_approval` bị từ chối.
- [ ] R1.7: phiên bản `object` có `tighten_only` true và `compared_live_hash` bằng `definition_hash` của bản `live`
      → `draft → live` nhận, không approval; cùng giá trị với `fixture_gateless` → 23514; bỏ nhánh khỏi trigger →
      test đỏ.
- [ ] R1.8 (AL19): `dw_app` UPDATE `awaiting_approval → live` (approval `approved`) sau khi bản `live` đã đổi kể từ
      lúc gửi (`compared_live_hash` cũ) → 23514; bản `live` cũ vừa gỡ `superseded` trong cùng giao dịch và
      `compared_live_hash` là mã của nó → nhận; chưa có bản `live` lúc gửi lẫn lúc chuyển (cùng NULL) → nhận; gỡ luật
      khỏi trigger → test đỏ.
- [ ] R1.9 (AL21): bằng vai migrator, UPDATE một dòng phiên bản của tenant A đặt `publish_approval_id` là id một yêu
      cầu phê duyệt của tenant B → FK ghép từ chối, dòng không đổi; cùng id của một yêu cầu của tenant A → nhận; đổi FK
      sang một cột `publish_approval_id` → test đỏ.
- [ ] R2.10: gửi một phiên bản `fixture` khi thành phần đã có bản `live` → `compared_live_hash` bằng `definition_hash`
      của bản đó; chưa có bản `live` → NULL.
- [ ] R2.1 (AL3): gửi kiểm định một nháp `fixture` hợp lệ → bao đóng, Mã băm định nghĩa, Nơi đang dùng,
      `submitted_by` và audit `studio.version.submitted` ghi trong một giao dịch, phiên bản sang `evaluating` với
      `gate_run_id` NULL; người đọc được mà thiếu khóa gửi mà mục registry của loại khai → 403, không đổi gì; người giữ
      khóa gửi ở độ sâu `workspace` của ws1 gửi thành phần có `owning_workspace_id` ws2 → 404; `POST /workflows/{id của một thành phần agent}/…/submit` → 404; `POST /objects/…/submit` → 404 tới ticket 04; `version_id`
      không phải bản Nháp của `artifact_id` → 404, không niêm phong gì.
- [ ] R1.6 (AL1): người ghi `contributor_ids` mà trigger và ticket 04 đọc: A tạo thành phần, B lưu nháp, A lưu lại → `contributor_ids` là `[A, B]`;
      bỏ phép thêm người lưu ở `save_draft` → test đỏ; migration trên một DB có dòng đã có backfill `contributor_ids`
      từ audit `studio.artifact.*`.
- [ ] R2.2 (AL3): hai phiên bản cùng nội dung và bao đóng → cùng Mã băm định nghĩa; đổi phiên bản một
      thành phần ghim → Mã băm định nghĩa khác.
- [ ] R2.3 (AL3): rollback giữa giao dịch gửi kiểm định → không bản kê, phụ thuộc hay audit; một `SubmitCheck` ném
      lỗi → giao dịch lùi, phiên bản `draft`.
- [ ] R2.4: rút một Bản ứng viên `fixture_gateless` ở `awaiting_approval` → về `draft`, yêu cầu phê duyệt phát hành
      `cancelled`, `publish_approval_id` NULL, audit `returned_to_draft` với `withdrawn`; một người giữ khóa gửi khác
      người gửi rút được; người thiếu khóa gửi → 403; với thành phần mà route tạo nháp vừa trả 409 `candidate_pending`,
      rút rồi lưu nháp → lưu được trên chính phiên bản vừa rút, không thêm dòng `draft` nào; rút một bản `draft` → 409
      `not_a_candidate`.
- [ ] R2.5: gỡ một phiên bản Đang dùng không bị phụ thuộc → `retired` (`explicit`), `retired_by`, với audit.
- [ ] R2.6: gỡ một phiên bản mà phiên bản Đang dùng của thành phần khác phụ thuộc → 409 `artifact_in_use` kèm danh sách
      bên đọc được và số bên ẩn; gỡ v2 khi bên phụ thuộc chỉ ghim v1 đã `retired` → nhận; gỡ một bản `draft` → 409
      `not_live`.
- [ ] R2.4 (AL36): theo CLAUDE.md, Tenancy and authorization, người của tenant B gọi `submit`, `withdraw` và `retire` với
      `artifact_id`, `version_id` của tenant A → 404 giống hệt id ngẫu nhiên, phiên bản của A không đổi, 0 audit ở A;
      chạy route bằng vai bỏ qua RLS hay bỏ lọc độ sâu → test đỏ.
- [ ] R2.7 (AL10): đăng ký một kiểm fixture từ chối cho loại `fixture` → gửi kiểm định 422 với `reason_code` của
      kiểm, phiên bản vẫn `draft`, không bản kê hay audit; bỏ bước chạy bảng kiểm → test đỏ.
- [ ] R2.12: nháp được lưu lại sau khi người gửi tải nó, rồi gửi với `If-Match` cũ → 412 `precondition_failed` với
      `stale_version`, phiên bản vẫn `draft`, không `version_no` nào được cấp, không bản kê hay audit; `If-Match`
      đúng → gửi được; bỏ việc chuyển `If-Match` cho `seal` → test đỏ.
- [ ] R2.13: gửi không có `If-Match` → 428 `precondition_required`, không đổi gì.
- [ ] R7.9: đóng băng công ty rồi gửi kiểm định → 409 `tenant_frozen`, phiên bản vẫn `draft`; Đóng băng của nền tảng
      → 409 `platform_frozen`; `RunControlPort` giả trả `control_state_unavailable` → 409, không niêm phong; bỏ phép hỏi
      → test đỏ.
- [ ] R1.1 (AL1): `test_privileges.py` khẳng định đúng danh sách cột UPDATE của `dw_app` ở bước 1; test đã chuyển của bước
      11 xanh trên helper.
- [ ] Xong: `uv run python -m pytest packages/python/dw_studio/tests apps/api/tests -k "lifecycle or version_stage or submit"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:142-152`, `:285-286`; spec: R2.4 (loại
  nghiêm chặn người gửi tự quyết qua `decide`, nên lệnh rút là route riêng).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:34-43`; spec: R1.1
  (trạng thái hôm nay không có CHECK, máy trạng thái phiên bản là mới).
- `.claude/plans/studio/tenant-config/spec.md:106`; spec: R2.1 (bước niêm phong R2.7 và cột `stage`);
  ADR-0120 (Accepted) quyết 1, ADR-0109 (Accepted) quyết 4-5.

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 04 và 05. `needs-info` vì DO-05 (vỏ chung hay bảng phiên
  bản theo loại) còn mở; Đạt ghi O1 (vỏ chung) ngày 23/10/2026, nên ticket viết trên
  `studio.artifact_versions`. Nếu DO-05 lật sang bảng theo loại thì trigger gắn vào từng bảng và Dữ liệu
  của spec đổi.
- 2026-10-23 (agent): DO-05 đã quyết theo (a) (Đạt, 23/10/2026), nên `needs-triage`. Thêm luật theo loại
  không cổng (R1.6), bảng kiểm theo loại lúc gửi kiểm định (R2.7) và từ chối gửi kiểm định khi đóng băng
  (R7.9, chờ ticket 01).
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: cột `has_quality_gate` của tenant-config, cột
  `tighten_only` và `compared_live_hash` với nhánh chỉ siết của `object` trong trigger (Q-R6, spec R1.7), route
  gửi chung cho mọi loại với khóa do registry khai (tenant-config:R2.15), đăng ký khóa của ticket này, thứ tự
  offboarding cho khóa ngoại `publish_approval_id`. Nhánh gửi của loại không cổng (so sánh, chỉ siết, mở phê
  duyệt) ở ticket 04, nơi có guard và handler phát hành; custom-objects/06 nối loại `object` vào đường này và chờ cả
  hai ticket.
- 2026-10-24 (agent): vòng sửa thứ tư: mọi lần gửi ghi `compared_live_hash` và trigger chỉ cho sang `live` khi mã đó
  vẫn là của bản `live` mà lần phát hành thay (quyết định của Đạt ngày 24/10/2026; spec R1.8, R2.10, AL19); chờ
  foundations-hardening/07 (cùng sửa `_ORDERED_FIRST`) và tenant-rbac/02 (INSERT khóa nêu `tenant_grantable`).
  workflow-engine/01 chờ ticket này vì ticket này đăng ký khóa gửi `studio.versions.submit` mà mục
  `ArtifactKindRegistry` của loại `workflow` khai; cạnh nằm ở ticket đó (Quyết định tạm của spec).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các Quyết định tạm cùng ngày của spec: route gửi nhận `If-Match`
  và chuyển nó cho `seal(..., expected_row_version)`, 412 `stale_version` khi lệch, 428 khi thiếu (spec R2.12, R2.13);
  route thêm `endpoints` với khóa gửi `studio.datahub.manage` và luật theo loại nêu Nguồn dữ liệu (V4.1); câu so
  `compared_live_hash` nói phiên bản Đang dùng mà lần phát hành này thay, hay NULL khi không có bản nào.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các Quyết định tạm cùng ngày của spec: đoạn route của Nguồn dữ
  liệu là `data-sources`, cùng đoạn mà workflow-triggers dùng, thay `endpoints` của dòng trên; `publish_approval_id`
  là FK ghép tới `uq_approval_requests_tenant_id_id` mà revision của ticket này thêm, còn FK ghép của `gate_run_id` do
  ticket 04 thêm cùng `studio.gate_runs` (spec R1.9, AL21); `LifecycleService` là bên duy nhất ghi `live` và gỡ bản
  cũ (ADR-0120 (Accepted) quyết 1), không còn dịch vụ phát hành của tenant-config ở bước 2. agent-builder/02 chờ
  ticket này cho khóa gửi `studio.versions.submit` của loại `agent`, như workflow-engine/01 (cạnh nằm ở ticket đó).
- 2026-10-24 (agent): kiểm lượt c: bước 1 nói FK ghép cho mọi FK tới một bảng theo tenant, vì luật của area để FK tới
  bảng không theo tenant (như `platform.users`) giữ một cột; dẫn thêm ADR-0120 (Accepted) quyết 1, nơi hai cột
  `gate_run_id`, `publish_approval_id` được nêu là FK ghép.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo Quyết định tạm cùng ngày của spec: bước 5 nói bước niêm phong của
  tenant-config không đổi giai đoạn và `LifecycleService` chuyển `draft → evaluating` (spec R2.1; ADR-0120 (Accepted)
  quyết 1), để việc chuyển giai đoạn có một bên ghi.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo V4.17 của Đạt (spec R1.2, R1.3, R2.4): một phiên bản chưa phát hành
  mỗi thành phần là chỉ mục của tenant-config/02, nên bước 2 bỏ chỉ mục một Bản ứng viên, và test catalog của bước 6
  đọc chỉ mục một Đang dùng của ticket này cùng chỉ mục của tenant-config/02; lần gửi song song thứ hai nhận 409
  `candidate_exists` vì bản Nháp duy nhất đã rời `draft`; lệnh rút là cách sửa tiếp khi route tạo nháp trả 409
  `candidate_pending`. Không thêm cạnh: ticket này đã chờ tenant-config/02 qua tenant-config/04.
- 2026-10-26 (agent): lượt h, đợt 2, theo V4.31 của Đạt: ticket 04 tách, nên FK ghép của `gate_run_id` và việc xếp
  Lượt kiểm định hay dùng lại bằng chứng nay ở ticket 06 (bước 1, bước 5); nhánh gửi của loại không cổng và
  `PublishBindingsCheck` vẫn ở ticket 04. Không đổi cạnh.
- 2026-10-26 (agent): lượt h, đợt 2, theo H-2: `_ORDERED_FIRST` đã bỏ; thứ tự xóa của khóa ngoại `publish_approval_id`
  suy từ `pg_constraint` qua sổ bước xóa của foundations-hardening/07 (foundations-hardening:R11.4, R11.5), thay câu
  "thêm thứ tự đó vào `_ORDERED_FIRST`" của bước 7 và chữ "cùng sửa `_ORDERED_FIRST`" của dòng trên; cạnh tới
  foundations-hardening/07 giữ, vì sổ ra đời ở đó.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `e35a917` (builder check và boundary walk trong một subagent, vì ticket có migration và route; đối chiếu mã đã dựng của tenant-config/02 `09c344d`, tenant-config/04 `f32a007`, custom-objects/02 và `approval_flow.py`; lượt xác nhận ngữ cảnh mới sau các sửa), 1 CRITICAL và 14 HIGH đã sửa theo khuyến nghị. CRITICAL: (1) `submit` và `withdraw` không có test âm chéo tenant (CLAUDE.md, Tenancy and authorization): thêm AL36 ở spec và tiêu chí cho ba route. HIGH: (2) bảng `ClosureExtractor` là bản sao thứ hai của `entry.extract` cộng `closure_of` mà `seal` đã gọi: bỏ, sửa cả R2.1 và Trong phạm vi của spec; (3) `VersionStage` là `Stage` đã có; (4) "cột nội dung đổi chỉ khi draft" đã là `studio.refuse_sealed_content_change()`; (5) `dw_app` chỉ giữ UPDATE theo cột, nên cột mới cần GRANT và `test_privileges.py`; (6) `contributor_ids` không có người ghi: `create`, `create_draft`, `save_draft` ghi người gọi, backfill từ audit `studio.artifact.*`; (7) `stage_changed_at` và index của nó không bên đọc ở W1: bỏ, sang W2; (8) `draft → evaluating` đòi `gate_run_id` trái Dữ liệu và ADR-0120 (Accepted) quyết 1, và phép kiểm cổng đọc bảng của ticket 06: `evaluating` không đòi, `evaluating → awaiting_approval` của loại có cổng bị từ chối tới khi ticket 06 thay hàm; (9) đoạn đường dẫn, `kind` lưu, `version_id` và độ sâu: ánh xạ, 404 và 403 như `ArtifactService`; (10) view `security_invoker` và một bên đọc `display_stage`; (11) `seal` trả 404 `no_draft` cho lần gửi song song thứ hai: route đọc lại và trả 409 `candidate_exists`, trước phép so `If-Match`; (12) ai rút: mọi người giữ khóa gửi, không chỉ người gửi (R2.4 và tiêu chí mâu thuẫn); (13) trigger cần `decided_by` của `platform.approval_decisions` (sửa ở lượt xác nhận: RLS của hai bảng phê duyệt chỉ theo tenant, nên hàm chạy quyền người gọi, không `SECURITY DEFINER`); (14) R2.6 lấy bên phụ thuộc từ `ArtifactService.dependents()`; (15) test đã dựng ghi `live` thẳng sẽ đỏ: helper `publish_for_test` và danh sách chỗ chuyển. Theo yêu cầu của điều phối: câu R2.11 của bước 6 theo R2.11 mới (`4470be0`). Nếu sai thì: (2)-(4) thêm bảng hay enum thứ hai và giữ hai chủ đồng bộ bằng test; (6) người đóng góp ghi lúc gửi từ audit; (7) thêm lại cột cùng bên đọc; (8) ticket 03 chờ ticket 06; (12) chỉ người gửi rút, người khác chờ hết hạn 14 ngày; (13) hàm `SECURITY DEFINER`.
- 2026-11-04 (agent): MEDIUM để lại: (a) gỡ phiên bản đối tượng và Nguồn dữ liệu không có route ở W1; (b) một Bản ứng viên ghim một phiên bản sau đó bị gỡ vẫn lên `live` được (R2.6 chỉ đếm bên Đang dùng); (c) cùng `Idempotency-Key` sau rút và sửa trả lại câu trả lời cũ trong 24 giờ (ADR-0108 (Accepted) quyết 4): người gọi dùng khóa mới cho lần gửi mới; (d) rút đua với quyết định duyệt: cả hai khóa dòng thành phần, handler của ticket 04 đọc lại giai đoạn; (e) rút ở `evaluating` hủy Lượt kiểm định là của ticket 06; (f) cảnh báo `ears` của R2.11 (hai modal) là câu của gate tenant-config/05, để chủ câu sửa.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (một subagent ngữ cảnh mới, mở đúng các tệp đã dẫn), 6 HIGH và 3 dẫn sai về mã, đã sửa: (16) cột vòng đời đổi cả khi `stage` không đổi: trigger canh từng cột theo bước của nó; (17) `publish_approval_id` phải là yêu cầu `studio.publish.<kind>` của chính phiên bản; (18) loại không cổng trước ticket 04: ticket này chỉ gắn đoạn `agents`, `workflows`, đoạn `objects`, `data-sources` đến ở ticket 04; (19) lệnh rút đọc và hủy yêu cầu qua adapter của Studio dưới RLS theo tenant, không qua repository lọc theo workspace; (20) bên phụ thuộc của lệnh gỡ theo `to_version_id`, trong giao dịch gỡ, vì `dependents()` theo thành phần và mở giao dịch riêng; (21) câu trả lời 202 là `VersionView`, lệnh gỡ không thân, `not_live`. Dẫn sai: `approval_flow.py:115` thành `:142-152`, `:285-286`; `dependents()` không đọc theo `to_version_id`; `display_stage` là trường mới. Nếu sai thì: (16) chỉ canh cặp giai đoạn và tin `LifecycleService`; (18) ticket 03 gắn cả bốn đoạn và trả 409 cho loại không cổng tới ticket 04; (20) chặn gỡ khi bất kỳ phiên bản Đang dùng nào dùng thành phần.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
