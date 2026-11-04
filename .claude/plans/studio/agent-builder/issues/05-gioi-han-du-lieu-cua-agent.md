# 05 — Giới hạn dữ liệu của agent: phép dẫn từ Bộ công cụ, móc phát hành và bộ dẫn của lượt mô phỏng

Status: ready-for-agent
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

1. Phép dẫn giới hạn của loại `agent`: một hàm thuần `derive_agent_boundary(closure)` trong `dw_studio.agents.domain`,
   nhận đúng kết quả của `closure_of` của tenant-config (tham chiếu cùng các dòng phiên bản đã nạp: tài liệu `dw.agent/v1`
   với mục `toolset` nhúng, mỗi đối tượng một phiên bản; `packages/python/dw_studio/src/dw_studio/core/application/service.py:587`),
   như `RunRequestService` đưa cho bộ dẫn của loại (workflow-engine/03 bước 7), và không truy vấn nào: siêu dữ liệu của
   công cụ đối tượng lấy từ `ToolsetSpec` của mục `toolset` trong tài liệu, hay từ hàm thuần của `ObjectToolGenerator` trên dòng
   phiên bản đối tượng trong cùng kết quả, nên ở lượt `simulate` nó đọc đúng bao đóng mà bản kê của lượt ghim (tenant-config:R6.1).
   Hàm trả đúng hình mà `ActorBoundaryPort.record` của record-access/04 nhận (đối tượng với cờ, trường với `access`),
   không kiểu thứ hai. Đối tượng và lệnh đọc từ siêu dữ liệu có cấu trúc của công cụ mà `ObjectToolGenerator` của
   `.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md` sinh (tools-and-skills:R6.1; đối tượng
   theo `api_name`, lệnh), không tách từ tên công cụ: `search`, `get` → `can_read`, mọi cờ khác `false`; ở W1
   `ObjectToolGenerator` chỉ sinh `search` và `get` (tools-and-skills/03 bước 2), nên một lệnh khác làm hàm ném
   `BoundaryDerivationError` tới khi ticket W2 sinh lệnh đó thêm ánh xạ của nó, đóng khi thiếu. Chỉ đọc công cụ đối tượng nêu thẳng trong
   `ToolsetSpec` đã ghim (`sub_agents` và `links` không có ở W1, ticket 02); một Bộ công cụ hay skill lồng mang công cụ
   đối tượng làm hàm ném `BoundaryDerivationError` tới khi W2 xử lý nó. `field_caps` có hình `{<api_name đối tượng>: [<api_name trường>,
...]}`: một đối tượng có công cụ mà không có mục trong `field_caps` nhận mọi trường của phiên bản đối tượng đã ghim,
   `access` `read`; một đối tượng có mục chỉ nhận các trường được nêu, `access` `read`, và một danh sách rỗng (`{mkt_lead: []}`)
   là không trường nào, không bao giờ là mọi trường; trường nêu hai lần tính một lần; dòng trường chỉ phủ trường của
   `studio.field_defs`, còn id bản ghi và cột hệ thống theo luật của custom-objects và record-access, không theo
   `field_caps` (custom-objects:R5.6); một mục cho đối tượng không có công cụ nào, hay một trường không có
   trong phiên bản đối tượng đã ghim, làm hàm ném `BoundaryDerivationError` nêu nó (field-security:R2.5 đọc các dòng này
   như quyền trường của giới hạn). Bộ công cụ không có công cụ đối tượng nào cho ra một giới hạn không đối tượng nào, vẫn
   được ghi, để runtime luôn có `boundary_id` và lượt đọc 0 bản ghi.
2. Móc phát hành của loại `agent` (spec R1.9; tenant-config:R2.15; ADR-0109 (Accepted) quyết 1): ticket này cho móc mà
   mục `ArtifactKindRegistry` của ticket 02 mang đúng một việc của loại: trong giao dịch phát hành mà agent-lifecycle mở,
   gọi phép dẫn của bước 1, nhận bằng tiêm, rồi `ActorBoundaryPort.record` của
   `.claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md` với loại `agent`, thành phần, phiên bản và
   kết quả dẫn (record-access:R6.7; ADR-0117 (Accepted) quyết 3); móc không ghi audit riêng, vì agent-lifecycle ghi
   `studio.version.published` một lần (agent-lifecycle:R5.5), và không viết phép dẫn thứ hai. Móc có chữ ký
   `PublishHook` (`tx`, id phiên bản; `packages/python/dw_studio/src/dw_studio/core/application/registry.py`), gọi
   `closure_of` trong chính giao dịch đó, và được nối ở cả hai composition root, API và worker, vì giao dịch phát hành
   có thể chạy trong handler `.decided` ở worker (ADR-0120 (Accepted) quyết 2). `BoundaryDerivationError`
   từ phép dẫn làm móc ném lại, nên giao dịch phát hành rollback và không phiên bản nào lên `live` thiếu giới hạn.
3. Bộ dẫn của lượt mô phỏng (spec R1.10; workflow-engine:R3.13, workflow-engine:R3.15): ở composition root của API và
   worker, đăng ký đúng hàm của bước 1 cho loại `agent` vào bảng bộ dẫn giới hạn theo loại mà `RunRequestService` nhận
   bằng tiêm (`.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md` bước 7), cùng hàm mà móc của bước
   2 nhận, nên giới hạn tạm của một bản Nháp (Kiểm định thử) hay của một Bản ứng viên (lần thử của Lượt kiểm định,
   agent-lifecycle:R4.12) dẫn đúng như lúc phát hành; trước ticket này, loại `agent` không có bộ dẫn, nên
   `RunRequestService` từ chối mọi lượt `simulate` có gốc chưa phát hành của agent (0 `worker_runs`, 0 giới hạn), đóng
   khi thiếu; `BoundaryDerivationError` ở cửa đó từ chối yêu cầu với 422 `boundary_derivation_failed`, `errors[].pointer`
   trỏ tới chỗ lỗi (`/field_caps/mkt_campaign`), không dòng lượt nào. Vì loại `agent` có Cổng chất lượng, mỗi Bản ứng
   viên qua lần thử của Lượt kiểm định trước khi được duyệt, và lần thử đó gọi cùng phép dẫn trên nội dung niêm phong,
   nên một lỗi dẫn làm Lượt kiểm định trượt với lần thử bị từ chối mang mã đó (agent-lifecycle:R4.12), trước khi ai
   duyệt, không để tới giao dịch phát hành. Không backfill: một phiên bản phát hành trước ticket này giữ không giới hạn
   (đọc 0 bản ghi) tới lần phát hành sau.

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
- [ ] R1.9 (AB11): Bộ công cụ có `obj_mkt_lead__search` và không mục `field_caps` cho `mkt_lead` → chỉ `can_read` của
      `mkt_lead`, mọi trường của phiên bản đối tượng đã ghim với `access` `read`; một công cụ giả có lệnh `update` →
      `BoundaryDerivationError`; `field_caps` nêu một
      trường của `mkt_campaign` khi Bộ công cụ không có công cụ nào của `mkt_campaign` → `BoundaryDerivationError`, phát
      hành rollback, không dòng giới hạn nào; Bộ công cụ chỉ có công cụ quy trình → đúng một dòng `studio.actor_boundaries`
      không dòng đối tượng nào; `field_caps: {mkt_lead: []}` → `mkt_lead` không trường nào; một `api_name` đối tượng chứa `__` → đúng đối tượng; móc chạy trong
      handler ở worker với registry của worker → ghi đúng dòng; tách đối tượng từ tên công cụ → test
      đỏ.
- [ ] Xong: `uv run python -m pytest packages/python/dw_studio/tests -k "agent_boundary"` xanh.

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
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `cb5e9a4` (builder check trong một subagent, không boundary walk: ticket không thêm migration hay route; lượt xác nhận ngữ cảnh mới sau các sửa), 0 CRITICAL, 12 HIGH đã sửa theo khuyến nghị. Lượt đầu: (1) hàm nhận bao đóng, không chỉ tài liệu; (2) lệnh → cờ từ siêu dữ liệu có cấu trúc, W1 chỉ `search`, `get`, lệnh khác ném lỗi; (3) nghĩa của `field_caps`; (4) lỗi dẫn rollback phát hành và từ chối lượt mô phỏng; (5) Bộ công cụ không công cụ đối tượng vẫn ghi một giới hạn rỗng; (6) không kiểu thứ hai ngoài hình của `ActorBoundaryPort.record`; (7) đọc đúng bao đóng mà bản kê ghim. Lượt xác nhận: (8) đầu vào là kết quả của `closure_of`, không truy vấn; (9) móc nối ở cả API và worker; (10) lỗi dẫn hiện ở lần thử của Lượt kiểm định trước khi duyệt; (11) danh sách rỗng là không trường nào; (12) 422 `boundary_derivation_failed` với `pointer`. Nếu sai thì: như `Nếu sai thì:` của dòng lượt xác nhận 4/11/2026 trong spec; với (1)-(12): hàm tự nạp bao đóng, đối tượng không có mục `field_caps` nhận không trường nào, lỗi dẫn chỉ hiện lúc phát hành.
- 2026-11-04 (agent): MEDIUM để lại: (a) bao đóng ghim một phiên bản mỗi đối tượng, nên hai công cụ của cùng đối tượng không dựa trên hai phiên bản; (b) id bản ghi và cột hệ thống theo custom-objects và record-access, không theo `field_caps`; (c) không backfill: phiên bản phát hành trước ticket này đọc 0 bản ghi tới lần phát hành sau; (d) một Bộ công cụ hay skill lồng ném lỗi tới W2.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
