# 11 — Tạo hoặc cập nhật không đổi gì trên bản ghi người gọi không sửa được trả 409 như R7.4

Status: needs-triage
Area: studio
Yêu cầu: R7.4, CO16

## Mục tiêu

R7.4 nói Tạo hoặc cập nhật trúng bản ghi người gọi không sửa được trả cùng 409 `duplicate_value` như R7.1 và không đổi
gì. Hôm nay một lần upsert gửi đúng giá trị đang có lên một bản ghi người gọi đọc được mà ngoài tầm sửa, khi người gọi
giữ khóa `obj.<api_name>.update`, trả 200 `created: false` với `permissions.update` sai (discovery/10 (b), đo
5/11/2026): nhánh không đổi gì của `_apply` trả bản ghi trước khi câu UPDATE, nơi policy sửa quyết, chạy. Không lộ gì vì
bản ghi đọc được, không ghi gì vào bản ghi; nhưng câu trả lời lệch R7.4, và với khóa `wf:` của một Bước nhánh đó còn ghi
một dòng `studio.record_write_keys` cho bản ghi không sửa được.

## Việc cần làm

1. Ở `_upsert_existing` của
   `packages/python/dw_studio/src/dw_studio/records/application/record_service.py`, bản ghi khớp mà
   `existing.may_update` sai (biểu thức `reach_sql('update')` của module policy, cùng văn bản policy dùng) → 409
   `duplicate_value` qua `duplicate()` như khi thiếu khóa `update`, trước `_apply`; không viết lại vị từ tầm nào trong
   Python (gate (l) của ticket 03).
2. `PATCH` không đổi gì lên bản ghi ngoài tầm sửa giữ hành vi của app-standards/03; ticket này chỉ đổi nhánh của upsert.

## Tiêu chí chấp nhận

- [ ] R7.4 (CO16): người đọc toàn công ty, sửa trong workspace mình, upsert đúng giá trị đang có lên bản ghi ở workspace
      kia → 409 `duplicate_value` chỉ con trỏ trường, một audit `studio.record.duplicate_refused`, không dòng
      `studio.record_write_keys` khi có khóa `wf:`; gỡ phép kiểm `may_update` → 200, test đỏ.
- [ ] R7.4: cùng người upsert đúng giá trị lên bản ghi trong workspace mình → 200 `created: false`, `version` không đổi.
- [ ] Xong: `DW_TEST_DB_SUFFIX=_lane2 uv run python -m pytest packages/python/dw_studio/tests/integration/test_record_service.py` xanh.

## Nguồn

- `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:671`; spec: R7.4.
- `packages/python/dw_studio/src/dw_studio/records/application/record_service.py:832`; spec: R7.4.
- `.claude/plans/studio/custom-objects/issues/03-record-service.md` Comments 2026-11-05 (lane 2).

## Comments

- 2026-11-05 (agent, lane 2): viết từ discovery/10 (b). Đo bằng một test tạm trên bản xuất sạch, không giữ trong repo.
