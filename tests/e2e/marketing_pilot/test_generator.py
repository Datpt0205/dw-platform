"""marketing-pilot ticket 01: the seeded lead generator, the dedupe oracle and the
synthetic-address check (R2.1, R2.2, R2.3)."""

from __future__ import annotations

import dataclasses
import io
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from marketing_pilot.generator import (
    MIN_COUNT,
    PAIR_KINDS,
    PHONE_FORMATS,
    LabelledLead,
    Lead,
    generate,
    serialize,
)
from marketing_pilot.measure import (
    PILOT_COUNT,
    PILOT_SEED,
    NotSimulatedError,
    dedupe_key,
    emails_in_text,
    main,
    measure,
    normalize_phone,
    phones_in_text,
    run,
    violations,
)

pytestmark = pytest.mark.unit

HERE = Path(__file__).resolve().parent
SEEDS = (PILOT_SEED, 0, 1, 7, 42, 2026)


@pytest.fixture(scope="module")
def pilot() -> list[LabelledLead]:
    return generate(PILOT_SEED, PILOT_COUNT)


def _single(
    person_id: str,
    *,
    phone: str | None = None,
    email: str | None = None,
    name: str = "Nguyễn An",
    message: str = "Em cần tư vấn.",
) -> LabelledLead:
    return LabelledLead(
        person_id=person_id,
        planted=None,
        lead=Lead(name=name, phone=phone, email=email, lead_source="website_form", message=message),
    )


# ----------------------------------------------------------------------- R2.1 --


def test_one_seed_gives_one_set_byte_for_byte() -> None:
    assert serialize(generate(PILOT_SEED, PILOT_COUNT)) == serialize(
        generate(PILOT_SEED, PILOT_COUNT)
    )


def test_the_set_does_not_depend_on_the_process() -> None:
    # Two fresh interpreters with different hash seeds: a set iterated anywhere
    # in the generator would order differently in one of them.
    code = (
        "import sys; from marketing_pilot.generator import generate, serialize; "
        f"sys.stdout.buffer.write(serialize(generate({PILOT_SEED}, {PILOT_COUNT})))"
    )
    outputs = []
    for hash_seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(HERE.parent)}
        done = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, check=True
        )
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1] == serialize(generate(PILOT_SEED, PILOT_COUNT))


def test_another_seed_gives_another_set() -> None:
    assert serialize(generate(1, PILOT_COUNT)) != serialize(generate(2, PILOT_COUNT))


def test_the_set_holds_a_close_tag_an_instruction_and_addresses_in_free_text(
    pilot: list[LabelledLead],
) -> None:
    messages = [x.lead.message for x in pilot]
    assert any("</input>" in m for m in messages)
    assert any("bỏ qua hướng dẫn phía trên" in m for m in messages)
    assert any(phones_in_text(m) for m in messages)
    assert any(emails_in_text(m) for m in messages)


def test_every_writing_of_a_number_and_mixed_case_email_occurs(
    pilot: list[LabelledLead],
) -> None:
    seen: set[str] = set()
    for x in pilot:
        if x.lead.phone is None:
            continue
        national = "0" + normalize_phone(x.lead.phone)[3:]
        seen |= {f for f, write in PHONE_FORMATS.items() if write(national) == x.lead.phone}
    assert seen == set(PHONE_FORMATS)
    emails = [x.lead.email for x in pilot if x.lead.email is not None]
    assert any(e != e.lower() for e in emails)
    assert any(e == e.lower() for e in emails)


@pytest.mark.parametrize("seed", SEEDS)
def test_every_lead_has_a_phone_or_an_email(seed: int) -> None:
    assert all(x.lead.phone is not None or x.lead.email is not None for x in generate(seed, 60))


def test_the_label_is_not_part_of_the_form_body() -> None:
    assert [f.name for f in dataclasses.fields(Lead)] == [
        "name",
        "phone",
        "email",
        "lead_source",
        "message",
    ]


def test_a_count_too_small_for_the_planted_pairs_is_refused() -> None:
    with pytest.raises(ValueError, match="count must be"):
        generate(PILOT_SEED, MIN_COUNT - 1)


# ----------------------------------------------------------------------- R2.2 --


def test_three_writings_of_one_number_are_one_key() -> None:
    keys = {
        dedupe_key(_single("p", phone=raw).lead)
        for raw in ("0901 234 567", "+84901234567", "84901234567")
    }
    assert keys == {("phone", "+84901234567")}


def test_one_name_with_two_numbers_is_two_keys() -> None:
    first = _single("p1", name="Nguyễn An", phone="0901 234 567")
    second = _single("p2", name="Nguyễn An", phone="0902 234 567")
    assert dedupe_key(first.lead) != dedupe_key(second.lead)


def test_the_number_wins_over_the_email_and_the_email_is_lower_case() -> None:
    assert dedupe_key(_single("p", phone="090-000-0101", email="A@example.com").lead) == (
        "phone",
        "+84900000101",
    )
    assert dedupe_key(_single("p", email=" An.Nguyen@Example.COM ").lead) == (
        "email",
        "an.nguyen@example.com",
    )


def test_a_lead_with_neither_number_nor_email_has_no_key() -> None:
    with pytest.raises(ValueError, match="neither"):
        dedupe_key(_single("p").lead)


@pytest.mark.parametrize("raw", ["12345", "+1 202 555 0100", "0901 234", "8490123456789"])
def test_a_number_that_is_not_vietnamese_is_not_normalised(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("kind", sorted(PAIR_KINDS))
def test_each_planted_pair_gives_one_key_per_person(seed: int, kind: str) -> None:
    pair = [x for x in generate(seed, 40) if x.planted == kind]
    people = {x.person_id for x in pair}
    keys = {dedupe_key(x.lead) for x in pair}
    assert len(pair) == 2
    assert len(people) == PAIR_KINDS[kind]
    assert len(keys) == len(people)
    if len(people) == 1:
        # What makes the pair a test of normalisation: the two leads are
        # written differently where the key is read.
        a, b = (x.lead for x in pair)
        assert (a.phone, a.email, a.name) != (b.phone, b.email, b.name)
        if a.phone is not None:
            assert a.phone != b.phone
        elif kind == "same_email_other_case":
            assert a.email != b.email


def test_the_measure_prints_three_numbers_with_no_wrong_merge(
    pilot: list[LabelledLead],
) -> None:
    out = io.StringIO()
    m = run(pilot, out)
    printed = out.getvalue()
    assert m.wrong_merges == 0
    assert m.same_person_pairs == sum(1 for n in PAIR_KINDS.values() if n == 1)
    for label in ("true_duplicate_rate:", "wrong_merges: 0", "missed_duplicate_rate:"):
        assert label in printed


def test_a_wrong_merge_is_counted() -> None:
    leads = [
        _single("p1", phone="0900 000 101"),
        _single("p2", phone="+84900000101", name="Trần Bình"),
        _single("p3", phone="0900 000 102"),
        _single("p3", phone="84900000102"),
    ]
    assert measure(leads).wrong_merges == 1


def test_a_person_with_a_number_then_only_an_email_is_missed() -> None:
    # The key's known limit (README): this person gets two keys.
    leads = [
        _single("p1", phone="0900 000 101", email="an@example.com"),
        _single("p1", email="AN@example.com"),
    ]
    m = measure(leads)
    assert (m.missed_pairs, m.missed_duplicate_rate) == (1, 1.0)


def test_a_variant_that_differs_only_in_name_makes_no_new_key(
    pilot: list[LabelledLead],
) -> None:
    for x in pilot:
        renamed = dataclasses.replace(x.lead, name=x.lead.name + " Khác")
        assert dedupe_key(renamed) == dedupe_key(x.lead)
    variant = dataclasses.replace(pilot[0], lead=dataclasses.replace(pilot[0].lead, name="Lê Khác"))
    assert measure([*pilot, variant]).keys == measure(pilot).keys


def test_readme_records_the_seed_the_key_and_what_the_measure_prints() -> None:
    out = io.StringIO()
    assert main([], out) == 0
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    assert f"```text\n{out.getvalue()}```" in readme
    assert f"seed {PILOT_SEED}, {PILOT_COUNT} leads" in readme
    assert "def dedupe_key(lead):" in readme


# ----------------------------------------------------------------------- R2.3 --


@pytest.mark.parametrize(
    "intruder",
    [
        _single("p_new", email="an@gmail.com"),
        _single("p_new", phone="+84901234567"),
        _single("p_new", email="an@example.com", message="Gửi vào an@gmail.com nhé."),
        _single("p_new", email="an@example.com", message="Gọi số 0901 234 567 giúp em."),
        _single("p_new", email="an@example.com", message="Gọi số 1234 5678 90 giúp em."),
        _single("p_new", email="an@example.com.vn"),
        _single("p_new", email="an@mail.example.com"),
        _single("p_new", email="an@b@example.com"),
        _single("p_new", phone="0900 0001"),
    ],
    ids=[
        "gmail",
        "number-outside-range",
        "gmail-in-message",
        "number-outside-range-in-message",
        "unreadable-number-in-message",
        "lookalike-domain",
        "subdomain",
        "two-at-signs",
        "unreadable-number",
    ],
)
def test_a_real_address_stops_the_measure_before_any_rate(
    pilot: list[LabelledLead], intruder: LabelledLead
) -> None:
    out = io.StringIO()
    with pytest.raises(NotSimulatedError):
        run([*pilot, intruder], out)
    assert out.getvalue() == ""


@pytest.mark.parametrize("labelled", [False, True], ids=["single", "labelled-as-a-duplicate"])
def test_the_check_ignores_the_label(pilot: list[LabelledLead], labelled: bool) -> None:
    twin = next(x for x in pilot if x.planted == "same_email_other_case")
    lead = dataclasses.replace(twin.lead, email="an@gmail.com")
    intruder = (
        dataclasses.replace(twin, lead=lead)
        if labelled
        else LabelledLead(person_id="p_new", planted=None, lead=lead)
    )
    with pytest.raises(NotSimulatedError, match=r"gmail\.com"):
        run([*pilot, intruder], io.StringIO())


def test_an_upper_case_example_address_is_synthetic() -> None:
    assert violations([_single("p", email="AN@EXAMPLE.COM", message="Mail AN@Example.Com.")]) == []


def test_the_error_names_the_domain_not_the_address() -> None:
    with pytest.raises(NotSimulatedError) as raised:
        run([_single("p", email="nguyen.an@gmail.com")], io.StringIO())
    assert "gmail.com" in str(raised.value)
    assert "nguyen.an" not in str(raised.value)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("count", [MIN_COUNT, 60, PILOT_COUNT])
def test_every_generated_set_is_synthetic(seed: int, count: int) -> None:
    assert violations(generate(seed, count)) == []


def test_every_planted_pair_kind_is_in_every_set() -> None:
    for seed in SEEDS:
        kinds: defaultdict[str, int] = defaultdict(int)
        for x in generate(seed, MIN_COUNT):
            if x.planted is not None:
                kinds[x.planted] += 1
        assert kinds == dict.fromkeys(PAIR_KINDS, 2)
