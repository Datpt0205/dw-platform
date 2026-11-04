# 01 — Từ vựng loại dữ liệu cá nhân một chủ

Status: resolved (2026-11-02, main)
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, CP1

## Mục tiêu

Một module kernel sở hữu từ vựng `pd_category`, `sensitive_type` và Trường định danh chủ thể; mọi bảng
định nghĩa trường đọc từ đó, và tạo trường thiếu loại bị từ chối (spec R1).

## Việc cần làm

1. `dw_kernel.personal_data` (thuần stdlib): `PdCategory` (`none`, `basic`, `sensitive`); `SensitiveType`
   theo Nghị định 356 Điều 4.1 (danh sách giữ một chỗ); `SubjectIdentifierKind` (email, phone,
   national_id, zalo_user_id, facebook_psid, tax_code, bank_account); `requires_explicit_grant(category)`.
   `SensitiveType` chép từ văn bản tiếng Việt chính thức của Nghị định 356/2025/NĐ-CP Điều 4 khoản 1 (Công báo
   hay Cơ sở dữ liệu quốc gia về văn bản pháp luật), không từ bản dịch tiếng Anh không chính thức mà
   `.claude/plans/studio/discovery/research.md:216` dẫn: đúng một giá trị cho mỗi điểm có chữ cái
   của khoản đó, tên `snake_case` tiếng Anh ngắn, mỗi thành viên mang chữ cái của điểm; không có giá trị gom
   `other`. Docstring của module ghi nguồn, ngày chép và số điểm; test đỏ khi số thành viên khác số đó.
2. JSON Schema `contracts/jsonschema/pd_classification.json` sinh ra từ module và `--check` trong CI: thêm vào
   `scripts/generate_contracts.py`, mà CI đã chạy `--check` (`.github/workflows/ci.yml:29`). Lược đồ mang ba
   enum và không đặt `pd_category` vào `required`, để thiếu loại là lỗi của helper ở bước 5, không phải `missing`
   của trình kiểm lược đồ.
3. Bảng nhãn tiếng Việt `apps/web/lib/pd-labels.ts`; test đỏ khi một giá trị `pd_category` hay
   `sensitive_type` thiếu nhãn. Test đọc enum từ `contracts/jsonschema/pd_classification.json` sinh ra, không
   từ một danh sách chép tay trong test.
4. Helper test catalog `assert_field_tables_classified(conn, tables)` để custom-objects, workflow-triggers và
   tools-and-skills dùng: mỗi bảng định nghĩa trường có cột `pd_category` (text NOT NULL), `sensitive_type` và
   `subject_identifier` (text NULL), và ràng buộc CHECK bằng đúng enum của `dw_kernel.personal_data`. Helper ở
   `dw_platform.testing.personal_data` vì `dw_kernel` không có phụ thuộc
   (`packages/python/dw_kernel/pyproject.toml:6`); nó đọc `pg_constraint` theo mẫu
   `packages/python/dw_memory/tests/integration/test_fixed_set_checks_db.py:130-157`. Bốn CHECK theo tên
   `NAMING_CONVENTION`: `ck_<bảng>_pd_category`, `ck_<bảng>_sensitive_type`, `ck_<bảng>_subject_identifier` (tập
   giá trị so với enum) và `ck_<bảng>_pd_sensitive_type`, mà định nghĩa phải bằng định nghĩa Postgres in ra cho
   biểu thức `SENSITIVE_TYPE_PAIRING_SQL` của kernel, `(pd_category = 'sensitive') = (sensitive_type IS NOT NULL)`,
   dựng trên một bảng tạm trong cùng kết nối. Migration của chủ bảng viết CHECK bằng chữ (không migration nào
   import một gói), helper là lưới bắt lệch.
5. Mã lỗi `pd_category_required`, `sensitive_type_required`, `sensitive_type_not_allowed` và helper validate
   thuần cho các spec chủ bảng: `classification_problems(fields)` nhận mỗi trường cùng con trỏ JSON của nó và trả
   danh sách `ClassificationProblem(code, pointer)` theo mẫu `QueryProblem`
   (`packages/python/dw_kernel/src/dw_kernel/filters.py:125-136`): thiếu `pd_category` →
   `pd_category_required` với con trỏ của trường; `sensitive` thiếu `sensitive_type` → `sensitive_type_required`
   với con trỏ của trường; `basic` hay `none` mang `sensitive_type` → `sensitive_type_not_allowed` với con trỏ
   `<trường>/sensitive_type`; mọi trường được kiểm, không dừng ở lỗi đầu. Chủ bảng gộp các vấn đề vào 422
   `validation_failed` với `errors[]` (app-standards:R1.3), không ở `details.reason_code`, và giữ `pd_category`
   không bắt buộc trong lược đồ đầu vào của mình để lỗi là của helper (spec chủ bảng thực thi điểm chèn:
   custom-objects:R2.2, workflow-triggers:R4.1; lát này cấp mã và helper).

## Tiêu chí chấp nhận

- [x] R1.1 (CP1): `classification_problems` trên ba trường, trường thứ hai (`/fields/1`) không có `pd_category`
      → đúng một vấn đề, `pd_category_required` với con trỏ `/fields/1`; hai trường có loại → không vấn đề nào.
      Nửa HTTP (422 `validation_failed`, `errors[].code`, không ở `details.reason_code`, không tạo trường) là tiêu
      chí của chủ bảng: custom-objects:R2.2 và workflow-triggers:R4.1.
- [x] R1.2 (CP1): `assert_field_tables_classified` trên một bảng tạm có ba cột và bốn CHECK đúng mẫu ở bước 4 →
      qua.
- [x] R1.3 (CP1): cùng bảng tạm với CHECK `pd_category` thêm một giá trị ngoài enum kernel, thiếu một giá trị,
      thiếu cột `subject_identifier` hay thiếu CHECK `sensitive_type` → helper đỏ, nêu tên bảng và ràng buộc; xóa
      nhãn của một giá trị `pd_category` hay `sensitive_type` khỏi `pd-labels.ts` → test nhãn đỏ.
- [x] R1.4: bảng tạm thiếu `ck_<bảng>_pd_sensitive_type`, hay mang một biểu thức khác (chỉ
      `sensitive_type IS NOT NULL`) → helper đỏ; INSERT vào bảng tạm đúng mẫu một dòng `sensitive` không
      `sensitive_type`, hay một dòng `basic` có `sensitive_type` → IntegrityError.
- [x] R1.5: `classification_problems` trả `sensitive_type_required` cho trường `sensitive` không có
      `sensitive_type` (con trỏ của trường) và `sensitive_type_not_allowed` cho trường `basic` hay `none` có
      `sensitive_type` (con trỏ `<trường>/sensitive_type`), cả hai trong cùng một lần gọi.
- [x] R1.4: `SensitiveType` có đúng số thành viên bằng số điểm docstring ghi; `pd_classification.json` sửa tay một enum
      → `uv run python scripts/generate_contracts.py --check` đỏ.
- [ ] Xong: `make ci && make test-integration && pnpm -C apps/web test` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R1.1 (`data_classification`
  khai mà không đọc, thay bằng `pd_category` theo thuộc tính).
- ADR-0106 (Accepted) quyết 1.

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 01. field-security, custom-objects và Data Hub đọc từ
  đây; field-security sở hữu chế độ `Mở`/`Bảo vệ` và mặc định bảo vệ.
- 2026-10-24 (agent): theo dòng tạm cùng ngày của spec, `pd_category_required` là một `errors[].code` của 422
  `validation_failed` có con trỏ tới trường (app-standards:R1.3), không phải `details.reason_code`, cùng hình với
  custom-objects:R2.2 và workflow-triggers:R4.1 (bước 5, tiêu chí R1.1).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness`, chỉ kiểm người dựng (ticket không thêm
  migration hay route; không đi ranh giới). HIGH 1: tiêu chí R1.1, R1.2, R1.4 nhắm một route và một bảng định nghĩa
  trường chưa có ở `1aa6ea7` (không có schema `studio` trong `db/migrations/versions`), nên chỉ ticket khác làm chúng
  đúng được; sửa: tiêu chí kiểm chính helper trên một bảng tạm và trên danh sách trường, nửa HTTP ở custom-objects:R2.2
  và workflow-triggers:R4.1; test nhãn đọc JSON Schema sinh ra; Xong thêm `make test-integration` và
  `pnpm -C apps/web test`, vì `make ci` không chạy vitest của web (`Makefile:170`). Nếu sai thì: ticket chờ
  custom-objects/02 và kiểm trên `studio.field_defs`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 2: R1.4 không nói ai từ chối và bằng mã nào; sửa: CHECK ghép
  `ck_<bảng>_pd_sensitive_type` mà helper catalog so khớp, cộng R1.5 mới của spec với `sensitive_type_required` và
  `sensitive_type_not_allowed` (bước 4, 5). Nếu sai thì: một mã `sensitive_type_invalid`, CHECK giữ nguyên.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 3: không chỗ nào trong repo liệt kê giá trị của `SensitiveType`,
  mà chúng vào CHECK của bảng ở các context khác; sửa: chép từ văn bản chính thức Điều 4 khoản 1, một giá trị mỗi
  điểm, test đếm (bước 1). Nếu sai thì: đổi tên hay thêm giá trị bằng migration ở mỗi bảng chủ khi dữ liệu còn giả lập.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 4: hợp đồng helper validate và nơi đặt helper catalog bỏ ngỏ;
  một trường Pydantic bắt buộc trả `missing` chứ không `pd_category_required`
  (`apps/api/src/dw_api/exception_handlers.py:58-78`, `:145-152`), và `dw_kernel` không có phụ thuộc để đọc catalog;
  sửa: `classification_problems` trả `ClassificationProblem(code, pointer)`, `pd_category` không bắt buộc trong lược
  đồ của chủ bảng và trong `pd_classification.json`, helper catalog ở `dw_platform.testing.personal_data`, sinh lược
  đồ trong `scripts/generate_contracts.py` (bước 2, 4, 5). Nếu sai thì: một exception kernel cộng một handler ở
  `exception_handlers.py` như `QueryError` (`:115-134`), helper catalog ở gói testing khác.
- 2026-11-02 (agent): MEDIUM, chưa sửa, cho người dựng: (a) neo `contracts.py:167` ở Nguồn và ở Hiện trạng của spec
  nay là `contracts.py:201` (`data_classification`), `tool_specs.py:54` là `:55`; ticket không gỡ
  `ToolDefinition.data_classification` mà ADR-0106 (Accepted) quyết 1 nói `pd_category` theo thuộc tính thay
  thế; việc gỡ là của field-security/01 (Nguồn của nó, R2.1); (b) `requires_explicit_grant(category)` chưa có bên
  đọc nào được nêu (grep `.claude/plans`, `docs`: không spec nào dẫn), `failure-modes.md` #1: gắn bên đọc là
  field-security hay bỏ; (c) `subject_identifier` trên trường
  `none` không có luật (một định danh chủ thể là dữ liệu cá nhân), đề xuất từ chối như R1.5; (d) `subject_identifier`
  chưa có bên đọc ở W1 (yêu cầu chủ thể là W2).
- 2026-11-02 (agent): cho `checking-plan-consistency`: R3.12 và CP25 của spec vẫn nói ticket 04 đăng ký Sàn gửi tin
  vào sổ bước, trong khi bước sàn đã đăng ký ở executor (ticket 08 resolved); ticket này không dẫn hai mục đó nên chưa
  sửa. `check_plans` còn neo hỏng ở ticket 06:93 (`retention@1.7.0.yaml`) và cảnh báo va chạm 08 với 04, 06.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): nguồn của `SensitiveType`: Cơ sở dữ liệu quốc gia về văn bản pháp
  luật (`vbpl.moj.gov.vn/TW/Lists/vbpq/Attachments/187276/ND.356.2025.doc`) không phân giải được tên miền từ máy này
  (ENOTFOUND), Công báo cũng không đọc được; danh sách chép từ toàn văn tiếng Việt của luatvietnam.vn, đối chiếu với
  trang phổ biến pháp luật `pbgdpl.cantho.gov.vn` (cùng 12 điểm a, b, c, d, đ, e, g, h, i, k, l, m). Spec và
  research.md không giữ danh sách tiếng Việt nào để dùng thay. Ticket 02 (luật sư) xác nhận danh sách trước khi dữ liệu
  thật vào. Nếu sai thì: đổi tên hay thêm giá trị ở `dw_kernel.personal_data`, sinh lại lược đồ và nhãn, và migration ở
  mỗi bảng chủ khi dữ liệu còn giả lập (YC89).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): MEDIUM (b): bỏ `requires_explicit_grant(category)`: không bên đọc nào
  (`failure-modes.md` #1), và mặc định `secured` của field-security là trigger trên `pd_category <> 'none'`
  (field-security spec, Dữ liệu), không gọi Python. Nếu sai thì: thêm lại một hàm một dòng cùng thay đổi có bên đọc nó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): MEDIUM (c): trường `Không` mang `subject_identifier` bị từ chối ở cả hai
  tầng: mã `subject_identifier_not_allowed` (con trỏ `<trường>/subject_identifier`) và CHECK thứ năm
  `ck_<bảng>_pd_subject_identifier` bằng `SUBJECT_IDENTIFIER_PAIRING_SQL`, mà helper catalog so khớp; spec ghi ở Dữ liệu,
  API và nhật ký. custom-objects/02, workflow-triggers và tools-and-skills viết năm CHECK, không bốn; helper đỏ nếu thiếu.
  Nếu sai thì: gỡ mã và CHECK, helper về bốn CHECK.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): helper catalog kiểm cả hình CHECK tập giá trị, không chỉ tập chữ: định
  nghĩa phải bằng định nghĩa Postgres in cho `<cột> IN (...)` trên bảng tạm tham chiếu (thứ tự giá trị tùy ý), nên
  `... OR true` cũng đỏ; cột phải `text` đúng NOT NULL/NULL; danh sách bảng rỗng bị từ chối. `classification_problems`
  nhận `ClassifiedField` (Protocol ba thuộc tính có kiểu enum), nên mô hình đầu vào của chủ bảng dùng thẳng; giá trị ngoài
  enum là lỗi lược đồ của chủ bảng. Nếu sai thì: nhận `Mapping` thô và thêm một mã cho giá trị lạ.
- 2026-11-02 (agent): MEDIUM (a) và (d) không đổi: gỡ `ToolDefinition.data_classification` là của field-security/01;
  bên đọc `subject_identifier` là yêu cầu chủ thể dữ liệu (W2), cột vẫn có vì ADR-0106 (Accepted) quyết 1 đòi. Thêm
  `contracts/jsonschema/` vào `.prettierignore` (bộ sinh sở hữu định dạng, như `openapi.json`); `generate_contracts.py`
  ghi LF.
- 2026-11-02 (agent): resolved. Dựng: `dw_kernel.personal_data` (ba enum, `SensitiveType` 12 thành viên mang chữ của
  điểm, hai biểu thức ghép, `ClassificationCode`, `ClassificationProblem`, `classification_problems`);
  `dw_platform.testing.personal_data.assert_field_tables_classified`; `scripts/generate_contracts.py` sinh và `--check`
  `contracts/jsonschema/pd_classification.json` (không `required`); `apps/web/lib/pd-labels.ts`. Test: kernel unit 8
  (`dw_kernel` + `dw_platform` unit: 415 qua), contract 4 (`apps/api/tests/contract` cùng hai test unit dùng
  `generate_contracts`: 43 qua), integration 16 (bảng tạm, không migration), web 3 (vitest cả app 141/141), `tsc`,
  ruff, format, mypy (557 tệp), lint-imports (7 giữ), verify_invariants xanh. `verify_architecture.py` đỏ vì `referencing`
  thiếu trong `IMPORT_TO_DIST` (`json_schema.py`, có từ `0f1943a`, không của ticket này). Mutation: 16 viết ở
  `mutations/01.yaml`, chưa chạy (cuối đợt); xóa một nhãn đã thử tay, test nhãn đỏ. `reviewing-feature-security` đã đọc:
  không route, bảng, cache, công cụ hay ghi audit (ranh giới 1-5 không áp); ranh giới 6: bảng tham chiếu tạm xóa trong
  `finally`, mã lạ đọc "Loại chưa biết", không "Không"; `detail` không mang giá trị. `Xong` để đóng đợt.
