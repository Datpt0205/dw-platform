# Spike S-RT: LangGraph chạy cây Bước, đo trên hai tiến trình worker (discovery 14)

Ticket: [`.claude/plans/studio/discovery/issues/14-workflow-runtime.md`](../../../.claude/plans/studio/discovery/issues/14-workflow-runtime.md).
Harness: [`tests/spike/srt/`](../../../tests/spike/srt/) (`645a2a0`, hai sửa của làn ở commit kết quả, xem "Cách chạy
lại"). Mọi số ở đây là _measured_ trên máy dev ngày 4/11/2026, không phải máy tham chiếu.

## Cách chạy lại

```sh
export DW_TEST_DB_SUFFIX=_lane2
uv run python tests/spike/srt/run_srt.py setup            # dw_spike_srt_lane2 ở head của migration, schema srt
uv run python tests/spike/srt/run_srt.py measure t1 t1r t2 t6 t7 t8 q1 q6 q3 q2 t4 t3 t5 --out <thư mục>
uv run pytest tests/spike/srt -m unit                     # tài liệu nào cũng biên dịch, làn không chung kênh
uv run pytest tests/spike/srt -m integration              # golden trace, bộ đếm bước, cột keyed của ma trận sập
```

Mỗi phép đo ghi `<thư mục>/<tên>.json` và log JSONL của từng tiến trình worker vào `<thư mục>/<tên>/`. Lần chạy ghi ở
đây: `measure t1 t1r t2 t6 t7 t8 q1 q6 q3 q2 t4 t3 t5` bắt đầu 21:38 ngày 4/11/2026 trên cây `94c43ee` (gồm harness
`645a2a0`), rồi `measure q3 q2 t5` lúc 23:21 sau hai sửa của làn nguyên mẫu, cả hai ở commit kết quả: lệnh nhận việc
dạng CTE (Phát hiện 1; sửa trước khi T3 bắt đầu, nên T3 đã chạy với nó) và một chu kỳ nhận lỗi không làm worker dừng
(lần T5 đầu bị bỏ: một `PoolTimeout` trong chu kỳ nhận làm cả hai worker dừng và 258 lượt nằm lại `queued`). Số của q3,
q2 và T5 ở đây là của lần chạy lại; t1-t4, t6-t8, q1, q6 là của lần chạy đầu, không chạm hai chỗ sửa (hàng đợi của chúng
không quá vài lượt).

## Máy và cấu hình

- Windows 11 (10.0.26300), AMD Ryzen 7 7735U, 16 luồng, 15,2 GiB; Docker Desktop 16 CPU, 7,9 GB.
- PostgreSQL 16.15 (`postgres:16-alpine`) của compose `dwskel`, 127.0.0.1:25432, **container không giới hạn CPU hay bộ
  nhớ**, `shared_buffers` 128 MB, `max_connections` 100, `synchronous_commit` on; dùng chung với làn build 1.
  Ticket nói đo trên 4 vCPU / 3 GiB của research.md mục 5: không áp ở đây, vì lần giao việc chỉ định Postgres của
  dwskel; số tuyệt đối của T4, T5, câu 2 và câu 6 vì thế không so thẳng với số của research.md.
- Python 3.12, langgraph 1.2.11, langgraph-checkpoint 4.2.0 (`uv.lock`), SQLAlchemy 2.0.54, asyncpg 0.31.0.
- Database `dw_spike_srt_lane2`, `dw_app` cho mọi worker (RLS), `dw_migrator` cho harness và cho nhà cung cấp giả.
- Hai tiến trình worker thật cho mọi phép đo (T3 thêm một tiến trình "nạn nhân" mỗi ô). Sập thật: `os._exit(17)` tại
  điểm đặt tên (như wf-lite/02), `TerminateProcess` cho T4; treo thật: `time.sleep` chặn cả event loop, heartbeat cũng
  dừng.
- Làn: lease 60 giây, heartbeat 15 giây, reaper mỗi 5 giây với backoff `min(2^attempt × 5 s, 10 phút)`, lô 8 mỗi worker,
  `durability="sync"`, NOTIFY đánh thức cộng thăm dò 1 giây, rào lease gộp vào câu gắn tenant (câu 1).
- Cửa tác động ngoài là `ToolExecutor` thật với `SqlToolClaims`, `SqlToolExecutionStore` (runtime-hardening/01), công cụ
  `external`, `timeout_seconds` 5 (claim sống 35 giây, dưới lease 60 giây).

## Phương án A đã dựng gì

`srtlib/compiler.py` hạ cây Bước (mô hình `Step` của wf-lite, thêm `retry`, `timeout_s`, `on_error`, `error_lane` như
Amendments 2026-11-03 của ADR-0112) sang `StateGraph` theo quyết định 4: switch là cạnh điều kiện gộp ở node rỗng; mỗi
làn `logic.parallel` là một node subgraph có lược đồ riêng, chỉ xuất kênh `out__` của Bước trong làn, gộp bằng một
waiting edge; `logic.loop` là vòng do-while có trần, đếm ở `iter__<id>`, `logic.break` là cạnh tới lối ra; `logic.map` là
một `Send` cho mỗi khúc 20 phần tử vào fan-in `defer=True`; `flow.subworkflow` tạo lượt con rồi chờ ở node riêng; mọi
điểm chờ là `interrupt()` ở dòng đầu của node riêng. Wrapper của quyết định 5 giữ bộ đếm bước theo lượt (`UPDATE ...
RETURNING` rào bằng `lease_owner`), retry có backoff chỉ với `not_dispatched` hay `rejected` thử lại được, `on_error`
(`fail`, `continue`, `route`, `incident`) và đỗ `outcome_review` không áp `on_error`. Đây là nguyên mẫu, không phải mã của
`wflite/compile.py`: workflow-engine/03 và /06 dựng phần đó.

## Bảng T1-T9

| #   | Ngưỡng                                                                                                                                                                              | Số đo                                                                                                                                                                                                                                                                                                                                                                                                   | Kết quả                                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| T1  | Golden trace RW1-RW6 và biến thể: 100%                                                                                                                                              | 15/15 ca (13 ở `t1`, 2 ở `t1r`); chi tiết ở "Golden trace"                                                                                                                                                                                                                                                                                                                                              | **Đạt**                                                              |
| T2  | ≥ 3 bước xong trong ≤ 5 giây khi một làn chờ backoff                                                                                                                                | 5 bước xong trong 1,06-1,07 giây trong khi `budget` chờ backoff 5 giây (xong lại ở 5,10-5,23 giây), 3/3 lượt                                                                                                                                                                                                                                                                                            | **Đạt**                                                              |
| T3  | Khóa hay tra cứu: đúng 1 lần; không gì: 0 lần tự gửi lại ở T, K4, S, `outcome_review`; nội bộ 0 lần ghi trùng; RW5 không bao giờ hai kênh; gỡ `dispatched` thì K4 của "không gì" đỏ | 42 ô: có khóa 10/10 đúng 1; tra cứu 10/11 (ô `lookup-SbX`, bên giữ treo sau `dispatched` không heartbeat được: **2**); không gì: T, K4, Sb, SbX đỗ `outcome_review` với 0 lần tự gửi lại; nội bộ 0 lần ghi trùng; RW5 0 lần hai kênh; hai đối chứng đỏ                                                                                                                                                  | **Trượt** một ô (tra cứu, W2)                                        |
| T4  | Resume ≤ 90 giây; lượt đỗ resume được hai chiều                                                                                                                                     | giết worker giữa lượt: 8 lượt resume ở worker kia sau 56,9-68,9 giây (p50 65,3, max 68,9); tắt có trật tự: 0,81 giây, `attempt` 0; đỗ ở compiler `c1` resume ở `c2` và ngược lại: đạt; đổi tên node chờ (`c2-renamed`): lượt `completed` mà `publish` không chạy                                                                                                                                        | **Đạt**                                                              |
| T5  | 1.000 RW3 đồng thời: 0 lượt hỏng, khoảng cách bước p95 ≤ 250 ms, công bằng                                                                                                          | Thiết kế làn của workflow-engine/04 (1.000 lượt nhận cùng lúc, hai worker lô 8): 1.000/1.000 `completed`, 0 hỏng; khoảng cách giữa hai node p95 203 ms (saver hiện tại) và 187 ms (blob), giữa hai Bước p95 118 / 113 ms; 421 Bước/giây. Nếu đẩy 1.000 lượt bay cùng lúc trong hai tiến trình (lô 500, pool 20+20, như mốc 506/1.000): 810 và 786 lượt hỏng vì `QueuePool ... timeout` với cả hai saver | **Đạt** với trần lô của làn; trượt khi không có trần, không do saver |
| T6  | Lượt đỗ ≤ 20 KB; 20 bước × 100 KB ≤ 3 MB                                                                                                                                            | đỗ: RW1 6,7 KB, RW4 6,1 KB, RW2 22,4 KB (10 trong 16 checkpoint là của namespace làn; bản mới nhất mỗi namespace 4,3 KB); 20 × 100 KB: saver hiện tại 22,5 MiB, blob theo kênh 3,95 MiB, blob tỉa write của checkpoint cha 2,09 MiB; 20 × 60 KB (dưới trần 64 KiB): 13,5 / 2,39 / 1,21 MiB                                                                                                              | **Trượt** với saver hiện tại                                         |
| T7  | Chỉ node lỗi và sau nó chạy; 0 tác động của 1-6 gửi lại; giữ `run_id`                                                                                                               | `s7` 3 lần thử → đỗ `incident`; sửa nhà cung cấp, "retry" ở worker kia → `s7` chạy lại cùng khóa, áp dụng 1; `s1`-`s6`, ba làn và `join__s2` mỗi thứ 1 lần; `budget`, `s3`, `s6` áp dụng 1; cùng `run_id`                                                                                                                                                                                               | **Đạt**                                                              |
| T8  | Mọi bước dừng ≤ 5 giây; mọi điểm chờ `cancelled` trong cùng giao dịch                                                                                                               | với NOTIFY hủy: bước đang chạy dừng sau 12-42 ms (RW2 ba làn 30 giây, RW6 cháu đang chạy), dòng chờ `child_run` và `approval` đóng cùng một `now()` với lượt; chỉ heartbeat 15 giây (thiết kế W1 của workflow-engine/04): 13,8-14,0 giây                                                                                                                                                                | **Đạt** với NOTIFY, **trượt** với heartbeat                          |
| T9  | Chỉ áp cho C                                                                                                                                                                        | không dựng C                                                                                                                                                                                                                                                                                                                                                                                            | Không áp                                                             |

## T5 chi tiết

`measure t5`, RW3 (map 100 phần tử, mỗi phần tử một `ai.llm` 0 giây với đầu ra 1 KB, `max_parallel` 10 → fan-in →
`summary`), 1.000 lượt chèn liền nhau, cứ mười lượt một lượt của công ty D, còn lại của C. Khoảng cách giữa hai Bước:
với mỗi dòng Bước chạy, thời điểm bắt đầu trừ lần kết thúc gần nhất trước nó của cùng lượt, trên 200 lượt lấy mẫu đều;
"giữa hai node" bỏ các phần tử của map (chạy nối nhau trong một node khúc).

| Cấu hình                        | Saver    | Kết quả                                                                          | Giữa hai node p50 / p95 / p99 ms | Giữa hai Bước p95 ms | Bước/giây | Chờ hàng p50 C / D giây | Checkpoint mỗi lượt |
| ------------------------------- | -------- | -------------------------------------------------------------------------------- | -------------------------------- | -------------------- | --------- | ----------------------- | ------------------- |
| làn: 2 worker × lô 8, pool 10   | hiện tại | 1.000 `completed`                                                                | 114 / 203 / 267                  | 118                  | 421       | 120 / 115               | 424 KB              |
| làn: 2 worker × lô 8, pool 10   | blob     | 1.000 `completed`                                                                | 112 / 187 / 242                  | 113                  | 424       | 124 / 124               | 220 KB              |
| dồn: 2 worker × lô 500, pool 20 | hiện tại | 190 `completed`, 810 `failed` (798 `TimeoutError` của pool, 12 `InterfaceError`) | 270 / 1.165 / 1.860              | 5.681                | 246       | 14 / 11                 | 86 KB (lượt dở)     |
| dồn: 2 worker × lô 500, pool 20 | blob     | 214 `completed`, 786 `failed` (768 / 18)                                         | 260 / 915 / 3.191                | 3.847                | 276       | 19 / 11                 | 54 KB (lượt dở)     |

Đọc: với trần lô của làn, không lượt nào hỏng và khoảng cách giữa hai node dưới 250 ms ở cả hai saver (mốc của research
là 506/1.000 hỏng và p95 0,54 giây trong một tiến trình). Không trần, lượt hỏng vì pool kết nối của tiến trình cạn,
không vì PostgreSQL hay saver: saver blob ghi ít hơn một nửa (220 KB so với 424 KB mỗi lượt) mà không cứu được lượt nào.
Công bằng: hai công ty chờ theo thứ tự đến (D p50 115-124 giây, C 120-124 giây, khi lượt của D xen đều vào hàng), và câu
3 cho thấy công ty D không chờ sau 10.000 lượt đã xếp của C. Thời gian chờ hàng ở đây là sức chứa của 16 chỗ, không phải
độ trễ của engine.

## Luật quyết

- **A đạt T1, T2 và T7** (golden trace 15/15, 5 Bước xong trong 1,07 giây khi một làn chờ backoff, Chạy tiếp từ Bước
  lỗi chỉ chạy lại Bước lỗi cùng khóa), nên luật quyết **chọn A**: LangGraph chạy cây Bước, mỗi làn song song một subgraph,
  `durability="sync"`; không dựng C, không mở B, và workflow-engine/03 đi tiếp trên A.
- A cũng đạt T4 (resume 56,9-68,9 giây, compiler kế tiếp hai chiều) và T5 với trần lô của làn.
- A trượt ở chỗ không thuộc LangGraph, nên theo dòng cuối của luật quyết không đổi engine, ghi số và nguyên nhân, và phần
  của nền tảng được sửa ở ticket nêu:
    - T6 với saver hiện tại (22,5 MiB cho 20 × 100 KB; lượt RW2 đỗ 22,4 KB): saver, xem Phát hiện 6. Saver blob có tỉa
      write đạt (2,09 MiB). T5 không trượt vì saver, nên dòng "T5 trượt chỉ vì saver" không kéo saver blob lên W1; việc
      đưa nó lên vì T6 là một quyết định của Đạt, chưa ai quyết (workflow-engine/03, Comments).
    - T8 khi worker chỉ có heartbeat 15 giây: làn (NOTIFY hủy), Phát hiện 3.
    - T3 ở một ô của chế độ tra cứu (W2): đường gửi, Phát hiện 5. Lõi W1 (`review`) đạt mọi ô.
- Không trượt nào có nguyên nhân ở LangGraph, nên không có lựa chọn tạm phải quay lại Đạt trước workflow-engine/03.

## Golden trace (T1, câu 7, 8, 9, 11)

Mỗi ca chạy trên hai worker, `alternate` bật: mỗi lần quay lại hàng sau một điểm chờ được nhận ở worker kia. Trace là các
dòng `srt.run_steps` mà wrapper và node của trình biên dịch ghi (`node`, `iteration_path`, worker, thứ tự).

| Ca                                     | Kiểm                                                                                                                                                                                                                                                          |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RW1 duyệt / từ chối / mặc định         | đúng tập Bước (`score`, `route`, `approve`, `email`\|`note`\|`nurture`, `log`) mỗi Bước 1 lần, thứ tự `score < route < log`, resume ở worker kia, email áp dụng 1                                                                                             |
| RW2 PO thành / PO lỗi                  | ba làn mỗi làn 1, `join__check` bắn 1 lần trước `approve2`, hai phê duyệt dưới một dòng chờ, `po` 1 hay 3 lần thử, làn lỗi `release` chỉ khi lỗi, `budget` áp dụng 1                                                                                          |
| RW2 câu 7                              | làn 1,0 giây cạnh làn 3 × 0,3 giây: khối xong sau 1,23 giây (làn ngắn xong ở 1,17, làn dài 1,18; không theo nhịp chung 1,61 của bộ nhớ); điểm nối lồng 1 lần; switch trong làn chọn đúng một ca; song song trong thân vòng gộp 1 lần mỗi vòng (`rounds=1..3`) |
| RW2 làn lỗi không có làn bắt           | hai làn kia `cancelled` sau 18-19 ms, hai audit `studio.branch.cancelled`, `join__check` không bắn, Bước sau không chạy, lượt `failed`                                                                                                                        |
| RW3 map 100                            | 100 `score_item` với 100 `iteration_path` khác nhau, fan-in 1 lần, `summary` 1 lần sau fan-in                                                                                                                                                                 |
| RW4 sửa lại                            | từ chối, từ chối, duyệt → `draft` 3, `review` 3, `revise` 2, `logic.break` 1, `publish` 1, ba interrupt id khác nhau, resume luân phiên worker; năm lần từ chối → `max_reached` (`escalate`) 1                                                                |
| RW4 câu 8 (`t1r`, `recursion_limit` 8) | vòng 10 lần, mỗi vòng một phê duyệt, `max_steps` 13: dừng `limit_exceeded` đúng ở Bước thứ 14 (vòng 7), 6 interrupt id khác nhau, 7 lần ghi nội bộ mỗi vòng 1, `after` không chạy; cùng vòng không chờ → `GraphRecursionError` sau 4 Bước                     |
| RW5                                    | Zalo nhận: zalo 1, email 0; Zalo từ chối hẳn (400): zalo 0, email 1                                                                                                                                                                                           |
| RW6 câu 11                             | cha → con (điểm chờ phê duyệt ở con) → cháu, ba lượt `completed` ở độ sâu 0, 1, 2, mỗi Bước 1 lần                                                                                                                                                             |
| T7 / câu 9                             | xem T7                                                                                                                                                                                                                                                        |

## Ma trận sập (T3, câu 1 và 10)

`measure t3`, 42 ô, mỗi ô một lượt `effect` (`before` → `fx` → `after`) hay `internal`, `rw5`; một tiến trình nạn nhân
nhận lượt (`--only-run`) rồi sập (`os._exit`) hay treo 130 giây ở điểm của ô, rồi hai worker còn sống tiếp quản sau
lease 60 giây. "Áp dụng" là số dòng nhà cung cấp giả ghi khi nó thật sự áp dụng (chế độ có khóa không ghi lần trùng
khóa); "dòng gửi" là `platform.tool_executions` của khóa theo thời gian.

| Điểm                                           | Có khóa (`resend_same_key`)                                                                  | Có tra cứu (`lookup_then_resend`)                              | Không gì (`review`)                                                                     |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| K1 trước khi giành claim                       | 1, `completed`                                                                               | 1, `completed`                                                 | 1, `completed`                                                                          |
| K2 đã giành claim, chưa `dispatched`           | 1, `completed` (claim 35 giây hết trước lease 60 giây, tiếp quản)                            | 1, `completed`                                                 | 1, `completed`                                                                          |
| T gửi rồi mất trả lời                          | 1: `outcome_unknown` → `failed resend_requested` → gửi lại cùng khóa, nhà cung cấp khử trùng | 1: tra thấy đã nhận → ghi `succeeded`, không gửi lại           | 1, đỗ `outcome_review`, 0 lần tự gửi lại                                                |
| K4 có 2xx, sập trước dòng kết thúc             | 1 (gửi lại cùng khóa)                                                                        | 1 (tra thấy)                                                   | 1, đỗ `outcome_review`                                                                  |
| K5 đã ghi `succeeded`, sập trước checkpoint    | 1 (phát lại)                                                                                 | 1                                                              | 1                                                                                       |
| K6 sau checkpoint                              | 1, Bước hiệu ứng không chạy lại                                                              | 1                                                              | 1                                                                                       |
| Sa treo sau claim, trước `dispatched`          | 1; bên cũ tỉnh dậy bị chính heartbeat của nó hủy                                             | 1                                                              | 1                                                                                       |
| Sb treo sau `dispatched`, trước lời gọi        | 1                                                                                            | 1                                                              | 0, đỗ `outcome_review` (bên cũ bị heartbeat hủy trước khi gửi)                          |
| SaX như Sa, bên cũ không heartbeat được        | 1; claim của bên cũ đã bị tiếp quản nên `dispatched` của nó bị từ chối                       | 1                                                              | 1                                                                                       |
| SbX như Sb, bên cũ không heartbeat được        | 1 (khử trùng theo khóa)                                                                      | **2**: bên mới tra "chưa nhận" rồi gửi, bên cũ tỉnh dậy và gửi | 1, đỗ `outcome_review`; lần gửi muộn của bên cũ đóng dòng `dispatched` bằng `succeeded` |
| SbP như SbX, kiểm lại claim ngay trước lời gọi | —                                                                                            | 1                                                              | 0, đỗ `outcome_review`                                                                  |

- Nội bộ (bản ghi và khóa trong một giao dịch rào lease): K1, K5, K6, Sa (bên cũ không heartbeat): 0 lần ghi trùng, lần
  ghi của bên cũ bị rào từ chối.
- RW5 (Zalo, làn lỗi gửi email): T và K4 với Zalo có khóa → Zalo 1, email 0; với Zalo không gì → Zalo 1, email 0, lượt
  đỗ `outcome_review`; không ô nào giao cả hai kênh.
- Đối chứng: gỡ dòng `dispatched` (worker `--no-dispatch-log`) → K4 của "không gì" áp dụng **2**, đỏ như ticket đòi;
  ghi khóa của tác động nội bộ ở giao dịch thứ hai → K4 ghi bản ghi **2** lần, đỏ.
- Ở mọi ô S, mọi lần ghi checkpoint của bên cũ sau khi tỉnh bị rào từ chối (`fence_rejected` 1 ở mỗi tiến trình nạn nhân
  không heartbeat), không Bước sau nào có dòng của bên cũ: câu 1.

Kết quả: 41/42 ô đúng mong đợi, 2/2 ô đối chứng đỏ. Trượt duy nhất là `lookup-SbX`: "tra rồi gửi lại" không an toàn khi
bên giữ cũ có thể còn đang bay sau `dispatched`; kiểm lại claim (`token` và `expires_at`) ngay trước lời gọi đưa ô đó về
1, nhưng chỉ thu hẹp cửa sổ chứ không đóng nó (bên cũ vẫn có thể treo giữa phép kiểm và byte đầu tiên). W1 không có chế
độ tra cứu (H-5: mọi Action W1 là `review`), nên trượt này không chạm lõi W1.

## Các câu khác

### Câu 1: rào lease trong `aput` và `aput_writes`

`measure q1`: 600 lần `aput` rồi `aput_writes` liền nhau trên `FencedSaver` (saver của nền tảng, mỗi biến thể một lượt),
bỏ 100 lần đầu, đo phía harness:

| Rào                                                | Lượt đi về mỗi lần ghi | `aput` p50 / p95 / p99 ms | `aput_writes` p50 / p95 / p99 ms |
| -------------------------------------------------- | ---------------------- | ------------------------- | -------------------------------- |
| không rào (saver như đã ship)                      | 2                      | 5,54 / 7,85 / 9,06        | 5,19 / 7,16 / 8,06               |
| `SELECT ... FOR SHARE` riêng sau câu gắn tenant    | 3                      | 6,61 / 9,72 / 11,58       | 6,19 / 9,07 / 11,28              |
| gộp: `srt.lease_held()` trong chính câu gắn tenant | 2                      | 5,77 / 8,68 / 10,14       | 5,38 / 8,13 / 9,18               |

Trả lời: **có**, saver rào được lần ghi của bên giữ cũ ngay trong giao dịch của `aput` và `aput_writes` mà không thêm
lượt đi về, khi phép kiểm `FOR SHARE` nằm trong cùng câu `SELECT set_config(...)` đã có (hàm invoker, gọi sau
`set_config` trong cùng danh sách chọn nên RLS thấy tenant): +0,2 ms p50, +0,8 ms p95 mỗi lần ghi, so với +1,1 ms p50,
+1,9 ms p95 của một câu riêng. Từ chối: lease chuyển sang token mới thì `aput` và `aput_writes` của token cũ ném
`LeaseLostError` và giao dịch lùi, của token mới nhận. Đua: bên cũ giữ `FOR SHARE` trong giao dịch đang mở, lệnh nhận
của bên mới chờ trong `pg_locks` 0,161 giây tới khi bên cũ commit, rồi lease thuộc bên mới; lần ghi kế tiếp của bên cũ
bị từ chối. Trong T3, mọi bên giữ cũ bị treo (ca `S*`, `internal-Sa`) đều có đúng 1 lần ghi checkpoint bị rào từ chối
và 0 lần ghi nào của nó được nhận (Bước sau không có dòng nào của worker cũ).

Một phát hiện đi kèm (lần chạy đầu của T1, RW2): khi một giao dịch vừa `FOR SHARE` dòng lượt chạy (rào) vừa `UPDATE`
chính dòng đó (bộ đếm `steps_started`), hai làn song song của cùng lượt nâng khóa chia sẻ lên khóa ghi cùng lúc và
PostgreSQL báo `DeadlockDetectedError` (2/2 lượt RW2 `failed`). Lệnh tăng bộ đếm phải tự là rào (`WHERE lease_owner =
:token`), không đứng sau một `FOR SHARE` của cùng dòng trong cùng giao dịch; harness đã sửa vậy và T1 đạt.

### Câu 2: 2xx tới Bước đầu khi dồn tải, đánh thức bằng NOTIFY

`measure q2`. Endpoint nguyên mẫu: một giao dịch chèn dòng lượt `queued` và `pg_notify` (commit = 2xx, đo phía bên gửi
với pool có sẵn), 60 giây mở vòng ở 20 và 60 lần/giây, xen hai công ty; hai worker lô 8; quy trình `intake` (một
`ai.llm` 20 ms, một ghi nội bộ). "Tới Bước đầu" là `started_at` của dòng Bước chạy đầu trừ `received_at`, cùng đồng hồ
PostgreSQL.

| Đánh thức               | Tải     | 2xx p50 / p95 / p99 ms | Tới Bước đầu p50 / p95 / p99 giây |
| ----------------------- | ------- | ---------------------- | --------------------------------- |
| NOTIFY + thăm dò 1 giây | 20/giây | 6,1 / 8,8 / 10,8       | 0,041 / 0,066 / 0,113             |
| chỉ thăm dò 1 giây      | 20/giây | 6,1 / 8,2 / 10,6       | 0,091 / 0,240 / 1,175             |
| NOTIFY + thăm dò 1 giây | 60/giây | 7,0 / 9,2 / 11,3       | 14,7 / 27,1 / 28,4                |
| chỉ thăm dò 1 giây      | 60/giây | 7,2 / 9,6 / 11,6       | 18,1 / 30,4 / 31,5                |

Trả lời: 2xx p99 11-12 ms, xa dưới 1 giây (YC44, KQ8). Dưới sức chứa của làn (20/giây), NOTIFY đưa Bước đầu về p95 66
ms, p99 113 ms; thăm dò 1 giây cộng việc nhận lại ngay khi một chỗ trống (worker tự đánh thức khi một lượt xong) cho p95
240 ms, p99 1,2 giây. Ở 60/giây làn bão hòa (16 chỗ cho hai worker lô 8) và độ trễ tăng theo độ dài đợt dồn, như nhau
với hay không NOTIFY: đó là sức chứa, không phải cách đánh thức. NOTIFY đủ cho đánh thức; YC100 (tiếp nhận p95 ≤ 60
giây, W2) phụ thuộc lô và số worker, phải đo lại trên host thí điểm (ticket 20).

### Câu 3: trigger của công ty khác sau một lần nhập 100.000 bản ghi

`measure q3`. Công ty C nhập 100.000 bản ghi (100.000 sự kiện `srt.record_event` vào `platform.outbox_events`), rồi
công ty D phát một sự kiện.

| Hàng                                                                                                             | D được xử lý sau                                             |
| ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| outbox của nền tảng, `SqlOutboxDrain` thật (`claim_batch` 100 theo `occurred_at`, `mark_processed` từng sự kiện) | **533,2 giây**, lô thứ 1.001, sau đủ 100.000 sự kiện của C   |
| nguyên mẫu theo công ty (`srt.outbox_scopes_due`, mỗi công ty một lô 50 dưới RLS)                                | 0,086 giây, chu kỳ đầu                                       |
| làn lượt chạy: 10.000 lượt `queued` của C, rồi một lượt của D, hai worker lô 8                                   | Bước đầu của D sau 0,514 giây; 4 lượt của C bắt đầu trước nó |

Trả lời: **có**. Hàng outbox FIFO của nền tảng bắt trigger của công ty khác chờ sau cả lần nhập (533 giây ở 100.000 sự
kiện, tuyến tính theo số sự kiện đứng trước). Làn lượt chạy theo công ty (hàm định danh trả tenant, rồi nhận dưới RLS)
không chờ sau 10.000 lượt của công ty khác, với lệnh nhận ở dạng CTE (mục Phát hiện 1; dạng `IN (...)` ở lần chạy đầu
cho D chờ 112 giây vì một chu kỳ nhận 9.300 lượt). Quyết định: nguồn sự kiện của trigger bản ghi (W2, `record_event`)
không dùng chung hàng FIFO của `platform.outbox_events`, hay hàng đó phải được rút theo công ty.

### Câu 5: allowlist msgpack

Đã trả lời ở foundations-hardening/02 (`1c681e8`, Comments 29/10/2026): `ALLOWED = ()`. Mọi lượt của spike này chạy với
`allowlisted_serializer(())` qua cả hai saver, kể cả subgraph làn, `Send` của map và lượt con: không lượt nào lỗi nạp
checkpoint, nên allowlist rỗng đủ cho mọi kiểu state của cây Bước (dict, list, str, int, bool). Checkpoint giữ đầu ra
Bước như mọi kênh, không phải tham chiếu bản ghi; spike không có giá trị bản ghi thật nên không trả lời phần "chiếu lại
khi đọc" của câu 5, phần đó là của field-security/02.

### Câu 6: bản kê lượt chạy lúc nhận và khi resume

`measure q6`, mã của tenant-config/04 (`RunManifestBuilder`, `SqlRunManifestStore`, `PinnedResolver`), bao đóng 50 thành
phần `live` dựng bằng `dw_studio.testing`, 1.000 gốc khác nhau mỗi đường (mỗi lần dựng chèn thật), bỏ 20 lần đầu, đo cả
giao dịch `store.transaction()` của lần nhận:

| Đo                                                                  | p50 ms | p95 ms | p99 ms | n   |
| ------------------------------------------------------------------- | ------ | ------ | ------ | --- |
| dựng và ghi bản kê, gốc đã niêm phong, `live`                       | 23,4   | 30,9   | 40,9   | 980 |
| dựng và ghi bản kê, gốc Nháp, `simulate` (đi closure, JCS, băm tạm) | 131,9  | 168,0  | 194,1  | 980 |
| `PinnedResolver.load` khi resume, cùng tiến trình, nóng             | 6,3    | 7,8    | 8,3    | 280 |
| `PinnedResolver.load` ở tiến trình mới, kết nối mới                 | 69,8   | 93,4   | 98,7   | 20  |

Tiến trình mới còn tốn 416 ms p50 (493 p95) nạp module trước lần đọc, không tính vào dòng trên. Ngưỡng R6.6 của
tenant-config/04 (p95 ≤ 20 ms cho `build`) **trượt** ở máy này: 30,9 ms với gốc đã niêm phong; đường Nháp gấp 5,4 lần.

## Phát hiện cho các ticket đã gate

Mỗi mục đã ghi một dòng có ngày vào Comments của ticket nêu; không yêu cầu nào của ticket bị viết lại.

1. **Lệnh nhận việc** (workflow-engine/04 bước 2). `UPDATE ... WHERE id IN (SELECT ... LIMIT n FOR UPDATE SKIP
LOCKED)` dưới RLS, với 10.000 lượt vừa chèn chưa `ANALYZE`, thành một nested-loop semi join quét lại vế trong: một
   chu kỳ của một worker nhận 9.300 lượt thay vì 8 (q3, lần chạy đầu), cạn pool 10+10 kết nối, `QueuePool limit ...
timeout 30.00`, lease hết hạn và reaper xếp lại; lượt của công ty D bắt đầu sau 112 giây. Cùng dữ liệu, `WITH picked
AS MATERIALIZED (SELECT ... LIMIT n FOR UPDATE SKIP LOCKED) UPDATE ... FROM picked` nhận đúng n (đo bằng psql: dạng
   `IN` nhận 6 khi n = 4, dạng CTE nhận 4). Harness dùng dạng CTE từ commit kết quả; T3, T5, q2, q3 ghi ở đây chạy với nó.
2. **Rào và bộ đếm bước trong cùng giao dịch thì deadlock** (workflow-engine/04 bước 4, /06 bước 5): mục câu 1.
3. **Hủy giữa chừng cần đánh thức xuyên tiến trình** (workflow-engine/04, /09): T8 trượt với heartbeat 15 giây (13,8-14,0
   giây) và đạt với NOTIFY (12-42 ms); 04 bỏ NOTIFY `dw_run_state` khỏi W1, còn R8.5 của 09 chỉ kiểm "không node nào bắt
   đầu sau 5 giây", nên một Bước 30 giây đang chạy của lượt con vẫn chạy tiếp 14 giây sau khi hủy mà R8.5 vẫn xanh.
4. **Compiler đổi tên node chờ thì lượt đỗ kết thúc im lặng** (workflow-engine/05): T4, lượt đỗ ở `wait__review` resume
   dưới `c2-renamed` thành `completed` mà `publish` không chạy, không lỗi; đổi thêm kênh hay thêm node khác thì resume hai
   chiều đạt. Phép kiểm resume của ADR-0109 quyết định 8 là thứ duy nhất bắt ca này.
5. **Lookup sau khi bên giữ treo sau `dispatched`** (workflow-engine/08, W2 `lookup_then_resend`): T3 ô `lookup-SbX`.
6. **Dung lượng checkpoint** (workflow-engine/03, saver): T6; RW2 đỗ 22,4 KB vì checkpoint của namespace làn còn nằm
   tới lane lưu giữ (7 ngày).
7. **Bản kê lượt chạy** (tenant-config/04 R6.6): p95 30,9 ms với gốc đã niêm phong, trên ngưỡng 20 ms.

## Chưa đo, và vì sao

- **Máy tham chiếu và host thí điểm.** Mọi số là của máy dev ở trên, với PostgreSQL của compose không giới hạn CPU và bộ
  nhớ và dùng chung với một làn build khác. Cấu hình 4 vCPU / 3 GiB của research.md mục 5 không được áp (lần giao việc
  chỉ định Postgres của dwskel), và host thí điểm 2 vCPU / 8 GB rồi 4 vCPU / 16 GB là của ticket 20 (Chờ Đạt 23). Số
  tuyệt đối của T4, T5, câu 2 và câu 6 phải đo lại ở đó; các kết quả đúng/sai (T1, T2, T3, T7, T8, câu 1, 3, 7-9, 11)
  không phụ thuộc máy.
- **Nhà cung cấp thật.** Ba chế độ là nhà cung cấp giả tại chỗ; khử trùng theo khóa của một nhà cung cấp thật trong
  `retention_hours` của nó, thời gian một lần tra cứu thấy lần gửi vừa áp dụng, và việc Gmail khử trùng theo
  `Message-ID` (ADR-0116 ghi UNVERIFIED) không đo được ở đây.
- **Mã sản phẩm của workflow-engine/03-09.** Spike đo nguyên mẫu của phương án A, không đo `wflite/compile.py` sau khi
  03 và 06 mở rộng nó, cũng không đo `RunWaitPort.open(detail)`, `effect_door` hay bảng `incident` của 05, 07, 08 (chưa
  dựng). Golden trace ở đây là bằng chứng cho engine, không thay bộ golden trace R7 mà 03 dựng.
- **Saver blob theo kênh dưới RLS ở khối lượng thật, lưu giá trị trên 64 KiB theo tham chiếu, và xóa sau 24 giờ** (quyết
  định 10): nguyên mẫu ở đây giữ mọi giá trị trong PostgreSQL và không xóa gì.
- **Câu 4** đã bỏ (V4.36, H-13). **Câu 5** đã trả lời ở foundations-hardening/02; phần "chiếu lại giá trị bản ghi khi
  đọc" là của field-security/02, spike không có giá trị bản ghi thật.
- **LangGraph 1.2.16** và lần resume chéo phiên bản thư viện: không đo lại (ADR-0112 Consequences đã ghi 1.2.11 và 1.2.16
  resume lượt của nhau); T4 chỉ đo compiler kế tiếp trên cùng phiên bản thư viện.
