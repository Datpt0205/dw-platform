# 04 — Người được dùng tối thiểu: dw.audience/v1 chỉ điều kiện workspace

Status: needs-triage
Blocked by: 02
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, OP12, OP13

## Mục tiêu

Lát W1 của người được dùng (R8; ADR-0102 (Accepted) quyết định 7; DO-40): tài liệu `dw.audience/v1` chỉ có điều kiện
`workspace_subtree`, một bộ kiểm trả 422 cho tài liệu rỗng hay sai, và hàm `platform.audience_matches` trả khớp theo từng
lần gọi, đọc `platform.tenant_members` và `platform.memberships` dưới RLS, không vật chất hóa. Người được dùng chỉ quyết
ai thấy và mở được agent, không bao giờ nới tầm dữ liệu. agent-builder/04 chờ ticket này và chỉ gọi bộ kiểm cùng hàm
(agent-builder:R1.5, agent-builder:R5.1, agent-builder:R5.2); điều kiện thuộc tính, nhóm và màn ngược đến ở W2 mà không
đổi dạng tài liệu.

## Việc cần làm

1. Mô hình thuần `AudienceDocument` trong `packages/python/dw_platform/src/dw_platform/domain/audience.py` (Pydantic,
   `extra="forbid"`): `schema` bằng `dw.audience/v1`; `any_of` là danh sách các `all_of`, mỗi `all_of` là danh sách điều
   kiện; ở W1 chỉ nhận loại điều kiện `{"workspace_subtree": "<uuid>"}`; tối đa 20 điều kiện trên cả tài liệu; xuất JSON
   Schema cho bên dùng.
2. Bộ kiểm `AudienceValidator.validate(context, document)` ở tầng application của `dw_platform`: tài liệu không có điều
   kiện nào → `DomainError` 422 với `details.reason_code = "audience_empty"`; điều kiện khác `workspace_subtree`, quá 20
   điều kiện, hay workspace mà kết nối của tenant trong AccessContext không đọc được → 422 `validation_failed` với
   `errors[].pointer` trỏ vào điều kiện đó. Workspace của tenant khác trả đúng lỗi của workspace không tồn tại.
3. Migration (id hex của `alembic revision`): hàm
   `platform.audience_matches(p_tenant_id uuid, p_user_id uuid, p_audience jsonb) RETURNS boolean`,
   `LANGUAGE sql STABLE SECURITY INVOKER`, `SET search_path = pg_catalog, pg_temp`: trả `true`
   khi người đó có dòng thành viên công ty `status = 'active'` của `p_tenant_id` và một membership ở workspace mà một điều
   kiện `workspace_subtree` nêu (cây W1 phẳng nên cây con của một workspace là chính nó; W2 đổi sang
   `platform.workspace_subtree` khi cây đến); loại điều kiện khác trả `false`. `REVOKE EXECUTE ... FROM PUBLIC`,
   `GRANT EXECUTE` cho `dw_app`. Không bảng và không cache kết quả.
4. Test: unit cho mô hình và bộ kiểm; integration cho hàm dưới `dw_app` với `app.tenant_id` đặt theo giao dịch; khẳng định
   `EXECUTE` trong `test_privileges.py`.

## Tiêu chí chấp nhận

- [ ] R8.1 (OP12): `{"schema": "dw.audience/v1", "any_of": []}` → 422 `audience_empty`, không dòng nào được ghi; gỡ kiểm rỗng → test đỏ.
- [ ] R8.2 (OP12): điều kiện `{"team": "<uuid>"}` → 422 với `errors[0].pointer` trỏ vào điều kiện đó; 21 điều kiện → 422; workspace của tenant B → 422 cùng thân lỗi với workspace không tồn tại.
- [ ] R8.3: người `active` có membership ở workspace W1 khớp tài liệu nêu W1 và không khớp tài liệu chỉ nêu W2.
- [ ] R8.4 (OP13): người `suspended` có membership ở W1 → `false`; người của tenant B hỏi qua kết nối của tenant A → `false`; gỡ điều kiện `status = 'active'` khỏi hàm → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:103-106`; spec: R8.4.
- ADR-0102 (Accepted) quyết định 7 và phần Consequences về phân đợt; spec: R8, OP12, OP13; agent-builder:R1.5,
  agent-builder:R5.1, agent-builder:R5.2.

## Comments
