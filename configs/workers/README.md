# Workers

One file per deployable Digital Worker: which graph version it runs, which
prompt bundle, toolset, policy and memory policy it is pinned to, which model
profile it defaults to, and its autonomy level.

Every run writes those versions onto its own row in `platform.worker_runs`, so
a result traces back to the exact artifacts that produced it with a query, not
with a guess. They are on the row rather than only in the trace on purpose: a
trace is sampled and expires, and provenance that only a sampled span can answer
is not provenance. `release_manifest_ref` does not substitute — it is a text
reference with no table behind it.

`autonomy_level` is read when a run starts: the runner lowers it to the
tenant's ceiling (`lower_autonomy`, `dw_agent_runtime/autonomy.py`), and
`AutonomyApprovalPolicy` decides from that level and the tool's side-effect
level whether a call waits for a person (ADR-0117, ADR-0125). A worker at A0
pauses more often than one at A4, so set it to what the worker is trusted with.

Empty because a worker is a property of a bounded context, not of the platform.
A process loads only the workers it hosts — `configs/` is shared, and loading a
file whose graph lives in another process would fail fast for the wrong reason.
