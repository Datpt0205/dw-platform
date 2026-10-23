# 02 — Thành viên cấp tenant và trạng thái

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.7, R4.8, R5.1, G1, G2, OP4, OP5, OP6, OP7

## Mục tiêu

Vị thế của một người trong công ty thành một dòng `platform.tenant_members` có trạng thái `invited`, `active` hay
`suspended`; mọi membership treo vào dòng đó, và người không `active` không có quyền ở workspace nào của công ty (R4, R5,
YC7). Từ brief B2 ticket 05, không có quan hệ quản lý (W2).

## Việc cần làm

1. **Bảng.** Migration (id hex của `alembic revision`): `platform.tenant_members`:
    - `tenant_id uuid NOT NULL` FK `platform.tenants` `ON DELETE CASCADE`, `user_id uuid NOT NULL` FK `platform.users`
      `ON DELETE CASCADE`, `PRIMARY KEY (tenant_id, user_id)`, index `ix_tenant_members_user_id (user_id)`;
    - `status text NOT NULL` với `ck_tenant_members_status CHECK (status IN ('invited','active','suspended'))`, không
      default;
    - `status_changed_at`, `created_at`, `updated_at` (`timestamptz NOT NULL DEFAULT now()`), trigger `updated_at` nhường
      giá trị câu lệnh nêu (CLAUDE.md, "Data model rules").
      Cột quản lý trực tiếp, mã nhân sự và nguồn ghi đến ở W2 (ADR-0102 (Proposed) mục 3).
2. **RLS và quyền DB.** ENABLE và FORCE; `tenant_isolation_tenant_members` theo `app.tenant_id`;
   `tenant_members_self_select` FOR SELECT theo `app.principal_id`, cùng dạng `memberships_self_select`, để bootstrap thấy
   trạng thái của chính người đó ở mọi tenant. `dw_app` SELECT, INSERT, UPDATE, DELETE; `dw_provisioner` SELECT, INSERT;
   khẳng định trong `test_privileges.py`, `test_rls_coverage.py`.
3. **Chuyển dữ liệu.** Một dòng cho mỗi cặp `(tenant_id, user_id)` có trong `platform.memberships`: `active` khi người đó
   đã đăng nhập theo đúng luật của `member_status()` (`directory.py:27-28`), không thì `invited`. Sau đó
   `fk_memberships_tenant_members (tenant_id, user_id)` tới `platform.tenant_members` `ON DELETE CASCADE`, dùng index sẵn
   có `ix_memberships_tenant_user`.
4. **Người ghi.** Mỗi đường ghi membership ghi dòng thành viên công ty trước, cùng giao dịch
   (`INSERT ... ON CONFLICT (tenant_id, user_id) DO NOTHING`): `membership_admin`, `tenant_members` (lời mời ghi `invited`
   cho người chưa đăng nhập lần nào), `_provision_default_membership` và `provisioning_repo` (ghi `active`), `seed_env`,
   `scripts/grant_platform_admin.py`. Lần đăng nhập đầu của người được mời (`_resolve_user`) đổi `invited` sang `active`
   trong giao dịch nối danh tính.
5. **Người đọc.** Dựng AccessContext (`membership_lookup.py:80-106`) join `platform.tenant_members` và đòi
   `status = 'active'`, thiếu dòng là từ chối (fail closed); `member_status()` đọc cột thay cho suy luận;
   `GET /api/v1/admin/members`, `GET /api/v1/directory/members` dùng nó; `_read_memberships` của bootstrap bỏ tenant nơi
   người đó không `active`; `scope_holders.py` bỏ người không `active`.
6. **Phiên bản quyền.** Trigger `platform.bump_access_version()` trên bảng này do tenant-rbac/02 gắn (hàm ra đời ở đó,
   sau ticket này); ticket này không đụng cache.
7. Offboarding xuất và xóa `platform.tenant_members` (`test_offboarding.py`).

## Tiêu chí chấp nhận

- [ ] R4.1 (OP4): sau chuyển dữ liệu, mọi cặp `(tenant_id, user_id)` của membership có đúng một dòng; INSERT membership không có dòng thành viên công ty → lỗi FK; mọi đường ghi ở bước 4 có test tạo membership mới thành công.
- [ ] R4.2 (OP4): DELETE dòng thành viên công ty có membership ở hai workspace → 0 membership còn lại, cùng câu lệnh.
- [ ] R4.3 (OP5): đặt `suspended` bằng SQL rồi dựng AccessContext không qua cache → 403 ở cả hai workspace của người đó; xóa dòng → 403; gỡ điều kiện `status = 'active'` → test đỏ.
- [ ] R4.4: `POST /api/v1/admin/invitations` cho email mới → dòng `invited`; lỗi giữa giao dịch → không có dòng nào.
- [ ] R4.5: người được mời đăng nhập lần đầu → dòng thành `active` trong cùng giao dịch với dòng `platform.external_identities`.
- [ ] R4.7 (OP6): kết nối `app.tenant_id` A đọc thành viên của B → 0 dòng; kết nối không đặt tenant → 0 dòng; self-select chỉ trả dòng của chính người đó.
- [ ] R4.8 (OP7): người `suspended` ở tenant A, `active` ở tenant B → bootstrap chỉ có workspace của B; gỡ điều kiện → đỏ.
- [ ] R5.1: test so sánh: với mọi người của tenant seed, `status` của `GET /api/v1/admin/members` và `GET /api/v1/directory/members` bằng cột `status`.
- [ ] G1: `test_an_invited_person_signs_in_and_finds_their_workspace` xanh trước và sau.
- [ ] G2: `test_revoke_removes_a_membership` xanh trước và sau; thành viên công ty còn lại sau khi gỡ membership cuối.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:1-8`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/directory.py:27-28`; spec: R5.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:105-106`; spec: R4.3.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_admin.py:109`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:201-222`; spec: R4.1, R4.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:287`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/testing/seed_env.py:227`; spec: R4.1.
- `scripts/grant_platform_admin.py:74`; spec: R4.1.
- `db/migrations/sql/0001_platform_baseline.sql:671`; spec: R4.2.
- `db/migrations/sql/0001_platform_baseline.sql:818`; spec: R4.8.
- ADR-0102 (Proposed) mục 3; brief B2 mục 1.2, 1.3 và ticket 05.

## Comments
