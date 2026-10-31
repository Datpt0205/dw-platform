# 03 — Gửi duyệt và phát hành

Status: needs-triage
Blocked by: 02
Area: studio
Yêu cầu: R6.3, R6.4, R6.5, R6.6, WAI10, WAI11, WAI12

## Mục tiêu

Chủ DW gửi bản nháp đã mô phỏng để một người khác duyệt; khi duyệt, phiên bản của tenant thành bất biến và DW chạy nó cho việc mới (R6.3-R6.6).

## Việc cần làm

1. Migration: bảng `platform.dw_workflow_versions` chỉ thêm (`tenant_id`, `workspace_id`, `dw_id`, `key`, `version` dạng `<semver gốc>+t<n>`, `content jsonb`, `content_sha256`, `base_sha256`, `author_id`, `approved_by`, `approval_id`, `created_at`), unique `(tenant_id, dw_id, version)`, RLS và quyền như ticket 02; `dw_app` không UPDATE hay DELETE ngoài offboarding.
2. `POST /api/v1/digital-workers/{dw_id}/workflow-draft/submit`: 409 `simulation_required` khi không có mô phỏng `passed` trên `content_sha256` hiện tại; mở approval `dw.workflow.publish` (payload: `dw_id`, `content_sha256`, `base_sha256`, diff) không lượt chạy, tiền tố strict, `DwDecisionAdmission(deciders=Validator hay Technical Owner)`, người soạn bị loại; bản nháp `submitted`.
3. Handler `dw.workflow.publish.decided` ở worker và API: duyệt thì trong một giao dịch kiểm ghim hiện tại của DW khớp `base_sha256` (khác thì bản nháp về `draft` với `reason` `base_changed`, audit, không phiên bản), ghi phiên bản, chuyển `workflow_version` của DW sang nó, audit đứng tên người duyệt với `details.lane`; từ chối thì bản nháp về `draft`.
4. Catalog trả phiên bản tenant theo ghim (`PinnedWorkflowsPort` có cài đặt đọc bảng khi `version` có hậu tố `+t`), bộ dựng graph `dw:<key>@<version>` cho nó; việc đang chạy giữ sha đã ghim lúc bắt đầu.
5. Test âm WAI10-WAI12, `mutations/03.yaml`; độ trễ theo `latency.md` vì thêm truy vấn trên đường chạy.

## Tiêu chí chấp nhận

- [ ] R6.3 (WAI10): sửa bản nháp sau mô phỏng rồi gửi: 409 `simulation_required`, 0 approval.
- [ ] R6.4 (WAI11): người soạn là Technical Owner quyết: 409 `second_person_required`; Validator quyết được.
- [ ] R6.5 (WAI12): duyệt: một phiên bản mới, ghim của DW trỏ tới nó, việc mới chạy theo nó, việc đang chờ giữ sha cũ.
- [ ] R6.6 (WAI12): đổi ghim của DW sau khi gửi rồi duyệt: bản nháp `draft` với `base_changed`, 0 phiên bản, ghim giữ giá trị đã đổi.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `docs/adr/0120-publish-gate-and-run-control-switches.md:78`; `packages/python/dw_platform/src/dw_platform/application/decision_gate.py:160`; spec: R6.3-R6.6, WAI10-WAI12.

## Comments

- 2026-10-31 (agent): viết cùng spec.
