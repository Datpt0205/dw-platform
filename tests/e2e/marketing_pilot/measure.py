"""The dedupe oracle and its measurement over a labelled lead set.

marketing-pilot R2.2: a number is normalised to E.164 `+84`, an email to lower
case, as custom-objects:R6.2 says RecordService stores them, and a lead's key is
`("phone", e164)` when it has a number, `("email", lower case)` otherwise; the
name is never part of the key (YC95).

This normaliser is the harness's ORACLE, not the owner of the rule: the owner is
RecordService (custom-objects/03). Ticket 05's MP10 replays the labelled pairs
through the real path, so the day the two disagree a test goes red instead of
this file quietly measuring a copy (ticket 01 Comments, H3).

R2.3, the generator's half: `assert_simulated` refuses a set holding any address
that is not synthetic, in a lead's fields or in its message, whatever its label,
and `run` calls it before it prints any rate.

    PYTHONPATH=tests/e2e uv run python -m marketing_pilot.measure [--seed N] [--count N]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

from marketing_pilot.generator import EMAIL_DOMAIN, TEST_RANGE, LabelledLead, Lead, generate

# The set README.md records and ticket 03 configures the upsert from.
PILOT_SEED = 20261102
PILOT_COUNT = 200

_SEPARATORS = re.compile(r"[\s.\-()]")
# A Vietnamese subscriber number after the country code: a mobile (3, 5, 7, 8 or
# 9, then eight digits) or a landline (2, then nine digits).
_SUBSCRIBER = re.compile(r"[35789]\d{8}|2\d{9}")
# In free text, any run of nine or more digits with single separators is read as
# a phone number and must normalise into the test range: a number the oracle
# cannot read fails the check, it is not skipped (failure-modes #7).
_PHONE_IN_TEXT = re.compile(r"\+?\d(?:[ .\-]?\d){8,}")
# Anything with an `@` between two non-blank runs is read as an email address.
_EMAIL_IN_TEXT = re.compile(r"[^\s<>()\[\]\"',;:]+@[^\s<>()\[\]\"',;:]+")


def normalize_phone(raw: str) -> str:
    """ "0901 234 567", "+84901234567" and "84901234567" -> "+84901234567"."""
    digits = _SEPARATORS.sub("", raw)
    if digits.startswith("+84"):
        subscriber = digits[3:]
    elif digits.startswith("84") and len(digits) in (11, 12):
        subscriber = digits[2:]
    elif digits.startswith("0"):
        subscriber = digits[1:]
    else:
        raise ValueError("not a Vietnamese phone number")
    if _SUBSCRIBER.fullmatch(subscriber) is None:
        raise ValueError("not a Vietnamese phone number")
    return f"+84{subscriber}"


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def dedupe_key(lead: Lead) -> tuple[str, str]:
    """The number when there is one, the email otherwise; never the name."""
    if lead.phone is not None:
        return ("phone", normalize_phone(lead.phone))
    if lead.email is not None:
        return ("email", normalize_email(lead.email))
    raise ValueError("a lead has neither a phone nor an email")


# ---------------------------------------------------------------- R2.3 check --


class NotSimulatedError(Exception):
    """The set holds an address that is not synthetic; nothing is measured."""


def phones_in_text(text: str) -> list[str]:
    return _PHONE_IN_TEXT.findall(text)


def emails_in_text(text: str) -> list[str]:
    return _EMAIL_IN_TEXT.findall(text)


def _phone_problem(raw: str) -> str | None:
    try:
        e164 = normalize_phone(raw)
    except ValueError:
        return "a number the oracle cannot read"
    if int(e164[1:]) not in TEST_RANGE:
        return "a number outside the test range"
    return None


def _email_problem(raw: str) -> str | None:
    address = normalize_email(raw).rstrip(".")
    if address.count("@") != 1:
        return "an address with more than one @"
    domain = address.rpartition("@")[2]
    if domain != EMAIL_DOMAIN:
        # The domain only: the error must not repeat a real person's address.
        return f"an address at {domain!r}, not {EMAIL_DOMAIN!r}"
    return None


def violations(leads: Sequence[LabelledLead]) -> list[str]:
    """Every non-synthetic address in the set, as `#index person field: what`."""
    found: list[str] = []
    for index, labelled in enumerate(leads):
        lead = labelled.lead
        where = f"#{index} {labelled.person_id}"
        checks: list[tuple[str, str | None]] = []
        if lead.phone is not None:
            checks.append(("phone", _phone_problem(lead.phone)))
        if lead.email is not None:
            checks.append(("email", _email_problem(lead.email)))
        checks += [("message", _phone_problem(m)) for m in phones_in_text(lead.message)]
        checks += [("message", _email_problem(m)) for m in emails_in_text(lead.message)]
        found += [f"{where} {field}: {problem}" for field, problem in checks if problem]
    return found


def assert_simulated(leads: Sequence[LabelledLead]) -> None:
    found = violations(leads)
    if found:
        raise NotSimulatedError(
            f"{len(found)} address(es) in the lead set are not synthetic: " + "; ".join(found)
        )


# --------------------------------------------------------------- measurement --


@dataclass(frozen=True)
class Measurement:
    leads: int
    keys: int
    duplicated_leads: int  # leads sharing their person_id with another lead
    wrong_merges: int  # pairs of different person_id with one key
    same_person_pairs: int
    missed_pairs: int  # pairs of one person_id with two keys

    @property
    def true_duplicate_rate(self) -> float:
        return self.duplicated_leads / self.leads

    @property
    def missed_duplicate_rate(self) -> float:
        return self.missed_pairs / self.same_person_pairs


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def measure(leads: Sequence[LabelledLead]) -> Measurement:
    """The three numbers of ticket 01 item 4, counted per group rather than per
    pair so a large set costs one pass."""
    if not leads:
        raise ValueError("an empty set measures nothing")
    keys = [dedupe_key(x.lead) for x in leads]
    per_person = Counter(x.person_id for x in leads)
    per_key = Counter(keys)
    per_key_and_person = Counter(zip(keys, (x.person_id for x in leads), strict=True))
    same_person_pairs = sum(_pairs(n) for n in per_person.values())
    if same_person_pairs == 0:
        # A missed-duplicate rate of 0/0 would read as "none missed".
        raise ValueError("the set has no same-person pair; the missed rate is undefined")
    same_person_same_key = sum(_pairs(n) for n in per_key_and_person.values())
    return Measurement(
        leads=len(leads),
        keys=len(per_key),
        duplicated_leads=sum(n for n in per_person.values() if n > 1),
        wrong_merges=sum(_pairs(n) for n in per_key.values()) - same_person_same_key,
        same_person_pairs=same_person_pairs,
        missed_pairs=same_person_pairs - same_person_same_key,
    )


def report(m: Measurement) -> str:
    return "\n".join(
        (
            f"leads: {m.leads}",
            f"keys: {m.keys}",
            f"true_duplicate_rate: {m.true_duplicate_rate:.4f}"
            f" ({m.duplicated_leads}/{m.leads} leads share a person_id with another)",
            f"wrong_merges: {m.wrong_merges} (pairs of different person_id with one key)",
            f"missed_duplicate_rate: {m.missed_duplicate_rate:.4f}"
            f" ({m.missed_pairs}/{m.same_person_pairs} same-person pairs with two keys)",
        )
    )


def run(leads: Sequence[LabelledLead], out: TextIO, header: str = "") -> Measurement:
    """Refuse a non-synthetic set before anything is printed, then print."""
    assert_simulated(leads)
    m = measure(leads)
    out.write(header + report(m) + "\n")
    return m


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--seed", type=int, default=PILOT_SEED)
    parser.add_argument("--count", type=int, default=PILOT_COUNT)
    args = parser.parse_args(argv)
    run(generate(args.seed, args.count), out, header=f"seed: {args.seed}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
