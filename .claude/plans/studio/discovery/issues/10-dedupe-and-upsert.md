# 10 — Kiểm trùng lead và sự tồn tại dưới RLS: chuẩn hóa số điện thoại, trường duy nhất, upsert theo từng lệnh

Type: prototype
Status: resolved
Area: studio · Viết: 23/10/2026
FOG: FOG-11 `dedupe-phone`, FOG-42 `upsert-under-rls`

## Câu hỏi

1. Kiểm trùng chính xác tới đâu sau khi chuẩn hóa số điện thoại Việt Nam (số 11 chữ số cũ, `+84`, nhiễu định dạng);
   thư viện `phonenumbers` có hợp không (giấy phép, kích thước, đợt đổi đầu số 2018) (FOG-11)?
2. Trường `phone_e164` duy nhất có thành cách dò sự tồn tại cho một vai trò không đọc được số điện thoại không
   (FOG-11)?
3. `INSERT ... ON CONFLICT DO UPDATE` và `UPDATE ... RETURNING` chạy thế nào dưới policy quyền trên bản ghi theo từng
   lệnh (policy SELECT áp cho cả dòng có sẵn và dòng mới), khi nhập và kiểm trùng (FOG-42)?

## Vì sao

Gộp nhầm làm mất lead; một cách dò tồn tại làm lộ dữ liệu cá nhân qua bảo mật trường; nhập và kiểm trùng có thể hỏng
trong im lặng hoặc lộ sự tồn tại của bản ghi không đọc được.

## Mở khóa

- Spec: `marketing-pilot` (01, 03), `custom-objects` (03: trường duy nhất và upsert, trên đường găng),
  `workflow-nodes` (hàm `phone.e164`), `record-access` (tính duy nhất).
- ADR: 0105 (Open 3), 0107 (Open 3).
- DO: DO-35 (chấp nhận cách dò tồn tại là rủi ro còn lại, với lỗi chung, giới hạn theo người và audit).
- Ticket W1: `marketing-pilot/01` (P0) đo câu 1; `custom-objects/03` dựng upsert theo câu 3.

## Dựng tối thiểu

Bộ sinh lead giả lập có hạt giống của `marketing-pilot/01` với nhiều dạng số; chuẩn hóa bằng `phonenumbers`; một vai
trò không có quyền trường số điện thoại thử tạo Lead trùng số. Câu 3 chạy trên bộ policy nguyên mẫu của ticket 05, nên
làm sau khi ticket 05 dựng xong policy; câu 1 không phải chờ.

## Phép đo quyết định

| Đo                                          | Ngưỡng                                                                | Quyết định                                |
| ------------------------------------------- | --------------------------------------------------------------------- | ----------------------------------------- |
| Trùng lọt; gộp nhầm                         | KQ3: ≤ 1%; 0. YC95: "0901 234 567" và "+84901234567" là một Lead      | Khóa kiểm trùng của quy trình             |
| Phản hồi khi vai trò không đọc số tạo trùng | Lỗi chung, không nêu bản ghi trùng; có audit                          | Giữ DO-35 hay thu hẹp trường duy nhất     |
| Upsert dưới policy theo từng lệnh           | Không ghi lọt, không lộ dòng không đọc được; test âm đỏ khi bỏ policy | Upsert trong `RecordService` dựng thế nào |

## Nguồn

- Brief B4, B7b, B12.
- [research.md](../research.md) mục 2 (upsert dưới policy theo từng lệnh chưa kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: (a) phần còn lại của câu 1: `phonenumbers` (ghim đúng phiên bản) có đưa mọi dạng số của bộ sinh
  `tests/e2e/marketing_pilot/generator.py`, cùng số 11 chữ số theo đầu số trước đợt đổi năm 2018, về cùng E.164
  với oracle `tests/e2e/marketing_pilot/measure.py` không; giấy phép và cỡ wheel của nó? (b) câu 3 dưới policy bản
  ghi đầy đủ.
- Cách làm: (a) venv tạm, không thêm vào `uv.lock`; chạy trên hạt giống 20261102 và một danh sách đầu số cũ lấy từ
  văn bản đổi đầu số (ghi số hiệu, URL, loại, ngày đọc); so từng khóa với oracle và với định dạng `phone_vn`
  (`packages/python/dw_platform/src/dw_platform/application/json_schema.py:77`). (b) trong custom-objects/03
  (`ready-for-agent`): test upsert `ON CONFLICT ... DO UPDATE` dưới policy của record-access/03, với ca âm: vai
  trò không đọc được dòng trùng nhận 409 `duplicate_value` chung, không ghi lọt, không lộ id; gỡ policy thì đỏ.
- Đầu ra: `## Answer` ở đây; (b) đóng bằng một dòng trỏ tới Comments của custom-objects/03.
- Đạt khi: (a) 0 gộp nhầm, trùng lọt ≤ 1% (KQ3), "0901 234 567" và "+84901234567" một khóa (YC95), giấy phép
  không copyleft; (b) như bảng Phép đo quyết định. Trượt (a) thì RecordService giữ bộ chuẩn hóa tự viết theo
  custom-objects:R6.2 và ghi số đầu số cũ bị sót.

## Answer

Đo ngày 5/11/2026 (lane 2). (a) chạy trong venv tạm ngoài repo, không chạm `uv.lock`; (b) trên bản xuất sạch của
`f10e2f64` cộng test mới, PostgreSQL của compose, `DW_TEST_DB_SUFFIX=_lane2`.

**(a) `phonenumbers`: đạt trên bộ sinh, trượt ở đầu số cũ, nên RecordService giữ bộ chuẩn hóa tự viết (R6.2).**

- Bản đo: `phonenumbers` 9.0.42 (PyPI 27/10/2026) và `phonenumberslite` 9.0.42, cùng kết quả; `parse(raw, "VN")`, khóa là
  E.164 khi `is_valid_number`. So với oracle `tests/e2e/marketing_pilot/measure.py`, với `normalize_phone` của
  custom-objects/03 (`packages/python/dw_studio/src/dw_studio/records/domain/values.py:100`) và với `phone_vn`.
- Bảy dạng của bộ sinh, mọi số của `TEST_RANGE` (10.000 số × 7 = 70.000 chuỗi): thư viện, oracle và RecordService cùng
  một E.164 ở 70.000/70.000, thư viện coi hợp lệ cả 70.000. `phone_vn` nhận 60.000: từ chối cả 10.000 số dạng
  `country` (`84900000101`). Trên hạt giống 20261102, 200 lead: 121 lead có số, ba bộ chuẩn hóa cùng khóa ở 121/121;
  `measure` cho cả ba 196 khóa, 0 gộp nhầm, trùng lọt 0/4; "0901 234 567" và "+84901234567" là một khóa
  `+84901234567` ở cả ba (YC95); `phone_vn` nhận 102/121.
- Đầu số trước đợt đổi: Quyết định số 798/QĐ-BTTTT ngày 25/5/2018 của Bộ Thông tin và Truyền thông, "Ban hành Kế hoạch
  chuyển đổi mã mạng" (loại: Quyết định, người ký Trương Minh Tuấn), bản ký
  `https://mic.mediacdn.vn/Upload_Moi/VanBan/qd-798signed.PDF` (sha256 `1e5c8fa3…d38b`), trang văn bản
  `https://mst.gov.vn/van-ban-phap-luat/14183.htm`, đọc ngày 5/11/2026; mục II.2.1 đổi 21 mã H2H, giữ bảy số cuối:
  MobiFone 120, 121, 122, 126, 128 → 70, 79, 77, 76, 78; VinaPhone 123, 124, 125, 127, 129 → 83, 84, 85, 81, 82;
  Viettel 162-169 → 32-39; Vietnamobile 186, 188 → 56, 58; Gmobile 199 → 59. Thử 21 mã × 3 đuôi × 5 dạng (`0168…`,
  cách, chấm, `+84168…`, `84168…`) = 315 chuỗi, đích là số mới cùng bảy số cuối: thư viện 0/315 (giữ `+841684567890`,
  `is_valid_number` sai ở cả 315, `is_possible_number` đúng); oracle 0/315 (từ chối cả 315); `phone_vn` từ chối cả 315;
  RecordService **nhận cả 315** và lưu `+841684567890`, một khóa không bao giờ trùng với số mới `+84384567890`: hai lead
  của một người, một ghi số cũ, là trùng lọt, và giá trị đã lưu không phải số dùng được. Không bộ nào sót ít hơn: cả 21
  mã sót, ở cả bốn.
- Giấy phép Apache-2.0 (`License-Expression` của wheel, không copyleft). Wheel `phonenumbers-9.0.42-py2.py3-none-any.whl`
  2.595.813 byte, giải nén 21,9 MB (620 tệp, kèm dữ liệu địa danh, nhà mạng, múi giờ); `phonenumberslite` 9.0.42 473.180
  byte, giải nén 1,23 MB, đủ cho parse, format và kiểm hợp lệ. Ghim nếu có ngày dùng: `phonenumberslite==9.0.42`.
- Quyết định (agent, theo ủy quyền 31/10/2026): không nhận `phonenumbers` làm phụ thuộc. Trên mọi dạng bộ sinh nó trùng
  bộ tự viết từng chuỗi, còn đợt đổi 2018 thì nó không đổi: bảng 21 mã phải viết tay ở cả hai cách, nên thư viện chỉ thêm
  phép kiểm hợp lệ và 0,47 MB. Trượt (a) theo dòng Đạt khi: RecordService giữ bộ chuẩn hóa tự viết theo
  custom-objects:R6.2, 21 mã sót ghi ở trên; sửa ở follow-up
  [custom-objects/10](../../custom-objects/issues/10-dau-so-cu-va-mot-luat-so-dien-thoai.md) (`needs-triage`): đổi 21 mã
  cũ về mã mới, và một chủ cho luật số điện thoại thay ba bản (oracle là bản thứ tư, có chủ ý). Nếu sai thì: thêm
  `phonenumberslite==9.0.42` ở ticket đó và chỉ dùng phép kiểm hợp lệ của nó, bảng 21 mã vẫn giữ.
- Nhiễu ngoài bộ sinh (mỗi dạng một chuỗi): `0084…` thư viện và RecordService cùng `+84900000101`, oracle và `phone_vn`
  từ chối; `+84 (0)900 000 101`, `0900/000/101`, chữ số toàn khổ: thư viện nhận, RecordService từ chối `invalid_type`
  (từ chối, không gộp sai); số cố định cũ `04 3825 1234` (trước đợt đổi mã vùng 2017): RecordService lưu `+84438251234`,
  thư viện coi không hợp lệ; văn bản đổi mã vùng chưa đọc, ghi vào follow-up.
- Cách lặp lại: venv tạm cài wheel đã tải, rồi script chạy bằng trình thông dịch của repo với `site-packages` của venv
  đó chèn vào `sys.path`, import `generate`, `measure`, `normalize_phone` của oracle, `normalize_phone` của
  `values.py` và `_phone_vn`; script không vào repo vì nó cần một gói không có trong khóa.

**(b) Câu 3 dưới bộ policy bản ghi đầy đủ: đạt; thiếu test của upsert lên dòng không đọc được, đã thêm và chứng minh
đỏ.** Chi tiết ở dòng 2026-11-05 lane 2 trong Comments của
[custom-objects/03](../../custom-objects/issues/03-record-service.md): hai test mới trong
`packages/python/dw_studio/tests/integration/test_record_service.py` (`test_r7_4_co16_an_upsert_onto_a_record_the_caller_cannot_read_reveals_nothing`,
`test_r7_4_co16_a_readable_match_out_of_update_reach_is_a_plain_duplicate`), gỡ tầm đọc của policy SELECT thì test thứ
nhất đỏ, gỡ tầm sửa của policy UPDATE thì test thứ hai đỏ; một lệch R7.4 không lộ gì, follow-up
[custom-objects/11](../../custom-objects/issues/11-upsert-khong-doi-tren-ban-ghi-khong-sua-duoc.md).

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Đã trả lời: câu 1 một phần, marketing-pilot/01 (`9397afb`): trên hạt giống 20261102, 200 lead, 0 gộp nhầm, trùng lọt 0/4, "0901 234 567" và "+84901234567" một khóa, bằng bộ chuẩn hóa tự viết của harness, không phải `phonenumbers`. Câu 2 là quyết định của Đạt (DO-35, 23 và 24/10/2026, mục Quyết định của spec `custom-objects`): trường duy nhất là cách dò tồn tại được chấp nhận làm rủi ro còn lại, với 409 chung, tối đa 20 lần mỗi người mỗi đối tượng trong 10 phút rồi 429 và audit (custom-objects/03, chưa dựng). Câu 3 một phần, custom-objects/01 (Comments 4/11/2026): `ON CONFLICT ... DO UPDATE` chạy dưới policy theo lệnh, còn `RETURNING (xmax = 0)` lỗi trên bảng partition nên thêm hay sửa đọc từ `version = 1`.
- 2026-11-05 (agent, lane 2, theo ủy quyền 31/10/2026): resolved. (a) thư viện trùng bộ tự viết 70.000/70.000 trên bộ sinh, 0/315 ở 21 mã cũ của QĐ 798/QĐ-BTTTT; không nhận làm phụ thuộc, follow-up custom-objects/10. (b) hai test âm mới (`a021a667`), mỗi test đỏ khi gỡ một lớp policy; lệch R7.4 khi upsert không đổi gì, follow-up custom-objects/11. Nếu sai thì: xem Nếu sai thì trong Answer.
