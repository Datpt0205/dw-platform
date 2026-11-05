"""What the platform's JSON Schema door costs on a 30-property schema (discovery 16, FOG-58).

    uv run python scripts/bench_json_schema.py [--n 10000] [--seed 16] [--out FILE.json]

Drives `dw_platform.application.json_schema`'s tool door (`tool_validator_for`,
`tool_problems`: Draft 2020-12, the closed format list with `phone_vn`, an
empty registry), the one a tool's input and output and an event's payload pass
through, and reports p50/p95/p99 in microseconds per case:

- `prebuilt.iter_errors`: the validator held, every error of a value collected;
- `prebuilt.tool_problems`: the door as a caller uses it, its LRU warm, so the
  canonical JSON of the schema and the cache lookup are in the number;
- `per_call.tool_problems`: a validator built on every call, the schema made
  distinct per call with a `$comment` nonce so the door's LRU never hits
  (`check_schema`, construction, then the check);
- `narrow_<k>.only`: the narrowing alone, no validator: what the planned design
  pays per model call, where the model sees the narrowed schema and the
  executor checks the full pinned one (tools-and-skills 03 step 4);
- `narrow_<k>.build`: per run, `k` fields (5, then 15) dropped from
  `properties` and `required` by field security's own narrowing
  (`dw_studio.records.application.schema_projector.narrowed`, which RecordService
  applies after its schema cache on every call), and the door builds the
  narrowed validator (nonce again, so every one is a miss);
- `narrow_<k>.warm`: the same narrowing whose result the door's LRU already
  holds (keyed by the narrowed schema's canonical JSON);
- `narrow_<k>.tenant_cache`: the narrowing looked up in a cache keyed by
  (tenant, SHA-256 of the narrowed schema's canonical JSON), the mitigation the
  ticket names for a missed narrowing line, on a hit;
- `narrow_<k>.evolve`: the narrowed validator made by `evolve(schema=...)` from
  the full one already checked, so `check_schema` is not run again (removing
  properties from a valid schema leaves a valid one); format checker and empty
  registry carry over;
- `check_schema`: Draft 2020-12's meta-schema check of the full schema alone,
  the part of a build that is not construction.

Each case runs on valid and on invalid vectors (one to three faults each:
wrong phone, missing field, extra field, wrong type, out of range, enum, an
offset-less date-time, a malformed tax code). Pass lines of the ticket: the
prebuilt check p95 at most 1 ms, one narrowing p95 at most 5 ms. Not a test:
nothing here is in `testpaths`, and it needs no database.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform as host
import random
import sys
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from dw_kernel.pagination import canonical_json
from dw_platform.application.json_schema import tool_problems, tool_validator_for
from dw_studio.records.application.schema_projector import AiDescriptions, ObjectSchemas
from dw_studio.records.application.schema_projector import narrowed as field_security_narrowed

PREBUILT_P95_US = 1_000.0
NARROWING_P95_US = 5_000.0
WARMUP = 200

_SEGMENTS = ["smb", "mid", "enterprise", "public", "individual"]
_SOURCES = ["web", "zalo", "facebook", "referral", "event", "cold_call"]
_CHANNELS = ["email", "phone", "zalo", "sms"]
_GENDERS = ["female", "male", "other", "unknown"]
_PROVINCES = ["Hà Nội", "TP Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ"]

_STR = {"type": "string", "minLength": 1, "maxLength": 200}
_OBJECT_ID = uuid.UUID(int=16)


def thirty_property_schema() -> dict[str, Any]:
    """A lead record as a tool takes it: every format the door checks, all required."""
    properties: dict[str, Any] = {
        "full_name": _STR,
        "phone": {"type": "string", "format": "phone_vn"},
        "alt_phone": {"type": "string", "format": "phone_vn"},
        "email": {"type": "string", "format": "email"},
        "customer_id": {"type": "string", "format": "uuid"},
        "birth_date": {"type": "string", "format": "date"},
        "created_at": {"type": "string", "format": "date-time"},
        "tax_code": {"type": "string", "format": "tax_code_vn"},
        "age": {"type": "integer", "minimum": 0, "maximum": 150},
        "credit_limit": {"type": "number", "minimum": 0},
        "is_vip": {"type": "boolean"},
        "segment": {"enum": _SEGMENTS},
        "tags": {
            "type": "array",
            "items": {"type": "string", "maxLength": 40},
            "maxItems": 10,
            "uniqueItems": True,
        },
        "address": {
            "type": "object",
            "properties": {"street": _STR, "ward": _STR, "province": _STR},
            "required": ["street", "ward", "province"],
            "additionalProperties": False,
        },
        "province_code": {"type": "string", "pattern": "^[0-9]{2}$"},
        "note": {"type": "string", "maxLength": 2000},
        "source": {"enum": _SOURCES},
        "consent": {"type": "boolean"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "discount": {"type": "number", "minimum": 0, "maximum": 1},
        "company": _STR,
        "job_title": _STR,
        "gender": {"enum": _GENDERS},
        "national_id": {"type": "string", "pattern": "^[0-9]{12}$"},
        "last_contact": {"type": "string", "format": "date-time"},
        "next_follow_up": {"type": "string", "format": "date"},
        "owner_id": {"type": "string", "format": "uuid"},
        "channel": {"enum": _CHANNELS},
        "order_count": {"type": "integer", "minimum": 0},
        "lifetime_value": {"type": "number", "minimum": 0},
    }
    assert len(properties) == 30
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _phone(rng: random.Random) -> str:
    national = rng.choice("3579") + "".join(rng.choice("0123456789") for _ in range(8))
    return rng.choice(["0", "+84 ", "84"]) + national


def valid_vector(rng: random.Random) -> dict[str, Any]:
    now = datetime(2026, 11, 5, tzinfo=UTC)
    return {
        "full_name": f"Nguyễn Văn {rng.randint(1, 9999)}",
        "phone": _phone(rng),
        "alt_phone": "0168 456 " + "".join(rng.choice("0123456789") for _ in range(4)),
        "email": f"lead{rng.randint(1, 99999)}@vidu.vn",
        "customer_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "birth_date": (date(1960, 1, 1) + timedelta(days=rng.randint(0, 20000))).isoformat(),
        "created_at": (now - timedelta(minutes=rng.randint(0, 10**6))).isoformat(),
        "tax_code": "".join(rng.choice("0123456789") for _ in range(10)),
        "age": rng.randint(18, 90),
        "credit_limit": round(rng.uniform(0, 5e8), 2),
        "is_vip": rng.random() < 0.1,
        "segment": rng.choice(_SEGMENTS),
        "tags": rng.sample(["hot", "cold", "q4", "re-engage", "partner", "vip"], rng.randint(0, 4)),
        "address": {
            "street": f"{rng.randint(1, 300)} Lê Lợi",
            "ward": f"Phường {rng.randint(1, 20)}",
            "province": rng.choice(_PROVINCES),
        },
        "province_code": f"{rng.randint(1, 96):02d}",
        "note": "Khách hỏi giá gói doanh nghiệp. " * rng.randint(0, 10),
        "source": rng.choice(_SOURCES),
        "consent": True,
        "score": rng.randint(0, 100),
        "discount": round(rng.random(), 3),
        "company": f"Công ty TNHH {rng.randint(1, 999)}",
        "job_title": rng.choice(["Giám đốc", "Kế toán", "Trưởng phòng mua hàng"]),
        "gender": rng.choice(_GENDERS),
        "national_id": "".join(rng.choice("0123456789") for _ in range(12)),
        "last_contact": (now - timedelta(hours=rng.randint(0, 2000))).isoformat(),
        "next_follow_up": (date(2026, 11, 5) + timedelta(days=rng.randint(1, 60))).isoformat(),
        "owner_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "channel": rng.choice(_CHANNELS),
        "order_count": rng.randint(0, 50),
        "lifetime_value": round(rng.uniform(0, 1e9), 2),
    }


_FAULTS: list[Callable[[dict[str, Any], random.Random], None]] = [
    lambda v, r: v.__setitem__("phone", "04 3825 " + str(r.randint(1000, 9999))),
    lambda v, r: v.__setitem__("alt_phone", str(r.randint(10000, 99999))),
    lambda v, r: v.pop(r.choice(sorted(v))),
    lambda v, r: v.__setitem__("unexpected", "x"),
    lambda v, r: v.__setitem__("age", str(v.get("age", 30))),
    lambda v, r: v.__setitem__("score", 101 + r.randint(0, 50)),
    lambda v, r: v.__setitem__("segment", "unknown"),
    lambda v, r: v.__setitem__("created_at", "2026-11-05T10:00:00"),
    lambda v, r: v.__setitem__("tax_code", "12345"),
    lambda v, r: v.__setitem__("email", "not-an-email"),
]


def invalid_vector(rng: random.Random) -> dict[str, Any]:
    value = valid_vector(rng)
    for fault in rng.sample(_FAULTS, rng.randint(1, 3)):
        fault(value, rng)
    return value


def narrowed(schema: dict[str, Any], hidden: Sequence[str]) -> dict[str, Any]:
    """`schema` without `hidden`, by field security's own narrowing: RecordService's
    `narrowed` over the create, update and query schemas, as one call pays it; the
    create schema comes back."""
    visible = frozenset(schema["properties"]) - frozenset(hidden)
    full = ObjectSchemas(
        object_id=_OBJECT_ID,
        schema_version=1,
        create=schema,
        update=schema,
        query=schema,
        sortable=(),
        ai_descriptions=AiDescriptions(object=None, fields={}),
    )
    out = field_security_narrowed(full, readable=visible, editable=visible, creatable=visible)
    return dict(out.create)


class TenantValidatorCache:
    """An LRU of validators keyed by (tenant, SHA-256 of the schema's canonical JSON)."""

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._entries: OrderedDict[tuple[str, str], Draft202012Validator] = OrderedDict()

    def get(self, tenant_id: str, schema: dict[str, Any]) -> Draft202012Validator:
        key = (tenant_id, hashlib.sha256(canonical_json(schema).encode()).hexdigest())
        found = self._entries.get(key)
        if found is not None:
            self._entries.move_to_end(key)
            return found
        built = tool_validator_for(schema)
        self._entries[key] = built
        if len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)
        return built


def percentile(samples: Sequence[float], q: float) -> float:
    """Nearest rank, as `scripts/bench_records_storage` reports it."""
    ordered = sorted(samples)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def measure(n: int, call: Callable[[int], object]) -> dict[str, float]:
    for i in range(WARMUP):
        call(-1 - i)
    gc.collect()
    samples: list[float] = []
    for i in range(n):
        start = time.perf_counter_ns()
        call(i)
        samples.append((time.perf_counter_ns() - start) / 1_000)
    return {
        "n": n,
        "p50_us": percentile(samples, 0.50),
        "p95_us": percentile(samples, 0.95),
        "p99_us": percentile(samples, 0.99),
        "max_us": max(samples),
    }


def run(n: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    schema = thirty_property_schema()
    pool = 500
    vectors = {
        "valid": [valid_vector(rng) for _ in range(pool)],
        "invalid": [invalid_vector(rng) for _ in range(pool)],
    }
    validator = tool_validator_for(schema)
    for value in vectors["valid"]:
        assert not tool_problems(schema, value), tool_problems(schema, value)
    for value in vectors["invalid"]:
        assert tool_problems(schema, value)

    # `evolve` keeps the door's format checker: a narrowed validator made that way
    # still refuses a bad `phone_vn` and a field the narrowing hid.
    evolved = validator.evolve(schema=narrowed(schema, ["note"]))
    sample = {k: v for k, v in vectors["valid"][0].items() if k != "note"}
    assert evolved.is_valid(sample)
    assert not evolved.is_valid({**sample, "phone": "04 3825 1234"})
    assert not evolved.is_valid({**sample, "note": "x"})

    cases: dict[str, dict[str, float]] = {}
    for kind, values in vectors.items():

        def raw(i: int, values: list[dict[str, Any]] = values) -> object:
            return list(validator.iter_errors(values[i % pool]))

        def door(i: int, values: list[dict[str, Any]] = values) -> object:
            return tool_problems(schema, values[i % pool])

        def fresh(i: int, values: list[dict[str, Any]] = values, kind: str = kind) -> object:
            return tool_problems({**schema, "$comment": f"{kind}:{i}"}, values[i % pool])

        cases[f"prebuilt.iter_errors/{kind}"] = measure(n, raw)
        cases[f"prebuilt.tool_problems/{kind}"] = measure(n, door)
        cases[f"per_call.tool_problems/{kind}"] = measure(n, fresh)

    names = sorted(schema["properties"])
    tenant = str(uuid.UUID(int=rng.getrandbits(128), version=4))
    for k in (5, 15):
        hidden = [rng.sample(names, k) for _ in range(pool)]

        def build(i: int, hidden: list[list[str]] = hidden, k: int = k) -> object:
            narrow = narrowed(schema, hidden[i % pool])
            return tool_validator_for({**narrow, "$comment": f"narrow{k}:{i}"})

        fixed = hidden[0]
        tool_validator_for(narrowed(schema, fixed))

        def warm(_: int, fixed: list[str] = fixed) -> object:
            return tool_validator_for(narrowed(schema, fixed))

        tenant_cache = TenantValidatorCache()
        tenant_cache.get(tenant, narrowed(schema, fixed))

        def cached(
            _: int, fixed: list[str] = fixed, c: TenantValidatorCache = tenant_cache
        ) -> object:
            return c.get(tenant, narrowed(schema, fixed))

        def evolve(i: int, hidden: list[list[str]] = hidden) -> object:
            return validator.evolve(schema=narrowed(schema, hidden[i % pool]))

        def only(i: int, hidden: list[list[str]] = hidden) -> object:
            return narrowed(schema, hidden[i % pool])

        cases[f"narrow_{k}.only"] = measure(n, only)
        cases[f"narrow_{k}.build"] = measure(n, build)
        cases[f"narrow_{k}.warm"] = measure(n, warm)
        cases[f"narrow_{k}.tenant_cache"] = measure(n, cached)
        cases[f"narrow_{k}.evolve"] = measure(n, evolve)

    cases["check_schema"] = measure(n, lambda _: Draft202012Validator.check_schema(schema))

    prebuilt_p95 = max(
        cases["prebuilt.tool_problems/valid"]["p95_us"],
        cases["prebuilt.tool_problems/invalid"]["p95_us"],
    )
    narrowing_p95 = max(cases["narrow_5.build"]["p95_us"], cases["narrow_15.build"]["p95_us"])
    return {
        "host": {
            "python": sys.version.split()[0],
            "implementation": host.python_implementation(),
            "platform": host.platform(),
            "cpus": os.cpu_count(),
            "jsonschema": version("jsonschema"),
            "referencing": version("referencing"),
            "rpds-py": version("rpds-py"),
        },
        "n": n,
        "seed": seed,
        "cases": cases,
        "pass": {
            "prebuilt_p95_le_1ms": prebuilt_p95 <= PREBUILT_P95_US,
            "narrowing_p95_le_5ms": narrowing_p95 <= NARROWING_P95_US,
        },
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--n", type=int, default=10_000, help="timed calls per case")
    parser.add_argument("--seed", type=int, default=16)
    parser.add_argument("--out", type=Path, help="also write the result as JSON here")
    args = parser.parse_args(argv)
    result = run(args.n, args.seed)
    print(json.dumps(result["host"]))
    print(f"{'case':38} {'p50 us':>10} {'p95 us':>10} {'p99 us':>10} {'max us':>10}")
    for name, row in result["cases"].items():
        print(
            f"{name:38} {row['p50_us']:>10.1f} {row['p95_us']:>10.1f}"
            f" {row['p99_us']:>10.1f} {row['max_us']:>10.1f}"
        )
    print(json.dumps(result["pass"]))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
