# 02 — Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng

Status: needs-info (DO-21)
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, UL5, UL7, UL12

## Mục tiêu

Một Bảng giá theo ngày hiệu lực là chủ duy nhất của giá; một Sổ sử dụng theo lượt gọi ghi mọi lượt gọi
model với đủ thuộc tính gán, chỉ thêm và idempotent; màn Mức độ sử dụng đọc chính sổ này (spec R2, R3).
Đảo việc gỡ `platform.model_usage_ledger` (DO-21), kèm bên đọc từ ngày đầu.

## Việc cần làm

1. `configs/pricing/price_book@1.0.0.yaml` và `dw_usage.domain.pricing.PriceBook.price(quantities, provider, model, at)`
   trả chi phí `Decimal`, phiên bản, id mục giá; loại sử dụng là tập đóng (`input_uncached`,
   `cache_read`, `cache_write_5m`, `cache_write_1h`, `output`, `image_input`, `audio_input`,
   `embedding_input`, `rerank_search_unit`, `extraction_page`, `transcription_second`,
   `sandbox_cpu_second`, `server_tool_call`); `input_uncached = input_tokens − cache_read − cache_write`.
   Bộ nạp từ chối mục chồng thời gian cùng khóa, loại sử dụng lạ, giá âm. Dời giá khỏi `ModelRoute`
   (`model/profiles.py:54-55`) và `configs/models/*.yaml` trong cùng thay đổi; thay `route_cost`;
   `scripts/release_manifest.py` ghim Bảng giá (id, version, sha256); `settings.is_deployed`: tuyến nền
   tảng trả phí không có mục giá → từ chối khởi động.
2. Revision Alembic mới (id hex ngẫu nhiên): `platform.usage_events` như mục Dữ liệu của spec, phân vùng
   theo tháng với DEFAULT, RLS ở cha và DEFAULT cùng migration, policy drain `app.worker_drain` trên
   cha; index `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
   `(lease_id) WHERE lease_id IS NOT NULL`; `dw_app` không UPDATE, DELETE trên cha và partition.
3. `platform.ensure_time_partitions` thêm `usage_events`; `_ensure_one_partition` thu hồi UPDATE, DELETE
   cho mảng cha chỉ-thêm thay `IF parent = 'audit_events'`; `drop_expired_partitions(cutoffs jsonb)` mỗi
   cha một mốc (NULL = không xóa); `retention@x.y.z.yaml` đặt `usage_events` 395 ngày.
4. `UsageLedgerPort.settle(event) -> bool` (`INSERT ... ON CONFLICT DO NOTHING`); `id`, `occurred_at`
   cấp trước lời gọi; thiếu số dùng của nhà cung cấp → `cost_source = 'estimated'` bằng ước tính, không 0.
5. Bên đọc từ ngày đầu: `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace) trả tổng theo
   thao tác, model, nguồn chi phí; `platform.usage_daily` cuộn ngày và lane `usage_rollup` (5 phút, tính
   lại hôm nay và hôm qua cho tenant có hoạt động, ngày theo `window_for`); `GET /api/v1/usage/summary`
   (`usage.read`); màn `/usage` antd (Statistic, Table, Progress; không thư viện biểu đồ tới khi có
   quyết định), nhúng tab ở trang agent và quy trình.

## Tiêu chí chấp nhận

- [ ] R2.1: giá một model đổi ngày 2027-01-01 cho hai chi phí khác nhau; 1000 input có 800 cache_read →
      200 `input_uncached`; bậc trên 200k token.
- [ ] R2.2: mục giá chồng thời gian cùng khóa, loại sử dụng lạ, hay giá âm → bộ nạp từ chối.
- [ ] R2.3: tuyến nền tảng trả phí thiếu giá ở profile `uat` → khởi động lỗi; gỡ kiểm → test đỏ.
- [ ] R2.4 (UL12): đổi Bảng giá → dòng sử dụng cũ giữ `price_book_version` và chi phí cũ.
- [ ] R3.1: một lượt gọi chat ghi đúng một Bản ghi sử dụng mang đủ thuộc tính gán và `price_book_version`.
- [ ] R3.2: quyết toán hai lần cùng `(id, occurred_at)` → một dòng.
- [ ] R3.3 (UL5): adapter không báo usage → dòng `estimated` bằng ước tính, không 0; gỡ → test đỏ.
- [ ] R3.4: `dw_app` UPDATE hay DELETE trên cha và partition mới → bị từ chối.
- [ ] R3.5: tổng `usage_daily` một ngày bằng tổng `usage_events` ngày đó theo `window_for`; cuộn hai lần
      cùng kết quả; dòng quyết toán trễ hiện sau lượt cuộn kế.
- [ ] R3.6 (UL7): tenant A đọc partition theo tên với dòng của B → 0 dòng; `GET /api/v1/runs/{run_id}/usage`
      của run tenant B từ A → 404.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`; spec: R2.1 (giá trên route).
- `db/migrations/versions/0013_drop_model_usage_ledger.py:1-3`; spec: R3.1 (sổ đã bị gỡ, nay đảo lại).
- `db/migrations/sql/0013_partition_maintenance.sql:123`; spec: R3.4 (mảng một cha hôm nay);
  ADR-0121 (Proposed) quyết 1-2.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 02, 03, 09. `needs-info` vì DO-21 (đưa lại sổ) chờ Đạt
  ký — chính Đạt yêu cầu gỡ. Offboarding xuất sổ và không purge (cạnh chỉ-thêm); cột `user_id` là dữ
  liệu cá nhân, xóa theo yêu cầu chủ thể chờ compliance-pdpl.
