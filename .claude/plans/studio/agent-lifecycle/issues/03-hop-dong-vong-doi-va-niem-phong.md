# 03 — Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong

Status: needs-triage
Blocked by: 01, .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R7.9, AL1, AL2, AL3, AL10

## Mục tiêu

Cài hợp đồng Giai đoạn trên vỏ phiên bản dùng chung: trigger canh chuyển trạng thái, cột cổng và route
gửi kiểm định niêm phong nội dung rồi tính bao đóng và Mã băm định nghĩa, để máy trạng thái thuộc
database và "đã kiểm định" tính được (spec R1, R2). Đứng trên vỏ `studio.artifact_versions` với cột
`stage` và bước niêm phong của tenant-config, và băm `dw_kernel.canonical`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên), thêm cột vòng đời trên `studio.artifact_versions` (vỏ chung
   của tenant-config, DO-05 chọn vỏ chung): `gate_run_id uuid` NULL FK `studio.gate_runs` ON DELETE
   RESTRICT (bắt buộc khi `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng,
   luôn NULL với loại không cổng); `publish_approval_id uuid`
   NULL FK `platform.approval_requests` ON DELETE RESTRICT (bắt buộc cùng điều kiện); `contributor_ids
uuid[] NOT NULL CHECK (cardinality(contributor_ids) >= 1)`; `submitted_by`, `submitted_at`,
   `published_by`, `published_at`, `retired_by`, `retired_at`; `retire_reason_code` CHECK (`superseded`,
   `explicit`); `stage_changed_at timestamptz NOT NULL`. Cột `gate_run_id` FK tạm để NULL tới khi ticket
   04 tạo `studio.gate_runs`, hoặc migration này đứng sau migration bảng cổng của ticket 04 (ticket 04
   không chặn ticket này vì FK thêm ở migration sau).
2. Hàm `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE): chèn là `draft`; `draft → evaluating`
   (có mã băm và `gate_run_id`); `evaluating → draft`; `evaluating → awaiting_approval` (gate `passed`,
   `definition_hash` của gate bằng của phiên bản, approval `pending`); `awaiting_approval → draft`;
   `awaiting_approval → live` (approval `approved`, người quyết không trong `contributor_ids` và không
   là `submitted_by`, gate vẫn `passed` trên cùng mã băm); `live → retired`; cột nội dung đổi chỉ khi
   `draft`. Luật theo loại (spec R1.6): với loại mà sổ loại `studio.artifact_kinds` của tenant-config ghi là
   không có Cổng chất lượng (đối tượng `dw.object/v1`, công cụ), cho `draft → awaiting_approval` không qua
   `evaluating` và không đòi `gate_run_id`; `awaiting_approval → live` vẫn đòi approval `approved` và người
   quyết ngoài `contributor_ids`. Từ chối: SQLSTATE 23514, ràng buộc `ck_artifact_versions_stage_transition`.
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
5. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/submit`
   (`studio.versions.submit`, `Idempotency-Key`) trong một giao dịch: hỏi `RunControlPort` của ticket 01,
   đóng băng thì 409 `tenant_frozen` hay `platform_frozen` (spec R7.9); tính bao đóng bằng extractor của
   loại, gọi bước niêm phong của tenant-config (cấp `version_no`, ghi `content_hash`, `definition_hash`,
   Nơi đang dùng), chạy các kiểm của bảng kiểm theo loại (một kiểm từ chối → 422 với `reason_code` của nó,
   giao dịch lùi, phiên bản giữ `draft`; spec R2.7), chuyển `draft → evaluating`, xếp Lượt kiểm định hoặc
   dùng lại bằng chứng (ticket 04), audit `studio.version.submitted`. `POST .../withdraw`: hủy yêu cầu phê duyệt phát hành treo bằng
   `ApprovalRequest.cancel()` và về `draft`, audit `studio.version.returned_to_draft`. `POST .../retire`
   (`studio.versions.retire`, lý do): `live → retired` (`explicit`), 409 `artifact_in_use` kèm danh sách
   khi phiên bản Đang dùng khác phụ thuộc, audit `studio.version.retired`.
6. Test catalog `test_version_stage_contract.py`: hỏi `pg_catalog` rằng mọi bảng `studio.*` có cột
   `stage` đều có trigger, các CHECK và hai chỉ mục từng phần; test đọc CHECK so với `VersionStage`.

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
- [ ] R1.6: một phiên bản loại không cổng đi `draft → awaiting_approval → live` không có `gate_run_id`; cùng
      đường với loại `agent` → 23514; `→ live` khi approval còn `pending` → 23514 ở cả hai loại.
- [ ] R2.1 (AL3): gửi kiểm định một nháp hợp lệ → bao đóng, Mã băm định nghĩa, Nơi đang dùng và audit
      `studio.version.submitted` ghi trong một giao dịch, phiên bản sang `evaluating`.
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
