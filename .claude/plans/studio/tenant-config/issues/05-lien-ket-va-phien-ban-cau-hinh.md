# 05 — Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau

Status: resolved (2026-11-05, main)
Blocked by: 04, .claude/plans/studio/connections-and-vault/issues/04-ket-noi-dung-chung-theo-workspace.md, .claude/plans/studio/runtime-hardening/issues/03-run-va-outbox-khong-ket.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, R8.12, R8.13, R8.14, R8.15, R8.16, R8.17, R8.18, R8.19, R2.18, R3.6, R3.7, R3.8, G4, TC15, TC16, TC17, TC18, TC19, TC20, TC21, TC22, TC23, TC25, TC26, TC29, TC31, TC33, TC34

## Mục tiêu

Tài liệu chỉ nêu tên điểm gắn; giá trị (kết nối, biến, người chạy) là một Bộ giá trị gắn, tức phiên bản
cấu hình riêng loại `binding_set`, do một người đề xuất và một người khác duyệt trên yêu cầu phê duyệt
không lượt chạy của nền tảng. Lệnh gửi và phát hành từ chối khi thiếu giá trị bắt buộc, nhận lượt chạy từ chối khi
kết nối hỏng, và mỗi lượt chạy ghim giá trị nó dùng, không ghim phiên bản bí mật của kết nối, vì lời gọi dùng phiên
bản mới nhất chưa bị thu hồi lúc gọi (spec R7, R8; D11; V4.35). Pilot Marketing cần điểm gắn
`zalo_oa`, `email_sender` và `score_threshold` theo đúng đường này.

## Việc cần làm

1. Lược đồ `bindings[]` dùng chung trong lõi `dw_studio`: mỗi mục `{name, kind, required, description}`,
   `name` khớp `^[a-z][a-z0-9_]{0,62}$` và không trùng trong tài liệu; `required` bắt buộc nêu, không mặc định; `kind` ở
   W1 là `connection` (`connector_key`, phiên bản chính, `required_scopes` phải rỗng ở W1 vì Kết nối của P1 không có
   phạm vi, `scopes` là của OAuth W2: khác rỗng → niêm phong trả 422 `binding_scopes_unsupported`), `variable` (kiểu,
   ràng buộc trong hồ sơ `dw.tool-schema/v1`, không `pattern`, `$ref` hay `format` ngoài bộ kiểm đóng của nền tảng,
   ADR-0116 (Accepted) quyết 3; `default` mã hóa thành chuỗi, một biến `required` có `default` coi như đã có giá trị) và
   `principal` (một chủ thể của tenant: tài khoản dịch vụ khi điểm gắn là danh tính chạy,
   ADR-0103 (Accepted) và workflow-triggers:R3.1; thành viên khi điểm gắn là người dự phòng của bước giao,
   workflow-nodes:R6.3); `secret`, `webhook_endpoint`, `schedule` vào cùng bên đọc của chúng
   (ADR-0110 (Accepted) quyết 6). Bộ kiểu Điểm gắn này là chỗ duy nhất các spec khác đăng ký kiểm riêng
   của một kind, không phải `ConfigKindRegistry`: mỗi kind có một kiểm lúc đề xuất (như `grants_cover` của
   workflow-triggers/01), và một kind không có kiểm đã đăng ký bị từ chối lúc đăng ký, không bao giờ nhận mọi giá trị
   đúng kiểu (failure-modes #7). Ticket này đăng ký kiểm của `principal`: id là một thành viên `active` hay một service
   principal còn hoạt động của chính công ty (công ty khác hay không có → 404, không `active` → 422
   `principal_inactive`), cộng kiểm riêng của điểm gắn danh tính chạy mà workflow-triggers/01 đăng ký (gate 4/11/2026
   (h)). Không kind nào ở W1 có kiểm lúc nhận lượt chạy riêng, nên bộ kiểu không có chỗ cho kiểm đó
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
   `decided_at`, `decision_comment`, `superseded_at`, và DELETE chỉ ở lượt xóa của offboarding (spec R3.8);
   `base_bindings_hash text NOT NULL`, mã băm JCS (`dw_kernel.canonical`) của khai báo điểm gắn (bước 3) của Phiên bản
   gốc, và `base_approved_id uuid` NULL, id của bản `approved` đang hiệu lực lúc đề xuất (không FK: bản ghi lịch sử), mà
   guard của bước 5 và quyết toán của bước 6 so (gate 4/11/2026 (d), (q)). Thêm:
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
   mục `binding_set` do `dw_studio` đăng ký ở composition root: JSON Schema sinh từ khai báo của thành phần: hợp của
   mọi điểm gắn mà bao đóng của phiên bản niêm phong mới nhất khai (dòng
   `studio.dependencies` `to_kind` `binding` của gốc và của mọi mục trong bao đóng, một Bộ giá trị gắn mỗi thành phần gốc;
   hai mục khai cùng tên khác kind → niêm phong gốc trả 422 `binding_conflict`), cộng các điểm gắn mà bản `live` khai nếu
   khác, để một Bộ duyệt theo Bản ứng viên vẫn giữ giá trị bản `live` cần; `required` theo phiên bản niêm phong mới nhất
   (gate 4/11/2026 (n), (o)); "phiên bản niêm phong mới nhất" là phiên bản có `version_no` lớn nhất không ở `draft`,
   nên một phiên bản bị rút hay bị trả về Nháp không còn là nó; bộ kiểm (kết nối cùng tenant, không thì 404; đúng trình kết
   nối và phiên bản chính, đủ `required_scopes`, `connection_usable` với `purpose` `tool` đúng với Người đề xuất theo
   connections-and-vault/04 (ADR-0115 (Accepted) quyết 2; W1 chỉ có kết nối cho công cụ), biến đúng kiểu, không thì
   422); quyền đề xuất `studio.bindings.propose`,
   quyền duyệt `studio.bindings.approve`; test bên đọc: bộ dựng bản kê đọc bản `approved`. Loại không
   đăng ký → 422.
4. `ConfigVersionService.propose`, một giao dịch, neo ở workspace sở hữu của thành phần (`owning_workspace_id`), không
   ở workspace đang làm việc (spec R8.17; gate 4/11/2026 (b)): người gọi không giữ khóa đọc của loại với tới workspace sở
   hữu theo `platform.workspace_reach` → 404; giữ nó mà không giữ `studio.bindings.propose` với tới workspace đó → 403;
   `checker_candidates`, `connection_usable` (`call_site` `binding_review`, `workspace_id` là workspace sở hữu) và yêu
   cầu phê duyệt đều ở workspace sở hữu; ứng viên người duyệt là giao của `platform.checker_candidates(...,
'studio.bindings.approve', ...)` với người giữ khóa đọc của loại với tới workspace sở hữu, vì người không đọc được
   thành phần bị guard từ chối (gate 4/11/2026 (r)); thành phần chưa có phiên bản niêm phong nào → 409 `no_sealed_version`;
   vi phạm partial unique "một `proposed` mỗi khóa" của hai đề xuất đồng thời → 409 `proposal_open` theo tên ràng
   buộc, không 500. Rồi:
   kiểm giá trị (404, 422); một đề xuất mở mỗi khóa (409 `proposal_open`); hàm SQL chung
   `platform.checker_candidates(tenant, 'studio.bindings.approve', người đề xuất, workspace của đề xuất)` của
   tenant-rbac/02 trên `platform.effective_grants` (cùng hàm `no_checker_available` của tenant-rbac:R7.3 dùng)
   trả rỗng → 409 `no_checker_available`; ghi phiên bản `proposed` với
   `base_version` là `version_no` của phiên bản niêm phong mới nhất đã dùng để kiểm, `base_bindings_hash` của nó; tạo
   yêu cầu phê duyệt không lượt chạy `config.version` ở workspace sở hữu, `required_scope` là quyền duyệt
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
   thay `DecisionGuard` đồng bộ, giữ guard `memory.review` (G4). Guard `ConfigVersionDecisions.check` trả 404 khi người
   quyết không giữ khóa đọc của loại với tới workspace sở hữu (người duyệt phải thấy được thứ mình duyệt,
   ADR-0004 (Accepted)), và 409 `decision_stale` khi mã băm `bindings[]` của phiên bản niêm phong mới nhất khác
   `base_bindings_hash` (một phiên bản niêm phong mới không đổi điểm gắn không làm đề xuất cũ), hay Phiên bản gốc không
   còn niêm phong (rút về Nháp), hay bản `approved` đang hiệu lực khác `base_approved_id`, và, với quyết định duyệt, khi `connection_usable` với `purpose` `tool` trả false cho Người đề
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
   tên; dòng đã rời `proposed` bằng đường khác (rút) → không đổi gì, không audit, chỉ log, vì trigger chỉ cho
   `proposed` sang `rejected`; giao lại sau khi đã quyết toán → không đổi gì, không audit thứ hai.
7. Rút đề xuất: chỉ Người đề xuất (khác → 403); một giao dịch khóa yêu cầu liên kết `FOR UPDATE`, chỉ rút khi yêu cầu
   còn `pending` (đã quyết mà chưa quyết toán → 409 `proposal_decided`, không đổi gì; spec R8.18; gate 4/11/2026 (f)),
   đặt `withdrawn`, gọi `ApprovalRequest.cancel()` trên yêu cầu liên kết, audit `config.version.withdrawn` (prefix nghiêm chặn
   đường tự từ chối, Quyết định của spec).
8. `BindingStatus.satisfied(version_id)` đáp ứng `PublishBindingsCheck` mà agent-lifecycle khai, nối ở composition
   root; lệnh gửi và handler `.decided` của agent-lifecycle gọi nó (agent-lifecycle:R2.11, agent-lifecycle:R5.10):
   mọi điểm gắn `required` của phiên bản có giá trị trong bản `approved` của thành phần (hay `default`) và giá trị qua
   bộ kiểu theo khai báo của chính phiên bản đó; kết nối qua `connection_usable` (`call_site` `binding_review`) cho
   `proposed_by` của bản `approved` ở workspace sở hữu, kể cả khi handler phát hành chạy ở lane outbox không có người
   gọi; không thì trả `binding_unset` kèm tên điểm gắn. Lệnh gửi có phê duyệt không từ chối vì nó (nhánh chỉ siết, phát
   hành ngay trong giao dịch gửi, vẫn trả 409): trả câu trả lời thành công kèm
   danh sách `binding_unset` để người dựng đề xuất theo phiên bản vừa niêm phong, vì Bộ giá trị gắn chỉ kiểm được theo
   khai báo đã niêm phong; handler phát hành từ chối, phiên bản về Nháp (spec R7.2; agent-lifecycle:R2.11, R5.10 sửa
   cùng gate; gate 4/11/2026 (a)).
9. Nhận lượt chạy: `RunManifestBuilder` của ticket 04 thêm mục `bindings` vào bản kê: id phiên bản Bộ
   giá trị gắn, với mỗi kết nối id kết nối và không gì khác của bí mật: không `secret_version`, không giá trị (mô hình
   mục `bindings` có `extra="forbid"`), vì lời gọi egress phân giải phiên bản mới nhất chưa bị thu hồi của kết nối lúc
   gọi và ghi nó vào `platform.tool_executions.credential_version` cùng audit, việc của connections-and-vault (R7.4,
   R7.5; ADR-0109 (Accepted) quyết 6; ADR-0115 (Accepted) quyết 1; V4.35, H-10), với mỗi biến `content_hash` của giá
   trị (không ghi giá trị), với
   mỗi điểm gắn `principal` id đã duyệt; thêm dòng `platform.run_manifest_keys` cho phiên bản cấu hình. Trước khi ghim,
   kiểm Bộ giá trị gắn đã duyệt theo khai báo của phiên bản gốc của lượt (điểm gắn `required` thiếu giá trị hay giá trị sai
   kiểu → từ chối `binding_unset`, không bản kê, không node nào chạy; spec R7.6; gate 4/11/2026 (g)), vì Bộ giá trị gắn
   được kiểm theo phiên bản niêm phong mới nhất, có thể là Bản ứng viên chứ không phải bản `live`. Lượt `simulate` không
   từ chối vì `binding_unset` hay `binding_degraded` (executor giả lập mọi lời gọi không `simulate_safe`,
   ADR-0111 (Accepted)), và ghim các giá trị đã duyệt đang có (gate 4/11/2026 (s)). Trước khi ghim,
   `connection_usable` với `purpose` `tool` cho người chạy sai (kể cả thiếu `connections.use` ở workspace của lượt
   chạy, ADR-0115 (Accepted) quyết 2) → từ chối nhận với `binding_degraded`, không node nào chạy. Bước này không từ
   chối lượt nào vì `binding_needs_review`: lượt được xin như mọi lượt, rồi ở lại `queued` tới khi Bộ giá trị gắn được
   duyệt lại, theo hàng của mã đó ở bảng từ chối của workflow-engine (workflow-engine:R5.19; ADR-0113 (Accepted) quyết
   3; workflow-triggers:R3.7; V4.16), với kiểm đọc `decided_at` của các Bộ giá trị gắn đã duyệt (bước 6), và lần giữ báo
   người giữ `studio.bindings.approve`, khóa duyệt của bước 3 (workflow-engine:R5.21); ticket này không giữ lượt nào và
   không gửi lời báo đó. Ticket này khai `RunBindingsPort` ở `dw_agent_runtime.ports` cạnh `RunManifestPort` và đáp ứng
   nó trong `dw_studio`: `connection(tenant_id, run_id, binding_name) -> BoundConnection | None`, `BoundConnection(
connection_id, workspace_id, principal_id, run_requested_at)`, đọc dòng `platform.worker_runs` của lượt (workspace,
   `created_at`, `run_manifest_hash`, `run_as_principal_id`, `requested_by`) và mục `bindings` của bản kê đã ghim dưới
   RLS của công ty, không từ Bộ giá trị gắn hiện hành; `principal_id` là `coalesce(run_as_principal_id, requested_by)`
   của dòng lượt chạy, chủ thể mà lượt hành động thay (ADR-0103 (Accepted)), vì `dw.run_manifest/v1` của ticket 04 không
   có trường `principal` và ticket này không thêm (gate 4/11/2026 (m)); tên tra trong mục `bindings` của chính bản kê
   của lượt (lượt con có bản kê riêng); bên dùng là `ManifestActionHandler` của connections-and-vault/05, nơi gắn port ở
   worker (gate 4/11/2026 (i)); workflow-engine và agent-builder không cài port này.
10. Route: `GET /api/v1/studio/artifacts/{id}/bindings` (khóa đọc của loại với tới workspace sở hữu, ngoài tầm → 404;
    khai báo, giá trị hiện hành và giá trị của đề xuất mở, với kết nối người gọi không đọc được thì chỉ id và
    `connection_hidden: true`, trạng thái từng điểm gắn là `unset`, `set` hay `default` cùng `proposal_open`, không kiểm
    `connection_usable` theo người gọi; gate 4/11/2026 (e), (t)), `POST /api/v1/studio/artifacts/{id}/bindings/proposals`,
    `POST /api/v1/studio/artifacts/{id}/bindings/proposals/{config_version_id}/withdraw`. Mọi id là UUID.
    `make generate-contracts`.
11. `ConnectionDependentsPort` (connections-and-vault khai) do ticket này đáp ứng ở composition root: một
    Kết nối đang được dùng khi một Bộ giá trị gắn `approved` của một thành phần chưa xóa mềm có giá trị là Kết nối đó;
    `studio.dependencies` không là nguồn, vì R7.1 cấm id kết nối trong tài liệu nên không dòng nào trỏ tới một Kết nối
    (spec R3.7 sửa cùng gate; gate 4/11/2026 (c)); trả số đếm và tên theo quyền người gọi như R3.4.

## Tiêu chí chấp nhận

- [x] R7.1 (TC23): niêm phong tài liệu `fixture` có id của một kết nối của tenant ở một trường tự do → 422,
      mỗi chỗ một con trỏ; gỡ bước quét → test đỏ.
- [x] R7.2 (TC22): gọi `PublishBindingsCheck` cho phiên bản khai `zalo_oa` bắt buộc chưa có giá trị đã duyệt →
      `binding_unset` nêu `zalo_oa`; có giá trị đã duyệt → đạt; biến `required` có `default` mà chưa có giá trị → đạt; gỡ
      kiểm `required` → test đỏ.
- [ ] R7.2 (TC22): thành phần mới, bản Nháp khai `email_sender` bắt buộc: lệnh gửi thành công kèm `binding_unset`
      `email_sender`; đề xuất theo phiên bản vừa niêm phong → duyệt → phát hành đạt; trước lần gửi đầu, đề xuất → 409
      `no_sealed_version`.
- [x] R7.6 (TC33): Bộ giá trị gắn được duyệt theo Bản ứng viên v2 thiếu điểm gắn bắt buộc `zalo_oa` mà bản `live` v1 khai
      → nhận lượt chạy của v1 trả `binding_unset`, không bản kê, không node nào chạy; gỡ lần kiểm lúc nhận → lượt chạy,
      test đỏ.
- [x] R8.17 (TC34): người giữ `studio.bindings.propose` và khóa đọc chỉ ở ws2 đề xuất cho thành phần của ws1 → 404; giữ
      khóa đọc với tới ws1 mà `studio.bindings.propose` chỉ ở ws2 → 403; người duyệt chỉ giữ `studio.bindings.approve`
      ở ws2 quyết yêu cầu của thành phần ws1 → 404; yêu cầu nằm ở workspace sở hữu; gỡ neo workspace sở hữu → đề xuất
      chéo workspace thành công, test đỏ.
- [x] R8.18 (TC34): người thứ hai duyệt, outbox chưa quyết toán, Người đề xuất rút → 409 `proposal_decided`, dòng vẫn
      `proposed`; quyết toán sau đó → `approved`.
- [x] R8.19 (TC34): một dòng đã `withdrawn` nhận sự kiện duyệt → không đổi, không audit; gỡ phép bỏ qua → trigger từ
      chối và sự kiện hỏng ở mỗi lần giao lại, test đỏ.
- [x] R8.4 (TC25): đề xuất `principal` là thành viên của tenant khác → 404; thành viên không `active` → 422
      `principal_inactive`; khai báo `connection` với `required_scopes` khác rỗng → niêm phong 422
      `binding_scopes_unsupported`; đăng ký một kind không có kiểm lúc đề xuất → lỗi lúc khởi động.
- [x] R8.9 (TC20): niêm phong v3 không đổi `bindings[]` sau khi đề xuất theo v2 → duyệt được; v3 đổi `bindings[]` → 409
      `decision_stale`; người duyệt không giữ khóa đọc của loại với tới workspace sở hữu → 404.
- [x] R7.6 (TC33): quy trình gốc khai `email_sender`, agent trong bao đóng khai `zalo_oa` → schema của đề xuất có cả
      hai; hai mục khai `email_sender` khác kind → niêm phong 422 `binding_conflict`; Bộ duyệt theo Bản ứng viên v2 vẫn
      nhận giá trị `zalo_oa` mà chỉ bản `live` v1 khai; lượt `simulate` của bản Nháp thiếu giá trị bắt buộc → được nhận.
- [x] R8.11 (TC20): bản `approved` đổi sau khi đề xuất (một đề xuất khác được duyệt và quyết toán) → quyết định đề xuất cũ
      trả 409 `decision_stale`; lần quyết toán thứ hai của một chuỗi đề xuất nối tiếp bình thường → `approved`, bản trước
      `superseded`, không `settlement_conflict`; Phiên bản gốc bị rút về Nháp → `decision_stale`.
- [x] R8.6 (TC18): hai đề xuất cùng khóa gửi đồng thời (hai giao dịch, đợi `pg_locks`) → một 201, một 409
      `proposal_open`, không 500.
- [x] R7.3 (TC22): thu hồi kết nối đã gắn rồi nhận lượt chạy → từ chối `binding_degraded`, không dòng
      `platform.run_manifests` mới, không node nào chạy.
- [x] R7.4 (TC15): bản kê có id phiên bản Bộ giá trị gắn, id kết nối và mã băm của biến; tìm token mẫu, giá trị biến
      dạng rõ và khóa `secret_version` trong `body` → không thấy; dựng mục `bindings` có `secret_version` → lỗi kiểm
      `extra="forbid"`, không dòng `platform.run_manifests`; nới `extra` → test đỏ.
- [x] R7.4: dòng `platform.run_manifest_keys` của Bộ giá trị gắn đã ghim mang `config_version_id`, còn
      `artifact_version_id` là NULL; INSERT dòng có cả hai cột, hay không cột nào → CHECK từ chối; dòng thứ hai cùng
      `(manifest_hash, config_version_id)` → unique từ chối.
- [x] R2.18 (TC29): bằng vai migrator, INSERT dòng `platform.run_manifest_keys` của tenant A có `config_version_id` là
      phiên bản cấu hình của tenant B → lỗi FK ghép; đổi FK ghép về FK một cột → test đỏ.
- [x] R7.5 (TC15): duyệt Bộ giá trị gắn mới khi lượt chạy chờ duyệt; tiếp tục → lượt chạy dùng bộ đã
      ghim; xoay bí mật của kết nối đã ghim khi lượt chờ, rồi tiếp tục → bản kê không đổi và lượt không bị từ chối vì
      phiên bản, `RunBindingsPort` trả id kết nối đã ghim (phiên bản bí mật đã dùng do connections-and-vault ghi).
- [x] R8.1: đề xuất hợp lệ ghi một phiên bản `proposed`, một yêu cầu `config.version` có `required_scope`
      `studio.bindings.approve` và một audit `config.version.proposed`, trong một giao dịch.
- [x] R8.2 (TC25): người thiếu `studio.bindings.propose` → 403, không dòng nào.
- [x] R8.3 (TC19): thành phần hay kết nối của tenant khác → 404, không dòng nào.
- [x] R8.4 (TC25): kết nối sai trình kết nối, thiếu quyền khai báo, hay `connection_usable` sai với Người
      đề xuất → 422, không dòng nào.
- [x] R8.5 (TC18): workspace chỉ Người đề xuất giữ `studio.bindings.approve` → 409
      `no_checker_available`, không dòng nào.
- [x] R8.6 (TC18): đề xuất thứ hai cùng khóa khi đề xuất đầu còn mở → 409 `proposal_open`.
- [x] R8.7 (TC19): đề xuất loại `prompt` → 422; INSERT thẳng `kind = 'prompt'` → CHECK từ chối.
- [x] R8.8 (TC16): Người đề xuất quyết yêu cầu của mình → 409 `conflict` với `details.reason_code`
      `second_person_required`; UPDATE `decided_by = proposed_by` → CHECK từ chối; bỏ `config.` khỏi prefix nghiêm
      ở API → test đỏ.
- [x] R8.8 (TC16): người yêu cầu tự quyết một yêu cầu `memory.review` → 409 `conflict` với cùng `details.reason_code`
      `second_person_required`; bỏ mã khỏi `_enforce_strict_rules` → cả hai ca đỏ.
- [x] R8.9 (TC20): niêm phong phiên bản đổi khai báo điểm gắn sau khi đề xuất, rồi quyết định → 409
      `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ.
- [x] R8.9 (TC20): sau khi đề xuất, tắt kết nối của đề xuất, hay thu hồi `connections.use` của Người đề xuất ở
      workspace của đề xuất, rồi người thứ hai duyệt → 409 `decision_stale`, yêu cầu vẫn `pending`, không dòng nào
      đổi; người đó từ chối cùng đề xuất → được; bỏ lần hỏi lại `connection_usable` lúc duyệt → ca duyệt đỏ.
- [x] R8.10 (TC17): duyệt → handler đặt `approved`, bản trước `superseded`, audit `config.version.approved` có
      actor là `decided_by` và `details.lane` `outbox`; ghi audit qua `lane_audit_event` (actor `system:outbox`) →
      test đỏ.
- [x] R8.11 (TC17): từ chối → `rejected`, audit `config.version.rejected` có actor là `decided_by` và
      `details.lane` `outbox`; ghi actor `system:outbox` → test đỏ.
- [x] R8.11 (TC20): quyết toán gặp khóa đã có bản khác được duyệt → `rejected` với `settlement_conflict`.
- [x] R8.12 (TC17): UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; UPDATE
      `superseded` về `proposed` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; gỡ
      trigger → test đỏ.
- [x] R8.13: Người đề xuất rút → `withdrawn`, yêu cầu phê duyệt `cancelled`, một audit
      `config.version.withdrawn`, trong một giao dịch.
- [x] R8.14 (TC26): người khác rút → 403, đề xuất và yêu cầu không đổi; bỏ so `proposed_by` → test đỏ.
- [x] R8.15 (TC17): outbox giao lại sự kiện đã quyết toán → không dòng nào đổi, không audit thứ hai.
- [x] R8.16 (TC29): bằng vai migrator, INSERT `platform.config_versions` của tenant A có `approval_id` là yêu cầu phê
      duyệt của tenant B, rồi của một workspace khác cùng tenant A → lỗi FK ghép; đổi FK ghép về FK một cột tới
      `platform.approval_requests (id)` → test đỏ.
- [x] G4: `test_the_api_decides_memory_reviews_strictly_and_only_with_clearance` vẫn xanh sau khi đổi sang
      guard async.
- [x] R3.6 (TC21): purge tenant có phiên bản cấu hình riêng được bản kê ghim và yêu cầu phê duyệt của nó
      → xong, tenant khác nguyên; thứ tự suy ra đặt `platform.config_versions` sau `platform.run_manifest_keys` và trước
      `platform.approval_requests`; đột biến phép suy để bỏ cạnh `approval_id` → test phủ offboarding
      (studio-skeleton:R4.2) đỏ, nêu khóa ngoại đó; thu DELETE của `dw_app` trên `platform.config_versions` → test phủ
      offboarding (studio-skeleton:R4.3) đỏ, nêu tên bảng.
- [x] R3.8 (TC31): `dw_app` DELETE một dòng `platform.config_versions` của công ty `active` → 23514, dòng và yêu cầu
      phê duyệt của nó còn; cùng lệnh khi công ty ở `offboarding` → xóa được; gỡ trigger khỏi bảng → test đỏ.
- [x] R3.7: Kết nối là giá trị của một Bộ giá trị gắn `approved` → `ConnectionDependentsPort` báo đang
      dùng; bản đó sang `superseded` bởi bản không dùng Kết nối → báo không dùng; thành phần của bản `approved` bị xóa mềm
      → báo không dùng; bỏ đọc `platform.config_versions` → ca đầu đỏ.
- [x] R7.5: `RunBindingsPort.connection` trả `BoundConnection` có `run_requested_at` bằng `created_at` của dòng lượt chạy
      và `principal_id` bằng `run_as_principal_id` khi có, `requested_by` khi không; công ty B hỏi `run_id` của A → None; tên không có trong `bindings`
      của bản kê → None.
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
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, ba
  subagent, vì ticket thêm migration và route) trên `0baced0`, đọc cùng mã của ticket 04 (`ece5697`, `f32a007`):
  `check_plans.py` 24 Đạt; 0 CRITICAL, 12 HIGH, sửa theo khuyến nghị; mỗi quyết định cùng `Nếu sai thì:` ở mục Quyết
  định của spec, dòng 4/11/2026 (a)-(l): vòng khóa chết ở phiên bản đầu (lệnh gửi đòi giá trị đã duyệt, đề xuất kiểm
  theo phiên bản niêm phong); neo đề xuất, người duyệt và `connection_usable` ở workspace sở hữu; nguồn thứ hai của
  `ConnectionDependentsPort` không bao giờ khớp; `decision_stale` theo mã băm `bindings[]`; người duyệt phải đọc được
  thành phần; rút đua với duyệt; kiểm lại lúc nhận lượt theo phiên bản gốc; kiểm của kind `principal`, kind không kiểm bị
  từ chối; ai khai `RunBindingsPort` và hình của nó; `required_scopes` không có bên đọc ở W1; biến có `default`; ràng
  buộc biến trong hồ sơ đóng. agent-lifecycle:R2.11 sửa cùng gate (commit riêng). Lượt xác nhận chạy sau, ghi ở dòng kế.
- 2026-11-04 (agent): MEDIUM, chưa sửa: (M1) yêu cầu `config.version` hết hạn hay bị hủy bằng đường khác `withdraw` để
  dòng ở `proposed` và chặn khóa bằng `proposal_open`: luật hết hạn chung của ADR-0110 (Accepted) và ADR-0104 (Accepted)
  quyết 10 là W2, tới đó Người đề xuất rút được, người quản trị rút thay là W2; (M2) phát lại `Idempotency-Key` của đề
  xuất theo app-standards/02, không tiêu chí riêng ở đây; (M3) bước quét của R7.1 chỉ bắt chuỗi trùng nguyên văn id
  (chữ thường): id viết hoa hay nằm trong chuỗi dài hơn lọt; đủ cho R7.1 vì giá trị gắn không đến từ tài liệu; (M4)
  trigger `platform.match_run_manifest()` đọc bản kê dưới RLS của bên gọi (ticket 04, MEDIUM để lại): mọi chỗ ghi lượt
  của ticket này đặt `app.tenant_id` của lượt; (M5) worker chưa phụ thuộc `dw-studio` (ticket 04 (7)): connections-and-
  vault/05 bước 10 thêm khi gắn `RunBindingsPort` ở worker; (M6) dòng `Xong:` đọc theo `.claude/rules/wave-close.md`,
  cộng `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding_coverage.py` vì có migration.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 0 CRITICAL, 7 HIGH,
  sửa: (m) `dw.run_manifest/v1` của ticket 04 không có `principal` (`dw_studio/core/domain/run_manifest.py`): chủ thể là
  `coalesce(run_as_principal_id, requested_by)` của dòng lượt chạy, không thêm trường vào bản kê; (n) điểm gắn của mục
  trong bao đóng: một Bộ mỗi gốc phủ hợp các khai báo, trùng tên khác kind bị niêm phong từ chối; (o) khóa bản `live` khai
  mà Bản ứng viên không khai vẫn nhận; (p) "niêm phong mới nhất" không gồm phiên bản ở Nháp, Phiên bản gốc rút về Nháp là
  `decision_stale`; (q) "bản `approved` đã đổi" có cột `base_approved_id` để so; (r) ứng viên người duyệt phải đọc được
  thành phần; (s) lượt `simulate` không bị chặn vì điểm gắn. Sửa luôn: tập trạng thái của `GET .../bindings`. Sửa của lượt
  này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu chí đỏ được. Nếu sai thì: lỗi
  lộ ra khi dựng, ghi ở đây. MEDIUM để lại: (M7) phát hành kiểm `connection_usable` cho `proposed_by` của bản `approved`,
  nên Người đề xuất rời công ty hay mất `connections.use` chặn lần phát hành sau (đóng khi lỗi): người khác đề xuất lại
  cùng giá trị; (M8) chú thích của `UsableContext.principal_id` ở `dw_platform/application/connections.py` nói
  "`principal` của bản kê": sửa chú thích khi ticket này gắn `RunBindingsPort`.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): xong ở `0abd1c1` (mã) và commit test kế tiếp, trên `main`.
    - Quyết định theo ủy quyền, mỗi cái kèm `Nếu sai thì:`
      (a) `PublishBindingsCheck` khai ở `dw_studio.lifecycle.application.ports` vì agent-lifecycle/04 chưa dựng; hình
      `satisfied(tenant_id, version_id) -> BindingVerdict`, giao dịch riêng dưới tenant (handler không có người gọi).
      `StudioContainer.binding_status` đáp ứng; lệnh gửi trả `binding_unset[]` và handler `.decided` gọi nó là việc của
      agent-lifecycle/04 (bước 4 của ticket đó). Nếu sai thì: agent-lifecycle/04 đổi hình sang giao dịch của nó, `BindingStatus`
      nhận `BindingTx` thay `tenant_id`.
      (b) `ProposedDecision` ở `dw_platform.domain.approval` (runtime và platform cùng đọc), `ApprovalDecisionGuard` async ở
      `approval_flow.py`; guard `memory.review` giữ hàm đồng bộ qua `RuleGuard`. Nếu sai thì: chuyển `ProposedDecision` vào
      `approval_flow.py` và guard của platform khai Protocol riêng.
      (c) `ConfigKind` có `readable` cạnh `target`: đọc và rút một đề xuất không cần phiên bản niêm phong (Phiên bản gốc rút về
      Nháp không chặn Người đề xuất rút). Nếu sai thì: `get`/`withdraw` gọi `target` và chịu 409 `no_sealed_version`.
      (d) `binding_unset` và `binding_degraded` lúc nhận lượt là 409 `conflict` với `details.bindings` (tên). Nếu sai thì: 422.
      (e) `bindings` vào `dw.workflow/v1` là danh sách object do hình chung của Studio kiểm, `PACK_RULES` từ chối khóa, và
      `exclude=True` để không dump nào thêm khóa (tài liệu đã lưu và đề xuất wf-ai giữ nguyên văn bản). Nếu sai thì: Studio bóc
      `bindings` trước mỗi lần đọc tài liệu quy trình.
      (f) Tài liệu Bộ giá trị gắn là `{"values": {tên: giá trị}}`; `default` của biến là văn bản JSON của giá trị; biến chỉ
      nhận lược đồ vô hướng trong tập từ khóa đóng (không `pattern`, `$ref`). Nếu sai thì: thêm từ khóa có người đọc.
      (g) `platform.config_versions` được mô tả ở `dw_studio.core.adapters.tables` (khóa của bản kê trỏ vào nó;
      `test_metadata_matches_catalog.py` giữ nó bằng catalog), adapter của platform giữ danh sách cột riêng. Nếu sai thì: một
      bảng mô tả chung ở `dw_platform.adapters.persistence.tables`.
      (h) Mã băm khai báo (`base_bindings_hash`) bỏ `description`; `decision_stale` mang `details.reason`
      (`bindings_changed`, `base_not_sealed`, `approved_changed`, `connection_unusable`, `no_sealed_version`). Nếu sai thì:
      băm cả mô tả.
      (i) Lúc nhận lượt, `connection_usable` hỏi cho `run_as` của lượt ở workspace của lượt (`run_admission`); lượt
      `simulate` ghim giá trị đã duyệt hợp lệ và `default`. Nếu sai thì: hỏi cho `requested_by`.
    - Thêm ngoài tiêu chí: hai đề xuất đồng thời đọc lại cả `uq_..._proposed` lẫn `uq_..._version_no` thành `proposal_open`;
      `ck_config_versions_decided` và `ck_config_versions_superseded` giữ cột quyết định theo trạng thái.
    - Test: integration `test_bindings.py` 37 ca (mọi R7, R8, R3.6-R3.8, R2.18; cửa gọi thẳng: `ConfigVersionService`,
      `decide` của luồng phê duyệt với tiền tố và guard của composition root, `ConfigSettlement`, `BindingStatus`,
      `RunRequestService`, `SqlRunBindings`, với `ConnectionUsability` thật); `test_privileges.py` (grant cột);
      unit `test_bindings_domain.py` 10, `test_approval_flow.py` (guard thấy quyết định; `second_person_required` cho
      `memory.review` và `config.version`), `test_workflow_ir.py` (gói từ chối `bindings`), `test_config_versions_wiring.py`,
      `test_channel_commands.py` (tiền tố `config.` ở worker), `test_memory_review_wiring.py` (G4 trên guard async).
      Xanh: `test_rls_coverage`, `test_privileges`, `test_offboarding_coverage`, `test_permission_catalogue`,
      `test_metadata_matches_catalog`, `test_run_manifest`, `test_run_request`, unit toàn repo (phủ 76,7%).
    - `mutations/05.yaml` 35 đột biến, chưa chạy `mutate.py`; chạy tay 10 (sao lưu, khôi phục bằng chép), mỗi cái đỏ ở ca
      của nó: quét id kết nối, kiểm lúc nhận theo phiên bản của lượt, `connection_usable` lúc nhận, `extra="forbid"` của
      mục `bindings`, neo workspace sở hữu, so mã băm khai báo, hỏi lại kết nối lúc duyệt, bỏ qua dòng đã rời `proposed`,
      so `proposed_by` khi rút, nguồn của `ConnectionDependentsPort`.
    - `reviewing-feature-security` (đọc): mọi đọc qua RLS của giao dịch, tenant từ ngữ cảnh đã xác minh; id trong đường
      dẫn kiểm bằng khóa đọc của loại ở workspace sở hữu trước mọi việc, công ty khác như không có (404); người đề xuất,
      người duyệt và `connection_usable` neo ở workspace sở hữu; yêu cầu phê duyệt mang id và mã băm, không giá trị;
      bản kê không bí mật; mặc định đóng: kind không kiểm thì khởi động hỏng, kết nối không đọc được chỉ hiện id.
    - MEDIUM để lại: (M9) ba route chỉ có test hợp đồng (snapshot) và test khai báo idempotency; cửa thật thử ở mức dịch vụ;
      (M10) R3.6 kiểm purge và thứ tự, chưa kiểm export của `config_versions`; (M11) `BindingStatus` đọc trong giao dịch riêng,
      không phải giao dịch phát hành của agent-lifecycle/04 (quyết định (a)); (M3), (M7) của gate giữ nguyên.
    - Owed ở lúc đóng hàng: `mutate.py` cho `mutations/05.yaml`; `make test-integration` toàn bộ; P50/P95/P99 của ba route mới,
      của cửa nhận lượt (thêm một đọc Bộ giá trị gắn, đọc tài liệu bao đóng, một `connection_usable` mỗi kết nối) và của
      lệnh niêm phong (quét id kết nối); `/code-review`, `reviewing-deployment-security` (route mới).
