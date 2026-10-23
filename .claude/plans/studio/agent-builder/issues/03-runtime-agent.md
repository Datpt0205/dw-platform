# 03 — Runtime agent: nguồn graph, cache, middleware, actor

Status: needs-triage
Blocked by: 02, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, AB5, AB6, AB7, AB9

## Mục tiêu

Dựng và chạy một phiên bản agent trong runner hiện có theo (công ty, phiên bản), với cache có trần kiểm mã băm, ngữ cảnh actor `agent` trong giới hạn dữ liệu, route model đọc từ bản kê và mọi lời gọi model chịu trần của lượt. Chứng minh R3 và cài AB5, AB6, AB7, AB9.

## Việc cần làm

1. `StudioGraphSource` ráp agent từ tài liệu phiên bản ghim; cache LRU có trần theo khóa `(tenant_id, agent_version_id)`; cổng mã băm định nghĩa từ chối biên dịch khi `document` lệch băm lúc nạp.
2. `StudioModelSelection` đọc route model đã ghim trong bản kê lượt chạy (qua `ModelResolver` của `model-connections`); đặt bước chọn model trước bước ngân sách và giới hạn hành vi trong ngăn xếp middleware (M2: middleware đứng trước là lớp ngoài), để model mặc định nhận 0 lượt gọi. Thứ tự ngăn xếp agent Studio là của spec này theo ADR-0117 (Accepted) quyết 5: `StudioModelSelection` ngoài cùng, rồi giới hạn và ngân sách lượt, một phê duyệt mỗi bước, lỗi công cụ, thử lại model và nén ngữ cảnh; `RunControlMiddleware` đứng ở chỗ agent-lifecycle/01 đã chèn vào `platform_middleware`, ticket này không đổi chỗ của nó.
3. Thêm `RunContext.artifact` đóng dấu lúc nhận lượt chạy; `thread_id = run_id`; giới hạn hành vi thành `recursion_limit` và một middleware đếm lượt gọi; middleware đóng băng và hạn mức (`RunControlMiddleware` của `agent-lifecycle`).
4. Mở phiên công cụ gắn actor `agent`, chủ thể là người kích hoạt, `app.boundary_id` của phiên bản đã phát hành (ghi bởi hook publish của `record-access`); prefix công cụ `studio.agent.tool.` và cổng subject-version.
5. Lượt chạy agent vào qua `RunRequestService` của `workflow-engine`; saver xóa checkpoint khi lượt chat kết thúc.

## Tiêu chí chấp nhận

- [ ] R3.1 (AB6): nạp một phiên bản dựng graph theo khóa `(tenant_id, agent_version_id)` trong cache LRU có trần; sai nếu cache không có trần.
- [ ] R3.2 (AB6): hai công ty dùng cùng `api_name` và cùng số phiên bản cho hai mục cache tách biệt; gỡ `tenant_id` khỏi khóa cache → test đỏ.
- [ ] R3.3 (AB7): sửa `document` của một phiên bản đã niêm phong bằng role migrator làm runtime từ chối biên dịch khi băm lệch; gỡ kiểm băm → test đỏ.
- [ ] R3.4 (AB5): một lead người kích hoạt không đọc được không có trong câu trả lời; giao dịch thiếu actor context trả 0 bản ghi; gỡ gán actor `agent` và `app.boundary_id` → test đỏ.
- [ ] R3.5: lượt chạy agent gọi đúng route model đã ghim trong bản kê, và model mặc định nhận 0 lượt gọi; sai nếu đọc route ngoài bản kê.
- [ ] R3.6 (AB9): mọi lời gọi model của lượt chịu trần chi phí của lượt; đảo thứ tự bước chọn model và bước ngân sách → test chi phí đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "agent_runtime"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-30`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:98`; spec: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, AB5, AB6, AB7, AB9.

## Comments

- 2026-10-23 (agent): thêm Blocked by agent-lifecycle/01 theo phát hiện kiểm nhất quán ngày 23/10/2026: cả hai ticket chạm ngăn xếp middleware, và `RunControlMiddleware` ở bước 3 là của agent-lifecycle/01; spec này giữ thứ tự ngăn xếp (bước 2).
