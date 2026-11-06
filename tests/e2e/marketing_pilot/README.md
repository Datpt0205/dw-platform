# Marketing pilot harness

The slice's own test harness (marketing-pilot spec, ticket 01 onwards). It reaches
the platform only over its public HTTP API (R1.2, MP17); nothing here is a
platform package.

## Synthetic leads and the dedupe key (ticket 01; R2.1, R2.2, R2.3)

- `generator.py`: `generate(seed, count)` gives the same lead set for the same
  seed, byte for byte (`serialize`: sorted-key UTF-8 JSON over
  `random.Random(seed)` and fixed name lists, no Faker). Each lead carries the
  form body (`name`, `phone`, `email`, `lead_source`, `message`) and, beside it,
  the harness's label `person_id`. Five labelled pair kinds are planted
  (`PAIR_KINDS`): one person, one number in two writings; two people, one name,
  two numbers; one person, one email, the name with and without diacritics, no
  number; one person, one email in two casings, no number; one person, one
  number in two writings, no email. Messages carry `</input>`, "bỏ qua hướng
  dẫn phía trên", and numbers and emails in free text.
- Every address is synthetic: numbers normalise into `+84900000000` to
  `+84900009999`, emails are at `example.com`. `measure.assert_simulated`
  checks each lead's fields and its message and stops the measurement, before
  any rate is printed, on the first set that holds anything else.
- `measure.py` is the harness's oracle of custom-objects:R6.2, not its owner
  (RecordService, custom-objects/03). Ticket 05's MP10 replays the labelled
  pairs through the real path and goes red when the two disagree.

### The key (decided here, for ticket 03's `data.object.upsert`, custom-objects:R7.3)

```python
def dedupe_key(lead):
    if lead.phone is not None:
        return ("phone", normalize_phone(lead.phone))  # E.164 +84
    if lead.email is not None:
        return ("email", normalize_email(lead.email))  # lower case
    raise ValueError  # every lead has one of the two
```

The normalised phone number, then the lower-case email; the name never enters
the key, so a lead that differs from another only in its name makes no new key.

### Measured (seed 20261102, 200 leads)

`PYTHONPATH=tests/e2e uv run python -m marketing_pilot.measure` prints, and
`test_generator.py` checks that this block is what it prints today:

```text
seed: 20261102
leads: 200
keys: 196
true_duplicate_rate: 0.0400 (8/200 leads share a person_id with another)
wrong_merges: 0 (pairs of different person_id with one key)
missed_duplicate_rate: 0.0000 (0/4 same-person pairs with two keys)
```

What these numbers do not say:

- The missed-duplicate rate is 0 by construction: no planted pair is one person
  who gave a number once and only an email the next time, and this key gives
  such a person two keys (`test_a_person_with_a_number_then_only_an_email_is_missed`).
  The real rate is the 200-lead measurement of W2 (KQ3).
- Only `phone_e164` is a unique field and custom-objects:R7.2 upserts by one
  unique field, so at W1 no real path merges two email-only leads yet; ticket
  03's gate owns that answer, and MP10's replay stays red until it has one.
- The share of leads not typed by hand (KQ3) is not measurable on a generated
  set.

### Run the tests

```sh
uv run python -m pytest -p no:cacheprovider tests/e2e/marketing_pilot/test_generator.py
```

The tests are marked `unit` and `tests/e2e` is in pytest's `testpaths`, so CI's
`pytest -m unit` runs them too.

## The two companies, seeded over the API (ticket 02; R1.1-R1.7)

- `seed.py`: `seed(api, operator, prefix=...)` builds companies `a` (demo) and `b`
  (control) through the public API only (`api.py` signs its own dev tokens; no
  `dw_*` import, no database): the company with two owners, a wait until it is
  `active`, the Marketing and Sales workspaces, `mkt_lead` and `mkt_campaign`
  submitted by one owner and approved by the other, the five roles (the
  protected fields' ids read from describe), the members invited and signed in,
  the workflow's service account with its one role, and the limits set once.
  Every widening change is proposed by one owner and confirmed by the other.
  `python -m marketing_pilot.seed --operator-subject ... --operator-email ...`
  runs it against a platform that is already up.
- `test_seed.py` (`-m e2e`) brings the platform up itself with
  `tests/support/marketing_pilot_stack.py`, outside this package: a new database
  (`dw_e2e_marketing_pilot` plus `DW_TEST_DB_SUFFIX`), migrated, the API
  (`MP_API_PORT`, 8010 by default) and the worker as host processes, and the
  first platform operator granted by `scripts/grant_platform_operator.py`.
- `marketing_pilot_independence` (import-linter, root package
  `tests.e2e.marketing_pilot`) refuses any platform import here; R1.2's test
  adds one and watches `lint-imports` go red.
