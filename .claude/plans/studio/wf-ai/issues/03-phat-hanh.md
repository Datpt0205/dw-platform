# 03 — Gửi duyệt và phát hành

Status: resolved (2026-11-02, main)
Blocked by: 02
Area: studio
Yêu cầu: R6.3, R6.4, R6.5, R6.6, R6.8, R6.10, R6.11, R6.14, R6.16, WAI10, WAI11, WAI12, WAI14, WAI16, WAI17

## Mục tiêu

Chủ DW gửi bản nháp đã mô phỏng để một người khác duyệt; khi duyệt, đúng nội dung đã duyệt thành phiên bản bất biến của tenant và DW chạy nó cho việc mới (R6.3-R6.6, R6.8, R6.10, R6.11, R6.14, R6.16).

## Việc cần làm

1. Migration: `platform.dw_workflow_versions` chỉ thêm (`tenant_id`, `workspace_id`, `dw_id`, `key`, `version` dạng `<semver gốc>+t<n>`, `content jsonb`, `content_sha256`, `base_sha256`, `author_ids uuid[]`, `approved_by uuid`, `approval_id uuid` unique, `created_at`), unique `(tenant_id, dw_id, version)`, RLS và quyền như ticket 02; `dw_app` không UPDATE, DELETE chỉ qua offboarding.
2. `POST /api/v1/digital-workers/{dw_id}/workflow-draft/submit`: 409 `draft_submitted` khi đã gửi (R6.8); 409 `simulation_required` khi dòng mô phỏng không `passed` trên `content_sha256` hiện tại (R6.3); UPDATE có điều kiện `draft` → `submitted` và mở approval `dw.workflow.publish` (payload: `dw_id`, `content_sha256`, `base_sha256`, `author_ids`; không lượt chạy) cùng giao dịch, tiền tố strict `dw.workflow.`, `DwDecisionAdmission(deciders=Validator hay Technical Owner)` loại `author_ids` và người gửi (R6.4). `PUT` và `simulate` của ticket 02 trả 409 `draft_submitted` khi `submitted` (R6.8). `POST .../withdraw`: hủy approval và về `draft` cùng giao dịch (R6.10). `Idempotency-Key` và audit trên cả hai.
3. Handler `dw.workflow.publish.decided` ở worker và API: duyệt thì trong một giao dịch khóa dòng DW và bản nháp, so hash của phiên bản DW đang ghim với `base_sha256` (khác: `base_changed`) và `content_sha256` của bản nháp với của approval (khác: `content_changed`), cả hai về `draft` với `reason`, audit, không phiên bản (R6.6); khớp thì ghi phiên bản với `n` = lớn nhất của `(tenant, dw_id)` cộng 1, đọc dưới dòng DW đã khóa, đổi `workflow_version` của DW, xóa bản nháp, audit đứng tên người duyệt với `details.lane` (R6.5); `approval_id` unique làm lần giao lại không ghi gì (R6.14); từ chối hay hủy thì về `draft` (R6.11).
4. Catalog: `PinnedWorkflowsPort` có cài đặt đọc `dw_workflow_versions` theo `(dw_id, version)` dưới tenant và workspace của DW khi `version` có hậu tố `+t`, không thấy thì 404 `workflow_not_shipped` (R6.16); bộ dựng graph `dw:<key>@<version>` cho nó; lượt chạy ghim sha của phiên bản như với bản gói.
5. Test âm WAI10, WAI11, WAI12, WAI14, WAI16, WAI17; `mutations/03.yaml`; độ trễ theo `latency.md` vì thêm truy vấn trên đường chạy.

## Tiêu chí chấp nhận

- [x] R6.3 (WAI10): lưu lại sau mô phỏng rồi gửi: 409 `simulation_required`, 0 approval.
- [x] R6.8 (WAI14): `PUT` khi `submitted`: 409 `draft_submitted`, nội dung không đổi.
- [x] R6.4 (WAI11): người lưu là Technical Owner quyết: 409 `second_person_required`; Validator quyết được.
- [x] R6.4 (WAI16): A lưu, B lưu và gửi, A quyết: 409 `second_person_required`.
- [x] R6.10: rút: approval `cancelled`, bản nháp `draft`, một dòng audit.
- [x] R6.5 (WAI12): duyệt: phiên bản `1.0.0+t1`, ghim của DW trỏ tới nó, việc mới chạy theo nó, việc đang chờ giữ sha cũ; lần duyệt sau ra `1.0.0+t2`.
- [x] R6.6 (WAI12): đổi ghim của DW sau khi gửi rồi duyệt: `base_changed`, 0 phiên bản, ghim giữ giá trị đã đổi.
- [x] R6.6 (WAI14): ghi đè `content` bản nháp bằng migrator sau khi gửi rồi duyệt: `content_changed`, 0 phiên bản.
- [x] R6.11: từ chối, và hủy qua `withdraw`: bản nháp `draft`, ghim không đổi.
- [x] R6.14 (WAI17): giao lại sự kiện đã xử lý: vẫn một phiên bản, một dòng audit phát hành.
- [x] R6.16: DW của tenant B ghim `1.0.0+t1` mà chỉ tenant A có, và DW thứ hai cùng workspace ghim `1.0.0+t1` của DW thứ nhất: cả hai 404 `workflow_not_shipped`.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `docs/adr/0120-publish-gate-and-run-control-switches.md:78`; `packages/python/dw_platform/src/dw_platform/application/decision_gate.py:160`; spec: R6.3-R6.6, R6.8, R6.10, R6.11, R6.14, R6.16, WAI10-WAI12, WAI14, WAI16, WAI17.

## Comments

- 2026-10-31 (agent): viết cùng spec.
- 2026-11-02 (agent): viết lại sau gate CHƯA ĐẠT: hash trong approval, khóa khi chờ, rút, xử lý một lần, loại mọi người đã lưu.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): `dw_workflow_versions` có thêm `seq` (CHECK buộc `version` kết thúc bằng `+t<seq>`, unique theo DW) để đếm `n` không phải tách chuỗi; `dw_workflow_drafts.approval_id` (CHECK `submitted` ⇔ có approval) để quyết định và rút chỉ tác động bản nháp đang chờ đúng approval đó. Handler `dw.workflow.publish.decided` chỉ ở worker (API không chạy outbox); API và worker cùng đăng ký tiền tố strict `dw.workflow.` và `PUBLISH_ADMISSION`. Gửi và rút ở `WorkflowPublishing` (`wflite/publish.py`), tách khỏi `WorkflowDrafts`, port hẹp và không vòng import. Nếu sai thì: gộp lại vào `WorkflowDrafts`.
    - Khác ticket: phiên bản tenant chạy dưới `run_version` `<semver>+t<n>.<sha256 nội dung>`, không `+t<n>` trần, vì graph đăng ký theo process và `+t1` của hai tenant là hai tài liệu; `WorkerDefinition` và `RunContext.worker_version` nhận build metadata semver. Graph của phiên bản tenant được đăng ký lần đầu dùng (`TenantWorkflowGraphs.ensure`, đọc dưới tenant của lượt chạy, kiểm lại hash nội dung) ở runner (start, resume) và ở `ApproveAndResumeService` trước `hosts`; giữ đến hết process, chặn trên bởi số phiên bản đã phát hành. Nếu sai thì: một kho graph có hạn (LRU) thay cho đăng ký vĩnh viễn.
    - Thêm: DW mới không ghim được `+t<n>` (422 `workflow_invalid`); `PackCatalog.schema` đọc theo semver của gói nên việc mới của DW ghim phiên bản tenant vẫn kiểm theo schema của kind; rút sau khi đã quyết là 409 `approval_decided` (quyết định đó do settlement xử lý); ghim tenant mà dòng phiên bản mất thì coi là `base_changed` (đóng an toàn).
    - Test: unit `test_wflite_publish.py` 29 ca, `test_digital_workers.py` thêm một ca; integration `apps/api/tests/integration/test_wf_ai_publish.py` 13 ca, `apps/worker/tests/integration/test_wflite_runs_db.py` thêm hai ca (việc mới chạy phiên bản tenant, việc đang chờ giữ sha gói, process khác quyết và chạy tiếp; ghim `+t1` của DW khác thì việc `failed`); `test_privileges.py` thêm một ca; `test_rls_coverage.py`, `test_offboarding_coverage.py` xanh với bảng mới.
    - `mutations/03.yaml` 11 đột biến, chưa chạy (chạy ở lượt kiểm tra cuối hàng đợi, `wave-close.md` 2/11/2026). Độ trễ cũng để lượt cuối.
    - `reviewing-feature-security` (đọc): tenant (bảng RLS bật và FORCE theo dạng workspace, tenant B 404 và đọc 0 dòng, graph đọc dưới tenant của lượt chạy và khóa theo sha đầy đủ); phân quyền (gửi, rút chỉ chủ DW, Validator 403, người lạ 404; quyết bởi Validator hay Technical Owner, không tác giả, không người gửi, kể cả qua Zalo vì worker đăng ký cùng admission); duyệt (phát hành chỉ từ dòng quyết định `approved`, kiểm lại hash gốc và hash nội dung dưới khóa dòng DW); nội dung không tin (payload approval dựng phía server từ dòng bản nháp đã khóa, chỉ định danh và hash); audit (`submitted`, `withdrawn` cùng giao dịch; `published`, `returned` đứng tên người quyết với `details.lane`); vòng đời (phiên bản chỉ thêm, `dw_app` không UPDATE, xóa qua offboarding).
