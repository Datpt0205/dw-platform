# 05 — Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau

Status: needs-triage
Blocked by: 04, .claude/plans/studio/connections-and-vault/issues/04-ket-noi-dung-chung-theo-workspace.md, .claude/plans/studio/runtime-hardening/issues/03-run-va-outbox-khong-ket.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, R8.12, R8.13, R8.14, R8.15, R8.16, R2.18, R3.6, R3.7, R3.8, G4, TC15, TC16, TC17, TC18, TC19, TC20, TC21, TC22, TC23, TC25, TC26, TC29, TC31

## Mục tiêu

Tài liệu chỉ nêu tên điểm gắn; giá trị (kết nối, biến, người chạy) là một Bộ giá trị gắn, tức phiên bản
cấu hình riêng loại `binding_set`, do một người đề xuất và một người khác duyệt trên yêu cầu phê duyệt
không lượt chạy của nền tảng. Lệnh gửi và phát hành từ chối khi thiếu giá trị bắt buộc, nhận lượt chạy từ chối khi
kết nối hỏng, và mỗi lượt chạy ghim giá trị nó dùng, không ghim phiên bản bí mật của kết nối, vì lời gọi dùng phiên
bản mới nhất chưa bị thu hồi lúc gọi (spec R7, R8; D11; V4.35). Pilot Marketing cần điểm gắn
`zalo_oa`, `email_sender` và `score_threshold` theo đúng đường này.

## Việc cần làm

1. Lược đồ `bindings[]` dùng chung trong lõi `dw_studio`: mỗi mục `{name, kind, required, description}`,
   `name` khớp `^[a-z][a-z0-9_]{0,62}$` và không trùng trong tài liệu; `kind` ở W1 là `connection`
   (`connector_key`, phiên bản chính, `required_scopes`), `variable` (kiểu, ràng buộc, `default` mã hóa
   thành chuỗi) và `principal` (một chủ thể của tenant: tài khoản dịch vụ khi điểm gắn là danh tính chạy,
   ADR-0103 (Accepted) và workflow-triggers:R3.1; thành viên khi điểm gắn là người dự phòng của bước giao,
   workflow-nodes:R6.3); `secret`, `webhook_endpoint`, `schedule` vào cùng bên đọc của chúng
   (ADR-0110 (Accepted) quyết 6). Bộ kiểu Điểm gắn này là chỗ duy nhất các spec khác đăng ký kiểm riêng
   của một kind, không phải `ConfigKindRegistry`: mỗi kind có một kiểm lúc đề xuất (như `grants_cover` của
   workflow-triggers/01). Không kind nào ở W1 có kiểm lúc nhận lượt chạy riêng, nên bộ kiểu không có chỗ cho kiểm đó
   tới khi kind đầu tiên cần nó (failure-modes #1): kết nối qua `connection_usable` ở bước 9, còn `binding_needs_review`
   của kind `principal` do `BindingReviewPort` hỏi ở dispatch (workflow-engine:R5.19; workflow-triggers:R3.7; V4.16).
    - Bộ trích xuất của mọi loại ghi mỗi điểm gắn khai báo thành một dòng `studio.dependencies` với
      `to_kind` `binding`, `usage` `bind`, `to_key` là tên.
    - Bước niêm phong của ticket 02 quét mọi chuỗi của tài liệu: chuỗi trùng id của một dòng
      `platform.connections` của tenant → lỗi 422 tại con trỏ đó (TC23).
2. Revision Alembic mới (id hex ngẫu nhiên), chép nguyên văn mục Dữ liệu của spec:
   `platform.config_versions`: `uq_config_versions_tenant_id_id UNIQUE (tenant_id, id)`, đích của FK ghép
   `config_version_id` của `platform.run_manifest_keys` (R2.18); `kind` CHECK (`binding_set`); `key` là id thành
   phần; `action` CHECK (`set`); `version_no` tăng theo khóa, không dùng lại; `base_version`; `document` jsonb object
   tối đa 256 KiB, NFC; `document_hash`; `status` CHECK (`proposed`, `approved`, `rejected`, `withdrawn`,
   `superseded`); partial unique một `approved` và một `proposed` mỗi khóa; `workspace_id` là nơi đề xuất; FK ghép
   `(tenant_id, workspace_id, approval_id)` tới `platform.approval_requests` ON DELETE RESTRICT, qua
   `uq_approval_requests_tenant_id_workspace_id_id`, có index `(tenant_id, workspace_id, approval_id)` (R8.16);
   `ck_config_versions_checker_not_maker`; trigger `approved_by_approval`; `dw_app` chỉ UPDATE `status`, `decided_by`,
   `decided_at`, `decision_comment`, `superseded_at`, và DELETE chỉ ở lượt xóa của offboarding (spec R3.8). Thêm:
    - `proposed_by`, `proposed_at`, `decided_by`, `decided_at`, `decision_comment`, `superseded_at`;
      `ck_config_versions_checker_not_maker` là `decided_by IS NULL OR decided_by <> proposed_by`; FK tới
      yêu cầu phê duyệt ON DELETE RESTRICT qua `uq_approval_requests_tenant_id_workspace_id_id`, ràng buộc
      đã có (`db/migrations/versions/e399be8c0a2d_platform_approval_view_receipts_and_.py:127-129`), ticket
      này chỉ dùng, với index `(tenant_id, workspace_id, approval_id)` của chính bảng này.
    - Trigger `approved_by_approval` từ chối chuyển sang `approved` khi yêu cầu phê duyệt liên kết chưa ở
      `approved`, và từ chối mọi đổi `status` ngoài `proposed` sang `approved`, `rejected`, `withdrawn`
      và `approved` sang `superseded` (TC17); grant cột cho `dw_app` như trên, cùng DELETE mà trigger BEFORE DELETE
      `platform.refuse_delete_outside_offboarding()` của ticket 02 trên bảng chỉ cho qua ở lượt xóa của offboarding
      (spec R3.8, TC31): ứng dụng không xóa phiên bản cấu hình nào (đề xuất bị từ chối, rút hay bị thay vẫn là hồ sơ),
      và lane `offboarding` chỉ xóa bảng có trong `_CATALOG_PURGEABLE`.
    - RLS ENABLE và FORCE chỉ theo tenant; `test_privileges.py` khẳng định grant cột;
      `test_rls_coverage.py` thấy bảng.
    - `platform.run_manifest_keys` thêm `config_version_id` với FK ghép `(tenant_id, config_version_id)` tới
      `uq_config_versions_tenant_id_id` ON DELETE RESTRICT (R2.18), index `(tenant_id, config_version_id)` và unique
      `(tenant_id, manifest_hash, config_version_id)`; CHECK `num_nonnulls(artifact_version_id, config_version_id) = 1`;
      và trong cùng bước `ALTER COLUMN artifact_version_id DROP NOT NULL`, vì ticket 04 tạo cột đó NOT NULL còn dòng
      khóa của phiên bản cấu hình để nó NULL.
    - Offboarding, trên `offboarding.py` và `test_offboarding.py` mà foundations-hardening/07 đã viết lại:
      `platform.config_versions` dùng bước mặc định của sổ bước xóa (foundations-hardening:R11.4; H-2), không đăng ký
      bước nào; thứ tự suy từ `pg_constraint` đặt nó sau `platform.run_manifest_keys` (FK RESTRICT `config_version_id`
      giữ nó) và trước `platform.approval_requests` (FK RESTRICT `approval_id` của nó giữ bảng đó).
    - Đăng ký khóa `studio.bindings.propose` và `studio.bindings.approve` vào `platform.permissions` (danh mục của
      tenant-rbac/01) trong cùng migration. Câu INSERT nêu mọi cột NOT NULL có lúc đó: `area`, `label_vi`,
      `scope_kind` (`workspace`), `risk`, `status` (`active`), `owner_package` của tenant-rbac/01 và
      `tenant_grantable` của tenant-rbac/02 (ADR-0104 (Accepted) quyết 1), với `risk` `standard` theo bảng phân loại
      của tenant-rbac/01 và `tenant_grantable` `true` theo tenant-rbac/02.
3. `ConfigKindRegistry` và `ConfigVersionService` trong `dw_platform` (ADR-0110 (Accepted) quyết 3-4);
   mục `binding_set` do `dw_studio` đăng ký ở composition root: JSON Schema sinh từ khai báo của phiên
   bản niêm phong mới nhất của thành phần; bộ kiểm (kết nối cùng tenant, không thì 404; đúng trình kết
   nối và phiên bản chính, đủ `required_scopes`, `connection_usable` với `purpose` `tool` đúng với Người đề xuất theo
   connections-and-vault/04 (ADR-0115 (Accepted) quyết 2; W1 chỉ có kết nối cho công cụ), biến đúng kiểu, không thì
   422); quyền đề xuất `studio.bindings.propose`,
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
   `config.version.proposed`. `Idempotency-Key` gắn người gọi của app-standards/02 (app-standards:R2.1;
   ADR-0108 (Accepted) quyết 4).
5. Phê duyệt: `config.` vào `strict_approval_prefixes` bằng `|=` ở API
   (`apps/api/src/dw_api/bootstrap/runtime.py`) và worker (`apps/worker/src/dw_worker/main.py`); ticket này chỉ thêm
   đúng một dòng `|=` cho `config.` ở mỗi chỗ và không sửa dòng của ticket khác (agent-lifecycle/01 thêm
   `studio.lifecycle.` cũng ở đó), và test khẳng định tập tiền tố nghiêm ở cả hai chỗ chứa `config.`.
   `_enforce_strict_rules` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:115-125`) thêm
   `details.reason_code` `second_person_required` vào `ConflictError` nó ném khi người yêu cầu tự quyết, một lần cho
   mọi loại phê duyệt dưới tiền tố nghiêm (người tạo lượt chạy là người yêu cầu của Bước phê duyệt), không nhánh
   theo loại trong `decide`; `author_cannot_approve` vẫn là mã của guard tác giả dưới `studio.publish.`. Người đề
   xuất quyết yêu cầu `config.version` của mình → 409 `conflict` với `details.reason_code`
   `second_person_required` (ADR-0104 (Accepted) quyết 11). Port
   `ApprovalDecisionGuard` async và `ProposedDecision` từ dw-proterial (`dw_agent_runtime/approval_flow.py`)
   thay `DecisionGuard` đồng bộ, giữ guard `memory.review` (G4). Guard `ConfigVersionDecisions.check` trả
   409 `decision_stale` khi `base_version` không còn là phiên bản niêm phong mới nhất hay bản `approved`
   đang hiệu lực đã đổi, và, với quyết định duyệt, khi `connection_usable` với `purpose` `tool` trả false cho Người đề
   xuất ở workspace của đề xuất với một kết nối của đề xuất (hỏi lại lúc duyệt như lúc đề xuất ở bước 3;
   ADR-0110 (Accepted) quyết 7; ADR-0115 (Accepted) quyết 2; connections-and-vault:R5.9), trước khi quyết định được
   ghi; quyết định từ chối không hỏi lại kết nối.
6. Worker: handler outbox cho `config.version.decided` (tên từ `decided_event_type`), đăng ký trong
   `apps/worker/src/dw_worker/main.py`. `ConfigSettlement.settle` idempotent theo id yêu cầu phê duyệt:
   duyệt → `approved` và bản trước `superseded` trong một giao dịch, audit `config.version.approved` đứng tên
   người quyết (`decided_by`) với `details.lane` `outbox`, không qua `lane_audit_event`, vì lane thi hành quyết
   định đã ghi của một người (ADR-0011 (Accepted); `CLAUDE.md`, Agent and tool rules); từ chối → `rejected`,
   audit `config.version.rejected` đứng tên người quyết với `details.lane` `outbox`; dòng không còn `proposed`
   hay khóa đã có bản khác được duyệt → `rejected` với `details.reason` `settlement_conflict`, cùng người đứng
   tên; giao lại sau khi đã quyết toán → không đổi gì, không audit thứ hai.
7. Rút đề xuất: chỉ Người đề xuất (khác → 403); một giao dịch đặt `withdrawn`, gọi
   `ApprovalRequest.cancel()` trên yêu cầu liên kết, audit `config.version.withdrawn` (prefix nghiêm chặn
   đường tự từ chối, Quyết định của spec).
8. `BindingStatus.satisfied(version_id)` đáp ứng `PublishBindingsCheck` mà agent-lifecycle khai, nối ở composition
   root; lệnh gửi và handler `.decided` của agent-lifecycle gọi nó (agent-lifecycle:R2.11, agent-lifecycle:R5.10):
   mọi điểm gắn `required` của phiên bản có giá trị trong bản `approved` của thành phần và qua bộ kiểm; không thì
   trả `binding_unset` kèm tên điểm gắn (lệnh gửi trả 409, handler không đưa phiên bản lên `live`).
9. Nhận lượt chạy: `RunManifestBuilder` của ticket 04 thêm mục `bindings` vào bản kê: id phiên bản Bộ
   giá trị gắn, với mỗi kết nối id kết nối và không gì khác của bí mật: không `secret_version`, không giá trị (mô hình
   mục `bindings` có `extra="forbid"`), vì lời gọi egress phân giải phiên bản mới nhất chưa bị thu hồi của kết nối lúc
   gọi và ghi nó vào `platform.tool_executions.credential_version` cùng audit, việc của connections-and-vault (R7.4,
   R7.5; ADR-0109 (Accepted) quyết 6; ADR-0115 (Accepted) quyết 1; V4.35, H-10), với mỗi biến `content_hash` của giá
   trị (không ghi giá trị), với
   `principal` id của người chạy; thêm dòng `platform.run_manifest_keys` cho phiên bản cấu hình. Trước khi ghim,
   `connection_usable` với `purpose` `tool` cho người chạy sai (kể cả thiếu `connections.use` ở workspace của lượt
   chạy, ADR-0115 (Accepted) quyết 2) → từ chối nhận với `binding_degraded`, không node nào chạy. Bước này không từ
   chối lượt nào vì `binding_needs_review`: lượt được xin như mọi lượt, rồi ở lại `queued` tới khi Bộ giá trị gắn được
   duyệt lại, theo hàng của mã đó ở bảng từ chối của workflow-engine (workflow-engine:R5.19; ADR-0113 (Accepted) quyết
   3; workflow-triggers:R3.7; V4.16), với kiểm đọc `decided_at` của các Bộ giá trị gắn đã duyệt (bước 6), và lần giữ báo
   người giữ `studio.bindings.approve`, khóa duyệt của bước 3 (workflow-engine:R5.21); ticket này không giữ lượt nào và
   không gửi lời báo đó. Ticket này đáp ứng
   `RunBindingsPort` (connections-and-vault và handler của lượt chạy khai): đọc giá trị từ mục `bindings` của bản kê
   đã ghim, không từ Bộ giá trị gắn hiện hành; workflow-engine và agent-builder không cài port này.
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
- [ ] R7.2 (TC22): gọi `PublishBindingsCheck` cho phiên bản khai `zalo_oa` bắt buộc chưa có giá trị đã duyệt →
      `binding_unset` nêu `zalo_oa`; có giá trị đã duyệt → đạt; gỡ kiểm `required` → test đỏ.
- [ ] R7.3 (TC22): thu hồi kết nối đã gắn rồi nhận lượt chạy → từ chối `binding_degraded`, không dòng
      `platform.run_manifests` mới, không node nào chạy.
- [ ] R7.4 (TC15): bản kê có id phiên bản Bộ giá trị gắn, id kết nối và mã băm của biến; tìm token mẫu, giá trị biến
      dạng rõ và khóa `secret_version` trong `body` → không thấy; dựng mục `bindings` có `secret_version` → lỗi kiểm
      `extra="forbid"`, không dòng `platform.run_manifests`; nới `extra` → test đỏ.
- [ ] R7.4: dòng `platform.run_manifest_keys` của Bộ giá trị gắn đã ghim mang `config_version_id`, còn
      `artifact_version_id` là NULL; INSERT dòng có cả hai cột, hay không cột nào → CHECK từ chối; dòng thứ hai cùng
      `(manifest_hash, config_version_id)` → unique từ chối.
- [ ] R2.18 (TC29): bằng vai migrator, INSERT dòng `platform.run_manifest_keys` của tenant A có `config_version_id` là
      phiên bản cấu hình của tenant B → lỗi FK ghép; đổi FK ghép về FK một cột → test đỏ.
- [ ] R7.5 (TC15): duyệt Bộ giá trị gắn mới khi lượt chạy chờ duyệt; tiếp tục → lượt chạy dùng bộ đã
      ghim; xoay bí mật của kết nối đã ghim khi lượt chờ, rồi tiếp tục → bản kê không đổi và lượt không bị từ chối vì
      phiên bản, `RunBindingsPort` trả id kết nối đã ghim (phiên bản bí mật đã dùng do connections-and-vault ghi).
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
- [ ] R8.8 (TC16): Người đề xuất quyết yêu cầu của mình → 409 `conflict` với `details.reason_code`
      `second_person_required`; UPDATE `decided_by = proposed_by` → CHECK từ chối; bỏ `config.` khỏi prefix nghiêm
      ở API → test đỏ.
- [ ] R8.8 (TC16): người yêu cầu tự quyết một yêu cầu `memory.review` → 409 `conflict` với cùng `details.reason_code`
      `second_person_required`; bỏ mã khỏi `_enforce_strict_rules` → cả hai ca đỏ.
- [ ] R8.9 (TC20): niêm phong phiên bản đổi khai báo điểm gắn sau khi đề xuất, rồi quyết định → 409
      `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ.
- [ ] R8.9 (TC20): sau khi đề xuất, tắt kết nối của đề xuất, hay thu hồi `connections.use` của Người đề xuất ở
      workspace của đề xuất, rồi người thứ hai duyệt → 409 `decision_stale`, yêu cầu vẫn `pending`, không dòng nào
      đổi; người đó từ chối cùng đề xuất → được; bỏ lần hỏi lại `connection_usable` lúc duyệt → ca duyệt đỏ.
- [ ] R8.10 (TC17): duyệt → handler đặt `approved`, bản trước `superseded`, audit `config.version.approved` có
      actor là `decided_by` và `details.lane` `outbox`; ghi audit qua `lane_audit_event` (actor `system:outbox`) →
      test đỏ.
- [ ] R8.11 (TC17): từ chối → `rejected`, audit `config.version.rejected` có actor là `decided_by` và
      `details.lane` `outbox`; ghi actor `system:outbox` → test đỏ.
- [ ] R8.11 (TC20): quyết toán gặp khóa đã có bản khác được duyệt → `rejected` với `settlement_conflict`.
- [ ] R8.12 (TC17): UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; UPDATE
      `superseded` về `proposed` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; gỡ
      trigger → test đỏ.
- [ ] R8.13: Người đề xuất rút → `withdrawn`, yêu cầu phê duyệt `cancelled`, một audit
      `config.version.withdrawn`, trong một giao dịch.
- [ ] R8.14 (TC26): người khác rút → 403, đề xuất và yêu cầu không đổi; bỏ so `proposed_by` → test đỏ.
- [ ] R8.15 (TC17): outbox giao lại sự kiện đã quyết toán → không dòng nào đổi, không audit thứ hai.
- [ ] R8.16 (TC29): bằng vai migrator, INSERT `platform.config_versions` của tenant A có `approval_id` là yêu cầu phê
      duyệt của tenant B, rồi của một workspace khác cùng tenant A → lỗi FK ghép; đổi FK ghép về FK một cột tới
      `platform.approval_requests (id)` → test đỏ.
- [ ] G4: `test_the_api_decides_memory_reviews_strictly_and_only_with_clearance` vẫn xanh sau khi đổi sang
      guard async.
- [ ] R3.6 (TC21): purge tenant có phiên bản cấu hình riêng được bản kê ghim và yêu cầu phê duyệt của nó
      → xong, tenant khác nguyên; thứ tự suy ra đặt `platform.config_versions` sau `platform.run_manifest_keys` và trước
      `platform.approval_requests`; đột biến phép suy để bỏ cạnh `approval_id` → test phủ offboarding
      (studio-skeleton:R4.2) đỏ, nêu khóa ngoại đó; thu DELETE của `dw_app` trên `platform.config_versions` → test phủ
      offboarding (studio-skeleton:R4.3) đỏ, nêu tên bảng.
- [ ] R3.8 (TC31): `dw_app` DELETE một dòng `platform.config_versions` của công ty `active` → 23514, dòng và yêu cầu
      phê duyệt của nó còn; cùng lệnh khi công ty ở `offboarding` → xóa được; gỡ trigger khỏi bảng → test đỏ.
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
  quyết 1-2, 6-8; ADR-0115 (Accepted) quyết 1-2 (R7.4, `purpose`).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`; spec: R3.6, R3.8, TC21,
  TC31.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 08 và 09. Chờ DO-06 (Đạt). Tên khóa quyền và cách rút đề
  xuất là quyết định tạm của spec. Outbox `config.version.approved` ra cùng bên đọc của nó (lệch cấu
  hình, W2).
- 2026-10-23 (agent): DO-06 đã có lời đáp (Đạt 23/10/2026, tài liệu giữ tên điểm gắn), nên ticket về
  `needs-triage`. Theo phiếu cùng ngày: chờ runtime-hardening/03 (OPS-b) và tenant-rbac/02 (hàm tìm
  người duyệt chung); `principal` nhận cả người dự phòng của bước giao (Q6); ticket này đáp ứng
  `RunBindingsPort` và `ConnectionDependentsPort`.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: audit quyết toán đứng tên `decided_by` với
  `details.lane` `outbox` (R8.10, R8.11); người đề xuất tự quyết nhận 409 `conflict` `second_person_required`
  (R8.8); bộ kiểu Điểm gắn có thêm kiểm lúc nhận lượt chạy cho `binding_needs_review` của workflow-triggers/03;
  `binding_set` ở W1 không có nhánh chỉ siết (ADR-0110 (Accepted) quyết 2). Theo cách sửa thứ hai của
  C:agent-lifecycle:R7.10~tenant-config:R8.8, như agent-lifecycle/01, ticket này chỉ thêm dòng `|=` của `config.`,
  không thêm cạnh Blocked by.
- 2026-10-24 (agent): vòng sửa thứ tư, theo Quyết định cùng ngày của spec: `BindingStatus` đáp ứng
  `PublishBindingsCheck` mà lệnh gửi và handler `.decided` của agent-lifecycle gọi (R7.2); `second_person_required`
  đặt một lần ở `_enforce_strict_rules` cho mọi loại dưới tiền tố nghiêm (R8.8, TC16; quyết định tạm của spec); câu
  INSERT khóa quyền nêu mọi cột NOT NULL, gồm `tenant_grantable` (quyết định tạm của spec); chờ
  foundations-hardening/07, vì cùng sửa `offboarding.py` và `test_offboarding.py`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: chờ app-standards/02, vì route đề xuất dùng `Idempotency-Key` gắn
  người gọi (quyết định tạm cùng ngày của spec).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các quyết định tạm cùng ngày của spec:
  `uq_config_versions_tenant_id_id` và `config_version_id` là FK ghép, kèm CHECK `num_nonnulls`, unique của cột mới và
  bỏ NOT NULL của `artifact_version_id` trong cùng bước (R2.18, TC29); FK tới yêu cầu phê duyệt có index; bản kê ghim
  một `secret_version` cho mỗi (kết nối, trường) (R7.4); `connection_usable` gọi với `purpose` `tool`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo quyết định tạm cùng ngày của spec: guard quyết định hỏi lại
  `connection_usable` lúc duyệt cho mọi kết nối của đề xuất, false → 409 `decision_stale` và yêu cầu giữ `pending`
  (R8.9, TC20; ADR-0110 (Accepted) quyết 7; connections-and-vault:R5.9), nên `connection_usable` có ba chỗ gọi: lúc
  đề xuất, lúc duyệt và lúc nhận lượt chạy; FK ghép tới yêu cầu phê duyệt có ca âm chéo tenant (R8.16, TC29).
- 2026-10-24 (agent): vòng sửa thứ tư, theo quyết định tạm cùng ngày của spec về quyền xóa của lane `offboarding`:
  `dw_app` có DELETE trên `platform.config_versions`, chỉ dùng được ở lượt xóa của offboarding nhờ trigger của ticket 02
  (R3.8, TC31), vì không có DELETE thì `purge_rows` bỏ qua mục `_ORDERED_FIRST` của bảng và lần xóa
  `platform.approval_requests` hỏng ở FK RESTRICT; mục đó đứng sau `platform.run_manifest_keys` của ticket 04.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo quyết định V4.16 của Đạt cùng ngày: bước 9 không còn từ chối lượt
  gặp `binding_needs_review`; lượt ở lại `queued` theo hàng của mã đó ở bảng từ chối của workflow-engine
  (workflow-engine:R5.19) tới khi Bộ giá trị gắn được duyệt lại, và người nhận báo của lần giữ là người giữ
  `studio.bindings.approve` (workflow-engine:R5.21). Kiểm đó rời bộ kiểu Điểm gắn sang `BindingReviewPort` ở dispatch
  (workflow-triggers:R3.7), nên bước 1 bỏ chỗ cho kiểm lúc nhận lượt chạy theo kind, chỗ không còn kind nào của W1
  đăng ký (failure-modes #1). Không thêm cạnh Blocked by.
- 2026-10-25 (agent): lượt h, theo V4.35 của Đạt (quyết định cùng ngày của spec): bước 9 thôi ghim `secret_version` và
  thôi đọc `platform.secret_status`; mục `bindings` mang id kết nối, lời gọi dùng phiên bản bí mật mới nhất chưa bị thu
  hồi lúc gọi và connections-and-vault ghi `credential_version`; tiêu chí R7.4 và R7.5 viết lại; câu Comments ngày
  24/10/2026 "bản kê ghim một `secret_version` cho mỗi (kết nối, trường)" không còn áp. Theo H-2, `platform.config_versions`
  dùng bước mặc định của sổ bước xóa của foundations-hardening/07, thứ tự suy từ `pg_constraint`, thay mục `_ORDERED_FIRST`.
  Dòng Blocked by không đổi.
