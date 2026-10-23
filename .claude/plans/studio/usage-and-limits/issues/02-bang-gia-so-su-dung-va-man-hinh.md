# 02 — Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, UL5, UL7, UL12

## Mục tiêu

Một Bảng giá theo ngày hiệu lực là chủ duy nhất của giá; một Sổ sử dụng theo lượt gọi ghi mọi lượt gọi
model với đủ thuộc tính gán, chỉ thêm và idempotent; màn Mức độ sử dụng đọc chính sổ này (spec R2, R3).
Đảo việc gỡ `platform.model_usage_ledger` (DO-21.1, Đạt ký 23/10/2026), kèm bên đọc từ ngày đầu.

## Việc cần làm

1. `configs/pricing/price_book@1.0.0.yaml` và `dw_usage.domain.pricing.PriceBook.price(quantities, provider, model, at)`
   trả chi phí `Decimal`, phiên bản, id mục giá; loại sử dụng là tập đóng (`input_uncached`,
   `cache_read`, `cache_write_5m`, `cache_write_1h`, `output`, `image_input`, `audio_input`,
   `embedding_input`, `rerank_search_unit`, `extraction_page`, `transcription_second`,
   `sandbox_vcpu_second`, `sandbox_gb_second`, `server_tool_call`; bước mã tính vCPU và GB đặt trước nhân
   thời gian chạy, DO-45.1); `input_uncached = input_tokens − cache_read − cache_write`.
   Bộ nạp từ chối mục chồng thời gian cùng khóa, loại sử dụng lạ, giá âm. Dời giá khỏi `ModelRoute`
   (`model/profiles.py:54-55`) và `configs/models/*.yaml` trong cùng thay đổi; thay `route_cost`;
   `scripts/release_manifest.py` ghim Bảng giá (id, version, sha256); `settings.is_deployed`: tuyến nền
   tảng trả phí không có mục giá → từ chối khởi động.
2. Revision Alembic mới (id hex ngẫu nhiên; không downgrade `aefe7c1f5d9b`): `platform.usage_events` như
   mục Dữ liệu của spec, gồm `data_route_class`, `data_location`, `processor` có CHECK; phân vùng theo tháng
   với DEFAULT, RLS ở cha và DEFAULT cùng migration, policy drain `app.worker_drain` trên cha; index
   `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
   `(lease_id) WHERE lease_id IS NOT NULL`; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào
   trên partition nào, kể cả DEFAULT (DO-02.2).
3. Đăng ký `usage_events` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong
   migration này; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm).
   `drop_expired_partitions(cutoffs jsonb)` mỗi cha một mốc (NULL = không xóa). Thời hạn 395 ngày của
   `usage_events` do telemetry-and-audit/03 khai trong `retention@1.8.0` (một chủ tệp, DO-52); ticket này
   không sửa tệp retention.
4. `UsageLedgerPort.settle(event) -> bool` (`INSERT ... ON CONFLICT DO NOTHING`); `id`, `occurred_at`
   cấp trước lời gọi; thiếu số dùng của nhà cung cấp → `cost_source = 'estimated'` bằng ước tính, không 0.
5. Bên đọc từ ngày đầu: `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace) trả tổng theo
   thao tác, model, nguồn chi phí; `platform.usage_daily` cuộn ngày và lane `usage_rollup` (5 phút, tính
   lại hôm nay và hôm qua cho tenant có hoạt động, ngày theo `window_for`); `GET /api/v1/usage/summary`
   (`platform.usage.read`, đưa về `active` trong danh mục quyền; gộp theo workspace, agent, quy trình, mục
   đích, không theo người ở W1, DO-51.2); màn `/usage` antd (Statistic, Table, Progress; không thư viện biểu
   đồ ở v1, DO-42.3), nhúng tab ở trang agent và quy trình.

## Tiêu chí chấp nhận

- [ ] R2.1: giá một model đổi ngày 2027-01-01 cho hai chi phí khác nhau; 1000 input có 800 cache_read →
      200 `input_uncached`; bậc trên 200k token.
- [ ] R2.2: mục giá chồng thời gian cùng khóa, loại sử dụng lạ, hay giá âm → bộ nạp từ chối.
- [ ] R2.3: tuyến nền tảng trả phí thiếu giá ở profile `uat` → khởi động lỗi; gỡ kiểm → test đỏ.
- [ ] R2.4 (UL12): đổi Bảng giá → dòng sử dụng cũ giữ `price_book_version` và chi phí cũ.
- [ ] R3.1: một lượt gọi chat ghi đúng một Bản ghi sử dụng mang đủ thuộc tính gán, `price_book_version` và
      `data_route_class`, `data_location`, `processor` của lời gọi.
- [ ] R3.2: quyết toán hai lần cùng `(id, occurred_at)` → một dòng.
- [ ] R3.3 (UL5): adapter không báo usage → dòng `estimated` bằng ước tính, không 0; gỡ → test đỏ.
- [ ] R3.4: `dw_app` UPDATE hay DELETE trên cha và partition mới → bị từ chối.
- [ ] R3.5: tổng `usage_daily` một ngày bằng tổng `usage_events` ngày đó theo `window_for`; cuộn hai lần
      cùng kết quả; dòng quyết toán trễ hiện sau lượt cuộn kế.
- [ ] R3.6 (UL7): tenant A đọc bảng cha `usage_events` khi có dòng của B → 0 dòng của B;
      `GET /api/v1/runs/{run_id}/usage` của run tenant B từ A → 404.
- [ ] R3.7 (UL7): `dw_app` đọc hay ghi một partition của `usage_events` theo tên → `permission denied`, cả
      partition do lane tạo lẫn DEFAULT; cấp lại SELECT trên partition → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`; spec: R2.1 (giá trên route).
- `db/migrations/versions/0013_drop_model_usage_ledger.py:1-3`; spec: R3.1 (sổ đã bị gỡ, nay đảo lại).
- `db/migrations/sql/0013_partition_maintenance.sql:123`; spec: R3.4 (mảng một cha hôm nay);
  ADR-0121 (Accepted) quyết 1-2.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 02, 03, 09. `needs-info` vì DO-21 (đưa lại sổ) chờ Đạt
  ký — chính Đạt yêu cầu gỡ. Offboarding xuất sổ và không purge (cạnh chỉ-thêm); cột `user_id` là dữ
  liệu cá nhân, xóa theo yêu cầu chủ thể chờ compliance-pdpl.
- 2026-10-23 (agent): Đạt ký DO-21.1 ngày 23/10/2026, nên `needs-triage`. Áp thêm DO-02.2 (partition không
  quyền `dw_app`, R3.7), DO-52 (thời hạn ở tệp của telemetry-and-audit/03), DO-45.1 (đơn vị bước mã), DO-42.3,
  DO-51.2 và cột lộ trình của ADR-0123 (Accepted) cho compliance-pdpl/03. Xóa `user_id` theo yêu cầu chủ thể
  vẫn mở (ADR-0122 (Accepted) Open 1).
