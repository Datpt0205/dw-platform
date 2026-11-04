"""Stand-ins for the two ports `run_cases` and `judge_grader` take, for tests
and for replaying a recorded run: `RecordedTarget` (`EvalTargetPort`) and
`ScriptedJudge` (`JudgePort`). Neither calls a model."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dw_evals.dataset import EvalCase
from dw_evals.graders import JudgeVerdict, Observation


@dataclass
class RecordedTarget:
    """Replays the observation recorded for `(case_id, trial)`; a trial with
    none recorded raises, which `run_cases` grades as `target_error`. `calls`
    lists every `(case_id, trial)` asked for, in order."""

    observations: Mapping[tuple[str, int], Observation]
    calls: list[tuple[str, int]] = field(default_factory=list)

    @classmethod
    def load(cls, *paths: Path) -> RecordedTarget:
        """From JSON files of `{"case_id": ..., "trials": [observation, ...]}`,
        the first observation being trial 1."""
        observations: dict[tuple[str, int], Observation] = {}
        for path in paths:
            recorded = json.loads(path.read_text(encoding="utf-8"))
            for trial, raw in enumerate(recorded["trials"], start=1):
                key = (str(recorded["case_id"]), trial)
                if key in observations:
                    raise ValueError(f"trial recorded twice: {key}")
                observations[key] = Observation.model_validate(raw)
        return cls(observations=observations)

    async def run(self, case: EvalCase, trial: int) -> Observation:
        self.calls.append((case.case_id, trial))
        try:
            return self.observations[(case.case_id, trial)]
        except KeyError:
            raise LookupError(f"no observation recorded for {case.case_id} trial {trial}") from None


@dataclass
class ScriptedJudge:
    """Answers each case with the verdict scripted for its id, which it reads
    from the case's input (`case_id`); a case with no verdict scripted
    raises. `calls` lists the case id of every question, in order."""

    verdicts: Mapping[str, JudgeVerdict]
    calls: list[str] = field(default_factory=list)

    async def judge(
        self,
        rubric: str,
        case_input: dict[str, Any],
        output: dict[str, Any],
        reference: dict[str, Any],
    ) -> JudgeVerdict:
        case_id = str(case_input["case_id"])
        self.calls.append(case_id)
        return self.verdicts[case_id]
