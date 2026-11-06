# 06 — Phát hành đối tượng qua vòng đời phiên bản: chỉ siết một người, nới qua người thứ hai

Status: resolved
Blocked by: 02, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md
Area: studio
Yêu cầu: R1.2, R1.3, R1.7, R1.8, R2.4, CO3, CO6, CO23

## Mục tiêu

Quản trị viên công ty phát hành một phiên bản `dw.object/v1` qua lệnh Gửi kiểm định của agent-lifecycle: phiên bản chỉ
siết lên Đang dùng bởi một người có audit, kể cả khi công ty Đóng băng (R1.7), mọi phiên bản khác qua Chờ duyệt và một
người thứ hai (R1.2), và chỉ người giữ `studio.objects.manage` gửi được (R1.3). Ticket 02 dựng loại `object`, bộ so
sánh chỉ siết (R1.8) và móc phát hành trong mục `ArtifactKindRegistry` của loại; ticket này nối loại đó vào route gửi,
máy giai đoạn, phê duyệt `studio.publish.object` và handler của agent-lifecycle, nơi agent-lifecycle gọi móc của mục
đăng ký (ADR-0120 (Accepted) mục 1, 2; ADR-0109 (Accepted) quyết 1). Đường này tách khỏi ticket 02 để các ticket bản
ghi, quyền và bảo mật trường chờ ticket 02 mà không phải chờ Cổng chất lượng của agent-lifecycle/04 (Quyết định
24/10/2026 của spec).

## Việc cần làm

1. Nối loại `object` vào lệnh Gửi kiểm định `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit`
   của agent-lifecycle/03 qua mục `ArtifactKindRegistry` mà ticket 02 đăng ký: khóa gửi `studio.objects.manage`
   (`tenant-config:R2.15`), bộ so sánh chỉ siết mà `LifecycleService` gọi để ghi `tighten_only` và
   `compared_live_hash` lên dòng phiên bản (`agent-lifecycle:R2.8`), và móc phát hành `MetadataService.apply`; `check_against_live` của ticket 02 vào bảng kiểm theo loại lúc gửi (`agent-lifecycle:R2.7`), với
   tài liệu của phiên bản Đang dùng, để bản bỏ hay đổi trường đã phát hành bị từ chối trước khi có phê duyệt.
   Trường bộ so sánh của mục `ArtifactKindRegistry` do agent-lifecycle/04 thêm cùng bên đọc của nó (bước 3 của ticket
   đó thử bằng một bộ so sánh giả), theo chữ ký nó khai; ticket này chỉ đặt `compare_object` của ticket 02 vào trường đó
   cho mục `object` trong `platform_kinds(...)` (`packages/python/dw_studio/src/dw_studio/kinds.py`), không thêm trường
   hay chữ ký thứ hai (gate 4/11/2026 (a)). Từ chối của `check_against_live` qua `SubmitCheck` mang `reason_code`
   `live_incompatible` cùng mọi `DocumentProblem` của nó thành `errors[]` (con trỏ, `code` như `field_removed`,
   `field_immutable`, `option_removed`, `pd_category_lowered`), và route trả 422 `validation_failed` với
   `details.reason_code` `live_incompatible` và `errors[]` đó, cùng hình 422 mà móc trả (spec R2.4); khi kiểu từ chối
   của `SubmitCheck` (agent-lifecycle/03 bước 5) chưa có chỗ cho danh sách lỗi, ticket này thêm một thành phần
   `errors` tùy chọn, mặc định rỗng, mà mọi kiểm có sẵn không đổi (gate (b)). Thứ tự giữa kiểm này và câu hỏi Đóng
   băng là của agent-lifecycle/04 bước 3; tiêu chí ở đây thử từng cái riêng. Chỉ từ chối có `errors` khác rỗng trả
   `validation_failed` với `errors[]`; từ chối của các kiểm khác giữ hình mà agent-lifecycle/03 định. Bộ so sánh, kiểm
   này và móc cùng so với một "bản Đang dùng": tài liệu của phiên bản `live` trong `studio.artifact_versions`; móc khẳng
   định `applied_version_id` của `studio.object_defs` là id của phiên bản đó trước khi áp, lệch thì ném lỗi (lượt xác
   nhận (g)). Ticket chờ field-security/01, chủ cột `access_mode` và phần áp nó của móc, vì nhánh chỉ siết "đóng
   `phone`" chỉ đổi `studio.field_defs` khi cột đó có (lượt xác nhận (h)).
   1a. Composition root của worker, nơi handler `studio.publish.object.decided` của agent-lifecycle/04 chạy, dựng
   `ArtifactKindRegistry` bằng cùng `platform_kinds(object_store_of, ...)` mà API dùng (`apps/api/src/dw_api/bootstrap/
studio.py`), không bản dựng thứ hai; khi agent-lifecycle/04 chưa làm, ticket này thêm `dw-studio` vào phụ thuộc của
   `apps/worker` (CLAUDE.md, Adding a bounded context, bước 8) và lời gọi đó. Giao dịch của handler mang `AccessContext`
   của người quyết định, nên các audit định nghĩa mà móc ghi (`studio.object.updated`, `studio.field.created`,
   `studio.field.updated`, `studio.picklist.updated`, qua `ObjectDefinitionStore.context`) đứng tên người duyệt với
   `details.lane` `outbox` (CLAUDE.md, Agent and tool rules; ADR-0011 (Accepted)), còn ở nhánh chỉ siết đứng tên người
   gửi, không `details.lane` (gate (d), (e)). `SqlArtifactTx` thêm `lane: str | None` (mặc định None), đặt `outbox` bởi
   đường mở giao dịch của handler `.decided`, và audit của móc ghi `details.lane` khi có; khi handler mở một giao dịch
   không phải `SqlArtifactTx`, ticket này đổi `object_store_of` sang nhận Protocol `ArtifactTx` có `context` và `lane`
   (đường lui (7) của ticket 02), không sửa handler (lượt xác nhận (i)). Móc ném lỗi trong handler là lỗi lập trình, không phải một nhánh: ngân
   sách slot (R1.6) đã kiểm lúc `seal`, và mỗi đối tượng có tối đa một Bản ứng viên, nên không phiên bản nào khác tiêu
   slot giữa lúc gửi và lúc duyệt; giao dịch lùi và lần giao outbox theo luật thử lại của outbox (gate, MEDIUM M1).
2. Nhánh chỉ siết (`agent-lifecycle:R1.7`, `agent-lifecycle:R2.9`): `LifecycleService` đưa phiên bản lên Đang dùng,
   phiên bản cũ sang Đã gỡ và ghi đúng một audit `studio.version.published` có người gửi là actor, `details.path`
   `tighten_only`, trong giao dịch của người gửi; móc phát hành chạy trong cùng giao dịch và chỉ áp định nghĩa, không
   ghi `studio.version.published` (ticket 02). Nhánh này đi qua Đóng băng của công ty, không qua Đóng băng của nền tảng
   (`platform_frozen`); mọi lần Gửi kiểm định khác trong lúc công ty Đóng băng nhận `tenant_frozen`
   (`agent-lifecycle:R7.9`, ADR-0120 (Accepted) quyết 7).
3. Nhánh nới: phiên bản sang Chờ duyệt với phê duyệt `studio.publish.object` có `author_ids`
   (`agent-lifecycle:R5.1`); handler `studio.publish.object.decided` (`agent-lifecycle:R5.5`) đưa phiên bản lên Đang
   dùng, ghi `studio.version.published` có người duyệt là actor và chạy móc phát hành trong cùng giao dịch, móc không ghi
   sự kiện đó lần nữa; bị từ chối thì phiên bản về Nháp và định nghĩa không đổi; phiên bản Đang dùng mà lần phát hành
   này thay không còn là bản đã so lúc gửi thì handler không phát hành mà đưa phiên bản về Nháp với
   `details.reason_code` `base_changed` (`agent-lifecycle:R5.9`, ADR-0120 (Accepted) quyết 2), một hàng rào mà đường W1
   không còn dẫn tới: mỗi thành phần có tối đa một phiên bản ở `draft`, `evaluating` hay `awaiting_approval`, nên trong
   lúc phiên bản nới chờ duyệt, lần tạo bản Nháp mới trả 409 `conflict` với `details.reason_code` `candidate_pending`
   (`tenant-config:R2.20`, `tenant-config:R2.22`), và người dựng muốn chỉ siết thì rút Bản ứng viên về Nháp
   (`agent-lifecycle:R2.4`) rồi sửa nó (ADR-0120 (Accepted) quyết 1, V4.17).
4. Test tích hợp đầu-cuối với hai người dùng thật của một tenant, cùng giữ `studio.objects.manage` và
   `studio.publish.approve`, không dùng fixture phê duyệt, gồm ca của V4.17: trong lúc một phiên bản nới chờ duyệt, tạo
   bản Nháp mới cho đối tượng bị từ chối `candidate_pending`; rút phiên bản nới về Nháp, sửa thành chỉ siết rồi gửi.

## Tiêu chí chấp nhận

- [ ] R1.2 (CO23): người giữ `studio.objects.manage` Gửi kiểm định bản nháp hợp lệ thêm một trường qua
      `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit` → phiên bản Chờ duyệt với phê duyệt
      `studio.publish.object` có `author_ids`, định nghĩa chưa đổi; một người khác giữ `studio.publish.approve` duyệt →
      Đang dùng, định nghĩa đã áp trong giao dịch của handler và đúng một dòng `studio.version.published` có người duyệt
      là actor; phiên bản mở một trường `basic` hay đổi `ai_description` → Chờ duyệt; người gửi tự duyệt → 409
      `conflict` với `details.reason_code` `second_person_required`, vì người gửi là người xin và tiền tố nghiêm
      `studio.publish.` kiểm trước guard tác giả (ADR-0104 (Accepted) quyết 11), định nghĩa không đổi.
- [ ] R1.7 (CO23): phiên bản chỉ đóng `phone` (hay chỉ hạ `default_access` từ `public_read` về `private`) → Đang dùng
      ngay trong giao dịch của người gửi, `tighten_only` đúng, `compared_live_hash` bằng mã băm của phiên bản Đang dùng
      trước đó, đúng một dòng `studio.version.published` có người gửi là actor và `details.path` `tighten_only`, không
      phê duyệt; công ty Đóng băng: phiên bản chỉ đóng `phone` → Đang dùng, phiên bản thêm một trường → 409
      `tenant_frozen`, giữ Nháp; nền tảng Đóng băng: phiên bản chỉ đóng `phone` → 409 `platform_frozen`, giữ Nháp;
      phiên bản vừa đóng `phone` vừa đổi nhãn → Chờ duyệt; coi thay đổi trộn là chỉ siết, cho nhánh chỉ siết qua Đóng
      băng của nền tảng hay để móc phát hành ghi thêm `studio.version.published` → test đỏ.
- [ ] R1.2 (CO23): ca của V4.17, phiên bản thêm một trường ở Chờ duyệt; trong lúc chờ, người giữ
      `studio.objects.manage` tạo bản Nháp mới cho đối tượng (để chỉ đóng `phone`) → 409 `conflict` với
      `details.reason_code` `candidate_pending`, không dòng `studio.artifact_versions` mới, Bản ứng viên vẫn Chờ duyệt và
      định nghĩa không đổi; người đó rút Bản ứng viên về Nháp (`agent-lifecycle:R2.4`), sửa nó thành chỉ đóng `phone` rồi
      Gửi kiểm định → Đang dùng ngay qua nhánh chỉ siết, phê duyệt `studio.publish.object` cũ đã hủy; cho tạo bản Nháp
      khi Bản ứng viên chờ → test đỏ.
- [ ] R1.3 (CO3): người thiếu `studio.objects.manage` gọi lệnh Gửi kiểm định → 404 như thành phần không tồn tại, vì
      khóa đó cũng là khóa đọc của loại (`tenant-config:R2.11`), phiên bản giữ Nháp, không phê duyệt nào mở; đổi khóa đọc
      và khóa gửi của mục `object` sang một khóa mà người thử giữ → lần gửi qua tới Chờ duyệt, test đỏ (gỡ riêng kiểm khóa
      gửi không đỏ được, vì kiểm đọc trả 404 trước nó; gate (c)).
- [ ] R2.4 (CO6): Gửi kiểm định bản nháp bỏ một trường đã phát hành và đổi `scale` của một trường khác → 422
      `validation_failed` với `details.reason_code` `live_incompatible` và hai phần tử `errors[]`, `field_removed` con
      trỏ `/fields` kèm `api_name` của trường đã bỏ trong `detail`, `field_immutable` con trỏ tới `scale`, phiên bản giữ Nháp, không phê duyệt nào mở; gỡ đăng ký kiểm → lần gửi qua tới Chờ duyệt và test đỏ.
- [ ] R1.2: lần phát hành qua handler `studio.publish.object.decided` trên worker thật → audit
      `studio.field.created` đứng tên người duyệt với `details.lane` `outbox`; lần phát hành chỉ siết → audit
      `studio.field.updated` đứng tên người gửi, không `details.lane`; worker dựng registry không có móc của `object` →
      handler không áp định nghĩa, test đỏ.
- [ ] R1.8: phiên bản giống hệt bản Đang dùng, hay chỉ đổi thứ tự trường → Chờ duyệt, không chỉ siết.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `docs/adr/0120-publish-gate-and-run-control-switches.md:39-84`; spec: R1.2, R1.7 (quyết 1 với nhánh chỉ siết, quyết 2).
- ADR-0120 (Accepted) quyết 7 (Đóng băng của công ty để nhánh chỉ siết đi qua); spec: R1.7.
- `agent-lifecycle:R1.7`, `agent-lifecycle:R2.4`, `agent-lifecycle:R2.8`, `agent-lifecycle:R2.9`, `agent-lifecycle:R5.1`,
  `agent-lifecycle:R5.5`, `agent-lifecycle:R5.9`, `agent-lifecycle:R7.9`; `tenant-config:R2.15`, `tenant-config:R2.16`,
  `tenant-config:R2.20`, `tenant-config:R2.22`; spec: R1.8 (bộ so sánh của ticket 02).
- ADR-0120 (Accepted) quyết 1 (một bản `live` và tối đa một bản chưa phát hành mỗi thành phần, V4.17); spec: CO23.
- ADR-0104 (Accepted) quyết 11 (tiền tố nghiêm kiểm trước guard tác giả); spec: R1.2.

## Comments

- 2026-10-24 (agent): tách từ ticket 02 (Quyết định 24/10/2026 của spec): cạnh ticket 02 → agent-lifecycle/04 khép vòng
  ticket 02 → agent-lifecycle/04 → workflow-engine/04 → workflow-engine/03 → record-access/04 → record-access/03 →
  record-access/02 → tenant-rbac/04 → ticket 02, sau khi workflow-engine/03 chờ record-access/04 và custom-objects/03
  (`I:record-access:R6.4~workflow-engine:R4.9`). R1.2, R1.7 và phần gửi của R1.3 chuyển sang đây; cạnh tới
  agent-lifecycle/03, /04 mà `B:agent-lifecycle:R5.1~custom-objects/02` đòi nằm ở ticket này. marketing-pilot/02 gieo
  đối tượng qua đường phát hành này nên chờ ticket này.
- 2026-10-24 (agent): vòng sửa 4: agent-lifecycle là người ghi duy nhất của `studio.version.published`, móc phát hành chỉ
  áp định nghĩa, thêm test "đúng một dòng" ở cả hai nhánh (`B:agent-lifecycle:R2.9~custom-objects:R1.7`); nhánh chỉ siết
  đi qua Đóng băng của công ty, không qua Đóng băng của nền tảng (Đạt, 24/10/2026; ADR-0120 (Accepted) quyết 7);
  "gửi phát hành" thành "Gửi kiểm định" (`G:CONTEXT.md#submit~custom-objects:R1.2`). marketing-pilot/02 thêm cạnh tới
  ticket này ở phía nó (`I:custom-objects/06~marketing-pilot/02`).
- 2026-10-24 (agent): kiểm vòng sửa 4: người gửi tự duyệt nhận 409 `conflict` với `details.reason_code`
  `second_person_required`, không `author_cannot_approve`, vì người gửi là người xin và tiền tố nghiêm kiểm trước guard
  tác giả (ADR-0104 (Accepted) quyết 11, `B:packages:spec~tenant-config/05`); bước 3 nêu ngoại lệ `base_changed` của
  handler khi bản Đang dùng đã đổi kể từ lúc gửi (Đạt, 24/10/2026; ADR-0120 (Accepted) quyết 2,
  `agent-lifecycle:R5.9`).
- 2026-10-24 (agent): vòng sửa 4, lượt hai: test đầu-cuối (bước 4) và một tiêu chí mới phủ ca của V4.2, một phiên bản
  chỉ siết lên Đang dùng trong lúc phiên bản nới chờ duyệt, rồi người thứ hai duyệt phiên bản nới → về Nháp với
  `base_changed`; bước 3 so với phiên bản Đang dùng mà lần phát hành thay (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): kiểm lượt hai của vòng sửa 4: tiêu chí ca V4.2 nêu tên audit `studio.version.returned_to_draft`
  của `agent-lifecycle:R5.9`; Mục tiêu nói móc phát hành nằm trong mục `ArtifactKindRegistry` của loại và
  agent-lifecycle gọi nó (ADR-0109 (Accepted) quyết 1), như bước 4 của ticket 02.
- 2026-10-24 (agent): vòng sửa 4, lượt sáu: Đạt quyết một bản chưa phát hành mỗi thành phần (V4.17), nên ca tranh chấp
  của V4.2 (phiên bản chỉ siết lên Đang dùng trong lúc phiên bản nới chờ duyệt) không còn xảy ra được: bước 4 và tiêu
  chí của ca đó đổi sang ca 409 `candidate_pending` rồi rút về Nháp (`agent-lifecycle:R2.4`); bước 3 giữ kiểm gốc
  `base_changed` của handler như hàng rào (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): kiểm lượt sáu của vòng sửa 4: đột biến của tiêu chí ca V4.17 là "cho tạo bản Nháp khi Bản ứng
  viên chờ" (bỏ kiểm `candidate_pending` của `tenant-config:R2.22`), không phải "bản Nháp thứ hai", vốn là ca
  `draft_exists` của `tenant-config:R2.23` và không làm test này đỏ; CO23 của spec sửa cùng.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate của ticket 02 (HIGH 7): bước 1 thêm đăng ký `check_against_live` vào bảng kiểm lúc gửi, Yêu cầu thêm R2.4, CO6 và một tiêu chí, vì `validate` của registry thuần trên một tài liệu nên phép so với bản Đang dùng không chạy được trong `seal`. Nếu sai thì: tenant-config đổi chữ ký `validate`, và tiêu chí này về ticket 02.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate của ticket 02, lượt xác nhận: tiêu chí R1.3 thành 404, vì `studio.objects.manage` là khóa đọc, khóa ghi và khóa gửi của loại, và người không đọc được thành phần nhận 404 (`tenant-config:R2.11`, TC24); spec R1.3 và CO3 sửa cùng. Nếu sai thì: khóa đọc của loại tách khỏi khóa ghi, và người đọc được mà không gửi được nhận 403.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check, một subagent; route Gửi kiểm định là của
  agent-lifecycle, ticket không thêm migration hay route): 0 CRITICAL, 6 HIGH, sửa theo khuyến nghị (Quyết định
  4/11/2026 của spec): (a) trường bộ so sánh do agent-lifecycle/04 thêm; (b) `live_incompatible` với `errors[]`; (c) đột
  biến R1.3 đổi khóa của mục; (d), (e) registry của worker và audit của móc ở handler; (f) không khác biệt thì không chỉ
  siết (R1.8).
- 2026-11-04 (agent): MEDIUM để lại: (M1) móc ném lỗi trong handler là lỗi lập trình (slot đã kiểm lúc `seal`, một Bản
  ứng viên mỗi đối tượng), outbox thử lại theo luật của nó; (M2) nâng `pd_category` kèm đóng trường vẫn qua người thứ hai
  theo R1.8, đúng chữ; (M3) công ty một quản trị viên không phát hành được đối tượng (Quyết định 23/10/2026, D11); (M4)
  cặp với ticket 03 (`details.reason_code`) là cảnh báo giả của `check_plans.py`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 3 HIGH, sửa: (h) chờ field-security/01, chủ `access_mode`, vì nhánh "đóng
  `phone`" không đổi gì khi cột chưa có; (i) `lane` trên `SqlArtifactTx` cho `details.lane` của móc, đường lui
  `ArtifactTx` có `context`; (g) một "bản Đang dùng" cho bộ so sánh, kiểm và móc. Sửa luôn: hình 422 của các kiểm khác
  giữ nguyên; con trỏ `/fields` của `field_removed`. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai
  thì: ghi ở đây khi dựng. Thứ tự dựng: sau 02, field-security/01, agent-lifecycle/03, /04; trước marketing-pilot/02.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, lane 2): dựng. Gate nói không migration, không route: đúng (route Gửi kiểm định, máy giai đoạn,
  phê duyệt và handler là của agent-lifecycle/03, /04; bước 1a đã có: worker dựng `platform_kinds(...)` qua
  `build_studio_kinds`). Mục `object` nhận `compare=object_tightens_only` (`compare_object(...).tighten_only` của ticket
  02, không trường hay chữ ký mới); `object_live_check` (trong `dw_studio.kinds`, vì các capability không import nhau)
  so phiên bản vừa niêm phong với tài liệu của bản `live` và vào `_SUBMIT_CHECKS` của API; `SubmitRefusal` thêm
  `errors` mặc định rỗng, và chỉ từ chối có `errors` thành `SubmitRefusedError` (422 `validation_failed`,
  `details.reason_code`, mỗi vấn đề một `errors[]`), mọi kiểm khác giữ hình cũ. Handler: `PublishSettler` gọi
  `LifecycleTx.carry_out(decision, "outbox")` sau khi đọc quyết định, đặt `AccessContext` của người quyết định và
  `lane` lên `SqlArtifactTx`; `object_store_of` truyền `lane` cho `SqlObjectDefinitionStore`, và audit của móc ghi
  `details.lane` khi có. Móc khẳng định định nghĩa đang áp là bản `live` mà lần gửi đã so (`compared_live_hash`), lệch
  thì 409 `base_changed` và cả giao dịch lùi (lượt xác nhận (g)).
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): làm khác ticket. (1) Không cần đường lui (7) của ticket 02: handler
  mở `SqlArtifactTx` (qua `for_tenant`) nhưng không có `AccessContext`, nên `object_store_of` trước đây ném `TypeError` ở
  mọi lần duyệt một đối tượng; ticket này cho giao dịch đó mang người quyết định bằng `carry_out`, một dòng ở handler.
  Ngữ cảnh dựng lại từ quyết định đã ghi: không vai trò, `plan_id` `recorded_decision`, chỉ ai và ở workspace nào. Nếu
  sai thì: `object_store_of` nhận một Protocol tác nhân hẹp (`principal_id`, `workspace_id`, `lane`) thay
  `AccessContext`. (2) `_SUBMIT_CHECKS` chỉ áp cho các loại của nền tảng: một app dựng với `studio_kinds=` của test
  không chạy kiểm của `object` trên tài liệu fixture. Nếu sai thì: kiểm gắn vào mục `ArtifactKindEntry`. (3) Test đi
  qua handler mà chính worker đăng ký (`dw_worker.main.register_studio_publish`) trên sự kiện outbox thật; Đóng băng là
  câu trả lời của `ControlStatePort` thay trên `LifecycleService` của app (cơ chế công tắc là của agent-lifecycle/01).
- 2026-11-06 (agent): kiểm. `apps/api/tests/integration/test_studio_object_publish.py` 16 (R1.2 đầu-cuối qua worker,
  từ chối về Nháp, tự duyệt 409 `second_person_required`, R1.8 năm ca, R1.7 đóng `phone`, hạ `default_access`, Đóng băng
  công ty và nền tảng, V4.17, R1.3 404, R2.4 hai `errors[]`, gate (g)); chạy lại `test_studio_publish.py`,
  `test_studio_lifecycle.py`, `test_studio_records.py`, `test_studio_objects.py` xanh. `reviewing-feature-security`:
  (1) tenant: mọi đọc dưới RLS của công ty trong giao dịch, khóa đọc của loại cho 404; (2) quyền: tự duyệt bị từ chối
  bởi tiền tố nghiêm, khóa gửi là khóa đọc; (3) nhánh chỉ siết chỉ bớt quyền, nhánh nới qua người thứ hai, Đóng băng
  nền tảng chặn cả chỉ siết; (4)-(6) không áp dụng (không bộ nhớ, migration, route, cache hay container mới).
  `mutations/06.yaml` 11 đột biến, mỗi `old` khớp đúng một lần, chưa chạy. Hoãn tới đóng hàng: mutate (11),
  `make test-integration` đầy đủ, P50/P95/P99 của lệnh Gửi kiểm định với loại `object` (nhánh chỉ siết, nhánh chờ
  duyệt) và của handler `.decided` so với commit bắt đầu hàng đợi.
