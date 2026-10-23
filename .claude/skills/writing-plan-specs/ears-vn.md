# EARS-VN: how a criterion is written

A criterion is one sentence a test can prove false. EARS (Mavin, Wilkinson, Harwood and Novak,
IEEE RE 2009) gives a handful of sentence shapes for that; EARS-VN is those shapes with Vietnamese
keywords written in capitals, plus one shape for behaviour that must survive a change.

It is a clarity device, linted mechanically by `scripts/check_plans.py`. Nothing measured says it
makes an agent build better, so never present it as more than that: its job is that every line
has one subject, one trigger and one outcome a test can fail on.

It applies to three kinds of line and nothing else:

- `R<n>.<m>` criteria and `G<n>` lines in a spec (`spec-template.md`);
- `YC<n>` lines in an area's `requirements.md` (`requirements-template.md`).

The keyword list and the vague-word list at the end of this file are the only copies of those
lists. The script parses both blocks, so change a list there and nowhere else.

---

## The shapes, and the test each one implies

| Shape      | Keyword            | Form                                                                        | Test it implies                                                                                                                               |
| ---------- | ------------------ | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Ubiquitous | none               | `<chủ thể> PHẢI <phản hồi>.`                                                | A property test that asks the running system for every instance, the shape of `test_rls_coverage.py`, not one example                         |
| Event      | `KHI`              | `KHI <sự kiện>, <chủ thể> PHẢI <phản hồi>.`                                 | One example test per trigger                                                                                                                  |
| State      | `TRONG KHI`        | `TRONG KHI <trạng thái>, <chủ thể> PHẢI <phản hồi>.`                        | A test inside the state, and one for its complement outside it                                                                                |
| Unwanted   | `NẾU ... THÌ`      | `NẾU <điều kiện xấu>, THÌ <chủ thể> PHẢI <từ chối cụ thể> và không đổi gì.` | A negative test asserting the exact refusal and that nothing changed; a "Kiểm soát" row when it guards a never-default topic                  |
| Optional   | `ĐỐI VỚI`          | `ĐỐI VỚI <biến thể>, <chủ thể> PHẢI <phản hồi>.`                            | A test with the variant and one without; an overlay variant also asserts the fallback to the platform layer, never sideways to another tenant |
| Complex    | `TRONG KHI`, `KHI` | `TRONG KHI <trạng thái>, KHI <sự kiện>, <chủ thể> PHẢI <phản hồi>.`         | One test per combination; past three preconditions, write a decision table instead (below)                                                    |
| Unchanged  | `PHẢI TIẾP TỤC`    | `KHI <điều kiện>, <chủ thể> PHẢI TIẾP TỤC <hành vi hiện có>.`               | A regression test that is green before the change and stays green after it; the `G<n>` line names it                                          |

An Unwanted line can sit inside a State or Event line, as in
`TRONG KHI <trạng thái>, NẾU <điều kiện xấu>, THÌ <chủ thể> PHẢI ...`; every `NẾU` still needs its
`THÌ`.

## Rules that go with the shapes

**One response per criterion.** Exactly one modal per line. "Refuse and change nothing" is one
outcome, so `PHẢI trả 403 và không đổi membership nào` is one response; "create the row and send
the email" is two criteria.

**Modality.** The modal is written in capitals so it can be counted:

- `PHẢI`: mandatory. This is nearly every line.
- `NÊN`: recommended, and the same sentence names its exception ("..., trừ khi <ngoại lệ>"). A
  `NÊN` with no exception is a `PHẢI` that has not been decided; decide it.
- `CÓ THỂ`: permitted, not required. Use it to make an allowance explicit, never to soften a rule.
- Never "cần", "được" or a lowercase "nên" as the modal. A lowercase "phải" is ordinary text, as in
  "không phải Platform Admin", and the lint ignores it.
- `PHẢI TIẾP TỤC` belongs to `G<n>` lines only, and every `G<n>` line uses it.

**Subject.** Name the narrowest real actor, right before the modal: "API quản trị", "lane
`partitions`", "trang `/admin`", "runner", "knowledge gateway". Never "hệ thống": a sentence whose
subject is the whole system cannot say which component a test should call.

**Numbers.** Give the unit, the scope (per tenant, per workspace, per run), the time zone (UTC or
Asia/Ho_Chi_Minh) and the behaviour exactly at the limit: "120 ký tự thì nhận, 121 thì 422".

**Contracts, not mechanisms.** A criterion may name what a caller can observe: a route, a scope,
an HTTP status, an event type, a `details.reason_code`, an audit event name, a field. It never
names a mechanism: a class, a function, SQL, a library, a file path. Mechanisms belong in tickets
or ADRs, where changing them does not change the requirement. When the mechanism is itself the
contract (the policy shape `CLAUDE.md` mandates for workspace-narrowed tables), cite the rule
rather than restating it.

**Decision tables.** When one requirement turns on more than three conditions, write a table
under the requirement instead of a sentence. Its first column is the criterion ID, so every row
is a criterion with its own `R<n>.<m>`; the remaining columns are the conditions and the outcome.
The script counts the rows as criteria for IDs and coverage, and does not lint them as sentences.

## Delta marks: what changes against "Hiện trạng"

A spec on existing code says what it changes, measured against the behaviour its "Hiện trạng"
section cites. The mark goes at the end of the requirement's heading and applies to every
criterion under it:

- `[Sửa]`: the behaviour changes. The criteria give the full new behaviour, and the line under
  the heading reads ``Trước đây: <hành vi cũ> (`<path>:<line>`).``
- `[Bỏ]`: the behaviour goes away. Under the heading: `Lý do: <...>.` and
  `Chuyển đổi: <điều xảy ra với dữ liệu và người gọi hiện có>.` At least one criterion asserts the
  old behaviour is gone, and its test looks for the behaviour "Hiện trạng" describes, never only
  for its name: a removal checked by name passes while the behaviour lives on under another one.
- `[Đổi tên]`: only the name changes. Under the heading: `Từ: <tên cũ>.` and
  `Thành: <tên mới>.`

Behaviour the change must not break gets a `G<n>` line in "Hành vi giữ nguyên", each with the
regression test that proves it: ``(test: `<tên test>`)``.

## Withdrawn IDs

An ID is never renumbered or reused once anything cites it. To withdraw a criterion, keep its
line and replace its sentence: `- R2.5 [Bỏ] <d/m/yyyy>: <lý do>.` The same form withdraws a
`G<n>` or a `YC<n>`. A withdrawn line needs no ticket and is not linted.

The two uses of `[Bỏ]` do not collide because of where they sit: on a requirement heading it is
a requirement to remove existing behaviour, whose criteria need tickets like any other; right
after a line's ID it withdraws that line from the document.

## Worked example

Goal 2 of `.claude/plans/platform-runtime/tenant-members-and-invitations/spec.md` (lines 33-34)
is one line:

> 2. `PUT /admin/members/{user_id}/memberships`: thay vai không quản trị ở nhiều workspace trong
>    một giao dịch; vai quản trị giữ nguyên.

In EARS-VN it becomes four criteria:

```markdown
### R2 — Sửa vai ở nhiều workspace trong một lần lưu

Quản trị viên tổ chức đổi vai của một người ở nhiều workspace mà không làm mất vai quản trị nào.

- R2.1 KHI quản trị viên tổ chức gửi `PUT /admin/members/{user_id}/memberships`, API quản trị
  PHẢI thay vai không quản trị của người đó ở mọi workspace có trong body, trong một giao dịch.
- R2.2 KHI body không nhắc một workspace nơi người đó đang giữ vai quản trị, API quản trị PHẢI
  giữ nguyên vai quản trị đó.
- R2.3 NẾU body có vai quản trị và người gọi không phải Platform Admin, THÌ API quản trị PHẢI
  trả 403 và không đổi membership nào.
- R2.4 NẾU body có workspace của tenant khác, THÌ API quản trị PHẢI trả 404 và không đổi
  membership nào.
```

with the controls naming what they guard:

| #   | Kiểm soát                                        | Yêu cầu    | Test âm                                                                 |
| --- | ------------------------------------------------ | ---------- | ----------------------------------------------------------------------- |
| TM1 | Sửa vai giữ vai quản trị; không cấp vai quản trị | R2.2, R2.3 | `PUT` có `org_admin` do `org_admin` gọi → 403, không membership nào đổi |
| TM2 | Chỉ người của tenant mình                        | R2.4       | `PUT` với `workspace_id` của tenant B → 404, không membership nào đổi   |

R2.3 and R2.4 are the spec's own TM1 and TM2. R2.1 and R2.2 were spelled out only later, in step
2 of the spec's ticket 01 (`issues/01-tenant-members-and-invitations.md`, lines 22-34). Writing
them as criteria moves that discovery into the spec, where a wrong answer costs a sentence instead
of a rework.

The same spec's goal 4 changes existing behaviour, so it carries a delta mark, and the scoping
the directory already had becomes a `G` line (illustrative: the spec had none; the anchor is the
one its "Hiện trạng" stamped on 3/10/2026):

```markdown
### R4 — Directory trả trạng thái của từng người [Sửa]

Trước đây: `GET /directory/members` trả người của workspace hiện tại, không có `status`
(`apps/api/src/dw_api/routes/v1/directory.py:38`).

- R4.1 KHI người có `directory.read` gọi `GET /directory/members`, API directory PHẢI trả
  `status` của mỗi người, bằng đúng giá trị `GET /admin/members` trả cho người đó.

## Hành vi giữ nguyên

- G1 KHI người có `directory.read` gọi `GET /directory/members`, API directory PHẢI TIẾP TỤC chỉ
  trả người của workspace hiện tại (test: `<tên test hồi quy>`).
```

R4.1 states the one-owner rule as something a test can observe: the two routes agree for every
person, so a second way of computing `status` fails it.

---

## Keyword list (read by `scripts/check_plans.py`)

One keyword per line, as `<role> <keyword>`: the role is the first word, the keyword is the rest
of the line. Blank lines and lines starting with `#` are ignored. Roles:

- `pattern`: may open a criterion;
- `then`: must follow every `NẾU` in the same line;
- `modal`: counts as the line's one modal;
- `keep`: the modal of a `G<n>` line, counted as its one modal, allowed nowhere else;
- `not-subject`: a word that must not stand right before the modal.

The lint (a warning, never a failure) runs on NFC text, outside backtick spans, matching
keywords case-sensitively as whole words and longest first, so `PHẢI TIẾP TỤC` counts once and
`TRONG KHI` is not also a `KHI`. A `not-subject` word matches in any case, so a sentence that opens
with `Hệ thống PHẢI` is caught like `hệ thống PHẢI`. A line passes when it opens with a `pattern` keyword or with none
(the Ubiquitous shape), every `NẾU` has its `THÌ`, it holds exactly one `modal` or `keep`, `keep`
appears only and always on `G<n>` lines, and no `not-subject` stands right before the modal.

```ears-keywords
pattern KHI
pattern TRONG KHI
pattern NẾU
pattern ĐỐI VỚI
then THÌ
modal PHẢI
modal NÊN
modal CÓ THỂ
keep PHẢI TIẾP TỤC
not-subject hệ thống
```

## Vague-word list (read by `scripts/check_plans.py`)

A hit on a criterion line is replaced by a number, an operation or a named control, or is
justified in the same sentence. One entry per line; blank lines and lines starting with `#` are
ignored. A line starting with `!` is an exception: a precise phrase that contains a listed word,
blanked out before the scan. Matching is case-insensitive, whole-word, longest entry first (so
"nhanh chóng" is one hit, not two), on NFC text, outside backtick spans, on `R<n>.<m>`, `G<n>` and
`YC<n>` lines only. A hit is a warning.

```vague-words
# Qualities with no measure: replace with a number, a tolerance or a named control
nhanh
nhanh chóng
kịp thời
ngay lập tức
hợp lý
phù hợp
thích hợp
linh hoạt
mạnh mẽ
ổn định
tin cậy
an toàn
bảo mật
thân thiện
dễ dùng
trực quan
tối ưu
hiệu quả
đầy đủ
chính xác
# Quantities with no count: replace with a count or a period
nhiều
ít
một số
đáng kể
thường xuyên
định kỳ
# Conditions with no name: name the condition or the case
khi cần
nếu cần
nếu có thể
tùy trường hợp
v.v.
vân vân
tương tự
sau này
# Verbs that hide the operation: name it (tạo, sửa, xóa, xem, duyệt, từ chối) and its outcome
hỗ trợ
xử lý
quản lý
# English equivalents
fast
robust
secure
scalable
user-friendly
appropriate
as needed
support
handle
gracefully
# Exceptions: precise phrases that contain a word above
!ít nhất
!nhiều nhất
!chính xác một
```
