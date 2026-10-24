# 03 — Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong

Status: needs-triage
Blocked by: 01, .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R1.9, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.10, R2.12, R2.13, R7.9, AL1, AL2, AL3, AL10, AL19, AL21

## Mục tiêu

Cài hợp đồng Giai đoạn trên vỏ phiên bản dùng chung: trigger canh chuyển trạng thái, cột cổng và route
gửi kiểm định niêm phong nội dung rồi tính bao đóng và Mã băm định nghĩa, để máy trạng thái thuộc
database và "đã kiểm định" tính được (spec R1, R2). Đứng trên vỏ `studio.artifact_versions` với cột
`stage` và bước niêm phong của tenant-config, và băm `dw_kernel.canonical`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên), thêm cột vòng đời trên `studio.artifact_versions` (vỏ chung
   của tenant-config, DO-05 chọn vỏ chung): `gate_run_id uuid` NULL (bắt buộc khi
   `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng, luôn NULL với loại có
   `has_quality_gate = false`); `publish_approval_id uuid` NULL, FK ghép `(tenant_id, publish_approval_id)` tới
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
   `explicit`); `stage_changed_at timestamptz NOT NULL`. Ở ticket này cột `gate_run_id` chưa có FK: ticket 04, trong
   revision tạo `studio.gate_runs` cùng `uq_gate_runs_tenant_id_id`, thêm FK ghép `(tenant_id, gate_run_id)` tới
   `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT có index riêng, nên ticket 04 không chặn ticket này. Mọi FK
   tới một bảng theo tenant ở đây là FK ghép vì kiểm khóa ngoại không đi qua RLS (ADR-0109 (Accepted) quyết 1;
   ADR-0120 (Accepted) quyết 1; tenant-config:R2.18 cùng luật).
2. Hàm `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE): chèn là `draft`; `draft → evaluating`
   (có mã băm và `gate_run_id`); `evaluating → draft`; `evaluating → awaiting_approval` (gate `passed`,
   `definition_hash` của gate bằng của phiên bản, approval `pending`); `awaiting_approval → draft`;
   `awaiting_approval → live` (approval `approved`, người quyết không trong `contributor_ids` và không
   là `submitted_by`, gate vẫn `passed` trên cùng mã băm); `live → retired`; cột nội dung đổi chỉ khi
   `draft`. Luật theo loại (spec R1.6): với loại mà cột `has_quality_gate` của `studio.artifact_kinds`
   (tenant-config:R2.14) là false (đối tượng `dw.object/v1` và Nguồn dữ liệu `dw.endpoint/v1` ở W1, công cụ ở W2),
   cho `draft → awaiting_approval` không qua `evaluating` và không đòi `gate_run_id`; `awaiting_approval → live`
   vẫn đòi approval `approved` và người quyết ngoài `contributor_ids`. Nhánh chỉ siết (spec R1.7): chỉ với loại
   `object`, cho `draft → live` khi `tighten_only` là true và `compared_live_hash` bằng `definition_hash` của phiên
   bản Đang dùng mà lần phát hành này thay; Nguồn dữ liệu và công cụ không bao giờ đi nhánh này, vì hai loại đó không
   đăng ký bộ so sánh (ADR-0120 (Accepted) quyết 1). Mọi `awaiting_approval → live`, ở mọi loại, còn đòi
   `compared_live_hash IS NOT DISTINCT FROM` `definition_hash` của phiên bản Đang dùng mà lần phát hành này thay, hay
   NULL khi không có bản nào (spec R1.8). Ở cả hai luật, phiên bản mà lần phát hành này thay là bản mà cùng giao dịch
   vừa đưa sang `retired` với `superseded`, vì chỉ mục một Đang dùng buộc `LifecycleService`, bên duy nhất ghi `live`,
   gỡ bản cũ trước (ADR-0120 (Accepted) quyết 1). Từ chối: SQLSTATE 23514, ràng buộc
   `ck_artifact_versions_stage_transition`.
   Chỉ mục từng phần một Đang dùng (`WHERE stage='live'`) và một Bản ứng viên
   (`WHERE stage IN ('evaluating','awaiting_approval')`), và `(tenant_id, stage, stage_changed_at DESC, id DESC)`.
3. `VersionStage` StrEnum soi CHECK và bảng chuyển đổi thuần; `LifecycleService` chỉ dùng chuyển đổi hợp
   lệ, dịch 23514 theo tên ràng buộc (như `ConflictError` theo tên ở ADR-0012 (Accepted)); view
   `studio.artifact_display_stage` tính Giai đoạn hiển thị theo thứ tự Bị kill, Đang dùng, Chờ duyệt,
   Đang kiểm định, Nháp, Đã gỡ.
4. Bảng điều phối `ClosureExtractor` theo loại ở composition root (extractor agent và quy trình do
   agent-builder, workflow-engine cung cấp qua `ArtifactKindRegistry`); mỗi extractor trả nội dung
   phiên bản và các ghim `(kind, key, version, content_hash)`. Ticket này kiểm bằng extractor fixture;
   extractor thật được đăng ký ở agent-builder/02 và workflow-engine/01. Cùng chỗ: bảng kiểm theo loại lúc
   gửi kiểm định (Protocol `SubmitCheck` của spec này, mỗi kiểm trả từ chối với `reason_code` hay cho qua);
   compliance-pdpl/05 đăng ký Phân tích năng lực, workflow-nodes đăng ký kiểm người duyệt (workflow-nodes:R9.5);
   ticket này kiểm bằng một kiểm fixture.
5. Route `POST /api/v1/studio/{agents|workflows|objects|data-sources}/{artifact_id}/versions/{version_id}/submit`
   (`Idempotency-Key`, `If-Match`), kiểm khóa gửi mà mục `ArtifactKindRegistry` của loại khai (tenant-config:R2.15:
   `studio.versions.submit` cho agent và quy trình, `studio.objects.manage` cho đối tượng, `studio.datahub.manage`
   cho Nguồn dữ liệu, workflow-triggers:R4.7; thiếu khóa → 403 `permission_denied`); thiếu `If-Match` → 428
   `precondition_required` trước mọi lần ghi (spec R2.13); giá trị `If-Match`, ETag của nháp tức `row_version`, đi vào
   `seal(..., expected_row_version)` của tenant-config/02, lệch → 412 `precondition_failed` với `details.reason_code`
   `stale_version`, giao dịch lùi, phiên bản giữ `draft` (spec R2.12; ADR-0108 (Accepted) quyết 3); mã 412, 428 và
   header là của app-standards/03, ticket này nhận qua tenant-config/04. Loại có `has_quality_gate = false` đi nhánh
   gửi của ticket 04 (spec R2.8). Với loại có cổng, trong một giao dịch: hỏi `RunControlPort` của ticket 01,
   đóng băng thì 409 `tenant_frozen` hay `platform_frozen` (spec R7.9); tính bao đóng bằng extractor của
   loại, gọi bước niêm phong của tenant-config (cấp `version_no`, ghi `content_hash`, `definition_hash`,
   Nơi đang dùng), chạy các kiểm của bảng kiểm theo loại (một kiểm từ chối → 422 với `reason_code` của nó,
   giao dịch lùi, phiên bản giữ `draft`; spec R2.7), ghi `compared_live_hash` (spec R2.10), chuyển
   `draft → evaluating`, xếp Lượt kiểm định hoặc dùng lại bằng chứng (ticket 04), audit `studio.version.submitted`.
   Ticket 04 thêm vào route này kiểm `PublishBindingsCheck` cho mọi loại (spec R2.11). `POST .../withdraw`: hủy yêu cầu phê duyệt phát hành treo bằng
   `ApprovalRequest.cancel()` và về `draft`, audit `studio.version.returned_to_draft`. `POST .../retire`
   (`studio.versions.retire`, lý do): `live → retired` (`explicit`), 409 `artifact_in_use` kèm danh sách
   khi phiên bản Đang dùng khác phụ thuộc, audit `studio.version.retired`.
6. Test catalog `test_version_stage_contract.py`: hỏi `pg_catalog` rằng mọi bảng `studio.*` có cột
   `stage` đều có trigger, các CHECK và hai chỉ mục từng phần; test đọc CHECK so với `VersionStage`.
7. Cùng migration: đăng ký khóa `studio.versions.submit` và `studio.versions.retire` trong `platform.permissions`
   của tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket
   đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` (`true`)
   của tenant-rbac/02, ticket này chờ ticket đó. Khóa ngoại `publish_approval_id` (RESTRICT) tới
   `platform.approval_requests` cần lane `offboarding` xóa `studio.artifact_versions` trước: thêm thứ tự đó vào
   `_ORDERED_FIRST` (studio-skeleton:R4.2), sau bản viết lại lane của foundations-hardening/07 mà ticket này chờ.

## Tiêu chí chấp nhận

- [ ] R1.1 (AL1): mọi chuyển tiếp bất hợp lệ bằng `dw_app` trực tiếp (bảng liệt kê từng cặp) → 23514
      `ck_artifact_versions_stage_transition`; sửa nội dung ngoài `draft` → 23514; gỡ trigger khỏi một
      bảng → test catalog đỏ.
- [ ] R1.2 (AL2): INSERT phiên bản `live` thứ hai cho một thành phần → lỗi chỉ mục từng phần; gỡ chỉ
      mục → test đỏ.
- [ ] R1.3 (AL2): hai lệnh gửi kiểm định song song một thành phần → một 202, một 409 `candidate_exists`.
- [ ] R1.4: duyệt phát hành (giả lập bước chuyển) → phiên bản Đang dùng cũ sang Đã gỡ (`superseded`)
      trong cùng giao dịch.
- [ ] R1.5: view Giai đoạn hiển thị cho đúng thứ tự ưu tiên; không cột nào lưu Giai đoạn hiển thị.
- [ ] R1.6: một phiên bản loại fixture có `has_quality_gate = false` đi `draft → awaiting_approval → live`
      không có `gate_run_id`; cùng đường với loại `agent` → 23514; `→ live` khi approval còn `pending` → 23514 ở
      cả hai loại; đổi cờ của loại fixture sang true → `draft → awaiting_approval` bị từ chối.
- [ ] R1.7: phiên bản `object` có `tighten_only` true và `compared_live_hash` bằng `definition_hash` của bản
      `live` → `draft → live` nhận, không approval; cùng giá trị với loại fixture không cổng khác `object` →
      23514; bỏ nhánh khỏi trigger → test đỏ.
- [ ] R1.8 (AL19): `dw_app` UPDATE `awaiting_approval → live` (approval `approved`) sau khi bản `live` đã đổi kể từ
      lúc gửi (`compared_live_hash` cũ) → 23514; bản `live` cũ vừa gỡ `superseded` trong cùng giao dịch và
      `compared_live_hash` là mã của nó → nhận; chưa có bản `live` lúc gửi lẫn lúc chuyển (cùng NULL) → nhận; gỡ luật
      khỏi trigger → test đỏ.
- [ ] R1.9 (AL21): bằng vai migrator, UPDATE một dòng phiên bản của tenant A đặt `publish_approval_id` là id một yêu
      cầu phê duyệt của tenant B → FK ghép từ chối, dòng không đổi; cùng id của một yêu cầu của tenant A → nhận; đổi FK
      sang một cột `publish_approval_id` → test đỏ.
- [ ] R2.10: gửi một phiên bản `agent` khi thành phần đã có bản `live` → `compared_live_hash` bằng `definition_hash`
      của bản đó; chưa có bản `live` → NULL.
- [ ] R2.1 (AL3): gửi kiểm định một nháp hợp lệ → bao đóng, Mã băm định nghĩa, Nơi đang dùng và audit
      `studio.version.submitted` ghi trong một giao dịch, phiên bản sang `evaluating`; người thiếu khóa gửi mà
      mục registry của loại khai → 403, không đổi gì.
- [ ] R2.2 (AL3): hai phiên bản cùng nội dung và bao đóng → cùng Mã băm định nghĩa; đổi phiên bản một
      công cụ ghim → Mã băm định nghĩa khác.
- [ ] R2.3 (AL3): rollback giữa giao dịch gửi kiểm định → không bản kê, phụ thuộc hay audit; bỏ một loại
      khỏi bao đóng của extractor fixture → test đỏ.
- [ ] R2.4: rút một Bản ứng viên → về `draft`, yêu cầu phê duyệt phát hành bị hủy, audit; người không
      phải người gửi gọi `withdraw` → 403.
- [ ] R2.5: gỡ một phiên bản Đang dùng không bị phụ thuộc → `retired` (`explicit`) với audit.
- [ ] R2.6: gỡ một phiên bản mà phiên bản Đang dùng của thành phần khác phụ thuộc → 409 `artifact_in_use`
      kèm danh sách; tenant B gửi id của tenant A → 404.
- [ ] R2.7 (AL10): đăng ký một kiểm fixture từ chối cho loại `workflow` → gửi kiểm định 422 với
      `reason_code` của kiểm, phiên bản vẫn `draft`, không bản kê hay audit; bỏ bước chạy bảng kiểm → test đỏ.
- [ ] R2.12: nháp được lưu lại sau khi người gửi tải nó, rồi gửi với `If-Match` cũ → 412 `precondition_failed` với
      `stale_version`, phiên bản vẫn `draft`, không `version_no` nào được cấp, không bản kê hay audit; `If-Match`
      đúng → gửi được; bỏ việc chuyển `If-Match` cho `seal` → test đỏ.
- [ ] R2.13: gửi không có `If-Match` → 428 `precondition_required`, không đổi gì.
- [ ] R7.9: đóng băng công ty rồi gửi kiểm định → 409 `tenant_frozen`, phiên bản vẫn `draft`.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:115`; spec: R2.4 (loại nghiêm
  chặn người gửi tự rút qua `decide`, cần route rút riêng).
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
