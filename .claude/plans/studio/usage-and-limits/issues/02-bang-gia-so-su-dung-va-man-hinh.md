# 02 — Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, UL5, UL7, UL12, UL16

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
   (`model/profiles.py:54-55`) và `configs/models/*.yaml` trong cùng thay đổi, sau `ModelProfile` v2 của
   model-connections/02 (ticket này chờ nó vì cả hai sửa hai tệp đó); thay `route_cost`;
   `scripts/release_manifest.py` ghim Bảng giá (id, version, sha256); `settings.is_deployed`: tuyến nền
   tảng trả phí không có mục giá → từ chối khởi động.
2. Revision Alembic mới (id hex ngẫu nhiên; không downgrade `aefe7c1f5d9b`): `platform.usage_events` như
   mục Dữ liệu của spec, gồm `data_route_class`, `data_location`, `processor` có CHECK; phân vùng theo tháng
   với DEFAULT, RLS ở cha và DEFAULT cùng migration, policy drain `app.worker_drain` trên cha; index
   `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
   `(lease_id) WHERE lease_id IS NOT NULL`; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào
   trên partition nào, kể cả DEFAULT (DO-02.2).
3. Đăng ký `usage_events` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong
   migration này; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm). Ticket này là
   chủ duy nhất ở W1 của `platform.drop_expired_partitions(cutoffs jsonb)`: viết lại thân hàm, mỗi bảng cha một
   mốc (NULL = không xóa), mốc dựng từ thời hạn dưới khóa `schema.table` của tệp chính sách retention mà lane
   `partitions` nạp; `test_a_partition_made_at_runtime_keeps_the_audit_log_append_only` (G1 của studio-skeleton)
   xanh qua bản viết lại. Cùng thay đổi đăng ký, thêm khóa `platform.usage_events` (395 ngày, số tạm UNVERIFIED,
   DROP PARTITION) vào bản kế tiếp của tệp chính sách retention theo định dạng của telemetry-and-audit:R5.6, nên
   studio-skeleton:R3.7 xanh ngay khi đăng ký. Tệp đi theo một chuỗi ticket bắt đầu từ ticket này, mỗi ticket một
   phiên bản mới (ticket này, ticket 03, telemetry-and-audit/03, agent-lifecycle/04, workflow-triggers/02,
   compliance-pdpl/04, agent-builder/04, compliance-pdpl/06; V4.P1, Quyết định tạm của spec); studio-skeleton/01 không
   sửa tệp mà đọc `retention@1.7.0` qua ánh xạ tạm của mô hình chính sách. Bản của ticket này là bản đầu có mục khóa
   `schema.table`: ticket này thêm mục đó, chuyển thời hạn của `audit_events` sang khóa `platform.audit_events` (1095
   ngày, `enforced` giữ nguyên), rồi bỏ ánh xạ tạm mà studio-skeleton/01 dùng.
4. Hàm `platform.purge_tenant_append_only(p_tenant uuid)` SECURITY DEFINER (search_path cố định, thu
   EXECUTE khỏi `PUBLIC`, cấp EXECUTE cho `dw_app`): từ chối với SQLSTATE 23514 khi `platform.tenants.status` của
   `p_tenant` khác `offboarding` (spec R3.9); không thì xóa dòng `tenant_id = p_tenant` ở mọi bảng có
   `append_only = true` trong sổ `platform.time_partitioned_tables`, trừ `platform.audit_events`, và trả số dòng
   theo bảng (spec R3.10). `SqlTenantOffboarding.purge_rows` của lane `offboarding` gọi hàm sau khi xuất, trong giao
   dịch xóa của nó và trước vòng DELETE bảng thường (`_ORDERED_FIRST` rồi phần còn lại), vì một bảng chỉ thêm có thể
   mang khóa ngoại `ON DELETE RESTRICT` tới một bảng thường, như `studio.conversation_messages` tới
   `studio.conversations` của agent-builder (spec R3.11); hàm xóa người dùng `service` của org-and-principals/03 đứng
   sau cùng, sau mọi bảng của công ty, và ticket đó chờ ticket này. Ticket này chờ foundations-hardening/07 vì cùng sửa
   lane đó. `STUDIO_EXCLUSIONS` thêm `platform.usage_events` với lý do
   "`dw_app` không DELETE; xóa khi offboarding bằng `platform.purge_tenant_append_only`" (studio-skeleton:R4.3);
   `platform.usage_daily` có policy `tenant_isolation_usage_daily` và DELETE cho `dw_app` để lane `offboarding` xóa
   như bảng thường (spec R3.8).
5. `UsageLedgerPort.settle(event) -> bool` (`INSERT ... ON CONFLICT DO NOTHING`); `id`, `occurred_at`
   cấp trước lời gọi; thiếu số dùng của nhà cung cấp → `cost_source = 'estimated'` bằng ước tính, không 0.
6. Bên đọc từ ngày đầu: `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace) trả tổng theo
   thao tác, model, nguồn chi phí; `platform.usage_daily` cuộn ngày và lane `usage_rollup` (5 phút, tính
   lại hôm nay và hôm qua cho tenant có hoạt động, ngày theo `window_for`); `GET /api/v1/usage/summary`
   (`platform.usage.read`, đưa về `active` trong `platform.permissions` bằng migration của ticket này theo quy
   ước của tenant-rbac/01, sau tenant-rbac/02 mà ticket này chờ; gộp theo workspace, agent, quy trình, mục
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
- [ ] R3.8: công ty `offboarding` có dòng trong `usage_events`, `usage_daily` → lane `offboarding` xuất mỗi dòng
      một lần rồi xóa hết; test phủ offboarding (studio-skeleton:R4.3) xanh với dòng `STUDIO_EXCLUSIONS` của
      `platform.usage_events`; bỏ lời gọi hàm khỏi lane → dòng `usage_events` còn, test đỏ.
- [ ] R3.9 (UL16): gọi `platform.purge_tenant_append_only` cho công ty `active` → 23514, 0 dòng xóa; gỡ kiểm
      trạng thái → test đỏ.
- [ ] R3.10 (UL16): với công ty `offboarding`, hàm xóa dòng của nó ở mọi bảng `append_only` của sổ, kể cả một
      bảng thử đăng ký trong test, còn dòng của công ty khác và mọi dòng `platform.audit_events` giữ nguyên.
- [ ] R3.11: một bảng `append_only` thử đăng ký trong test có khóa ngoại `ON DELETE RESTRICT` tới một bảng thường
      thử, công ty `offboarding` có dòng ở cả hai → lane `offboarding` xóa hết cả hai trong một giao dịch; dời lời gọi
      hàm ra sau vòng DELETE bảng thường → lỗi khóa ngoại, giao dịch xóa lùi, test đỏ.
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
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: ticket này là chủ duy nhất của
  `platform.drop_expired_partitions(cutoffs jsonb)` ở W1; thêm thời hạn của `platform.usage_events` vào tệp
  retention trong cùng thay đổi đăng ký, theo định dạng khóa `schema.table` của telemetry-and-audit (bản tệp đầu
  có mục đó nếu chưa có); hàm `platform.purge_tenant_append_only` và dòng `STUDIO_EXCLUSIONS` cho offboarding
  (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu); chờ model-connections/02 (cùng sửa `model/profiles.py`,
  `configs/models/*.yaml`: hồ sơ v2 trước, rồi dời giá) và foundations-hardening/07 (cùng sửa lane `offboarding`).
  Ticket này là ticket đầu sau studio-skeleton/01 thêm khóa vào tệp retention; các ticket sau (ticket 03,
  agent-lifecycle/04, telemetry-and-audit/03, compliance-pdpl/04, compliance-pdpl/06) mỗi ticket thêm một bản mới.
- 2026-10-24 (agent): vòng sửa thứ tư: thứ tự của chuỗi tệp retention theo Quyết định tạm của spec, thay danh sách ở
  dòng trên: studio-skeleton/01, ticket này, ticket 03, telemetry-and-audit/03, agent-lifecycle/04,
  workflow-triggers/02, compliance-pdpl/04, agent-builder/04, compliance-pdpl/06; bản của ticket này chắc chắn là bản
  đầu có mục khóa `schema.table` (kể cả `platform.audit_events`). Chờ tenant-rbac/02 (Quyết định tạm của spec về
  đăng ký khóa).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các Quyết định tạm cùng ngày của spec: chuỗi tệp retention bắt
  đầu từ ticket này, studio-skeleton/01 không sửa tệp mà đọc `retention@1.7.0` qua ánh xạ tạm (V4.P1), thay danh
  sách của hai dòng trên; lời gọi `platform.purge_tenant_append_only` đứng trước vòng DELETE bảng thường trong giao
  dịch xóa (spec R3.11), và org-and-principals/03 chờ ticket này vì hàm xóa người dùng `service` của nó chạy sau cùng.
