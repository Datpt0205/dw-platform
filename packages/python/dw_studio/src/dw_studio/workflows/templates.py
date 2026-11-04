"""Text templates: `{{ expr }}` in a tenant's text, checked at submit and
rendered per sink (workflow-nodes R4; ADR-0114 decisions 1, 5; ADR-0010).

A tenant's value reaches text only through here. The tokenizer reads
`{{ expr }}` knowing CEL's string literals, so `}}` inside one does not close
the expression; `\\{{` is a literal `{{`; nothing else is special, so
`{0}{x.__class__}` is text, never a format string (WN1). Every expression goes
through the `ExpressionEngine` it is handed: this module names no adapter.

Each templatable config field declares its sink with `x-dw-sink` in its
type's config schema; `template_fields` finds them, and a templated string
in a field that declares none is `sink_missing` (there is no default sink,
failure-modes #7). The six sinks:

- `text`: a scalar as text (`scalar_text`).
- `html`: values escaped; the literal markup is a fixed list of tags whose
  only attribute is `a`'s literal `https://` or `mailto:` `href`, and an
  expression stands in text content only.
- `url`: the scheme and the whole authority are literal, before the first
  expression; each value is percent-encoded, and a path segment a value
  makes `.` or `..` is refused (WN13).
- `header`: a header value; CR, LF and NUL are refused in the literal and in
  what a value renders.
- `json`: the field is a JSON value; a leaf exactly `{{ expr }}` takes the
  typed value, a leaf mixing text renders as `text`; the result is data for
  the caller to serialise, never concatenated text.
- `prompt`: each value is cut at 16 KiB and contained in its own `<input>`
  block named `v<n>` by the platform; the literal is instructions, so it may
  not write that tag and holds at most 8 KiB (WN2).

A template holds at most 16 KiB and 50 expressions and renders at most
64 KiB; `null` renders nowhere but a `json` leaf, never as empty text.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final, Literal, cast, get_args
from urllib.parse import quote

from dw_agent_runtime.model.prompts import contain_untrusted, writes_untrusted_tag
from dw_kernel.expressions import (
    CheckedExpression,
    ErrorCode,
    ExpressionEngine,
    ExpressionEnv,
    ExpressionError,
    ExpressionIssue,
    ExprType,
    JsonValue,
    ListType,
    MapType,
    ObjectType,
    OptionalType,
)

Sink = Literal["prompt", "text", "html", "url", "header", "json"]
SINKS: Final[frozenset[str]] = frozenset(get_args(Sink))
# The config-schema keyword that names a field's sink.
SINK_KEYWORD: Final = "x-dw-sink"

TemplateCode = Literal[
    "template_syntax",
    "sink_missing",
    "template_too_large",
    "render_too_large",
    "null_in_template",
    "non_scalar_in_text",
    "html_markup_not_allowed",
    "templated_host",
    "url_dot_segment",
    "header_crlf",
    "prompt_literal_input_tag",
    "prompt_literal_too_large",
    # An expression that does not check; the engine's issue rides along.
    "expression_invalid",
]
TEMPLATE_CODES: Final[frozenset[str]] = frozenset(get_args(TemplateCode))
RenderCode = TemplateCode | ErrorCode

MAX_SOURCE_BYTES: Final = 16_384
MAX_EXPRESSIONS: Final = 50
MAX_RENDER_BYTES: Final = 65_536
MAX_PROMPT_VALUE_BYTES: Final = 16_384
MAX_PROMPT_LITERAL_BYTES: Final = 8_192


# ---------------------------------------------------------------------------
# What a check returns
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemplateIssue:
    """One reason a template does not check. `index` is the expression's
    number in the template (from 1), `None` for the template as a whole;
    `offset` is where in its string the problem starts (an expression's
    `{{`); `pointer` is the leaf (RFC 6901) inside a `json` field, `""`
    elsewhere."""

    code: TemplateCode
    index: int | None = None
    offset: int | None = None
    pointer: str = ""
    expression: ExpressionIssue | None = None


@dataclass(frozen=True, slots=True)
class TemplateExpression:
    index: int
    offset: int
    checked: CheckedExpression


@dataclass(frozen=True, slots=True)
class TemplatedText:
    """A string as literal text and expressions, in order."""

    parts: tuple[str | TemplateExpression, ...]


# A `json` field after its check: its JSON value with each templated leaf
# replaced, by a `TemplateExpression` when the leaf is exactly one, by a
# `TemplatedText` when it mixes text.
type JsonTemplate = (
    TemplateExpression
    | TemplatedText
    | dict[str, JsonTemplate]
    | list[JsonTemplate]
    | bool
    | int
    | float
    | str
    | None
)


@dataclass(frozen=True, slots=True)
class CheckedTemplate:
    sink: Sink
    body: JsonTemplate


@dataclass(frozen=True, slots=True)
class TemplateError:
    """A render that produced nothing. No node and no path: the node's
    wrapper attaches them (workflow-nodes ticket 01, step 1). Never a value."""

    code: RenderCode
    index: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateField:
    """A config field that declares a sink: where it is and what it holds."""

    pointer: str
    sink: Sink
    value: Any


# ---------------------------------------------------------------------------
# The tokenizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Source:
    text: str
    offset: int


def _string_end(source: str, at: int) -> int | None:
    """The index after the CEL string literal whose quote is at `at`: single
    or double, triple or not, raw (`r`, `br`) or with backslash escapes."""
    mark = source[at]
    prefix_start = at
    while prefix_start > 0 and at - prefix_start < 2 and source[prefix_start - 1] in "rRbB":
        prefix_start -= 1
    in_word = prefix_start > 0 and (
        source[prefix_start - 1].isalnum() or source[prefix_start - 1] == "_"
    )
    raw = not in_word and "r" in source[prefix_start:at].lower()
    delimiter = mark * 3 if source.startswith(mark * 3, at) else mark
    index = at + len(delimiter)
    while index < len(source):
        if not raw and source[index] == "\\":
            index += 2
            continue
        if source.startswith(delimiter, index):
            return index + len(delimiter)
        index += 1
    return None


def _expression_end(source: str, start: int) -> int | None:
    """The index of the `}}` that closes an expression begun before `start`."""
    index = start
    while index < len(source):
        if source[index] in "'\"":
            found = _string_end(source, index)
            if found is None:
                return None
            index = found
            continue
        if source.startswith("}}", index):
            return index
        index += 1
    return None


def _tokenize(source: str) -> list[str | _Source] | int:
    """The literal text and expression sources of `source`, in order, or the
    offset of a `{{` that does not close or holds nothing."""
    parts: list[str | _Source] = []
    literal: list[str] = []
    index = 0
    while index < len(source):
        if source.startswith("\\{{", index):
            literal.append("{{")
            index += 3
            continue
        if source.startswith("{{", index):
            end = _expression_end(source, index + 2)
            inner = "" if end is None else source[index + 2 : end].strip()
            if end is None or not inner:
                return index
            if literal:
                parts.append("".join(literal))
                literal = []
            parts.append(_Source(inner, index))
            index = end + 2
            continue
        literal.append(source[index])
        index += 1
    if literal:
        parts.append("".join(literal))
    return parts


def _templated(text: str) -> bool:
    """Whether `text` holds an unescaped `{{`, closed or not."""
    tokens = _tokenize(text)
    return isinstance(tokens, int) or any(isinstance(part, _Source) for part in tokens)


# ---------------------------------------------------------------------------
# Finding the templatable fields of a config
# ---------------------------------------------------------------------------


def _token(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def template_fields(
    config_schema: Mapping[str, Any], config: Any
) -> tuple[list[TemplateField], list[TemplateIssue]]:
    """Each field of `config` whose schema declares `x-dw-sink`, and a
    `sink_missing` for each templated string anywhere else. A field is found
    through `properties`, `additionalProperties` and `items`; a string the
    walk cannot place under a declared sink has none."""
    fields: list[TemplateField] = []
    issues: list[TemplateIssue] = []

    def walk(schema: Mapping[str, Any], value: Any, pointer: str) -> None:
        sink = schema.get(SINK_KEYWORD)
        if sink is not None:
            if sink not in SINKS:
                raise ValueError(f"{SINK_KEYWORD} {sink!r} at {pointer or '/'} is no sink")
            fields.append(TemplateField(pointer, cast(Sink, sink), value))
            return
        if isinstance(value, str):
            if _templated(value):
                issues.append(TemplateIssue("sink_missing", pointer=pointer))
        elif isinstance(value, Mapping):
            properties = schema.get("properties")
            extra = schema.get("additionalProperties")
            for key, item in value.items():
                found = properties.get(key) if isinstance(properties, Mapping) else None
                if found is None and isinstance(extra, Mapping):
                    found = extra
                walk(found if isinstance(found, Mapping) else {}, item, f"{pointer}/{_token(key)}")
        elif isinstance(value, list):
            items = schema.get("items")
            for index, item in enumerate(value):
                walk(items if isinstance(items, Mapping) else {}, item, f"{pointer}/{index}")

    walk(config_schema, config, "")
    return fields, issues


# ---------------------------------------------------------------------------
# Checks of the literal text, per sink
# ---------------------------------------------------------------------------

_HTML_TAGS: Final = frozenset(
    {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "a", "h1", "h2", "h3", "h4"}
    | {"blockquote", "table", "thead", "tbody", "tr", "th", "td", "span", "div"}
)
_HREF = re.compile(r"^(https://|mailto:)")
# Where an expression stands while the literal markup is parsed: one private
# use character, so an expression inside a tag shows up in that tag.
_HOLE: Final = ""
_AUTHORITY = re.compile(r"^https://[^\s/?#@{}\\]+[/?#]")
_HEADER_BREAKS: Final = ("\r", "\n", "\0")


class _Markup(HTMLParser):
    """Whether literal markup keeps to the allowed tags, with expressions in
    text content only. Character references are left as they are, so a
    literal `&lt;` stays allowed text while a bare `<` is refused."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.allowed = True

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _HTML_TAGS or _HOLE in (self.get_starttag_text() or ""):
            self.allowed = False
            return
        for name, value in attrs:
            if not (tag == "a" and name == "href" and value is not None and _HREF.match(value)):
                self.allowed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in _HTML_TAGS:
            self.allowed = False

    def handle_data(self, data: str) -> None:
        if "<" in data:
            self.allowed = False

    def handle_comment(self, data: str) -> None:
        self.allowed = False

    def handle_decl(self, decl: str) -> None:
        self.allowed = False

    def handle_pi(self, data: str) -> None:
        self.allowed = False

    def unknown_decl(self, data: str) -> None:
        self.allowed = False


def _markup_allowed(tokens: list[str | _Source]) -> bool:
    parser = _Markup()
    parser.feed("".join(_HOLE if isinstance(part, _Source) else part for part in tokens))
    parser.close()
    return parser.allowed


def _literal_issues(sink: Sink, tokens: list[str | _Source]) -> list[TemplateIssue]:
    literals = [part for part in tokens if isinstance(part, str)]
    has_expression = len(literals) != len(tokens)
    match sink:
        case "html":
            return [] if _markup_allowed(tokens) else [TemplateIssue("html_markup_not_allowed")]
        case "url":
            # Only a template with an expression: a literal URL is the egress
            # door's to judge, not this one's.
            head = tokens[0] if tokens and isinstance(tokens[0], str) else ""
            if has_expression and not _AUTHORITY.match(head):
                return [TemplateIssue("templated_host")]
            return []
        case "header":
            if any(mark in text for text in literals for mark in _HEADER_BREAKS):
                return [TemplateIssue("header_crlf")]
            return []
        case "prompt":
            found: list[TemplateIssue] = []
            if any(writes_untrusted_tag(text) for text in literals):
                found.append(TemplateIssue("prompt_literal_input_tag"))
            if sum(len(text.encode("utf-8")) for text in literals) > MAX_PROMPT_LITERAL_BYTES:
                found.append(TemplateIssue("prompt_literal_too_large"))
            return found
        case "text" | "json":
            return []


# ---------------------------------------------------------------------------
# check_template: at submit
# ---------------------------------------------------------------------------


def _non_scalar(expr_type: ExprType) -> bool:
    if isinstance(expr_type, OptionalType):
        return _non_scalar(expr_type.inner)
    return isinstance(expr_type, ListType | MapType | ObjectType)


def _json_bytes(value: Any) -> int:
    """How big a JSON value is: its `json.dumps`, compact, in UTF-8 bytes."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class _Checker:
    """One template's expressions, numbered across the whole field."""

    def __init__(self, env: ExpressionEnv, engine: ExpressionEngine) -> None:
        self.env = env
        self.engine = engine
        self.count = 0
        self.issues: list[TemplateIssue] = []

    def text(
        self, tokens: list[str | _Source], *, scalar: bool, pointer: str = ""
    ) -> TemplatedText:
        parts: list[str | TemplateExpression] = []
        for part in tokens:
            if isinstance(part, str):
                parts.append(part)
                continue
            found = self.expression(part, pointer)
            if found is None:
                continue
            if scalar and _non_scalar(found.checked.result_type):
                self.issues.append(
                    TemplateIssue("non_scalar_in_text", found.index, part.offset, pointer)
                )
            parts.append(found)
        return TemplatedText(tuple(parts))

    def expression(self, source: _Source, pointer: str) -> TemplateExpression | None:
        self.count += 1
        result = self.engine.check(source.text, self.env)
        if isinstance(result, CheckedExpression):
            return TemplateExpression(self.count, source.offset, result)
        self.issues.extend(
            TemplateIssue("expression_invalid", self.count, source.offset, pointer, issue)
            for issue in result
        )
        return None


def _expression_count(tokens: list[str | _Source]) -> int:
    return sum(isinstance(part, _Source) for part in tokens)


def check_template(
    source: Any, sink: Sink, env: ExpressionEnv, engine: ExpressionEngine
) -> CheckedTemplate | list[TemplateIssue]:
    """Check a template at submit: its size, its syntax, its literal text for
    `sink`, and every expression through `engine.check` against `env`. For
    `json`, `source` is the field's whole JSON value."""
    if sink == "json":
        return _check_json(source, env, engine)
    if not isinstance(source, str):
        return [TemplateIssue("template_syntax")]
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return [TemplateIssue("template_too_large")]
    tokens = _tokenize(source)
    if isinstance(tokens, int):
        return [TemplateIssue("template_syntax", offset=tokens)]
    if _expression_count(tokens) > MAX_EXPRESSIONS:
        return [TemplateIssue("template_too_large")]
    issues = _literal_issues(sink, tokens)
    checker = _Checker(env, engine)
    body = checker.text(tokens, scalar=sink != "prompt")
    issues.extend(checker.issues)
    return issues or CheckedTemplate(sink, body)


def _check_json(
    source: Any, env: ExpressionEnv, engine: ExpressionEngine
) -> CheckedTemplate | list[TemplateIssue]:
    if _json_bytes(source) > MAX_SOURCE_BYTES:
        return [TemplateIssue("template_too_large")]
    leaves: dict[str, list[str | _Source]] = {}
    issues: list[TemplateIssue] = []

    def scan(value: Any, pointer: str) -> None:
        if isinstance(value, str):
            tokens = _tokenize(value)
            if isinstance(tokens, int):
                issues.append(TemplateIssue("template_syntax", offset=tokens, pointer=pointer))
            else:
                leaves[pointer] = tokens
        elif isinstance(value, Mapping):
            for key, item in value.items():
                at = f"{pointer}/{_token(key)}"
                if "{{" in key:
                    # A key is never templated: a field's shape is the tenant's.
                    issues.append(TemplateIssue("template_syntax", pointer=at))
                scan(item, at)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                scan(item, f"{pointer}/{index}")

    scan(source, "")
    if issues:
        return issues
    if sum(_expression_count(tokens) for tokens in leaves.values()) > MAX_EXPRESSIONS:
        return [TemplateIssue("template_too_large")]
    checker = _Checker(env, engine)

    def build(value: Any, pointer: str) -> JsonTemplate:
        if isinstance(value, str):
            tokens = leaves[pointer]
            if len(tokens) == 1 and isinstance(tokens[0], _Source):
                found = checker.expression(tokens[0], pointer)
                return found if found is not None else None
            if all(isinstance(part, str) for part in tokens):
                return "".join(cast(list[str], tokens))
            return checker.text(tokens, scalar=True, pointer=pointer)
        if isinstance(value, Mapping):
            return {key: build(item, f"{pointer}/{_token(key)}") for key, item in value.items()}
        if isinstance(value, list):
            return [build(item, f"{pointer}/{index}") for index, item in enumerate(value)]
        return cast(JsonTemplate, value)

    body = build(source, "")
    return checker.issues or CheckedTemplate("json", body)


# ---------------------------------------------------------------------------
# render: at run time
# ---------------------------------------------------------------------------


def scalar_text(value: JsonValue) -> str | None:
    """A scalar as text, `None` for a list or a map: a string as it is, an
    integer in decimal, a double as `json.dumps` writes it, `true` or
    `false`. Timestamps, durations and bytes are strings already when
    `evaluate` returns them (ticket 01)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value)
    return None


def _cut(text: str, limit: int) -> str:
    """At most `limit` bytes of UTF-8, cut at a character boundary."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore")


def _sink_value(sink: Sink, value: JsonValue, index: int) -> str | TemplateError:
    """One value as `sink` writes it inside text."""
    if value is None:
        return TemplateError("null_in_template", index)
    if sink == "prompt":
        text = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if isinstance(value, list | dict)
            else scalar_text(value)
        )
        assert text is not None
        return contain_untrusted(f"v{index}", _cut(text, MAX_PROMPT_VALUE_BYTES))
    text = scalar_text(value)
    if text is None:
        return TemplateError("non_scalar_in_text", index)
    match sink:
        case "html":
            return html.escape(text, quote=True)
        case "url":
            return quote(text, safe="")
        case "header":
            if any(mark in text for mark in _HEADER_BREAKS):
                return TemplateError("header_crlf", index)
            return text
        case _:
            return text


def _dot_segment(pieces: list[tuple[str, bool]]) -> bool:
    """Whether a path segment that a value helped make is `.` or `..`. The
    pieces are the rendered URL in order, each marked when a value wrote it;
    the path starts at the literal's first `/`, `?` or `#` after the
    authority and ends at the first literal `?` or `#` (a value's are
    encoded)."""
    head = _AUTHORITY.match(pieces[0][0]) if pieces and not pieces[0][1] else None
    if head is None:
        # `check_template` refused a templated URL without a literal
        # authority; should one arrive anyway, a value in it is refused.
        return any(from_value for _, from_value in pieces)
    segment, valued = "", False
    for text, from_value in [(pieces[0][0][head.end() - 1 :], False), *pieces[1:]]:
        if from_value:
            segment, valued = segment + text, True
            continue
        for char in text:
            if char not in "/?#":
                segment += char
                continue
            if valued and segment in (".", ".."):
                return True
            if char != "/":
                return False
            segment, valued = "", False
    return valued and segment in (".", "..")


async def _render_text(
    body: TemplatedText,
    sink: Sink,
    activation: Mapping[str, object],
    engine: ExpressionEngine,
) -> str | TemplateError:
    pieces: list[tuple[str, bool]] = []
    for part in body.parts:
        if isinstance(part, str):
            pieces.append((part, False))
            continue
        value = await engine.evaluate(part.checked, activation)
        if isinstance(value, ExpressionError):
            return TemplateError(value.code, part.index)
        written = _sink_value(sink, value, part.index)
        if isinstance(written, TemplateError):
            return written
        pieces.append((written, True))
    if sink == "url" and _dot_segment(pieces):
        return TemplateError("url_dot_segment")
    return "".join(text for text, _ in pieces)


async def _render_json(
    body: JsonTemplate, activation: Mapping[str, object], engine: ExpressionEngine
) -> JsonValue | TemplateError:
    if isinstance(body, TemplateExpression):
        value = await engine.evaluate(body.checked, activation)
        return (
            TemplateError(value.code, body.index) if isinstance(value, ExpressionError) else value
        )
    if isinstance(body, TemplatedText):
        return await _render_text(body, "text", activation, engine)
    if isinstance(body, dict):
        rendered: dict[str, JsonValue] = {}
        for key, item in body.items():
            rendered_item = await _render_json(item, activation, engine)
            if isinstance(rendered_item, TemplateError):
                return rendered_item
            rendered[key] = rendered_item
        return rendered
    if isinstance(body, list):
        items: list[JsonValue] = []
        for item in body:
            rendered_item = await _render_json(item, activation, engine)
            if isinstance(rendered_item, TemplateError):
                return rendered_item
            items.append(rendered_item)
        return items
    return body


async def render(
    checked: CheckedTemplate, activation: Mapping[str, object], engine: ExpressionEngine
) -> JsonValue | TemplateError:
    """Render a checked template over `activation`: a `str`, or for `json` a
    JSON value, or the first `TemplateError`. An expression that fails fails
    the render with its own code; nothing renders as empty."""
    if checked.sink == "json":
        value = await _render_json(checked.body, activation, engine)
        if not isinstance(value, TemplateError) and _json_bytes(value) > MAX_RENDER_BYTES:
            return TemplateError("render_too_large")
        return value
    assert isinstance(checked.body, TemplatedText)
    text = await _render_text(checked.body, checked.sink, activation, engine)
    if isinstance(text, str) and len(text.encode("utf-8")) > MAX_RENDER_BYTES:
        return TemplateError("render_too_large")
    return text


__all__ = [
    "MAX_EXPRESSIONS",
    "MAX_PROMPT_LITERAL_BYTES",
    "MAX_PROMPT_VALUE_BYTES",
    "MAX_RENDER_BYTES",
    "MAX_SOURCE_BYTES",
    "SINKS",
    "SINK_KEYWORD",
    "TEMPLATE_CODES",
    "CheckedTemplate",
    "JsonTemplate",
    "RenderCode",
    "Sink",
    "TemplateCode",
    "TemplateError",
    "TemplateExpression",
    "TemplateField",
    "TemplateIssue",
    "TemplatedText",
    "check_template",
    "render",
    "scalar_text",
    "template_fields",
]
