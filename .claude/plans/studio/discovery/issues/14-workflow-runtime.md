# 14 — Runtime quy trình: rào lease trong saver, độ trễ đánh thức, công bằng, allowlist checkpoint, bản kê lượt chạy, nhánh song song, vòng lặp có chờ và Sự cố

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-56 `runtime-mechanics`, FOG-37 `checkpoint-allowlist`, FOG-59 `run-manifest-cost`

## Câu hỏi

1. Saver có rào được lần ghi của bên giữ lease đã cũ ngay trong `aput` và `aput_writes`, không thêm một lượt đi về
   không (FOG-56)?
2. p95 từ lúc endpoint Data Hub trả 2xx tới bước đầu tiên khi dồn tải, với đánh thức bằng NOTIFY (FOG-56)?
3. Hàng outbox FIFO có làm trigger bản ghi của công ty khác chờ sau một lần nhập 100.000 bản ghi không (FOG-56)?
4. Chạy tách từ bước gieo bằng `aupdate_state(as_node=...)` sau một bước map và một điểm nối có đúng không (FOG-56)?
5. Allowlist msgpack tường minh nào đủ cho các kiểu state checkpoint thật của nền tảng dưới langgraph-checkpoint 4.2.0
   (`uv.lock:2091`); checkpoint và lịch sử chạy chỉ giữ tham chiếu bản ghi, hay chiếu lại khi đọc (FOG-37)?
6. Dựng và ghi bản kê lượt chạy lúc nhận run (đi closure, JCS, hai lệnh insert) tốn bao nhiêu ở khối lượng Studio, và
   dựng lại ảnh đã ghim khi resume ở tiến trình khác tốn bao nhiêu (FOG-59)?
7. (V4.26, B1) Trên saver PostgreSQL với hai worker, một Bước song song mà mỗi nhánh biên dịch thành một subgraph node
   có lược đồ trạng thái riêng, đầu ra xuất lên kênh của cha và các nhánh gặp nhau bằng một waiting edge, có chạy
   `Điểm nối` đúng một lần và cho các nhánh không đều chạy thật cùng lúc không, kể cả khi lồng nhau, khi một nhánh chứa
   một Bước rẽ nhánh (gộp qua một node rỗng của trình biên dịch) và khi Bước song song nằm trong thân một vòng lặp (gộp
   một lần mỗi vòng)?
8. (V4.26, B2) Một vòng lặp mà mỗi vòng chờ duyệt và mỗi lần tiếp tục ở worker kia: mỗi vòng có id interrupt riêng và
   mỗi tác động chạy một lần mỗi vòng (khóa chống lặp mang `iteration_path`) không, và bộ đếm bước của bộ bọc node có
   dừng lượt ở `limits.max_steps` qua mọi lần tiếp tục không, khi `recursion_limit` đặt lại ở mỗi lần tiếp tục?
9. (V4.26, B3) Một Bước có `on_error: incident` hết lần thử thì lượt đỗ ở `waiting` trên một dòng `platform.run_waits`
   loại `incident`; `Chạy tiếp từ Bước lỗi` có xếp lại hàng ở worker kia và chạy lại đúng Bước lỗi (không Bước nào đã
   xong trước nó chạy lại, kể cả các nhánh và `Điểm nối` của một Bước song song đứng trước, vì Bước có
   `on_error: incident` không được nằm trong nhánh song song) với cùng khóa chống lặp không, và khi lần thử lỗi có kết
   quả không rõ (hết giờ sau khi nhà cung cấp giả đã nhận), nhà cung cấp nhận tác động mấy lần?

## Vì sao

Công bằng giữa các công ty và hiệu ứng đúng một lần phụ thuộc câu 1-4. Allowlist quá chặt làm hỏng resume, quá lỏng
giữ rủi ro giải tuần tự; giá trị bản ghi lưu trong checkpoint đi vòng qua bảo mật trường. Câu 6 đặt ngân sách độ trễ
lúc nhận run và chứng minh resume được ở bất kỳ tiến trình nào.

Câu 7-9 là bậc B của V4.26 (W1, sau đường găng tới YC94). Số đo đầu của chúng ngày 24/10/2026 chạy trong một tiến trình
trên saver trong bộ nhớ, còn checkpoint thật, lease và hai worker chỉ đo mới biết (`.claude/rules/failure-modes.md`
mục 4); một trần bước không giữ qua lần tiếp tục thì không gì chặn một vòng lặp có chờ (mục 0 và 5).

## Mở khóa

- Spec: `workflow-engine` (03, 04, 05; 06 song song, vòng lặp có trần và nhánh lỗi; 07 Chạy tiếp từ Bước lỗi),
  `workflow-triggers` (02), `foundations-hardening` (02, checkpoint an toàn), `field-security` (02), `tenant-config`
  (04, bản kê lượt chạy), `telemetry-and-audit` (03, Bước chạy mang nhánh và `iteration_path`).
- ADR: 0109, 0112 (Open 5; quyết định 3, 4 và 5 sửa ngày 24/10/2026), 0113 (loại chờ `incident`), 0106.
- DO: DO-05, DO-41. Ticket W1: `foundations-hardening/02` (allowlist checkpoint), `workflow-engine/04`; câu 7-9 đo
  trước khi `workflow-engine/06` và `/07` bắt đầu (ADR 0112, Consequences).

## Dựng tối thiểu

Một làn `studio_runs` nguyên mẫu trên PostgreSQL: bảng run có lease, saver bọc có rào, NOTIFY để đánh thức, hai công ty
giả lập (một nhập 100.000 bản ghi, một gửi sự kiện), một quy trình map rồi nối; chạy với langgraph 1.2.11
(`uv.lock:2074`) và langgraph-checkpoint 4.2.0 của repo.

Cho câu 7-9, thêm ba quy trình trên cùng nguyên mẫu, mỗi lượt chạy qua lại giữa hai worker:

- Bước song song 3 nhánh không đều (một Bước 1,0 s cạnh ba Bước 0,3 s), mỗi nhánh một subgraph, có một tầng lồng, một
  Bước rẽ nhánh trong một nhánh, và một Bước song song trong thân một vòng lặp.
- Một vòng lặp `Lặp lại khi …` 10 vòng có phê duyệt trong thân, mỗi lần tiếp tục ở worker kia, với `limits.max_steps`
  nhỏ hơn số bước mà 10 vòng cần.
- Một Bước đứng sau một Bước song song, gửi qua nhà cung cấp giả lỗi tạm thời tới hết lần thử thành `Sự cố`, rồi
  `Chạy tiếp từ Bước lỗi` ở worker kia; cùng một ca hết giờ sau khi nhà cung cấp giả đã nhận.

## Phép đo quyết định

| Đo                                                          | Ngưỡng                                                                                                                                                                                                                                                       | Quyết định                                                                                                        |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| Resume ở worker khác; số lần nhà cung cấp nhận một tác động | YC41: ≤ 90 giây, đúng 1 lần, không chờ sau 10.000 lượt đang xếp của một công ty                                                                                                                                                                              | Rào trong saver hay một bước riêng                                                                                |
| 2xx tới bước đầu khi dồn tải                                | YC44 và KQ8: 2xx p99 < 1 giây; YC100: tiếp nhận p95 ≤ 60 giây (W2)                                                                                                                                                                                           | NOTIFY đủ hay cần thêm                                                                                            |
| Trigger của công ty khác sau lần nhập lớn                   | Không bị chặn sau hàng của công ty kia                                                                                                                                                                                                                       | Outbox FIFO chung hay theo công ty                                                                                |
| Resume với allowlist                                        | Mọi kiểu state thật qua; kiểu lạ bị từ chối                                                                                                                                                                                                                  | Nội dung allowlist                                                                                                |
| Bản kê lượt chạy lúc nhận và khi resume                     | Chưa có ngưỡng; ghi p95                                                                                                                                                                                                                                      | Ngân sách lúc nhận run                                                                                            |
| Bước song song trên PostgreSQL với hai worker (câu 7)       | `Điểm nối` chạy đúng 1 lần ở mọi ca (lồng, rẽ nhánh trong nhánh, trong vòng lặp); nhánh không đều xong sau khoảng thời gian của nhánh dài nhất (1,01 s trong bộ nhớ), không theo nhịp chung của các nhánh (1,61 s); không nhánh nào cộng lại giá trị của cha | Giữ biên dịch mỗi nhánh thành subgraph gặp nhau bằng waiting edge (ADR 0112 quyết định 4) hay quay lại Đạt        |
| Vòng lặp có chờ (câu 8)                                     | id interrupt khác nhau mỗi vòng; mỗi tác động 1 lần mỗi vòng; bộ đếm bước dừng lượt với `limit_exceeded` đúng ở `limits.max_steps` dù mỗi vòng tiếp tục ở worker khác                                                                                        | Bộ đếm của bộ bọc node là trần thật, số bước xấu nhất lúc gửi kiểm định chỉ cảnh báo (ADR 0112 quyết định 3 và 5) |
| `Sự cố` và `Chạy tiếp từ Bước lỗi` (câu 9)                  | Chỉ Bước lỗi chạy lại; các nhánh và `Điểm nối` của Bước song song đứng trước 1 lần; tác động đã ghi nhận không lặp; ca kết quả không rõ: ghi số lần nhà cung cấp nhận                                                                                        | Giữ cách giải `Sự cố` của ADR 0113 hay đổi; màn hiện "kết quả lần trước không rõ" (YC109)                         |

## Nguồn

- Brief B4, B6 (F2), B7a, B11.
- [research.md](../research.md) mục 4 và 5 (rào lease trong saver, allowlist msgpack chưa kiểm).
- Số đo đầu cho câu 7-9, ngày 24/10/2026, langgraph 1.2.11 và langgraph-checkpoint 4.2.0 của repo trên saver trong bộ
  nhớ, máy dev (nghiên cứu sơ đồ và phản biện của nó; ghi ở Context của ADR 0112); _measured_:
    - waiting edge chạy join một lần với nhánh không đều, cạnh thường chạy hai lần; `defer=True` giữ join lồng tới khi
      một nhánh ngoài không liên quan xong; rẽ nhánh trong nhánh, gộp qua node rỗng rồi waiting edge, chạy join một
      lần;
    - nhánh biên dịch thành nhánh thường của một graph chạy theo cùng nhịp (một Bước 1,0 s cạnh ba Bước 0,3 s: 1,61 s;
      mỗi nhánh một subgraph: 1,01 s); subgraph chung khóa reducer với cha cộng lại giá trị của cha;
    - vòng lặp có chờ: id interrupt riêng mỗi vòng, tác động một lần mỗi vòng, và 20 superstep dưới `recursion_limit`
      8 qua 10 lần tiếp tục, chỉ báo lỗi khi bỏ chờ;
    - sau khi một nhánh lỗi, `invoke(None)` chỉ chạy lại Bước lỗi, còn nhánh anh em và join chạy một lần.
- Camunda: một job lỗi hết lần thử thành incident, instance đứng chờ người xử lý rồi chạy tiếp:
  <https://docs.camunda.io/docs/components/concepts/incidents/>; _documented_, đọc 24/10/2026.

## Comments

- 2026-10-24 (agent): thêm câu 7-9 cho bậc B của V4.26 (B1-B3), bắt đầu từ số đo trong bộ nhớ ngày 24/10/2026; không
  thêm phép đo chờ trong nhánh song song, vì V4.26 giữ mọi Bước chờ ngoài nhánh song song. Ngưỡng 2xx sửa từ p95 ≤ 1
  giây thành p99 < 1 giây theo YC44 (Q2, Đạt ngày 23/10/2026).
