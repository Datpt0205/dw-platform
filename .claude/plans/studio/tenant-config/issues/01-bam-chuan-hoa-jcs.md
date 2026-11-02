# 01 — Băm chuẩn hóa JCS (RFC 8785) một chủ trong dw_kernel

Status: ready-for-agent
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, G2, G3, TC8

## Mục tiêu

Mọi mã băm của Studio (Mã băm nội dung, Mã băm định nghĩa, bản kê lượt chạy) có đúng một nơi sinh:
`dw_kernel.canonical`, chỉ dùng stdlib, ra bytes RFC 8785 trên tài liệu NFC không số thực, và từ chối
có mã thay vì sửa ngầm (spec R1, TC8). Khóa chống lặp của executor và ref của release manifest giữ
nguyên (G2, G3). Ticket này là chủ duy nhất của băm RFC 8785 cho cả agent-lifecycle. "Mã băm của
Studio" là mã băm của vỏ phiên bản `studio.*`, bản kê định nghĩa và bản kê lượt chạy (ADR-0109 (Accepted) quyết 3,
sửa đổi 2026-11-02); mã băm quy trình của DW (`workflow_sha256`) và `canonical_json` của kernel không phải mã băm
Studio và giữ nguyên (bước 4).

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
    - `to_nfc(value)`: chuẩn NFC đệ quy cho chuỗi và khóa, để biên API gọi trước khi kiểm (bên đọc:
      `save_draft` của ticket 02); `canonical_bytes` không bao giờ gọi nó (hàm băm từ chối, không sửa).
      Trả bản mới, không sửa đầu vào. NẾU hai khóa của cùng một object trùng nhau sau NFC (ví dụ `"é"` NFC
      và NFD), THÌ `to_nfc` từ chối bằng `CanonicalError` lý do `nfc_key_collision`, `pointer` tới object
      đó, không bao giờ chọn một trong hai giá trị.
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
    - `to_nfc`: tài liệu NFD lồng (khóa và giá trị, trong object và list) ra bản NFC có `content_hash`
      bằng `content_hash` của chính tài liệu viết sẵn ở NFC, đầu vào không đổi; hai khóa trùng sau NFC →
      `nfc_key_collision`; bỏ phép kiểm trùng thì test này đỏ (một giá trị mất lặng lẽ);
    - bằng chứng mutation: đổi sắp khóa sang code point thì test vi sai đỏ trên khóa ngoài BMP; ghi kết
      quả vào Comments.
4. Test đối chiếu: `canonical_bytes` của `contracts/release/manifest.json` bỏ `git_sha` bằng đúng bytes
   mà `manifest_ref` băm (`scripts/release_manifest.py:249-254`). Không sửa `manifest_ref` và
   `canonical_hash` của executor (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`):
   khóa chống lặp của lượt chạy đang dở dựa vào nó (ADR-0108 (Accepted)). Cũng không sửa, và không
   chuyển sang `dw_kernel.canonical`: `workflow_sha256`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:63-68`; wf-ai:R6, wf-lite:R6.14),
   hex trần trên `canonical_json`, vì nó là `content_sha256`/`base_sha256` đã lưu của bản nháp và phiên bản quy
   trình DW, định danh của approval `dw.workflow.publish` đang chờ và, với phiên bản của tenant,
   `PinnedWorkflow.sha256` mà lượt wf-lite ghi vào `definition_hash` của lượt đang chạy hay đang chờ, và tài
   liệu gói có số thực (`minimum`, `maximum`: `wflite/document.py:46-47`) mà `ensure_hashable` từ chối; nó
   chuyển sang `content_hash` khi phiên bản quy trình DW vào vỏ `studio.*` (ADR-0109 (Accepted) sửa đổi
   2026-11-02; ADR-0120 (Accepted) sửa đổi 2026-11-02 ghi nó chưa là thành phần Studio). `dw_kernel.pagination.canonical_json`
   và các bên gọi của nó (con trỏ phân trang, `filters`, khóa cache `json_schema`, `work_item`) cũng giữ nguyên:
   chúng không phải mã băm Studio.
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
- [ ] R1.4 (TC8): `to_nfc` cho NFD lồng ra cùng `content_hash` với dạng NFC; hai khóa trùng sau NFC →
      `nfc_key_collision`, không giá trị nào bị chọn; bỏ phép kiểm trùng thì test đỏ.
- [ ] R1.1 (TC8): phạm vi một chủ: `workflow_sha256` và `dw_kernel.pagination.canonical_json` không đổi dòng
      nào (`git diff` của ticket không chạm hai hàm đó); test của wf-ai và wf-lite vẫn xanh.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`; spec: G2.
- `scripts/release_manifest.py:249-254`; spec: R1.5, G3.
- `pyproject.toml:252`; spec: R1, TC8; ADR-0109 (Accepted) quyết 3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:63-68`; ADR-0109 (Accepted) sửa đổi
  2026-11-02; ADR-0120 (Accepted) sửa đổi 2026-11-02.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 01 và B10a agent-lifecycle 03; agent-lifecycle dùng hàm
  này, không viết hàm băm thứ hai.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B1: Mục tiêu nói "mọi mã băm của Studio" một nơi sinh
  trong khi `workflow_sha256` của wf-ai (2/11/2026) băm bản nháp, phiên bản và approval của quy trình DW bằng
  `canonical_json`; người dựng phải đoán có chuyển nó không. Sửa: Mục tiêu định nghĩa phạm vi, bước 4 và một tiêu
  chí giữ nguyên `workflow_sha256` và `canonical_json`, ADR-0109 (Accepted) thêm sửa đổi 2026-11-02, spec thêm dòng Quyết
  định. Nếu sai thì: một ticket riêng chuyển `workflow_sha256` sang `content_hash`, băm lại dòng đã lưu và đưa
  approval đang chờ về nháp.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B2: `to_nfc` không nói gì khi hai khóa trùng sau NFC
  (một giá trị mất lặng lẽ ở `save_draft` của ticket 02) và không có test. Sửa: bước 1 từ chối
  `nfc_key_collision`, bước 3 và một tiêu chí có test, kể cả test đỏ khi bỏ phép kiểm. Nếu sai thì: biên API từ
  chối tài liệu không NFC thay vì chuẩn hóa, và `to_nfc` bị bỏ.
- 2026-11-02 (agent): ghi chú MEDIUM của gate cho người dựng, chưa sửa: (M1) neo đã trôi từ `ab33703`:
  `canonical_hash` nay ở `executor.py:190-194`, `manifest_ref` ở `scripts/release_manifest.py:274-279`, hợp đồng
  "Kernel is pure" ở `pyproject.toml:260`; tìm theo tên. (M2) test vi sai chỉ đỏ với mutation code point khi cùng
  một object có hai khóa khác nhau đầu tiên ở một ký tự ngoài BMP và một ký tự U+E000-U+FFFF (ví dụ `"דּ"` và
  emoji); U+FFFF chỉ ở giá trị thì mutation vẫn xanh. (M3) khóa của release manifest đều ASCII, nên với R1.5
  mutation phải là bỏ hay đảo sắp khóa, không phải UTF-16 sang code point; đặt test R1.5 trong
  `apps/api/tests/unit/test_release_manifest.py` (đã nạp script theo đường dẫn), không trong test của kernel. (M4)
  tài liệu lồng quá sâu hay có vòng tham chiếu ra `RecursionError` chứ không `CanonicalError`; hoặc giới hạn độ sâu
  có mã, hoặc ghi rằng biên đọc JSON đã chặn. (M5) `RunContext.definition_hash` (`contracts.py:123`,
  `^[0-9a-f]{64}$`) và `definition_hash` của wf-lite là hex trần, còn `HASH_PATTERN` có tiền tố `sha256:`;
  ticket 01 không đụng, ticket 04 phải hòa hai dạng. LOW: "vector không số thực của RFC 8785" là ví dụ sắp khóa
  mục 3.2.3 và ví dụ mục 3.2.2 bỏ `numbers`; `pointer` theo RFC 6901 (thoát `~0`, `~1`).
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc hai chỗ sửa B1 và B2: không CRITICAL mới; B1 đóng
  (phạm vi ở Mục tiêu, bước 4, một tiêu chí, ADR-0109 (Accepted) sửa đổi 2026-11-02 và Quyết định của spec nói
  cùng một điều; dẫn chứng số thực của tài liệu gói sửa thành `wflite/document.py:46-47`), B2 đóng.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
