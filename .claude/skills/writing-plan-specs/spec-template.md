# Mẫu `spec.md`

Tệp này là chủ duy nhất của định dạng spec tính năng,
`.claude/plans/<area>/<feature-slug>/spec.md`. `writing-plan-specs` viết theo nó,
`checking-plan-readiness` kiểm theo nó, và `scripts/check_plans.py` đọc hai khối ở đây: khối
`markdown template` cuối tệp (mục nào bắt buộc, dòng đầu nào phải có) và khối `ids` (mã định danh
trông thế nào). Đổi định dạng thì đổi ở đây, không ở đâu khác.

Cách viết một tiêu chí (EARS-VN, dấu delta, mã bị rút) ở `ears-vn.md`. Mẫu ticket ở
`ticket-template.md`, mẫu yêu cầu cấp area ở `requirements-template.md`.

## Cách đọc khối mẫu

- Mỗi tiêu đề cấp hai (`##`) trong khối là một mục của spec, theo đúng thứ tự đó; tiêu đề cấp ba
  trong khối chỉ là ví dụ. Tên mục so khớp phần đứng trước dấu ngoặc đầu tiên, nên "Hiện trạng (đã
  kiểm ở ...)" là mục "Hiện trạng".
- Mục có dòng `<!-- TUY CHON: ... -->` ngay dưới là tùy chọn: dùng thì viết đủ, không dùng thì bỏ
  hẳn, không bao giờ để "N/A" hay "Không áp dụng".
- Mục có dòng `<!-- CO THE RONG -->` là bắt buộc nhưng được để trống khi chưa có gì (chưa có câu
  hỏi, chưa có quyết định, chưa cắt ticket).
- Mọi mục khác bắt buộc và phải có nội dung. Không có gì để ghi thì viết `Không có.`; ở mục Kiểm
  soát, kèm lý do một dòng.
- Mục không có trong khối là lệch định dạng. Ba tên cũ không dùng nữa: "Quy tắc và kiểm soát" (nay
  là Kiểm soát), "Quy tắc và quyết định" (nay là Quyết định), "Tiêu chí xong của slice" (nay là Tiêu
  chí xong).
- Khi chép khối thành spec thật: thay mọi `<...>`, xóa các dòng `<!-- ... -->` của mẫu. Một
  `<...>` của mẫu còn sót lại là chỗ chưa điền, và script coi đó là lỗi.

## Dòng đầu tệp

Bốn dòng liền nhau ngay dưới tiêu đề `#`, theo thứ tự này. Một dòng có nhiều phần thì các phần cách
nhau bằng dấu chấm giữa `·` (U+00B7) với một khoảng trắng mỗi bên.

| Dòng        | Giá trị cho phép                                                                                                                                                                                    | Ai ghi                                                                                                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Status:`   | một nhãn trong `docs/agents/triage-labels.md`; sau nhãn chỉ được thêm một ghi chú trong ngoặc                                                                                                       | writer: `needs-triage`, `needs-info`; gate: `ready-for-agent` hoặc hạ về `needs-triage`; người đóng việc: `resolved (<yyyy-mm-dd>, <nhánh>)`                                            |
| `Area:`     | `Area: <area> · Nhánh: <nhánh trong backtick> · Viết: <d/m/yyyy>`; `<area>` trùng tên thư mục area                                                                                                  | writer                                                                                                                                                                                  |
| `Duyệt:`    | `chưa`, `Đạt <d/m/yyyy>` hoặc `agent, tạm theo ủy quyền <d/m/yyyy>`                                                                                                                                 | writer, chỉ khi Đạt nói duyệt; dạng ủy quyền chỉ khi mục Ủy quyền của area file có dòng `Ủy quyền duyệt: Đạt, spec, từ <d/m/yyyy>` (`requirements-template.md`) với ngày không muộn hơn |
| `Sẵn sàng:` | `chưa kiểm`; `<ĐẠT, CẦN XEM hay CHƯA ĐẠT> (<d/m/yyyy>; <n> CRITICAL, <n> HIGH)`; hoặc, khi lượt kiểm gồm ticket, `<ĐẠT, CẦN XEM hay CHƯA ĐẠT> (<d/m/yyyy>; <n> CRITICAL, <n> HIGH; ticket <NN-NN>)` | gate; writer chỉ được đặt lại `chưa kiểm`                                                                                                                                               |

Quy tắc đi kèm:

- Đổi bất cứ gì trong Mục tiêu, Hành vi giữ nguyên, Trong phạm vi, Ngoài phạm vi, Kiểm soát hay Phụ
  thuộc thì đặt lại `Sẵn sàng: chưa kiểm` và `Duyệt: chưa`, và hạ spec cùng mọi ticket đang
  `ready-for-agent` của nó về `needs-triage`. Một lần duyệt chỉ phủ đúng bản Đạt đã đọc.
- Phần `ticket` của `Sẵn sàng:` liệt kê các ticket lượt kiểm đã xem, dạng dải `01-04` hoặc danh sách
  `01, 03`. Ticket không có trong đó chưa được kiểm, nên chưa được `ready-for-agent`.
- Ngày trong spec viết `d/m/yyyy` (`3/10/2026`), như các spec hiện có; riêng ngày trong
  `resolved (...)` viết `yyyy-mm-dd`, như các ticket hiện có.

## Mã định danh

Mã là ASCII để `grep` tìm được và khác biệt NFC/NFD không che được. Một mã đã có nơi trích thì
không bao giờ đánh số lại hay dùng lại; rút một mã thì giữ dòng của nó với `[Bỏ]` (`ears-vn.md`).

| Mã                        | Ví dụ                 | Chỗ định nghĩa                                                         | Quy tắc                                                                                      |
| ------------------------- | --------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `R<n>`                    | `R2`                  | tiêu đề `### R2 — <tên>` trong Mục tiêu                                | một yêu cầu; dòng đầu nói ai được gì                                                         |
| `R<n>.<m>`                | `R2.3`                | đầu một dòng gạch đầu dòng dưới `R<n>`, hoặc ô đầu của bảng quyết định | một tiêu chí EARS-VN; `m` đếm từ 1 trong mỗi `R<n>`                                          |
| `G<n>`                    | `G1`                  | đầu dòng trong Hành vi giữ nguyên                                      | hành vi đang có phải giữ, kèm test hồi quy                                                   |
| mã kiểm soát              | `TM1`                 | cột `#` của bảng Kiểm soát                                             | 2-4 chữ hoa rồi số; tiền tố riêng của spec, không trùng trong cả area; không dùng `YC`, `KQ` |
| `Q<n>`                    | `Q2`                  | đầu dòng trong Câu hỏi còn mở                                          | trả lời xong thì xóa dòng câu hỏi; số không dùng lại                                         |
| `[CAN LAM RO: Q<n>]`      | `[CAN LAM RO: Q2]`    | ngay chỗ thiếu câu trả lời                                             | trỏ tới một `Q<n>` còn mở; tối đa ba trong một bản nháp                                      |
| `<feature-slug>:R<n>.<m>` | `support-access:R1.2` | nơi trích                                                              | tiêu chí của spec khác cùng area; khác area thì `<area>/<feature-slug>:R<n>.<m>`             |
| `ADR-NNNN`                | `ADR-0024 (Proposed)` | nơi trích                                                              | ghi trạng thái trong ngoặc ngay sau mã; script so với `status` của tệp ADR                   |
| `YC<n>`, `KQ<n>`          | `YC3`, `KQ1`          | `requirements.md`                                                      | xem `requirements-template.md`                                                               |

Khối dưới là định nghĩa mà script đọc: mỗi dòng `<tên> <biểu thức chính quy Python>`. Một mã khớp
trọn vẹn: không đứng sau chữ hay số, không đứng trước chữ, số, hay dấu chấm theo sau là số; loại
dài hơn khớp trước (`R2.3` không phải `R2`). Mã kiểm soát và `G<n>` chỉ được hiểu là mã ở chỗ có
cấu trúc (bảng Kiểm soát, đầu dòng trong Hành vi giữ nguyên, đầu ô `Việc` của Ngoài phạm vi, dòng
`Yêu cầu:`, đầu tiêu chí chấp nhận), vì chữ như `UTF8` cũng khớp mẫu.

```ids
requirement R[1-9][0-9]*
criterion R[1-9][0-9]*\.[1-9][0-9]*
unchanged G[1-9][0-9]*
control (?!YC|KQ)[A-Z]{2,4}[1-9][0-9]*
question Q[1-9][0-9]*
marker \[CAN LAM RO: Q[1-9][0-9]*\]
cross-ref (?:[a-z0-9]+(?:-[a-z0-9]+)*/)?[a-z0-9]+(?:-[a-z0-9]+)*:R[1-9][0-9]*\.[1-9][0-9]*
adr ADR-[0-9]{4}
yc YC[1-9][0-9]*
kq KQ[1-9][0-9]*
```

## Từng mục

**Hiện trạng.** Tiêu đề mang dấu kiểm: sha ngắn (7-40 ký tự hex) của commit đã đọc và ngày đọc.
Mỗi dòng là một sự thật có neo và một nhãn:

- Neo là một code span `<đường dẫn từ gốc repo>:<dòng>` hoặc `<đường dẫn>:<dòng đầu>-<dòng cuối>`,
  mỗi neo một span. Không viết tắt `:139` hay đường dẫn tương đối: script mở đúng tệp đó và đếm dòng.
  Neo ở dòng `Trước đây:` của Mục tiêu và ở mục Nguồn của ticket theo cùng dạng, và được kiểm như
  nhau.
- Nhãn: `Thiếu` (tính năng cần mà code chưa có), `Chưa rõ` (chưa xác lập được; thành câu hỏi
  hoặc ticket nghiên cứu), `Ràng buộc` (hành vi đang có mà thiết kế phải theo).
- Viết như trả lời câu hỏi trung tính (X chạy thế nào, ở đâu, cái gì chạm vào nó), không nói sẽ làm
  gì.

**Mục tiêu.** Mỗi yêu cầu là `### R<n> — <tên ngắn>` (gạch dài), có thể thêm dấu delta `[Sửa]`,
`[Bỏ]` hay `[Đổi tên]` ở cuối tiêu đề. Dòng đầu nói ai được gì. Tiêu chí là
`- R<n>.<m> <câu EARS-VN>`: một câu, một `PHẢI`. Không ghi mã kiểm soát vào câu: bảng Kiểm soát là
chủ duy nhất của việc kiểm soát nào canh tiêu chí nào. Khoảng 10 yêu cầu và 500 ký tự mỗi tiêu chí
là trần; vượt thì tách spec.

**Kiểm soát.** Một dòng cho mỗi tiêu chí `NẾU ... THÌ` canh một chủ đề không bao giờ đoán (danh
sách ở nhóm 3 của `.claude/skills/checking-plan-readiness/quality-checklist.md`), và cho mỗi
anti-goal (một thất bại kể cả khi chạy được). Cột `Yêu cầu` liệt kê `R<n>.<m>` hoặc `G<n>` mà dòng đó canh. Cột
`Test âm` nói gọi gì và khẳng định gì, một test sẽ đỏ khi gỡ kiểm soát.

**Ngoài phạm vi.** Cột `Chủ` là spec, area hay context chịu việc đó; `đợt sau` khi chưa làm bây
giờ; `không làm` khi không bao giờ là việc của ta. Một tiêu chí bị hoãn ghi mã ở đầu ô `Việc`
(`R3.2: gửi email lời mời`) thì được tính là đã phủ.

**Phụ thuộc.** Chỉ những gì spec được phép dựa vào: seam nền tảng, Protocol do bên dùng khai, hợp
đồng của spec khác (trích bằng mã). Dòng `Kiểm lại khi:` nói thay đổi nào buộc kiểm lại spec hay
ticket nào.

**Câu hỏi còn mở.** Mỗi câu một dòng:
`- Q<n>. <câu hỏi>? Chủ: <ai>. Chặn: <mã, ticket>.` Câu trả lời không đổi được gì đã viết thì thay
`Chặn:` bằng `Không đổi: <điều không thể đổi>.` Còn một câu không có `Không đổi:` thì spec chưa
được `ready-for-agent`.

**Quyết định.** Nhật ký chỉ thêm, theo thứ tự ngày, mỗi dòng
`- <d/m/yyyy> (<ai>): <quyết định>.` rồi, khi có, `Hỏi: Q<n>.`, `Sửa: <mục hoặc mã>.`,
`Nếu sai thì: <điều gì đổi>.` `<ai>` là `Đạt`, `agent, tạm` hoặc `agent, tạm theo ủy quyền`. Các
dòng có dạng cố định:

- duyệt cách chia ticket: `- <d/m/yyyy> (Đạt): Duyệt cách chia ticket <NN-NN>.`, hoặc `(agent, tạm theo ủy quyền)` thay `(Đạt)` khi mục Ủy quyền của area file có dòng `Ủy quyền duyệt: Đạt, spec, từ <d/m/yyyy>` không muộn hơn: một ủy quyền spec phủ cả `Duyệt:` lẫn cách chia ticket của spec đó;
- rủi ro chấp nhận, chỉ Đạt ghi: `Chấp nhận rủi ro: <rủi ro>; <vì sao>.`;
- đề xuất bị từ chối: `Không nhận: <đề xuất>; <lý do>.` Không nêu lại nếu không có bằng chứng mới;
- nguồn lệch nhau: `Mâu thuẫn nguồn: <nguồn A> nói <X>, <nguồn B> nói <Y>; theo <cái nào>.`

**Danh sách ticket.** Chỉ link, không chép `Status` hay `Blocked by`: ticket là chủ của chúng, và
`scripts/check_plans.py --table <spec>` in bảng sống khi cần.

## Khối mẫu

```markdown template
# <Tên tính năng>

Status: needs-triage
Area: <area> · Nhánh: `<branch>` · Viết: <d/m/yyyy>
Duyệt: chưa
Sẵn sàng: chưa kiểm

<Một đoạn: ai cần gì, vì sao bây giờ. Ý định nói được trong một câu.>

## Hiện trạng (đã kiểm ở `<sha>` ngày <d/m/yyyy>)

- <điều đang có> (`<path>:<line>`). <Thiếu, Chưa rõ hoặc Ràng buộc>: <một dòng>.

## Mục tiêu

### R1 — <tên ngắn>

<Ai được gì, một dòng.>

- R1.1 KHI <sự kiện>, <chủ thể> PHẢI <phản hồi quan sát được>.
- R1.2 NẾU <điều kiện xấu>, THÌ <chủ thể> PHẢI <từ chối cụ thể> và không đổi gì.

### R2 — <tên ngắn> [Sửa]

Trước đây: <hành vi cũ> (`<path>:<line>`).

- R2.1 TRONG KHI <trạng thái>, <chủ thể> PHẢI <phản hồi mới>.

## Hành vi giữ nguyên

<!-- TUY CHON: chỉ khi spec đổi hành vi đang có -->

- G1 KHI <điều kiện>, <chủ thể> PHẢI TIẾP TỤC <hành vi hiện có> (test: `<tên test>`).

## Trong phạm vi

- <bảng, route, port, sự kiện, màn hình mà spec này là chủ>.

## Ngoài phạm vi

| Việc   | Vì sao  | Chủ                                               |
| ------ | ------- | ------------------------------------------------- |
| <việc> | <lý do> | <spec, area hay context chịu; đợt sau; không làm> |

## Dữ liệu

<!-- TUY CHON: bảng, cột, ràng buộc, chỉ mục và RLS khi spec tạo hay đổi dữ liệu -->

## API

<!-- TUY CHON: route, scope, mã lỗi và details.reason_code khi spec mở route -->

## Màn hình

<!-- TUY CHON: trang, trạng thái và ai thấy gì khi spec có giao diện -->

## Kiểm soát

| #     | Kiểm soát           | Yêu cầu | Test âm                                      |
| ----- | ------------------- | ------- | -------------------------------------------- |
| <XX1> | <một câu kiểm soát> | R1.2    | <gọi gì, khẳng định gì; đỏ khi gỡ kiểm soát> |

## Tiêu chí thành công

<!-- TUY CHON: kết quả đo được phía người dùng, ghi KQ nào của area nó góp vào -->

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- <lệnh kiểm chạy được, ví dụ `make ci` xanh>.

## Phụ thuộc

- <seam nền tảng, Protocol do bên dùng khai, mã của spec khác> mà spec này được phép dựa vào.
- Kiểm lại khi: <đổi hình hợp đồng, đổi chủ dữ liệu hoặc đổi chiều phụ thuộc> → <spec, ticket>.

## Câu hỏi còn mở

<!-- CO THE RONG -->

- Q1. <câu hỏi>? Chủ: <ai>. Chặn: <mã, ticket>.

## Quyết định

<!-- CO THE RONG -->

- <d/m/yyyy> (<ai>): <quyết định>. Hỏi: Q<n>. Sửa: <mục hoặc mã>.

## Danh sách ticket

<!-- CO THE RONG -->

| #   | Ticket                           |
| --- | -------------------------------- |
| 01  | [<Tiêu đề>](issues/01-<slug>.md) |
```
