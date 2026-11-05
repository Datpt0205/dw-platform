# 10 — Đầu số di động trước đợt đổi 2018 và một chủ cho luật số điện thoại

Status: needs-triage
Area: studio
Yêu cầu: R6.2, R7.3

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
   gạch, ngoặc) đi cùng đường.
2. Một chủ: hàm chuẩn hóa số điện thoại chuyển vào một mô-đun thuần mà cả `dw_platform` và `dw_studio` import được
   (đề xuất `dw_kernel`), không phụ thuộc mới; `normalize_phone` của
   `packages/python/dw_studio/src/dw_studio/records/domain/values.py` và định dạng `phone_vn` của
   `packages/python/dw_platform/src/dw_platform/application/json_schema.py` cùng đọc nó: `phone_vn` nhận đúng chuỗi mà
   hàm đưa về một số `+84`. Hôm nay `phone_vn` từ chối `84900000101` (10.000/10.000 số của `TEST_RANGE`) và `0084…` mà
   RecordService nhận; chưa công cụ nào trong `configs/` khai `phone_vn` và bộ chiếu lược đồ không phát nó, nên lệch còn
   ngầm. Oracle `tests/e2e/marketing_pilot/measure.py` giữ bản riêng có chủ ý (marketing-pilot R1.2, MP17), và thêm bảng
   21 mã để KQ3 đo cùng luật.
3. Không nhận `phonenumbers`: trên mọi dạng của bộ sinh nó trùng bộ tự viết, còn đầu số cũ nó không đổi (giữ
   `+841684567890`, `is_valid_number` sai), nên bảng 21 mã viết tay ở cả hai cách (discovery/10 (a), quyết định theo ủy
   quyền 31/10/2026). Nếu gate thấy cần phép kiểm hợp lệ của nó: `phonenumberslite==9.0.42`, Apache-2.0, wheel 473.180
   byte, giải nén 1,23 MB, ghi vào ADR trước khi thêm.
4. Số cố định trước đợt đổi mã vùng 2017 (`04 3825 1234`, RecordService lưu `+84438251234`): đọc văn bản đổi mã vùng chính
   thức (số hiệu, URL, ngày đọc) rồi chọn đổi hay từ chối `invalid_type`; chưa đo ở discovery/10.

## Tiêu chí chấp nhận

- [ ] R6.2: `0168 456 7890`, `+84 168 456 7890`, `841684567890` và `01684567890` lưu `+84384567890`; mỗi mã trong 21 mã
      có một vector; gỡ một dòng khỏi bảng → test của mã đó đỏ.
- [ ] R7.3: hai lần Tạo hoặc cập nhật song song với `0168 456 7890` và `038 456 7890` → một dòng; gỡ bảng → hai dòng,
      test đỏ.
- [ ] R6.2: `phone_vn` và `normalize_phone` đọc một hàm: một test chạy cùng bộ vector qua cả hai và đỏ khi một bên đổi
      luật mà bên kia không; `84900000101` qua `phone_vn` → hợp lệ.
- [ ] R6.2: số `+84` mà mã mạng không phải mã đang cấp (vd. `+84 1xx…` sau khi đổi) không lưu nguyên dạng; quyết định
      đổi hay từ chối số cố định cũ ghi trong Comments cùng văn bản nguồn.
- [ ] Xong: `uv run python -m pytest -m unit packages/python/dw_studio packages/python/dw_platform packages/python/dw_kernel tests/e2e/marketing_pilot` xanh.

## Nguồn

- `packages/python/dw_studio/src/dw_studio/records/domain/values.py:100`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/application/json_schema.py:77`; spec: R6.2.
- `tests/e2e/marketing_pilot/measure.py:48`; spec: R7.3.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md` mục Answer (a).

## Comments

- 2026-11-05 (agent, lane 2): viết từ discovery/10 (a). Đo: 70.000/70.000 chuỗi của bộ sinh cùng E.164 ở oracle,
  RecordService và `phonenumbers` 9.0.42; 315 chuỗi của 21 mã cũ: 0 bộ nào đưa về số mới, RecordService nhận cả 315.
