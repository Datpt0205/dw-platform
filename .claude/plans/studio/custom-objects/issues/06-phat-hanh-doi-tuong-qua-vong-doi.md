# 06 — Phát hành đối tượng qua vòng đời phiên bản: chỉ siết một người, nới qua người thứ hai

Status: needs-triage
Blocked by: 02, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md
Area: studio
Yêu cầu: R1.2, R1.3, R1.7, CO3, CO23

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
   `compared_live_hash` lên dòng phiên bản (`agent-lifecycle:R2.8`), và móc phát hành `MetadataService.apply`.
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
   này thay không còn là bản đã so lúc gửi (một phiên bản chỉ siết lên trước) thì handler không phát hành mà đưa phiên
   bản về Nháp với `details.reason_code` `base_changed`, định nghĩa giữ bản Đang dùng mới (`agent-lifecycle:R5.9`,
   ADR-0120 (Accepted) quyết 2).
4. Test tích hợp đầu-cuối với hai người dùng thật của một tenant, cùng giữ `studio.objects.manage` và
   `studio.publish.approve`, không dùng fixture phê duyệt, gồm ca của V4.2: một phiên bản chỉ siết lên Đang dùng trong
   lúc một phiên bản nới chờ duyệt, rồi người thứ hai duyệt phiên bản nới.

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
- [ ] R1.2 (CO23): ca của V4.2, phiên bản thêm một trường ở Chờ duyệt; trong lúc chờ, một phiên bản chỉ đóng
      `phone` lên Đang dùng; người thứ hai duyệt phiên bản thêm trường → phiên bản đó về Nháp với `details.reason_code`
      `base_changed` và đúng một audit `studio.version.returned_to_draft` có người duyệt là actor (`agent-lifecycle:R5.9`),
      không thêm dòng `studio.version.published`, định nghĩa và bản Đang dùng vẫn là bản chỉ siết; để handler phát hành
      khi bản Đang dùng đã đổi → test đỏ.
- [ ] R1.3 (CO3): người thiếu `studio.objects.manage` gọi lệnh Gửi kiểm định → 403 `permission_denied`, phiên bản giữ
      Nháp, không phê duyệt nào mở; gỡ kiểm khóa gửi ở mục đăng ký của loại → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `docs/adr/0120-publish-gate-and-run-control-switches.md:39-84`; spec: R1.2, R1.7 (quyết 1 với nhánh chỉ siết, quyết 2).
- ADR-0120 (Accepted) quyết 7 (Đóng băng của công ty để nhánh chỉ siết đi qua); spec: R1.7.
- `agent-lifecycle:R1.7`, `agent-lifecycle:R2.8`, `agent-lifecycle:R2.9`, `agent-lifecycle:R5.1`,
  `agent-lifecycle:R5.5`, `agent-lifecycle:R5.9`, `agent-lifecycle:R7.9`; `tenant-config:R2.15`, `tenant-config:R2.16`;
  spec: R1.8 (bộ so sánh của ticket 02).
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
