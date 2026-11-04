# 04 — Bước dữ liệu đối tượng qua RecordsPort và bước giao người phụ trách

Status: ready-for-agent
Blocked by: 03, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2, R6.3, R6.4, R6.5, WN4, WN16

## Mục tiêu

Các bước đọc và ghi bản ghi đi qua một `RecordsPort` do người dùng khai báo (RecordService đáp ứng), với
quyền của người chạy, và một bộ contract test của cổng đó chạy trên mọi bản cài, để bản giả mà workflow-engine dùng
không trôi khỏi bản thật; và một bước giao người phụ trách theo quy tắc, xoay vòng theo người lâu nhất chưa
nhận, không giao lại cho người kế tiếp khi chạy lại (workflow-nodes R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2,
R6.3, R6.4, R6.5, WN4, WN16).

## Việc cần làm

1. **Bộ contract test trên bản thật.** `RecordsPort` và `RecordAssignPort` do workflow-engine/03 khai trong
   `dw_studio.workflows.ports` (bên dùng là quy trình; H-30), thỏa bởi `RecordService` của custom-objects và
   `AssignRecordService` của record-access/05. Ticket này chạy bộ contract test mà workflow-engine/03 khai cạnh Protocol
   (`packages/python/dw_studio/src/dw_studio/workflows/testing/records_port_contract.py`) trên hai bản cài qua tham số:
   bản giả `dw_studio.workflows.testing.FakeRecordsPort` mà workflow-engine/03 dùng để thử workflow-engine:R4.7 và
   workflow-engine:R4.22, và `RecordService` thật nối như ở composition root (H-7). Các ca của hợp đồng R5:
    - lệnh ghi ở `simulate` không ghi dòng, sự kiện hay audit nào (custom-objects:R5.4);
    - gặp lại cùng khoá chống lặp thì trả kết quả đã lưu, không ghi lần hai (mức bảo đảm nội bộ, V4.30);
    - lệnh sửa chỉ đổi các trường nó mang (PATCH theo trường, V4.34);
    - chủ thể chạy thiếu quyền → `permission_denied`;
    - id bản ghi của công ty khác → `not_found` như id không có, không ghi gì (RLS của `RecordService`).

    Cùng bộ phủ `RecordAssignPort` trên bản giả mà workflow-engine/03 dùng cho ca `assign` và trên `AssignRecordService`
    thật: gặp lại cùng khoá thì trả người đã giao, không giao lần hai; `run_mode` `simulate` thì không đổi người phụ
    trách, không audit, không outbox, không dòng khoá (record-access/05 bước 6); chủ thể chạy không có tầm `assign` →
    `assign_not_permitted` (record-access:R8.4); id bản ghi của công ty khác → `not_found`.

2. **Bốn bước `data.object.query|create|update|upsert`** (Studio, mới trong `studio_node_types` của ticket 03).
    - Ngữ cảnh actor lấy từ lượt chạy. Khoá chống lặp là khoá wrapper nút dẫn theo workflow-engine:R4.5; Bước chỉ chuyển
      nó qua và không tự dựng khoá.
    - Lệnh sửa một bản ghi có sẵn của `update` và `upsert` chỉ mang các trường cấu hình của Bước nêu, không cả bản ghi
      đã đọc, vì workflow-engine:R7.3 dựa vào đó cho hai làn song song sửa cùng một bản ghi (R5.1; V4.34).
    - `limit` 1-200 (200 nhận, 201 lỗi); tối đa 100 trường mỗi lần ghi. `query` dùng cây lọc AST của custom-objects.
    - Cấu hình không nhận `owner_id`, `owner_kind`, `workspace_id` hay `object_id` như trường để ghi: đổi người phụ trách
      chỉ đi qua Bước giao (bước 6), vì `dw_app` không UPDATE các cột đó (record-access:R1.3).
    - Đầu ra kiểu bản ghi mang id đối tượng, để phép lọc Trường của ticket 03 (bước 2) áp được: `query` trả
      `{records, next_cursor}`, `create` và `update` trả `{record}`, `upsert` trả `{record, created}`.
    - Bản ghi tạo mới thuộc workspace mà ngữ cảnh actor của lượt nêu (workspace của lượt chạy), do `RecordService` đặt;
      Bước không chọn workspace.
    - Mỗi loại khai `block` `none`, `ends_run` và `exits_loop` sai, `dependencies` một dòng `artifact` tới đối tượng
      (`usage` `read` cho `query`, `write` cho ba loại kia), Khi lỗi `fail`, `continue`, `route`, và `side_effect_level`
      `none` cho `query`, `internal` cho ba loại kia.
3. Schema loại bước bản ghi không có khoá `run_as` và không nhận chủ thể khác người chạy; một cấu hình mang khoá đó bị
   schema từ chối.
4. **Chế độ chạy**: Bước bản ghi và Bước giao chuyển nguyên `run_mode` của lượt chạy qua `RecordsPort` và
   `RecordAssignPort`; `RecordService` và `AssignRecordService` giả lập ở `simulate` (custom-objects:R5.4;
   record-access/05 bước 6); Bước không có nhánh giả lập riêng (ADR-0112 (Accepted) quyết 6). Thiếu `run_mode` ở lời
   gọi là lỗi lập trình (`ValueError`), không bao giờ đọc thành `live`.
5. **Kiểm trùng cho quy trình Tiếp nhận lead** (R5.4): `upsert` nhận `match_on`, danh sách có thứ tự các
   `{field, normalize}`, `normalize` là một Biểu thức CEL trên giá trị vào. Bước thử từng khóa theo thứ tự, khóa đầu tiên
   tìm thấy bản ghi thì sửa bản ghi đó; giá trị mà `normalize` lỗi thì bỏ qua khóa đó; không khóa nào khớp thì tạo mới.
   So khớp là phép bằng giữa giá trị vào đã chuẩn hóa và giá trị đã lưu, qua cây lọc của `RecordsPort`; vì vậy quy trình
   ghi giá trị đã chuẩn hóa vào chính trường đó khi tạo hay sửa (`{{ phone.e164(trigger.input.phone) }}`). Một khóa khớp
   từ hai bản ghi trở lên thì sửa bản ghi cũ nhất theo `(created_at, id)`. Bản ghi mà chủ thể chạy không đọc được thì
   không khớp. Quy trình mẫu dùng `phone` với `phone.e164` rồi `email` với `email.normalize`. "0901 234 567" và
   "+84901234567" là một Lead; cùng tên khác số và khác email là hai Lead (MP10).
6. **`data.object.assign`** (Studio, mới).
    - Cấu hình: `object` (`api_name` của đối tượng), `record_id` (một `{{ expr }}`), `candidates` tùy chọn (một Biểu
      thức `x-dw-cel` kiểu `list[string]`, danh sách id người), `fallback` (tên một điểm gắn kind `principal` trong
      `bindings[]`), `reassign` (`bool`, mặc định `false`). Bản ghi không thuộc `object` → `not_found`. Đầu ra
      `{owner_id, assigned}`.
    - Thứ tự lúc chạy: trước hết, một dòng vòng xoay mang khóa của lần chạy này (chạy lại) → gọi `RecordAssignPort` với
      người đó và cùng khóa, lấy kết quả phát lại làm đầu ra, nên đầu ra của lần chạy lại bằng lần đầu. Không có thì xét
      các mục dưới.
    - Bản ghi đã có người phụ trách khác chủ thể chạy của lượt, người đó vẫn thỏa kiểm người nhận của
      record-access:R8.5, và `reassign` là `false` → Bước không giao, đầu ra `{owner_id, assigned: false}`; lead trùng
      sau `upsert` vì thế giữ người cũ, còn lead của một người đã rời công ty thì được giao lại.
    - Ứng viên: thành viên công ty đang hoạt động thỏa đúng kiểm người nhận của record-access:R8.5 trên bản ghi đó (quyền
      `read` đối tượng, thành viên workspace sở hữu bản ghi), gọi cùng hàm mà `AssignRecordService` dùng, không bản sao
      (R6.1), trừ tài khoản dịch vụ; có `candidates` thì chỉ trong danh sách đó. Tầm giao là workspace sở hữu của bản
      ghi, giữ nguyên (DO-11). Ở `simulate`, một `record_id` không có thật (bản ghi mà một Bước ghi giả lập trả) dùng
      workspace của lượt chạy làm tầm giao.
      Biểu thức `candidates` lỗi hay vượt ngân sách → Bước lỗi `expression_error` theo Khi lỗi, không đi người dự phòng.
    - "Lâu nhất chưa nhận" (R6.2): bảng `studio.assign_rotation` của ticket này (bước 7), một vòng xoay cho mỗi Bước
      giao của một quy trình. Người chưa từng nhận đứng trước; hòa thì id nhỏ hơn.
    - Không ứng viên nào hợp lệ → người dự phòng là giá trị đã duyệt của điểm gắn `fallback` (tenant-config/05), đọc
      qua `RunBindingsPort` từ bản kê, qua cùng kiểm của R6.1. Điểm gắn thiếu giá trị thì lần gửi kiểm định trả 409
      `binding_unset` (tenant-config:R7.2). Người dự phòng cũng không hợp lệ → Bước kết thúc với lỗi `no_assignee` theo
      Khi lỗi của nó (làn lỗi khi `route`), không giao.
    - Giao bằng `AssignRecordService` của record-access/05 qua `RecordAssignPort`, dưới ngữ cảnh actor của lượt. Dịch vụ
      kiểm tầm `assign` của chủ thể chạy (record-access:R8.4) và ghi audit, outbox `studio.record.assigned` trong một
      giao dịch, actor là chủ thể chạy (record-access:R8.7, record-access:R8.8). Bước không gọi `studio.assign_record`
      và không tự ghi audit.
    - Bước chuyển đúng khoá chống lặp mà wrapper nút dẫn (workflow-engine:R4.5) qua `RecordAssignPort`; lần giao ghi
      khoá cùng giao dịch và phát lại người đã giao khi gặp lại khoá (V4.30 mục 10), nên một lần chạy lại sau khi
      worker chết không giao bản ghi cho người kế tiếp (R6.5).
    - `block` `none`, `ends_run`, `exits_loop` sai, `dependencies` một dòng `artifact` tới đối tượng (`usage`
      `assign`), Khi lỗi `fail`, `continue`, `route`, `side_effect_level` `internal`.
7. **Migration** (`alembic revision -m "studio assign rotation"`, id hex ngẫu nhiên): bảng `studio.assign_rotation`
   (`tenant_id`, `artifact_id`, `node_id text`, `principal_id uuid`, `last_assigned_at timestamptz NOT NULL`,
   `last_key text NOT NULL`), PK `(tenant_id, artifact_id, node_id, principal_id)`, FK `(tenant_id, artifact_id)` tới
   `studio.artifacts (tenant_id, id)` `ON DELETE CASCADE` mà PK là index của nó. Bảng toàn tenant (vòng xoay thuộc một
   quy trình, định nghĩa toàn tenant), nên không có `workspace_id` và có một dòng lý do trong danh sách bảng toàn tenant
   của `test_rls_coverage.py`; RLS bật và FORCE, policy theo `app.tenant_id`; `dw_app` SELECT, INSERT, UPDATE; một dòng
   trong `test_offboarding_coverage.py`. Không audit: đây là dòng vận hành, không phải bản ghi một người làm (CLAUDE.md,
   Agent and tool rules).
    - Chọn người ở `live`: trong một giao dịch, trước hết `pg_advisory_xact_lock` trên băm của
      `(tenant_id, artifact_id, node_id)`, để cả lần chạy đầu (chưa có dòng nào để khóa) cũng nối tiếp nhau; rồi đọc các
      dòng của `(artifact_id, node_id)`; một dòng có `last_key` bằng khoá của lần chạy này thì trả người đó (chạy lại);
      không thì chọn theo bước 6, rồi `INSERT ... ON CONFLICT DO UPDATE` dòng của người được chọn với
      `last_assigned_at = now()` và `last_key` là khoá, rồi commit, rồi gọi `RecordAssignPort`. Hai lượt đồng thời vì
      vậy không chọn cùng một người.
    - Lần giao sau đó lỗi (`assign_not_permitted`, `not_found`) thì dòng đã ghi giữ nguyên và Bước lỗi theo Khi lỗi:
      người được chọn lùi một lượt trong vòng xoay, chỉ lệch công bằng, không lệch người phụ trách (MEDIUM (d)).
    - Ở `simulate`: chỉ đọc, không ghi dòng nào.
    - Vòng xoay đọc và ghi qua một Protocol hẹp mà ticket này khai trong `dw_studio.workflows`, đáp ứng bằng một adapter
      SQL nối ở composition root, nên mô-đun loại bước không chứa SQL (R2.2).

## Tiêu chí chấp nhận

- [ ] R2.1: mỗi bước bản ghi có đúng một tác dụng phụ, đi qua `RecordsPort`; test kiến trúc: mô-đun bước không có SQL
      nhắc `studio.records` hay `studio.assign_rotation`. `query` với `limit` 200 → nhận, 201 → `wf.config_invalid`.
- [ ] R2.2: mô-đun loại bước không import adapter cụ thể và không có SDK nhà cung cấp (test kiến trúc).
- [ ] R5.1: chạy lại `create` sau sập với cùng khoá do wrapper nút dẫn (workflow-engine:R4.5) không tạo bản ghi thứ
      hai; Bước không có chỗ nào tự dựng khoá (test kiến trúc).
- [ ] R5.2 (WN4): cấu hình bước có `run_as` → schema từ chối; cấu hình `update` có `owner_id` → schema từ chối; chủ
      thể chạy thiếu quyền → `permission_denied`.
- [ ] R5.5: một `create` ở `simulate` → `RecordsPort` (spy) nhận `run_mode` `simulate`; với `RecordService` thật không
      có dòng, sự kiện hay audit nào (custom-objects:R5.4).
- [ ] R5.5: Bước giao ở `simulate` → `RecordAssignPort` (spy) nhận `run_mode` `simulate`; với `AssignRecordService`
      thật người phụ trách không đổi, 0 audit, 0 outbox, 0 dòng `studio.assign_rotation` được ghi; cho Bước không chuyển
      `run_mode` → lần giao thật xảy ra, test đỏ.
- [ ] R5.5: bộ contract test của `RecordsPort` và `RecordAssignPort` chạy trên bản thật và trên bản giả của
      workflow-engine/03, cả hai xanh; sửa bản giả để lưu lệnh ghi nhận ở `simulate` → ca `simulate` đỏ trên bản giả.
- [ ] R5.1: ca phát lại của bộ contract test: gửi lại cùng khoá → kết quả lần đầu, không ghi lần hai, trên cả hai bản
      cài; sửa bản giả để ghi lần hai → ca đó đỏ trên bản giả.
- [ ] R5.1: một Bước `update` nêu `score` trên Lead có `score` và `status` → `RecordsPort` (spy) nhận lệnh chỉ mang
      `score`; ca PATCH của bộ contract test: hai lệnh sửa cùng một bản ghi, một nêu `score`, một nêu `status`, dưới hai
      khoá → bản ghi giữ cả hai giá trị trên cả hai bản cài; cho Bước gửi cả bản ghi đã đọc → giá trị của lệnh kia bị
      ghi đè, test đỏ.
- [ ] R5.1: ca khác tenant của bộ contract test: `update` hay `assign` với id bản ghi của công ty khác → `not_found`, bản
      ghi của công ty kia không đổi, trên cả hai bản cài.
- [ ] R5.4: "0901 234 567" và "+84901234567" tới cùng một Lead; số không chuẩn hóa được mà email trùng → cùng Lead; cùng
      tên khác số và khác email tạo hai Lead; hai Lead có sẵn cùng số → `upsert` sửa Lead cũ nhất, đầu ra
      `created: false`.
- [ ] R6.2: 100 lead cho 3 ứng viên → số nhận lệch tối đa 1; hai lượt đồng thời, cả hai là lần chạy đầu của Bước giao
      (bảng chưa có dòng), giao hai lead cho 3 ứng viên → hai người khác nhau; bỏ khóa advisory → cả hai cùng một người,
      test đỏ. Tài khoản dịch vụ thỏa R8.5 không bao giờ được chọn.
- [ ] R6.1 (WN16): một người không thỏa kiểm người nhận của record-access:R8.5 không bao giờ được chọn; gỡ kiểm quyền ứng
      viên → test đỏ. Chủ thể chạy không có tầm `assign` → Bước lỗi `assign_not_permitted`, không giao.
- [ ] R6.1: lead đã của người A (không phải chủ thể chạy) qua Bước giao với `reassign` `false` → vẫn của A, đầu ra
      `assigned: false`, 0 audit; A đã rời công ty → lead được giao theo vòng xoay. Bản ghi của một đối tượng khác
      `object` → `not_found`.
- [ ] R6.3 (WN16): không ứng viên nào hợp lệ → giao cho người dự phòng đã duyệt qua `RecordAssignPort`, với đúng một
      audit và một outbox `studio.record.assigned` do `AssignRecordService` ghi, actor là chủ thể chạy; Bước ghi thêm một
      audit hay gọi thẳng `studio.assign_record` → test đỏ.
- [ ] R6.4 (WN16): người dự phòng cũng không hợp lệ → Bước khai Khi lỗi `route` chạy làn lỗi với `no_assignee`, Bước
      khai `fail` làm lượt `failed`, bản ghi không có người phụ trách mới ở cả hai; Biểu thức `candidates` lỗi → Bước lỗi
      `expression_error`, người dự phòng không được giao; bỏ kiểm quyền của người dự phòng → test đỏ.
- [ ] R6.5: worker chết sau khi lần giao commit mà trước checkpoint, rồi lượt chạy lại Bước giao → bản ghi vẫn của người
      đã giao lần đầu, với đúng một audit và một outbox `studio.record.assigned`, và đầu ra `assigned: true` như lần đầu;
      worker chết sau khi vòng xoay commit mà trước lần giao → chạy lại chọn đúng người đó theo `last_key`; cho Bước
      không chuyển khoá hay dựng khoá khác → bản ghi sang người kế tiếp trong vòng xoay, test đỏ.
- [ ] R6.5: ca `RecordAssignPort` của bộ contract test: gửi lại cùng khoá → người đã giao lần đầu, không giao lần hai,
      trên bản giả và trên `AssignRecordService` thật; sửa bản giả để giao lại theo vòng xoay → ca đó đỏ trên bản giả.
- [ ] R6.2: `studio.assign_rotation`: `dw_app` gắn tenant A không đọc được dòng của tenant B, và chèn dòng mang
      `artifact_id` của tenant B → lỗi FK; `test_rls_coverage.py`, `test_privileges.py` và `test_offboarding_coverage.py`
      xanh với bảng mới.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_data_object_nodes.py packages/python/dw_studio/tests/workflows/test_assign_node.py packages/python/dw_studio/tests/workflows/test_records_port_contract.py && make test-integration` xanh.

## Nguồn

- custom-objects:R5.6, custom-objects:R8.9; `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`.
- record-access:R6.4, record-access:R8.1; `.claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md`.
- ADR-0112 (Accepted) quyết 6; spec: R2.1, R5.1, R5.5.
- workflow-engine:R4.5, workflow-engine:R4.7; `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`;
  spec: R5.1, R5.5 (bản giả của `RecordsPort` mà bộ contract test phủ, H-7), R6.5 (khoá chống lặp, V4.30).
- workflow-engine:R7.3 (lệnh sửa trong làn song song là PATCH theo trường); spec: R5.1 (V4.34).
- record-access:R8.4, record-access:R8.5 (tầm `assign` của người giao, kiểm người nhận), record-access/05 bước 6
  (`simulate`); spec: R5.5, R6.1.
- record-access:R1.3 (`dw_app` không UPDATE cột người phụ trách); spec: R5.2, R6.1.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: giả lập ghi bản ghi ở RecordService, R5.3 rút và R5.5 thay (D:custom-objects:R5.4~workflow-nodes:R5.3); người dự phòng là điểm gắn kind `principal` duyệt hai người, nhóm ở W2 (Q6), nên ticket chờ tenant-config/05.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: khoá chống lặp là của workflow-engine:R4.5; giao qua `AssignRecordService` (record-access/05), không qua `studio.assign_record`, không audit riêng.
- 2026-10-24 (agent): theo V4.24 của Đạt: làn lỗi chỉ có khi Khi lỗi là `route`, nên R6.4 nói Bước kết thúc với lỗi theo Khi lỗi của nó thay "đi Nhánh ra lỗi", và tiêu chí của nó thử cả `route` lẫn `fail`. Không thêm cạnh.
- 2026-10-25 (agent): lượt h: theo H-7, bộ contract test của `RecordsPort` khai cùng Protocol ở ticket này và chạy trên bản giả của workflow-engine/03 lẫn `RecordService` thật; thêm cạnh tới workflow-engine/03, ngoài bảng cạnh của lượt, vì hai ticket chưa có đường nào nối nhau nên bộ không chạy được trên bản giả khi ticket này đến trước (đã chạy g.py trên cây hiện tại cộng các cạnh của lượt: không vòng, marketing-pilot/03 vẫn ở độ sâu 15, ticket này vẫn ở độ sâu 14). Theo V4.30 (mục 10): Bước giao chuyển khoá của wrapper nút cho dịch vụ giao, để chạy lại không giao cho người kế tiếp (R6.5); dòng `Xong:` thêm `make test-integration` vì bộ contract và ca R6.5 cần PostgreSQL thật.
- 2026-10-26 (agent): lượt h, rà lại theo V4.34 của Đạt: workflow-engine:R7.3 (ngữ nghĩa thực thi, lệnh sửa trong làn song song là PATCH theo trường) dựa vào R5.1 của spec này, nên R5.1 nói lệnh sửa một bản ghi có sẵn của Bước chỉ mang các trường cấu hình của Bước nêu, bước 1 và bộ contract test thêm ca PATCH, và một tiêu chí mới của R5.1 có ca âm (gửi cả bản ghi đã đọc thì giá trị của lệnh kia bị ghi đè). Không thêm cạnh.
- 2026-10-26 (agent): lượt h, sau đợt 1: H-30, `RecordsPort` và `RecordAssignPort` khai ở workflow-engine/03 (người dùng đầu tiên, đứng trước workflow-nodes/04), workflow-nodes/04 chạy bộ contract test trên bản thật. Không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check cùng boundary walk; ticket
  nay có migration, `studio.assign_rotation`). Lượt đầu: 1 CRITICAL, 9 HIGH, đều sửa ở ticket này và spec (Quyết định
  4/11/2026):
    - CRITICAL: Bước giao không chuyển `run_mode` qua `RecordAssignPort`, nên một lượt `simulate` giao thật, ghi audit
      và outbox, trái ADR-0112 (Accepted) quyết 6 và ADR-0111 (Accepted). Câu trả lời đã có ở record-access/05 bước 6
      ("ở `simulate` không gọi hàm"); nay Bước chuyển nó, có tiêu chí và ca đột biến.
    - Chủ thể chạy phải có tầm `assign` (record-access:R8.4) và audit mang chủ thể chạy: chưa nói.
    - "Quyền làm người phụ trách" và "tầm giao" chưa định nghĩa: nay là kiểm người nhận của record-access:R8.5 trong
      workspace sở hữu, cùng hàm.
    - Quy tắc CEL chọn tầm chưa có hình hay hành vi khi lỗi: nay `candidates` là danh sách id, lỗi thì `expression_error`,
      không rơi xuống người dự phòng.
    - "Lâu nhất chưa nhận" đọc `owner_assigned_at`, cột mà không ticket nào tạo, qua một hàm SECURITY DEFINER không chủ:
      nay là bảng `studio.assign_rotation` của ticket này, khóa hàng, chạy lại theo `last_key`.
    - Bản ghi đã có người phụ trách (lead trùng sau `upsert`) bị xoay sang người khác: nay giữ người cũ trừ khi
      `reassign`.
    - `create`, `update`, `upsert` ghi được trường người phụ trách, đi vòng qua R6.1: nay schema từ chối.
    - Kiểm trùng: thứ tự khóa, số không chuẩn hóa được, và đây là cấu hình `match_on` của `upsert`.
    - Bộ contract test không có ca id bản ghi của công ty khác.
- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) Hai lượt đồng thời với cùng số điện thoại cùng không thấy bản ghi rồi cùng tạo: chặn thật là ràng buộc duy
      nhất trên trường của custom-objects, không phải Bước.
    - (b) Kết quả lưu theo khóa `wf:` (`studio.record_write_keys`, custom-objects/03) chứa giá trị bản ghi; hạn giữ và
      bên xóa là của custom-objects và compliance-pdpl.
    - (c) Dòng `studio.assign_rotation` của một người rời công ty còn lại tới khi quy trình bị xóa hay công ty
      offboard; người đó không còn là ứng viên nên dòng không được đọc.
    - (d) Lần giao lỗi sau khi vòng xoay đã ghi đẩy người được chọn lùi một lượt; chỉ lệch công bằng.
    - (e) Kiểm trùng chỉ thấy bản ghi chủ thể chạy đọc được; một Lead trùng ở workspace mà tài khoản dịch vụ không thấy
      thành Lead thứ hai. Bản ghi tạo ngoài quy trình với số chưa chuẩn hóa không khớp.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 10 câu, sửa theo khuyến nghị: khóa
  advisory cho lần chạy đầu của vòng xoay; giá trị chuẩn hóa được ghi vào trường; `object` trong cấu hình của Bước giao;
  phát lại theo khóa trước kiểm "đã có người phụ trách"; tầm giao ở `simulate` với bản ghi giả là workspace của lượt;
  tài khoản dịch vụ không là ứng viên; lần giao lỗi sau khi vòng xoay đã ghi; workspace của bản ghi tạo mới; hình đầu
  ra của bốn Bước bản ghi; nhiều bản ghi khớp thì sửa bản ghi cũ nhất. Người phụ trách đã rời công ty thì lead được giao
  lại. Không còn CRITICAL hay HIGH.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
