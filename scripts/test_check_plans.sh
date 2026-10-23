#!/usr/bin/env bash
# Tests for scripts/check_plans.py, the mechanical half of the planning skills.
#
#   bash scripts/test_check_plans.sh [OWNER_ROOT]     (also: make test-plans)
#
# Every case runs the checker against a throwaway plan tree, never this checkout:
# one clean tree that must pass every check, then one planted defect per rule,
# each of which must be reported by that rule's check id and, where the fixture
# allows, be the only finding. A case that cannot plant its defect fails loudly
# instead of passing (failure-modes.md #3).
#
# The owner files (templates, ears-vn.md, docs/agents/*) are read from
# OWNER_ROOT, by default the checkout this script sits in. The emoji ranges come
# from scripts/check_hygiene.py under it; set CHECK_HYGIENE to point elsewhere
# when running from a copy that does not carry that file.
set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
owners=${1:-$here}
script="$here/scripts/check_plans.py"
hygiene=${CHECK_HYGIENE:-$owners/scripts/check_hygiene.py}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if command -v python3 >/dev/null 2>&1 && python3 -c '' >/dev/null 2>&1; then py=python3; else py=python; fi
if [ ! -f "$hygiene" ]; then
  echo "check_hygiene.py not found at $hygiene; set CHECK_HYGIENE to its path"
  exit 2
fi

passed=0
failed=0
check() { # description expected actual
  if [ "$2" = "$3" ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "FAIL: $1 (expected $2, got $3)"
  fi
}

plans() { # fixture [args...] -> exit code; output in $work/out
  local dir=$1
  shift
  "$py" -I "$script" --owners "$owners" --repo "$dir" --hygiene "$hygiene" "$@" >"$work/out" 2>&1
  echo $?
}

reported() { # check-id -> yes when that check failed and printed a finding under its id
  if grep -qE "^Không đạt +$1( |:|$)" "$work/out" && grep -qF "[$1]" "$work/out"; then
    echo yes
  else
    echo no
  fi
}

edit() { # file old new: replace the first occurrence; a missing one is a failed case
  if ! "$py" -I - "$@" <<'PY'; then
import pathlib, sys
path, old, new = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_bytes().decode("utf-8")
if old not in text:
    sys.exit(f"mutation target not found in {path.name}: {old!r}")
path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
PY
    failed=$((failed + 1))
    echo "FAIL: could not plant the defect in $1"
  fi
}

# --- the clean tree ------------------------------------------------------------

clean="$work/clean"
p="$clean/.claude/plans"
f="$p/demo/alpha"
mkdir -p "$f/issues" "$p/demo/discovery/issues" "$clean/docs/adr" "$clean/docs/platform" "$clean/src"

printf 'import os\n\n\ndef members():\n    return []\n' >"$clean/src/app.py"

cat >"$clean/CONTEXT-MAP.md" <<'EOF'
# Context map

| Context  | What it covers | Glossary                   | Decisions   |
| -------- | -------------- | -------------------------- | ----------- |
| Platform | Everything     | `docs/platform/CONTEXT.md` | `docs/adr/` |
EOF

cat >"$clean/docs/platform/CONTEXT.md" <<'EOF'
# Platform

**Thành viên** (`member`): người có membership trong một workspace. _Tránh_: user.
EOF

cat >"$clean/docs/adr/0100-filter-by-workspace.md" <<'EOF'
---
status: Proposed
date: 2026-10-01
source: []
---

# 0100. Filter members by workspace

The member list is filtered by the caller's workspace.
EOF

cat >"$p/demo.md" <<'EOF'
# demo

Trạng thái: đang lập kế hoạch.

## Lộ trình

| Tính năng (thư mục) | Ý định                        | Yêu cầu cấp area | Trong; để cho | Phụ thuộc |
| ------------------- | ----------------------------- | ---------------- | ------------- | --------- |
| `alpha`             | Lọc thành viên theo workspace | YC1              | trong         | không     |

## ADR

Khối số dành riêng: 0100-0109.

| Số   | Tên                 | Tệp                                    |
| ---- | ------------------- | -------------------------------------- |
| 0100 | Filter by workspace | `docs/adr/0100-filter-by-workspace.md` |

## Tiếp theo

- [`alpha`](demo/alpha/spec.md): làm ticket 01 (2/10/2026).

## Đợt

Kiểm nhất quán 2/10/2026: 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW; phủ YC 1/1, tiêu chí 2/2.

- Đợt 1: `alpha`. Đang làm.
EOF

cat >"$p/demo/requirements.md" <<'EOF'
# Yêu cầu cấp cao: demo

Status: needs-triage
Area: demo · Viết: 1/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

## Mục đích tài liệu

Quyết định quản trị viên thấy ai trong danh sách thành viên.

## Vấn đề

Quản trị viên thấy người của workspace khác.

Cái giá của việc không làm: lộ danh sách người giữa các workspace.

## Người dùng

- quản trị viên workspace: mở danh sách thành viên mỗi tuần.

## Yêu cầu

- YC1 KHI quản trị viên mở trang thành viên, trang thành viên PHẢI chỉ hiện người của workspace hiện tại.
- YC2 KHI quản trị viên bấm xuất, trang thành viên PHẢI tải tệp CSV.

## Không làm

- YC2: xuất CSV; chưa ai yêu cầu; đợt sau.

## Kết quả đo được

| #   | Kết quả      | Đơn vị    | Hiện nay  | Đích | Đối trọng           | Cách đo       |
| --- | ------------ | --------- | --------- | ---- | ------------------- | ------------- |
| KQ1 | Lần lộ người | lần/tháng | chưa biết | 0    | thời gian tải trang | nhật ký audit |

## Bằng chứng

- Khách báo thấy người lạ. Nguồn: GIẢ ĐỊNH. Tin cậy: thấp.

## Bằng chứng ngược

- Chưa thấy báo cáo nào trong nhật ký. Nguồn: GIẢ ĐỊNH. Tin cậy: thấp.

## Phương án

### A — Nhỏ nhất làm được

- Phác thảo: lọc ở route.
- Ngân sách thời gian: hai ngày.
- Đánh đổi: rẻ; chưa có trang riêng.
- Chỗ dễ sa lầy: không.

Đề xuất: A, vì rẻ nhất.

## Câu hỏi hoài nghi

- Phần khó nhất là gì? Lọc đúng workspace. Kết luận: vững.

## Ràng buộc

- `CLAUDE.md`, mục "Tenancy and authorization": dữ liệu theo workspace.

## Câu hỏi còn mở

## Quyết định
EOF

cat >"$f/spec.md" <<'EOF'
# Danh sách thành viên theo workspace

Status: ready-for-agent
Area: demo · Nhánh: `main` · Viết: 1/10/2026
Duyệt: Đạt 2/10/2026
Sẵn sàng: ĐẠT (2/10/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)

Quản trị viên chỉ cần thấy thành viên của workspace mình; hôm nay route trả cả tenant.

## Hiện trạng (đã kiểm ở `abc1234` ngày 1/10/2026)

- Route danh sách trả mọi người của tenant (`src/app.py:3`). Thiếu: chưa lọc theo workspace.

## Mục tiêu

### R1 — Danh sách theo workspace

Quản trị viên thấy người của workspace hiện tại.

- R1.1 KHI quản trị viên gọi `GET /members`, API thành viên PHẢI trả người của workspace hiện tại.
- R1.2 NẾU người gọi thuộc tenant khác, THÌ API thành viên PHẢI trả 404 và không đổi gì.

## Hành vi giữ nguyên

- G1 KHI người gọi có scope `members.read`, API thành viên PHẢI TIẾP TỤC trả 200
  (test: `test_members_ok`).

## Trong phạm vi

- Route `GET /members`.

## Ngoài phạm vi

| Việc     | Vì sao          | Chủ     |
| -------- | --------------- | ------- |
| Xuất CSV | chưa ai yêu cầu | đợt sau |

## Kiểm soát

| #   | Kiểm soát                 | Yêu cầu | Test âm                          |
| --- | ------------------------- | ------- | -------------------------------- |
| AL1 | Chỉ người của tenant mình | R1.2    | gọi với tenant B, khẳng định 404 |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make test` xanh.

## Phụ thuộc

- ADR-0100 (Proposed): lọc theo workspace ở repository.
- Kiểm lại khi: đổi hình `AccessContext` thì kiểm lại ticket 01.

## Câu hỏi còn mở

## Quyết định

- 2/10/2026 (Đạt): Duyệt cách chia ticket 01-02.

## Danh sách ticket

| #   | Ticket                                    |
| --- | ----------------------------------------- |
| 01  | [Lọc theo workspace](issues/01-filter.md) |
| 02  | [Chặn tenant khác](issues/02-tenant.md)   |
EOF

cat >"$f/issues/01-filter.md" <<'EOF'
# 01 — Lọc theo workspace

Status: ready-for-agent
Area: demo
Yêu cầu: R1.1, G1

## Mục tiêu

Quản trị viên chỉ thấy người của workspace mình (R1.1) và giữ quyền đọc đang có (G1).

## Việc cần làm

1. Lọc theo workspace trong route `GET /members` (`src/app.py`).

## Tiêu chí chấp nhận

- [ ] R1.1: trả người của workspace hiện tại; sai nếu thấy người của workspace khác.
- [ ] G1: scope `members.read` vẫn nhận 200; sai nếu nhận 403.
- [ ] Xong: `make test` xanh.

## Nguồn

- `src/app.py:3`; spec: R1.1.

## Comments
EOF

cat >"$f/issues/02-tenant.md" <<'EOF'
# 02 — Chặn tenant khác

Status: needs-triage
Blocked by: 01
Area: demo
Yêu cầu: R1.2, AL1

## Mục tiêu

Người của tenant khác nhận 404 (R1.2, AL1).

## Việc cần làm

1. Thêm test tenant B cho route `GET /members`.

## Tiêu chí chấp nhận

- [ ] R1.2 (AL1): tenant B nhận 404 và không đổi gì; sai nếu nhận 200.
- [ ] Xong: `make test` xanh.

## Nguồn

- `src/app.py:1-3`; spec: R1.2.

## Comments
EOF

cat >"$p/demo/discovery/map.md" <<'EOF'
# Bản đồ demo

## Decisions so far

- Quản trị viên workspace là người dùng chính ([01](issues/01-who-uses-it.md)).
EOF

cat >"$p/demo/discovery/issues/01-who-uses-it.md" <<'EOF'
# 01 — Ai mở danh sách thành viên

Type: research
Status: resolved

## Answer

Quản trị viên workspace.
EOF

# A ticket with no spec (tier A): its folder holds only issues/, and every ticket
# check runs on it (issue-tracker.md, ticket-template.md).
mkdir -p "$p/demo/gamma/issues"
cat >"$p/demo/gamma/issues/01-export-label.md" <<'TICKET'
# 01 — Sửa nhãn nút xuất

Status: ready-for-agent
Area: demo
Yêu cầu: không (việc cỡ A, không có spec)

## Mục tiêu

Quản trị viên đọc đúng nhãn trên nút xuất.

## Việc cần làm

1. Đổi nhãn trong `src/app.py`.

## Tiêu chí chấp nhận

- [ ] Xong: `make test` xanh.

## Nguồn

- `src/app.py:1`.

## Comments

- 2026-10-02 (Đạt): Duyệt ticket.
- 2026-10-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
TICKET

check "clean tree: exits 0" 0 "$(plans "$clean")"
check "clean tree: no check fails" no "$(grep -qE '^Không đạt' "$work/out" && echo yes || echo no)"
check "clean tree: no check is left unrun" no "$(grep -qE '^Chưa kiểm' "$work/out" && echo yes || echo no)"

# --- one planted defect per rule -----------------------------------------------
#
# Each rule the script enforces has a fixture built so that, within its check, no
# other rule fires: deleting the rule then turns its case red, which a case that
# shared its check id with another rule could not show. `only` also asserts that
# the planted defect is the single finding of the whole run, wherever the fixture
# allows it; `red` is used where a defect necessarily trips a second check.

fixture() { # -> a fresh copy of the clean tree (runs in a subshell, so no counter)
  local dir
  dir=$(mktemp -d "$work/case.XXXXXX")
  cp -r "$clean/." "$dir"
  echo "$dir"
}

red() { # description check-id fixture -> asserts exit 1 and the finding under that id
  local code
  code=$(plans "$3")
  check "$1: exits 1" 1 "$code"
  check "$1: reported by [$2]" yes "$(reported "$2")"
}

only() { # description check-id fixture -> red, and that finding is the only one
  red "$1" "$2" "$3"
  check "$1: the only finding" 1 "$(grep -cE '^  .* \[[a-z-]+\] ' "$work/out")"
}

warned() { # description check-id fixture -> a warning check: exit 0, finding reported
  local code
  code=$(plans "$3")
  check "$1: exits 0" 0 "$code"
  check "$1: reported by [$2]" yes "$(reported "$2")"
}

quiet() { # description check-id fixture -> exit 0 and nothing reported by that id
  local code
  code=$(plans "$3")
  check "$1: exits 0" 0 "$code"
  check "$1: not reported by [$2]" no "$(reported "$2")"
}

S=.claude/plans/demo/alpha/spec.md
T1=.claude/plans/demo/alpha/issues/01-filter.md
T2=.claude/plans/demo/alpha/issues/02-tenant.md
G1=.claude/plans/demo/gamma/issues/01-export-label.md
R=.claude/plans/demo/requirements.md
A=.claude/plans/demo.md
W=.claude/plans/demo/discovery/issues/01-who-uses-it.md
R12=$'- R1.2 NẾU người gọi thuộc tenant khác, THÌ API thành viên PHẢI trả 404 và không đổi gì.\n'
XONG=$'- [ ] Xong: `make test` xanh.\n'
G1BOX=$'- [ ] G1: scope `members.read` vẫn nhận 200; sai nếu nhận 403.\n'
CONTROLS=$'| #   | Kiểm soát                 | Yêu cầu | Test âm                          |\n| --- | ------------------------- | ------- | -------------------------------- |\n| AL1 | Chỉ người của tenant mình | R1.2    | gọi với tenant B, khẳng định 404 |\n'
DONE=$'## Tiêu chí xong\n\n- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.\n- `make test` xanh.\n\n'
DEPENDS=$'## Phụ thuộc\n\n- ADR-0100 (Proposed): lọc theo workspace ở repository.\n- Kiểm lại khi: đổi hình `AccessContext` thì kiểm lại ticket 01.\n\n'

# status
d=$(fixture); edit "$d/$S" "Status: ready-for-agent" "Status: in-progress"
only "a Status outside triage-labels.md" status "$d"

# headers
d=$(fixture); edit "$d/$T1" "# 01 — " "# 1 - "
only "a ticket title without its number" headers "$d"

d=$(fixture); edit "$d/$R" $'Status: needs-triage\nArea: demo · Viết: 1/10/2026' $'Area: demo · Viết: 1/10/2026\nStatus: needs-triage'
only "header lines out of order" headers "$d"

d=$(fixture); edit "$d/$R" $'Duyệt: chưa\n' ""
only "a required header line missing" headers "$d"

d=$(fixture); edit "$d/$R" "Duyệt: chưa" "Duyệt: ok"
only "a Duyệt value outside its grammar" headers "$d"

d=$(fixture); edit "$d/$T2" "Area: demo" "Area: other"
only "a ticket Area that is not its folder" headers "$d"

d=$(fixture); edit "$d/$W" "Type: research" "Type: banana"
only "a wayfinder ticket with an unknown Type" headers "$d"

d=$(fixture); edit "$d/$W" $'Status: resolved\n' ""
only "a wayfinder ticket with no Status" headers "$d"

# headers and ready: a delegated approval needs Đạt's line in the area file
delegate() { # fixture kind date -> the area file records Đạt's delegation
  printf '\n## Ủy quyền\n\n- Ủy quyền duyệt: Đạt, %s, từ %s\n' "$2" "$3" >>"$1/$A"
}
d=$(fixture); edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: agent, tạm theo ủy quyền 2/10/2026"
delegate "$d" spec 1/10/2026
check "a delegated Duyệt with Đạt's line in the area file passes" 0 "$(plans "$d")"

d=$(fixture); edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: agent, tạm theo ủy quyền 2/10/2026"
red "a delegated Duyệt with no delegation recorded" headers "$d"
check "a delegated Duyệt with no delegation recorded: refused by [ready] too" yes "$(reported ready)"

d=$(fixture); edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: agent, tạm theo ủy quyền 2/10/2026"
delegate "$d" spec 3/10/2026
red "a delegated Duyệt dated before the delegation" headers "$d"

d=$(fixture); edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: agent, tạm theo ủy quyền 2/10/2026"
delegate "$d" requirements 1/10/2026
red "a delegated Duyệt for another kind of document" headers "$d"

# sections
d=$(fixture); edit "$d/$S" $'- Route `GET /members`.\n' $'- Route `GET /members`.\n\n## Trong phạm vi\n\n- Màn hình thành viên.\n'
only "a section written twice" sections "$d"

d=$(fixture); printf '\n## Ghi chú\n\nMột dòng.\n' >>"$d/$S"
only "a spec with a section the template does not have" sections "$d"

d=$(fixture); edit "$d/$S" "$DONE$DEPENDS" "$DEPENDS$DONE"
only "sections out of the template's order" sections "$d"

d=$(fixture); edit "$d/$S" $'## Trong phạm vi\n' ""
red "a spec missing a required section" sections "$d"

d=$(fixture); edit "$d/$A" $'## Đợt\n' ""
only "a planned area file missing a roadmap section" sections "$d"

d=$(fixture); edit "$d/$S" $'## Trong phạm vi\n\n- Route `GET /members`.\n' $'## Trong phạm vi\n\n'
only "a required section left empty" sections "$d"

d=$(fixture); edit "$d/$S" $'## Kiểm soát\n' $'## Dữ liệu\n\nN/A\n\n## Kiểm soát\n'
only "an optional section holding only N/A" sections "$d"

# placeholders
d=$(fixture); edit "$d/$S" "Quản trị viên chỉ cần" "<area> chỉ cần"
only "a leftover template token" placeholders "$d"

d=$(fixture); edit "$d/$T1" $'- `src/app.py:3`; spec: R1.1.\n' $'- `src/app.py:3`; spec: R1.1.\n- `<path>:<line>`; spec: R1.1.\n'
only "a leftover template code span" placeholders "$d"

d=$(fixture); edit "$d/$T1" "Quản trị viên chỉ thấy" "TODO chỉ thấy"
only "a TODO in a ticket" placeholders "$d"

d=$(fixture); edit "$d/$S" $'## Câu hỏi còn mở\n' $'## Câu hỏi còn mở\n\n<!-- CO THE RONG -->\n'
only "a template comment left in" placeholders "$d"

# ids
d=$(fixture); edit "$d/$S" "$R12" "$R12$R12"
only "a criterion ID defined twice" ids "$d"

d=$(fixture); edit "$d/$S" "$R12" "$R12"$'\n### R2 Đếm\n\nĐếm người.\n'
only "a requirement heading without its dash" ids "$d"

d=$(fixture); edit "$d/$S" "$R12" "$R12"$'- R1 bổ sung.\n'
only "a criterion line with a malformed ID" ids "$d"

d=$(fixture); edit "$d/$S" "$R12" "$R12"$'- R2.1 KHI quản trị viên gọi `GET /members/count`, API thành viên PHẢI trả số người.\n'
edit "$d/$S" "| Xuất CSV |" "| R2.1: đếm |"
only "a criterion numbered under the wrong requirement" ids "$d"

d=$(fixture); edit "$d/$S" "$CONTROLS" "$CONTROLS"$'| a1  | Ghi audit                 | R1.2    | gọi với tenant B, khẳng định audit |\n'
only "a control ID outside the ids grammar" ids "$d"

d=$(fixture); edit "$d/$S" "$R12" "$R12"$'\n### R2 — Đếm\n\nĐếm người.\n'
only "a requirement with no criteria" ids "$d"

second_spec() { # fixture slug control -> a second clean spec in the area, with no tickets
  mkdir -p "$1/.claude/plans/demo/$2"
  "$py" -I - "$1/$S" "$1/.claude/plans/demo/$2/spec.md" "$3" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
text = re.sub(r"\| 0[12] .*\n", "", text).replace("| AL1 |", f"| {sys.argv[3]} |")
pathlib.Path(sys.argv[2]).write_bytes(text.encode("utf-8"))
PY
}
d=$(fixture); second_spec "$d" beta AL1
only "two specs in one area using one control prefix" ids "$d"

# refs
d=$(fixture); edit "$d/$T1" "Yêu cầu: R1.1, G1" "Yêu cầu: R1.1, G1, R9.9"
red "a ticket citing an ID its spec lacks" refs "$d"

d=$(fixture); edit "$d/$S" "| R1.2    |" "| R1.9    |"
only "a control guarding a criterion Mục tiêu lacks" refs "$d"

d=$(fixture); edit "$d/$S" "| Xuất CSV |" "| R5.1: Xuất CSV |"
only "an out-of-scope row deferring a criterion Mục tiêu lacks" refs "$d"

d=$(fixture); edit "$d/$S" "lọc theo workspace ở repository." "lọc như alpha:R7.1."
only "a cross-reference to a criterion that does not exist" refs "$d"

d=$(fixture); edit "$d/$S" "ADR-0100 (Proposed)" "ADR-0101 (Proposed)"
only "an ADR cited that does not exist" refs "$d"

d=$(fixture); edit "$d/$S" "ADR-0100 (Proposed)" "ADR-0100"
only "an ADR cited without its status" refs "$d"

d=$(fixture); edit "$d/$S" "ADR-0100 (Proposed)" "ADR-0100 (Accepted)"
only "an ADR cited with a status its file does not have" refs "$d"

d=$(fixture); edit "$d/$G1" "Yêu cầu: không (việc cỡ A, không có spec)" "Yêu cầu: R1.1"
edit "$d/$G1" "$XONG" $'- [ ] R1.1: nhãn đúng.\n'"$XONG"
only "a ticket with no spec citing requirement IDs" refs "$d"

# markers
d=$(fixture); edit "$d/$S" "PHẢI trả người của workspace hiện tại." "PHẢI trả người của workspace hiện tại [CAN LAM RO: Q7]."
red "a marker with no open question" markers "$d"

d=$(fixture)
edit "$d/$S" $'## Câu hỏi còn mở\n' $'## Câu hỏi còn mở\n\n- Q1. A? Chủ: Đạt. Chặn: R1.1.\n- Q2. B? Chủ: Đạt. Chặn: R1.1.\n- Q3. C? Chủ: Đạt. Chặn: R1.1.\n- Q4. D? Chủ: Đạt. Chặn: R1.1.\n'
edit "$d/$S" "chưa ai yêu cầu" "[CAN LAM RO: Q1] [CAN LAM RO: Q2] [CAN LAM RO: Q3] [CAN LAM RO: Q4]"
red "four markers in one spec" markers "$d"

# questions
d=$(fixture); edit "$d/$S" $'## Câu hỏi còn mở\n' $'## Câu hỏi còn mở\n\n- Q1. Có cần xuất CSV không?\n'
red "an open question with no owner" questions "$d"

# blocked-by
d=$(fixture); edit "$d/$T1" $'Status: ready-for-agent\nArea' $'Status: ready-for-agent\nBlocked by: 02\nArea'
red "a ticket blocked by a later one, in a cycle" blocked-by "$d"

d=$(fixture); edit "$d/$T2" $'Blocked by: 01\n' ""
edit "$d/$T1" $'Status: ready-for-agent\nArea' $'Status: ready-for-agent\nBlocked by: 02\nArea'
only "a ticket blocked by a later one" blocked-by "$d"

d=$(fixture); edit "$d/$T1" $'Status: ready-for-agent\nArea' $'Status: ready-for-agent\nBlocked by: .claude/plans/demo/alpha/issues/02-tenant.md\nArea'
only "a cycle through a path-form Blocked by" blocked-by "$d"

d=$(fixture); edit "$d/$T2" "Blocked by: 01" "Blocked by: 05"
red "a Blocked by target that does not exist" blocked-by "$d"

d=$(fixture); edit "$d/$T1" "Status: ready-for-agent" "Status: wontfix"
only "a ticket blocked by a wontfix ticket" blocked-by "$d"

# numbering
d=$(fixture); cp "$d/$T2" "$d/.claude/plans/demo/alpha/issues/03_bad.md"
red "a ticket file name outside NN-slug.md" numbering "$d"

d=$(fixture); cp "$d/$T2" "$d/.claude/plans/demo/alpha/issues/02-again.md"
red "two tickets with one number" numbering "$d"

d=$(fixture); mv "$d/$G1" "$d/.claude/plans/demo/gamma/issues/02-export-label.md"
edit "$d/.claude/plans/demo/gamma/issues/02-export-label.md" "# 01 — " "# 02 — "
only "a ticket folder not counting from 01" numbering "$d"

# layout
d=$(fixture); printf '# Lạc chỗ\n' >"$d/.claude/plans/demo/spec.md"
only "a spec.md outside a feature folder" layout "$d"

# controls
d=$(fixture); edit "$d/$S" "$CONTROLS" $'Không có.\n'
red "a Kiểm soát with no table and no reason" controls "$d"

d=$(fixture); edit "$d/$S" "| Test âm                          |" "| Kiểm thử                         |"
only "a Kiểm soát table missing a column" controls "$d"

d=$(fixture); edit "$d/$S" "| R1.2    |" "| tenant  |"
only "a control naming no requirement" controls "$d"

d=$(fixture); edit "$d/$S" "gọi với tenant B, khẳng định 404" "-"
only "a control with no negative test" controls "$d"

# coverage
d=$(fixture); edit "$d/$S" $'\n## Hành vi giữ nguyên' $'- R1.3 KHI quản trị viên gọi `GET /members/count`, API thành viên PHẢI trả số người.\n\n## Hành vi giữ nguyên'
only "a criterion in no ticket and not out of scope" coverage "$d"

d=$(fixture); edit "$d/$R" $'\n## Không làm' $'- YC3 KHI quản trị viên tìm theo tên, trang thành viên PHẢI lọc theo tên.\n\n## Không làm'
only "a YC in no roadmap row and not under Không làm" coverage "$d"

# acceptance
d=$(fixture); edit "$d/$T1" "$XONG" $'- ghi chú thêm.\n'"$XONG"
only "an acceptance line that is not a box" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$XONG" $'- [ ] Xong: make test.\n'
only "a Xong line out of shape" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$XONG" $'- [ ] kiểm tay trang thành viên.\n'"$XONG"
only "a criterion led by no ID" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$XONG" $'- [ ] R1.2: tenant B nhận 404.\n'"$XONG"
only "a criterion led by an ID its Yêu cầu line lacks" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$XONG" ""
only "a ticket with no Xong line" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$G1BOX$XONG" "$XONG$G1BOX"
only "a Xong line that is not last" acceptance "$d"

d=$(fixture); edit "$d/$T1" "$G1BOX" ""
only "a cited ID with no acceptance criterion" acceptance "$d"

# ready
d=$(fixture); edit "$d/$S" "Sẵn sàng: ĐẠT (2/10/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)" "Sẵn sàng: chưa kiểm"
red "ready-for-agent without a passing gate" ready "$d"

d=$(fixture); edit "$d/$T1" "Status: ready-for-agent" "Status: needs-triage"
edit "$d/$S" "Sẵn sàng: ĐẠT (2/10/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)" "Sẵn sàng: chưa kiểm"
only "a ready spec whose gate has not passed" ready "$d"

d=$(fixture); edit "$d/$T1" "Status: ready-for-agent" "Status: needs-triage"
edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: chưa"
only "a ready spec Đạt has not approved" ready "$d"

d=$(fixture); edit "$d/$S" $'## Câu hỏi còn mở\n' $'## Câu hỏi còn mở\n\n- Q1. Có cần xuất CSV không? Chủ: Đạt. Không đổi: R1.1.\n'
edit "$d/$S" "chưa ai yêu cầu" "[CAN LAM RO: Q1]"
only "a ready spec still carrying a marker" ready "$d"

d=$(fixture); edit "$d/$S" $'## Câu hỏi còn mở\n' $'## Câu hỏi còn mở\n\n- Q1. Có cần xuất CSV không? Chủ: Đạt. Chặn: R1.1.\n'
only "a ready spec with a blocking question" ready "$d"

d=$(fixture); edit "$d/$S" "ticket 01-02)" "ticket 02)"
only "a ready ticket the gate's run did not include" ready "$d"

d=$(fixture); edit "$d/$S" "Status: ready-for-agent" "Status: needs-triage"
edit "$d/$S" "Duyệt: Đạt 2/10/2026" "Duyệt: chưa"
only "a ready ticket whose spec Đạt has not approved" ready "$d"

d=$(fixture); edit "$d/$S" "Duyệt cách chia ticket 01-02." "Duyệt cách chia ticket 02."
only "a ready ticket whose split was not approved" ready "$d"

d=$(fixture); edit "$d/$G1" $'- 2026-10-02 (Đạt): Duyệt ticket.\n' ""
only "a ready ticket with no spec and no approval by Đạt" ready "$d"

d=$(fixture); edit "$d/$G1" $'- 2026-10-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.\n' ""
only "a ready ticket with no spec and no gate pass" ready "$d"

# anchors
d=$(fixture); edit "$d/$S" '(`src/app.py:3`)' '(`app.py:3`)'
only "an anchor with no path from the root" anchors "$d"

d=$(fixture); edit "$d/$S" '(`src/app.py:3`)' '(`src/nope.py:3`)'
only "an anchor to a file that does not exist" anchors "$d"

d=$(fixture); edit "$d/$S" '(`src/app.py:3`)' '(`src/app.py:300`)'
only "an anchor past the end of its file" anchors "$d"

d=$(fixture); edit "$d/$S" '`abc1234`' '`main`'
only "a Hiện trạng heading without its commit" anchors "$d"

d=$(fixture); edit "$d/$S" '(`src/app.py:3`)' '(src/app.py)'
only "a Hiện trạng fact with no anchor" anchors "$d"

d=$(fixture); edit "$d/$S" "Thiếu: chưa lọc" "Lưu ý: chưa lọc"
only "a Hiện trạng fact with no label" anchors "$d"

d=$(fixture); edit "$d/$S" $'Quản trị viên thấy người của workspace hiện tại.\n' $'Quản trị viên thấy người của workspace hiện tại.\n\nTrước đây: route trả cả tenant.\n'
only "a Trước đây line with no anchor" anchors "$d"

d=$(fixture); edit "$d/$T1" $'- `src/app.py:3`; spec: R1.1.\n' $'- `src/app.py:3`; spec: R1.1. Chạy ở `localhost:8000` lúc `10:30`.\n'
quiet "a host:port or a time in a code span is not an anchor" anchors "$d"

# links, ticket-list, adr
d=$(fixture); edit "$d/$A" "demo/alpha/spec.md" "demo/beta/spec.md"
only "a link to a file that does not exist" links "$d"

d=$(fixture); edit "$d/$S" "| Ticket " "| Status "
only "a ticket table copying a ticket's Status" ticket-list "$d"

d=$(fixture); cp "$d/docs/adr/0100-filter-by-workspace.md" "$d/docs/adr/0100-another-decision.md"
only "two ADRs with one number" adr "$d"

d=$(fixture); edit "$d/docs/adr/0100-filter-by-workspace.md" "status: Proposed" "status: Maybe"
red "an ADR status outside domain.md" adr "$d"

# stray
d=$(fixture); printf '# Glossary\n' >"$d/GLOSSARY.md"
only "a GLOSSARY.md beside CONTEXT.md" stray "$d"

d=$(fixture); mkdir -p "$d/.scratch/alpha/issues"; printf '# 01\n' >"$d/.scratch/alpha/issues/01-a.md"
only "a .scratch tracker" stray "$d"

d=$(fixture); mkdir -p "$d/specs/001-members"
only "a specs/NNN- folder" stray "$d"

d=$(fixture); mkdir -p "$d/docs/notes/issues"; printf '# 01\n' >"$d/docs/notes/issues/01-a.md"
only "a ticket outside .claude/plans" stray "$d"

d=$(fixture); mkdir -p "$d/docs/notes"; printf '# Spec\n\nStatus: needs-triage\n' >"$d/docs/notes/spec.md"
only "a spec.md with a Status line outside .claude/plans" stray "$d"

d=$(fixture); mkdir -p "$d/docs/openapi"; printf '# API spec\n\nThe public API.\n' >"$d/docs/openapi/spec.md"
quiet "a spec.md that is no tracker file" stray "$d"

# emoji
d=$(fixture); printf 'Xong \342\234\205\n' >>"$d/$T2"
only "an emoji in a ticket" emoji "$d"

# ears, vague, collision: warnings
d=$(fixture); edit "$d/$S" "PHẢI trả người của workspace hiện tại." "PHẢI trả người của workspace hiện tại và PHẢI ghi audit."
warned "a criterion with two modals" ears "$d"

d=$(fixture); edit "$d/$S" "API thành viên PHẢI trả người" "hệ thống PHẢI trả người"
warned "a criterion whose subject is the whole system" ears "$d"

d=$(fixture); edit "$d/$S" "API thành viên PHẢI trả người" "Hệ thống PHẢI trả người"
warned "a criterion whose subject is Hệ thống, capitalised" ears "$d"

d=$(fixture); edit "$d/$S" "THÌ API thành viên" "API thành viên"
warned "a NẾU with no THÌ" ears "$d"

d=$(fixture); edit "$d/$S" "NẾU người gọi thuộc tenant khác, THÌ" "KHI người gọi thuộc tenant khác, THÌ"
warned "a THÌ with no NẾU" ears "$d"

d=$(fixture); edit "$d/$S" "PHẢI TIẾP TỤC trả 200" "PHẢI trả 200"
warned "a G line without PHẢI TIẾP TỤC" ears "$d"

d=$(fixture); edit "$d/$S" "PHẢI trả người" "PHẢI trả nhanh chóng người"
warned "a vague word in a criterion" vague "$d"

d=$(fixture); edit "$d/$R" "PHẢI chỉ hiện người" "PHẢI hiện đầy đủ người"
warned "a vague word in a YC line" vague "$d"

d=$(fixture); edit "$d/$S" "PHẢI trả người" "PHẢI trả ít nhất một người"
quiet "a vague-word exception is not a hit" vague "$d"

d=$(fixture); second_spec "$d" support-access SA1
edit "$d/$S" "PHẢI trả người của workspace hiện tại." "PHẢI trả người của workspace hiện tại như support-access:R1.1."
quiet "a cross-reference whose slug holds a vague word is not a hit" vague "$d"

d=$(fixture); edit "$d/$T2" $'Blocked by: 01\n' ""
warned "two tickets touching one route with no dependency" collision "$d"

# --- the modes, and what must not count as a pass -------------------------------

d=$(fixture); rm "$d/$T2"
plans "$d" >/dev/null
check "one ticket, so no pair to compare: collision is Không áp dụng, not Đạt" yes \
  "$(grep -qE '^Không áp dụng +collision' "$work/out" && echo yes || echo no)"

d=$(fixture)
"$py" -I - "$d/$S" <<'PY'
import pathlib, sys, unicodedata
path = pathlib.Path(sys.argv[1])
path.write_bytes(unicodedata.normalize("NFD", path.read_bytes().decode("utf-8")).encode("utf-8"))
PY
check "a spec saved as NFD still passes" 0 "$(plans "$d")"

check "a missing check_hygiene.py: exits 1" 1 "$(plans "$clean" --hygiene "$work/none.py")"
check "a missing check_hygiene.py: emoji is Chưa kiểm, not Đạt" yes \
  "$(grep -qE '^Chưa kiểm +emoji' "$work/out" && echo yes || echo no)"

d=$(fixture); edit "$d/$S" "Status: ready-for-agent" "Status: in-progress"
check "--advisory exits 0 on a failure" 0 "$(plans "$d" --advisory)"
check "--advisory still reports it" yes "$(reported status)"

d=$(fixture); edit "$d/$R" $'\n## Không làm' $'- YC3 KHI quản trị viên tìm theo tên, trang thành viên PHẢI lọc theo tên.\n\n## Không làm'
check "--path reports only its folder" 0 "$(plans "$d" --path "$d/.claude/plans/demo/alpha")"
check "--area reports the area" 1 "$(plans "$d" --area demo)"

check "--table exits 0" 0 "$(plans "$clean" --table "$clean/$S")"
check "--table prints the ticket lines" yes \
  "$(grep -qF '| 02 | needs-triage | 01 | R1.2, AL1 |' "$work/out" && echo yes || echo no)"

# --- owner files: a block missing or doubled is an error, never a quiet pass ----

copy_owners() { # -> a copy of the owner files
  local dir="$work/owners$1"
  mkdir -p "$dir/.claude/skills" "$dir/docs"
  cp -r "$owners/.claude/skills/writing-plan-specs" "$dir/.claude/skills/"
  cp -r "$owners/docs/agents" "$dir/docs/"
  echo "$dir"
}

o=$(copy_owners 1); printf '\n```ids\nrequirement R[0-9]+\n```\n' >>"$o/.claude/skills/writing-plan-specs/spec-template.md"
check "a doubled ids block: exits 2" 2 \
  "$("$py" -I "$script" --owners "$o" --repo "$clean" --hygiene "$hygiene" >"$work/out" 2>&1; echo $?)"
check "a doubled ids block: says so" yes "$(grep -qF 'found 2' "$work/out" && echo yes || echo no)"

o=$(copy_owners 2); edit "$o/.claude/skills/writing-plan-specs/ears-vn.md" '```vague-words' '```vague'
check "a missing vague-words block: exits 2" 2 \
  "$("$py" -I "$script" --owners "$o" --repo "$clean" --hygiene "$hygiene" >"$work/out" 2>&1; echo $?)"

o=$(copy_owners 3); edit "$o/docs/agents/triage-labels.md" '| `needs-triage`             | `needs-triage`' '| `needs-triage`             | `needs-review`'
check "a label renamed in triage-labels.md: exits 1" 1 "$(plans "$clean" --owners "$o")"
check "a label renamed in triage-labels.md: the old one is refused" yes "$(reported status)"

# The header tables and GRAMMAR hold each other to the same values, both ways.
spec_tpl=.claude/skills/writing-plan-specs/spec-template.md
o=$(copy_owners 4); edit "$o/$spec_tpl" '`chưa`, `Đạt <d/m/yyyy>` hoặc' '`chưa`, `Đạt <d/m/yyyy>`, `Đạt đã xem` hoặc'
check "a Duyệt value the table lists and GRAMMAR refuses: exits 2" 2 \
  "$("$py" -I "$script" --owners "$o" --repo "$clean" --hygiene "$hygiene" >"$work/out" 2>&1; echo $?)"
check "a Duyệt value the table lists and GRAMMAR refuses: says so" yes \
  "$(grep -qF 'listed but refused' "$work/out" && echo yes || echo no)"

o=$(copy_owners 5); edit "$o/$spec_tpl" ' hoặc `agent, tạm theo ủy quyền <d/m/yyyy>`' ''
check "a Duyệt form GRAMMAR accepts and the table no longer lists: exits 2" 2 \
  "$("$py" -I "$script" --owners "$o" --repo "$clean" --hygiene "$hygiene" >"$work/out" 2>&1; echo $?)"

o=$(copy_owners 6); edit "$o/.claude/skills/writing-plan-specs/requirements-template.md" $'## Ủy quyền\n' $'## Ủy quyền cũ\n'
check "an area block with no delegation section: exits 2" 2 \
  "$("$py" -I "$script" --owners "$o" --repo "$clean" --hygiene "$hygiene" >"$work/out" 2>&1; echo $?)"

# --- the real plans, advisory: the checker runs on them without crashing --------

if [ -d "$here/.claude/plans" ]; then
  "$py" -I "$script" --owners "$owners" --repo "$here" --hygiene "$hygiene" --advisory >"$work/out" 2>&1
  check "the real .claude/plans in advisory mode: exits 0" 0 "$?"
else
  echo "skip: no .claude/plans beside this script (run from the repository to include it)"
fi

echo "check_plans: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
