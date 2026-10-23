# 04 — Chat: hội thoại, tin nhắn, cửa nhận run, polling và màn chat

Status: needs-info (DO-44)
Blocked by: 03, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, AB3, AB4, AB8

## Mục tiêu

Cho nhân viên trong `Người được dùng` trò chuyện với một trợ lý qua màn `/chat`: hội thoại riêng của chủ, một lượt chạy mỗi lượt hội thoại ở worker, kết quả trả qua polling. Chứng minh R4 và R5 của spec và cài AB3, AB4, AB8.

## Việc cần làm

1. Migration hai bảng `studio.conversations` và `studio.conversation_messages` (revision hex): RLS bật và FORCE với một policy permissive theo hình workspace và một policy RESTRICTIVE siết `owner_user_id = current_setting('app.user_id')` theo tiền lệ `platform.notifications`; `active_run_id` unique cục bộ để chiếm chỗ một lượt; chỉ mục phân trang dẫn đầu `(tenant_id, owner_user_id, created_at DESC)`.
2. Route chat: `POST /api/v1/studio/agents/{id}/conversations`, `POST .../conversations/{conversation_id}/messages` (chiếm `active_run_id`, 202 khi nhận, 409 `reason_code=conversation_busy` khi đang chạy), `GET .../messages` (polling của chủ). Cửa nhận run `trigger_kind=chat` qua `RunRequestService`; `worker_runs.input` chỉ mang id; hook hoàn tất ghi tin nhắn trợ lý; xóa hội thoại audit `studio.conversation.deleted`.
3. Lọc agent theo `Người được dùng`: `GET /api/v1/studio/agents` và `/chat` chỉ trả agent mà `platform.audience_matches` của `org-and-principals` khớp người gọi; người ngoài audience mở hội thoại hay gửi tin trả 404.
4. Màn `/chat` antd (`vi_VN`, seam web và allowlist của `studio-skeleton`): danh sách agent theo audience, danh sách hội thoại của chủ, khung tin nhắn cập nhật qua polling, "Đang suy nghĩ · n bước", nhãn AI cố định, lời chào và tối đa sáu gợi ý.

## Tiêu chí chấp nhận

- [ ] R4.1 (AB4): người B đọc hội thoại của người A trả 404; câu SQL thiếu `app.user_id` trả 0 dòng; gỡ policy RESTRICTIVE → test đỏ.
- [ ] R4.2 (AB4): mở hội thoại của người khác cùng công ty trả 404 như với hội thoại không tồn tại; sai nếu lộ sự tồn tại.
- [ ] R4.3 (AB8): hai `POST .../messages` song song cho một hội thoại cho đúng một 202 và một 409; gỡ chiếm `active_run_id` → hai lượt chạy.
- [ ] R4.4: `worker_runs.input` của lượt chạy chat chỉ chứa id; sai nếu chứa nội dung tin nhắn.
- [ ] R4.5: lượt chạy chat hoàn tất ở worker làm lần `GET .../messages` tiếp theo của chủ trả tin nhắn trợ lý mới; sai nếu không trả qua polling.
- [ ] R5.1 (AB3): `GET /api/v1/studio/agents` chỉ trả agent mà audience của người gọi khớp; sai nếu trả agent ngoài audience.
- [ ] R5.2 (AB3): người ngoài `Người được dùng` gọi một agent nhận 404; gỡ kiểm audience ở cửa chat → người ngoài thấy agent.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "chat or conversation" && pnpm --filter web test:e2e -- chat` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41`; `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:46`; `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:26`; spec: R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, AB3, AB4, AB8.

## Comments
