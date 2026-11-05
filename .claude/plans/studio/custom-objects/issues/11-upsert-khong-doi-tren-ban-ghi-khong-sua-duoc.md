# 11 — Tạo hoặc cập nhật không đổi gì trên bản ghi người gọi không sửa được trả 409 như R7.4

Status: ready-for-agent
Area: studio
Yêu cầu: R5.8, R7.4, CO16

## Mục tiêu

R7.4 nói Tạo hoặc cập nhật trúng bản ghi người gọi không sửa được trả cùng 409 `duplicate_value` như R7.1 và không đổi
gì. Hôm nay một lần upsert gửi đúng giá trị đang có lên một bản ghi người gọi đọc được mà ngoài tầm sửa, khi người gọi
giữ khóa `obj.<api_name>.update`, trả 200 `created: false` với `permissions.update` sai (discovery/10 (b), đo
5/11/2026): nhánh không đổi gì của `_apply` trả bản ghi trước khi câu UPDATE, nơi policy sửa quyết, chạy. Không lộ gì vì
bản ghi đọc được, không ghi gì vào bản ghi; nhưng câu trả lời lệch R7.4, và với khóa `wf:` của một Bước nhánh đó còn ghi
một dòng `studio.record_write_keys` cho bản ghi không sửa được. `PATCH` không đổi gì đi cùng nhánh đó nên lệch R5.8 theo
cùng cách: 200 thay 403.

## Việc cần làm

1. Ở nhánh không đổi gì của `_apply` trong
   `packages/python/dw_studio/src/dw_studio/records/application/record_service.py`: sau phép so phiên bản (412 trước,
   như thứ tự 404, 412, 403 của `_why_not`), bản ghi đã đọc mà `call.holds("update") and current.may_update` sai →
   `_refused("change")`, trước khi ghi khóa `wf:`. `may_update` là biểu thức `may_sql('update')` của module policy,
   cùng văn bản policy UPDATE dùng; không viết lại vị từ tầm nào trong Python (gate (l) của ticket 03).
2. Một phép kiểm cho hai cửa: `PATCH` nhận 403 `permission_denied` (R5.8; app-standards:R3.16 "khi người gọi không sửa
   được, R3.2 và R3.13 áp như với mọi lần ghi"), còn nhánh sửa của upsert đã đổi `PermissionDeniedError` thành 409
   `duplicate_value` ở `_upsert_existing` (R7.4). Phép kiểm nằm sau quyết định trường `_editable`, theo thứ tự của
   ADR-0107 (Accepted) quyết định 3 (bước 6 trước bước 7): quyết định trường không phụ thuộc bản ghi nên không lộ gì về
   bản ghi; `_upsert_existing` không đổi.

## Tiêu chí chấp nhận

- [ ] R7.4 (CO16): người đọc toàn công ty, sửa trong workspace mình, upsert đúng giá trị đang có lên bản ghi ở workspace
      kia → 409 `duplicate_value` chỉ con trỏ trường, một audit `studio.record.duplicate_refused`, `version` không đổi;
      cùng người qua cửa lượt `workflow` (lượt `run_as` chính người đó, ranh giới mở `update` của đối tượng) với khóa
      `wf:` → 409, một audit, 0 dòng `studio.record_write_keys` của khóa đó; gỡ phép kiểm `may_update` → 200, test đỏ.
- [ ] R5.8: cùng người `PATCH` đúng giá trị đang có lên bản ghi đó, không `If-Match` và có khóa `wf:` qua cửa lượt → 403
      `permission_denied`, `version` không đổi, 0 dòng khóa; gỡ phép kiểm → 200, test đỏ.
- [ ] R7.4: cùng người upsert đúng giá trị lên bản ghi trong workspace mình → 200 `created: false`, `version` không đổi;
      qua cửa lượt với khóa `wf:` → 200 và một dòng khóa (R5.9).
- [ ] Xong: `DW_TEST_DB_SUFFIX=_lane2 uv run python -m pytest packages/python/dw_studio/tests/integration/test_record_service.py` xanh.

## Nguồn

- `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:671`; spec: R7.4.
- `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:832`; spec: R7.4.
- `.claude/plans/studio/app-standards/spec.md` R3.16; spec: R5.8.
- `.claude/plans/studio/custom-objects/issues/03-record-service.md` Comments 2026-11-05 (lane 2).

## Comments

- 2026-11-05 (agent, lane 2): viết từ discovery/10 (b). Đo bằng một test tạm trên bản xuất sạch, không giữ trong repo.
- 2026-11-05 (agent, lane 2, theo ủy quyền 31/10/2026): gate `checking-plan-readiness`, builder check (không migration,
  không route): 0 CRITICAL, 2 HIGH đã sửa, cả hai đã có câu trả lời. (H1) Phép kiểm trước hay sau `_editable` và
  `claim`: thứ tự của ADR-0107 (Accepted) quyết định 3 (trường trước tầm ghi), nên đặt trong `_apply`; `claim` cùng giao dịch, lỗi
  thì cuộn lại. (H2) "Giữ hành vi `PATCH` của app-standards/03" sai: app-standards:R3.16 cho `PATCH` không đổi gì của
  người không sửa được là 403, và R5.8 cũng vậy; một phép kiểm trong `_apply` sửa cả hai cửa, thêm R5.8 vào Yêu cầu.
  Nếu sai thì: `PATCH` không đổi gì giữ 200 và phép kiểm chuyển lên `_upsert_existing` cạnh `call.holds("update")`.
  MEDIUM: (M1) vế khóa `wf:` của tiêu chí chạy dưới lượt `run_as` của chính người đó để `may_update` sai vì tầm
  workspace, không vì ranh giới actor; 409 của loại actor `workflow` có audit (R7.5) mà không đếm (R7.6), đã ghi vào
  tiêu chí. (M2) Sau sửa, upsert không đổi gì lên bản ghi đọc được mà ngoài tầm sửa là một lần 409 đếm vào giới hạn dò
  trùng của người và agent (R7.6 đếm mọi 409); đúng như spec, ghi để người đọc số đếm không ngạc nhiên.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
