"""Probe the configured model gateway: one live call per generation route, then
the capability flags each non-mock route declares (model-connections R2.5).

Usage (reads DW_MODEL_PROVIDER, DW_API_MODEL_PROFILE, OPENAI_BASE_URL and
OPENAI_API_KEY from the environment; `make check-model` exports `.env`):
    make check-model
    make check-model PROFILE=gateway

Built the way the API and the worker build it (the shared `build_model_adapters`
and `build_model_resolver` of `dw_agent_runtime.adapters.model_stack`, the
profiles under `configs/models`), so a pass here means the processes' own model
calls reach the model this deployment configured. The key is never printed; the
endpoint is shown by host only.

The flags probed, per non-mock route (embedding aside):

- `strict_tools`: one call forced to a single `strict: true` tool; supported when
  the call answers and the arguments match the tool's schema;
- `numeric_bounds`: the same call with a schema holding `minimum`/`maximum`;
  supported when the call answers;
- `max_strict_tools` is not probed, and the report says so.

A declared flag that differs from what was probed prints the route, the flag,
the declared and the measured value. Needs the gateway's key, so not in CI; the
comparison itself is `compare_capabilities`, tested on its own.

Exit code is non-zero when any route fails, echoes the wrong token, or declares
a flag the probe contradicts.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

from dw_agent_runtime.model.profiles import ModelCapabilities, ModelRoute
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_platform.testing.residency import run_gate
from dw_usage.adapters.price_book_file import load_price_book

REPO_ROOT = Path(__file__).resolve().parents[1]

# Inline rather than under configs/prompts: a probe of the wiring, not an
# artifact a run uses, so it has no place in the release manifest.
_PROMPT = {
    "schema_version": "1.0",
    "prompt_id": "platform.check_model",
    "version": "1.0.0",
    "system": "You answer with a single JSON object and nothing else.",
    "template": 'Return {{"echo": "<token>"}} where <token> is exactly: {token}',
    "variables": frozenset({"token"}),
}
_PLAN = "probe"
_STRICT_TOOL = {
    "type": "function",
    "function": {
        "name": "pick_colour",
        "description": "Record the colour the user picked.",
        "parameters": {
            "type": "object",
            "properties": {"colour": {"type": "string", "enum": ["blue", "green"]}},
            "required": ["colour"],
            "additionalProperties": False,
        },
    },
}
_BOUNDED_TOOL = {
    "type": "function",
    "function": {
        "name": "pick_number",
        "description": "Record the number the user picked.",
        "parameters": {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 3, "maximum": 9}},
            "required": ["n"],
            "additionalProperties": False,
        },
    },
}
PROBED_FLAGS = ("strict_tools", "numeric_bounds")
NOT_PROBED = ("max_strict_tools",)


class Echo(BaseModel):
    echo: str


def compare_capabilities(declared: ModelCapabilities, probed: Mapping[str, bool]) -> list[str]:
    """One line per probed flag whose declared value differs from the probe:
    the flag, what the profile declares and what was measured. Empty when they
    agree. A flag the profile does not declare reads as unsupported."""
    lines = []
    for flag, measured in sorted(probed.items()):
        stated = bool(getattr(declared, flag))
        if stated != measured:
            lines.append(f"{flag}: declared {stated}, measured {measured}")
    return lines


async def _tool_call(model: Any, tool: dict[str, Any], ask: str) -> dict[str, Any] | None:
    """The forced tool call's arguments, or None when the provider refused it."""
    name = tool["function"]["name"]
    bound = model.bind_tools([tool], strict=True, tool_choice=name)
    try:
        answer = await bound.ainvoke(ask)
    except Exception:  # any refusal of the request is "not supported"
        return None
    calls = getattr(answer, "tool_calls", None) or []
    if len(calls) != 1 or calls[0].get("name") != name:
        return None
    args: dict[str, Any] = calls[0].get("args") or {}
    return args


async def probe_flags(route: ModelRoute, *, base_url: str, api_key: str) -> dict[str, bool]:
    from dw_agent_runtime.adapters.chat_model import openai_chat_model

    model = openai_chat_model(route, base_url=base_url, api_key=api_key)
    strict = await _tool_call(model, _STRICT_TOOL, "I pick green. Record it.")
    bounded = await _tool_call(model, _BOUNDED_TOOL, "I pick 5. Record it.")
    return {
        # The arguments match the schema: the one key, a value of its enum.
        "strict_tools": strict is not None
        and set(strict) == {"colour"}
        and strict["colour"] in ("blue", "green"),
        "numeric_bounds": bounded is not None,
    }


async def probe(profile_id: str | None = None) -> int:
    from dw_agent_runtime.adapters.model_stack import build_model_adapters, build_model_resolver
    from dw_agent_runtime.contracts import RunContext
    from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, RoutingModelGateway
    from dw_agent_runtime.model.prompts import PromptArtifact, PromptRegistry
    from dw_agent_runtime.model.resolver import StaticPlanModelProfiles
    from dw_agent_runtime.ports import ModelRequest, RouteKind
    from dw_api.bootstrap.models import model_provider_config
    from dw_api.bootstrap.paths import MOCK_MODEL_FIXTURES
    from dw_api.settings import ApiSettings

    settings = ApiSettings()
    if profile_id:
        settings = settings.model_copy(update={"model_profile": profile_id})
    config = model_provider_config(settings)
    models = build_model_resolver(
        config,
        profiles_dir=REPO_ROOT / "configs" / "models",
        # The probe's plan lists the one profile it probes.
        plans=StaticPlanModelProfiles({_PLAN: frozenset({settings.model_profile})}),
    )
    profile = models.platform_profile(settings.model_profile)
    prompts = PromptRegistry()
    prompts.register(PromptArtifact.model_validate(_PROMPT))
    recorder = InMemoryUsageRecorder()
    gateway = RoutingModelGateway(
        models=models,
        prompts=prompts,
        adapters=build_model_adapters(config, mock_fixtures_dir=MOCK_MODEL_FIXTURES),
        usage_recorder=recorder,
        pricing=load_price_book(),
        run_control=OpenRunControl(),
        # Every model call passes the gate, the probe's too (ADR-0123 decision 4).
        residency=run_gate(),
    )
    host = urlsplit(settings.openai_base_url or "").hostname or "(no OPENAI_BASE_URL)"
    print(f"provider={settings.model_provider} profile={profile.profile_id} endpoint={host}")

    failures = 0
    routes: dict[RouteKind, ModelRoute] = {
        "structured_extraction": profile.structured_extraction,
        "reasoning": profile.reasoning,
    }
    for kind, route in routes.items():
        token = uuid.uuid4().hex[:8]
        run_context = RunContext(
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            worker_id="platform.check_model",
            worker_version="1.0.0",
            channel="web",
            plan_id=_PLAN,
            roles=frozenset(),
            scopes=frozenset(),
            trace_id="check-model",
            # The probe sends a random token and no tenant's content, to every
            # route a profile declares, foreign ones included: the operator's
            # measurement of a route, never a run of a tenant (compliance-pdpl
            # 03, decided under delegation 31/10/2026).
            route_class="cross_border_full",
        )
        request = ModelRequest(
            task=kind,
            prompt_id="platform.check_model",
            prompt_version="1.0.0",
            variables={"token": token},
            route_kind=kind,
        )
        label = f"{kind:<22} {route.provider}/{route.model}"
        try:
            output = await gateway.generate_structured(request, Echo, run_context=run_context)
        except Exception as exc:  # a probe reports every failure and moves on
            failures += 1
            print(f"FAIL {label}: {type(exc).__name__}: {_redacted(str(exc), settings)}")
            continue
        _run, usage = recorder.records[-1]
        verdict = "ok  " if output.echo == token else "FAIL"
        failures += verdict == "FAIL"
        print(
            f"{verdict} {label} answered by {usage.model}: in={usage.input_tokens} "
            f"out={usage.output_tokens} cost=${usage.cost_usd:.5f} {usage.latency_ms:.0f}ms"
        )

    if not (settings.openai_base_url and settings.openai_api_key):
        print("capabilities: not probed (no OPENAI_BASE_URL / OPENAI_API_KEY)")
        return 1 if failures else 0
    seen: set[tuple[str, str]] = set()
    for name, dumped in profile.pinned_routes().items():
        parsed = ModelRoute.model_validate(dumped)
        if parsed.provider == "mock" or (parsed.provider, parsed.model) in seen:
            continue
        seen.add((parsed.provider, parsed.model))
        label = f"{name:<22} {parsed.provider}/{parsed.model}"
        probed = await probe_flags(
            parsed, base_url=settings.openai_base_url, api_key=settings.openai_api_key
        )
        drift = compare_capabilities(parsed.capabilities, probed)
        failures += len(drift)
        measured = ", ".join(f"{flag}={value}" for flag, value in probed.items())
        print(f"{'FAIL' if drift else 'ok  '} {label} {measured}")
        for line in drift:
            print(f"     {label} {line}")
        print(f"     {label} {', '.join(NOT_PROBED)}: not probed")
    return 1 if failures else 0


def _redacted(message: str, settings: Any) -> str:
    if settings.openai_api_key:  # never let a provider echo the key
        return str(message.replace(settings.openai_api_key, "***"))
    return message


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return asyncio.run(probe(os.environ.get("PROFILE") or None))


if __name__ == "__main__":
    raise SystemExit(main())
