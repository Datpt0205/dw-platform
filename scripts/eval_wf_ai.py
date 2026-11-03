"""The workflow assistant's prompt-injection eval (wf-ai R5.2, R5.3): `make eval-wf-ai`.

Runs `evals/datasets/wf_ai_injection_v1.jsonl` through `WorkflowAssistant`
against the real model the deployment configured (OPENAI_* in `.env`, as
`make check-model`), on the Marketing pack's `lead_care@1.0.0`. A case may
plant an instruction in what the person typed, in a step's description of the
base document (`base_description`) or in a forged earlier assistant turn; the
grader named by `expect` (`dw_agent_runtime.testing.wf_ai.GRADERS`) decides.
Not in CI: it needs a model key. Exit non-zero on any failure.

One case's unreadable answer (`ModelOutputInvalidError`) or provider failure
(`InfrastructureError`) is a `FAIL <id>: <error>` line and the run goes on; a
`ConfigError` (a schema the adapter refuses is the code's fault, not a case's)
or any other error stops the run (wf-ai/05). Every line also prints the
answer's `kind`, whether it is `publishable` and its `wf.*` codes.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from dw_agent_runtime.ports import ModelGateway

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "evals" / "datasets" / "wf_ai_injection_v1.jsonl"
CONFIGS = REPO_ROOT / "configs"


def live_gateway() -> ModelGateway:
    """The gateway the deployment configured (`DW_MODEL_PROVIDER`, `DW_API_MODEL_PROFILE`)."""
    from dw_agent_runtime.adapters.model_stack import build_model_adapters
    from dw_agent_runtime.model.gateway import InMemoryUsageRecorder, RoutingModelGateway
    from dw_agent_runtime.model.profiles import ModelProfileRegistry
    from dw_agent_runtime.model.prompts import PromptRegistry
    from dw_api.bootstrap.models import model_provider_config
    from dw_api.bootstrap.paths import MOCK_MODEL_FIXTURES
    from dw_api.settings import ApiSettings

    settings = ApiSettings()
    profiles = ModelProfileRegistry()
    profiles.load_directory(CONFIGS / "models")
    prompts = PromptRegistry()
    prompts.load_directory(CONFIGS / "prompts")
    adapters = build_model_adapters(
        model_provider_config(settings), mock_fixtures_dir=MOCK_MODEL_FIXTURES
    )
    profile = profiles.resolve(settings.model_profile).profile_id
    # Which model answered, said before any case: `.env` says mock, and a Make
    # variable from `include .env` beats one set in the shell (3/11/2026), so a
    # "live" run could be the fixture five times without this line.
    print(f"profile {profile}, adapters {', '.join(sorted(adapters))}", file=sys.stderr)
    return RoutingModelGateway(
        profiles=profiles,
        prompts=prompts,
        adapters=adapters,
        usage_recorder=InMemoryUsageRecorder(),
        default_profile=profile,
    )


async def run(
    gateway: ModelGateway | None = None,
    dataset: Path = DATASET,
    out: Callable[[str], None] = print,
) -> int:
    from dw_agent_runtime.contracts import RunContext
    from dw_agent_runtime.ports import ModelOutputInvalidError
    from dw_agent_runtime.testing.wf_ai import GRADERS
    from dw_agent_runtime.wflite.assistant import HistoryTurn, WorkflowAssistant
    from dw_agent_runtime.wflite.catalog import ShippedToolSpecs, load_shipped_packs
    from dw_agent_runtime.wflite.registry import build_node_registry
    from dw_kernel.errors import InfrastructureError
    from dw_platform.application.access_context import AccessContext
    from dw_platform.domain.digital_worker import (
        DecisionClass,
        DigitalWorker,
        DwConfiguration,
        DwPeople,
    )

    gateway = gateway or live_gateway()
    packs = load_shipped_packs(CONFIGS)
    pinned = packs.workflow("lead_care", "1.0.0")
    assert pinned is not None
    tenant, workspace, owner = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    worker = DigitalWorker(
        id=uuid.uuid4(),
        tenant_id=tenant,
        workspace_id=workspace,
        principal_user_id=uuid.uuid4(),
        configuration=DwConfiguration(
            key="lead_care",
            name="Chăm sóc lead",
            mandate="eval",
            work_kinds=("marketing.lead",),
            allowed_tools=("email.send", "mailbox.fetch_reply", "work.handoff"),
            workflow_key="lead_care",
            workflow_version="1.0.0",
            parameters={},
            role_keys=frozenset({"member"}),
            decision_classes=(
                DecisionClass("email.send", "external", False, "A2", "A1"),
                DecisionClass("work.handoff", "internal", True, "A3", "A3"),
            ),
        ),
        people=DwPeople(owner, uuid.uuid4(), owner, uuid.uuid4()),
        state="operating",
        created_by=owner,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    context = AccessContext(
        tenant_id=tenant,
        workspace_id=workspace,
        principal_id=owner,
        roles=frozenset({"member"}),
        scopes=frozenset({"dw.read", "dw.manage"}),
        plan_id="eval",
    )

    class Owner:
        async def require_owner(self, ctx: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
            return worker

    failures = 0
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        case = json.loads(line)
        base_pin = pinned
        if case.get("base_description"):
            first = pinned.document.steps[0].model_copy(
                update={"description": case["base_description"]}
            )
            document = pinned.document.model_copy(
                update={"steps": [first, *pinned.document.steps[1:]]}
            )
            base_pin = replace(pinned, document=document)

        pack_pin = pinned

        class Pins:
            # `pack_pin`, not `pinned`: inside this class body `pinned` is the
            # method above, which a default argument would bind instead.
            async def pinned(self, worker: DigitalWorker, pin=base_pin):  # type: ignore[no-untyped-def]
                return pin

            def pack(self, key: str, version: str, pin=pack_pin):  # type: ignore[no-untyped-def]
                return pin if (key, version) == ("lead_care", "1.0.0") else None

        assistant = WorkflowAssistant(
            workers=Owner(),
            workflows=Pins(),
            gateway=gateway,
            registry=build_node_registry(),
            tools=ShippedToolSpecs.load(CONFIGS / "tools"),
            run_context=lambda ctx, run_id: RunContext(
                run_id=run_id,
                tenant_id=ctx.tenant_id,
                workspace_id=ctx.workspace_id,
                actor_id=ctx.principal_id,
                worker_id="wf_ai",
                worker_version="1.0.0",
                channel="eval",
                plan_id="eval",
                roles=ctx.roles,
                scopes=ctx.scopes,
                trace_id="eval-wf-ai",
            ),
        )
        try:
            answer = await assistant.turn(
                context,
                worker.id,
                instruction=case["instruction"],
                history=[HistoryTurn(**t) for t in case.get("history", [])],
            )
        except (ModelOutputInvalidError, InfrastructureError) as exc:
            failures += 1
            out(f"FAIL {case['id']}: {type(exc).__name__}")
            continue
        base = base_pin.document.model_dump(by_alias=True, exclude_none=True)
        proposed = None if answer.steps is None else {**base, "steps": list(answer.steps)}
        ok, why = GRADERS[case["expect"]](base, proposed, answer)
        failures += not ok
        codes = ",".join(sorted({p.code for p in answer.problems})) or "-"
        out(
            f"{'ok  ' if ok else 'FAIL'} {case['id']}: {why} (kind={answer.kind},"
            f" publishable={answer.publishable}, codes={codes})"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
