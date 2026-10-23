# 01 — Băm chuẩn hóa JCS (RFC 8785) một chủ trong dw_kernel

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, G2, G3, TC8

## Mục tiêu

Mọi mã băm của Studio (Mã băm nội dung, Mã băm định nghĩa, bản kê lượt chạy) có đúng một nơi sinh:
`dw_kernel.canonical`, chỉ dùng stdlib, ra bytes RFC 8785 trên tài liệu NFC không số thực, và từ chối
có mã thay vì sửa ngầm (spec R1, TC8). Khóa chống lặp của executor và ref của release manifest giữ
nguyên (G2, G3). Ticket này là chủ duy nhất của băm RFC 8785 cho cả agent-lifecycle.

## Việc cần làm

1. Tạo `packages/python/dw_kernel/src/dw_kernel/canonical.py`, chỉ import stdlib (hợp đồng
   import-linter "Kernel is pure (stdlib only)", `pyproject.toml:252`):
    - `CanonicalError(DomainError)` (mã `validation_failed`), `details` gồm `reason` và `pointer` (con
      trỏ JSON tới chỗ hỏng), không bao giờ chứa giá trị.
    - `ensure_hashable(value)`: chỉ nhận `dict` khóa `str`, `list`, `str`, `int`, `bool`, `None`. Từ
      chối: `float` (kể cả `1.0`), NaN, Infinity → `float_forbidden`; `int` có trị tuyệt đối vượt
      2^53−1 → `integer_out_of_range` (2^53−1 nhận, 2^53 từ chối); chuỗi hay khóa không ở NFC →
      `not_nfc`; khóa không phải `str` → `key_not_string`; surrogate lẻ → `lone_surrogate`; kiểu khác
      (`Decimal`, `bytes`, `datetime`) → `type_forbidden`. Số không nguyên đi trong tài liệu dưới dạng
      chuỗi thập phân (ADR-0109 (Accepted) quyết 3).
    - `canonical_bytes(value) -> bytes`: gọi `ensure_hashable`, sắp khóa theo đơn vị mã UTF-16 (RFC 8785
      mục 3.2.3), rồi `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` trên khóa đã sắp,
      mã hóa UTF-8.
    - `content_hash(value) -> str`: `sha256:` cộng 64 chữ số hex của `canonical_bytes`; `HASH_PATTERN`
      là `^sha256:[0-9a-f]{64}$`.
    - `to_nfc(value)`: chuẩn NFC đệ quy cho chuỗi và khóa, để biên API gọi trước khi kiểm;
      `canonical_bytes` không bao giờ gọi nó (hàm băm từ chối, không sửa).
    - Docstring ghi: băm giá trị ứng dụng đã kiểm, không bao giờ băm `jsonb::text` hay đầu ra
      `json.dumps(sort_keys=True)`.
2. `rfc8785==0.1.4` vào nhóm `dev` của root `pyproject.toml`, không bao giờ vào `dependencies` của
   `dw_kernel`; cập nhật `uv.lock`. Gói này chỉ là bộ đối chứng trong test.
3. `packages/python/dw_kernel/tests/unit/test_canonical.py`:
    - các vector không số thực của RFC 8785;
    - test vi sai với `rfc8785.dumps` trên 20.000 tài liệu sinh có seed cố định: ký tự điều khiển,
      U+007F, U+2028, U+FFFF, emoji ở khóa (ngoài BMP), tiếng Việt NFC, dấu nháy và gạch chéo ngược ở cả
      khóa lẫn giá trị, số nguyên tới ±(2^53−1);
    - một test âm cho mỗi mã lỗi ở bước 1, khẳng định không có mã băm nào được trả;
    - bằng chứng mutation: đổi sắp khóa sang code point thì test vi sai đỏ trên khóa ngoài BMP; ghi kết
      quả vào Comments.
4. Test đối chiếu: `canonical_bytes` của `contracts/release/manifest.json` bỏ `git_sha` bằng đúng bytes
   mà `manifest_ref` băm (`scripts/release_manifest.py:249-254`). Không sửa `manifest_ref` và
   `canonical_hash` của executor (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`):
   khóa chống lặp của lượt chạy đang dở dựa vào nó (ADR-0108 (Accepted)).
5. `make test-architecture` xanh: kernel vẫn chỉ dùng stdlib.

## Tiêu chí chấp nhận

- [ ] R1.1 (TC8): vector RFC 8785 và 20.000 ca vi sai cho bytes trùng `rfc8785.dumps`; đổi sắp khóa sang
      code point thì test vi sai đỏ trên khóa ngoài BMP (ghi Comments).
- [ ] R1.2 (TC8): `{"a": 1.0}`, `float("nan")`, `float("inf")` → `float_forbidden`, không trả mã băm.
- [ ] R1.3 (TC8): `2**53 - 1` và `-(2**53 - 1)` băm được; `2**53` và `-(2**53)` → `integer_out_of_range`.
- [ ] R1.4 (TC8): "Ngưỡng điểm" dạng NFD ở giá trị và ở khóa → `not_nfc`; cùng chuỗi ở NFC băm được;
      bỏ kiểm NFC thì hai dạng cho hai mã băm khác nhau và test đỏ.
- [ ] R1.5: bytes của release manifest đã commit (bỏ `git_sha`) trùng bytes mà `manifest_ref` băm; sửa
      thứ tự sắp của một bên trong test thì test đỏ.
- [ ] G2: `test_replay_returns_cached_output_without_reexecution` vẫn xanh và `canonical_hash` của
      executor không đổi dòng nào.
- [ ] G3: `test_manifest_ref_is_stable_and_ignores_git_sha` vẫn xanh; `contracts/release/manifest.ref`
      không đổi.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`; spec: G2.
- `scripts/release_manifest.py:249-254`; spec: R1.5, G3.
- `pyproject.toml:252`; spec: R1, TC8; ADR-0109 (Accepted) quyết 3.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 01 và B10a agent-lifecycle 03; agent-lifecycle dùng hàm
  này, không viết hàm băm thứ hai.
