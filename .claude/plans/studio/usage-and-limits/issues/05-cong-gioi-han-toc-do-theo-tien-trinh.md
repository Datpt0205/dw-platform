# 05 — Một RateLimiterPort và bộ đếm theo tiến trình cho giới hạn tốc độ W1

Status: needs-triage
Area: studio
Yêu cầu: R7.1, R7.2, UL14

## Mục tiêu

Mọi giới hạn tốc độ theo công ty (60 sự kiện mỗi phút của một nguồn dữ liệu Data Hub, giới hạn kiểm trùng
của custom-objects) hỏi một `RateLimiterPort` của usage-and-limits và không tự viết bộ đếm; W1 đáp port bằng
bộ đếm theo tiến trình ở `giới hạn / số replica`, không cần Valkey (spec R7; DO-49). GCRA trên Valkey là
adapter thứ hai ở W2.

## Việc cần làm

1. Protocol `RateLimiterPort` trong `packages/python/dw_platform/src/dw_platform/application/rate_limit.py`:
   `acquire(key: RateLimitKey, limit_per_minute: int) -> RateDecision(allowed: bool, retry_at: datetime | None)`;
   `RateLimitKey` là `(tenant_id, source_id)` có kiểu, không nhận chuỗi tự do, nên bên gọi không truyền
   được băm của bearer.
2. Adapter `InProcessRateLimiter` trong `packages/python/dw_platform/src/dw_platform/adapters/rate_limit.py`:
   cửa sổ một phút mỗi khóa trong bộ nhớ tiến trình; phần của mỗi tiến trình bằng
   `floor(limit_per_minute / replicas)`, `replicas` đọc từ `settings` (tối thiểu 1), nên khi một bản sao chết
   tổng giới hạn thấp đi chứ không cao lên; khóa không dùng quá 2 phút bị dọn để bộ nhớ không phình
   (`.claude/rules/failure-modes.md` mục 6).
3. Gắn một instance ở composition root của API (`apps/api/src/dw_api/bootstrap/wiring.py`) và của worker,
   truyền cho bên dùng bằng injection; không module nào giữ instance toàn cục.
4. `apps/api/src/dw_api/middleware/rate_limit.py` giữ nguyên vai chặn ở cửa API; nó không phải chủ giới hạn
   theo công ty và không ai gọi nó thay port này.

## Tiêu chí chấp nhận

- [ ] R7.1 (UL14): giới hạn 60 với `replicas` = 2: lần thứ 30 trong một phút ở một tiến trình được nhận,
      lần thứ 31 bị từ chối kèm `retry_at`; phút sau nhận lại; với `replicas` = 1 thì lần 60 nhận, lần 61 từ
      chối.
- [ ] R7.2 (UL14): hai yêu cầu tới cùng nguồn mang hai bearer khác nhau chia chung một bộ đếm; gọi port với
      một chuỗi thay `RateLimitKey` → mypy báo lỗi; đổi khóa sang băm bearer → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `apps/api/src/dw_api/middleware/rate_limit.py:36-41`; spec: R7.2 (limiter hôm nay khóa theo băm bearer
  chưa xác minh).
- spec: R7.1; workflow-triggers:R5.9; custom-objects:R7.6; DO-49.

## Comments

- 2026-10-23 (agent): ticket mới theo DO-49 và câu Q3 của requirements.md (Đạt, 23/10/2026). Bên dùng là
  workflow-triggers/02 (Data Hub) và kiểm trùng của custom-objects; hai ticket đó nên chờ ticket này.
