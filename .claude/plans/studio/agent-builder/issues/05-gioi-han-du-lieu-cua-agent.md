# 05 — Giới hạn dữ liệu của agent: phép dẫn từ Bộ công cụ, móc phát hành và bộ dẫn của lượt mô phỏng

Status: needs-triage
Blocked by: 02, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R1.9, R1.10, AB11, AB14

## Mục tiêu

Một phiên bản agent đọc đúng các đối tượng và trường mà Bộ công cụ đã ghim của nó cho phép, ở lượt `live` lẫn ở lượt
`simulate` có gốc chưa phát hành: một phép dẫn giới hạn duy nhất trên tài liệu, mà móc phát hành của loại `agent` gọi rồi
ghi qua `ActorBoundaryPort` của record-access trong giao dịch phát hành, và mà `RunRequestService` gọi qua bảng bộ dẫn
giới hạn theo loại khi ghi giới hạn dữ liệu tạm cho bản Nháp hay Bản ứng viên (spec R1.9, R1.10; AB11, phần phép dẫn của
AB14; ADR-0117 (Accepted) quyết 3; V4.22). Loại `agent`, cài đặt, khóa, route và khung prompt là của ticket 02; runtime
gắn giới hạn vào phiên công cụ là của ticket 03.

## Việc cần làm

1. Phép dẫn giới hạn của loại `agent`: một hàm thuần `derive_agent_boundary(document) -> BoundarySpec` trong
   `dw_studio.agents.domain`, trả mỗi đối tượng của công cụ đối tượng trong Bộ công cụ đã ghim cùng lệnh của nó (đọc từ
   `ToolsetSpec` của `.claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md` và công cụ mà
   `ObjectToolGenerator` của `.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md` sinh;
   tools-and-skills:R4.1, tools-and-skills:R6.1) và các trường của `field_caps`, không thêm đối tượng hay trường nào khác.
2. Móc phát hành của loại `agent` (spec R1.9; tenant-config:R2.15; ADR-0109 (Accepted) quyết 1): ticket này cho móc mà
   mục `ArtifactKindRegistry` của ticket 02 mang đúng một việc của loại: trong giao dịch phát hành mà agent-lifecycle mở,
   gọi phép dẫn của bước 1, nhận bằng tiêm, rồi `ActorBoundaryPort.record` của
   `.claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md` với loại `agent`, thành phần, phiên bản và
   kết quả dẫn (record-access:R6.7; ADR-0117 (Accepted) quyết 3); móc không ghi audit riêng, vì agent-lifecycle ghi
   `studio.version.published` một lần (agent-lifecycle:R5.5), và không viết phép dẫn thứ hai.
3. Bộ dẫn của lượt mô phỏng (spec R1.10; workflow-engine:R3.13, workflow-engine:R3.15): ở composition root của API và
   worker, đăng ký đúng hàm của bước 1 cho loại `agent` vào bảng bộ dẫn giới hạn theo loại mà `RunRequestService` nhận
   bằng tiêm (`.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md` bước 7), cùng hàm mà móc của bước
   2 nhận, nên giới hạn tạm của một bản Nháp (Kiểm định thử) hay của một Bản ứng viên (lần thử của Lượt kiểm định,
   agent-lifecycle:R4.12) dẫn đúng như lúc phát hành; trước ticket này, loại `agent` không có bộ dẫn, nên
   `RunRequestService` từ chối mọi lượt `simulate` có gốc chưa phát hành của agent (0 `worker_runs`, 0 giới hạn), đóng
   khi thiếu.

## Tiêu chí chấp nhận

- [ ] R1.9 (AB11): gọi móc phát hành của `agent` trong một giao dịch cho phiên bản ghim `obj_mkt_lead__search`,
      `obj_mkt_lead__get` và `field_caps` một trường → đúng một dòng `studio.actor_boundaries` loại `agent` cho phiên bản,
      `studio.actor_boundary_objects` chỉ có `mkt_lead` với `can_read`, `studio.actor_boundary_fields` chỉ có trường đó;
      rollback giao dịch → không dòng giới hạn nào; gỡ lời gọi `ActorBoundaryPort` khỏi móc → không dòng giới hạn nào,
      test đỏ.
- [ ] R1.10 (AB14): hàm dẫn của loại `agent`, gọi trên nội dung nháp hay nội dung niêm phong của một Bản ứng viên ghim
      `obj_mkt_lead__search`, `obj_mkt_lead__get` và `field_caps` một trường, trả đúng đối tượng, lệnh và trường mà móc phát
      hành ghi cho cùng nội dung ở ca R1.9; dựng móc với một hàm dẫn giả chỉ trả `mkt_campaign` → móc phát hành ghi
      `mkt_campaign`, tức móc không có phép dẫn riêng; viết một phép dẫn riêng trong móc → móc vẫn ghi `mkt_lead` khi hàm
      dẫn nó nhận đổi, test đỏ.
- [ ] R1.10 (AB14): Kiểm định thử một bản Nháp agent chỉ ghim công cụ đọc `mkt_lead`, xin qua `RunRequestService` thật →
      giới hạn tạm của lượt dưới `(version_id, pinned_hash)` chỉ có `mkt_lead` với `can_read`, bằng đúng giới hạn mà móc
      phát hành dẫn cho cùng nội dung; lần thử của Lượt kiểm định trên một Bản ứng viên agent cùng Bộ công cụ → giới hạn tạm
      dưới `(version_id, definition_hash)` bằng đúng giới hạn đó; gỡ dòng đăng ký bộ dẫn của `agent` khỏi composition root
      → `RunRequestService` từ chối lượt, 0 `worker_runs`, 0 giới hạn, và test đăng ký đỏ; đăng ký một hàm dẫn khác hàm
      móc nhận → test so hai giới hạn đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "agent_boundary"` xanh.

## Nguồn

- `apps/api/src/dw_api/bootstrap/wiring.py:332`; spec: R1.10 (seam của composition root, nơi bộ dẫn của loại `agent`
  đăng ký vào bảng bộ dẫn mà `RunRequestService` nhận).
- spec: R1.9, R1.10, AB11, AB14; record-access:R6.7, record-access:R6.11; tools-and-skills:R4.1, tools-and-skills:R6.1;
  workflow-engine:R3.13, workflow-engine:R3.15; agent-lifecycle:R4.12, agent-lifecycle:R5.5; tenant-config:R2.15;
  ADR-0117 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 1, 6; V4.22, V4.31.

## Comments

- 2026-10-26 (agent): lượt h, đợt 2, tách từ ticket 02 theo V4.31 của Đạt và bảng ticket của lượt h: ticket này nhận phép
  dẫn giới hạn của loại `agent` và móc phát hành gọi `ActorBoundaryPort` (phần giới hạn dữ liệu của bước 1 cũ của ticket
  02), cùng bộ dẫn của lượt mô phỏng mà ticket 03 từng đăng ký ở bảng bộ dẫn của `RunRequestService` (bước 5 cũ của ticket
  03); dời mã R1.9, R1.10, AB11 và phần phép dẫn của AB14 từ dòng Yêu cầu của ticket 02. Blocked by theo bảng: 02,
  record-access/04, tools-and-skills/02, tools-and-skills/03, workflow-engine/03, ba cạnh đầu dời từ ticket 02.
