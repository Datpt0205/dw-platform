# 03 — Runtime agent: nguồn graph, cache, middleware, actor

Status: needs-triage
Blocked by: 02, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, AB5, AB6, AB7, AB9

## Mục tiêu

Dựng và chạy một phiên bản agent trong runner hiện có theo (công ty, phiên bản), với cache có trần kiểm mã băm, ngữ cảnh actor `agent` trong giới hạn dữ liệu, route model đọc từ bản kê và mọi lời gọi model chịu trần của lượt. Chứng minh R3 và cài AB5, AB6, AB7, AB9.

## Việc cần làm

1. `StudioGraphSource` ráp agent từ tài liệu phiên bản ghim; cache LRU có trần theo khóa `(tenant_id, agent_version_id, pinned_hash)`, `pinned_hash` là mã băm mà bản kê của lượt ghim, `definition_hash` của bản đã niêm phong hay mã băm tạm của bản Nháp ở lượt `simulate` (workflow-engine:R3.9), vì bản Nháp giữ id khi sửa; cổng mã băm tính lại mã băm của `document` đã nạp bằng cùng bước băm của niêm phong và từ chối biên dịch khi nó lệch `pinned_hash`, hay khi phiên bản là bản Nháp mà lượt chạy không ở `simulate` (ADR-0109 (Accepted) quyết 6; ADR-0117 (Accepted) quyết 5).
2. `StudioModelSelection` đọc route model đã ghim trong bản kê lượt chạy (qua `ModelResolver` của `model-connections`); đặt bước chọn model trước bước ngân sách và giới hạn hành vi trong ngăn xếp middleware (M2: middleware đứng trước là lớp ngoài), để model mặc định nhận 0 lượt gọi. Thứ tự ngăn xếp agent Studio là của spec này theo ADR-0117 (Accepted) quyết 5: `StudioModelSelection` ngoài cùng, rồi `ResidencyGate` của compliance-pdpl/03 như một middleware ngay sau nó, rồi giới hạn và ngân sách lượt (`LimitsMiddleware` của usage-and-limits/03, thay `RunBudgetMiddleware`), một phê duyệt mỗi bước, lỗi công cụ, thử lại model và nén ngữ cảnh; nhờ vậy lời gọi bị cổng lộ trình từ chối không tới lease (R3.7, usage-and-limits:R6.5). `RunControlMiddleware` đứng ở chỗ agent-lifecycle/01 đã chèn vào `platform_middleware`, ticket này không đổi chỗ của nó.
3. Thêm `RunContext.artifact` đóng dấu lúc nhận lượt chạy; `thread_id = run_id`; giới hạn hành vi thành `recursion_limit` và một middleware đếm lượt gọi; middleware đóng băng và hạn mức (`RunControlMiddleware` của `agent-lifecycle`).
4. Mở phiên công cụ gắn actor `agent`, chủ thể là người kích hoạt, `app.boundary_id` của phiên bản đã phát hành (dòng `studio.actor_boundaries` mà móc phát hành của loại `agent` ở ticket 02 ghi qua `ActorBoundaryPort` của `record-access`, R1.9); prefix công cụ `studio.agent.tool.` và cổng subject-version.
5. Lượt chạy agent vào qua `RunRequestService` của `workflow-engine`; saver xóa checkpoint khi lượt chat kết thúc.

## Tiêu chí chấp nhận

- [ ] R3.1 (AB6): nạp một phiên bản dựng graph theo khóa `(tenant_id, agent_version_id, pinned_hash)` trong cache LRU có trần; hai lượt `simulate` của cùng bản Nháp trước và sau một lần sửa → hai mục cache, lượt sau chạy graph của nội dung mới; gỡ `pinned_hash` khỏi khóa → lượt sau chạy graph cũ, test đỏ; sai nếu cache không có trần.
- [ ] R3.2 (AB6): hai công ty dùng cùng `api_name` và cùng số phiên bản cho hai mục cache tách biệt; gỡ `tenant_id` khỏi khóa cache → test đỏ.
- [ ] R3.3 (AB7): sửa `document` của một phiên bản đã niêm phong bằng role migrator làm runtime từ chối biên dịch khi băm lệch; sửa bản Nháp sau khi lượt `simulate` của nó được nhận → biên dịch từ chối, không bước nào chạy; một lượt khác `simulate` trỏ tới bản Nháp, dựng thẳng không qua `RunRequestService` → biên dịch từ chối; gỡ kiểm băm hay kiểm chế độ → test đỏ.
- [ ] R3.4 (AB5): một lead người kích hoạt không đọc được không có trong câu trả lời; giao dịch thiếu actor context trả 0 bản ghi; gỡ gán actor `agent` và `app.boundary_id` → test đỏ.
- [ ] R3.5: lượt chạy agent gọi đúng route model đã ghim trong bản kê, và model mặc định nhận 0 lượt gọi; sai nếu đọc route ngoài bản kê.
- [ ] R3.6 (AB9): mọi lời gọi model của lượt chịu trần chi phí của lượt; đảo thứ tự bước chọn model và bước ngân sách → test chi phí đỏ.
- [ ] R3.7 (AB9): lượt chạy agent dưới lộ trình `vn_only` gọi một route có `data_location` `foreign` ở cửa vòng agent → lời gọi bị `ResidencyGate` từ chối, không lease nào được giữ, không Bản ghi sử dụng nào được ghi; đặt `ResidencyGate` sau `LimitsMiddleware` → test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "agent_runtime"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-30`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:98`; spec: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, AB5, AB6, AB7, AB9; usage-and-limits:R6.5; compliance-pdpl:R2.2; workflow-engine:R3.9.

## Comments

- 2026-10-23 (agent): thêm Blocked by agent-lifecycle/01 theo phát hiện kiểm nhất quán ngày 23/10/2026: cả hai ticket chạm ngăn xếp middleware, và `RunControlMiddleware` ở bước 3 là của agent-lifecycle/01; spec này giữ thứ tự ngăn xếp (bước 2).
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026: thêm Blocked by usage-and-limits/03, vì `LimitsMiddleware` của ticket đó thay `RunBudgetMiddleware` trong chính ngăn xếp mà bước 2 đặt thứ tự; usage-and-limits/03 không chờ ticket này.
- 2026-10-24 (agent): theo kiểm nhất quán vòng 3 (vòng sửa thứ tư): bước 2 ghi chỗ của `ResidencyGate` trong ngăn xếp agent, ngay sau `StudioModelSelection` và trước `LimitsMiddleware`, cùng test R6.5 của usage-and-limits ở cửa vòng agent (R3.7, AB9); compliance-pdpl/03 bước 4 trỏ về thứ tự này. Blocked by đã có compliance-pdpl/03.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d: khóa cache là `(tenant_id, agent_version_id, pinned_hash)` và cổng mã băm so với `pinned_hash` của bản kê, nên bản Nháp mà route `dry-evaluations` của agent-lifecycle nhận chạy được ở `simulate` dưới mã băm tạm, và chỉ ở `simulate` (bước 1; R3.1, R3.3; ADR-0109 (Accepted) quyết 6; ADR-0117 (Accepted) quyết 5); `app.boundary_id` đọc dòng `studio.actor_boundaries` mà móc phát hành của loại `agent` ở ticket 02 ghi, không phải một hook của record-access (bước 4; R1.9).
