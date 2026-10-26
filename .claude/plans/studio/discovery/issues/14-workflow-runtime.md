# 14 — Spike runtime S-RT: sáu quy trình tham chiếu, ngưỡng T1-T9, ma trận sập của tác động và các câu runtime đã có

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-56 `runtime-mechanics`, FOG-37 `checkpoint-allowlist`, FOG-59 `run-manifest-cost`

## Câu hỏi

Từ 25/10/2026 ticket này là spike S-RT của V4.34 (Đạt): 2 tuần, 1-2 kỹ sư, ở đầu W1 (lát S0 của bản trả lời bản phản
biện), song song với `foundations-hardening` và `app-standards`, trên langgraph 1.2.11 (`uv.lock:2074`) và
langgraph-checkpoint 4.2.0 (`uv.lock:2091`) đã ghim. Câu chính: phương án A, tức LangGraph chạy tài liệu cây Bước
(ADR-0112 (Accepted) quyết định 1), mỗi nhánh song song là một subgraph và `durability="sync"` ghim ở mục `engine` của
bản kê lượt chạy, có đạt ngưỡng T1-T8 trên sáu quy trình tham chiếu RW1-RW6 không? Luật quyết ở cuối "Phép đo quyết
định" chọn engine. Ticket này là chủ duy nhất của mọi phép đo runtime (H-9): các câu dưới, kể cả câu 1-3, 5 và 6 có
từ trước và câu 7-9 của bậc B (B1-B3), được trả lời bằng chính các lượt chạy của spike, và `workflow-engine/03` chờ phần
trả lời của nó.

1. Saver có rào được lần ghi của bên giữ lease đã cũ ngay trong `aput` và `aput_writes`, không thêm một lượt đi về
   không (FOG-56)? Đo trong ca S của câu 10.
2. p95 từ lúc endpoint Data Hub trả 2xx tới bước đầu tiên khi dồn tải, với đánh thức bằng NOTIFY (FOG-56)?
3. Hàng outbox FIFO có làm trigger bản ghi của công ty khác chờ sau một lần nhập 100.000 bản ghi không (FOG-56)?
4. [Bỏ] 25/10/2026: "Chạy tách từ bước" bị bỏ (V4.36, H-13), nên không đo `aupdate_state(as_node=...)`;
   `Chạy lại mô phỏng` (W2) là một lượt Mô phỏng mới với cùng đầu vào, không gieo trạng thái từ checkpoint của lượt cũ.
5. Allowlist msgpack tường minh nào đủ cho các kiểu state checkpoint thật của nền tảng dưới langgraph-checkpoint 4.2.0
   (`uv.lock:2091`); checkpoint và lịch sử chạy chỉ giữ tham chiếu bản ghi, hay chiếu lại khi đọc (FOG-37)?
6. Dựng và ghi bản kê lượt chạy lúc nhận run (đi closure, JCS, hai lệnh insert) tốn bao nhiêu ở khối lượng Studio, và
   dựng lại ảnh đã ghim khi resume ở tiến trình khác tốn bao nhiêu (FOG-59)?
7. (V4.26, B1) Trên saver PostgreSQL với hai worker, một Bước song song mà mỗi nhánh biên dịch thành một subgraph node
   có lược đồ trạng thái riêng, đầu ra xuất lên kênh của cha và các nhánh gặp nhau bằng một waiting edge, có chạy
   `Điểm nối` đúng một lần và cho các nhánh không đều chạy thật cùng lúc không, kể cả khi lồng nhau, khi một nhánh chứa
   một Bước rẽ nhánh (gộp qua một node rỗng của trình biên dịch) và khi Bước song song nằm trong thân một vòng lặp (gộp
   một lần mỗi vòng)? Đo bằng RW2 và biến thể của nó (T1, T2).
8. (V4.26, B2) Một vòng lặp mà mỗi vòng chờ duyệt và mỗi lần tiếp tục ở worker kia: mỗi vòng có id interrupt riêng và
   mỗi tác động chạy một lần mỗi vòng (khóa chống lặp mang `iteration_path`) không, và bộ đếm bước của bộ bọc node có
   dừng lượt ở `limits.max_steps` qua mọi lần tiếp tục không, khi `recursion_limit` đặt lại ở mỗi lần tiếp tục? Đo bằng
   RW4 và biến thể của nó (T1).
9. (V4.26, B3) Một Bước có `on_error: incident` hết lần thử thì lượt đỗ ở `waiting` trên một dòng `platform.run_waits`
   loại `incident`; `Chạy tiếp từ Bước lỗi` có xếp lại hàng ở worker kia và chạy lại đúng Bước lỗi (không Bước nào đã
   xong trước nó chạy lại, kể cả các nhánh và `Điểm nối` của một Bước song song đứng trước, vì Bước có
   `on_error: incident` không được nằm trong nhánh song song) với cùng khóa chống lặp không? Đo bằng RW2 và biến thể
   của nó (T7). Một lần thử có kết quả không rõ thì lượt đỗ ở `outcome_review` chứ không ở `Sự cố` (V4.30), nên ca đó
   thuộc câu 10.
10. (V4.30) Với nhà cung cấp giả ba chế độ (có khóa, có tra cứu, không gì), nhà cung cấp áp dụng một tác động mấy lần
    ở mỗi điểm sập K1, K2, T, K4, K5, K6 và S, và có lần ghi nội bộ nào trùng không? Đây là T3.
11. (V4.33) Một lượt cha gọi quy trình con sâu 3 cấp, có điểm chờ ở cấp con, rồi bị hủy giữa chừng: mọi lượt con có
    dừng trong ≤ 5 giây và mọi điểm chờ có chuyển `cancelled` trong cùng giao dịch không? Đo bằng RW6 (T1, T8).

## Vì sao

YC41 đứng trên câu 1-3 và 10: lượt chạy tiếp tục ở worker khác trong ≤ 90 giây, không chờ sau lượt của công ty khác,
và mỗi tác động giữ mức bảo đảm giao nhận của nó. Không engine nào trong các phương án tự giải phần tác động ra ngoài
(mục 5 của bản trả lời), nên phép đo nhắm vào phần của nền tảng: nhật ký lần gửi, tiếp quản lượt giữ và bộ bọc node.
Allowlist quá chặt làm hỏng resume, quá lỏng giữ rủi ro giải tuần tự; giá trị bản ghi lưu trong checkpoint đi vòng qua
bảo mật trường. Câu 6 đặt ngân sách độ trễ lúc nhận run và chứng minh resume được ở bất kỳ tiến trình nào.

Câu 7-9 là bậc B của V4.26 và câu 11 là quy trình con của V4.33, cùng ở W1 sau đường găng tới lối ra W1a. Số đo đầu
của câu 7-9 ngày 24/10/2026 chạy trong một tiến trình trên saver trong bộ nhớ, còn checkpoint thật, lease và hai worker
chỉ đo mới biết (`.claude/rules/failure-modes.md` mục 4); một trần bước không giữ qua lần tiếp tục thì không gì chặn một
vòng lặp có chờ (mục 0 và 5). Spike trả lời trước khi `workflow-engine/03` bắt đầu, vì một engine chọn sai bắt mọi
ticket dựng trên nó làm lại, và chạy song song nên không kéo dài đường găng (V4.34).

## Mở khóa

- Spec: `workflow-engine` (03 chờ ticket này qua dòng `Blocked by:`; 04, 05; 06 song song, vòng lặp có trần và nhánh
  lỗi; 07 Chạy tiếp từ Bước lỗi; 08 tác động không rõ kết quả, `issues/08-tac-dong-khong-ro-ket-qua.md`; 09 quy trình
  con, `issues/09-quy-trinh-con.md`; R7 "Ngữ nghĩa thực thi có golden trace", mà RW1-RW6 chạy), `runtime-hardening`
  (01, giành lượt và nhật ký lần gửi), `workflow-triggers` (02), `foundations-hardening` (02, checkpoint an toàn),
  `field-security` (02), `tenant-config` (04, bản kê lượt chạy và mục `engine`), `telemetry-and-audit` (03, Bước chạy
  mang nhánh và `iteration_path`).
- ADR, đều Accepted: 0106; 0108 (quyết định 5, tiếp quản lượt giữ); 0109 (quyết định 8, engine ghim theo lượt); 0112
  (Open 5; quyết định 3, 4, 5 và 11; số đo của spike thay lý do của dòng "A custom interpreter: Rejected" ở
  Alternatives); 0113 (loại chờ `incident`, `child_run` và `outcome_review`); 0115 (quyết định 6, kết quả có kiểu của
  egress); 0116 (khối `delivery`).
- DO: DO-05, DO-41. Ticket W1: `foundations-hardening/02` (allowlist checkpoint), `workflow-engine/03` và `/04`; câu
  7-9 và 11 đo trước khi `workflow-engine/06`, `/07` và `/09` bắt đầu (ADR-0112 (Accepted), Consequences).

## Dựng tối thiểu

Một làn `studio_runs` nguyên mẫu trên PostgreSQL: bảng run có lease, saver bọc có rào, NOTIFY để đánh thức, hai worker,
hai công ty giả lập (một nhập 100.000 bản ghi, một gửi sự kiện), `durability="sync"`, và nguyên mẫu của nhật ký lần gửi
(V4.30): một dòng `dispatched` commit trong giao dịch riêng trước lời gọi ra ngoài, và lượt giữ quá hạn bị tiếp quản
chỉ chạy lại khi chưa có dòng đó, không thì làm theo `on_unknown`. Đo trên cấu hình của [research.md](../research.md)
mục 5 (4 vCPU, 3 GiB, PostgreSQL 16.15), rồi đo lại trên host thí điểm khi có.

Sáu quy trình tham chiếu, mỗi quy trình là một tài liệu cây Bước chạy qua lại giữa hai worker, kèm golden trace theo
R7 "Ngữ nghĩa thực thi có golden trace" của `workflow-engine` (V4.34):

| Mã  | Quy trình                                                                                                                                                                                                                                                             |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RW1 | Tiếp nhận lead: tuần tự, rẽ nhánh, phê duyệt, email; làm mốc so sánh                                                                                                                                                                                                  |
| RW2 | Mua hàng: Bước song song {kiểm ngân sách ở ERP giả, tra nhà cung cấp, chấm rủi ro bằng `ai.llm`} → `Điểm nối` → một Bước phê duyệt có hai người bắt buộc → tạo PO qua HTTP giả, thử lại 3 lần → vẫn lỗi thì vào nhánh lỗi gọi một Bước bù (nhả phần ngân sách đã giữ) |
| RW3 | Map 100 phần tử, mỗi phần tử một `ai.llm` (`max_parallel` 10) → nối → tóm tắt; đo bằng saver hiện tại và bằng saver blob theo kênh                                                                                                                                    |
| RW4 | Vòng sửa: soạn → duyệt → bị trả thì sửa lại; `max_iterations` 5; điểm chờ trong thân vòng; có `logic.break`                                                                                                                                                           |
| RW5 | Kênh dự phòng: gửi Zalo, lỗi thì vào nhánh lỗi gửi email; không bao giờ giao cả hai, kể cả khi sập                                                                                                                                                                    |
| RW6 | Lồng nhau: lượt cha gọi quy trình con sâu 3 cấp, có điểm chờ ở cấp con; hủy lượt cha giữa chừng                                                                                                                                                                       |

Ba biến thể giữ phép đo đã thiết kế cho câu 7-9:

- RW2 cho câu 7: Bước song song 3 nhánh không đều (một Bước 1,0 s cạnh ba Bước 0,3 s), có một tầng lồng, một Bước rẽ
  nhánh trong một nhánh, và một Bước song song trong thân một vòng lặp.
- RW4 cho câu 8: một vòng lặp `Lặp lại khi …` 10 vòng có phê duyệt trong thân, mỗi lần tiếp tục ở worker kia, với
  `limits.max_steps` nhỏ hơn số bước mà 10 vòng cần.
- RW2 cho câu 9: một Bước đứng sau Bước song song, gửi qua nhà cung cấp giả lỗi tạm thời tới hết lần thử thành
  `Sự cố`, rồi `Chạy tiếp từ Bước lỗi` ở worker kia.

Nhà cung cấp giả có ba chế độ, mỗi chế độ đếm số lần đã áp dụng mỗi tác động (V4.30): có khóa (khử trùng theo khóa
nhận được trong `retention_hours`), có tra cứu (không khử trùng, nhưng một Hành động tra cứu theo `ref_field` trả lời
đã nhận hay chưa), và không gì (như SMTP: không khóa, không tra cứu). Ma trận sập lấy từ mục 5.2 của bản trả lời, nơi
không có K3 vì T đứng ở chỗ đó:

| Điểm | Lúc sập hay lỗi                                                        | Mong đợi                                                                                    |
| ---- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| K1   | Trước khi giành lượt                                                   | Bước chạy lại; nhà cung cấp áp dụng 1 lần                                                   |
| K2   | Đã giành lượt, chưa có dòng `dispatched`                               | Lượt giữ quá hạn bị tiếp quản và chạy lại an toàn; 1 lần                                    |
| T    | Đã gửi và nhà cung cấp đã áp dụng, nhưng mất phản hồi (hết giờ, reset) | Kết quả `outcome_unknown`; làm theo `on_unknown`                                            |
| K4   | Đã nhận 2xx, sập trước khi ghi kết quả                                 | Có `dispatched` mà không có dòng kết thúc: làm theo `on_unknown`, không bao giờ chạy lại mù |
| K5   | Đã ghi `succeeded`, sập trước checkpoint                               | Phát lại kết quả đã lưu; 1 lần                                                              |
| K6   | Sau checkpoint                                                         | Không chạy lại; 1 lần                                                                       |
| S    | Bên giữ lượt cũ treo quá hạn giữ trong lúc bên mới tiếp quản           | Bên mới thấy `dispatched` và làm theo `on_unknown`; hai bên không cùng gửi                  |

## Phép đo quyết định

| #   | Đo gì                                                                                                                      | Ngưỡng                                                                                                                                                                                                                      |
| --- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | Golden trace của RW1-RW6 và các biến thể: tập node đã chạy, thứ tự bắt buộc, lần bắn của `Điểm nối`, nhánh bị hủy, số vòng | 100%                                                                                                                                                                                                                        |
| T2  | RW2: một nhánh đang đợi backoff thì các nhánh khác vẫn tiến                                                                | ≥ 3 bước xong trong ≤ 5 giây                                                                                                                                                                                                |
| T3  | Ma trận sập K1-K6, S và T nhân ba chế độ của nhà cung cấp giả (câu 1 và 10)                                                | Có khóa hay tra cứu: đúng 1 lần áp dụng; không gì: 0 lần tự gửi lại ở T, K4 và S, cả ba thành `outcome_review`; nội bộ: 0 lần ghi trùng; RW5: 0 lần giao cả hai kênh; gỡ dòng `dispatched` thì ca K4 của chế độ không gì đỏ |
| T4  | Giết worker giữa lượt; deploy bản compiler kế tiếp khi đang có lượt đỗ                                                     | Resume trong ≤ 90 giây (YC41); fixture lượt đỗ resume được theo cả hai chiều                                                                                                                                                |
| T5  | 1.000 lượt RW3 đồng thời, đầu ra 1 KB, `durability="sync"`                                                                 | 0 lượt hỏng (mốc hôm nay 506/1.000); khoảng cách giữa hai bước p95 ≤ 250 ms (mốc của saver theo kênh 125 ms); công bằng giữa các công ty vẫn giữ                                                                            |
| T6  | Dung lượng                                                                                                                 | Một lượt đỗ ≤ 20 KB; một lượt 20 bước với đầu ra 100 KB ≤ 3 MB (mốc hôm nay 8,5 MB)                                                                                                                                         |
| T7  | `Chạy tiếp từ Bước lỗi`: RW2 với PO lỗi ở bước 7 trên 10, và biến thể câu 9                                                | Chỉ node lỗi và các node sau nó chạy; 0 tác động của node 1-6 bị gửi lại; giữ nguyên `run_id`                                                                                                                               |
| T8  | Hủy giữa chừng RW2 và RW6                                                                                                  | Mọi bước dừng trong ≤ 5 giây (YC45, YC117); mọi điểm chờ chuyển `cancelled` trong cùng giao dịch                                                                                                                            |
| T9  | Chỉ áp cho C, nếu phải dựng                                                                                                | Lõi ≤ 3.000 dòng; không cửa nào mất test âm                                                                                                                                                                                 |

Luật quyết (V4.34):

- Chọn A nếu đạt T1-T8.
- A trượt T1, T2 hay T7: dựng C, một token engine trên PostgreSQL mà tới lúc đó chỉ thiết kế trên giấy, rồi đo lại
  T1-T9.
- Cả A và C trượt: mở B (Temporal tự host) kèm một ADR riêng, nói về câu "PostgreSQL is the system of record" của
  `CLAUDE.md`, mục "Non-negotiable architecture", và một codec mã hóa payload theo công ty (mục 3.5 của bản trả lời).
- T5 trượt chỉ vì saver: kéo saver blob theo kênh (dòng W2 "bộ lưu checkpoint Studio blob-per-channel" ở Ngoài phạm vi
  của `workflow-engine`) lên W1, không đổi engine.
- A đạt T1, T2 và T7 mà trượt T3, T4, T6, T8, hay T5 không chỉ vì saver: không đổi engine vì thế; ghi số đo và
  nguyên nhân, sửa phần của nền tảng mà số đo chỉ ra rồi đo lại, và nếu nguyên nhân nằm ở LangGraph thì quay lại Đạt
  trước khi `workflow-engine/03` bắt đầu (lựa chọn tạm ở Comments).
- Dù kết quả thế nào, số đo thay lý do của dòng "A custom interpreter: Rejected" ở Alternatives của ADR-0112
  (Accepted).

Các phép đo khác, đo trong cùng các lượt chạy:

| Đo                                                                     | Ngưỡng                                                                                                                                                                                                                                                       | Quyết định                                                                                                                   |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| Lần ghi của bên giữ lease cũ (câu 1, ca S của T3)                      | 0 lần ghi của bên cũ được nhận                                                                                                                                                                                                                               | Rào trong saver hay một bước riêng                                                                                           |
| 2xx tới bước đầu khi dồn tải (câu 2)                                   | YC44 và KQ8: 2xx p99 < 1 giây; YC100: tiếp nhận p95 ≤ 60 giây (W2)                                                                                                                                                                                           | NOTIFY đủ hay cần thêm                                                                                                       |
| Trigger của công ty khác sau lần nhập lớn (câu 3)                      | Không bị chặn sau hàng của công ty kia; không chờ sau 10.000 lượt đang xếp của một công ty khác (YC41)                                                                                                                                                       | Outbox FIFO chung hay theo công ty                                                                                           |
| Resume với allowlist (câu 5)                                           | Mọi kiểu state thật qua; kiểu lạ bị từ chối                                                                                                                                                                                                                  | Nội dung allowlist                                                                                                           |
| Bản kê lượt chạy lúc nhận và khi resume (câu 6)                        | Chưa có ngưỡng; ghi p95                                                                                                                                                                                                                                      | Ngân sách lúc nhận run                                                                                                       |
| Bước song song trên PostgreSQL với hai worker (câu 7, phần của T1, T2) | `Điểm nối` chạy đúng 1 lần ở mọi ca (lồng, rẽ nhánh trong nhánh, trong vòng lặp); nhánh không đều xong sau khoảng thời gian của nhánh dài nhất (1,01 s trong bộ nhớ), không theo nhịp chung của các nhánh (1,61 s); không nhánh nào cộng lại giá trị của cha | Giữ biên dịch mỗi nhánh thành subgraph gặp nhau bằng waiting edge (ADR-0112 (Accepted) quyết định 4) hay quay lại Đạt        |
| Vòng lặp có chờ (câu 8, phần của T1)                                   | id interrupt khác nhau mỗi vòng; mỗi tác động 1 lần mỗi vòng; bộ đếm bước dừng lượt với `limit_exceeded` đúng ở `limits.max_steps` dù mỗi vòng tiếp tục ở worker khác                                                                                        | Bộ đếm của bộ bọc node là trần thật, số bước xấu nhất lúc gửi kiểm định chỉ cảnh báo (ADR-0112 (Accepted) quyết định 3 và 5) |
| `Sự cố` và `Chạy tiếp từ Bước lỗi` (câu 9, phần của T7)                | Chỉ Bước lỗi chạy lại; các nhánh và `Điểm nối` của Bước song song đứng trước 1 lần; tác động đã ghi nhận không lặp                                                                                                                                           | Giữ cách giải `Sự cố` của ADR-0113 (Accepted) hay đổi; màn hiện "kết quả lần trước không rõ" (YC109)                         |

## Nguồn

- Brief B4, B6 (F2), B7a, B11.
- [research.md](../research.md) mục 4 và 5 (rào lease trong saver, allowlist msgpack chưa kiểm, saver hiện tại ở 1.000
  lượt và đầu ra 100 KB).
- Bản trả lời bản phản biện kiến trúc Studio ngày 24/10/2026: mục 3.4 (ngữ nghĩa và golden trace), 3.5 và 3.6 (RW1-RW6,
  T1-T9, luật quyết) và 5.2 (ma trận sập); Đạt nhận ngày 25/10/2026 (V4.30, V4.34, area file).
- Số đo đầu cho câu 7-9, ngày 24/10/2026, langgraph 1.2.11 và langgraph-checkpoint 4.2.0 của repo trên saver trong bộ
  nhớ, máy dev (nghiên cứu sơ đồ và phản biện của nó; ghi ở Context của ADR-0112 (Accepted)); _measured_:
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
- 2026-10-25 (agent): theo V4.34 của Đạt, ticket này thành spike S-RT: thêm RW1-RW6, T1-T9 và luật quyết (mục 3.6 của
  bản trả lời), gộp câu 7-9 (B1-B3) vào các phép đo đó cùng ba biến thể đã thiết kế cho chúng, thêm câu 10 (ma trận sập
  K1-K6, S và T với nhà cung cấp giả ba chế độ, V4.30) và câu 11 (RW6, quy trình con, V4.33); câu 4 bỏ theo V4.36
  (H-13); hàng YC41 của bảng đo cũ tách thành T3, T4 và hàng câu 3, theo mức bảo đảm giao nhận thay cho "đúng 1 lần";
  `workflow-engine/03` chờ ticket này.
- 2026-10-25 (agent, tạm): H-9: một chủ cho mọi phép đo runtime (`.claude/rules/failure-modes.md` mục 2), nên S-RT là
  ticket này chứ không là một ticket khám phá mới: câu hỏi cũ và ma trận sập nằm cùng chỗ với RW1-RW6, và
  `workflow-engine/03` có dòng `Blocked by:` tới tệp này. Nếu sai thì: một ticket khám phá mới cho S-RT, ticket này giữ
  câu 1-9 cũ, và `workflow-engine/03` chờ ticket mới.
- 2026-10-25 (agent, tạm): luật quyết của V4.34 không nói khi A đạt T1, T2 và T7 mà trượt T3, T4, T6, T8, hay T5
  không chỉ vì saver; khi đó ticket này không đổi engine: ghi số đo và nguyên nhân, sửa phần của nền tảng mà số đo chỉ
  ra (nhật ký lần gửi, tiếp quản, bộ bọc node, saver, lane hủy) rồi đo lại, và nếu nguyên nhân nằm ở LangGraph thì
  quay lại Đạt trước khi `workflow-engine/03` bắt đầu. Nếu sai thì: một trượt ở T3, T4, T6, T8, hay T5 không chỉ vì
  saver, cũng dựng C như trượt T1, T2 hay T7.
