# 06 — Phát hành đối tượng qua vòng đời phiên bản: chỉ siết một người, nới qua người thứ hai

Status: needs-triage
Blocked by: 02, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md
Area: studio
Yêu cầu: R1.2, R1.3, R1.7, CO3, CO23

## Mục tiêu

Quản trị viên công ty phát hành một phiên bản `dw.object/v1` qua lệnh gửi của agent-lifecycle: phiên bản chỉ siết lên
Đang dùng bởi một người có audit (R1.7), mọi phiên bản khác qua Chờ duyệt và một người thứ hai (R1.2), và chỉ người giữ
`studio.objects.manage` gửi được (R1.3). Ticket 02 dựng loại `object`, bộ so sánh chỉ siết (R1.8) và móc phát hành;
ticket này nối chúng vào route gửi, máy giai đoạn, phê duyệt `studio.publish.object` và handler của agent-lifecycle
(ADR-0120 (Accepted) mục 1, 2). Đường này tách khỏi ticket 02 để các ticket bản ghi, quyền và bảo mật trường chờ ticket
02 mà không phải chờ Cổng chất lượng của agent-lifecycle/04 (Quyết định 24/10/2026 của spec).

## Việc cần làm

1. Nối loại `object` vào lệnh gửi `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit` của
   agent-lifecycle/03 qua mục `ArtifactKindRegistry` mà ticket 02 đăng ký: khóa gửi `studio.objects.manage`
   (`tenant-config:R2.15`), bộ so sánh chỉ siết mà `LifecycleService` gọi để ghi `tighten_only` và
   `compared_live_hash` lên dòng phiên bản (`agent-lifecycle:R2.8`), và móc phát hành `MetadataService.apply`.
2. Nhánh chỉ siết (`agent-lifecycle:R1.7`, `agent-lifecycle:R2.9`): móc phát hành chạy trong giao dịch của người gửi,
   cùng giao dịch đưa phiên bản lên Đang dùng, đưa phiên bản cũ sang Đã gỡ và ghi audit `studio.version.published` có
   người gửi là actor, `details.path` `tighten_only`.
3. Nhánh nới: phiên bản sang Chờ duyệt với phê duyệt `studio.publish.object` có `author_ids`
   (`agent-lifecycle:R5.1`); handler `studio.publish.object.decided` (`agent-lifecycle:R5.5`) chạy móc phát hành trong
   giao dịch đưa phiên bản lên Đang dùng; bị từ chối thì phiên bản về Nháp và định nghĩa không đổi.
4. Test tích hợp đầu-cuối với hai người dùng thật của một tenant, cùng giữ `studio.objects.manage` và
   `studio.publish.approve`, không dùng fixture phê duyệt.

## Tiêu chí chấp nhận

- [ ] R1.2 (CO23): người giữ `studio.objects.manage` gửi phát hành bản nháp hợp lệ thêm một trường qua
      `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit` → phiên bản Chờ duyệt với phê duyệt
      `studio.publish.object` có `author_ids`, định nghĩa chưa đổi; một người khác giữ `studio.publish.approve` duyệt →
      Đang dùng và định nghĩa đã áp trong giao dịch của handler; phiên bản mở một trường `basic` hay đổi
      `ai_description` → Chờ duyệt; người gửi tự duyệt → 409 `author_cannot_approve`, định nghĩa không đổi.
- [ ] R1.7 (CO23): phiên bản chỉ đóng `phone` (hay chỉ hạ `default_access` từ `public_read` về `private`) → Đang dùng
      ngay trong giao dịch của người gửi, `tighten_only` đúng, `compared_live_hash` bằng mã băm của phiên bản Đang dùng
      trước đó, audit `studio.version.published` có người gửi là actor và `details.path` `tighten_only`, không phê
      duyệt; phiên bản vừa đóng `phone` vừa đổi nhãn → Chờ duyệt; coi thay đổi trộn là chỉ siết → test đỏ.
- [ ] R1.3 (CO3): người thiếu `studio.objects.manage` gọi lệnh gửi phát hành → 403 `permission_denied`, phiên bản giữ
      Nháp, không phê duyệt nào mở; gỡ kiểm khóa gửi ở mục đăng ký của loại → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `docs/adr/0120-publish-gate-and-run-control-switches.md:39-84`; spec: R1.2, R1.7 (quyết 1 với nhánh chỉ siết, quyết 2).
- `agent-lifecycle:R1.7`, `agent-lifecycle:R2.8`, `agent-lifecycle:R2.9`, `agent-lifecycle:R5.1`,
  `agent-lifecycle:R5.5`; `tenant-config:R2.15`, `tenant-config:R2.16`; spec: R1.8 (bộ so sánh của ticket 02).

## Comments

- 2026-10-24 (agent): tách từ ticket 02 (Quyết định 24/10/2026 của spec): cạnh ticket 02 → agent-lifecycle/04 khép vòng
  ticket 02 → agent-lifecycle/04 → workflow-engine/04 → workflow-engine/03 → record-access/04 → record-access/03 →
  record-access/02 → tenant-rbac/04 → ticket 02, sau khi workflow-engine/03 chờ record-access/04 và custom-objects/03
  (`I:record-access:R6.4~workflow-engine:R4.9`). R1.2, R1.7 và phần gửi của R1.3 chuyển sang đây; cạnh tới
  agent-lifecycle/03, /04 mà `B:agent-lifecycle:R5.1~custom-objects/02` đòi nằm ở ticket này. marketing-pilot/02 gieo
  đối tượng qua đường phát hành này nên chờ ticket này.
