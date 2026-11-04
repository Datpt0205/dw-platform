"""Evaluation package: versioned datasets, deterministic graders and the CI
runner (`run_dataset`); graders of a trial's `Observation`, run k times by
`run_cases` against an `EvalTargetPort`; an LLM judge only behind `JudgePort`
(`judge_grader`); and `gate.evaluate_gate`, the one pure function deciding
whether a gate run passes. It imports no bounded context and no Studio
package: a context's graders join at an eval composition root."""

__version__ = "0.1.0"
