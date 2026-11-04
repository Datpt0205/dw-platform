"""The contract suite of `ExpressionEngine` (workflow-nodes 01 step 5; ADR-0114
decision 2): a replacement adapter joins only by passing every case here.

The cases are written against the Protocol, through the `engine` fixture; the
few that read the adapter's own parts (its cache, its pool, its process
limits) are in `test_cel_cpp_engine.py`.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta, timezone

import pytest

from dw_kernel.expressions import (
    BOOL,
    BYTES,
    DURATION,
    DW_CEL_LIBRARY,
    DYN,
    INT,
    STRING,
    TIMESTAMP,
    CheckedExpression,
    ExpressionEngine,
    ExpressionEnv,
    ExpressionError,
    ExpressionIssue,
    ExprType,
    ListType,
    MapType,
    OptionalType,
    object_type,
)
from dw_kernel.ids import TenantId
from dw_studio.core.adapters.cel import CelCppEngine

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.UUID("00000000-0000-4000-8000-0000000000a1"))

TRIGGER = object_type("Trigger", {"amount": INT})
SCORE = object_type(
    "Score",
    {
        "response": object_type(
            "Response",
            {"tier": STRING, "flag": OptionalType(BOOL), "note": OptionalType(STRING)},
        )
    },
)
RECORD = object_type(
    "Record",
    {
        "name": STRING,
        "count": INT,
        "at": TIMESTAMP,
        "wait": DURATION,
        "blob": BYTES,
        "tags": ListType(STRING),
        "scores": MapType(INT),
        "extra": DYN,
    },
)

# WN12: 19 concatenations of a 500-element list, then a map. 77 bytes; held a
# process 5.6 s under the binding's iteration budget (FOG-50).
QUADRATIC_77 = "(" + "+".join(["xs"] * 19) + ").map(a, a+1).size()"
# A slow evaluation that stays small: 9,801 regex scans of 300 KB. About 5 s
# in-process on Windows and in python:3.12-slim-bookworm, with a 32 MB peak,
# so the clock stops it on every platform, before any memory limit could.
SLOW_SMALL = "ys.all(a, ys.all(b, !s.matches('(x+x+)+y')))"


@pytest.fixture(scope="module")
def engine() -> Iterator[ExpressionEngine]:
    adapter = CelCppEngine()
    yield adapter
    asyncio.run(adapter.aclose())


def env(variables: Mapping[str, ExprType], tenant: TenantId | None = TENANT) -> ExpressionEnv:
    return ExpressionEnv(tenant, variables, DW_CEL_LIBRARY)


def checked(engine: ExpressionEngine, source: str, e: ExpressionEnv) -> CheckedExpression:
    result = engine.check(source, e)
    assert isinstance(result, CheckedExpression), result
    return result


def issues(engine: ExpressionEngine, source: str, e: ExpressionEnv) -> list[ExpressionIssue]:
    result = engine.check(source, e)
    assert isinstance(result, list), result
    return result


async def value_of(
    engine: ExpressionEngine,
    source: str,
    variables: Mapping[str, ExprType] | None = None,
    activation: Mapping[str, object] | None = None,
) -> object:
    e = env(variables or {})
    return await engine.evaluate(checked(engine, source, e), activation or {})


# ---------------------------------------------------------------------------
# R3.1: type-checked at check, evaluated by the engine
# ---------------------------------------------------------------------------


async def test_a_condition_checks_as_bool_and_evaluates(engine: ExpressionEngine) -> None:
    e = env({"trigger": TRIGGER})
    result = checked(engine, "trigger.amount > 1000000", e)
    assert result.result_type == BOOL
    assert await engine.evaluate(result, {"trigger": {"amount": 2_000_000}}) is True
    assert await engine.evaluate(result, {"trigger": {"amount": 5}}) is False


def test_an_undeclared_reference_is_an_issue_naming_it(engine: ExpressionEngine) -> None:
    found = issues(engine, "trigger.amount > 1 && nope", env({"trigger": TRIGGER}))
    assert [(i.kind, i.name, i.line, i.column) for i in found] == [
        ("undeclared_reference", "nope", 1, 23)
    ]


def test_object_fields_are_checked(engine: ExpressionEngine) -> None:
    e = env({"score": SCORE})
    typo = issues(engine, "score.response.tierr", e)
    assert [(i.kind, i.name) for i in typo] == [("undefined_field", "tierr")]
    overload = issues(engine, "score.response.tier + 1", e)
    assert [i.kind for i in overload] == ["no_matching_overload"]
    assert checked(engine, "score.response.tier", e).result_type == STRING


async def test_an_absent_scalar_field_reads_null_never_its_zero(engine: ExpressionEngine) -> None:
    e = env({"score": SCORE})
    absent: dict[str, object] = {"score": {"response": {}}}
    assert await engine.evaluate(checked(engine, "score.response.tier", e), absent) is None
    assert await engine.evaluate(checked(engine, "score.response.tier == ''", e), absent) is False
    assert await engine.evaluate(checked(engine, "has(score.response.tier)", e), absent) is False
    present = {"score": {"response": {"tier": ""}}}
    assert await engine.evaluate(checked(engine, "has(score.response.tier)", e), present) is True


async def test_has_and_the_optional_extension_guard_an_optional_field(
    engine: ExpressionEngine,
) -> None:
    e = env({"score": SCORE})
    guard = checked(engine, "has(score.response.note) ? score.response.note : 'none'", e)
    assert await engine.evaluate(guard, {"score": {"response": {}}}) == "none"
    assert await engine.evaluate(guard, {"score": {"response": {"note": "hi"}}}) == "hi"
    chained = checked(engine, "score.response.?note.orValue('none')", e)
    assert await engine.evaluate(chained, {"score": {"response": {}}}) == "none"


async def test_an_absent_wrapper_in_a_boolean_fails_closed(engine: ExpressionEngine) -> None:
    e = env({"score": SCORE})
    result = checked(engine, "score.response.flag && true", e)
    assert result.result_type == BOOL
    assert await engine.evaluate(result, {"score": {"response": {}}}) == ExpressionError(
        "expression_error", "UNKNOWN"
    )


async def test_a_naive_datetime_is_refused_before_it_is_sent(engine: ExpressionEngine) -> None:
    e = env({"at": TIMESTAMP, "record": RECORD})
    result = checked(engine, "at.getHours('+07:00')", e)
    with pytest.raises(ValueError, match="zone"):
        await engine.evaluate(result, {"at": datetime(2026, 11, 3, 1, 30)})
    with pytest.raises(ValueError, match="zone"):
        await engine.evaluate(result, {"record": {"at": datetime(2026, 11, 3, 1, 30)}})
    vietnam = timezone(timedelta(hours=7))
    aware = {"at": datetime(2026, 11, 3, 1, 30, tzinfo=vietnam)}
    assert await engine.evaluate(result, aware) == 1


async def test_phone_e164_one_answer_for_three_spellings(engine: ExpressionEngine) -> None:
    for spelling in ("0901 234 567", "+84901234567", "+84 0901 234 567"):
        found = await value_of(engine, f"phone.e164('{spelling}')")
        assert found == "+84901234567", spelling
    assert await value_of(engine, "phone.e164('12345')") == ExpressionError(
        "expression_error", "OUT_OF_RANGE"
    )


def test_a_library_this_adapter_does_not_ship_is_a_programming_error(
    engine: ExpressionEngine,
) -> None:
    with pytest.raises(ValueError, match="not shipped"):
        engine.check("1 == 1", ExpressionEnv(TENANT, {}, "dw.cel/v2.0"))


async def test_evaluate_refuses_a_library_this_adapter_does_not_ship(
    engine: ExpressionEngine,
) -> None:
    forged = CheckedExpression("1 == 1", ExpressionEnv(TENANT, {}, "dw.cel/v1.1"), BOOL)
    with pytest.raises(ValueError, match="not shipped"):
        await engine.evaluate(forged, {})


# ---------------------------------------------------------------------------
# R3.4 (WN12): iterations, the clock and the size of the result
# ---------------------------------------------------------------------------

NESTED = "xs.map(a, xs.map(b, xs.map(c, a+b+c)))"


async def test_the_iteration_budget_stops_a_nested_map(engine: ExpressionEngine) -> None:
    e = env({"xs": ListType(INT)})
    result = checked(engine, NESTED, e)
    assert await engine.evaluate(result, {"xs": list(range(22))}) == ExpressionError(
        "expression_budget_exceeded", "INTERNAL"
    )
    under = await engine.evaluate(result, {"xs": list(range(21))})
    assert isinstance(under, list)
    assert len(under) == 21
    assert under[20][20][20] == 60  # type: ignore[index]


async def _timed_with_ticks(
    engine: ExpressionEngine, result: CheckedExpression, activation: Mapping[str, object]
) -> tuple[object, float, int]:
    """The outcome, its time, and the 10 ms ticks in which the caller's event
    loop ran a task of its own. A tick is a 10 ms slot the ticker visited, not
    one `sleep(0.01)`: Windows rounds a sleep up to its 15.6 ms timer, which
    would count a free loop short."""
    slots: set[int] = set()
    stop = asyncio.Event()
    started = time.perf_counter()

    async def ticker() -> None:
        while not stop.is_set():
            slots.add(int((time.perf_counter() - started) / 0.01))
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    outcome = await engine.evaluate(result, activation)
    elapsed = time.perf_counter() - started
    stop.set()
    await task
    return outcome, elapsed, len(slots)


async def test_the_77_byte_expression_is_stopped_and_the_caller_keeps_running(
    engine: ExpressionEngine,
) -> None:
    assert len(QUADRATIC_77) == 77
    e = env({"xs": ListType(INT)})
    result = checked(engine, QUADRATIC_77, e)
    small = {"xs": list(range(3))}
    assert await engine.evaluate(result, small) == 3 * 19  # warm
    outcome, elapsed, ticks = await _timed_with_ticks(engine, result, {"xs": list(range(500))})
    # The clock on Windows; on Linux the 512 MiB address-space limit stops it
    # first (`RESOURCE_EXHAUSTED`, see test_cel_cpp_engine.py).
    assert isinstance(outcome, ExpressionError)
    assert outcome.code == "expression_budget_exceeded"
    assert outcome.status in ("DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED")
    assert elapsed <= 1.5
    assert ticks >= 50 or elapsed < 0.6
    assert await engine.evaluate(result, small) == 3 * 19


async def test_the_wall_clock_stops_a_slow_small_evaluation(engine: ExpressionEngine) -> None:
    e = env({"ys": ListType(INT), "s": STRING})
    result = checked(engine, SLOW_SMALL, e)
    assert await engine.evaluate(result, {"ys": [1], "s": "x" * 10}) is True  # warm
    big = {"ys": list(range(99)), "s": "x" * 300_000}
    outcome, elapsed, ticks = await _timed_with_ticks(engine, result, big)
    assert outcome == ExpressionError("expression_budget_exceeded", "DEADLINE_EXCEEDED")
    assert elapsed <= 1.5
    assert ticks >= 50
    assert await engine.evaluate(result, {"ys": [1, 2], "s": "xxy"}) is False


async def test_a_result_over_256_kib_is_refused(engine: ExpressionEngine) -> None:
    e = env({"s": STRING})
    hundred_kib = {"s": "x" * 100 * 1024}
    three = checked(engine, "s + s + s", e)
    assert await engine.evaluate(three, hundred_kib) == ExpressionError(
        "expression_budget_exceeded", "RESOURCE_EXHAUSTED"
    )
    two = await engine.evaluate(checked(engine, "s + s", e), hundred_kib)
    assert isinstance(two, str)
    assert len(two) == 200 * 1024


async def test_requests_beyond_the_pool_wait_and_all_answer(engine: ExpressionEngine) -> None:
    e = env({"n": INT})
    result = checked(engine, "n * 2", e)
    answers = await asyncio.gather(*(engine.evaluate(result, {"n": n}) for n in range(7)))
    assert answers == [n * 2 for n in range(7)]


# ---------------------------------------------------------------------------
# Issues: one case per kind, each from the binding's measured wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "kind", "name"),
    [
        ("1 +", "syntax", None),
        ("missing > 1", "undeclared_reference", "missing"),
        ("trigger.amont", "undefined_field", "amont"),
        ("trigger.amount + 'x'", "no_matching_overload", None),
        ("(" * 40 + "1" + ")" * 40, "too_deep", None),
        ("1" + " + 1" * 40, "too_deep", None),
        ("trigger.amount.size", "other", None),
    ],
)
def test_each_issue_kind(
    engine: ExpressionEngine, source: str, kind: str, name: str | None
) -> None:
    found = issues(engine, source, env({"trigger": TRIGGER}))
    assert found
    assert found[0].kind == kind
    assert found[0].name == name
    assert found[0].message


def test_every_issue_of_a_source_is_reported(engine: ExpressionEngine) -> None:
    found = issues(engine, "a + b", env({}))
    assert [(i.kind, i.name, i.column) for i in found] == [
        ("undeclared_reference", "a", 1),
        ("undeclared_reference", "b", 5),
    ]


def test_a_source_over_2_kib_is_refused_without_compiling(engine: ExpressionEngine) -> None:
    e = env({"s": STRING})
    at_limit = "s == '" + "x" * (2048 - 7) + "'"
    assert len(at_limit.encode("utf-8")) == 2048
    assert isinstance(engine.check(at_limit, e), CheckedExpression)
    over = at_limit[:-1] + "x'"
    found = issues(engine, over, e)
    assert [i.kind for i in found] == ["source_too_large"]
    # Bytes, not characters: 1,000 characters of two bytes each are over.
    wide = "s == '" + "đ" * 1022 + "'"
    assert [i.kind for i in issues(engine, wide, e)] == ["source_too_large"]


def test_a_result_with_no_json_form_is_refused_at_check(engine: ExpressionEngine) -> None:
    found = issues(engine, "optional.of(1)", env({}))
    assert [i.kind for i in found] == ["other"]


# ---------------------------------------------------------------------------
# Errors: each status measured, and never the binding's text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("1 / 0 == 1", "INVALID_ARGUMENT"),
        ("{'k': 1}['nope'] == 1", "NOT_FOUND"),
        ("9223372036854775807 + 1 > 0", "OUT_OF_RANGE"),
        ("'ab'.matches('a(?=b)')", "INVALID_ARGUMENT"),
    ],
)
async def test_each_evaluation_status(engine: ExpressionEngine, source: str, status: str) -> None:
    outcome = await value_of(engine, source)
    assert outcome == ExpressionError("expression_error", status)  # type: ignore[arg-type]


async def test_an_error_carries_no_value(engine: ExpressionEngine) -> None:
    outcome = await value_of(engine, "{'k': 1}['secret-key'] == 1")
    assert isinstance(outcome, ExpressionError)
    assert "secret-key" not in repr(outcome)


async def test_an_undeclared_activation_key_is_an_error(engine: ExpressionEngine) -> None:
    e = env({"trigger": TRIGGER})
    result = checked(engine, "trigger.amount > 1", e)
    stray = {"trigger": {"amount": 2}, "other": 1}
    assert await engine.evaluate(result, stray) == ExpressionError(
        "expression_error", "INVALID_ARGUMENT"
    )
    unknown_field = {"trigger": {"amount": 2, "bogus": 1}}
    assert await engine.evaluate(result, unknown_field) == ExpressionError(
        "expression_error", "INVALID_ARGUMENT"
    )


async def test_a_value_of_the_wrong_type_is_an_error(engine: ExpressionEngine) -> None:
    e = env({"xs": ListType(INT)})
    result = checked(engine, "xs.size()", e)
    assert await engine.evaluate(result, {"xs": [1, "two"]}) == ExpressionError(
        "expression_error", "INVALID_ARGUMENT"
    )


async def test_a_plain_string_with_nul_is_refused_and_an_object_keeps_it(
    engine: ExpressionEngine,
) -> None:
    # Measured: the binding cuts a plain `str` at U+0000 ('a\\x00b' reads 'a').
    e = env({"s": STRING, "record": RECORD})
    plain = checked(engine, "size(s)", e)
    assert await engine.evaluate(plain, {"s": "a\x00b"}) == ExpressionError(
        "expression_error", "INVALID_ARGUMENT"
    )
    inside = checked(engine, "size(record.name)", e)
    assert await engine.evaluate(inside, {"record": {"name": "a\x00b"}}) == 3


# ---------------------------------------------------------------------------
# Results as JSON
# ---------------------------------------------------------------------------


async def test_results_are_json(engine: ExpressionEngine) -> None:
    e = env({"record": RECORD})
    record = {
        "name": "Lan",
        "count": 9_007_199_254_740_993,
        "at": datetime(2026, 11, 3, 1, 30, tzinfo=timezone(timedelta(hours=7))),
        "wait": timedelta(hours=1),
        "blob": b"\x00\xffa",
        "tags": ["a", "b"],
        "scores": {"x": 1},
    }
    whole = await engine.evaluate(checked(engine, "record", e), {"record": record})
    assert whole == {
        "name": "Lan",
        "count": 9_007_199_254_740_993,
        "at": "2026-11-02T18:30:00+00:00",
        "wait": "3600s",
        "blob": "AP9h",
        "tags": ["a", "b"],
        "scores": {"x": 1},
    }
    assert await engine.evaluate(checked(engine, "record.at", e), {"record": record}) == (
        "2026-11-02T18:30:00+00:00"
    )
    assert await engine.evaluate(checked(engine, "record.wait", e), {"record": record}) == "3600s"
    assert await engine.evaluate(checked(engine, "record.blob", e), {"record": record}) == "AP9h"
    assert await value_of(engine, "{'a': [1, 2.5, true, null]}") == {"a": [1, 2.5, True, None]}


async def test_a_non_finite_double_is_an_error(engine: ExpressionEngine) -> None:
    assert await value_of(engine, "1.0 / 0.0") == ExpressionError(
        "expression_error", "INVALID_ARGUMENT"
    )


# ---------------------------------------------------------------------------
# A cel-spec subset (timestamps with a fixed offset only: the binding finds an
# IANA zone name on Linux alone)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("1 + 2 * 3 - 4 / 2 % 3", 5),
        ("7 / 2", 3),
        ("1.5 * 2.0", 3.0),
        ("-(3) < 0 && !false || false", True),
        ("'ab' + 'c' == 'abc' && 'abc'.startsWith('ab') && 'abc'.endsWith('bc')", True),
        ("'abc'.contains('b') && size('đâu') == 3", True),
        ("'Hello'.lowerAscii() + '|' + 'x,y'.split(',').join('-')", "hello|x-y"),
        ("[1, 2] + [3] == [1, 2, 3] && 2 in [1, 2] && size([1, 2]) == 2", True),
        ("{'a': 1, 'b': 2}['b'] == 2 && 'a' in {'a': 1} && size({'a': 1}) == 1", True),
        ("[1, 2, 3].all(x, x > 0)", True),
        ("[1, 2, 3].exists(x, x > 2)", True),
        ("[1, 2, 3].exists_one(x, x > 1)", False),
        ("[1, 2, 3].map(x, x * 10)", [10, 20, 30]),
        ("[1, 2, 3].filter(x, x % 2 == 1)", [1, 3]),
        ("{'a': 1}.?a.orValue(0) + {'a': 1}.?b.orValue(5)", 6),
        ("optional.of(2).hasValue() && !optional.none().hasValue()", True),
        ("math.greatest(1, 4, 2) + math.least(3, 1)", 5),
        ("cel.bind(t, 3, t * t)", 9),
        ("base64.encode(b'hi')", "aGk="),
        ("timestamp('2026-11-03T01:30:00+07:00').getHours('+07:00')", 1),
        ("timestamp('2026-11-03T01:30:00+07:00').getDayOfWeek('+07:00')", 2),
        ("timestamp('2026-11-03T01:30:00+07:00') + duration('1h')", "2026-11-02T19:30:00+00:00"),
        ("duration('1h30m') + duration('30m')", "7200s"),
        ("timestamp('2026-11-03T00:00:00Z') - timestamp('2026-11-02T00:00:00Z')", "86400s"),
        ("'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaab'.matches('(a+)+$')", False),
        ("type(1) == int && type('a') == string", True),
    ],
)
async def test_cel_spec_subset(engine: ExpressionEngine, source: str, expected: object) -> None:
    assert await value_of(engine, source) == expected


async def test_re2_refuses_backreferences_and_lookahead(engine: ExpressionEngine) -> None:
    for pattern in (r"r'(a)\1'", "'a(?=b)'"):
        outcome = await value_of(engine, f"'aab'.matches({pattern})")
        assert outcome == ExpressionError("expression_error", "INVALID_ARGUMENT"), pattern


# ---------------------------------------------------------------------------
# dw.cel/v1.0: a valid and an invalid case for every platform function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("text.nfc('é') == 'é'", True),
        ("text.unaccent('Đặng Thị Ốc ư')", "Dang Thi Oc u"),
        (
            "text.mask_contacts('gọi 0901.234.567, +84 90 123 4567 hay lan.ng@vd.vn; mã 12345678')",
            "gọi [đã che], [đã che] hay [đã che]; mã 12345678",
        ),
        ("phone.e164('84901234567')", "+84901234567"),
        ("phone.e164('(+1) 415-555-0100')", "+14155550100"),
        ("email.normalize('  Lan.NG@VD.vn ')", "lan.ng@vd.vn"),
        ("fmt.money_vnd(1234567)", "1.234.567 ₫"),
        ("fmt.money_vnd(-500)", "-500 ₫"),
        ("fmt.datetime(timestamp('2026-11-02T18:30:00Z'))", "03/11/2026 01:30"),
        ("fmt.date(timestamp('2026-11-02T18:30:00Z'))", "03/11/2026"),
        ("fmt.date('2026-11-03')", "03/11/2026"),
    ],
)
async def test_platform_function(engine: ExpressionEngine, source: str, expected: object) -> None:
    assert await value_of(engine, source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "phone.e164('12345')",
        "phone.e164('0901 234 56x')",
        "email.normalize('a@b@c')",
        "email.normalize('nobody')",
        "fmt.date('03/11/2026')",
        "fmt.date('2026-02-30')",
    ],
)
async def test_platform_function_refusal(engine: ExpressionEngine, source: str) -> None:
    assert await value_of(engine, source) == ExpressionError("expression_error", "OUT_OF_RANGE")


@pytest.mark.parametrize(
    "source",
    [
        "text.nfc(1)",
        "text.unaccent(b'x')",
        "text.mask_contacts(1)",
        "phone.e164(901234567)",
        "email.normalize(1)",
        "fmt.money_vnd('1')",
        "fmt.money_vnd(1.5)",
        "fmt.datetime('2026-11-03')",
        "fmt.date(1)",
    ],
)
def test_platform_function_wrong_argument_type(engine: ExpressionEngine, source: str) -> None:
    assert [i.kind for i in issues(engine, source, env({}))] == ["no_matching_overload"]


def test_no_now(engine: ExpressionEngine) -> None:
    assert [i.kind for i in issues(engine, "now()", env({}))] == ["undeclared_reference"]


# ---------------------------------------------------------------------------
# Top-level variables of every kind
# ---------------------------------------------------------------------------


async def test_top_level_variables(engine: ExpressionEngine) -> None:
    e = env(
        {
            "flag": BOOL,
            "n": INT,
            "at": TIMESTAMP,
            "wait": DURATION,
            "blob": BYTES,
            "names": ListType(STRING),
            "counts": MapType(INT),
            "people": ListType(TRIGGER),
            "free": DYN,
            "maybe": OptionalType(INT),
        }
    )
    activation = {
        "flag": True,
        "n": 2,
        "at": datetime(2026, 11, 3, tzinfo=UTC),
        "wait": "90s",
        "blob": b"hi",
        "names": ["a"],
        "counts": {"k": 3},
        "people": [{"amount": 4}],
        "free": {"deep": [1, "x"]},
    }
    source = (
        "flag && n + counts['k'] + people[0].amount == 9 && at.getHours('+07:00') == 7"
        " && wait == duration('90s') && blob == b'hi' && names[0] == 'a'"
        " && free.deep[1] == 'x'"
    )
    assert await engine.evaluate(checked(engine, source, e), activation) is True
    # An optional top-level variable left out fails closed when it is read.
    maybe = checked(engine, "maybe + 1", e)
    assert await engine.evaluate(maybe, {}) == ExpressionError("expression_error", "UNKNOWN")
    assert await engine.evaluate(maybe, {"maybe": 1}) == 2


def test_an_unrepresentable_field_type_is_a_programming_error(engine: ExpressionEngine) -> None:
    nested = object_type("Grid", {"rows": ListType(ListType(INT))})
    with pytest.raises(ValueError, match="no field form"):
        engine.check("1 == 1", env({"grid": nested}))
