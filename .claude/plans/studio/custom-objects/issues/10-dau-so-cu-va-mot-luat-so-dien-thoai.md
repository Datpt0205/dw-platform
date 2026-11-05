# 10 — Đầu số di động trước đợt đổi 2018 và một chủ cho luật số điện thoại

Status: ready-for-agent
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

- [ ] R6.2: `0168 456 7890`, `+84 168 456 7890`, `841684567890` và `01684567890` lưu `+84384567890`; mỗi mã trong 21 mã
      có một vector ở mỗi dạng; gỡ một dòng khỏi bảng → test của mã đó đỏ; số mã mới (`038 456 7890`) không đổi.
- [ ] R7.3 (CO17): hai lần Tạo hoặc cập nhật song song với `0168 456 7890` và `038 456 7890` → một dòng; gỡ bảng → hai
      dòng, test đỏ.
- [ ] R6.2: `phone_vn`, `coerce_input` và oracle đọc cùng luật: một test chạy cùng bộ vector qua cả bốn và đỏ khi một
      bên đổi luật mà bên kia không; `84900000101` và `0084 900 000 101` qua `phone_vn` → hợp lệ.
- [ ] R6.2: `+84 130 123 4567` (mã `1xx` ngoài bảng) và `04 3825 1234` (số cố định trước 2017) → 422 `invalid_type`,
      không lưu; `+1 415 555 0100` vẫn lưu `+14155550100`; quyết định về số cố định cũ ghi trong Comments cùng văn bản
      nguồn.
- [ ] Xong: `uv run python -m pytest -m unit packages/python/dw_studio packages/python/dw_platform packages/python/dw_kernel tests/e2e/marketing_pilot` xanh.

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
