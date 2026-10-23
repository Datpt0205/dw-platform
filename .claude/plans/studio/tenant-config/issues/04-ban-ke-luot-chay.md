# 04 — Bản kê lượt chạy: ghim mọi thứ lượt chạy dùng, phân giải theo bản kê

Status: needs-triage
Blocked by: 02, 03
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R3.6, TC15, TC21

## Mục tiêu

Mỗi lượt chạy có gốc là thành phần Studio ghim release ref, chế độ chạy, phiên bản gốc và bao đóng vào
một bản kê lưu một lần theo mã băm; trong lượt chạy, mọi phân giải chỉ đọc bản kê, kể cả khi tiếp tục ở
tiến trình khác sau 3 ngày chờ duyệt hay lâu hơn; không gì một lượt chạy còn trỏ tới bị dọn (spec R6,
TC15). Ticket 05 thêm mục điểm gắn vào cùng bản kê.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên), chép nguyên văn mục Dữ liệu của spec:
    - `platform.run_manifests`: khóa chính `(tenant_id, hash)`, `hash` khớp `^sha256:[0-9a-f]{64}$`,
      `body` jsonb NFC tối đa 1 MiB, `created_at timestamptz NOT NULL`; ghi bằng
      `INSERT ... ON CONFLICT DO NOTHING`; `dw_app` chỉ SELECT và INSERT.
    - `platform.run_manifest_keys`: `(tenant_id, manifest_hash)` FK tới `platform.run_manifests` ON
      DELETE CASCADE; `artifact_version_id` NOT NULL, FK RESTRICT tới `studio.artifact_versions`; mỗi FK
      một index; unique `(tenant_id, manifest_hash, artifact_version_id)`. Ticket 05 thêm
      `config_version_id` và CHECK đúng một cột khác NULL.
    - `platform.worker_runs.run_manifest_hash` NULL, khớp `^sha256:[0-9a-f]{64}$`, FK
      `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` ON DELETE RESTRICT, index
      `(tenant_id, run_manifest_hash)`. CHECK buộc lượt chạy có gốc Studio phải có bản kê đi cùng cột gốc
      Studio mà workflow-engine thêm (ADR-0113 (Proposed)).
    - RLS ENABLE và FORCE theo tenant cho hai bảng mới; grant khẳng định trong `test_privileges.py`;
      `test_rls_coverage.py` thấy cả hai.
    - Offboarding: `platform.run_manifests` vào `_ORDERED_FIRST` ngay sau `platform.worker_runs` (cạnh
      RESTRICT từ lượt chạy) và trước các mục `studio` của ticket 02 (`platform.run_manifest_keys` đi theo
      CASCADE, gỡ cạnh RESTRICT tới phiên bản).
2. Thân `dw.run_manifest/v1` (mô hình trong lõi `dw_studio`, `extra="forbid"`): `schema`,
   `release_manifest_ref`, `run_mode`, `root` (`kind`, `artifact_id`, `version_no`, `definition_hash`),
   `closure` (mỗi mục `kind`, `key`, `version`, `content_hash`, lấy từ `studio.definition_manifests` của
   gốc), `engine` (lấy từ mục registry của loại gốc; workflow-engine và agent-builder điền mục của họ,
   ADR-0109 (Proposed) quyết 8). Mã băm là `content_hash` của thân qua `dw_kernel.canonical`. Thân không
   chứa bí mật nào.
3. `RunManifestPort` khai trong `dw_agent_runtime` (bên dùng là cửa nhận lượt chạy), `RunManifestBuilder`
   của `dw_studio` đáp ứng, nối ở composition root: `build(tenant_id, root_version_id, run_mode)` ghi bản
   kê và các dòng `platform.run_manifest_keys` (gốc và mọi phiên bản trong bao đóng) rồi trả mã băm, trong
   giao dịch nhận lượt chạy; cửa nhận lượt chạy của workflow-engine gọi nó trước node đầu tiên.
4. `PinnedResolver` trong `dw_agent_runtime`: dựng từ các dòng bất biến của bản kê; khóa không có trong
   bản kê → `ConfigError` với `details.key`, không truy vấn phiên bản hiện hành. Mọi phân giải Studio
   trong lượt chạy Studio đi qua nó. Khi tiếp tục ở bất kỳ tiến trình nào, dựng lại từ
   `platform.worker_runs.run_manifest_hash`; `WorkflowRunnerPort.hosts` trả đúng cho lượt chạy Studio khi
   mọi phiên bản bản kê ghim đọc được từ database (ADR-0109 (Proposed) quyết 7).
5. Đo p95 thời gian dựng và ghi bản kê lúc nhận lượt chạy trên compose, bao đóng 50 thành phần, 1.000
   lượt; ghi số đo và cấu hình máy vào Comments (R6.6).

## Tiêu chí chấp nhận

- [ ] R6.1: lượt chạy gốc `fixture` có `run_manifest_hash` trước node đầu tiên; thân có release ref,
      `run_mode`, gốc với `definition_hash` và bao đóng; mã băm bằng `content_hash` của thân.
- [ ] R6.2: hai lượt chạy cùng nội dung → cùng `run_manifest_hash` và đúng một dòng
      `platform.run_manifests`; đổi `run_mode` → mã băm khác.
- [ ] R6.3 (TC15): trong lượt chạy Studio, hỏi khóa không ghim → `ConfigError`, repository phiên bản
      (spy) không được gọi; gỡ kiểm của `PinnedResolver` → test đỏ.
- [ ] R6.4 (TC15): lượt chạy chờ duyệt, niêm phong v2 của một thành phần trong bao đóng, tiếp tục ở tiến
      trình khác → lượt chạy dùng v1 đã ghim.
- [ ] R6.5 (TC15): DELETE phiên bản được bản kê ghim → lỗi FK; DELETE bản kê mà `platform.worker_runs`
      còn trỏ tới → lỗi FK.
- [ ] R6.6: p95 đo được ghi ở Comments và không quá 20 ms, hoặc Quyết định của spec có dòng Đạt chấp
      nhận số đo mới.
- [ ] R3.6 (TC21): `test_offboarding.py` purge tenant có lượt chạy ghim bản kê lên phiên bản Studio, tenant
      khác giữ nguyên; gỡ mục `platform.run_manifests` khỏi `_ORDERED_FIRST` → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:132`; spec: R6.4.
- `db/migrations/versions/0005_run_artifact_versions.py:41-51`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R3.6,
  TC21; ADR-0109 (Proposed) quyết 6-7.

## Comments

- 2026-10-23 (agent): từ B6 tenant-config 05. Mục lớp riêng của tenant (`overlay`) và `effective_hash`
  vào bản kê cùng lớp riêng ở W2.
