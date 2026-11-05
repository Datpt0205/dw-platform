# 10 — Đầu số di động trước đợt đổi 2018 và một chủ cho luật số điện thoại

Status: resolved
Area: studio
Yêu cầu: R6.2, R7.3, CO17

## Mục tiêu

Một lead ghi số 11 chữ số cũ (`0168 456 7890`) và một lead ghi số mới của cùng người (`038 456 7890`) là một Lead
(R7.3), và RecordService không lưu một số không còn dùng được làm E.164 (R6.2). Hôm nay bộ chuẩn hóa của custom-objects/03
nhận cả 21 mã cũ và lưu `+841684567890`, khóa không bao giờ trùng số mới (discovery/10 (a): 315/315 chuỗi). Cùng lúc,
luật số điện thoại Việt Nam có ba bản trong mã nền tảng không ai so với nhau (failure-modes #2), nên ticket này cho nó
một chủ.

## Việc cần làm

1. Bảng đổi mã của Quyết định số 798/QĐ-BTTTT ngày 25/5/2018 (Bộ Thông tin và Truyền thông, mục II.2.1, đổi 21 mã H2H,
   giữ bảy số cuối; bản ký `https://mic.mediacdn.vn/Upload_Moi/VanBan/qd-798signed.PDF`, đọc 5/11/2026): MobiFone 120,
   121, 122, 126, 128 → 70, 79, 77, 76, 78; VinaPhone 123, 124, 125, 127, 129 → 83, 84, 85, 81, 82; Viettel 162-169 →
   32-39; Vietnamobile 186, 188 → 56, 58; Gmobile 199 → 59. Một số Việt Nam có 10 chữ số sau `84` bắt đầu bằng một trong
   21 mã thì đổi sang mã mới cộng bảy số cuối; mọi dạng viết đã nhận hôm nay (`0`, `+84`, `0084`, `84` trần, cách, chấm,
   gạch, ngoặc) đi cùng đường, dạng bị từ chối hôm nay (`+84 (0)…`, `/`) vẫn bị từ chối.
2. Mã đang cấp: sau bảng, phần sau `84` phải thuộc một họ của kế hoạch số hiện hành, di động `[35789]` cộng tám chữ số
   hay cố định `2` cộng chín chữ số, đúng họ mà `phone_vn` (`json_schema.py:74`) và oracle (`measure.py:38`) đã đọc; số
   `+84` ngoài họ (mã `1xx` không có trong bảng, số cố định trước đợt đổi mã vùng 2017 nằm ngoài họ) → `invalid_type`,
   không mã lỗi mới. Số nước khác giữ luật hôm nay (E.164, 8 tới 15 chữ số).
3. Một chủ: `packages/python/dw_kernel/src/dw_kernel/phone.py`, thư viện chuẩn (hợp đồng "Kernel is pure"), mà cả
   `dw_platform` và `dw_studio` import được: hàm chuẩn hóa về E.164 và phép hỏi "là số Việt Nam". `coerce_input` của
   `packages/python/dw_studio/src/dw_studio/records/domain/values.py` và định dạng `phone_vn` của
   `packages/python/dw_platform/src/dw_platform/application/json_schema.py` cùng đọc nó, không giữ biểu thức nào của
   riêng mình: `phone_vn` nhận đúng chuỗi mà hàm đưa về một số `+84` (hôm nay nó từ chối `84900000101` và `0084…` mà
   RecordService nhận). `phone_vn` chỉ kiểm, không đổi giá trị: công cụ nào gọi hay nhắn tới số đó tự chuẩn hóa bằng
   cùng hàm.
4. Oracle `tests/e2e/marketing_pilot/measure.py` giữ bản riêng có chủ ý: harness không import nội bộ nền tảng
   (marketing-pilot R1.2, MP17), và một oracle đọc chủ sẽ đo chủ với chính nó (marketing-pilot/01, H3). Nó thêm bảng 21
   mã và dạng `0084`. Một test đơn vị trong `packages/python/dw_studio/tests/unit/` chạy một bộ vector qua
   `dw_kernel.phone`, `coerce_input`, `phone_vn` và oracle, đỏ khi một bản lệch; để test import được oracle,
   `tests/e2e` vào `pythonpath` của pytest và `mypy_path` của mypy. Bộ sinh không đổi: tập hạt giống và số của README
   giữ nguyên.
5. Không chuyển dữ liệu: bản ghi đã lưu số mã cũ (chỉ có từ custom-objects/03, 5/11/2026, trên cơ sở dữ liệu phát triển
   và thử) giữ nguyên tới lần ghi kế tiếp của nó. Không thêm `phonenumbers` (discovery/10 (a)).

## Tiêu chí chấp nhận

- [x] R6.2: `0168 456 7890`, `+84 168 456 7890`, `841684567890` và `01684567890` lưu `+84384567890`; mỗi mã trong 21 mã
      có một vector ở mỗi dạng; gỡ một dòng khỏi bảng → test của mã đó đỏ; số mã mới (`038 456 7890`) không đổi.
- [x] R7.3 (CO17): hai lần Tạo hoặc cập nhật song song với `0168 456 7890` và `038 456 7890` → một dòng; gỡ bảng → hai
      dòng, test đỏ.
- [x] R6.2: `phone_vn`, `coerce_input` và oracle đọc cùng luật: một test chạy cùng bộ vector qua cả bốn và đỏ khi một
      bên đổi luật mà bên kia không; `84900000101` và `0084 900 000 101` qua `phone_vn` → hợp lệ.
- [x] R6.2: `+84 130 123 4567` (mã `1xx` ngoài bảng) và `04 3825 1234` (số cố định trước 2017) → 422 `invalid_type`,
      không lưu; `+1 415 555 0100` vẫn lưu `+14155550100`; quyết định về số cố định cũ ghi trong Comments cùng văn bản
      nguồn.
- [x] Xong: `uv run python -m pytest -m unit packages/python/dw_studio packages/python/dw_platform packages/python/dw_kernel tests/e2e/marketing_pilot` xanh.

## Nguồn

- `packages/python/dw_studio/src/dw_studio/records/domain/values.py:100`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/application/json_schema.py:77`; spec: R6.2.
- `tests/e2e/marketing_pilot/measure.py:48`; spec: R7.3.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md` mục Answer (a).

## Comments

- 2026-11-05 (agent, lane 2): viết từ discovery/10 (a). Đo: 70.000/70.000 chuỗi của bộ sinh cùng E.164 ở oracle,
  RecordService và `phonenumbers` 9.0.42; 315 chuỗi của 21 mã cũ: 0 bộ nào đưa về số mới, RecordService nhận cả 315.
- 2026-11-05 (agent, lane 2, theo ủy quyền 31/10/2026): gate `checking-plan-readiness`, builder check (không migration,
  không route): 0 CRITICAL, 3 HIGH đã sửa. (H1) "Mã đang cấp" có ba cách đọc: chọn họ của kế hoạch số mà `phone_vn` và
  oracle đã đọc (Việc 2), không danh sách mã từng nhà mạng, để mã mới cấp không bị từ chối. Nếu sai thì: một danh sách
  mã có văn bản nguồn thay biểu thức họ, ở chủ. (H2) Bản ghi đã lưu mã cũ: không chuyển (Việc 5), vì chỉ có trên cơ sở
  dữ liệu phát triển và thử, còn chuyển cần quyết gộp khi hai bản ghi đổi về một số. Nếu sai thì: một ticket chuyển qua
  RecordService, gộp trùng theo R7.3. (H3) Oracle chép bảng thì hai bảng: test bốn bên của Việc 4 đỏ khi lệch. Nếu sai
  thì: oracle đọc bảng của chủ và MP17 ghi ngoại lệ. MEDIUM: (M1) `phone_vn` kiểm mà không đổi giá trị (Việc 3). (M2) bộ
  sinh không có đầu số cũ nên KQ3 không chạm bảng; bảng của oracle được kiểm qua test bốn bên. (M3) hàm `phone.e164` của
  workflow-nodes (discovery/10, Phụ thuộc) chưa dựng; khi dựng nó đọc `dw_kernel.phone`. (M4) từ chối dùng
  `invalid_type`, không đổi bảng mã lỗi. Đã có câu trả lời: giá trị lọc trên trường số điện thoại đi qua cùng bộ ép
  kiểu (ticket 04, Việc cần làm, dòng 31).
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, lane 2, theo ủy quyền 31/10/2026): số cố định trước đợt đổi mã vùng 2017. Văn bản: Quyết định số
  2036/QĐ-BTTTT ngày 21/11/2016 của Bộ Thông tin và Truyền thông, "Kế hoạch chuyển đổi mã vùng" (59/63 tỉnh, giai đoạn
  1 từ 0 giờ 11/2/2017); tìm 5/11/2026 không thấy bản trên trang của Bộ (`mst.gov.vn`, `mic.gov.vn`), chỉ bản của bên
  thứ ba (`https://luatvietnam.vn/thong-tin/quyet-dinh-2036-qd-btttt-bo-thong-tin-va-truyen-thong-110635-d1.html`,
  `https://hethongphapluat.com/decision-no-2036-qd-btttt-dated-november-21-2016.html`), nên phụ lục mã vùng không đọc
  làm nguồn. Quyết định: không đổi, từ chối `invalid_type` số cố định cũ nằm ngoài họ của kế hoạch hiện hành
  (`04 3825 1234`, `0511 382 1234`; hôm nay lưu `+84438251234`), giữ nguyên số cố định mã `2x` hiện hành. Lý do không
  đổi kể cả khi có phụ lục: một số cũ của TP.HCM `08 3825 1234` trùng từng chữ số với số di động VinaPhone
  `083 825 1234` (123 → 83 theo QĐ 798), số cũ Hải Phòng `031 …` rơi vào họ `3` của Viettel, nên không bảng nào tách
  được; các số đó đọc là số di động hiện hành như hôm nay. Từ chối thì người nhập sửa được, gộp sai thì không
  (failure-modes #7). Nếu sai thì: một bảng mã vùng cũ, từ bản chính thức của phụ lục, chỉ cho mã nằm ngoài họ.
- 2026-11-05 (agent, lane 2): resolved. Chủ: `packages/python/dw_kernel/src/dw_kernel/phone.py` (`normalize_phone`,
  `is_vietnamese_phone`, `PRE_2018_MOBILE_CODES`), thư viện chuẩn; `values.py` bỏ hàm và hai biểu thức của mình,
  `json_schema.py` bỏ `_PHONE_VN`; oracle thêm bảng (viết theo mạng) và `0084`; `pyproject.toml` thêm `tests/e2e` vào
  `pythonpath` và `mypy_path`, không phụ thuộc mới. Test: `packages/python/dw_kernel/tests/unit/test_phone.py` (21 mã ×
  9 dạng, bảng so với danh sách viết tay, bốn dạng của tiêu chí, số đang dùng, số bị từ chối, 217 ca);
  `packages/python/dw_studio/tests/unit/test_phone_rule.py` (bốn bên trên 845 vector: 104 số của `TEST_RANGE` × 7 dạng
  của bộ sinh, 21 mã × 5 dạng, 12 ca biên; một test chặn bộ vector chỉ có một đáp án); `test_record_service.py`
  `test_r7_3_co17_an_old_and_a_new_writing_of_one_number_race_to_one_record` (hai upsert song song `0168…` và `038…` →
  một dòng `+8438…`). Phá tay, bản gốc trong scratchpad, sha256 so lại: bỏ dòng 168 khỏi bảng của chủ → 20 đỏ; bỏ phép
  kiểm họ → 13 đỏ; `phone_vn` về biểu thức cũ → 213 đỏ; `coerce_input` tự chuẩn hóa → 532 đỏ; oracle bỏ 168 → 5 đỏ;
  oracle đổi 199 → 5 đỏ; chủ bỏ phép đổi mã → test đua đỏ (hai dòng). `mutations/10.yaml` sáu mục.
  Cổng trên bản xuất sạch của `a0c530b5` cộng thay đổi (cây chung có việc dở của lane 1 làm hỏng `kinds.py`): unit
  toàn repo 4836 qua, 9 bỏ qua, phủ 76,29%; `test_record_service.py` 28/28; mypy Linux 913 tệp sạch; lint-imports 16
  hợp đồng giữ ("Kernel is pure" giữ: `dw_kernel.phone` chỉ dùng `re` và `types`); verify_invariants,
  verify_architecture, `release_manifest --check` xanh; ruff và format sạch. `reviewing-feature-security`: (3) `phone_vn`
  nhận rộng hơn (`84…`, `0084…`, mã cũ) nhưng chỉ là phép kiểm, chưa công cụ nào trong `configs/` khai nó; (4) đầu vào
  công cụ do mô hình viết vẫn qua cùng phép kiểm, lỗi không nhắc giá trị; (6) số ngoài kế hoạch bị từ chối, không lưu
  nguyên dạng; (1), (2), (5) không áp dụng: không bảng, không quyền, không audit mới. Nợ lúc đóng hàng:
  `scripts/mutate.py` cho `mutations/10.yaml`; P50/P95/P99 của tạo, `PATCH` và upsert so với điểm bắt đầu hàng (phép
  chuẩn hóa thêm một tra bảng, không câu truy vấn); `/code-review`; `checking-plan-consistency` của vùng (marketing-pilot
  MP10 nay phát lại cùng luật có bảng 21 mã).
  Sót của lane: `4ad791f8` được đẩy với hai chú thích viết tên văn bản tiếng Việt ngoài dấu backtick, `check_hygiene`
  báo sau khi lệnh đẩy chạy cùng chuỗi; commit kế tiếp sửa, `--base a0c530b5` về 0. Từ nay kiểm hygiene trước, đẩy
  trong một lệnh riêng.
