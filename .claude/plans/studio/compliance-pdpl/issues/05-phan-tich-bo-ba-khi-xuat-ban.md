# 05 — Phân tích bộ ba nguy hiểm và năng lực của quy trình khi gửi kiểm định

Status: ready-for-agent
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md
Area: studio
Yêu cầu: R2.6, R4.1, R4.2, R4.4, R4.5, R4.6, R4.7, R4.8, R5.5, CP6, CP12, CP14, CP15, CP21, CP26

## Mục tiêu

Khi gửi kiểm định một quy trình, một module thuần đọc nhãn năng lực của loại node và loại công cụ; một đường nối đầu
vào không tin cậy, dữ liệu riêng và tác động ra ngoài phải qua node phê duyệt; một Bước Quy trình con mang nhãn của
phiên bản con đã ghim, bắc cầu (V4.33); trường dữ liệu cá nhân không vào prompt trên tuyến ra nước ngoài; kết quả ghi
vào `studio.version_assessments` để lane `studio_gate` đọc (spec R2.6, R4; ADR-0125 (Accepted)). Luật agent và móc
phân tích của loại `agent` ở `.claude/plans/studio/compliance-pdpl/issues/07-phan-tich-nang-luc-agent.md` (V4.31).

## Việc cần làm

1. Module thuần `capability_analysis(definition, closure)` trả một kết quả Phân tích năng lực (một dòng
   `studio.version_assessments`) từ tài liệu được gửi kiểm định và bao đóng ghim lúc đó (phiên bản công cụ, phiên bản
   đối tượng, phiên bản con), không từ gì đọc lúc chạy. Nhãn `untrusted_source` (A), `private_data` (B),
   `external_effect` (C) theo ADR-0125 (Accepted) quyết 1, từ một bảng điều phối khóa theo loại node dựng ở composition
   root (đó là nhãn `NodeTypeSpec` của ADR-0112 (Accepted); `NodeTypeSpec` của
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:31` không thêm trường), mỗi mục là một hàm
   thuần (config của Bước, bao đóng) → tập nhãn:
    - mọi loại: C khi `side_effect_level` của `NodeTypeSpec` (`wflite/registry.py:38`, một chủ, không chép tay vào
      bảng) là `external` hay `critical`; từ vựng chỉ có `none`, `internal`, `external`, `critical`
      (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:25`);
    - `tool.call`: nhãn từ ba phân loại của phiên bản công cụ đã ghim (ADR-0116 (Accepted)): `output_trust`
      `untrusted` → A; `data_classification` `personal`, `sensitive` hay `secret` → B, và một giá trị ngoài tập đóng của
      ADR-0116 (Accepted) quyết 4 (kể cả `basic`) hay tập rỗng cũng → B (đóng khi lạ, failure-modes #7); `side_effect_level` `external`
      hay `critical` → C; thiếu một phân loại → 422 `tool_unclassified` (bước 3);
    - `http.request` (khi workflow-nodes đăng ký nó): A, vì phản hồi từ ngoài, cộng C theo mức của nó;
    - Bước đọc đối tượng (`data.*`): B khi phiên bản đối tượng đã ghim có một trường `pd_category` khác `none`
      (ADR-0106 (Accepted)), không B khi mọi trường là `none`; bao đóng thiếu phiên bản đối tượng → B (đóng khi thiếu);
    - trigger: A với mọi loại trigger trừ loại bảng đánh dấu nội bộ (`schedule`, `manual`), gồm endpoint Data Hub, sự
      kiện nhà cung cấp, tin nhắn đến và `trigger.work_item@1`; thêm B khi lược đồ đầu vào của trigger có một trường
      `pd_category` khác `none`, vì lead tới thẳng từ trigger mang dữ liệu cá nhân;
    - `ai.agent`: nhãn ở dòng `studio.version_assessments` của phiên bản agent đã ghim, đọc qua
      `VersionAssessmentLookup` của bước 8 như Bước Quy trình con; dòng của agent do ticket 07 ghi, nên tới đó Bước
      `ai.agent` mang cả ba nhãn (ADR-0125 (Accepted) quyết 2);
    - một loại không có mục, hay một loại lạ → cả ba nhãn (spec R4.1); một test so sổ loại của `NodeTypeRegistry` với
      bảng và đỏ khi một loại đã đăng ký thiếu mục, để "loại lạ" chỉ là lưới đóng chứ không phải đường thường.

    Tổ tiên tính trên IR gồm cả cạnh quay lui của một vòng lặp: mọi Bước trong thân một vòng là tổ tiên của mọi Bước
    trong thân đó, vì vòng sau thấy trạng thái của vòng trước. Phân tích chỉ chạy lúc gửi kiểm định, không ở lượt
    `simulate` của bản Nháp (tác động của lượt đó đã giả lập ở executor, tenant-config/03), và không ghi dòng nào cho
    bản Nháp. Chạy trên cùng `WorkflowIR` và module đồ thị `ir.py` (`reachable`, `dominators`) mà workflow-engine/01
    dựng; ticket này thêm `paths_to` vào chính `ir.py`, như workflow-engine/01 bước 2 để dành, không dựng module đồ thị thứ hai.
    Đăng ký nó vào bảng kiểm theo loại lúc gửi kiểm định của agent-lifecycle/03 (agent-lifecycle:R2.7) cho loại
    `workflow`.

2. Quy tắc quy trình (spec R4.2; ADR-0125 (Accepted) quyết 2): một Bước C cần người khi có một Bước mang A và một Bước
   mang B (một Bước mang nhiều nhãn tính cho mỗi nhãn nó mang) cùng là chính C hay tổ tiên của C trong IR, theo bất kỳ
   thứ tự nào, vì trạng thái của quy trình giữ dữ liệu đã đọc tới mọi Bước sau. Một node `human.approval` H gác C khi
   cả ba cùng đúng: H chi phối C; C nằm trong làn `approved` của H, không trong làn `rejected` hay `error_lane` của nó;
   và mọi Bước A, B là tổ tiên của C (khác chính C) cũng là tổ tiên của H, để người duyệt sau khi dữ liệu đã tới. Thiếu
   → gửi kiểm định trả 422 `trifecta_path_unapproved` kèm đường vi phạm (id các Bước A, B, C). Hai `human.approval` trên
   hai nhánh gộp lại trước C không gác C, vì không cái nào chi phối C (spec R4.2, "chỉ trên một nhánh → vẫn 422").
3. Công cụ mà một Bước `tool.call` của quy trình dùng thiếu một trong ba phân loại → 422 `tool_unclassified` (spec
   R4.4). Quy tắc agent (Mức tự chủ ≤ A2 khi mang cả ba nhãn) và móc của loại `agent` ở ticket 07.
4. Migration (id hex ngẫu nhiên) tạo `studio.version_assessments` (tín hiệu, đường vi phạm, kết luận, phiên bản bộ
   phân tích; RLS chỉ theo công ty, không cột `workspace_id`, nên cùng thay đổi thêm một dòng cho bảng vào danh sách bảng
   toàn tenant của `test_rls_coverage.py` với lý do "đánh giá đi theo phiên bản toàn tenant của nó"
   (studio-skeleton:R9.1)); UNIQUE `(tenant_id, version_id, definition_hash, analyser_version)`, ghi bằng
   `ON CONFLICT DO NOTHING`, nên gửi kiểm định lại cùng nội dung và cùng bộ phân tích không thêm dòng hay lỗi; FK ghép
   `(tenant_id, version_id)` tới `studio.artifact_versions (tenant_id, id)`, đích là
   `uq_artifact_versions_tenant_id_id` của tenant-config/02 (ticket này chờ nó), ON DELETE CASCADE với index
   `(tenant_id, version_id)`, nên một dòng không trỏ được tới phiên bản của công ty khác (spec R4.7) và lượt xóa
   phiên bản khi offboarding xóa luôn dòng đánh giá; `dw_app` SELECT, INSERT, không UPDATE, không DELETE, nên cùng thay
   đổi thêm một dòng `STUDIO_EXCLUSIONS` cho bảng với lý do "`dw_app` không DELETE; xóa khi offboarding theo FK CASCADE
   từ `studio.artifact_versions`" (spec R5.5; studio-skeleton:R4.1); ghi kết quả trong giao dịch gửi kiểm định, không
   thêm cột lên dòng phiên bản; lần gửi bị 422 lùi cả giao dịch nên không để lại dòng; kết quả đi trong payload phê
   duyệt phát hành (ADR-0120 (Accepted)); không cấu hình nào hạ sàn.
5. Kiểm R2.6 trong cùng phân tích (MP7): lớp lúc gửi kiểm định là `effective_route_class` của ticket 03 trên lớp của
   công ty và `route_class` của phiên bản (phiên bản là toàn tenant, workspace chỉ siết lúc nhận lượt). Khi lớp là
   `vn_only`, kiểm này không chạy: cổng của ticket 03 từ chối mọi tuyến `foreign` lúc chạy, và hồ sơ bị cấm cũng bị từ
   chối lúc gửi kiểm định theo ADR-0118 (Accepted). Khi lớp khác `vn_only`, một Bước `ai.llm` hay `ai.agent` mà một
   tuyến bất kỳ của hồ sơ model đã ghim (tuyến chính hay dự phòng) khai `data_location` khác `vn` hay không khai, và có
   một tổ tiên (hay chính nó) mang nhãn B của bước 1 → 422 `residency_refused` kèm đường. Ở W1 chưa có truy nguồn gốc
   trường (W2, ADR-0125 (Accepted) quyết 8), nên kiểm theo tổ tiên, không theo tham chiếu: một trường cá nhân tới
   prompt qua đầu ra của một Bước khác cũng bị từ chối.
6. Không tạo `configs/policies/studio_risk@1.0.0.yaml` ở W1: bên đọc duy nhất của nó là `suggested_tier`, cột W2
   (ADR-0125 (Accepted) quyết 6; dòng "Mức rủi ro AI" của Ngoài phạm vi), nên tệp đến cùng cột đó.
   Thân 422: một lỗi mỗi lần gửi, `details.reason_code` là kiểm hỏng đầu tiên theo thứ tự `tool_unclassified`,
   `residency_refused`, `trifecta_path_unapproved`, `details.paths` liệt kê mọi đường vi phạm của kiểm đó (id các Bước);
   theo vỏ của ADR-0108 (Accepted).
7. Case trong bộ eval bảo mật: workflow pilot bỏ node phê duyệt; đường `score → send` không qua `approve`. "Workflow
   pilot" của các tiêu chí là một fixture của ticket này cùng hình với quy trình của
   `.claude/plans/studio/marketing-pilot/issues/03-quy-trinh-tiep-nhan-lead.md` (trigger Data Hub mang trường cá nhân,
   chấm điểm `ai.llm`, phê duyệt, `tool.call email.send`).
8. Bước Quy trình con (spec R4.8; V4.33): bảng điều phối nhãn có một mục cho `flow.subworkflow@1` mà nhãn là hợp các
   nhãn ở dòng `studio.version_assessments` của phiên bản con mà bao đóng của lần gửi kiểm định ghim
   (ADR-0109 (Accepted) quyết 4, 9), đọc qua một Protocol hẹp `VersionAssessmentLookup` mà module khai và composition
   root đáp ứng từ bảng của bước 4, dưới RLS của công ty gửi kiểm định, nên module vẫn thuần; dòng của phiên bản con đã
   gồm nhãn của phiên bản con của nó, nên phép hợp bắc cầu mà không duyệt lại cây. Không có dòng cho
   `(version_id, definition_hash)` của phiên bản con với phiên bản bộ phân tích hiện hành của loại phiên bản đó (gồm id phiên bản của công ty
   khác, mà RLS không trả) → cả ba nhãn; lookup ném lỗi (mất kết nối, hết giờ) → gửi kiểm định thất bại, không ghi
   dòng, không bao giờ coi là nhãn rỗng. Tới khi `flow.subworkflow@1` có trong sổ loại (workflow-nodes/08, bậc B), một
   Bước loại đó là loại chưa biết và mang cả ba nhãn theo R4.1, nên ticket này không chờ workflow-nodes/08 hay
   workflow-engine/09.
9. "Overlay công ty" của R4.5 ở W1 là bản của chính công ty cho một quy trình của gói cấu hình (ADR-0100 (Accepted)), một phiên
   bản đi qua cùng cửa gửi kiểm định, nên phân tích chạy trên chính tài liệu đó; overlay của đặc tả công cụ nền tảng
   (kind `tool_spec` của ADR-0110 (Accepted) quyết 3) là W2, và khi có thì một overlay đổi phân loại của công cụ đã ghim
   phải chạy lại phân tích (Comments, cho W2).

## Tiêu chí chấp nhận

- [ ] R4.1: node loại lạ hay công cụ loại lạ → `capability_analysis` gán cả ba nhãn; nhãn đọc từ bảng điều
      phối ở composition root, không từ nhánh trong module; một loại đã đăng ký trong `NodeTypeRegistry` mà thiếu mục
      trong bảng → test so sổ đỏ, nêu tên loại.
- [ ] R4.1: `tool.call` dùng công cụ `output_trust: untrusted`, `data_classification: personal`,
      `side_effect_level: external` → A, B, C; cùng công cụ với `side_effect_level: none` → không C; Bước đọc đối tượng
      có một trường `basic` → B, đối tượng mọi trường `none` → không B.
- [ ] R4.2 (CP12): bỏ node phê duyệt khỏi workflow pilot → gửi kiểm định 422 `trifecta_path_unapproved` nêu
      đường; đường chấm điểm tới gửi tin không qua node `approve` → 422 nêu đường; node phê duyệt chỉ trên một
      nhánh → vẫn 422.
- [ ] R4.2 (CP12): `human.approval` là Bước đầu, rồi đọc web (A), đọc lead (B), gửi email (C) → 422; Bước gửi email
      trong làn `rejected` của node phê duyệt đứng sau A và B → 422; đọc lead trước, đọc web sau, rồi gửi, không phê duyệt
      → 422; A và B trên hai nhánh song song gộp trước C → 422; A, B, rồi phê duyệt, gửi trong làn `approved` → qua; bỏ
      điều kiện "A, B là tổ tiên của H" → ca phê duyệt đầu tiên qua, test đỏ.
- [ ] R4.4 (CP14): quy trình có Bước `tool.call` dùng công cụ thiếu một trong ba phân loại → 422 `tool_unclassified`;
      gỡ kiểm → test đỏ.
- [ ] R4.5 (CP15): bản của công ty cho quy trình bộ ba của gói bỏ node phê duyệt → gửi kiểm định 422
      `trifecta_path_unapproved`, phiên bản vẫn Nháp.
- [ ] R4.8 (CP26): quy trình cha có `untrusted_source` và `private_data`, gọi một quy trình con mà dòng đánh giá mang
      `external_effect`, không node phê duyệt nào chi phối Bước Quy trình con → 422 `trifecta_path_unapproved` nêu
      đường qua Bước đó; con không tác động mà cháu có (dòng của con đã gồm nhãn của cháu) → vẫn 422; bản giả của
      `VersionAssessmentLookup` không trả dòng → Bước mang cả ba nhãn; trước khi loại có trong sổ → mang cả ba nhãn
      theo R4.1; gán nhãn rỗng thay hợp nhãn của con → test đỏ.
- [ ] R4.8 (CP26): Bước Quy trình con của công ty B trỏ tới id một phiên bản con của công ty A có dòng đánh giá →
      lookup dưới RLS của B không trả dòng, Bước mang cả ba nhãn; dòng của phiên bản con ghi bởi phiên bản bộ phân tích
      khác → cả ba nhãn; lookup ném lỗi → gửi kiểm định thất bại, không dòng `studio.version_assessments` nào.
- [ ] R4.6: gửi kiểm định một quy trình hợp lệ → đúng một dòng `studio.version_assessments` cho Mã băm định
      nghĩa của phiên bản, ghi trong cùng giao dịch; rollback giao dịch gửi kiểm định → không dòng nào; gửi kiểm định
      lại cùng nội dung → vẫn một dòng, không lỗi; `dw_app` UPDATE một dòng → `permission denied`.
- [ ] R4.7 (CP21): chèn một dòng `studio.version_assessments` mang `tenant_id` của công ty A và `version_id` của một
      phiên bản công ty B → SQLSTATE 23503, không dòng nào; đổi FK ghép về FK một cột `version_id` → test đỏ.
- [ ] R4.6: test phủ RLS (studio-skeleton:R9.1) xanh với dòng của `studio.version_assessments` trong danh sách bảng
      toàn tenant, bỏ dòng đó → test phủ đỏ, nêu tên bảng.
- [ ] R5.5: công ty `offboarding` có dòng `studio.version_assessments` → lane `offboarding` xuất mỗi dòng một lần,
      rồi lượt xóa `studio.artifact_versions` của công ty xóa hết các dòng đó qua FK CASCADE, dòng của công ty khác
      còn nguyên; test phủ offboarding (studio-skeleton:R4.1) xanh với dòng `STUDIO_EXCLUSIONS` của bảng, bỏ dòng đó
      → test phủ đỏ, nêu tên bảng; đổi FK sang `RESTRICT` → test đỏ.
- [ ] R2.6 (CP6): công ty `cross_border_full`, tuyến model `foreign`, gắn `full_name` vào prompt → gửi kiểm định 422
      `residency_refused` kèm đường, phiên bản vẫn Nháp; trường đó tới prompt qua đầu ra của một Bước khác → vẫn 422;
      cùng quy trình trên tuyến khai `vn` → qua; gỡ kiểm → test đỏ.
- [ ] R4.1: trigger Data Hub có trường `basic` → A và B; Bước trong thân vòng `[gửi C, đọc web A, đọc lead B]` không phê
      duyệt → 422 (tổ tiên qua cạnh quay lui); bỏ cạnh quay lui khỏi phép tính tổ tiên → test đỏ; Bước loại có
      `side_effect_level: external` trong `NodeTypeSpec` mà không phải `tool.call` → C.
- [ ] R2.6 (CP6): hồ sơ có tuyến chính `vn` và tuyến dự phòng `foreign` dưới `cross_border_full`, có tổ tiên mang B →
      422; bao đóng thiếu `data_location` của tuyến → coi là `foreign`, 422.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`; spec: R4.3 (thang tự chủ, hai
  sàn `critical` và `approval_policy: always`).
- ADR-0125 (Accepted) quyết 1, 2, 3, 5.
- tenant-config:R2.18 (FK ghép tới `uq_artifact_versions_tenant_id_id`); spec: R4.7.
- ADR-0109 (Accepted) quyết 4, 9 (bao đóng ghim phiên bản con); workflow-nodes:R13.1; spec: R4.8.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 08 và phần phân tích năng lực của B10a-lifecycle
  agent-lifecycle 08. Phân tích chạy khi gửi kiểm định (submit), kết quả đi vào phê duyệt phát hành; bản
  ghi tầng rủi ro AI `studio.version_assessments`, tờ giải thích và taint động là W2.
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026 (B:agent-lifecycle:R6.1~compliance-pdpl:R4.2 (a),
  ADR-0125 (Accepted)): tiêu đề "khi gửi kiểm định"; kết quả ghi vào `studio.version_assessments` do ticket
  này tạo (cột tầng rủi ro là W2), không cột `capability_report`; tên theo glossary; đăng ký qua bảng kiểm
  theo loại của agent-lifecycle/03; kiểm R2.6 chuyển từ ticket 03 về đây nên chờ ticket 03.
- 2026-10-24 (agent): theo dòng tạm cùng ngày của spec (H:compliance-pdpl:spec\~studio-skeleton:R4.1):
  `studio.version_assessments` có FK `version_id` tới `studio.artifact_versions` ON DELETE CASCADE, nên offboarding
  xóa nó cùng phiên bản (bước 4; spec R5.5); `dw_app` vẫn chỉ SELECT, INSERT.
- 2026-10-24 (agent): kiểm sau lượt sửa: vì `dw_app` chỉ SELECT, INSERT, bảng nằm ngoài `_CATALOG_PURGEABLE` của
  adapter offboarding, nên test phủ của studio-skeleton:R4.1 đỏ nếu thiếu dòng `STUDIO_EXCLUSIONS`; bước 4 nay thêm
  dòng đó với cascade từ `studio.artifact_versions` làm cách xóa, theo bước 7 của studio-skeleton/01 (như
  `platform.service_principals` của org-and-principals), và tiêu chí R5.5 thử nó; câu "không cần dòng
  `STUDIO_EXCLUSIONS`" bỏ.
- 2026-10-24 (agent): lượt sửa thứ hai của vòng 4, theo dòng tạm của spec về `studio.version_assessments`: FK thành
  FK ghép `(tenant_id, version_id)` tới `uq_artifact_versions_tenant_id_id` mà tenant-config/02 thêm, để chặn tham
  chiếu chéo công ty, nên ticket này chờ tenant-config/02; bảng không có `workspace_id` nên thêm một dòng lý do vào
  danh sách bảng toàn tenant của `test_rls_coverage.py` (`CLAUDE.md` mục 'Tenancy and authorization'); bước 4 làm
  cả hai, tiêu chí R4.7 (CP21) thử FK ghép (spec R4.7, theo tenant-config:R2.18) và tiêu chí R4.6 thứ hai thử dòng
  danh sách.
- 2026-10-25 (agent): lượt h, theo V4.31 của Đạt (bảng ticket mới và bảng cạnh của lượt): luật agent (bước 3 cũ) và móc
  phân tích của loại `agent` tách sang `.claude/plans/studio/compliance-pdpl/issues/07-phan-tich-nang-luc-agent.md`,
  R4.3 (CP13) dời theo, R4.4 và R4.5 giữ phần quy trình ở đây; gỡ Blocked by agent-builder/02. Theo V4.33: bước 8 cho
  Bước `flow.subworkflow@1` mang nhãn của phiên bản con đã ghim, bắc cầu, và loại chưa biết mang cả ba nhãn tới khi
  loại có trong sổ (spec R4.8, CP26); không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và ranh giới, vì ticket thêm
  migration). CRITICAL 1: `VersionAssessmentLookup` đọc dòng đánh giá của phiên bản con mà không có test âm đọc chéo
  tenant (`CLAUDE.md` mục 'Tenancy and authorization'); sửa: lookup dưới RLS của công ty gửi kiểm định, tiêu chí R4.8
  thứ hai. Nếu sai thì: lookup lọc thêm `tenant_id` của ngữ cảnh trong câu truy vấn, cùng test.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 1-3 (nhãn): bảng chỉ nói "theo loại node"; ADR-0125 (Accepted)
  quyết 1 đã trả lời: `tool.call` theo ba phân loại của phiên bản công cụ, đọc đối tượng theo `pd_category`, trigger ngoài
  là A; `ai.agent` theo dòng của agent đã ghim, cả ba tới ticket 07; test so sổ loại với bảng (bước 1). Nếu sai thì:
  nhãn theo loại, `tool.call` mang cả ba.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 4-5 (đường và vị trí phê duyệt): "chi phối" để lọt phê duyệt đứng
  trước dữ liệu, node tác động trong làn `rejected`, và thứ tự B rồi A; sửa: luật ở bước 2, spec R4.2,
  ADR-0125 (Accepted) Amendments 2026-11-04, năm ca âm ở tiêu chí R4.2 thứ hai. Nếu sai thì: chỉ phép chi phối, hai ca kia ghi
  là rủi ro.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 6-7 (R2.6): "đường đưa giá trị vào prompt" không định nghĩa khi
  truy nguồn gốc là W2, và lớp lúc gửi kiểm định của một phiên bản toàn tenant không nói; sửa: theo tổ tiên, lớp của công
  ty và phiên bản, không chạy dưới `vn_only` (bước 5, spec R2.6). Nếu sai thì: chỉ tham chiếu thẳng tới trường trong
  prompt, và W2 thay bằng truy nguồn gốc.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 8: gửi kiểm định lại cùng nội dung đụng khóa của bảng, và dòng của
  bộ phân tích cũ được tin; sửa: UNIQUE có `analyser_version`, `ON CONFLICT DO NOTHING`, dòng của phiên bản bộ phân
  tích khác đọc là không có (bước 4, 8). Nếu sai thì: một dòng mỗi `(version_id, definition_hash)`, bộ phân tích mới
  thì phân tích lại khi đọc.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (không CRITICAL mới, 4 HIGH, đã sửa): nhãn C
  của mọi loại đọc `side_effect_level` của `NodeTypeSpec`, một chủ; từ vựng mức chỉ có bốn giá trị, không
  `external_idempotent`; trigger mang dữ liệu cá nhân mang B; tổ tiên tính cả cạnh quay lui của vòng lặp. Thêm: R2.6
  xét mọi tuyến của hồ sơ và mọi tổ tiên mang B; thiếu dữ liệu trong bao đóng thì đóng; thân 422 một mã; không tạo
  `studio_risk@1.0.0.yaml` ở W1 vì bên đọc là cột W2; phân tích không chạy ở lượt `simulate`. Nếu sai thì: từng mục quay
  về bản trước trong lịch sử git.
- 2026-11-04 (agent): MEDIUM, để người dựng: (a) `dw_app` INSERT được một dòng "đạt" ngoài giao dịch gửi kiểm định;
  lane `studio_gate` chỉ đọc làm chốt chặn; một trigger kiểm phiên bản đang ở bước niêm phong sẽ đóng nó; (b) Bước Quy
  trình con mang C của con dù con đã tự gác C (spec R4.8 bảo thủ), nên quy trình cha vẫn cần phê duyệt riêng; xét lại
  ở W2; (e) case eval của bước 7 chưa có tiêu chí hay grader riêng, chạy ở eval smoke; (c) khi overlay của đặc tả công cụ có ở W2 (bước 9), phân tích phải chạy lại khi phân loại của công cụ đã ghim
  đổi; (d) phân tích lấy lớp công ty lúc gửi kiểm định; công ty nới lớp sau đó (W2) cần phân tích lại.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `checking-plan-consistency` của vùng studio (B:compliance-pdpl/05~tools-and-skills/03, HIGH): giá trị `data_classification` ngoài tập đóng cho nhãn B, không bỏ qua; ticket này là bên đọc của trường mà field-security/01 từng định gỡ (ADR-0106 (Accepted) bổ sung 4/11/2026 giữ trường). Nếu sai thì: giá trị lạ làm gửi kiểm định trả 422 `tool_unclassified`.
