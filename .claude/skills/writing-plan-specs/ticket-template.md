# Mẫu ticket

Tệp này là chủ duy nhất của định dạng ticket,
`.claude/plans/<area>/<feature-slug>/issues/NN-<slug>.md`. `/to-tickets` viết theo nó
(`docs/agents/issue-tracker.md` trỏ tới đây), `checking-plan-readiness` kiểm theo nó, và
`scripts/check_plans.py` đọc khối `markdown template` cuối tệp. Mã định danh theo khối `ids` của
`spec-template.md`; cách đọc khối mẫu (mục tùy chọn, mục được để trống, `<...>` chưa điền) như ở
đó.

Mẫu này là ticket hiện có của repo thêm một dòng `Yêu cầu:`. Ticket của bản đồ wayfinder (trong thư
mục có `map.md` mà không có `spec.md`, như `discovery/`) không theo mẫu này mà theo mục Wayfinding
của `docs/agents/issue-tracker.md`.

Một thư mục tính năng có thể chỉ có `issues/`, không có `spec.md`: đó là việc cỡ A của
`writing-plan-specs`, gói trong một câu. Ticket ở đó theo đúng mẫu này và mọi quy tắc của nó, trừ
hai chỗ: dòng `Yêu cầu:` là `không (<lý do>)`, vì không có spec để dẫn mã, và điều kiện
`ready-for-agent` ở mục Comments thay cho điều kiện về spec.

## Tên tệp và tiêu đề

- Tên tệp `issues/NN-<slug>.md`: `NN` hai chữ số, đếm từ `01` trong mỗi thư mục, không trùng;
  `<slug>` gồm chữ thường, số và gạch nối.
- Tiêu đề `# NN — <Tiêu đề>` (gạch dài), `NN` trùng tên tệp.

## Dòng đầu tệp

Ngay dưới tiêu đề, theo thứ tự này:

| Dòng          | Giá trị cho phép                                                                                                                             | Ai ghi                                                                                                                             |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `Status:`     | một nhãn trong `docs/agents/triage-labels.md`                                                                                                | `/to-tickets`: `needs-triage`; gate: `ready-for-agent`; người đóng việc: `resolved (<yyyy-mm-dd>, <nhánh>)` như các ticket hiện có |
| `Blocked by:` | các mục cách nhau dấu phẩy, mỗi mục là `NN` (ticket cùng thư mục) hoặc đường dẫn từ gốc repo tới tệp ticket; bỏ hẳn dòng khi không gì chặn   | `/to-tickets`                                                                                                                      |
| `Area:`       | tên thư mục area                                                                                                                             | `/to-tickets`                                                                                                                      |
| `Yêu cầu:`    | mã `R<n>.<m>`, `G<n>` hoặc mã kiểm soát của spec cùng thư mục, cách nhau dấu phẩy; hoặc `không (<lý do>)` cho ticket không chứng minh mã nào | `/to-tickets`                                                                                                                      |

Quy tắc đi kèm:

- Một ticket chỉ bị chặn bởi ticket số nhỏ hơn trong cùng thư mục: phụ thuộc chỉ trỏ ngược. Mọi
  ticket được trỏ tới phải tồn tại, không tạo vòng, và không ở `wontfix`.
- Ticket được `ready-for-agent` chỉ khi spec cùng thư mục có `Sẵn sàng: ĐẠT` với phần `ticket` gồm số
  của nó, có `Duyệt:` của Đạt hoặc theo ủy quyền đã ghi (`spec-template.md`), và có dòng Quyết
  định `Duyệt cách chia ticket` gồm số của nó. Thư mục không có spec thì xem mục Comments.
- Hai ticket không có đường phụ thuộc nào nối nhau thì không chạm chung tài nguyên nào sau đây:
  bảng, route, migration, config hay prompt. Phần dựng chung nằm ở ticket sớm nhất. Danh sách tài
  nguyên này chỉ ghi ở đây; các skill khác trỏ tới nó.

## Từng mục

**Mục tiêu.** Một đoạn: lát này cho ai được gì, trỏ tới mã của spec. Không chép lại spec.

**Việc cần làm.** Ticket phải làm được mà không đọc chat: nêu đường dẫn, route, bảng, scope và
lệnh. Ràng buộc dữ liệu (độ dài, enum, unique, null, collation) chép nguyên văn từ spec. Chữ hoãn
việc ("tạm thời", "placeholder", "đơn giản hóa" hay "nối sau"; danh sách chỉ ghi ở đây) nghĩa là
còn một ticket thứ hai: tách ra, không thu nhỏ ticket này.

**Tiêu chí chấp nhận.** Mỗi dòng là một ô `- [ ]` bắt đầu bằng mã nó chứng minh, rồi điều quan sát
được và điều gì sẽ làm nó sai. Khi dòng đó là test âm của một kiểm soát, mã kiểm soát đứng trong
ngoặc ngay sau mã tiêu chí: `- [ ] R1.2 (TM1): ...`. Quy tắc:

- mỗi mã ở dòng `Yêu cầu:` có ít nhất một tiêu chí chấp nhận, và mỗi tiêu chí chấp nhận dùng mã có ở
  dòng đó; ticket `Yêu cầu: không (...)` không có mã để dẫn đầu, nên chỉ quy tắc dòng `Xong:` áp
  cho nó;
- ticket cài một kiểm soát thì mang test âm của kiểm soát đó, và test ấy phải đỏ khi gỡ kiểm soát;
- một tiêu chí đã đúng sẵn ở commit gốc, chỉ ticket khác làm cho đúng được, hoặc chỉ nhắc lại yêu cầu
  thì không phải tiêu chí;
- dòng cuối là đúng một lệnh kiểm chạy được: `- [ ] Xong: <lệnh> xanh.`;
- không tick ô lúc viết; ô được tick khi test đã chạy và đã thấy kết quả.

**Nguồn.** Neo `<đường dẫn từ gốc repo>:<dòng>` như Hiện trạng của spec, mỗi neo một code span, và
mã của spec mà ticket dựa vào.

**Comments.** Nhật ký chỉ thêm, mỗi dòng `- <yyyy-mm-dd> (<ai>): <nội dung>` như các ticket hiện có.
Gate thêm một dòng khi nâng ticket lên `ready-for-agent`:
`- <yyyy-mm-dd> (agent): checking-plan-readiness ĐẠT; ready-for-agent.` Ticket không có spec chỉ
được `ready-for-agent` khi Comments có cả dòng đó lẫn dòng Đạt duyệt chính ticket:
`- <yyyy-mm-dd> (Đạt): Duyệt ticket.` Điều phát hiện lúc build ghi ở đây dưới
dạng đề xuất (`Đề xuất đổi R2.1: ...`); nó được sửa ở nguồn qua `writing-plan-specs` sau khi Đạt
đồng ý, không sửa thẳng trong ticket.

## Khối mẫu

```markdown template
# NN — <Tiêu đề>

Status: needs-triage
Blocked by: <NN, NN hoặc đường dẫn tới ticket>
Area: <area>
Yêu cầu: <các mã như R1.1, R1.2, TM1; hoặc không (lý do)>

## Mục tiêu

<Một đoạn: lát này cho ai được gì, trỏ tới mã của spec.>

## Việc cần làm

1. <bước, với đường dẫn, route, bảng, scope hoặc lệnh>.

## Tiêu chí chấp nhận

- [ ] R1.2 (TM1): <điều quan sát được; điều gì sẽ làm nó sai>.
- [ ] Xong: `<lệnh>` xanh.

## Nguồn

- `<path>:<line>`; spec: <mã>.

## Comments

<!-- CO THE RONG -->
```
