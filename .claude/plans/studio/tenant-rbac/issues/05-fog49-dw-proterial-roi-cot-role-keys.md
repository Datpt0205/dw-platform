# 05 — FOG-49: dw-proterial thôi ghi `memberships.role_keys` trước khi ticket 06 khóa cột

Status: ready-for-human (FOG-49: người giữ dw-proterial)
Blocked by: 02
Area: studio
Yêu cầu: không (điều kiện tiên quyết ngoài repo; tách khỏi ticket 03 ngày 3/11/2026, không chứng minh mã R nào)

## Mục tiêu

Ticket 06 khóa `memberships.role_keys` và `permission_set_keys` (`ck_memberships_legacy_role_columns`), nên một sản
phẩm dựng trên nền tảng còn ghi hai cột đó sẽ lỗi 23514 ngay khi nhận migration của ticket 06. Đạt quyết ngày
24/10/2026 (FOG-49) rằng người giữ dw-proterial chuyển dw-proterial khỏi hai cột trước khi cột bị khóa; khóa tách từ
ticket 03 sang ticket 06 ngày 4/11/2026, nên ticket này chỉ chặn ticket 06. Agent không có kênh tới dw-proterial, nên
phần này là việc của người: Đạt hỏi, người giữ dw-proterial làm và xác nhận, Đạt ghi lại.

## Việc cần làm

1. Đạt gửi người giữ dw-proterial: hai cột bị khóa ở ticket 06; từ ticket 03, gán vai trò là đề xuất hai người qua
   API gán vai trò (bước 4 và 6), nên ngay khi nhận migration của ticket 03, một lần ghi hai cột dưới `dw_app` mà thêm
   vai trò đã bị từ chối (23514 `rbac_refusals_role_assignments`), lần thêm khóa dưới `dw_provisioner` và lần thêm
   `platform_admin` dưới vai khác `dw_migrator` cũng vậy (`ck_memberships_legacy_role_writer`), và không lần ghi nào
   đổi được `user_id`, `workspace_id`, `tenant_id` của membership (`ck_memberships_identity_fixed`); lần ghi dưới
   `dw_migrator` và lần bỏ vai trò còn qua tới ticket 06. Importer hay script ghi vai trò dưới `dw_migrator` thì ghi
   bảng gán vai trò của ticket 02.
2. Người giữ dw-proterial chuyển mọi chỗ ghi hai cột, gồm importer, seed và fixture, rồi trả lời bằng commit đã chuyển.
3. Đạt ghi vào Comments ngày, người xác nhận và commit đó; agent dời ticket này sang `resolved`.

## Tiêu chí chấp nhận

- [ ] Comments có câu trả lời của người giữ dw-proterial, kèm commit mà ở đó `git grep -nE "role_keys|permission_set_keys"`
      trên mã (không tính tài liệu) chỉ còn chỗ đọc hay ghi `["platform_admin"]`; sai nếu còn một chỗ ghi khóa khác.
- [ ] Xong: `python -I scripts/check_plans.py --advisory --path .claude/plans/studio/tenant-rbac` xanh.

## Nguồn

- `.claude/plans/studio/requirements.md:518`; spec: R8.6 (FOG-49).
- `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:303-304` (ADR-0104 (Accepted), Amendments 2026-10-24); spec: R8.6.

## Comments

- 2026-11-03 (agent, theo ủy quyền 31/10/2026): tách từ ticket 03 theo gate `checking-plan-readiness` (HIGH 9), vì
  điều kiện FOG-49 ("chưa xong thì ticket 03 không lên ready-for-agent") cần một câu trả lời chỉ Đạt lấy được từ người
  giữ dw-proterial. Ticket 03 lên `ready-for-agent` khi ticket này `resolved`; Blocked by chỉ trỏ ngược, nên ticket 03
  ghi điều đó ở bước 9 và Comments. Nếu sai thì: gộp lại thành điều kiện trong bước 9 của ticket 03.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): khóa cột tách từ ticket 03 sang ticket 06 (Quyết định 4/11/2026 của
  spec); ticket này chặn ticket 06, không chặn ticket 03. Bước 1 nói thêm điều ticket 03 đã từ chối, để người giữ
  dw-proterial biết lần nhận nào làm vỡ gì. Nếu sai thì: như dòng của ticket 03 cùng ngày.
