# 05 — Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau

Status: needs-triage
Blocked by: 04, .claude/plans/studio/connections-and-vault/issues/04-ket-noi-dung-chung-theo-workspace.md, .claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, R8.12, R8.13, R8.14, R8.15, R3.6, R3.7, G4, TC15, TC16, TC17, TC18, TC19, TC20, TC21, TC22, TC23, TC25, TC26

## Mục tiêu

Tài liệu chỉ nêu tên điểm gắn; giá trị (kết nối, biến, người chạy) là một Bộ giá trị gắn, tức phiên bản
cấu hình riêng loại `binding_set`, do một người đề xuất và một người khác duyệt trên yêu cầu phê duyệt
không lượt chạy của nền tảng. Phát hành từ chối khi thiếu giá trị bắt buộc, nhận lượt chạy từ chối khi
kết nối hỏng, và mỗi lượt chạy ghim giá trị nó dùng (spec R7, R8; D11). Pilot Marketing cần điểm gắn
`zalo_oa`, `email_sender` và `score_threshold` theo đúng đường này.

## Việc cần làm

1. Lược đồ `bindings[]` dùng chung trong lõi `dw_studio`: mỗi mục `{name, kind, required, description}`,
   `name` khớp `^[a-z][a-z0-9_]{0,62}$` và không trùng trong tài liệu; `kind` ở W1 là `connection`
   (`connector_key`, phiên bản chính, `required_scopes`), `variable` (kiểu, ràng buộc, `default` mã hóa
   thành chuỗi) và `principal` (một chủ thể của tenant: tài khoản dịch vụ khi điểm gắn là danh tính chạy,
   ADR-0103 (Accepted) và workflow-triggers:R3.1; thành viên khi điểm gắn là người dự phòng của bước giao,
   workflow-nodes:R6.3); `secret`, `webhook_endpoint`, `schedule` vào cùng bên đọc của chúng
   (ADR-0110 (Accepted) quyết 6). Bộ kiểu Điểm gắn này là chỗ duy nhất các spec khác đăng ký kiểm riêng
   của một kind (như `grants_cover` của workflow-triggers/01), không phải `ConfigKindRegistry`.
    - Bộ trích xuất của mọi loại ghi mỗi điểm gắn khai báo thành một dòng `studio.dependencies` với
      `to_kind` `binding`, `usage` `bind`, `to_key` là tên.
    - Bước niêm phong của ticket 02 quét mọi chuỗi của tài liệu: chuỗi trùng id của một dòng
      `platform.connections` của tenant → lỗi 422 tại con trỏ đó (TC23).
2. Revision Alembic mới (id hex ngẫu nhiên), chép nguyên văn mục Dữ liệu của spec:
   `platform.config_versions`: `kind` CHECK (`binding_set`); `key` là id thành phần; `action` CHECK
   (`set`); `version_no` tăng theo khóa, không dùng lại; `base_version`; `document` jsonb object tối đa
   256 KiB, NFC; `document_hash`; `status` CHECK (`proposed`, `approved`, `rejected`, `withdrawn`,
   `superseded`); partial unique một `approved` và một `proposed` mỗi khóa; `workspace_id` là nơi đề
   xuất; FK `(tenant_id, workspace_id, approval_id)` tới `platform.approval_requests`;
   `ck_config_versions_checker_not_maker`; trigger `approved_by_approval`; `dw_app` chỉ UPDATE `status`,
   `decided_by`, `decided_at`, `decision_comment`, `superseded_at`. Thêm:
    - `proposed_by`, `proposed_at`, `decided_by`, `decided_at`, `decision_comment`, `superseded_at`;
      `ck_config_versions_checker_not_maker` là `decided_by IS NULL OR decided_by <> proposed_by`; FK tới
      yêu cầu phê duyệt ON DELETE RESTRICT qua `uq_approval_requests_tenant_id_workspace_id_id`, ràng buộc
      đã có (`db/migrations/versions/e399be8c0a2d_platform_approval_view_receipts_and_.py:127-129`), ticket
      này chỉ dùng.
    - Trigger `approved_by_approval` từ chối chuyển sang `approved` khi yêu cầu phê duyệt liên kết chưa ở
      `approved`, và từ chối mọi đổi `status` ngoài `proposed` sang `approved`, `rejected`, `withdrawn`
      và `approved` sang `superseded` (TC17); grant cột cho `dw_app` như trên, không DELETE.
    - RLS ENABLE và FORCE chỉ theo tenant; `test_privileges.py` khẳng định grant cột;
      `test_rls_coverage.py` thấy bảng.
    - `platform.run_manifest_keys` thêm `config_version_id` FK RESTRICT có index, và CHECK
      `num_nonnulls(artifact_version_id, config_version_id) = 1`.
    - Offboarding: `platform.config_versions` vào `_ORDERED_FIRST` sau `platform.run_manifests` và trước
      phần xóa theo chữ cái (nơi có `platform.approval_requests`).
    - Đăng ký khóa `studio.bindings.propose` và `studio.bindings.approve` vào danh mục quyền của
      tenant-rbac/01 trong cùng migration.
3. `ConfigKindRegistry` và `ConfigVersionService` trong `dw_platform` (ADR-0110 (Accepted) quyết 3-4);
   mục `binding_set` do `dw_studio` đăng ký ở composition root: JSON Schema sinh từ khai báo của phiên
   bản niêm phong mới nhất của thành phần; bộ kiểm (kết nối cùng tenant, không thì 404; đúng trình kết
   nối và phiên bản chính, đủ `required_scopes`, `connection_usable` đúng với Người đề xuất theo
   connections-and-vault/04, biến đúng kiểu, không thì 422); quyền đề xuất `studio.bindings.propose`,
   quyền duyệt `studio.bindings.approve`; test bên đọc: bộ dựng bản kê đọc bản `approved`. Loại không
   đăng ký → 422.
4. `ConfigVersionService.propose`, một giao dịch: kiểm quyền đề xuất ở workspace đang làm việc (403);
   kiểm giá trị (404, 422); một đề xuất mở mỗi khóa (409 `proposal_open`); hàm SQL chung
   `platform.checker_candidates(tenant, 'studio.bindings.approve', người đề xuất, workspace của đề xuất)` của
   tenant-rbac/02 trên `platform.effective_grants` (cùng hàm `no_checker_available` của tenant-rbac:R7.3 dùng)
   trả rỗng → 409 `no_checker_available`; ghi phiên bản `proposed` với
   `base_version` là `version_no` của phiên bản niêm phong mới nhất đã dùng để kiểm; tạo yêu cầu phê
   duyệt không lượt chạy `config.version` ở workspace đang làm việc, `required_scope` là quyền duyệt
   (ADR-0004 (Accepted)), payload chỉ gồm id, `kind`, `key`, `version_no`, `document_hash`; audit
   `config.version.proposed`. `Idempotency-Key` theo ADR-0108 (Accepted) quyết 4.
5. Phê duyệt: `config.` vào `strict_approval_prefixes` bằng `|=` ở API
   (`apps/api/src/dw_api/bootstrap/runtime.py`) và worker (`apps/worker/src/dw_worker/main.py`). Port
   `ApprovalDecisionGuard` async và `ProposedDecision` từ dw-proterial (`dw_agent_runtime/approval_flow.py`)
   thay `DecisionGuard` đồng bộ, giữ guard `memory.review` (G4). Guard `ConfigVersionDecisions.check` trả
   409 `decision_stale` khi `base_version` không còn là phiên bản niêm phong mới nhất hay bản `approved`
   đang hiệu lực đã đổi, trước khi quyết định được ghi.
6. Worker: handler outbox cho `config.version.decided` (tên từ `decided_event_type`), đăng ký trong
   `apps/worker/src/dw_worker/main.py`. `ConfigSettlement.settle` idempotent theo id yêu cầu phê duyệt:
   duyệt → `approved` và bản trước `superseded` trong một giao dịch, audit `config.version.approved` qua
   `lane_audit_event` của lane `outbox` (actor `system:outbox`, `details.decided_by`); từ chối →
   `rejected`, audit `config.version.rejected`; dòng không còn `proposed` hay khóa đã có bản khác được
   duyệt → `rejected` với `details.reason` `settlement_conflict`; giao lại sau khi đã quyết toán → không
   đổi gì, không audit thứ hai.
7. Rút đề xuất: chỉ Người đề xuất (khác → 403); một giao dịch đặt `withdrawn`, gọi
   `ApprovalRequest.cancel()` trên yêu cầu liên kết, audit `config.version.withdrawn` (prefix nghiêm chặn
   đường tự từ chối, Quyết định của spec).
8. `BindingStatus.satisfied(version_id)` đáp ứng Protocol kiểm điểm gắn mà việc phát hành của
   agent-lifecycle khai: mọi điểm gắn `required` của phiên bản có giá trị trong bản `approved` của thành
   phần và qua bộ kiểm; không thì trả `binding_unset` kèm tên (việc phát hành trả 409).
9. Nhận lượt chạy: `RunManifestBuilder` của ticket 04 thêm mục `bindings` vào bản kê: id phiên bản Bộ
   giá trị gắn, với mỗi kết nối id kết nối và phiên bản credential, với mỗi biến `content_hash` của giá
   trị (không ghi giá trị), với `principal` id của người chạy; thêm dòng `platform.run_manifest_keys` cho
   phiên bản cấu hình. Trước khi ghim, `connection_usable` cho người chạy sai → từ chối nhận với
   `binding_degraded`, không node nào chạy. Ticket này đáp ứng `RunBindingsPort` (connections-and-vault và
   handler của lượt chạy khai): đọc giá trị từ mục `bindings` của bản kê đã ghim, không từ Bộ giá trị gắn
   hiện hành; workflow-engine và agent-builder không cài port này.
10. Route: `GET /api/v1/studio/artifacts/{id}/bindings` (khai báo, giá trị hiện hành với tên kết nối người
    gọi đọc được, đề xuất mở, trạng thái từng điểm gắn), `POST /api/v1/studio/artifacts/{id}/bindings/proposals`,
    `POST /api/v1/studio/artifacts/{id}/bindings/proposals/{config_version_id}/withdraw`. Mọi id là UUID.
    `make generate-contracts`.
11. `ConnectionDependentsPort` (connections-and-vault khai) do ticket này đáp ứng ở composition root: một
    Kết nối đang được dùng khi một Bộ giá trị gắn `approved` có giá trị là Kết nối đó, hoặc một dòng
    `studio.dependencies` trỏ tới nó; trả số đếm và tên theo quyền người gọi như R3.4 (R3.7).

## Tiêu chí chấp nhận

- [ ] R7.1 (TC23): niêm phong tài liệu `fixture` có id của một kết nối của tenant ở một trường tự do → 422,
      mỗi chỗ một con trỏ; gỡ bước quét → test đỏ.
- [ ] R7.2 (TC22): phiên bản khai `zalo_oa` bắt buộc chưa có giá trị đã duyệt → `binding_unset` nêu
      `zalo_oa`; có giá trị đã duyệt → đạt.
- [ ] R7.3 (TC22): thu hồi kết nối đã gắn rồi nhận lượt chạy → từ chối `binding_degraded`, không dòng
      `platform.run_manifests` mới, không node nào chạy.
- [ ] R7.4 (TC15): bản kê có id phiên bản Bộ giá trị gắn, id và phiên bản credential của kết nối, mã băm
      của biến; tìm token mẫu và giá trị biến dạng rõ trong `body` → không thấy.
- [ ] R7.5 (TC15): duyệt Bộ giá trị gắn mới khi lượt chạy chờ duyệt; tiếp tục → lượt chạy dùng bộ đã
      ghim.
- [ ] R8.1: đề xuất hợp lệ ghi một phiên bản `proposed`, một yêu cầu `config.version` có `required_scope`
      `studio.bindings.approve` và một audit `config.version.proposed`, trong một giao dịch.
- [ ] R8.2 (TC25): người thiếu `studio.bindings.propose` → 403, không dòng nào.
- [ ] R8.3 (TC19): thành phần hay kết nối của tenant khác → 404, không dòng nào.
- [ ] R8.4 (TC25): kết nối sai trình kết nối, thiếu quyền khai báo, hay `connection_usable` sai với Người
      đề xuất → 422, không dòng nào.
- [ ] R8.5 (TC18): workspace chỉ Người đề xuất giữ `studio.bindings.approve` → 409
      `no_checker_available`, không dòng nào.
- [ ] R8.6 (TC18): đề xuất thứ hai cùng khóa khi đề xuất đầu còn mở → 409 `proposal_open`.
- [ ] R8.7 (TC19): đề xuất loại `prompt` → 422; INSERT thẳng `kind = 'prompt'` → CHECK từ chối.
- [ ] R8.8 (TC16): Người đề xuất quyết yêu cầu của mình → 409; UPDATE `decided_by = proposed_by` → CHECK
      từ chối; bỏ `config.` khỏi prefix nghiêm ở API → test đỏ.
- [ ] R8.9 (TC20): niêm phong phiên bản đổi khai báo điểm gắn sau khi đề xuất, rồi quyết định → 409
      `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ.
- [ ] R8.10 (TC17): duyệt → handler đặt `approved`, bản trước `superseded`, audit có actor
      `system:outbox`.
- [ ] R8.11 (TC20): từ chối → `rejected`; quyết toán gặp khóa đã có bản khác được duyệt → `rejected` với
      `settlement_conflict`.
- [ ] R8.12 (TC17): UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; UPDATE
      `superseded` về `proposed` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; gỡ
      trigger → test đỏ.
- [ ] R8.13: Người đề xuất rút → `withdrawn`, yêu cầu phê duyệt `cancelled`, một audit
      `config.version.withdrawn`, trong một giao dịch.
- [ ] R8.14 (TC26): người khác rút → 403, đề xuất và yêu cầu không đổi; bỏ so `proposed_by` → test đỏ.
- [ ] R8.15 (TC17): outbox giao lại sự kiện đã quyết toán → không dòng nào đổi, không audit thứ hai.
- [ ] G4: `test_the_api_decides_memory_reviews_strictly_and_only_with_clearance` vẫn xanh sau khi đổi sang
      guard async.
- [ ] R3.6 (TC21): purge tenant có phiên bản cấu hình riêng được bản kê ghim và yêu cầu phê duyệt của nó
      → xong, tenant khác nguyên; gỡ mục `platform.config_versions` khỏi `_ORDERED_FIRST` → test đỏ.
- [ ] R3.7: Kết nối là giá trị của một Bộ giá trị gắn `approved` → `ConnectionDependentsPort` báo đang
      dùng; bản đó sang `superseded` bởi bản không dùng Kết nối → báo không dùng; bỏ đọc
      `platform.config_versions` → ca đầu đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:47`; spec: R8.9, G4.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:118-124`; spec: R8.8, R8.13.
- `apps/api/src/dw_api/bootstrap/runtime.py:237`; `apps/worker/src/dw_worker/main.py:175`; spec: TC16.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:77`; spec: R8.5.
- `packages/python/dw_platform/src/dw_platform/domain/audit.py:67`; spec: R8.10; ADR-0110 (Accepted)
  quyết 1-2, 6-8.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 08 và 09. Chờ DO-06 (Đạt). Tên khóa quyền và cách rút đề
  xuất là quyết định tạm của spec. Outbox `config.version.approved` ra cùng bên đọc của nó (lệch cấu
  hình, W2).
- 2026-10-23 (agent): DO-06 đã có lời đáp (Đạt 23/10/2026, tài liệu giữ tên điểm gắn), nên ticket về
  `needs-triage`. Theo phiếu cùng ngày: chờ foundations-hardening/06 (OPS-b) và tenant-rbac/02 (hàm tìm
  người duyệt chung); `principal` nhận cả người dự phòng của bước giao (Q6); ticket này đáp ứng
  `RunBindingsPort` và `ConnectionDependentsPort`.
