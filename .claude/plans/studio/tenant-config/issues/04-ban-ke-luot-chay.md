# 04 — Bản kê lượt chạy: ghim mọi thứ lượt chạy dùng, phân giải theo bản kê

Status: resolved (2026-11-04, main)
Blocked by: 02, 03, .claude/plans/studio/runtime-hardening/issues/03-run-va-outbox-khong-ket.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R3.6, R3.8, R2.18, TC15, TC21, TC28, TC29, TC31, TC32

## Mục tiêu

Mỗi lượt chạy có gốc là thành phần Studio ghim release ref, chế độ chạy, phiên bản gốc và bao đóng vào
một bản kê lưu một lần theo mã băm; trong lượt chạy, mọi phân giải chỉ đọc bản kê, kể cả khi tiếp tục ở
tiến trình khác sau 3 ngày chờ duyệt hay lâu hơn; không gì một lượt chạy còn trỏ tới bị dọn (spec R6,
TC15). Chỉ lượt `simulate` được có gốc là bản Nháp, ghim bằng mã băm tạm của nội dung nháp (R6.1, R6.7,
TC28). Mục `engine` ghim độ bền checkpoint `sync` (R6.8, TC32; V4.34). Ticket 05 thêm mục điểm gắn vào cùng bản kê,
không ghim phiên bản bí mật nào (V4.35).

Ticket này làm chủ thân bản kê, bộ dựng, hai bảng, cột `run_manifest_hash` và `PinnedResolver`, và thử chúng ở
chính các seam đó. Cửa nhận `RunRequestService` gọi bộ dựng trước node đầu tiên (workflow-engine/02, R3.3, R3.9),
runner truyền `durability` ở mọi lần chạy và tiếp tục (workflow-engine/03, R4.25), và sáu kiểm trước khi tiếp tục biến
lần từ chối của `PinnedResolver` thành `blocked` với `incompatible_resume` (workflow-engine/05, R6.7, R6.14); ba ticket
đó chờ ticket này, nên không tiêu chí nào ở đây cần chúng (spec, Ngoài phạm vi).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên), chép nguyên văn mục Dữ liệu của spec:
    - `platform.run_manifests`: khóa chính `(tenant_id, hash)`, `hash` khớp `^sha256:[0-9a-f]{64}$`,
      `body` jsonb NFC tối đa 1 MiB, `created_at timestamptz NOT NULL`; ghi bằng
      `INSERT ... ON CONFLICT DO NOTHING`; `dw_app` SELECT, INSERT và DELETE, DELETE chỉ dùng được ở lượt xóa của
      offboarding (spec R3.8).
    - `platform.run_manifest_keys`: `(tenant_id, manifest_hash)` FK tới `platform.run_manifests` ON
      DELETE CASCADE; `artifact_version_id` NOT NULL, FK ghép `(tenant_id, artifact_version_id)` ON DELETE RESTRICT
      tới `studio.artifact_versions (tenant_id, id)` qua `uq_artifact_versions_tenant_id_id` của ticket 02 (R2.18);
      unique `(tenant_id, manifest_hash, artifact_version_id)`; mỗi FK một index dẫn bằng cột của nó: FK
      `(tenant_id, manifest_hash)` qua unique đó, FK ghép của `artifact_version_id` qua index
      `(tenant_id, artifact_version_id)`; `dw_app` SELECT, INSERT và DELETE như `platform.run_manifests`. Ticket 05
      thêm `config_version_id` (FK ghép ON DELETE RESTRICT
      tới `uq_config_versions_tenant_id_id`), CHECK `num_nonnulls(artifact_version_id, config_version_id) = 1` và unique
      `(tenant_id, manifest_hash, config_version_id)`, và trong cùng bước bỏ NOT NULL của `artifact_version_id` mà
      revision này đặt.
    - `platform.worker_runs.run_manifest_hash` NULL, khớp `^sha256:[0-9a-f]{64}$`, FK
      `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` ON DELETE RESTRICT, index
      `(tenant_id, run_manifest_hash)`. Revision này không viết CHECK buộc lượt có gốc Studio mang bản kê, vì cột
      đánh dấu gốc Studio (`artifact_kind`) chưa có: workflow-engine/02 thêm nó và chờ ticket này, nên
      `ck_worker_runs_studio_manifest CHECK (artifact_kind IS NULL OR run_manifest_hash IS NOT NULL)` vào revision của
      ticket đó cùng cột (ADR-0109 (Accepted) quyết 6; Quyết định 3/11/2026 của spec). Lượt của worker định nghĩa bằng
      code và lượt wf-lite của Digital Worker (phiên bản ghim `<semver>+t<n>.<sha256>`, chưa là thành phần Studio,
      ADR-0109 (Accepted) sửa đổi 2026-11-02) giữ `run_manifest_hash` NULL.
    - Trigger BEFORE INSERT OR UPDATE OF `run_manifest_hash`, `run_mode` trên `platform.worker_runs`,
      `platform.match_run_manifest()` (R6.9, TC28): khi `NEW.run_manifest_hash` khác NULL, đọc `body->>'run_mode'` của
      dòng `platform.run_manifests` `(NEW.tenant_id, NEW.run_manifest_hash)` dưới quyền của bên gọi (RLS); khác
      `NEW.run_mode`, hay không đọc được → `ERRCODE 23514`, ràng buộc `ck_worker_runs_manifest_run_mode`; ở UPDATE, khi
      `OLD.run_manifest_hash` khác NULL mà `NEW.run_manifest_hash IS DISTINCT FROM OLD.run_manifest_hash` → `23514`,
      ràng buộc `ck_worker_runs_manifest_pinned`. `run_mode` của dòng là chỗ executor đọc khi chạy và khi tiếp tục
      (R4.5), `run_mode` trong thân là thứ bản kê ghim; trigger làm hai bản đó bất đồng ầm ĩ, không lặng lẽ
      (failure-modes #2), nên một cửa ghi dòng `live` cho bản kê `simulate` của một bản Nháp bị từ chối.
    - RLS ENABLE và FORCE theo tenant cho hai bảng mới; grant khẳng định trong `test_privileges.py`;
      `test_rls_coverage.py` thấy cả hai, và mỗi bảng có một dòng lý do trong danh sách bảng toàn tenant
      của test đó (bản kê định danh theo nội dung, dùng chung cho mọi lượt chạy cùng nội dung; khóa bản kê
      là con của bản kê; DO-01).
    - Trigger BEFORE DELETE `platform.refuse_delete_outside_offboarding()` của ticket 02 trên cả hai bảng mới (spec
      R3.8, TC31): ứng dụng không xóa dòng nào của hai bảng (bản kê định danh theo nội dung, khóa ghim phiên bản cho
      lượt chạy còn giữ), nên DELETE của `dw_app` chỉ để lane `offboarding` xóa được, vì lane chỉ xóa bảng có trong
      `_CATALOG_PURGEABLE`.
    - Offboarding, trên `offboarding.py` và `test_offboarding.py` mà foundations-hardening/07 đã viết lại: hai bảng
      dùng bước mặc định của sổ bước xóa (foundations-hardening:R11.4; H-2), không đăng ký bước nào; thứ tự suy từ
      `pg_constraint` đặt `platform.run_manifest_keys` trước `studio.artifact_versions` (FK RESTRICT của
      `artifact_version_id`; và trước `platform.config_versions` khi ticket 05 thêm FK RESTRICT của `config_version_id`),
      và `platform.worker_runs` trước `platform.run_manifests` (FK RESTRICT của `run_manifest_hash`; ADR-0109 (Accepted)
      Consequences). Dòng của `platform.run_manifest_keys` cũng mất qua CASCADE từ `platform.run_manifests`, nhưng bước
      riêng của bảng đó đã đứng trước `studio.artifact_versions`, nên thứ tự không dựa vào CASCADE.
    - Cột mới đi sau `ck_worker_runs_status` của runtime-hardening/03 trên cùng `platform.worker_runs`, nên
      revision này nối sau revision của ticket đó.
2. Thân `dw.run_manifest/v1`, mô hình trong lõi `dw_studio`, `extra="forbid"` ở mọi tầng (thân, `root`, mục bao đóng,
   `engine`): `schema`, `release_manifest_ref`, `run_mode`, `root`, `closure`, `engine`. Mã băm là `content_hash` của
   thân qua `dw_kernel.canonical`. Thân không chứa bí mật nào; ticket 05 thêm `bindings`.
    - `release_manifest_ref`: giá trị mà composition root đọc bằng `read_release_manifest_ref`
      (`apps/api/src/dw_api/bootstrap/paths.py:42`, `apps/worker/src/dw_worker/composition.py:387`), tiêm vào
      constructor của `RunManifestBuilder`, cùng giá trị mà dòng lượt chạy ghi.
    - `root`: `kind`, `artifact_id`, `version_id` (id của dòng phiên bản, cho mọi gốc; ADR-0109 (Accepted) quyết 6 ghi id
      phiên bản của gốc bản Nháp, và hai bản Nháp nối tiếp cùng nội dung là hai dòng khác nhau), `version_no` (null với
      mọi gốc có `stage` hiện tại `draft`, kể cả Bản ứng viên đã rút về còn giữ số cũ, vì lần niêm phong sau cấp số mới,
      R2.8), `definition_hash`, và `stage` `draft` chỉ khi gốc là bản Nháp. Gốc là bản Nháp khi `stage` của dòng lúc
      nhận là `draft`; khi tiếp tục, `root.stage` đã ghim quyết định, không `stage` hiện tại của dòng.
    - `closure` chỉ gồm phụ thuộc trực tiếp của gốc; một quy trình con hay một agent node chạy thành lượt riêng với bản
      kê riêng dựng từ phiên bản con mà bản kê của lượt cha ghim (ADR-0109 (Accepted) quyết 9; workflow-engine/09).
      Gốc đã niêm phong: nguyên văn `closure` của thân `studio.definition_manifests` đọc theo
      `(tenant_id, definition_hash)` của gốc. Gốc ở `draft` (chỉ lượt `simulate`, R6.7; ADR-0109 (Accepted) quyết 6):
      gọi lại hai hàm của ticket 02, không chép (failure-modes #2): `closure_of(uow, kind, artifact_id, document)` trên
      nội dung nháp đọc lúc nhận, rồi `definition_body(kind, artifact_id, content_hash(document), closure)`;
      `definition_hash` là `content_hash` của thân mà `definition_body` trả, và `closure` của bản kê là `closure` của
      chính thân đó, nên bước gộp trùng và xếp theo `(kind, key)` chỉ có một chủ. `closure_of` không ghi dòng nào (bước
      niêm phong của ticket 02 tự ghi `studio.dependencies`); không gì được ghi vào dòng nháp, `studio.dependencies` hay
      `studio.definition_manifests`. Tham chiếu hỏng của nháp → lỗi 422 `dependency_unresolved` của `closure_of`, nguyên
      văn; nội dung nháp không băm được (số thực, số nguyên ngoài ±(2^53−1), chữ không NFC) → `CanonicalError` của
      `dw_kernel.canonical` với con trỏ; cả hai trước khi ghi gì.
    - `engine`: mô hình `EngineSection` với `durability: Literal["sync"]` bắt buộc, không giá trị mặc định ở mô hình, do
      builder đặt cho mọi gốc (R6.8; V4.34). Ticket này không thêm trường nào vào mục `ArtifactKindRegistry` của ticket 02;
      các mục ghim theo loại của ADR-0109 (Accepted) quyết 8 (compiler, `type@major`, mã băm schema state, định dạng lưu,
      phiên bản LangGraph) vào `EngineSection` ở workflow-engine/05 cùng bên đọc của chúng (failure-modes #1).
    - Thân vượt CHECK kích thước 1 MiB của `platform.run_manifests.body` → vi phạm ánh xạ theo tên ràng buộc ra
      `PayloadTooLargeError`, không 500 và không dòng nào; một phép đo duy nhất là CHECK của bảng.
3. `RunManifestBuilder` trong lõi `dw_studio` (constructor injection: registry của ticket 02, `release_manifest_ref`),
   `build(uow, root_version_id, run_mode) -> str`, gọi thẳng bởi `RunRequestService` của workflow-engine/02 (cùng gói
   `dw_studio`, không qua Protocol), trong giao dịch nhận lượt chạy của bên gọi. Không có tham số tenant: tenant là
   `app.tenant_id` của giao dịch, và mọi lần đọc đi qua RLS (`CLAUDE.md`, Per-tenant artifacts). Theo thứ tự:
    - đọc dòng phiên bản gốc cùng dòng thành phần của nó, khóa dòng thành phần `FOR SHARE`, nên `save_draft` của ticket 02
      (khóa `FOR UPDATE` cùng dòng) chờ tới khi giao dịch nhận kết thúc và nội dung nháp được băm là nội dung được nhận;
      không thấy dòng (tenant khác, id không có) hay thành phần đã xóa mềm → `NotFoundError`, không ghi gì;
    - gốc ở `draft` mà `run_mode` khác `simulate` → `ConflictError` với `details.reason_code`
      `draft_root_not_simulate`, trước khi ghi gì, bên gọi nào cũng vậy (R6.7);
    - dựng thân như bước 2, kiểm bằng mô hình, tính mã băm;
    - `INSERT ... ON CONFLICT DO NOTHING` vào `platform.run_manifests`, rồi `INSERT ... ON CONFLICT DO NOTHING` các dòng
      `platform.run_manifest_keys`: một dòng cho phiên bản gốc và một dòng cho mỗi phiên bản mà một mục `artifact` của bao
      đóng ghim, lấy `to_version_id` từ `studio.dependencies` của phiên bản gốc khi gốc đã niêm phong (nguồn duy nhất của
      bao đóng một lượt chạy, ADR-0109 (Accepted) quyết 5), và từ các dòng `closure_of` phân giải khi gốc ở `draft`; mục
      `to_kind` khác không có dòng khóa (ticket 05 thêm dòng của phiên bản cấu hình). Hai lượt cùng nội dung nhận đồng
      thời không vỡ unique nào. Gốc `draft` với `simulate` → dòng khóa trỏ dòng nháp, FK RESTRICT giữ nó khỏi bị xóa cứng;
    - trả mã băm. `build` không ghi `platform.worker_runs`; cửa ghi dòng lượt chạy với mã băm đó.
4. Phân giải khi chạy và khi tiếp tục, qua ranh giới gói (`dw_agent_runtime` không import `dw_studio`, hợp đồng
   import-linter của studio-skeleton/02):
    - `RunManifestPort` khai trong `dw_agent_runtime.ports`, bên dùng là runtime dựng phân giải của lượt chạy Studio lúc
      chạy và lúc tiếp tục: `async load(run_manifest_hash) -> PinnedManifest`, gồm thân và, cho mỗi dòng
      `platform.run_manifest_keys`, dòng phiên bản bất biến (`id`, `artifact_id`, `version_no`, `stage`, `content_hash`,
      `definition_hash`, `document_schema`, `document`), đọc dưới tenant của giao dịch (RLS). Dòng không ở `draft` bất
      biến nhờ trigger của ticket 02 (TC1); dòng hiện ở `draft` (gốc là bản Nháp, hay Bản ứng viên đã rút về sau khi lượt
      ghim nó) thì sửa được, nên adapter kèm `current_hash` của dòng đó: với gốc, mã băm tính lại bằng `definition_body`
      của ticket 02 trên `document` hiện tại và `closure` đã ghim trong thân, không gọi lại `closure_of` (một phụ thuộc
      phát hành bản mới trong lúc chờ không làm lượt hỏng, vì bao đóng đã ghim); với mục bao đóng, `content_hash` của
      `document` hiện tại. `SqlRunManifestStore` trong tầng `adapters` của `dw_studio` đáp ứng, nối ở
      composition root của API và worker.
    - `PinnedResolver` trong `dw_agent_runtime`, dựng bằng `await PinnedResolver.load(port, run_manifest_hash)`: mã băm
      không đọc được (tenant khác, không có) → `ConfigError` với `details.reason` `manifest_not_found`; một dòng khóa
      không đọc được → `ConfigError`; dòng có `current_hash` khác mã băm đã ghim (`root.definition_hash` cho gốc, `content_hash`
      của mục cho mục bao đóng) → `ConfigError` với `details.reason` `pinned_version_changed`, không trả nội dung mới nào.
      So mã băm ở đây là chỗ duy nhất, mà kiểm thứ sáu của ADR-0109 (Accepted) quyết 8 ở workflow-engine/05 dùng.
    - `resolve(kind, key)` trả mục đã ghim (`kind`, `key`, `version`, `content_hash`, và với mục `artifact` thì dòng
      phiên bản); khóa không có trong bản kê → `ConfigError` với `details.key`, không truy vấn nào. Mục không phải
      `artifact` trả từ chính mục bản kê; loại nào đọc nội dung của mục đó từ ngoài database thì spec đăng ký loại đó so
      mã băm của nội dung với mã băm đã ghim. Mọi phân giải Studio trong lượt chạy Studio đi qua `PinnedResolver`.
    - `WorkflowRunnerPort.hosts` giữ chữ ký cho worker định nghĩa bằng code. Với lượt chạy Studio, câu "tiến trình này
      tiếp tục được không" là `PinnedResolver.load` thành công cộng các kiểm của ADR-0109 (Accepted) quyết 8 mà
      workflow-engine/05 chạy trước mỗi lần tiếp tục và nhận lại (ADR-0109 (Accepted) sửa đổi 2026-11-03).
5. Đo p95 của `build` (bao đóng 50 thành phần `live` của loại `fixture`, dựng bằng bộ dựng của `dw_studio.testing`) trên
   PostgreSQL của compose, 1.000 lượt nóng, mỗi lượt một gốc khác để lượt nào cũng chèn thật, một p95 cho gốc đã niêm
   phong và một cho gốc nháp `simulate` (đường `closure_of`), một lần ở lúc đóng hàng (`.claude/rules/wave-close.md`,
   `.claude/rules/latency.md`); ghi số đo và cấu hình máy vào Comments (R6.6).

## Tiêu chí chấp nhận

- [x] R6.1: `build` cho một phiên bản đã niêm phong của `fixture` có `uses` trỏ hai thành phần có bản `live` → trả mã
      băm bằng `content_hash` của thân; thân có `release_manifest_ref` tiêm vào, `run_mode`, `root` với `version_id`,
      `version_no`, `definition_hash`, `closure` bằng `closure` của bản kê định nghĩa của gốc, `engine.durability` `sync`;
      đúng ba dòng `platform.run_manifest_keys` (gốc và hai đích); test chèn một dòng `platform.worker_runs` cùng
      `run_mode` mang mã băm đó (đóng vai cửa của workflow-engine/02) → được.
- [x] R6.1 (TC28): `build` `simulate` trên bản Nháp `fixture` → thân ghim `stage` `draft` và `version_id` của dòng nháp;
      niêm phong đúng nội dung đó ngay sau trong test → `definition_hash` của bước niêm phong bằng mã băm tạm đã ghim;
      trước lần niêm phong, dòng nháp, `studio.dependencies` và `studio.definition_manifests` không đổi.
- [x] R6.1: bản Nháp có `uses` trỏ một thành phần chưa có bản `live` → lỗi 422 `dependency_unresolved` của `closure_of`;
      bản Nháp chứa một số thực → `CanonicalError` `float_forbidden` với con trỏ; cả hai không dòng `platform.run_manifests`
      hay `platform.run_manifest_keys` nào.
- [x] R6.2: hai lần `build` cùng nội dung → cùng mã băm, đúng một dòng `platform.run_manifests` và không dòng khóa trùng;
      hai lần `build` cùng nội dung ở hai giao dịch đồng thời → cả hai commit, cùng mã băm, không lỗi unique; bỏ
      `ON CONFLICT DO NOTHING` ở dòng khóa → ca đồng thời đỏ; đổi `run_mode` → mã băm khác.
- [x] R6.3 (TC15): `PinnedResolver` hỏi khóa không ghim → `ConfigError` với `details.key`, port (spy) không được gọi sau
      `load`; gỡ kiểm của `PinnedResolver` → test đỏ.
- [x] R6.4 (TC15): dựng bản kê cho gốc đã niêm phong, chèn dòng lượt chạy, niêm phong v2 của một đích trong bao đóng và
      đặt v2 `live`, v1 `retired` bằng vai migrator, rồi ở một tiến trình con mới (kết nối mới) `PinnedResolver.load` từ
      `platform.worker_runs.run_manifest_hash` → đích phân giải về v1 với `document` của v1; để resolver đọc bản `live`
      hiện hành → test đỏ.
- [x] R6.4 (TC15): bản kê `simulate` trên bản Nháp; lưu nháp nội dung mới rồi `load` ở tiến trình con →
      `ConfigError` `pinned_version_changed`, không nội dung mới nào được trả; bỏ so mã băm → test đỏ; nháp giữ nguyên mà
      một đích trong bao đóng phát hành bản mới → `load` thành công với bao đóng đã ghim.
- [x] R6.4 (TC15): bản kê `test` ghim một gốc ở `evaluating`; bằng vai migrator đưa gốc về `draft` (như lệnh rút của
      agent-lifecycle) rồi đổi `document` → `load` trả `ConfigError` `pinned_version_changed`; đưa về `draft` mà không đổi
      `document` → `load` thành công; chỉ so ở gốc có `root.stage` `draft` → ca đổi `document` đỏ.
- [x] R6.3 (TC15): ca âm chéo tenant (`CLAUDE.md`, Tenancy and authorization): giao dịch gắn tenant B gọi `build` với
      `root_version_id` là phiên bản của tenant A → `NotFoundError`, không dòng nào ở cả hai tenant; giao dịch gắn tenant B
      `PinnedResolver.load` mã băm bản kê của tenant A → `ConfigError` `manifest_not_found`; chạy truy vấn của
      `SqlRunManifestStore` bằng vai bỏ qua RLS → test đỏ.
- [x] R6.5 (TC15): ở một công ty đã chuyển sang `offboarding` (ngoài đó trigger của spec R3.8 từ chối lệnh xóa
      trước): DELETE phiên bản gốc của bản kê, dòng mà chỉ `platform.run_manifest_keys` giữ → lỗi FK nêu FK của
      `artifact_version_id`; DELETE bản kê mà `platform.worker_runs` còn trỏ tới → lỗi FK; gỡ FK của `artifact_version_id`
      → ca đầu đỏ.
- [x] R6.1: một thân giả lớn hơn 1 MiB → `PayloadTooLargeError`, không dòng `platform.run_manifests` nào; bỏ ánh xạ theo
      tên ràng buộc → lỗi 500, test đỏ.
- [ ] R6.6: p95 đo ở lúc đóng hàng được ghi ở Comments và không quá 20 ms, hoặc Quyết định của spec có dòng Đạt chấp
      nhận số đo mới.
- [x] R6.8 (TC32): bản kê của gốc `fixture` có `engine.durability` `sync`; dựng thân với `async`, thiếu `durability`, hay
      thêm một khóa lạ vào `engine` → lỗi kiểm mô hình, không dòng `platform.run_manifests`; đổi kiểu trường thành `str` →
      ca `async` được nhận, test đỏ.
- [x] R6.7 (TC28): `build` với gốc ở `draft` và `run_mode` `live` hay `test`, gọi thẳng không qua route nào →
      `ConflictError` `draft_root_not_simulate`, không dòng `platform.run_manifests` hay `platform.run_manifest_keys` nào;
      bỏ kiểm chế độ → test đỏ.
- [x] R6.9 (TC28): `dw_app` chèn dòng `platform.worker_runs` `run_mode` `live` mang mã băm của một bản kê `simulate` →
      23514 `ck_worker_runs_manifest_run_mode`, không dòng nào; cùng chế độ → được; dòng worker định nghĩa bằng code với
      `run_manifest_hash` NULL → được; UPDATE `run_manifest_hash` đã đặt sang mã băm khác → 23514
      `ck_worker_runs_manifest_pinned`, dòng giữ nguyên; gỡ trigger → test đỏ.
- [x] R2.18 (TC29): bằng vai migrator, INSERT dòng `platform.run_manifest_keys` của tenant A có `artifact_version_id`
      là phiên bản của tenant B → lỗi FK ghép; đổi FK ghép về FK một cột → test đỏ.
- [x] R3.6 (TC21): `test_offboarding.py` purge tenant có lượt chạy ghim bản kê lên phiên bản Studio, tenant
      khác giữ nguyên; thứ tự mà sổ bước xóa suy ra đặt `platform.run_manifest_keys` trước `studio.artifact_versions` và
      `platform.worker_runs` trước `platform.run_manifests`; đột biến phép suy để bỏ cạnh của `artifact_version_id` → test
      phủ offboarding (studio-skeleton:R4.2) đỏ, nêu FK ghép của `artifact_version_id`; thu DELETE của `dw_app` trên
      `platform.run_manifests` → test phủ (studio-skeleton:R4.3) đỏ, nêu tên bảng.
- [x] R3.8 (TC31): `dw_app` DELETE một dòng `platform.run_manifests` hay `platform.run_manifest_keys` của công ty
      `active` → 23514, dòng còn; cùng lệnh khi công ty ở `offboarding` → xóa được; gỡ trigger khỏi một trong hai bảng
      → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:132`; spec: R6.4; ADR-0109 (Accepted) quyết 7, sửa đổi
  2026-11-03.
- `db/migrations/versions/0005_run_artifact_versions.py:41-51`; spec: R6.1.
- `db/migrations/versions/c478ca7b6ed1_run_mode_and_simulated_tool_calls.py` (`run_mode` của ticket 03); spec: R6.9.
- `apps/api/src/dw_api/bootstrap/paths.py:42`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114` (foundations-hardening/07 thay
  bằng sổ bước xóa); spec: R3.6, TC21; ADR-0109 (Accepted) quyết 6-7.
- ADR-0109 (Accepted) quyết 8 (mục `engine`, độ bền `sync`); spec: R6.8, TC32.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`; spec: R3.8, TC31.

## Comments

- 2026-10-23 (agent): từ B6 tenant-config 05. Mục lớp riêng của tenant (`overlay`) và `effective_hash`
  vào bản kê cùng lớp riêng ở W2.
- 2026-10-24 (agent): vòng sửa thứ tư, theo Quyết định cùng ngày của spec: lượt `simulate` được có gốc là bản
  Nháp, ghim giai đoạn `draft` và mã băm tạm; lượt khác có gốc `draft` bị từ chối (R6.1, R6.7, TC28; quyết định
  của Đạt). Ticket này chờ runtime-hardening/03, vì `ck_worker_runs_status` có trước cột `run_manifest_hash`
  trên cùng `platform.worker_runs` (quyết định tạm của spec; ticket kia ghi cùng cạnh ở Comments của nó), và chờ
  foundations-hardening/07, vì cùng sửa `offboarding.py` và `test_offboarding.py`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các quyết định tạm cùng ngày của spec: `artifact_version_id` là FK
  ghép tới `uq_artifact_versions_tenant_id_id` của ticket 02 (R2.18, TC29); gốc bản Nháp dẫn ADR-0109 (Accepted)
  quyết 6, và lần tiếp tục bị từ chối theo kiểm thứ sáu của quyết 8.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các quyết định tạm cùng ngày của spec: `artifact_version_id` NOT
  NULL ở ticket này; ticket 05 bỏ NOT NULL đó cùng bước thêm `config_version_id`, CHECK `num_nonnulls` và unique của
  cột mới; FK của `artifact_version_id`, và FK của `config_version_id` mà ticket 05 thêm, nêu `ON DELETE RESTRICT`
  tường minh.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo quyết định tạm cùng ngày của spec: FK `(tenant_id, manifest_hash)`
  dùng unique `(tenant_id, manifest_hash, artifact_version_id)` làm index dẫn bằng hai cột của nó (`CLAUDE.md`, Data
  model rules).
- 2026-10-24 (agent): vòng sửa thứ tư, theo quyết định tạm cùng ngày của spec về quyền xóa của lane `offboarding`:
  `dw_app` có DELETE trên hai bảng của ticket này, chỉ dùng được ở lượt xóa của offboarding nhờ trigger của ticket 02
  (R3.8, TC31); `platform.run_manifest_keys` vào `_ORDERED_FIRST` thay cho `platform.run_manifests`, vì test phủ
  offboarding kiểm FK RESTRICT tới `studio.artifact_versions` theo thứ tự các bước xóa mà `offboarding.py` khai, không
  theo CASCADE (studio-skeleton:R4.2), nên ca âm của R3.6 gỡ mục đó; ca xóa cứng để thấy lỗi FK (R6.5) chạy khi công ty
  ở `offboarding`.
- 2026-10-25 (agent): lượt h, theo V4.34 của Đạt và H-2 (quyết định cùng ngày của spec): mục `engine` của thân có
  `durability` `sync` (R6.8, TC32), mà workflow-engine/03 truyền; hai bảng của ticket dùng bước mặc định của sổ bước xóa
  của foundations-hardening/07, thứ tự suy từ `pg_constraint`, thay mục `_ORDERED_FIRST` của các dòng Comments ngày
  24/10/2026, và ca âm của R3.6 thành đột biến phép suy. Dòng Blocked by không đổi.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk trong
  một subagent, vì ticket thêm migration; không route; đối chiếu ticket 02 đã ĐẠT ở `2a22b5d`, mã sau ticket 01, 03 và
  `5246de9`): 2 CRITICAL, 8 HIGH, đã sửa ở bước 1-5 và tiêu chí, mỗi cái một dòng Quyết định 3/11/2026 của spec với
  Nếu sai thì. CRITICAL: (1) `root` thiếu `version_id` mà ADR-0109 (Accepted) quyết 6 ghi cho gốc bản Nháp; (2) không ca
  âm chéo tenant nào ở `build` hay `PinnedResolver` (`CLAUDE.md`, Tenancy and authorization). HIGH: (3) tiêu chí R6.1,
  R6.4 cần cửa, runner và kiểm tiếp tục của workflow-engine/02, 03, 05, ba ticket chờ ticket này, và CHECK "gốc Studio có
  bản kê" cần cột `artifact_kind` của workflow-engine/02: tiêu chí nay thử ở seam của ticket này, CHECK sang revision
  của workflow-engine/02; (4) bao đóng nháp "lấy từ `extract`" thay vì gọi lại `closure_of` và `definition_body` của
  ticket 02; (5) băm lại nháp khi tiếp tục dùng bao đóng đã ghim, không gọi lại `closure_of`; (6) dòng khóa ghi `ON
CONFLICT DO NOTHING`; (7) `run_mode` ở dòng lượt chạy và trong thân bất đồng được: trigger
  `platform.match_run_manifest()` và R6.9, kèm `run_manifest_hash` đã đặt thì không đổi; (8) `RunManifestPort` là
  `load` cho runtime qua ranh giới gói, `build` gọi thẳng trong `dw_studio`; (9) `engine` không lấy từ mục registry mà
  ticket 02 không có trường đó; (10) `hosts` giữ chữ ký, lượt Studio hỏi `PinnedResolver.load` và kiểm của
  workflow-engine/05 (ADR-0109 (Accepted) sửa đổi 2026-11-03).
- 2026-11-03 (agent): đối chiếu ticket 02 (hợp đồng đã ĐẠT, chưa dựng): không mâu thuẫn buộc sửa ticket 02. Ticket này
  dựa vào `closure_of` không ghi dòng nào (bước niêm phong tự ghi `studio.dependencies`) và vào `definition_body` nhận
  `closure` rồi tự gộp trùng và xếp; nếu người dựng ticket 02 đặt bước ghi hay bước xếp ở chỗ khác, ticket này gọi đúng
  hàm làm việc đó, không chép (tiêu chí R6.1 (TC28) đỏ khi hai bản lệch). Không thêm trường nào vào `ArtifactKindRegistry`.
- 2026-11-03 (agent): việc của ticket ngoài vùng này, cho gate của ticket đó: workflow-engine/02 thêm
  `ck_worker_runs_studio_manifest CHECK (artifact_kind IS NULL OR run_manifest_hash IS NOT NULL)` cùng cột
  `artifact_kind` và một ca âm (gỡ CHECK → dòng Studio thiếu bản kê lọt), và khóa dòng thành phần gốc `FOR SHARE` trước
  `validate` của bản Nháp, để `validate` và `build` đọc cùng một nội dung; workflow-engine/05 thêm vào `EngineSection`
  các mục ghim theo loại của ADR-0109 (Accepted) quyết 8 và đọc `ConfigError` của `PinnedResolver.load` thành `blocked`
  với `incompatible_resume`.
- 2026-11-03 (agent): MEDIUM và LOW của gate, chưa sửa, cho người dựng:
  (a) `release_manifest_ref` là `unreleased` ở cây chưa phát hành; một môi trường `settings.is_deployed` mà đọc ra
  `unreleased` nên từ chối nhận lượt chạy Studio thay vì ghim lớp nền tảng không truy được (failure-modes #7); chủ là
  composition root của API và worker;
  (b) `ConfigError` giữa lượt (khóa không ghim) kết thúc lượt với mã lỗi ổn định, audit và span, không thử lại; chủ là
  wrapper nút của workflow-engine/03;
  (c) mỗi lần lưu nháp rồi mô phỏng sinh một bản kê mới giữ FK RESTRICT lên dòng nháp; dọn bản kê theo lưu giữ của lượt
  chạy là W2 (spec, Ngoài phạm vi: "lưu giữ và dọn"; ADR-0109 (Accepted) Open 3);
  (d) cạnh `platform.worker_runs` → `platform.run_manifests` nằm ngoài schema `studio`, nên test phủ của
  studio-skeleton:R4.2 không đọc nó; ca purge của tiêu chí R3.6 với một lượt chạy trỏ bản kê là phép đo của cạnh đó;
  (e) tiêu chí R6.4 dùng tiến trình con (`subprocess`, kết nối mới) cho "tiến trình khác"; lần tiếp tục thật qua runner
  là của workflow-engine/05 (R6.7, R6.14).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 3 HIGH, đã sửa: dòng
  khóa hiện ở `draft` (Bản ứng viên rút về sau khi lượt ghim nó, rồi sửa) được băm lại, không chỉ gốc có `root.stage`
  `draft`, lỗi chung `pinned_version_changed`; ca R6.4 đặt v2 `live` và v1 `retired`, vì v2 còn ở `draft` thì resolver đọc
  bản hiện hành cũng trả v1; ca R6.5 xóa phiên bản gốc mà chỉ dòng khóa giữ, kèm đột biến gỡ FK. Kèm (MEDIUM, sửa luôn vì
  rẻ): bao đóng chỉ gồm phụ thuộc trực tiếp, lượt con có bản kê riêng; `version_no` null với mọi gốc ở `draft`; giới hạn
  1 MiB là CHECK của bảng, ánh xạ theo tên ra `PayloadTooLargeError`; phép đo R6.6 mỗi lượt một gốc khác, hai đường.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): (1) `platform.run_manifest_keys` có khóa chính `id` (uuid do ứng dụng
      cấp), vì lane offboarding xuất theo keyset trên khóa chính và ticket 05 bỏ NOT NULL của `artifact_version_id` nên bộ ba
      unique không làm khóa chính được. Nếu sai thì: khóa chính ghép ở ticket 05 cùng `config_version_id`. (2) Unique
      `(tenant_id, manifest_hash, artifact_version_id)` đặt tên tay `uq_run_manifest_keys_tenant_id_manifest_hash_artifact_version`
      (tên theo quy ước dài 64 ký tự, quá giới hạn 63 của PostgreSQL); `CHECK` 1 MiB là ràng buộc riêng
      `ck_run_manifests_body_size`, để ánh xạ theo tên không bắt nhầm `ck_run_manifests_body_object`. Nếu sai thì: đổi tên trong
      revision mới. (3) Hai bảng không phân vùng: định danh theo nội dung, không theo thời gian, và FK
      `(tenant_id, run_manifest_hash)` cần unique không có cột phân vùng; dọn bản kê theo lưu giữ là W2 (MEDIUM (c), ADR-0109 (Accepted)
      Open 3). Nếu sai thì: phân vùng theo `created_at` cần đổi khóa của FK, tức đổi ADR-0109 (Accepted) quyết 6. (4) `closure_of` thành hàm
      cấp module nhận registry (`ArtifactService.closure_of` gọi nó), để `RunManifestBuilder` chỉ nhận registry và
      `release_manifest_ref` như bước 3 viết; không chép dòng nào. (5) `RunManifestTx` (Protocol mở rộng `ArtifactTx`, năm
      phương thức) do `SqlArtifactTx` đáp ứng; `ArtifactStore.transaction` vẫn trả `ArtifactTx`, nên `RunRequestService` của
      workflow-engine/02 cần một Protocol cửa hàng trả `RunManifestTx` (test ở đây dùng `SqlArtifactStore` cụ thể). (6) Mô tả hai
      bảng nằm ở `dw_studio.core.adapters.tables` với `schema="platform"`, và `test_metadata_matches_catalog.py` so cả hai với
      catalog. (7) Composition root của API dựng `RunManifestBuilder(registry, release_manifest_ref())` và
      `pinned_manifests=SqlRunManifestStore` trong `StudioContainer`; worker chưa nối, vì worker chưa phụ thuộc `dw-studio` và bên
      đọc ở worker là lần tiếp tục của workflow-engine/05 (failure-modes #1). Nếu sai thì: thêm `dw-studio` vào
      `apps/worker/pyproject.toml` và dựng cùng hai thứ ở `composition.py`. (8) `dw_studio` khai `dw-agent-runtime` (kiểu của
      `RunManifestPort`) và `pydantic`; không gói ngoài mới, `uv.lock` chỉ đổi mục `dw-studio`.
    - Thêm ngoài tiêu chí: `PinnedResolver` cũng từ chối dòng khóa không đọc được (`pinned_version_unreadable`); khi đọc gốc,
      dòng thành phần khóa `FOR SHARE` trong một câu lệnh, dòng phiên bản đọc ở câu lệnh sau (một câu JOIN đọc phiên bản từ ảnh
      chụp trước khi `save_draft` mà nó chờ commit), có test giữ giao dịch nhận ngay sau lần đọc đầu: giữ ở sau khi ghi dòng khóa
      thì FK của dòng khóa tự chặn `save_draft`, test không thấy khóa (đo tay 4/11/2026). Hai test đồng thời chờ tới khi
      `pg_locks` có phiên chờ, không `sleep`. Ca R3.6: thứ tự theo tên đã đặt `platform.run_manifest_keys` trước
      `studio.artifact_versions`, nên đột biến bỏ cạnh FK không làm test purge đỏ; thêm test đặt tên bước ngược chữ cái và đọc
      FK bằng truy vấn của lane (đột biến TC21 đỏ ở test đó).
    - Test: unit `test_pinned_resolver.py` 7 ca, `test_run_manifest_model.py` 9 ca; integration `test_run_manifest.py` 20 ca
      (R6.1 ×4, R6.2 ×2, R6.3 chéo tenant, gốc xóa mềm, R6.7 ×2, R6.8, R6.9, R6.4 ×3 trong đó 2 qua tiến trình con
      `dw_studio.testing.pinned_probe`, khóa `FOR SHARE`, TC29, R6.5, TC31 ×2), `test_metadata_matches_catalog.py`,
      `test_offboarding.py` (ca Studio có lượt chạy ghim bản kê, thứ tự theo FK), `test_privileges.py`, `test_rls_coverage.py`,
      `test_studio_artifacts.py` (nối ở composition root). Toàn bộ test của `dw_studio`, các test catalog của `dw_platform`,
      unit của API và runtime: xanh.
    - `mutations/04.yaml` 27 đột biến, chưa chạy bằng `mutate.py`; chạy tay khi viết test (bộ test xanh ngay lần đầu), mỗi cái
      đỏ ở ca của nó: kiểm khóa của resolver, so mã băm, kiểm chế độ của bản Nháp, kiểm chế độ của trigger, `ON CONFLICT` của dòng
      khóa, `FOR SHARE` khi nhận, phép nối về bản `live` hiện hành, cạnh FK của offboarding.
    - `reviewing-feature-security` (đọc): mọi truy vấn qua RLS của giao dịch (`set_config(..., true)`), không tham số tenant; ca
      âm chéo tenant ở `build` và `load`, số dòng hai tenant không đổi; không route, không quyền mới (cửa của workflow-engine/02
      kiểm quyền); thân qua mô hình `extra="forbid"` trước lần ghi đầu, không bí mật; FK RESTRICT giữ phiên bản và bản kê; mặc
      định đóng: bản kê không đọc được thì trigger từ chối, dòng khóa không đọc được hay thiếu bản kê định nghĩa thì từ chối.
      Không gói ngoài mới, không image mới.
    - MEDIUM để lại: (a) của gate (`unreleased` ở môi trường triển khai), (b) (`ConfigError` giữa lượt), (c) (dọn bản kê, W2),
      (e) (lần tiếp tục thật là của workflow-engine/05) giữ nguyên chủ; mới: `RunRequestService` cần Protocol cửa hàng trả
      `RunManifestTx` (quyết định (5) ở trên); trigger `platform.match_run_manifest()` đọc bản kê dưới RLS của bên gọi, nên
      một lane xuyên tenant (`app.worker_drain`) ghi `run_mode` hay `run_manifest_hash` của lượt Studio sẽ bị từ chối: lane đó
      phải gắn tenant của lượt.
    - Owed ở lúc đóng hàng: `mutate.py` cho `mutations/04.yaml`; p95 của `build` (R6.6, 1.000 lượt, 50 thành phần, hai đường;
      `dw_studio.testing.run_manifests.live_closure` dựng bao đóng); `make test-integration` toàn bộ; độ trễ của
      INSERT/UPDATE `platform.worker_runs` (trigger mới đọc một dòng bản kê khi cột khác NULL).
- 2026-11-04 (agent, discovery/14 câu 6, `db/bench/srt/RESULTS.md`): phép đo R6.6 chạy trên máy dev (PostgreSQL của compose không giới hạn): `build` bao đóng 50, 1.000 gốc khác nhau, p50 / p95 / p99 23,4 / 30,9 / 40,9 ms với gốc đã niêm phong (trên ngưỡng 20 ms) và 131,9 / 168,0 / 194,1 ms với gốc Nháp; `PinnedResolver.load` khi resume 6,3 / 7,8 ms nóng, 69,8 / 93,4 ms ở tiến trình mới với kết nối mới. Chưa phải số của lúc đóng hàng trên máy tham chiếu; ngưỡng 20 ms trượt cần Đạt chấp nhận số mới hay một lượt sửa.
