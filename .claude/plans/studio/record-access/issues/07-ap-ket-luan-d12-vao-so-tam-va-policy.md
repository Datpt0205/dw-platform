# 07 — Áp kết luận đo D12 vào sổ tầm và mẫu policy bản ghi

Status: ready-for-human (Chờ Đạt 23: máy tham chiếu của YC20)
Blocked by: 02, 03, 04, 05, 06
Area: studio
Yêu cầu: R9.1, R9.10

## Mục tiêu

Ticket 02 và 03 dựng sổ tầm và mẫu policy theo P0, tức ADR-0105 (Accepted) quyết 1, 3, 4 như viết, vì lần đo D12 của
ticket 06 chờ máy tham chiếu mà YC20 định nghĩa; số smoke của ticket 01 không chọn được phương án (luật chọn ở smoke đọc
lỗi và nhiễu của máy dev quá tải). Ticket này đọc phương án thắng của ticket 06 ở D12 và đưa sổ tầm, cột `access_key` và
policy về đúng phương án đó bằng một revision sau, như custom-objects/07 làm với DDL của `studio.records` (spec R9;
ADR-0105 (Accepted), Amendments 2026-11-04). Phần của người là cấp máy cho ticket 06 (Chờ Đạt 23); khi ticket 06
`resolved`, agent làm phần còn lại.

## Việc cần làm

1. Đọc phương án thắng của từng trục ở Comments của ticket 06 và mục Consequences của ADR-0105 (Accepted). Phương án thắng
   là P0 ở mọi trục: ghi vào Comments ở đây, không revision, ticket xong. Không phương án nào đạt ở D12: câu hỏi mở
   của ticket 06 cho người đặt yêu cầu chặn ticket này, ticket giữ `ready-for-human`.
2. Phương án khác: một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh), một thay đổi mỗi trục, mỗi
   trục dựng lại qua module mẫu policy của ticket 03 (chủ duy nhất của văn bản policy và của `reach_sql`), và test catalog
   của ticket 03 so văn bản mới:
    - L (một dòng sổ tầm mỗi hành động): PK, compare-and-set (một `version` chung cho các dòng của một chủ thể), trigger
      `studio.mark_principal_stale()`, hàm cửa, `studio.acl_*` và oracle của ticket 02 đổi theo; tiêu chí R5.1 tới R5.7
      của ticket 02 chạy lại xanh;
    - K (khóa `bigint`): `access_key` thành cột thường do trigger BEFORE INSERT OR UPDATE OF `object_id`, `workspace_id`
      luôn ghi đè (cột sinh không đọc được bảng khác), từ `object_defs.object_no` và `platform.workspaces.workspace_no`
      gán theo tenant lúc chèn, bất biến và không dùng lại; `access_key` không nằm trong quyền UPDATE của `dw_app`; một
      lần giao đổi `workspace_id` (ticket 05) tính lại khóa, nên workspace cũ thấy 0 dòng;
    - E (`EXISTS` tương quan thay mảng) hay H (câu gợi ý cho planner): đổi `reach_sql` và văn bản policy.
      Áp cho bảng cha và mọi partition đọc từ `pg_inherits`, kể cả partition mà custom-objects/07 tạo khi đổi modulus.

## Tiêu chí chấp nhận

- [ ] R9.1: phương án ghi ở đây là phương án thắng của ticket 06 ở D12 cho từng trục, kèm dòng Comments của ticket 06
      nó dẫn; sai nếu một trục theo số smoke.
- [ ] R9.10: sau revision, tiêu chí của ticket 02 (R5.1 tới R5.7) và của ticket 03 (R2.2 tới R4.6, R7.1 tới R7.3, R9.10)
      chạy lại xanh trên hình mới; test catalog so văn bản policy với module mẫu xanh.
- [ ] R9.1: với K, `assign_record` đổi `workspace_id` → `access_key` mới, người chỉ có tầm ở workspace cũ thấy 0 dòng;
      `dw_app` UPDATE `access_key` → permission denied.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `.claude/plans/studio/record-access/issues/06-do-rls-ban-ghi-o-quy-mo-d12.md` (phương án thắng ở D12);
  `db/bench/record-access/RESULTS.md` (smoke); spec: R9.
- `.claude/plans/studio/record-access/issues/01-do-hinh-dang-rls-ban-ghi.md` (Comments 2026-11-04: trục K, L, E, H, W).
- `.claude/plans/studio/custom-objects/issues/07-ap-so-do-d12-vao-ddl-ban-ghi.md` (cùng cách áp kết luận D12).

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách theo gate `checking-plan-readiness` của ticket 02 và 03 (HIGH (a)):
  ticket 03 chờ ticket 06 (Comments 3/11/2026 của ticket 03) làm custom-objects/03 tới 05, record-access/04, 05 và mọi
  ticket dựng trên bản ghi đứng chờ máy tham chiếu; ticket 02 và 03 dựng tạm theo P0, ticket này áp kết luận D12. Nếu
  sai thì: ticket 03 trở lại chờ ticket 06, và ticket này rút.
