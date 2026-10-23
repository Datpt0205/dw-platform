# Mẫu `requirements.md` và các mục của area file

Tệp này là chủ duy nhất của hai định dạng:

- `.claude/plans/<area>/requirements.md`, yêu cầu cấp cao của một area được lập kế hoạch trước khi
  có code (khối `markdown template`);
- các mục mà area file `.claude/plans/<area>.md` của area ấy có (khối `markdown area`): bốn mục
  bắt buộc và mục Ủy quyền tùy chọn.

`writing-plan-specs` (chế độ requirements) viết theo nó, `checking-plan-readiness` chạy reader test
trên nó, và `scripts/check_plans.py` đọc cả hai khối. Dòng đầu tệp, mã định danh và cách đọc khối
mẫu (mục tùy chọn, mục được để trống, `<...>` chưa điền) như ở `spec-template.md`; câu yêu cầu viết
theo `ears-vn.md`.

## Khác với spec

- Chỉ cái gì và vì sao. Không công nghệ: không framework, bảng, route, thư viện hay tên lớp. Cách
  làm thuộc spec và ADR. (Spec thì ngược lại: Hiện trạng có `path:line` và bảng Kiểm soát; đừng áp
  luật "không cách làm" lên spec.)
- Vấn đề nói trong không gian vấn đề: ai bị ảnh hưởng, đau ở đâu, khi nào, vì sao bây giờ, và cái
  giá của việc không làm. Một mong muốn viết dưới dạng giải pháp thì lần ngược về vấn đề của nó.
- Chủ thể của một `YC<n>` là vai người dùng hoặc bề mặt sản phẩm người dùng thấy được, không phải
  thành phần kỹ thuật.
- Dưới khoảng 200 dòng. Dài hơn thường là spec viết sớm.

## Dòng đầu tệp

Như spec, trừ dòng `Area:` không có phần `Nhánh`: `Area: <area> · Viết: <d/m/yyyy>`.
`Status: ready-for-agent` ở đây nghĩa là được viết spec từ nó; như spec, chỉ gate nâng lên, khi
`Sẵn sàng: ĐẠT` và có `Duyệt:`. `Duyệt:` của tài liệu này là của chính Đạt, trừ khi mục Ủy quyền của
area file có dòng ủy quyền cho loại tài liệu này (dưới đây).

## Từng mục

**Yêu cầu.** `- YC<n> <câu EARS-VN>`. Mã không bao giờ dùng lại; rút thì giữ dòng với `[Bỏ]`.

**Không làm.** Non-goal và anti-goal (một thất bại kể cả khi chạy được). Một `YC<n>` chưa làm bây
giờ ghi mã ở đầu dòng (`- YC5: <việc>; <vì sao>; đợt sau.`) và như vậy là đã phủ. Ứng viên bị dừng
cũng ghi ở đây.

**Kết quả đo được.** Mỗi `KQ<n>` một dòng bảng. `Hiện nay` là số đo hoặc `chưa biết`. `Đối trọng`
là chỉ số không được xấu đi khi đẩy kết quả này lên. `Cách đo` nói số lấy ở đâu; một KQ không có
cách đo là chưa xong.

**Bằng chứng** và **Bằng chứng ngược.** Mỗi dòng một điều quan sát được, với `Nguồn:` (đường dẫn,
link hoặc người) và `Tin cậy:` (`cao`, `vừa` hoặc `thấp`). Điều chưa có nguồn ghi `Nguồn: GIẢ ĐỊNH`.
Bằng chứng ngược là bắt buộc: không tìm thấy gì thì ghi đã tìm ở đâu.

**Phương án.** Hai hay ba phương án, luôn có `Nhỏ nhất làm được` và `Không làm gì`, mỗi phương án
một tiêu đề `###` với phác thảo, ngân sách thời gian (ngày, tuần hay tháng: mức chi chấp nhận, không
phải ước lượng), đánh đổi và chỗ dễ sa lầy. Cuối mục là một đề xuất, hoặc đề xuất không chọn gì.

**Câu hỏi hoài nghi.** Trả lời từng câu trong khối mẫu, kết thúc bằng `Kết luận: vững`, `chưa chắc`
hoặc `nứt`. "Chưa biết" là câu trả lời được nhận khi kèm cách biết và hạn; câu chưa xét thì không.

**Ràng buộc.** Link tới mục của `CLAUDE.md` hoặc ADR (kèm trạng thái), mỗi dòng nói vì sao nó bó
area này. Không chép lại nội dung.

**Câu hỏi còn mở** và **Quyết định.** Như spec. Kết luận cho từng ứng viên tính năng là một dòng
Quyết định có dạng cố định:
`- <d/m/yyyy> (<ai>): Ứng viên <tên>: <làm, cần làm rõ hoặc dừng>; bằng chứng <mạnh, đủ, yếu hoặc chưa biết>.`
`làm` cần bằng chứng `đủ` trở lên và thành một dòng Lộ trình; `cần làm rõ` thành một `Q<n>`; `dừng`
thành một dòng Không làm.

## Các mục của area file

Area lập kế hoạch trước code giữ bốn mục bắt buộc của khối `markdown area` trong
`.claude/plans/<area>.md`, bên cạnh trạng thái, nhật ký slice và quyết định như mọi area file:

- `## Lộ trình`: một dòng mỗi thư mục tính năng. Cột `Yêu cầu cấp area` là nơi duy nhất ghi YC nào
  được tính năng nào phục vụ; spec không chép lại. Không có cột Status: trạng thái nằm ở spec.
- `## ADR`: khối số dành riêng của area và bảng số, tên, tệp. Số được gán ở đây trước khi ai viết
  ADR; trạng thái nằm trong tệp ADR. Thư mục ADR theo `CONTEXT-MAP.md`.
- `## Tiếp theo`: một dòng mỗi spec, là link duy nhất từ area file tới thư mục tính năng (một link mỗi
  thư mục, không mỗi ticket). `requirements.md`, một ADR hay glossary đang được kiểm cũng có một dòng,
  gọi bằng tên tệp hoặc mã ADR. `writing-plan-specs` thêm dòng; `checking-plan-readiness` làm mới nó.
- `## Đợt`: dòng đầu là kết quả lần kiểm nhất quán gần nhất, thay mỗi lần chạy; dưới là các đợt.
  `checking-plan-consistency` làm mới nó.

Mục `## Ủy quyền` là tùy chọn, và mọi area file đều có thể có nó, kể cả area không có
`requirements.md`. Chỉ Đạt ghi vào đó, mỗi loại tài liệu một dòng cố định:
`- Ủy quyền duyệt: Đạt, <spec hoặc requirements>, từ <d/m/yyyy>`. Không có dòng ấy thì dạng
`Duyệt: agent, tạm theo ủy quyền <d/m/yyyy>` của spec hay `requirements.md` trong area là lỗi, và
ngày ở `Duyệt:` không được sớm hơn ngày `từ`. `scripts/check_plans.py` kiểm cả hai: một agent không
tự duyệt tài liệu của mình bằng một ủy quyền không ai ghi.

```markdown area
## Lộ trình

| Tính năng (thư mục) | Ý định    | Yêu cầu cấp area | Trong; để cho                 | Phụ thuộc        |
| ------------------- | --------- | ---------------- | ----------------------------- | ---------------- |
| `<feature-slug>`    | <một câu> | YC1, YC3         | <trong, hoặc để cho nơi khác> | `<feature-slug>` |

## ADR

Khối số dành riêng: <NNNN>-<NNNN>.

| Số     | Tên   | Tệp                              |
| ------ | ----- | -------------------------------- |
| <NNNN> | <tên> | `<thư mục adr>/<NNNN>-<slug>.md` |

## Tiếp theo

- [`<feature-slug>`](<area>/<feature-slug>/spec.md): <bước tiếp theo, một dòng> (<d/m/yyyy>).

## Đợt

Kiểm nhất quán <d/m/yyyy>: <n> CRITICAL, <n> HIGH, <n> MEDIUM, <n> LOW; phủ YC <x>/<y>, tiêu chí <x>/<y>.

- Đợt 1: `<feature-slug>`, `<feature-slug>`. <trạng thái, một dòng>.

## Ủy quyền

<!-- TUY CHON: chỉ Đạt ghi, khi Đạt ủy quyền agent duyệt một loại tài liệu -->

- Ủy quyền duyệt: Đạt, <spec hoặc requirements>, từ <d/m/yyyy>
```

## Khối mẫu

```markdown template
# Yêu cầu cấp cao: <tên area>

Status: needs-triage
Area: <area> · Viết: <d/m/yyyy>
Duyệt: chưa
Sẵn sàng: chưa kiểm

## Mục đích tài liệu

<Tài liệu này quyết định gì và không quyết định gì; ai đọc nó để làm gì.>

## Vấn đề

<Ai bị ảnh hưởng, đau ở đâu, khi nào, vì sao bây giờ.>

Cái giá của việc không làm: <điều xảy ra nếu ta không làm gì>.

## Người dùng

- <vai người dùng>: <hôm nay họ làm gì, vướng ở đâu>.

## Yêu cầu

- YC1 KHI <sự kiện>, <chủ thể> PHẢI <kết quả người dùng thấy được>.

## Không làm

- <việc>: <vì sao>.

## Kết quả đo được

| #   | Kết quả   | Đơn vị   | Hiện nay            | Đích   | Đối trọng                  | Cách đo        |
| --- | --------- | -------- | ------------------- | ------ | -------------------------- | -------------- |
| KQ1 | <kết quả> | <đơn vị> | <số hoặc chưa biết> | <đích> | <chỉ số không được xấu đi> | <lấy số ở đâu> |

## Bằng chứng

- <điều quan sát được>. Nguồn: <đường dẫn, link, người hoặc GIẢ ĐỊNH>. Tin cậy: <cao, vừa hoặc thấp>.

## Bằng chứng ngược

- <điều làm ý tưởng yếu đi>. Nguồn: <đường dẫn, link, người hoặc GIẢ ĐỊNH>. Tin cậy: <cao, vừa hoặc thấp>.

## Phương án

### A — Nhỏ nhất làm được

- Phác thảo: <một đoạn>.
- Ngân sách thời gian: <ngày, tuần hoặc tháng>.
- Đánh đổi: <được gì, mất gì>.
- Chỗ dễ sa lầy: <điều có thể nuốt hết ngân sách>.

### B — Không làm gì

- Phác thảo: <điều gì vẫn chạy như hôm nay>.
- Ngân sách thời gian: không.
- Đánh đổi: <được gì, mất gì>.
- Chỗ dễ sa lầy: <điều sẽ tệ đi nếu cứ để vậy>.

Đề xuất: <phương án nào, hoặc không chọn gì>, vì <lý do>.

## Câu hỏi hoài nghi

- Phần khó nhất về kỹ thuật là gì, và repo này đã làm thứ gì gần giống chưa? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Điều gì ta chưa biết cách làm, và phải tốn gì để biết? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Ta dựa vào thứ gì ngoài tầm tay (thư viện, nhà cung cấp, area khác), và nếu nó đổi thì sao? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Ai dùng nó trong tuần đầu, và điều gì khiến họ quay lại hay bỏ đi? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Xong rồi thì ai giữ nó chạy, và mỗi tháng tốn gì? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Làm cái này thì phải nói không với việc gì? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Điều gì giết area này; có dữ liệu cá nhân hay ràng buộc pháp lý nào? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Vì sao là bây giờ, và nó thay thế hay làm yếu thứ gì đang có? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.
- Câu nào ta ngại hỏi nhất ở đây, và câu trả lời thật là gì? <trả lời>. Kết luận: <vững, chưa chắc hoặc nứt>.

## Ràng buộc

- `CLAUDE.md`, mục "<tên mục>": <vì sao nó bó area này, một dòng>.

## Câu hỏi còn mở

<!-- CO THE RONG -->

- Q1. <câu hỏi>? Chủ: <ai>. Chặn: <mã>.

## Quyết định

<!-- CO THE RONG -->

- <d/m/yyyy> (<ai>): Ứng viên <tên>: <làm, cần làm rõ hoặc dừng>; bằng chứng <mạnh, đủ, yếu hoặc chưa biết>.
```
