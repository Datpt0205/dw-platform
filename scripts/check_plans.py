"""Check the planning documents under .claude/plans/ against the files that own their format.

The mechanical half of writing-plan-specs, checking-plan-readiness and
checking-plan-consistency. Everything it enforces is read from its owner, never
restated here, so the check cannot drift from the format it checks:

- sections, header keys and template tokens: the `markdown template` blocks of
  spec-template.md, ticket-template.md and requirements-template.md, and the
  area-file sections in the `markdown area` block;
- the ID grammar: the `ids` block of spec-template.md;
- EARS-VN keywords and vague words: the two blocks of ears-vn.md;
- Status labels: column 2 of the table in docs/agents/triage-labels.md;
- ADR statuses: docs/agents/domain.md; wayfinder ticket types:
  docs/agents/issue-tracker.md; emoji ranges: scripts/check_hygiene.py.

The one thing written here is the grammar of each header value, which the
templates give as prose tables. A header key the template block declares and
this file has no grammar for is an owner error, so the two disagree loudly. So
is, for the keys in LISTED_VALUES, a value the table lists that the grammar
refuses, or an alternative of the grammar that no listed value shows.

An owner block that is missing or present twice is an owner error too (exit 2):
a check that matches nothing looks exactly like a check that found nothing
(failure-modes.md #0). Every check prints one status, and a check that could not
run says so instead of passing (`Chua kiem` never counts as a pass).

Usage:
    python scripts/check_plans.py [--area AREA | --path DIR] [--advisory]
    python scripts/check_plans.py --table .claude/plans/<area>/<feature>/spec.md

Exit 0 clean or --advisory, 1 when an enforcing check failed or did not run,
2 when an owner file cannot be read. Python stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
PLANS = Path(".claude/plans")
SKILL = Path(".claude/skills/writing-plan-specs")
SPEC_TEMPLATE = SKILL / "spec-template.md"
TICKET_TEMPLATE = SKILL / "ticket-template.md"
REQUIREMENTS_TEMPLATE = SKILL / "requirements-template.md"
EARS_FILE = SKILL / "ears-vn.md"
TRIAGE_FILE = Path("docs/agents/triage-labels.md")
DOMAIN_FILE = Path("docs/agents/domain.md")
TRACKER_FILE = Path("docs/agents/issue-tracker.md")
HYGIENE_FILE = Path("scripts/check_hygiene.py")

OK, FAIL, NA, NOT_RUN = "Đạt", "Không đạt", "Không áp dụng", ("Chưa kiểm")
DOT = "·"
DASH = "—"
DATE = r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}"
TICKET_SET = r"[0-9]{2}(?:-[0-9]{2})?(?:, [0-9]{2}(?:-[0-9]{2})?)*"
ISO_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
DELEGATED = "agent, tạm theo ủy quyền"

# Header value grammar per document kind, transcribed from the "Dong dau tep"
# tables of the templates. Keys and their order come from the template blocks.
GRAMMAR: dict[str, dict[str, str]] = {
    "spec": {
        "Status": r".+",
        "Area": rf"(?P<area>[a-z0-9-]+) · Nhánh: `[^`]+` · Viết: {DATE}",
        "Duyệt": rf"chưa|Đạt {DATE}|{DELEGATED} {DATE}",
        "Sẵn sàng": (
            rf"chưa kiểm|(?:ĐẠT|CẦN XEM|CHƯA ĐẠT) "
            rf"\({DATE}; [0-9]+ CRITICAL, [0-9]+ HIGH(?:; ticket {TICKET_SET})?\)"
        ),
    },
    "ticket": {
        "Status": r".+",
        "Blocked by": r"[^,\s]+(?:, [^,\s]+)*",
        "Area": r"(?P<area>[a-z0-9-]+)",
        "Yêu cầu": r"không \(.+\)|[A-Za-z0-9.]+(?:, [A-Za-z0-9.]+)*",
    },
    "requirements": {"Status": r".+", "Area": rf"(?P<area>[a-z0-9-]+) · Viết: {DATE}"},
}
GRAMMAR["requirements"]["Duyệt"] = GRAMMAR["spec"]["Duyệt"]
GRAMMAR["requirements"]["Sẵn sàng"] = GRAMMAR["spec"]["Sẵn sàng"]
# The keys whose table cell gives every allowed value as a code span. Before any
# check runs, each listed value (placeholders replaced by SAMPLE, and a choice
# placeholder such as `<A, B hay C>` read as one value per word) must match the
# grammar, and each top-level alternative of the grammar must match a value.
LISTED_VALUES = {"spec": ("Duyệt", "Sẵn sàng"), "ticket": ("Yêu cầu",)}
SAMPLE = {"<d/m/yyyy>": "2/10/2026", "<n>": "1", "<m>": "1", "<NN-NN>": "01-02", "<lý do>": "x"}
# Fixed lines other owners give: the delegation in an area file
# (requirements-template.md, `markdown area`) and the two Comments lines that make
# a ticket with no spec ready (ticket-template.md, Comments).
DELEGATION = rf"Ủy quyền duyệt: Đạt, (?P<kind>spec|requirements), từ (?P<date>{DATE})"
TICKET_APPROVED = rf"{ISO_DATE} \(Đạt\): Duyệt ticket\."
TICKET_PASSED = rf"{ISO_DATE} \(agent\): checking-plan-readiness ĐẠT; ready-for-agent\."
# ticket-template.md: "bo han dong khi khong gi chan" -- the one optional header line.
OPTIONAL_HEADERS = {"Blocked by"}
ID_NAMES: tuple[str, ...] = ("requirement", "criterion", "unchanged", "control", "question")
ID_NAMES += ("marker", "cross-ref", "adr", "yc", "kq")
EARS_ROLES = ("pattern", "then", "modal", "keep", "not-subject")
IF_KEYWORD = "NẾU"
LABELS_DONE = ("Thiếu", "Chưa rõ", "Ràng buộc")
PRUNE = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}
PRUNE |= {".mypy_cache", ".ruff_cache", ".pytest_cache", "vendor", ".turbo", ".pnpm-store"}
STRAY_DIRS = (".scratch", "openspec", ".kiro")
FILE_SUFFIXES = {"py", "ts", "tsx", "js", "md", "yaml", "yml", "json", "sql", "sh", "toml", "txt"}

# Section names the checks below look into. Each must exist in its template.
S = {
    "current": "Hiện trạng",
    "goals": "Mục tiêu",
    "kept": "Hành vi giữ nguyên",
    "out": "Ngoài phạm vi",
    "controls": "Kiểm soát",
    "questions": "Câu hỏi còn mở",
    "decisions": "Quyết định",
    "tickets": "Danh sách ticket",
    "work": "Việc cần làm",
    "accept": "Tiêu chí chấp nhận",
    "source": "Nguồn",
    "yc": "Yêu cầu",
    "notdo": "Không làm",
    "kq": "Kết quả đo được",
    "roadmap": "Lộ trình",
    "comments": "Comments",
    "delegation": "Ủy quyền",
}
REQ_HEADER = "Yêu cầu"
READY_HEADER = "Sẵn sàng"
APPROVED_HEADER = "Duyệt"
ROADMAP_COLUMN = "Yêu cầu cấp area"
CONTROL_COLUMNS = ("#", "Yêu cầu", "Test âm")
OUT_COLUMN = "Việc"


class OwnerError(Exception):
    """An owner file is missing, or holds a block zero or two times."""


def read(path: Path) -> str:
    return unicodedata.normalize("NFC", path.read_text(encoding="utf-8-sig"))


def code_free(text: str) -> str:
    """The text with every backtick span blanked, offsets kept."""
    return re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), text)


def spans(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def cells(line: str) -> list[str]:
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [part.strip() for part in parts[1:-1]]


FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def fenced_flags(lines: list[str]) -> list[bool]:
    flags: list[bool] = []
    fence = ""
    for line in lines:
        match = FENCE.match(line)
        if fence:
            flags.append(True)
            if match and match.group(1).startswith(fence) and not match.group(2).strip():
                fence = ""
        elif match:
            fence = match.group(1)
            flags.append(True)
        else:
            flags.append(False)
    return flags


def owner_block(path: Path, info: str) -> list[str]:
    if not path.is_file():
        raise OwnerError(f"{path}: owner file not found")
    lines = read(path).splitlines()
    found: list[list[str]] = []
    index = 0
    while index < len(lines):
        match = FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        fence, name = match.group(1), match.group(2).strip()
        body: list[str] = []
        index += 1
        while index < len(lines):
            close = FENCE.match(lines[index])
            if close and close.group(1).startswith(fence) and not close.group(2).strip():
                break
            body.append(lines[index])
            index += 1
        index += 1
        if name == info:
            found.append(body)
    if len(found) != 1:
        raise OwnerError(f"{path}: expected exactly one ```{info} block, found {len(found)}")
    return found[0]


# ------------------------------------------------------------------ owners --


@dataclass
class SectionRule:
    name: str
    optional: bool
    may_be_empty: bool
    table: list[str]


@dataclass
class Template:
    title: str
    headers: list[str]
    sections: list[SectionRule]
    loose_tokens: set[str]
    span_tokens: set[str]

    def rule(self, name: str) -> SectionRule | None:
        return next((rule for rule in self.sections if rule.name == name), None)


def section_name(heading: str) -> str:
    return heading.split("(", 1)[0].strip()


def parse_template(lines: list[str], kind: str, where: Path) -> Template:
    title = next((line for line in lines if line.startswith("# ")), "")
    headers: list[str] = []
    if title:
        index = lines.index(title) + 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        while index < len(lines) and re.match(r"^[^\s:#|<][^:]{0,40}: ", lines[index]):
            headers.append(lines[index].split(":", 1)[0])
            index += 1
        unknown = [key for key in headers if key not in GRAMMAR.get(kind, {})]
        if unknown:
            raise OwnerError(f"{where}: header line(s) {unknown} have no value grammar here")
    sections: list[SectionRule] = []
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        following = [rest for rest in lines[index + 1 :] if rest.strip()]
        marker = following[0] if following else ""
        table: list[str] = []
        for rest in lines[index + 1 :]:
            if rest.startswith("## "):
                break
            if rest.startswith("|"):
                table = cells(rest)
                break
        sections.append(
            SectionRule(
                section_name(line[3:]),
                marker.startswith("<!-- TUY CHON"),
                marker.startswith("<!-- CO THE RONG"),
                table,
            )
        )
    text = "\n".join(lines)
    span_tokens = {f"`{span}`" for span in spans(text) if "<" in span}
    loose = set(re.findall(r"<(?!!--)[^<>\n]+>", code_free(text)))
    return Template(title, headers, sections, loose, span_tokens)


@dataclass
class Ids:
    raw: dict[str, str]
    compiled: dict[str, re.Pattern[str]] = field(default_factory=dict)

    def full(self, name: str, text: str) -> bool:
        return re.fullmatch(self.raw[name], text) is not None

    def pattern(self, name: str) -> re.Pattern[str]:
        if name not in self.compiled:
            before = r"(?<![A-Za-z0-9/._-])" if name == "cross-ref" else r"(?<![A-Za-z0-9])"
            rx = rf"{before}(?:{self.raw[name]})(?![A-Za-z0-9]|\.[0-9])"
            self.compiled[name] = re.compile(rx)
        return self.compiled[name]

    def find(self, name: str, text: str) -> list[str]:
        return self.pattern(name).findall(text)


@dataclass
class Owners:
    root: Path
    spec: Template
    ticket: Template
    requirements: Template
    area: list[SectionRule]
    ids: Ids
    keywords: dict[str, str]
    vague: list[str]
    vague_exceptions: list[str]
    labels: set[str]
    adr_statuses: set[str]
    way_types: set[str]


def load_owners(root: Path) -> Owners:
    spec = parse_template(owner_block(root / SPEC_TEMPLATE, "markdown template"), "spec", root)
    ticket = parse_template(
        owner_block(root / TICKET_TEMPLATE, "markdown template"), "ticket", root
    )
    requirements = parse_template(
        owner_block(root / REQUIREMENTS_TEMPLATE, "markdown template"), "requirements", root
    )
    area = parse_template(
        owner_block(root / REQUIREMENTS_TEMPLATE, "markdown area"), "area", root
    ).sections
    _check_listed_values(root)

    raw: dict[str, str] = {}
    for line in owner_block(root / SPEC_TEMPLATE, "ids"):
        if line.strip():
            name, _, pattern = line.strip().partition(" ")
            re.compile(pattern)
            raw[name] = pattern
    missing = [name for name in ID_NAMES if name not in raw]
    if missing:
        raise OwnerError(f"{root / SPEC_TEMPLATE}: ids block lacks {missing}")

    keywords: dict[str, str] = {}
    for line in owner_block(root / EARS_FILE, "ears-keywords"):
        if line.strip() and not line.startswith("#"):
            role, _, keyword = line.strip().partition(" ")
            if role not in EARS_ROLES:
                raise OwnerError(f"{root / EARS_FILE}: unknown keyword role {role!r}")
            keywords[keyword.strip()] = role
    lacking = {"pattern", "then", "modal", "keep"} - set(keywords.values())
    if lacking or keywords.get(IF_KEYWORD) != "pattern":
        raise OwnerError(f"{root / EARS_FILE}: keyword roles missing: {sorted(lacking)}")

    vague: list[str] = []
    exceptions: list[str] = []
    for line in owner_block(root / EARS_FILE, "vague-words"):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        (exceptions if entry.startswith("!") else vague).append(entry.lstrip("!"))

    labels: set[str] = set()
    triage = root / TRIAGE_FILE
    if not triage.is_file():
        raise OwnerError(f"{triage}: owner file not found")
    for line in read(triage).splitlines():
        row = cells(line) if line.startswith("|") else []
        if len(row) >= 2 and row[1].startswith("`"):
            labels.add(row[1].strip("`").split(" ", 1)[0])
    if not labels:
        raise OwnerError(f"{triage}: no labels in column 2 of the table")

    domain = root / DOMAIN_FILE
    if not domain.is_file():
        raise OwnerError(f"{domain}: owner file not found")
    settled = read(domain).split("## Decisions are not all settled", 1)
    statuses = set(re.findall(r"^- \*\*([A-Z][a-z]+)\*\*:", settled[-1].split("\n## ")[0], re.M))
    if len(settled) != 2 or not statuses:
        raise OwnerError(f"{domain}: no ADR statuses under 'Decisions are not all settled'")

    tracker = root / TRACKER_FILE
    if not tracker.is_file():
        raise OwnerError(f"{tracker}: owner file not found")
    flat = " ".join(read(tracker).split())
    types = re.search(r"A `Type:` line records the ticket type \(([^)]*)\)", flat)
    if not types:
        raise OwnerError(f"{tracker}: no wayfinder ticket types after 'A `Type:` line'")

    owners = Owners(
        root,
        spec,
        ticket,
        requirements,
        area,
        Ids(raw),
        keywords,
        vague,
        exceptions,
        labels,
        statuses,
        set(spans(types.group(1))),
    )
    _require_sections(owners)
    return owners


def _alternatives(pattern: str) -> list[str]:
    """The top-level alternatives of a regular expression."""
    parts: list[str] = []
    depth, start, index, in_class = 0, 0, 0, False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char in "()":
            depth += 1 if char == "(" else -1
        elif char == "|" and depth == 0:
            parts.append(pattern[start:index])
            start = index + 1
        index += 1
    return [*parts, pattern[start:]]


def _listed_forms(span: str) -> list[str]:
    """One code span of a header table cell, as the concrete values it stands for."""
    choice = re.search(r"<([^<>]+) hay ([^<>]+)>", span)
    forms = [span]
    if choice:
        words = [*choice.group(1).split(", "), choice.group(2)]
        forms = [span.replace(choice.group(0), word) for word in words]
    for placeholder, sample in SAMPLE.items():
        forms = [form.replace(placeholder, sample) for form in forms]
    return forms


def _check_listed_values(root: Path) -> None:
    """Hold GRAMMAR to the values the header tables list, in both directions."""
    for kind, keys in LISTED_VALUES.items():
        path = root / (SPEC_TEMPLATE if kind == "spec" else TICKET_TEMPLATE)
        rows = {row[0]: row for row in map(cells, read(path).splitlines()) if len(row) > 1}
        for key in keys:
            row = rows.get(f"`{key}:`", [])
            values = [form for span in spans(row[1]) for form in _listed_forms(span)] if row else []
            if not values:
                raise OwnerError(f"{path}: no table row lists the values of `{key}:`")
            refused = [value for value in values if not re.fullmatch(GRAMMAR[kind][key], value)]
            unseen = [
                alt
                for alt in _alternatives(GRAMMAR[kind][key])
                if not any(re.fullmatch(alt, value) for value in values)
            ]
            if refused or unseen:
                raise OwnerError(
                    f"{path}: `{key}:` values disagree with check_plans.py GRAMMAR: "
                    f"listed but refused {refused}, accepted but not listed {unseen}"
                )


def _require_sections(owners: Owners) -> None:
    """Every section and column a check reads must exist in its template."""
    needs = (
        (owners.spec, ("current", "goals", "kept", "out", "controls", "questions")),
        (owners.spec, ("decisions", "tickets")),
        (owners.ticket, ("work", "accept", "source", "comments")),
        (owners.requirements, ("yc", "notdo", "kq", "questions")),
    )
    for template, keys in needs:
        for key in keys:
            if not template.rule(S[key]):
                raise OwnerError(f"template section {S[key]!r} not found in its owner block")
    if not any(rule.name == S["delegation"] for rule in owners.area):
        raise OwnerError(f"area section {S['delegation']!r} not found in its owner block")
    columns = (
        (owners.spec.rule(S["controls"]), CONTROL_COLUMNS),
        (owners.spec.rule(S["out"]), (OUT_COLUMN,)),
        (next((r for r in owners.area if r.name == S["roadmap"]), None), (ROADMAP_COLUMN,)),
    )
    for rule, wanted in columns:
        if rule is None or any(column not in rule.table for column in wanted):
            raise OwnerError(f"template table lacks one of the columns {wanted}")


# --------------------------------------------------------------- documents --


@dataclass
class Section:
    name: str
    line: int
    heading: str
    start: int
    end: int


@dataclass
class Doc:
    path: Path
    rel: str
    kind: str
    area: str
    lines: list[str]
    fenced: list[bool]
    title: tuple[int, str] | None
    headers: list[tuple[int, str, str]]
    sections: list[Section]

    @property
    def folder(self) -> Path:
        return self.path.parent.parent if self.kind in ("ticket", "wayticket") else self.path.parent

    def header(self, key: str) -> tuple[int, str] | None:
        return next(((line, value) for line, k, value in self.headers if k == key), None)

    def value(self, key: str) -> str:
        found = self.header(key)
        return found[1] if found else ""

    def section(self, name: str) -> Section | None:
        return next((sec for sec in self.sections if sec.name == name), None)

    def body(self, name: str) -> list[tuple[int, str]]:
        sec = self.section(name)
        if not sec:
            return []
        return [
            (index + 1, self.lines[index])
            for index in range(sec.start, sec.end)
            if not self.fenced[index]
        ]

    def bullets(self, name: str) -> list[tuple[int, str]]:
        out: list[list[int | str]] = []
        open_item = False
        for number, line in self.body(name):
            if line.startswith("- "):
                out.append([number, line[2:].strip()])
                open_item = True
            elif open_item and line.strip() and line[:1] in (" ", "\t"):
                out[-1][1] = f"{out[-1][1]} {line.strip()}"
            else:
                open_item = False
        return [(int(item[0]), str(item[1])) for item in out]

    def table(self, name: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
        header: list[str] = []
        rows: list[tuple[int, list[str]]] = []
        for number, line in self.body(name):
            if not line.startswith("|"):
                if header:
                    break
                continue
            row = cells(line)
            if not header:
                header = row
            elif not all(re.fullmatch(r":?-+:?", cell) for cell in row):
                rows.append((number, row))
        return header, rows

    def ticket_number(self) -> str:
        return self.path.name[:2]


def classify(rel_parts: tuple[str, ...], plans: Path) -> str:
    if len(rel_parts) == 1:
        return "area"
    if len(rel_parts) == 2 and rel_parts[1] == "requirements.md":
        return "requirements"
    if len(rel_parts) == 3 and rel_parts[2] == "spec.md":
        return "spec"
    if len(rel_parts) == 3 and rel_parts[2] == "map.md":
        return "map"
    if len(rel_parts) == 4 and rel_parts[2] == "issues":
        # A folder with a map and no spec holds wayfinder tickets; any other
        # folder holds house tickets, with or without a spec beside them.
        folder = plans.joinpath(*rel_parts[:2])
        if (folder / "map.md").is_file() and not (folder / "spec.md").is_file():
            return "wayticket"
        return "ticket"
    if "issues" in rel_parts or rel_parts[-1] in ("spec.md", "map.md", "requirements.md"):
        return "misplaced"
    return "note"


def parse_doc(repo: Path, path: Path) -> Doc:
    plans = repo / PLANS
    rel_path = path.relative_to(repo)
    try:
        parts = path.relative_to(plans).parts
        kind = classify(parts, plans)
        area = parts[0].removesuffix(".md")
    except ValueError:
        kind, area = "other", ""
    lines = read(path).splitlines()
    fenced = fenced_flags(lines)
    title: tuple[int, str] | None = None
    headers: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines[:5]):
        if line.startswith("# ") and not fenced[index]:
            title = (index + 1, line[2:].strip())
            cursor = index + 1
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            while cursor < len(lines):
                match = re.match(r"^([^\s:#|<\-*>][^:]{0,40}): ?(.*)$", lines[cursor])
                if not match:
                    break
                headers.append((cursor + 1, match.group(1), match.group(2).strip()))
                cursor += 1
            break
    sections: list[Section] = []
    for index, line in enumerate(lines):
        if line.startswith("## ") and not fenced[index]:
            if sections:
                sections[-1].end = index
            heading = line[3:].strip()
            sections.append(
                Section(section_name(heading), index + 1, heading, index + 1, len(lines))
            )
    return Doc(path, rel_path.as_posix(), kind, area, lines, fenced, title, headers, sections)


# ------------------------------------------------------------------- model --


@dataclass
class Finding:
    rel: str
    line: int
    check: str
    message: str
    fix: str


@dataclass
class SpecIds:
    requirements: dict[str, int] = field(default_factory=dict)
    criteria: dict[str, int] = field(default_factory=dict)
    criterion_text: dict[str, str] = field(default_factory=dict)
    table_rows: set[str] = field(default_factory=set)
    withdrawn: set[str] = field(default_factory=set)
    unchanged: dict[str, int] = field(default_factory=dict)
    unchanged_text: dict[str, str] = field(default_factory=dict)
    controls: dict[str, int] = field(default_factory=dict)
    questions: dict[str, tuple[int, str]] = field(default_factory=dict)
    duplicates: list[tuple[int, str]] = field(default_factory=list)
    malformed: list[tuple[int, str, str]] = field(default_factory=list)

    def live(self) -> dict[str, int]:
        found = {k: v for k, v in self.criteria.items() if k not in self.withdrawn}
        found.update({k: v for k, v in self.unchanged.items() if k not in self.withdrawn})
        found.update(self.controls)
        return found

    def defined(self) -> set[str]:
        return set(self.criteria) | set(self.unchanged) | set(self.controls)


@dataclass
class Model:
    repo: Path
    owners: Owners
    docs: list[Doc]
    scope: list[str]
    hygiene: Path | None
    cache: dict[Path, Doc] = field(default_factory=dict)
    id_cache: dict[str, SpecIds] = field(default_factory=dict)

    def of(self, *kinds: str) -> list[Doc]:
        return [doc for doc in self.docs if doc.kind in kinds]

    def in_scope(self, rel: str) -> bool:
        if not rel.startswith(PLANS.as_posix() + "/"):
            return True
        return any(rel == scope or rel.startswith(scope + "/") for scope in self.scope)

    def doc(self, path: Path) -> Doc | None:
        path = path.resolve()
        for doc in self.docs:
            if doc.path.resolve() == path:
                return doc
        if path not in self.cache:
            if not path.is_file():
                return None
            self.cache[path] = parse_doc(self.repo, path)
        return self.cache[path]

    def spec_of(self, ticket: Doc) -> Doc | None:
        return self.doc(ticket.folder / "spec.md")

    def tickets_of(self, spec: Doc) -> list[Doc]:
        folder = spec.path.parent / "issues"
        found = [self.doc(path) for path in sorted(folder.glob("*.md"))] if folder.is_dir() else []
        return [doc for doc in found if doc is not None]

    def ids_of(self, doc: Doc) -> SpecIds:
        if doc.rel not in self.id_cache:
            self.id_cache[doc.rel] = collect_ids(self.owners.ids, doc)
        return self.id_cache[doc.rel]


def collect_ids(ids: Ids, doc: Doc) -> SpecIds:
    found = SpecIds()

    def define(store: dict[str, int], key: str, line: int) -> None:
        if key in store:
            found.duplicates.append((line, key))
        else:
            store[key] = line

    if doc.kind == "requirements":
        for line, text in doc.bullets(S["yc"]):
            head = text.split(" ", 1)[0]
            if ids.full("yc", head):
                define(found.criteria, head, line)
                found.criterion_text[head] = text[len(head) :].strip()
                if text[len(head) :].strip().startswith("[Bỏ]"):
                    found.withdrawn.add(head)
        for line, row in doc.table(S["kq"])[1]:
            if row and ids.full("kq", row[0]):
                define(found.requirements, row[0], line)
        _collect_questions(ids, doc, found, define)
        return found

    headings: list[tuple[int, str]] = []
    for line, text in doc.body(S["goals"]):
        if text.startswith("### "):
            match = re.match(rf"^### ({ids.raw['requirement']}) — \S.*$", text)
            if not match:
                found.malformed.append((line, text, "requirement"))
                continue
            define(found.requirements, match.group(1), line)
            headings.append((line, match.group(1)))
        elif text.startswith("|"):
            row = cells(text)
            if row and ids.full("criterion", row[0]):
                define(found.criteria, row[0], line)
                found.table_rows.add(row[0])
    for line, text in doc.bullets(S["goals"]):
        head = text.split(" ", 1)[0]
        if not ids.full("criterion", head):
            if re.match(r"^R[0-9]", head):
                found.malformed.append((line, text, "criterion"))
            continue
        define(found.criteria, head, line)
        rest = text[len(head) :].strip()
        found.criterion_text[head] = rest
        if rest.startswith("[Bỏ]"):
            found.withdrawn.add(head)
        owner = [req for at, req in headings if at < line]
        if not owner or head.split(".")[0] != owner[-1]:
            found.malformed.append((line, text, "parent"))
    for line, text in doc.bullets(S["kept"]):
        head = text.split(" ", 1)[0]
        if ids.full("unchanged", head):
            define(found.unchanged, head, line)
            found.unchanged_text[head] = text[len(head) :].strip()
            if text[len(head) :].strip().startswith("[Bỏ]"):
                found.withdrawn.add(head)
    for line, row in doc.table(S["controls"])[1]:
        if row and row[0]:
            if ids.full("control", row[0]):
                define(found.controls, row[0], line)
            else:
                found.malformed.append((line, row[0], "control"))
    _collect_questions(ids, doc, found, define)
    return found


def _collect_questions(
    ids: Ids, doc: Doc, found: SpecIds, define: Callable[[dict[str, int], str, int], None]
) -> None:
    seen: dict[str, int] = {}
    for line, text in doc.bullets(S["questions"]):
        head = text.split(".", 1)[0]
        if ids.full("question", head):
            define(seen, head, line)
            found.questions.setdefault(head, (line, text))


# ------------------------------------------------------------------ checks --


@dataclass
class Outcome:
    check: str
    findings: list[Finding] = field(default_factory=list)
    not_run: str = ""
    # How many items the check inspected, for checks where zero means nothing
    # was checked at all: reported as not applicable, never as a pass.
    seen: int | None = None

    def count(self, m: Model, doc: Doc, items: int = 1) -> None:
        if m.in_scope(doc.rel):
            self.seen = (self.seen or 0) + items

    def add(self, rel: str, line: int, message: str, fix: str) -> None:
        self.findings.append(Finding(rel, line, self.check, message, fix))


def id_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def expand_tickets(value: str) -> set[str]:
    numbers: set[str] = set()
    for item in id_list(value):
        low, _, high = item.partition("-")
        if low.isdigit() and (not high or high.isdigit()):
            for number in range(int(low), int(high or low) + 1):
                numbers.add(f"{number:02d}")
    return numbers


def status_label(doc: Doc) -> str:
    return doc.value("Status").split(" ", 1)[0]


def template_of(owners: Owners, doc: Doc) -> Template | None:
    return {"spec": owners.spec, "ticket": owners.ticket, "requirements": owners.requirements}.get(
        doc.kind
    )


def check_status(m: Model, o: Outcome) -> None:
    for doc in m.of("spec", "ticket", "requirements", "wayticket"):
        found = doc.header("Status")
        if not found:
            continue
        line, value = found
        match = re.fullmatch(r"(\S+)(?: (\(.+\)))?", value)
        if not match or match.group(1) not in m.owners.labels:
            o.add(
                doc.rel,
                line,
                f"Status `{value}` không phải nhãn trong triage-labels.md.",
                f"dùng một trong {', '.join(sorted(m.owners.labels))};"
                " ghi chú chỉ được đặt trong ngoặc sau nhãn.",
            )


def check_headers(m: Model, o: Outcome) -> None:
    for doc in m.of("spec", "ticket", "requirements", "wayticket"):
        if doc.kind == "wayticket":
            _wayticket_headers(m, doc, o)
            continue
        template = template_of(m.owners, doc)
        assert template is not None
        prefix = template.title[2:].split("<", 1)[0]
        if doc.kind == "ticket":
            prefix = prefix.replace("NN", doc.ticket_number(), 1)
        if not doc.title or not doc.title[1].startswith(prefix) or doc.title[1] == prefix.strip():
            o.add(
                doc.rel,
                doc.title[0] if doc.title else 1,
                "Tiêu đề không đúng mẫu.",
                f"viết dòng đầu `# {prefix}<tiêu đề>`.",
            )
        present = [key for _, key, _ in doc.headers]
        order = [key for key in present if key in template.headers]
        expected = [key for key in template.headers if key in order]
        if order != expected:
            o.add(
                doc.rel,
                doc.headers[0][0] if doc.headers else 1,
                f"Dòng đầu sai thứ tự: {', '.join(order)}.",
                f"xếp theo {', '.join(template.headers)}.",
            )
        for key in template.headers:
            found = doc.header(key)
            if not found:
                if key not in OPTIONAL_HEADERS:
                    o.add(
                        doc.rel,
                        doc.title[0] if doc.title else 1,
                        f"Thiếu dòng `{key}:` ngay dưới tiêu đề.",
                        f"thêm `{key}:` theo mẫu {doc.kind}.",
                    )
                continue
            line, value = found
            match = re.fullmatch(GRAMMAR[doc.kind][key], value)
            if not match:
                o.add(
                    doc.rel,
                    line,
                    f"Giá trị `{key}: {value}` sai dạng.",
                    f"viết theo bảng Dòng đầu tệp của mẫu {doc.kind}.",
                )
            elif "area" in match.groupdict() and match.group("area") != doc.area:
                o.add(
                    doc.rel,
                    line,
                    f"Area `{match.group('area')}` khác thư mục `{doc.area}`.",
                    f"đổi thành `{doc.area}`.",
                )
            elif key == APPROVED_HEADER and value.startswith(DELEGATED) and not _approved(m, doc):
                o.add(
                    doc.rel,
                    line,
                    f"`{key}: {value}` mà area file không ghi Đạt ủy quyền duyệt {doc.kind}"
                    " từ ngày đó trở về trước.",
                    "chờ Đạt duyệt; dạng ủy quyền cần dòng `Ủy quyền duyệt: ...` của Đạt"
                    " ở mục Ủy quyền của area file.",
                )


def _day(text: str) -> tuple[int, int, int]:
    day, month, year = (int(part) for part in text.split("/"))
    return year, month, day


def _approved(m: Model, doc: Doc) -> bool:
    """Duyet holds Dat's word, or the delegated form backed by Dat's line in the area file.

    The delegated form counts only when the area file's delegation section holds
    `Uy quyen duyet: Dat, <kind>, tu <date>` for this kind of document, dated no
    later than the approval it backs: an agent cannot approve its own document on
    a delegation nobody wrote down.
    """
    value = doc.value(APPROVED_HEADER)
    if re.fullmatch(rf"Đạt {DATE}", value):
        return True
    delegated = re.fullmatch(rf"{DELEGATED} ({DATE})", value)
    return delegated is not None and _delegated_on(m, doc, delegated.group(1))


def _delegated_on(m: Model, doc: Doc, date: str) -> bool:
    """Whether the area file records Dat's delegation for this kind of document by `date`.

    One delegation covers a spec's `Duyet:` and the split of its tickets: a split
    approved by an agent on Dat's recorded word, never on a word nobody wrote.
    """
    area = m.doc(m.repo / PLANS / f"{doc.area}.md")
    for _, text in area.bullets(S["delegation"]) if area else []:
        line = re.fullmatch(DELEGATION, text)
        if not line or line.group("kind") != doc.kind:
            continue
        if _day(line.group("date")) <= _day(date):
            return True
    return False


def _wayticket_headers(m: Model, doc: Doc, o: Outcome) -> None:
    kind = doc.header("Type")
    if not kind or kind[1] not in m.owners.way_types:
        o.add(
            doc.rel,
            kind[0] if kind else 1,
            "Ticket wayfinder thiếu dòng `Type:` hợp lệ.",
            f"thêm `Type:` là một trong {', '.join(sorted(m.owners.way_types))}.",
        )
    if not doc.header("Status"):
        o.add(
            doc.rel,
            1,
            "Ticket wayfinder thiếu dòng `Status:`.",
            "thêm `Status:` (issue-tracker.md, Wayfinding).",
        )


def check_sections(m: Model, o: Outcome) -> None:
    for doc in m.of("spec", "ticket", "requirements"):
        template = template_of(m.owners, doc)
        assert template is not None
        _sections_against(doc, template.sections, o, strict=True)
    areas_planned = {doc.area for doc in m.of("requirements")}
    for doc in m.of("area"):
        if doc.area in areas_planned:
            _sections_against(doc, m.owners.area, o, strict=False)


def _sections_against(doc: Doc, rules: list[SectionRule], o: Outcome, strict: bool) -> None:
    names = [rule.name for rule in rules]
    seen: list[str] = []
    for sec in doc.sections:
        if sec.name in seen:
            o.add(doc.rel, sec.line, f"Mục `{sec.name}` lặp.", "gộp hai mục.")
        seen.append(sec.name)
        if strict and sec.name not in names:
            o.add(
                doc.rel,
                sec.line,
                f"Mục `{sec.name}` không có trong mẫu.",
                "đổi về tên mục của mẫu hoặc bỏ mục.",
            )
    known = [name for name in seen if name in names]
    if strict and known != sorted(known, key=names.index):
        o.add(
            doc.rel,
            doc.sections[0].line if doc.sections else 1,
            "Các mục không theo thứ tự của mẫu.",
            f"xếp theo: {', '.join(names)}.",
        )
    for rule in rules:
        present = doc.section(rule.name)
        if not present:
            if not rule.optional:
                o.add(
                    doc.rel,
                    1,
                    f"Thiếu mục bắt buộc `## {rule.name}`.",
                    "thêm mục theo mẫu; không có gì thì viết `Không có.`.",
                )
            continue
        text = [
            line.strip()
            for _, line in doc.body(rule.name)
            if line.strip() and not line.strip().startswith("<!--")
        ]
        if not text and not rule.may_be_empty:
            o.add(
                doc.rel,
                present.line,
                f"Mục `{rule.name}` trống.",
                "viết nội dung, hoặc `Không có.`; mục tùy chọn thì bỏ hẳn.",
            )
        if text and re.fullmatch(r"(?i)(?:N/A|Không áp dụng)\.?", " ".join(text)):
            o.add(
                doc.rel,
                present.line,
                f"Mục `{rule.name}` chỉ ghi N/A.",
                "mục tùy chọn thì bỏ hẳn; mục bắt buộc thì viết `Không có.`.",
            )


def check_placeholders(m: Model, o: Outcome) -> None:
    for doc in m.of("spec", "ticket", "requirements"):
        template = template_of(m.owners, doc)
        assert template is not None
        for index, line in enumerate(doc.lines):
            if doc.fenced[index]:
                continue
            loose = code_free(line)
            hits = [token for token in template.loose_tokens if token in loose]
            hits += [token for token in template.span_tokens if token in line]
            hits += re.findall(r"(?<!\w)(?:TBD|TODO|FIXME|XXX)(?!\w)|\?\?\?", loose)
            if line.strip().startswith(("<!-- TUY CHON", "<!-- CO THE RONG")):
                hits.append(line.strip())
            if hits:
                o.add(
                    doc.rel,
                    index + 1,
                    f"Còn chỗ chưa điền: {', '.join(sorted(set(hits)))}.",
                    "thay bằng nội dung thật; xóa dòng chú thích của mẫu.",
                )


def check_ids(m: Model, o: Outcome) -> None:
    o.seen = 0
    owners_of_control: dict[tuple[str, str], str] = {}
    for doc in m.of("spec", "requirements"):
        found = m.ids_of(doc)
        o.count(m, doc, len(found.defined()) + len(found.requirements) + len(found.malformed))
        for line, key in found.duplicates:
            o.add(
                doc.rel,
                line,
                f"Mã `{key}` định nghĩa hai lần.",
                "đặt mã mới; mã đã dùng không dùng lại.",
            )
        for line, text, what in found.malformed:
            fixes = {
                "requirement": "viết `### R<n> — <tên ngắn>` (gạch dài).",
                "criterion": "viết `- R<n>.<m> <câu EARS-VN>`.",
                "parent": "đánh số tiêu chí theo yêu cầu chứa nó.",
                "control": "mã kiểm soát là 2-4 chữ hoa rồi số, không dùng YC, KQ.",
            }
            o.add(doc.rel, line, f"Mã sai dạng: `{text[:60]}`.", fixes[what])
        if doc.kind == "spec":
            for req, line in found.requirements.items():
                if not any(key.split(".")[0] == req for key in found.criteria):
                    o.add(
                        doc.rel, line, f"`{req}` không có tiêu chí nào.", f"thêm `- {req}.1 ...`."
                    )
            for control, line in found.controls.items():
                where = (doc.area, control)
                if where in owners_of_control and owners_of_control[where] != doc.rel:
                    o.add(
                        doc.rel,
                        line,
                        f"Mã kiểm soát `{control}` đã dùng ở {owners_of_control[where]}.",
                        "dùng tiền tố riêng của spec này.",
                    )
                owners_of_control.setdefault(where, doc.rel)


def check_refs(m: Model, o: Outcome) -> None:
    o.seen = 0
    ids = m.owners.ids
    for ticket in m.of("ticket"):
        spec = m.spec_of(ticket)
        found = ticket.header(REQ_HEADER)
        if not found or found[1].startswith("không ("):
            continue
        if not spec:
            o.count(m, ticket)
            o.add(
                ticket.rel,
                found[0],
                f"`{REQ_HEADER}: {found[1]}` mà thư mục không có spec.md.",
                "ticket không có spec ghi `Yêu cầu: không (<lý do>)`.",
            )
            continue
        defined = m.ids_of(spec).defined()
        o.count(m, ticket, len(id_list(found[1])))
        for key in id_list(found[1]):
            if key not in defined:
                o.add(
                    ticket.rel,
                    found[0],
                    f"`{key}` không có trong {spec.rel}.",
                    "dẫn mã R<n>.<m>, G<n> hoặc mã kiểm soát của spec cùng thư mục.",
                )
    for spec in m.of("spec"):
        spec_ids = m.ids_of(spec)
        header, rows = spec.table(S["controls"])
        if REQ_HEADER in header:
            column = header.index(REQ_HEADER)
            for line, row in rows:
                cited = ids.find("criterion", row[column]) + ids.find("unchanged", row[column])
                o.count(m, spec, len(cited))
                for key in cited:
                    if key not in spec_ids.criteria and key not in spec_ids.unchanged:
                        o.add(
                            spec.rel,
                            line,
                            f"`{key}` trong Kiểm soát không có trong Mục tiêu.",
                            "sửa mã cho đúng tiêu chí nó canh.",
                        )
        header, rows = spec.table(S["out"])
        if OUT_COLUMN in header:
            for line, row in rows:
                head = re.match(r"^([A-Za-z0-9.]+):", row[header.index(OUT_COLUMN)])
                if (
                    head
                    and ids.full("criterion", head.group(1))
                    and head.group(1) not in spec_ids.criteria
                ):
                    o.add(
                        spec.rel,
                        line,
                        f"`{head.group(1)}` không có trong Mục tiêu.",
                        "sửa mã ở đầu ô Việc.",
                    )
    adrs = adr_index(m)[0]
    for doc in m.of("spec", "ticket", "requirements"):
        for index, text in enumerate(doc.lines):
            if doc.fenced[index]:
                continue
            for ref in ids.find("cross-ref", text):
                o.count(m, doc)
                if not _cross_ref_ok(m, doc, ref):
                    o.add(
                        doc.rel,
                        index + 1,
                        f"`{ref}` không trỏ tới tiêu chí nào.",
                        "sửa slug, area hoặc mã.",
                    )
            for match in re.finditer(
                rf"(?<![A-Za-z0-9])({ids.raw['adr']})(?![0-9])( \(([^)]*)\))?", text
            ):
                number = match.group(1)[4:]
                o.count(m, doc)
                status = (match.group(3) or "").split(" ", 1)[0]
                if number not in adrs:
                    o.add(
                        doc.rel,
                        index + 1,
                        f"{match.group(1)} không có tệp ADR.",
                        "sửa số hoặc viết ADR trước.",
                    )
                elif not status:
                    o.add(
                        doc.rel,
                        index + 1,
                        f"{match.group(1)} thiếu trạng thái trong ngoặc.",
                        f"viết `{match.group(1)} ({adrs[number][1]})`.",
                    )
                elif status != adrs[number][1]:
                    o.add(
                        doc.rel,
                        index + 1,
                        f"{match.group(1)} ghi `{status}`, tệp ADR ghi `{adrs[number][1]}`.",
                        f"sửa thành `{adrs[number][1]}`.",
                    )


def _cross_ref_ok(m: Model, doc: Doc, ref: str) -> bool:
    target, _, key = ref.partition(":")
    area, _, slug = target.rpartition("/")
    spec = m.doc(m.repo / PLANS / (area or doc.area) / slug / "spec.md")
    return spec is not None and key in m.ids_of(spec).criteria


def check_markers(m: Model, o: Outcome) -> None:
    ids = m.owners.ids
    for doc in m.of("spec", "requirements"):
        open_questions = m.ids_of(doc).questions
        found: list[tuple[int, str]] = []
        for index, text in enumerate(doc.lines):
            if not doc.fenced[index]:
                found += [(index + 1, marker) for marker in ids.find("marker", text)]
        if len(found) > 3:
            o.add(
                doc.rel,
                found[3][0],
                f"{len(found)} đánh dấu [CAN LAM RO], quá 3.",
                "hỏi Đạt để đóng bớt, hoặc tách spec.",
            )
        for line, marker in found:
            question = marker.rsplit(" ", 1)[-1].rstrip("]")
            if question not in open_questions:
                o.add(
                    doc.rel,
                    line,
                    f"{marker} không trỏ tới câu hỏi còn mở nào.",
                    f"thêm `- {question}. ...` vào Câu hỏi còn mở, hoặc bỏ đánh dấu.",
                )


def check_questions(m: Model, o: Outcome) -> None:
    q = m.owners.ids.raw["question"]
    shape = rf"({q})\. .+\? Chủ: [^.]+\. (?:Chặn|Không đổi): .+\."
    for doc in m.of("spec", "requirements"):
        for line, text in doc.bullets(S["questions"]):
            if not re.fullmatch(shape, text):
                o.add(
                    doc.rel,
                    line,
                    f"Câu hỏi sai dạng: `{text[:60]}`.",
                    "viết `- Q<n>. <câu hỏi>? Chủ: <ai>. Chặn: <mã>.` hoặc `Không đổi: ...`.",
                )


def _ticket_graph(m: Model) -> dict[str, list[tuple[int, str, Doc | None]]]:
    graph: dict[str, list[tuple[int, str, Doc | None]]] = {}
    pending = list(m.of("ticket", "wayticket"))
    while pending:
        doc = pending.pop()
        if doc.rel in graph:
            continue
        found = doc.header("Blocked by")
        edges: list[tuple[int, str, Doc | None]] = []
        if found:
            for item in id_list(found[1]):
                if re.fullmatch(r"[0-9]{2}", item):
                    matches = sorted((doc.path.parent).glob(f"{item}-*.md"))
                    target = m.doc(matches[0]) if matches else None
                else:
                    target = m.doc(m.repo / item) if item.endswith(".md") else None
                    if target and target.kind not in ("ticket", "wayticket"):
                        target = None
                edges.append((found[0], item, target))
                if target is not None:
                    pending.append(target)
        graph[doc.rel] = edges
    return graph


def check_blocked_by(m: Model, o: Outcome) -> None:
    graph = _ticket_graph(m)
    for doc in m.of("ticket", "wayticket"):
        for line, item, target in graph.get(doc.rel, []):
            if target is None:
                o.add(
                    doc.rel,
                    line,
                    f"Blocked by `{item}` không trỏ tới ticket nào.",
                    "dùng `NN` cùng thư mục hoặc đường dẫn từ gốc repo tới tệp ticket.",
                )
                continue
            if (
                doc.kind == "ticket"
                and re.fullmatch(r"[0-9]{2}", item)
                and item >= doc.ticket_number()
            ):
                o.add(
                    doc.rel,
                    line,
                    f"Ticket {doc.ticket_number()} bị chặn bởi {item}, không nhỏ hơn.",
                    "phụ thuộc chỉ trỏ ngược: đánh số lại hoặc đảo phụ thuộc.",
                )
            if status_label(target) == "wontfix":
                o.add(
                    doc.rel,
                    line,
                    f"Ticket chặn `{item}` ở wontfix.",
                    "bỏ phụ thuộc hoặc đổi ticket chặn.",
                )
    reported: set[str] = set()

    def visit(rel: str, trail: list[str]) -> None:
        if rel in trail:
            cycle = trail[trail.index(rel) :]
            key = min(cycle)
            if key not in reported:
                reported.add(key)
                o.add(
                    rel,
                    1,
                    f"Vòng phụ thuộc: {' -> '.join([*cycle, rel])}.",
                    "bỏ một cạnh Blocked by trong vòng.",
                )
            return
        for _, _, target in graph.get(rel, []):
            if target is not None:
                visit(target.rel, [*trail, rel])

    for rel in sorted(graph):
        visit(rel, [])


def check_numbering(m: Model, o: Outcome) -> None:
    folders = {doc.path.parent for doc in m.of("ticket", "wayticket")}
    for folder in sorted(folders):
        numbers: dict[str, str] = {}
        rel = folder.relative_to(m.repo).as_posix()
        for path in sorted(folder.glob("*.md")):
            match = re.fullmatch(r"([0-9]{2})-[a-z0-9]+(?:-[a-z0-9]+)*\.md", path.name)
            if not match:
                o.add(
                    f"{rel}/{path.name}",
                    1,
                    f"Tên tệp `{path.name}` sai dạng.",
                    "đặt tên `NN-<slug>.md`, slug chữ thường, số và gạch nối.",
                )
                continue
            if match.group(1) in numbers:
                o.add(
                    f"{rel}/{path.name}",
                    1,
                    f"Số {match.group(1)} trùng với {numbers[match.group(1)]}.",
                    "đánh số tiếp theo, không trùng.",
                )
            numbers.setdefault(match.group(1), path.name)
        if numbers and "01" not in numbers:
            o.add(rel, 1, "Ticket không đếm từ 01.", "đánh số từ `01` trong mỗi thư mục.")


def check_layout(m: Model, o: Outcome) -> None:
    for doc in m.of("misplaced"):
        o.add(
            doc.rel,
            1,
            "Tệp ngoài layout của issue-tracker.md.",
            "spec, map ở `<area>/<feature>/`; ticket ở `<area>/<feature>/issues/NN-<slug>.md`.",
        )


def check_controls(m: Model, o: Outcome) -> None:
    ids = m.owners.ids
    for spec in m.of("spec"):
        sec = spec.section(S["controls"])
        if not sec:
            continue
        header, rows = spec.table(S["controls"])
        if not header:
            text = " ".join(line.strip() for _, line in spec.body(S["controls"]) if line.strip())
            if not re.fullmatch(r"Không có\. \S.*", text):
                o.add(
                    spec.rel,
                    sec.line,
                    "Kiểm soát không có bảng và không ghi `Không có.` kèm lý do.",
                    "thêm bảng theo mẫu, hoặc `Không có. <lý do>`.",
                )
            continue
        missing = [column for column in CONTROL_COLUMNS if column not in header]
        if missing:
            o.add(
                spec.rel,
                sec.line,
                f"Bảng Kiểm soát thiếu cột {', '.join(missing)}.",
                "dùng đúng các cột của mẫu.",
            )
            continue
        refs, negative = header.index(CONTROL_COLUMNS[1]), header.index(CONTROL_COLUMNS[2])
        for line, row in rows:
            cell = row[refs] if refs < len(row) else ""
            if not ids.find("criterion", cell) and not ids.find("unchanged", cell):
                o.add(
                    spec.rel,
                    line,
                    f"Kiểm soát `{row[0]}` không nêu tiêu chí nó canh.",
                    "ghi R<n>.<m> hoặc G<n> vào cột Yêu cầu.",
                )
            test = row[negative] if negative < len(row) else ""
            if len(test.strip(" -")) < 3:
                o.add(
                    spec.rel,
                    line,
                    f"Kiểm soát `{row[0]}` không có test âm.",
                    "nói gọi gì, khẳng định gì; test đỏ khi gỡ kiểm soát.",
                )


def check_coverage(m: Model, o: Outcome) -> None:
    o.seen = 0
    ids = m.owners.ids
    for spec in m.of("spec"):
        tickets = [t for t in m.tickets_of(spec) if t.kind == "ticket"]
        if not tickets:
            continue
        covered: set[str] = set()
        for ticket in tickets:
            value = ticket.value(REQ_HEADER)
            if not value.startswith("không ("):
                covered |= set(id_list(value))
        header, rows = spec.table(S["out"])
        if OUT_COLUMN in header:
            for _, row in rows:
                head = re.match(r"^([A-Za-z0-9.]+):", row[header.index(OUT_COLUMN)])
                if head:
                    covered.add(head.group(1))
        o.count(m, spec, len(m.ids_of(spec).live()))
        for key, line in m.ids_of(spec).live().items():
            if key not in covered:
                o.add(
                    spec.rel,
                    line,
                    f"`{key}` không có ticket nào và không ở Ngoài phạm vi.",
                    "thêm vào dòng Yêu cầu của một ticket, hoặc `<mã>: ...` ở ô Việc.",
                )
    for doc in m.of("requirements"):
        served: set[str] = set()
        area = m.doc(m.repo / PLANS / f"{doc.area}.md")
        if area:
            header, rows = area.table(S["roadmap"])
            if ROADMAP_COLUMN in header:
                for _, row in rows:
                    served |= set(ids.find("yc", row[header.index(ROADMAP_COLUMN)]))
        for _, text in doc.bullets(S["notdo"]):
            head = re.match(r"^([A-Za-z0-9]+):", text)
            if head:
                served.add(head.group(1))
        o.count(m, doc, len(m.ids_of(doc).criteria))
        for key, line in m.ids_of(doc).criteria.items():
            if key not in served and key not in m.ids_of(doc).withdrawn:
                o.add(
                    doc.rel,
                    line,
                    f"`{key}` không có dòng Lộ trình nào và không ở Không làm.",
                    f"thêm `{key}` vào cột Yêu cầu cấp area, hoặc `- {key}: ...` ở Không làm.",
                )


def check_acceptance(m: Model, o: Outcome) -> None:
    for ticket in m.of("ticket"):
        accept = ticket.section(S["accept"])
        if not accept:
            continue
        value = ticket.value(REQ_HEADER)
        cited = None if not value or value.startswith("không (") else set(id_list(value))
        led: set[str] = set()
        boxes = ticket.bullets(S["accept"])
        done: list[int] = []
        for line, text in boxes:
            box = re.fullmatch(r"\[[ xX]\] (.*)", text)
            if not box:
                o.add(
                    ticket.rel,
                    line,
                    "Dòng không phải ô `- [ ]`.",
                    "viết mỗi tiêu chí là một ô `- [ ]`.",
                )
                continue
            body = box.group(1)
            if body.startswith("Xong:"):
                done.append(line)
                if not re.fullmatch(r"Xong: `[^`]+` xanh\.", body):
                    o.add(
                        ticket.rel,
                        line,
                        "Dòng Xong sai dạng.",
                        "viết `- [ ] Xong: `<lệnh>` xanh.`.",
                    )
                continue
            if cited is None:
                continue
            lead = re.match(r"^([A-Za-z0-9.]+)(?: \(([A-Za-z0-9]+)\))?:", body)
            kinds = ("criterion", "unchanged", "control")
            if lead and not any(m.owners.ids.full(kind, lead.group(1)) for kind in kinds):
                lead = None
            if not lead:
                o.add(
                    ticket.rel,
                    line,
                    "Tiêu chí không bắt đầu bằng mã nó chứng minh.",
                    "viết `- [ ] R1.2 (TM1): ...`.",
                )
                continue
            for key in (lead.group(1), lead.group(2)):
                if key and key not in cited:
                    o.add(
                        ticket.rel,
                        line,
                        f"`{key}` không có ở dòng Yêu cầu.",
                        "thêm mã vào dòng Yêu cầu hoặc sửa mã dẫn đầu.",
                    )
                elif key:
                    led.add(key)
        if len(done) != 1:
            o.add(
                ticket.rel,
                accept.line,
                f"Có {len(done)} dòng Xong, cần đúng một.",
                "kết thúc bằng một `- [ ] Xong: `<lệnh>` xanh.`.",
            )
        elif boxes and done[0] != boxes[-1][0]:
            o.add(ticket.rel, done[0], "Dòng Xong không ở cuối.", "chuyển dòng Xong xuống cuối.")
        for key in sorted((cited or set()) - led):
            req_line = ticket.header(REQ_HEADER)
            o.add(
                ticket.rel,
                req_line[0] if req_line else 1,
                f"`{key}` không có tiêu chí chấp nhận nào.",
                f"thêm `- [ ] {key}: ...`.",
            )


def check_ready(m: Model, o: Outcome) -> None:
    for doc in m.of("spec", "requirements"):
        if status_label(doc) != "ready-for-agent":
            continue
        line = doc.header("Status")
        at = line[0] if line else 1
        if not doc.value(READY_HEADER).startswith("ĐẠT "):
            o.add(
                doc.rel,
                at,
                "ready-for-agent khi Sẵn sàng chưa là ĐẠT.",
                "chạy checking-plan-readiness, hoặc hạ về needs-triage.",
            )
        if not _approved(m, doc):
            o.add(
                doc.rel,
                at,
                "ready-for-agent khi chưa có Duyệt hợp lệ.",
                "chờ Đạt duyệt, hoặc hạ về needs-triage.",
            )
        if any(m.owners.ids.find("marker", text) for text in doc.lines):
            o.add(doc.rel, at, "ready-for-agent khi còn [CAN LAM RO].", "đóng câu hỏi trước.")
        for _, (qline, text) in m.ids_of(doc).questions.items():
            if "Không đổi:" not in text:
                o.add(
                    doc.rel,
                    qline,
                    "ready-for-agent khi còn câu hỏi chặn.",
                    "trả lời câu hỏi, hoặc ghi `Không đổi: ...`.",
                )
    for ticket in m.of("ticket"):
        if status_label(ticket) != "ready-for-agent":
            continue
        spec = m.spec_of(ticket)
        number = ticket.ticket_number()
        line = ticket.header("Status")
        at = line[0] if line else 1
        if spec is None:
            _ready_without_spec(ticket, at, o)
            continue
        readiness = spec.value(READY_HEADER)
        listed = re.search(rf"; ticket ({TICKET_SET})\)$", readiness)
        if (
            not readiness.startswith("ĐẠT ")
            or not listed
            or number not in expand_tickets(listed.group(1))
        ):
            o.add(
                ticket.rel,
                at,
                f"Ticket {number} ready-for-agent mà spec chưa ĐẠT với ticket này.",
                "chạy checking-plan-readiness gồm ticket này, hoặc hạ về needs-triage.",
            )
        if not _approved(m, spec):
            o.add(ticket.rel, at, "Spec cùng thư mục chưa được duyệt.", "chờ Đạt duyệt spec.")
        approved: set[str] = set()
        for _, text in spec.bullets(S["decisions"]):
            split = re.match(
                rf"({DATE}) \((Đạt|{DELEGATED})\): Duyệt cách chia ticket ({TICKET_SET})\.", text
            )
            if split and (split.group(2) == "Đạt" or _delegated_on(m, spec, split.group(1))):
                approved |= expand_tickets(split.group(3))
        if number not in approved:
            o.add(
                ticket.rel,
                at,
                f"Không có dòng Quyết định `Duyệt cách chia ticket` gồm {number}.",
                "chờ Đạt duyệt cách chia ticket.",
            )


def _ready_without_spec(ticket: Doc, at: int, o: Outcome) -> None:
    """A ticket with no spec (tier A) is ready on Dat's approval and the gate's pass."""
    comments = [text for _, text in ticket.bullets(S["comments"])]
    if not any(re.fullmatch(TICKET_APPROVED, text) for text in comments):
        o.add(
            ticket.rel,
            at,
            "Ticket không có spec ready-for-agent mà Comments không có dòng Đạt duyệt.",
            "chờ Đạt: `- <yyyy-mm-dd> (Đạt): Duyệt ticket.`, hoặc hạ về needs-triage.",
        )
    if not any(re.fullmatch(TICKET_PASSED, text) for text in comments):
        o.add(
            ticket.rel,
            at,
            "Ticket không có spec ready-for-agent mà Comments không có dòng gate ĐẠT.",
            "chạy checking-plan-readiness trên ticket, hoặc hạ về needs-triage.",
        )


# `path:line` is an anchor only when the path has a folder or a file extension, so
# `localhost:8000` and `10:30` in a code span are not read as citations.
ANCHOR = re.compile(r"(?P<path>[^\s:`]*):(?P<a>[0-9]+)(?:-(?P<b>[0-9]+))?")
ANCHOR_PATH = re.compile(r".*/.*|.*\.[A-Za-z0-9]+")


def _anchors(m: Model, doc: Doc, line: int, text: str, o: Outcome) -> int:
    count = 0
    for span in spans(text):
        match = ANCHOR.fullmatch(span)
        if not match or not ANCHOR_PATH.fullmatch(match.group("path")):
            continue
        count += 1
        path = match.group("path")
        target = m.repo / path
        first, last = int(match.group("a")), int(match.group("b") or match.group("a"))
        if "/" not in path and not target.is_file():
            o.add(
                doc.rel,
                line,
                f"Neo `{span}` không có đường dẫn từ gốc repo.",
                "viết `<đường dẫn từ gốc repo>:<dòng>`.",
            )
        elif not target.is_file():
            o.add(
                doc.rel, line, f"Neo `{span}`: tệp không tồn tại.", "sửa đường dẫn (từ gốc repo)."
            )
        else:
            total = len(target.read_bytes().splitlines())
            if first < 1 or first > last or last > total:
                o.add(
                    doc.rel,
                    line,
                    f"Neo `{span}`: tệp chỉ có {total} dòng.",
                    "đọc lại tệp và sửa số dòng.",
                )
    return count


def check_anchors(m: Model, o: Outcome) -> None:
    for spec in m.of("spec"):
        sec = spec.section(S["current"])
        if sec:
            stamp = rf"\(đã kiểm ở `[0-9a-f]{{7,40}}` ngày {DATE}\)"
            if not re.search(stamp, sec.heading):
                o.add(
                    spec.rel,
                    sec.line,
                    "Tiêu đề Hiện trạng thiếu dấu kiểm sha và ngày.",
                    "viết `## Hiện trạng (đã kiểm ở `<sha>` ngày <d/m/yyyy>)`.",
                )
            for line, text in spec.bullets(S["current"]):
                if _anchors(m, spec, line, text, o) == 0:
                    o.add(
                        spec.rel,
                        line,
                        "Sự thật không có neo `path:line`.",
                        "thêm neo, mỗi neo một code span.",
                    )
                if not re.search(rf"(?:{'|'.join(LABELS_DONE)}):", code_free(text)):
                    o.add(
                        spec.rel,
                        line,
                        "Sự thật không có nhãn.",
                        f"thêm một trong {', '.join(LABELS_DONE)}.",
                    )
        for index, text in enumerate(spec.lines):
            if spec.fenced[index] or not text.startswith("Trước đây:"):
                continue
            if _anchors(m, spec, index + 1, text, o) == 0:
                o.add(
                    spec.rel,
                    index + 1,
                    "Dòng Trước đây không có neo.",
                    "thêm `<path>:<line>` của hành vi cũ.",
                )
    for ticket in m.of("ticket"):
        for line, text in ticket.bullets(S["source"]):
            _anchors(m, ticket, line, text, o)


def check_links(m: Model, o: Outcome) -> None:
    rx = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
    for doc in m.docs:
        for index, line in enumerate(doc.lines):
            if doc.fenced[index]:
                continue
            for target in rx.findall(code_free(line)):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                plain = target.split("#", 1)[0].strip("<>")
                base = m.repo if plain.startswith("/") else doc.path.parent
                if plain and not (base / plain.lstrip("/")).exists():
                    o.add(
                        doc.rel,
                        index + 1,
                        f"Link `{target}` không tới tệp nào.",
                        "sửa đường dẫn tương đối từ thư mục của tệp.",
                    )


def check_ticket_list(m: Model, o: Outcome) -> None:
    wanted = m.owners.spec.rule(S["tickets"])
    for spec in m.of("spec"):
        header, _ = spec.table(S["tickets"])
        if header and wanted and header != wanted.table:
            sec = spec.section(S["tickets"])
            o.add(
                spec.rel,
                sec.line if sec else 1,
                f"Danh sách ticket có cột {', '.join(header)}.",
                f"chỉ giữ {', '.join(wanted.table)}: ticket là chủ của Status và Blocked by.",
            )


def adr_index(m: Model) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]], list[Path]]:
    """Number -> (file, status first word); duplicates; the glossary files."""
    dirs = [m.repo / "docs/adr", *sorted((m.repo / "packages/python").glob("*/docs/adr"))]
    glossaries: list[Path] = []
    context_map = m.repo / "CONTEXT-MAP.md"
    if context_map.is_file():
        for line in read(context_map).splitlines():
            row = cells(line) if line.startswith("|") else []
            for cell in row:
                for span in spans(cell):
                    if span.endswith("CONTEXT.md"):
                        glossaries.append(m.repo / span)
                    elif span.rstrip("/").endswith("adr") and "<" not in span:
                        dirs.append(m.repo / span)
    index: dict[str, tuple[str, str]] = {}
    duplicates: list[tuple[str, str]] = []
    for folder in dict.fromkeys(path.resolve() for path in dirs if path.is_dir()):
        for path in sorted(folder.glob("*.md")):
            match = re.match(r"^([0-9]{4})-", path.name)
            if not match:
                continue
            rel = path.relative_to(m.repo.resolve()).as_posix()
            text = read(path)
            front = re.match(r"^---\n(.*?)\n---", text, re.S)
            status = (
                re.search(r"^status:\s*['\"]?([A-Za-z]+)", front.group(1), re.M) if front else None
            )
            if match.group(1) in index:
                duplicates.append((rel, index[match.group(1)][0]))
            else:
                index[match.group(1)] = (rel, status.group(1) if status else "")
    return index, duplicates, glossaries


def check_adr(m: Model, o: Outcome) -> None:
    index, duplicates, _ = adr_index(m)
    for rel, first in duplicates:
        o.add(rel, 1, f"Số ADR trùng với {first}.", "lấy số từ khối dành riêng trong area file.")
    for rel, status in index.values():
        if status not in m.owners.adr_statuses:
            o.add(
                rel,
                1,
                f"status `{status}` không thuộc {', '.join(sorted(m.owners.adr_statuses))}.",
                "sửa front matter `status:` theo docs/agents/domain.md.",
            )


def check_stray(m: Model, o: Outcome) -> None:
    plans = PLANS.parts
    for dirpath, dirnames, filenames in os.walk(m.repo):
        here = Path(dirpath).relative_to(m.repo)
        for name in list(dirnames):
            rel = (here / name).as_posix()
            if name in PRUNE:
                dirnames.remove(name)
            elif name in STRAY_DIRS or name.startswith("_bmad"):
                o.add(
                    rel + "/",
                    1,
                    f"Tracker lạ `{name}/`.",
                    "chuyển nội dung vào .claude/plans/ (issue-tracker.md) và xóa thư mục.",
                )
                dirnames.remove(name)
            elif name == "specs":
                for child in sorted((m.repo / rel).iterdir()):
                    if child.is_dir() and re.match(r"^[0-9]{3}-", child.name):
                        o.add(
                            f"{rel}/{child.name}/",
                            1,
                            "Thư mục spec kiểu `specs/NNN-*`.",
                            "viết spec ở .claude/plans/<area>/<feature>/spec.md.",
                        )
        inside = here.parts[: len(plans)] == plans
        for name in filenames:
            rel = (here / name).as_posix()
            if name.startswith("GLOSSARY") and name.endswith(".md"):
                o.add(
                    rel,
                    1,
                    "Glossary riêng ngoài CONTEXT.md.",
                    "chuyển thuật ngữ vào CONTEXT.md mà CONTEXT-MAP.md nêu.",
                )
            elif not inside and (
                (name in ("spec.md", "map.md") and _tracker_file(Path(dirpath), name))
                or (here.name == "issues" and re.match(r"^[0-9]{2}-.*\.md$", name))
            ):
                o.add(
                    rel,
                    1,
                    "Spec, map hay ticket ngoài .claude/plans/.",
                    "chuyển vào .claude/plans/<area>/<feature>/.",
                )


def _tracker_file(folder: Path, name: str) -> bool:
    """A spec.md or map.md is a tracker file when it has a Status line or tickets beside it."""
    if (folder / "issues").is_dir():
        return True
    try:
        head = read(folder / name).splitlines()[:8]
    except (OSError, UnicodeDecodeError):
        return True
    return any(line.startswith("Status: ") for line in head)


def emoji_ranges(path: Path | None) -> list[tuple[int, int]] | None:
    if path is None or not path.is_file():
        return None
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "EMOJI_RANGES" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return [(int(low), int(high)) for low, high in value]
    return None


def check_emoji(m: Model, o: Outcome) -> None:
    ranges = emoji_ranges(m.hygiene)
    if ranges is None:
        o.not_run = f"không đọc được EMOJI_RANGES từ {m.hygiene or HYGIENE_FILE}"
        return
    docs = list(m.docs)
    index, _, glossaries = adr_index(m)
    extra = [m.repo / rel for rel, _ in index.values()] + [g for g in glossaries if g.is_file()]
    docs += [doc for doc in (m.doc(path) for path in extra) if doc is not None]
    for doc in docs:
        for number, line in enumerate(doc.lines, 1):
            if any(low <= ord(char) <= high for char in line for low, high in ranges):
                o.add(doc.rel, number, "Emoji trong tệp (check_hygiene.py).", "thay bằng chữ.")


def _lint_lines(m: Model) -> Iterator[tuple[Doc, int, str, str, bool]]:
    for doc in m.of("spec", "requirements"):
        found = m.ids_of(doc)
        for key, text in found.criterion_text.items():
            if key not in found.withdrawn and key not in found.table_rows:
                yield doc, found.criteria[key], key, text, False
        for key, text in found.unchanged_text.items():
            if key not in found.withdrawn:
                yield doc, found.unchanged[key], key, text, True


def check_ears(m: Model, o: Outcome) -> None:
    o.seen = 0
    keywords = sorted(m.owners.keywords, key=len, reverse=True)
    rx = re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(k) for k in keywords)})(?!\w)")
    not_subject = [k for k, role in m.owners.keywords.items() if role == "not-subject"]
    for doc, line, key, text, is_kept in _lint_lines(m):
        o.count(m, doc)
        plain = code_free(text)
        hits = [
            (match.start(), m.owners.keywords[match.group(0)], match.group(0))
            for match in rx.finditer(plain)
        ]
        modals = [hit for hit in hits if hit[1] in ("modal", "keep")]
        problems: list[str] = []
        if len(modals) != 1:
            problems.append(f"{len(modals)} modal, cần đúng một")
        keeps = any(hit[1] == "keep" for hit in hits)
        if keeps != is_kept:
            problems.append("PHẢI TIẾP TỤC chỉ và luôn ở dòng G")
        pending = 0
        for _, role, word in hits:
            if word == IF_KEYWORD:
                pending += 1
            elif role == "then":
                pending = max(pending - 1, 0) if pending else -99
        if pending:
            problems.append("NẾU thiếu THÌ" if pending > 0 else "THÌ không có NẾU")
        for start, _, _ in modals[:1]:
            before = plain[:start].rstrip()
            if any(re.search(rf"(?<!\w){re.escape(w)}$", before, re.I) for w in not_subject):
                problems.append("chủ thể không được là " + ", ".join(not_subject))
        if problems:
            o.add(
                doc.rel,
                line,
                f"{key}: {'; '.join(problems)}.",
                "viết lại theo ears-vn.md: một chủ thể, một modal.",
            )


def blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def check_vague(m: Model, o: Outcome) -> None:
    o.seen = 0
    flags = re.IGNORECASE
    words = sorted(m.owners.vague, key=len, reverse=True)
    rx = re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(w) for w in words)})(?!\w)", flags)
    exceptions = sorted(m.owners.vague_exceptions, key=len, reverse=True)
    skip = (
        re.compile(rf"(?<!\w)(?:{'|'.join(re.escape(w) for w in exceptions)})(?!\w)", flags)
        if exceptions
        else None
    )
    for doc, line, key, text, _ in _lint_lines(m):
        o.count(m, doc)
        # A cross-reference is a name, not prose: `support-access:R1.2` holds no vague word.
        plain = m.owners.ids.pattern("cross-ref").sub(blank, code_free(text))
        if skip:
            plain = skip.sub(blank, plain)
        hits = rx.findall(plain)
        if hits:
            o.add(
                doc.rel,
                line,
                f"{key}: từ mơ hồ {', '.join(hits)}.",
                "thay bằng con số, thao tác hay kiểm soát có tên.",
            )


def _resource(span: str) -> str | None:
    text = span.strip()
    route = re.fullmatch(r"(?:(?:GET|POST|PUT|PATCH|DELETE) )?(/[A-Za-z0-9{}_./-]+)", text)
    if route:
        return route.group(1)
    if "migrations/" in text or text.startswith("configs/"):
        return text
    table = re.fullmatch(r"[a-z_][a-z0-9_]*\.([a-z_][a-z0-9_]*)", text)
    if table and table.group(1) not in FILE_SUFFIXES:
        return text
    return None


def check_collision(m: Model, o: Outcome) -> None:
    o.seen = 0
    graph = _ticket_graph(m)

    def reach(rel: str) -> set[str]:
        seen: set[str] = set()
        stack = [rel]
        while stack:
            for _, _, target in graph.get(stack.pop(), []):
                if target is not None and target.rel not in seen:
                    seen.add(target.rel)
                    stack.append(target.rel)
        return seen

    folders: dict[Path, list[Doc]] = {}
    for ticket in m.of("ticket"):
        folders.setdefault(ticket.path.parent, []).append(ticket)
    for tickets in folders.values():
        tickets.sort(key=lambda t: t.rel)
        touches = {
            t.rel: {r for _, line in t.body(S["work"]) for s in spans(line) if (r := _resource(s))}
            for t in tickets
        }
        for i, first in enumerate(tickets):
            for second in tickets[i + 1 :]:
                o.count(m, second)
                if second.rel in reach(first.rel) or first.rel in reach(second.rel):
                    continue
                shared = sorted(touches[first.rel] & touches[second.rel])
                if shared:
                    o.add(
                        second.rel,
                        1,
                        f"Chạm chung {', '.join(shared)} với {first.path.name}, không phụ thuộc.",
                        "thêm Blocked by, hoặc dựng phần chung ở ticket sớm nhất.",
                    )


Runner = Callable[[Model, Outcome], None]
REPO_WIDE: tuple[str, ...] = ()
CHECKS: tuple[tuple[str, bool, tuple[str, ...], Runner], ...] = (
    ("status", False, ("spec", "ticket", "requirements", "wayticket"), check_status),
    ("headers", False, ("spec", "ticket", "requirements", "wayticket"), check_headers),
    ("sections", False, ("spec", "ticket", "requirements"), check_sections),
    ("placeholders", False, ("spec", "ticket", "requirements"), check_placeholders),
    ("ids", False, ("spec", "requirements"), check_ids),
    ("refs", False, ("spec", "ticket", "requirements"), check_refs),
    ("markers", False, ("spec", "requirements"), check_markers),
    ("questions", False, ("spec", "requirements"), check_questions),
    ("blocked-by", False, ("ticket", "wayticket"), check_blocked_by),
    ("numbering", False, ("ticket", "wayticket"), check_numbering),
    ("layout", False, REPO_WIDE, check_layout),
    ("controls", False, ("spec",), check_controls),
    ("coverage", False, ("spec", "requirements"), check_coverage),
    ("acceptance", False, ("ticket",), check_acceptance),
    ("ready", False, ("spec", "ticket", "requirements"), check_ready),
    ("anchors", False, ("spec", "ticket"), check_anchors),
    ("links", False, REPO_WIDE, check_links),
    ("ticket-list", False, ("spec",), check_ticket_list),
    ("adr", False, REPO_WIDE, check_adr),
    ("stray", False, REPO_WIDE, check_stray),
    ("emoji", False, REPO_WIDE, check_emoji),
    ("ears", True, ("spec", "requirements"), check_ears),
    ("vague", True, ("spec", "requirements"), check_vague),
    ("collision", True, ("ticket",), check_collision),
)


# -------------------------------------------------------------------- main --


def build_model(repo: Path, owners: Owners, scope: list[str], hygiene: Path | None) -> Model:
    plans = repo / PLANS
    areas = {
        Path(item).relative_to(PLANS).parts[0].removesuffix(".md")
        for item in scope
        if item != PLANS.as_posix()
    }
    paths: list[Path] = []
    if plans.is_dir():
        for path in sorted(plans.rglob("*.md")):
            first = path.relative_to(plans).parts[0].removesuffix(".md")
            if not areas or first in areas:
                paths.append(path)
    return Model(repo, owners, [parse_doc(repo, path) for path in paths], scope, hygiene)


def run(model: Model, advisory: bool) -> int:
    tally = {OK: 0, FAIL: 0, NA: 0, NOT_RUN: 0}
    failed = False
    warnings = 0
    for check_id, warn, kinds, runner in CHECKS:
        outcome = Outcome(check_id)
        try:
            runner(model, outcome)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            outcome.not_run = f"lỗi khi chạy: {error}"
        findings = [f for f in outcome.findings if model.in_scope(f.rel)]
        applicable = not kinds or any(d.kind in kinds and model.in_scope(d.rel) for d in model.docs)
        if outcome.not_run:
            status = NOT_RUN
        elif findings:
            status = FAIL
        elif not applicable or outcome.seen == 0:
            status = NA
            if applicable:
                outcome.not_run = "không có mục nào để kiểm"
        else:
            status = OK
        tally[status] += 1
        if warn:
            warnings += len(findings)
        elif status in (FAIL, NOT_RUN):
            failed = True
        note = " (cảnh báo)" if warn else ""
        reason = f": {outcome.not_run}" if outcome.not_run else ""
        print(f"{status:<16}{check_id}{note}{reason}")
        for f in sorted(findings, key=lambda f: (f.rel, f.line)):
            print(f"  {f.rel}:{f.line} [{f.check}] {f.message} Sửa: {f.fix}")
    print(
        f"Tổng: {tally[OK]} {OK}, {tally[FAIL]} {FAIL}, {tally[NA]} {NA}, "
        f"{tally[NOT_RUN]} {NOT_RUN}; {warnings} cảnh báo."
    )
    return 0 if advisory or not failed else 1


def print_table(model: Model, spec_path: Path) -> int:
    spec = model.doc(spec_path)
    if spec is None or spec.kind != "spec":
        print(f"{spec_path}: not a spec under .claude/plans/", file=sys.stderr)
        return 2
    print(f"| # | Status | Blocked by | {REQ_HEADER} |")
    print("| --- | --- | --- | --- |")
    for ticket in model.tickets_of(spec):
        row = (ticket.ticket_number(), ticket.value("Status"), ticket.value("Blocked by"))
        print(f"| {' | '.join(row)} | {ticket.value(REQ_HEADER)} |")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252, which cannot print Vietnamese.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--area", help="check one area: .claude/plans/<area>.md and <area>/")
    where.add_argument("--path", type=Path, help="check one folder or file under .claude/plans/")
    where.add_argument("--table", type=Path, help="print the live ticket table of one spec")
    parser.add_argument("--advisory", action="store_true", help="report, but exit 0")
    parser.add_argument(
        "--owners", type=Path, default=SCRIPT_ROOT, help="root holding the owner files"
    )
    parser.add_argument("--repo", type=Path, help="root holding .claude/plans (default: derived)")
    parser.add_argument("--hygiene", type=Path, help="check_hygiene.py to read emoji ranges from")
    args = parser.parse_args(argv)

    target: Path | None = args.path or args.table
    repo: Path | None = args.repo.resolve() if args.repo else None
    if target is not None:
        target = target.resolve() if target.exists() or repo is None else (repo / target).resolve()
        if repo is None:
            repo = next((p for p in [target, *target.parents] if (p / PLANS).is_dir()), None)
    if repo is None:
        repo = args.owners.resolve()
    owners_root = args.owners.resolve()
    try:
        owners = load_owners(owners_root)
    except OwnerError as error:
        print(f"check_plans: owner error: {error}", file=sys.stderr)
        return 2
    hygiene = args.hygiene
    if hygiene is None:
        hygiene = next(
            (p for p in (owners_root / HYGIENE_FILE, repo / HYGIENE_FILE) if p.is_file()), None
        )

    scope = [PLANS.as_posix()]
    if args.area:
        scope = [f"{PLANS.as_posix()}/{args.area}", f"{PLANS.as_posix()}/{args.area}.md"]
    elif target is not None:
        try:
            rel = target.relative_to(repo).as_posix()
        except ValueError:
            print(f"check_plans: {target} is not under {repo}", file=sys.stderr)
            return 2
        if not rel.startswith(PLANS.as_posix() + "/"):
            print(f"check_plans: {rel} is not under {PLANS.as_posix()}/", file=sys.stderr)
            return 2
        scope = [rel]
        if len(Path(rel).parts) == 3 and target.is_dir():
            scope.append(rel + ".md")
    model = build_model(repo, owners, scope, hygiene)
    if args.table is not None:
        return print_table(model, target or args.table)
    print(f"check_plans: {', '.join(scope)} (repo {repo}; owner files {owners_root})")
    return run(model, args.advisory)


if __name__ == "__main__":
    sys.exit(main())
