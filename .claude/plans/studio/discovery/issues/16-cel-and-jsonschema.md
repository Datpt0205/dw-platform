# 16 — Runtime CEL và chi phí kiểm JSON Schema trên đường nóng

Type: prototype
Status: resolved
Area: studio · Viết: 23/10/2026
FOG: FOG-50 `cel-runtime`, FOG-58 `jsonschema-cost`

## Câu hỏi

1. Runtime CEL Python nào (`cel-expr-python` 0.1.3, `common-expression-language` 0.10.0, `cel-python` 0.5.0) đăng ký
   được hàm Python và đối tượng có kiểu, ép được giới hạn chi phí, qua bộ conformance, có wheel manylinux cho image
   Python 3.12, và chấm tiêu chí chia sẻ trong giới hạn chi phí theo lô 1.000 bản ghi (FOG-50)?
2. Bản Rust dự phòng có bị chặn chi phí chỉ bằng kiểm AST trước khi chạy không, khi một lời gọi native không ngắt được
   từ Python (FOG-50)?
3. Kiểm `jsonschema` mỗi lời gọi tốn bao nhiêu (p95, lược đồ 30 thuộc tính); thu hẹp lược đồ theo bảo mật trường cho mỗi
   lượt chạy tốn bao nhiêu; `jsonschema-rs` (giấy phép, wheel, tương đương) có nên thay ở ingress và đầu ra của bước
   không (FOG-58)?

## Vì sao

Một ngôn ngữ biểu thức cho điều kiện, chuỗi có biến, điều kiện để lưu được, trường công thức và quy tắc chia sẻ dựa cả
vào runtime này. Kiểm lược đồ chạy ở mọi lời gọi công cụ và mọi sự kiện nhận.

## Mở khóa

- Spec: `workflow-nodes` (01, `ExpressionEngine`), `custom-objects` (điều kiện để lưu được), `record-access` (quy tắc
  chia sẻ, W2), `tools-and-skills` (01, executor tự kiểm JSON Schema), `workflow-triggers` (02, ingress).
- ADR: 0114 (Open 5), 0116.
- DO: DO-38 (bản C++ 0.1.x ghim chính xác làm mặc định, bản Rust dự phòng qua cùng bộ test hợp đồng), DO-37 (Đạt
  chốt 23/10/2026: "phải đúng", CEL với vector thử port từ si-platform).
- Ticket W1: `workflow-nodes/01`, `tools-and-skills/01` (P0).

## Dựng tối thiểu

Ba adapter `ExpressionEngine` mỏng qua cùng một bộ test hợp đồng: một hàm Python tùy biến, một đối tượng JSON có kiểu,
một biểu thức vượt chi phí, 1.000 bản ghi giả lập cho tiêu chí chia sẻ; cài wheel trong image `python:3.12-slim-bookworm`
(`infra/docker/worker.Dockerfile:41`). Phần JSON Schema: một lược đồ 30 thuộc tính, `jsonschema` 4.26.0
(`uv.lock:1947`) so với `jsonschema-rs` trên cùng bộ vector.

## Phép đo quyết định

| Đo                                                            | Ngưỡng hay so sánh                         | Quyết định                                       |
| ------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------ |
| Hàm Python, kiểu, conformance, wheel                          | Có hay không, theo từng runtime            | Runtime mặc định và dự phòng (ADR 0114, DO-38)   |
| Biểu thức vượt chi phí trên mỗi runtime                       | Dừng trong giới hạn, không treo tiến trình | Bản Rust có cần ranh giới tiến trình không       |
| Lô 1.000 bản ghi                                              | Chưa có ngưỡng; ghi p95                    | Quy tắc chia sẻ (W2) dùng được runtime này không |
| `jsonschema` p95 mỗi lời gọi; tương đương với `jsonschema-rs` | Ghi số; mọi vector cho cùng kết quả        | Giữ `jsonschema` hay đổi                         |

## Nguồn

- Brief B4, B5, B7a, B7b, B8b; `docs/adr/0114-cel-is-the-one-expression-language.md:110` (đo trước) và Open 5.
- [research.md](../research.md) mục 3 và 15 (runtime CEL chưa chọn; giới hạn chi phí có thật sự được ép không chưa
  kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 3 (FOG-58), không gồm `jsonschema-rs`: p95 của một lần kiểm `jsonschema` 4.26.0 trên lược đồ 30
  thuộc tính, với validator dựng sẵn và dựng mỗi lần; và chi phí thu hẹp lược đồ theo bảo mật trường mỗi lượt
  chạy.
- Cách làm: script đo trong venv của repo, 10.000 lần mỗi ca trên vector hợp lệ và không hợp lệ, qua cửa JSON
  Schema của nền tảng (`packages/python/dw_platform/src/dw_platform/application/json_schema.py`, có format
  `phone_vn`); thu hẹp: bỏ 5 rồi 15 trường khỏi `properties` và `required` của lược đồ 30 thuộc tính rồi dựng lại
  validator.
- Đầu ra: `## Answer` ở đây và một dòng vào mục Open của ADR-0116 (Accepted).
- Đạt khi: kiểm với validator dựng sẵn p95 ≤ 1 ms và một lần thu hẹp p95 ≤ 5 ms trên máy dev (đề xuất, chưa chốt:
  1/300 và 1/60 của ngân sách P95 300 ms trong `latency.md`). Trượt thì đề xuất cache validator theo (tenant, mã
  băm lược đồ) và đo lại.

## Answer

Câu 1-2 (FOG-50): đã trả lời ở ADR-0114 (Accepted), Amendments 2026-11-03 (Comments dưới). Câu 3 (FOG-58), không gồm
`jsonschema-rs` (đóng theo `CLAUDE.md` mục Required stack và workflow-nodes/05): đo ngày 5/11/2026 bằng
`scripts/bench_json_schema.py`, `jsonschema` 4.26.0, `referencing` 0.37.0, `rpds-py` 2026.6.3, 10.000 lần mỗi ca sau 200
lần làm nóng, hạt giống 16. Hai nơi chạy: venv của repo trên máy dev Windows 11 (Python 3.12.10, 16 luồng) và một bản
xuất sạch `git archive 5dea012e` cộng script, trong `python:3.12-slim-bookworm` (Python 3.12.16, `uv sync --frozen
--no-dev --package dw-studio`, Docker Desktop trên WSL2). Máy dùng chung với làn build 1 đang chạy test, nên cột max
nhiễu; p95 đọc được.

Đo qua cửa công cụ của `packages/python/dw_platform/src/dw_platform/application/json_schema.py` (`tool_validator_for`,
`tool_problems`: Draft 2020-12, tập format đóng có `phone_vn`, `Registry()` rỗng). Lược đồ: một lead 30 thuộc tính, đủ
mọi format của cửa (`phone_vn` hai trường, `email`, `uuid`, `date`, `date-time`, `tax_code_vn`), enum, pattern, mảng
`uniqueItems`, một đối tượng lồng, cả 30 `required`, `additionalProperties: false`. Vector: 500 hợp lệ và 500 không hợp lệ
(1-3 lỗi mỗi vector: số điện thoại cố định cũ, thiếu trường, trường lạ, sai kiểu, ngoài khoảng, enum, `date-time` không
offset, mã số thuế sai); script tự kiểm mọi vector hợp lệ qua và mọi vector lỗi bị từ chối. Thu hẹp: chính hàm
`narrowed` của RecordService (`dw_studio/records/application/schema_projector.py`) trên lược đồ tạo, sửa và truy vấn,
bỏ 5 rồi 15 trường khỏi `properties` và `required`.

| Ca (µs, p50 / p95 / p99)                                 | Windows, 3.12.10         | Linux, 3.12.16           |
| -------------------------------------------------------- | ------------------------ | ------------------------ |
| Dựng sẵn, `iter_errors` hết lỗi, hợp lệ                  | 279 / 495 / 585          | 295 / 499 / 661          |
| Dựng sẵn, `iter_errors` hết lỗi, không hợp lệ            | 328 / 655 / 877          | 297 / 483 / 653          |
| Dựng sẵn qua `tool_problems` (LRU ấm), hợp lệ            | 541 / 767 / 1.030        | 388 / 706 / 1.076        |
| Dựng sẵn qua `tool_problems` (LRU ấm), không hợp lệ      | 356 / 745 / 972          | 343 / 512 / 653          |
| Dựng mỗi lần qua `tool_problems`, hợp lệ                 | 17.224 / 23.368 / 28.514 | 11.901 / 17.353 / 24.169 |
| Dựng mỗi lần qua `tool_problems`, không hợp lệ           | 15.514 / 21.485 / 27.452 | 11.583 / 16.099 / 21.567 |
| `check_schema` riêng, lược đồ đầy đủ                     | 10.851 / 17.915 / 21.286 | 15.575 / 23.607 / 31.333 |
| Bỏ 5: chỉ thu hẹp (`narrowed`), không validator          | 19 / 39 / 55             | 16 / 28 / 44             |
| Bỏ 5: thu hẹp rồi dựng lại validator qua cửa (LRU trượt) | 11.268 / 17.375 / 20.950 | 10.706 / 16.106 / 20.841 |
| Bỏ 5: thu hẹp, LRU của cửa đã giữ                        | 46 / 92 / 122            | 46 / 87 / 119            |
| Bỏ 5: thu hẹp, cache (tenant, SHA-256 lược đồ) trúng     | 51 / 139 / 184           | 51 / 104 / 149           |
| Bỏ 5: thu hẹp, `evolve(schema=…)` từ validator đầy đủ    | 25 / 53 / 83             | 23 / 42 / 66             |
| Bỏ 15: chỉ thu hẹp                                       | 19 / 43 / 67             | 17 / 26 / 44             |
| Bỏ 15: thu hẹp rồi dựng lại qua cửa                      | 6.135 / 10.459 / 12.611  | 7.351 / 11.437 / 14.902  |
| Bỏ 15: LRU của cửa đã giữ                                | 30 / 39 / 58             | 43 / 112 / 154           |
| Bỏ 15: cache (tenant, SHA-256) trúng                     | 32 / 57 / 80             | 40 / 94 / 127            |
| Bỏ 15: `evolve`                                          | 24 / 53 / 69             | 27 / 59 / 84             |

Dòng Đạt khi:

- **Validator dựng sẵn p95 ≤ 1 ms: ĐẠT** ở cả hai, qua đúng cửa mà executor gọi: 0,77 ms (Windows) và 0,71 ms (Linux),
  biên chỉ khoảng 1,3 lần; p99 của ca hợp lệ chạm 1,03 và 1,08 ms. Khoảng 10 µs mỗi thuộc tính (docstring của cửa đo 27
  µs trên năm trường). `tool_problems` dựng lại JSON chuẩn của lược đồ ở mỗi lời gọi để tra LRU, khoảng 50-90 µs trong
  số đó; người gọi giữ validator thì không trả.
- **Một lần thu hẹp p95 ≤ 5 ms: TRƯỢT nếu dựng lại validator** (bỏ 5: 17,4 và 16,1 ms; bỏ 15: 10,5 và 11,4 ms). Gần như
  cả lần dựng là `check_schema` theo meta-schema 2020-12 (17,9 và 23,6 ms p95 trên lược đồ đầy đủ), không phải dựng đối
  tượng. Đo lại theo đề xuất: cache theo (tenant, mã băm lược đồ) khi trúng 0,14 và 0,10 ms p95, ĐẠT; nhưng lần trượt vẫn
  là 16-17 ms, và `evolve(schema=lược đồ đã thu hẹp)` từ validator đầy đủ đã kiểm (giữ format checker và registry rỗng;
  bỏ thuộc tính khỏi một lược đồ hợp lệ vẫn là lược đồ hợp lệ, nên không cần `check_schema` lại) tốn 0,05 và 0,06 ms p95
  mà không cần cache nào.

Quyết định (agent, theo ủy quyền 31/10/2026):

- Giữ `jsonschema` 4.26.0 ở cửa, ở ingress và ở đầu ra của bước; không đổi thư viện.
- Không thêm cache validator theo (tenant, mã băm lược đồ). Thiết kế đã chốt không dựng lại validator khi thu hẹp:
  tools-and-skills/03 bước 4 và field-security/02 bước 2 thu hẹp lược đồ model thấy ở mỗi lời gọi model, không đệm bản
  đã lọc, còn executor kiểm theo lược đồ đầy đủ đã ghim, mà LRU của cửa đã giữ validator. Chi phí thu hẹp mỗi lời gọi
  vì vậy là dòng "chỉ thu hẹp": 0,03-0,04 ms p95, đạt dòng 5 ms hơn trăm lần. Nếu một ticket sau cần validator của lược
  đồ đã thu hẹp, nó dựng bằng `evolve` từ validator đầy đủ của cửa (một hàm trong `json_schema.py`, ticket đó thêm),
  không qua `tool_validator_for` và không qua cache mới: không có lần trượt 16 ms nào và không có mục nào phải dọn
  (failure-modes #6).
- Nếu sai thì: một đường kiểm theo lược đồ đã thu hẹp mà dựng qua cửa sẽ trả 10-17 ms p95 ở mỗi hồ sơ bảo mật trường
  mới; khi đó thêm cache theo (tenant, SHA-256 của JSON chuẩn) như `TenantValidatorCache` của script, có giới hạn, và đo
  tỉ lệ trúng.

Phát hiện: một lần trượt LRU của cửa (`_cached_tool`, `maxsize=256`, chung mọi tenant trong một tiến trình) tốn 16-23 ms
p95, khoảng 5-8% ngân sách P95 300 ms của `latency.md`, cho lược đồ đầu vào và lại cho lược đồ đầu ra. Một worker phục vụ
nhiều công ty với hơn 256 lược đồ sống (công cụ × 2, cộng công cụ đối tượng mỗi `schema_version`) sẽ xoay vòng LRU và
trả lần dựng đó ở mỗi lời gọi. Chưa đo số lược đồ sống; ứng viên follow-up của tools-and-skills: đếm lược đồ sống mỗi
worker và tỉ lệ trúng, rồi định cỡ LRU.

Cách lặp lại: `uv run python scripts/bench_json_schema.py [--n 10000] [--out FILE.json]`; trong ảnh: bản xuất sạch,
`pip install uv==0.11.31`, `uv sync --frozen --no-dev --package dw-studio`, rồi cùng lệnh. Không vào `testpaths`, không
cần cơ sở dữ liệu. Chưa đo: ảnh worker thật với giới hạn 1 CPU của compose, `jsonschema-rs` (ngoài phạm vi).

## Comments

- 2026-11-03 (agent, theo ủy quyền 31/10/2026): FOG-50 đã đo ở gate của workflow-nodes/01 (Windows và ảnh
  `python:3.12-slim-bookworm`); số đo và quyết định ở `docs/adr/0114-cel-is-the-one-expression-language.md`,
  Amendments 2026-11-03: `cel-expr-python` là engine duy nhất, bản Rust không bị chặn chi phí (cần ranh giới tiến
  trình mà nó cũng không có bộ kiểm kiểu), nên bị bỏ; lô 1.000 điều kiện điển hình ≈ 13,5 ms trong tiến trình. FOG-58
  (`jsonschema`) vẫn mở.
- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Đã trả lời: FOG-50 (câu 1-2) ở workflow-nodes/01 (`73ee226`) và ADR-0114 (Accepted), Amendments 2026-11-03: `cel-expr-python` là engine duy nhất, bản Rust bị bỏ vì không chặn chi phí được nếu không có ranh giới tiến trình; lô 1.000 điều kiện điển hình khoảng 13,5 ms trong tiến trình. Phần `jsonschema-rs` của câu 3 đóng theo `CLAUDE.md` mục Required stack (`jsonschema`, ADR-0116) và gate workflow-nodes/05 (`377c9c9`); chi phí của `jsonschema` chưa ai đo.
- 2026-11-05 (agent, lane 2, theo ủy quyền 31/10/2026): resolved. Câu 3 đo bằng `scripts/bench_json_schema.py` trên
  Windows (3.12.10) và `python:3.12-slim-bookworm` (3.12.16): validator dựng sẵn p95 0,77 / 0,71 ms, đạt; thu hẹp rồi
  dựng lại 17,4 / 16,1 ms p95, trượt, gần hết là `check_schema`; cache (tenant, mã băm) trúng 0,14 / 0,10 ms, `evolve`
  0,05 / 0,06 ms. Không thêm cache: thiết kế (tools-and-skills/03 bước 4) chỉ thu hẹp lược đồ model thấy, 0,04 / 0,03 ms
  p95. Một dòng vào Open của ADR-0116. Nếu sai thì: xem Nếu sai thì trong Answer.
