---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied; the C++ binding stays the default only if the FOG-50 measurement holds; FOG-50 measured 2026-11-03, see Amendments)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/workflow-nodes/spec.md
    - ../../.claude/plans/studio/custom-objects/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py
    - ../../pyproject.toml # the kernel purity contract
---

# 0114. CEL is the one expression language for tenant text, behind an ExpressionEngine port, type-checked at submit, cost-bounded and evaluated only on the server

Numbered 0114 in the block 0100-0199 that ADR-0100 reserves for Studio. It rests on the requester's D2 (business
admins write simple expressions; tenant code exists only in the code node) and D5 (si-platform's validation evaluator is
on the port list: this ADR ports its semantics and test vectors and answers its syntax with CEL). One language is stance
S7.

## Context

- Tenant logic appears in many places: workflow conditions and mappings, `{{ }}` text templates in messages and
  prompts, validation rules and formula fields (ADR-0107), sharing-rule criteria (ADR-0105), record-event conditions
  (ADR-0113), tool approval conditions (ADR-0116) and outcome events. Two languages for one question, "does this
  hold?", would be two answers to it (failure-modes #2).
- The only template mechanism today is `PromptRegistry.render`, which calls `artifact.template.format(...)`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`) with each value wrapped by
  `contain_untrusted` (`prompts.py:35-43`, ADR-0010). A tenant's text handed to `str.format` would honour attribute
  access and indexing, and fail on any JSON example it contains.
- Measured by the research on 2026-10-22: `cel-expr-python` 0.1.3 (Apache-2.0, wrapping cel-cpp,
  <https://github.com/cel-expr/cel-python>) evaluates a typical condition in 13.2 µs and stops a map over 10,000
  elements with "Iteration budget exceeded"; `common-expression-language` 0.10.0 (Rust) takes 28.3 µs, but a
  triple-nested map over 100 elements did not finish in 20 s; `celpy` 0.5.0 takes 728 µs and is unbounded. Jinja2's
  sandbox had three breakout advisories in 2024-2025 (<https://github.com/pallets/jinja/security/advisories>), and
  n8n's JavaScript expressions at least three sandbox escapes to code execution (CVE-2025-68613, CVE-2026-27577,
  GHSA-gv7g-jm28-cr3m).
- CEL "evaluates in linear time, is mutation free, and not Turing-complete" (<https://github.com/google/cel-spec>), and
  Kubernetes evaluates it in a multi-tenant control plane under a runtime cost budget with write-time estimates
  (<https://kubernetes.io/docs/reference/using-api/cel/#resource-constraints>).
- si-platform's validation rules (si-platform `packages/python/platform/si_metadata/src/si_metadata/rules.py`) are JSON
  conditions in its query AST that report an error when the condition is true, as in Salesforce.

## Decision

1. **CEL everywhere tenant text decides or renders.** Conditions, mappings, `{{ }}` text templates, validation rules,
   formula fields, sharing-rule criteria, record-event conditions, tool approval conditions and workflow outcome
   events are CEL. Tenant text never reaches `str.format`, `format_map`, `string.Template`, Jinja2, f-strings, `eval`
   or JavaScript; an architecture test fails a `dw_studio` module that imports `jinja2` or calls `.format(` on anything
   but a literal. No expression is evaluated in the browser: the builder calls
   `POST /api/v1/studio/expressions/check` and `POST /api/v1/studio/expressions/evaluate` (sub-resources, ADR-0108's
   convention; against a sample the caller typed, or a recorded step output the caller may read, masked),
   rate-limited per user.
2. **The port.** `ExpressionEngine` lives in `dw_kernel.expressions` (stdlib only): `check(source, env)` returns a
   checked expression (its result type) or issues, each with a kind, a position and the name involved;
   `evaluate(checked, activation)` returns a value or an error; one closed type algebra (`null`, `bool`, `int`,
   `double`, `string`, `bytes`, `timestamp`, `duration`, `list[T]`, `map[string, T]`, `object{...}`, `optional[T]`,
   `dyn`). workflow-nodes owns it. The one adapter lives in `dw_studio.core.adapters.cel`, the one module
   import-linter lets import a CEL binding (ADR-0100 decision 3): `CelCppEngine` on `cel-expr-python==0.1.3`, pinned
   exactly, passing one contract suite (a cel-spec conformance subset, the function library, budget, wall-clock and
   size cases). FOG-50 measured that it registers Python functions and typed objects with fields, so it is the engine
   (DO-38 (a)). There is no second binding and no setting choosing one (amended 2026-11-03): FOG-50 measured the Rust
   binding without a checker, an AST or a budget, so it could not pass the suite. A replacement adapter joins only by
   passing the same suite first, and one that moves deployed profiles off `cel-expr-python` amends `CLAUDE.md`
   (Required stack) in the same change.
3. **One library, pinned per run.** `dw.cel/v1`, pinned on the run manifest (ADR-0109), is the CEL standard with the
   `strings`, `math`, `optional`, `encoders` and `bindings` extensions plus the platform functions `text.nfc`,
   `text.unaccent`, `text.mask_contacts`, `phone.e164`, `email.normalize`, `fmt.money_vnd`, `fmt.datetime`, `fmt.date`
   (in `Asia/Ho_Chi_Minh`) and `time.add_workdays`. There is no `now()`: time comes from `run` or a node output, so a
   retried node evaluates the same way. A new function is a minor version, a changed one a major. An environment never
   holds a secret: connection bindings are not addressable from an expression.
4. **One type mapping, checked at submit, bounded at evaluation.** One table maps field types (ADR-0107) and the tool
   schema profile (ADR-0116) to CEL: text-like to `string`; integer and money (integer VND) to `int`; decimal and
   percent to `double`; boolean to `bool`; datetime to `timestamp`; date-only to a `string` `YYYY-MM-DD`; picklist to
   `string`; multi-picklist to `list[string]`; lookup and owner to `string` (a UUID); json to `dyn`, refused in a
   condition without a `type()` guard. At submit (inside ADR-0112's validator, the first step of the path to live) the
   checks refuse undeclared or non-dominating references, type mismatches (a condition must be `bool`), a field the run
   principal cannot read (`field_not_readable`, ADR-0106), source over 2 KiB for a condition or 16 KiB for a text
   template, and AST depth over 32 (the binding's parser refuses it). At evaluation the binding's iteration budget
   (10,000, fixed inside it), a wall clock of 1 second, and a 256 KiB cap on the serialized result apply, each as
   `expression_budget_exceeded`; evaluation runs in an evaluator process the caller does not share, so a stopped
   evaluation never holds the caller (amended 2026-11-03). An evaluation error becomes `expression_error` naming the
   node and the path, never a value. Compiled programs are cached by
   `(tenant id, library version, env hash, sha256(source))` (`CLAUDE.md`, Tenancy: cache keys include the tenant) in a
   bounded per-process LRU of 10,000.
5. **Text templates are parsed by the platform and rendered per sink.** A CEL-aware tokenizer reads `{{ expr }}` (a
   string literal may contain `}}`; `\{{` is literal). Each templatable config field declares its sink (`x-dw-sink`):
   `prompt` wraps every value with `contain_untrusted(name, value)` (ADR-0010), the tenant's literal text being
   instructions linted for `<input` and capped at 8 KiB; `text` is length-capped; `html` escapes values and allows
   literal markup from a fixed list; `url` templates only path segments and query values, each percent-encoded, never
   a scheme or a host (`templated_host`); `header` refuses CR and LF in a value and never templates a header name;
   `json` puts typed values in as leaves, never by concatenation. A list or map inside text is `non_scalar_in_text`. A
   reference to a hidden field fails at submit and, if access changed since, fails the render with `field_hidden`
   instead of rendering empty. A text template holds at most 16 KiB and 50 expressions and renders at most 64 KiB.
6. **Validation rules port si-platform's structure; selection and audiences keep their own forms.** A validation rule
   means "must hold" (true is valid; the UI says "Điều kiện để lưu được") and ports the order, the all-errors result
   and the message shape of si-platform's `rules.py`, with its test vectors; since si-platform's rules mean "error when
   true", each ported vector's expected outcome is inverted. Validation rules ship in W2 with YC28 (DO-37 (a)). Record
   selection stays on the JSON filter AST (ADR-0108): CEL decides whether something holds, not which records a query
   returns. Audiences stay a typed condition list (ADR-0102), a reasoned exception to decision 1: the reverse screen
   "who may use this agent" must generate positive SQL, which a CEL expression cannot give, and a list without
   arithmetic is not a second expression language (DO-40 (a)).

## Alternatives considered

- **JSONata or JMESPath.** Rejected: no type checker, so errors surface at run time instead of submit; JSONata also
  recursed without bound when measured, and JMESPath has no arithmetic.
- **A JavaScript sandbox.** Rejected: a code-execution surface behind every condition, with n8n's escapes as the record;
  D7 keeps tenant code to a fresh container per code execution (ADR-0119).
- **Jinja templates.** Rejected: template injection and a sandbox with three breakouts in two years; ADR-0010's
  containment would not hold.
- **Port si-platform's own rule syntax (D5's port list).** Rejected: a second expression language beside CEL (S7).
  D5's intent is kept for the evaluator's semantics and its tests.
- **`celpy`.** Rejected: about 25 to 50 times slower than the C++ binding when measured, and unbounded.
- **A structured condition builder alone.** Rejected: it cannot express normalisation such as `text.nfc` or
  `phone.e164`, which lead de-duplication needs.

## Consequences

- tools-and-skills ticket 07 re-points to workflow-nodes' engine ticket; custom-objects and record-access consume the
  same port and build their own environments on it.
- A C++ wheel enters the images (measured 2026-11-03: about 66 MB installed, 16 MB of it a stray, non-importable
  `bazel-project` build tree the wheel ships), and a 0.1.x dependency sits behind a port and a contract suite any
  replacement must pass. Typed objects reach the binding as protobuf messages of a descriptor pool built per
  environment, so `protobuf` becomes a direct dependency of `dw-studio`.
- The kernel purity contract (`pyproject.toml:251-276`) is a denylist: the binding's import name joins its
  `forbidden_modules`, or the guard cannot see the new library. FOG-50 read it from the installed wheel:
  `cel_expr_python`. (The Rust binding's import name is `cel`, not `common_expression_language`; it is not installed.)
- Tests that must exist, each red when its guard is removed: the contract suite against the adapter; a
  10,000-element map refused by the budget; an expression that stays under the budget but runs past the wall clock
  refused while the caller's event loop keeps running;
  the architecture test on `jinja2` and `.format(`; per sink, a value containing `</input>`, a header value with CR
  or LF and a templated host, each refused; a hidden field failing the render closed; the ported si-platform vectors
  passing.
- Harder: a library change is a versioned `dw.cel/v1` bump that runs pin; tenant overrides of platform prompts
  (ADR-0110) must refuse any `string.Formatter().parse` field other than a declared plain name.
- Extends `docs/adr/0010-prompt-variables-are-untrusted-by-default.md` to every template sink, through the same
  `contain_untrusted` and never a second containment function.
- `CLAUDE.md` (Required stack) named no expression language at acceptance; since 2026-10-24 it carries "CEL only
  behind `ExpressionEngine`, on `cel-expr-python` pinned exactly (ADR 0114)".
- si-platform: ports the structure (order, all-errors result, messages) of si-platform
  `packages/python/platform/si_metadata/src/si_metadata/rules.py` and diverges on predicate syntax (CEL) and on
  meaning ("must hold" rather than "error when true").

## Open

1. **DO-38 (Đạt).** Accept a 0.1.x C++ binding (`cel-expr-python`), pinned exactly, as the default engine, with the
   Rust binding as the fallback behind the same contract suite, and workflow-nodes as the port's owner?
   Answered 2026-10-23: yes (DO-38 (a)), on decision 2's condition that FOG-50 holds; workflow-nodes owns the port, as
   Đạt confirmed in its spec.
2. **DO-37 (requester for the meaning, Đạt for the engine).** CEL with si-platform's `rules.py` semantics and test
   vectors rather than porting the evaluator (D5 versus S7)? Answered 2026-10-23 (DO-37 (a)): validation rules mean
   "must hold", in CEL, with si-platform's vectors ported and each one's polarity checked (decision 6); they ship in W2
   with YC28.
3. **DO-40 (Đạt and requester).** Audiences as a typed condition list or as CEL? Answered 2026-10-23: a typed
   condition list (DO-40 (a)), recorded in decision 6 as a reasoned exception to CEL.
4. **DO-03 (Đạt, with si-platform's PO and SA).** The terms for porting si-platform code and test
   vectors: a written agreement, a pinned commit per port, provenance headers. They are settled before anything is
   ported.
5. **FOG-50 (prototype).** Which runtime registers Python functions and typed objects and enforces cost limits, and is
   the Rust fallback bounded by the AST pre-check alone, given a native call cannot be interrupted from Python? Its
   answer is the condition this ADR was accepted on (decision 2). Answered 2026-11-03 (Amendments): the C++ binding
   does both; the Rust binding is not bounded, and has no checker and no AST to pre-check.

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23, on condition that the C++ binding stays the default only if the FOG-50 measurement
holds, with these amendments from the decision brief:

- Decision 1: the builder's routes are the sub-resources `/expressions/check` and `/expressions/evaluate`, not
  `expressions:check` (ADR-0108, DO-16 (a)).
- Decision 2: the rule that picks the default after FOG-50, Rust as the fallback, and a stop if both bindings fail
  (DO-38 (a)).
- Decision 6: validation rules ship in W2 with YC28 (DO-37 (a)); audiences as a typed condition list are recorded as
  a reasoned exception, with its reason (DO-40 (a)).
- Consequences: the bindings' import names are measured in FOG-50 before they join `forbidden_modules`; the sentence
  `CLAUDE.md` (Required stack) gains is written out.
- Open: DO-38, DO-37 and DO-40 answered; DO-03 and FOG-50 stay open.

## Amendments (2026-10-24)

- Third consistency check (round 4), second pass: decision 2 adds that deployed profiles (`settings.is_deployed`) pick
  `cel-expr-python`, with a test that fails when the setting points at the Rust binding, and that moving them to the
  Rust binding amends `CLAUDE.md` (Required stack) in the same change, so workflow-nodes/01 ships both bindings
  behind `ExpressionEngine`, one contract suite and the setting, as decision 2 already said (V4.P13, the planner's
  provisional call, revised so as not to contradict decision 2; E:CLAUDE.md#required-stack\~workflow-nodes/01; if it
  is wrong, Đạt amends decision 2 so that W1 ships `cel-expr-python` alone). The title, decisions 4 and 5 and the
  first alternative say "at submit", where ADR-0112's validator runs these checks, no longer "at publish". The status
  stays Accepted.
- Third consistency check (round 4), third pass: decision 2 places both adapters in `dw_studio.core.adapters.cel`,
  the one module import-linter lets import a CEL binding, as ADR-0100 decision 3 and studio-skeleton R5.6 say;
  Consequences and Acceptance cite `CLAUDE.md` (Required stack) by its section instead of its line numbers, say that
  it named no expression language at acceptance, and quote the sentence it has carried since 2026-10-24.

## Amendments (2026-11-03)

The gate of workflow-nodes ticket 01 ran FOG-50 (agent, theo ủy quyền 31/10/2026). It used a scratch venv on Windows
11 (CPython 3.12) and the `python:3.12-slim-bookworm` image the API and worker run on (glibc 2.36). The scripts stay
out of the repository, as ticket 01 said; these are the numbers.

- **Wheels.** `cel-expr-python` 0.1.3 ships cp312 wheels for `win_amd64`, `manylinux_2_27/2_28` x86_64 and aarch64,
  and macOS, but no sdist. It installs in the image. Its import name is `cel_expr_python` (`cel_expr_python.cel`, plus
  `cel_expr_python.ext.ext_strings`, `ext_math`, `ext_optional`, `ext_encoders`, `ext_bindings`). It declares no
  dependencies, but typed objects need `protobuf` (7.36.1 in `uv.lock`). `common-expression-language` 0.10.0 imports
  as `cel`, and that import also loads its CLI dependencies `typer`, `rich`, `prompt_toolkit` and `pygments`.
- **C++ binding, what FOG-50 asked.** Python functions register under dotted names (`phone.e164`,
  `time.add_workdays`) through `CelExtension`/`FunctionDecl`/`Overload`, and calling one with a wrong argument type
  is refused at compile. Typed objects register through a protobuf `DescriptorPool` built at run time: `score.response.tier`
  type-checks to `STRING` and a typo is refused at compile ("undefined field"). The activation must then hold message
  instances, not dicts. An absent proto3 scalar reads as its zero value (`''`); a wrapper-type field reads as `null`.
  Converting a 20-field dict and evaluating costs about 267 µs; a typical three-clause condition over maps evaluates in
  13.5 µs (6.2 µs in the image) and compiles in about 317 µs.
- **Budget.** The binding stops every evaluation at 10,000 comprehension iterations in total, across nesting, with a
  raised `RuntimeError("INTERNAL: Iteration budget exceeded")`. It resets per evaluation, and no API or YAML option
  changes it. A triple-nested map over 21 elements (9,261 iterations) completes; over 22 it stops in about 30 ms.
  But `map` and `filter` cost quadratic time and hold the GIL: a single map over 9,000 elements takes 4.1 s. A 77-byte
  expression that concatenates a 500-element list 19 times and maps over the result runs 5.6 s under the budget, and
  `s.split('')` over a 9,999-character string then `map` runs 6.4 s. A ticker thread got one tick in a 1.44 s
  evaluation, so the budget bounds iterations, not the time a caller is held. That is why decision 4 adds an
  evaluator process and a 1 s wall clock. Measured: spawning the process and the first evaluation take 298 ms, a
  typical round trip 149 µs, and a pathological evaluation is killed at about 1.07 s.
- **Errors.** A compile problem raises one `RuntimeError` whose text begins with a status (`INVALID_ARGUMENT: ERROR:
<input>:line:col: ...`). An evaluation error is not raised: it is returned as a value of type `ERROR`
  (`divide by zero`, `NOT_FOUND: Key not found in map`, `OUT_OF_RANGE: integer overflow`, a Python function's exception
  text as `OUT_OF_RANGE: <message>`). Only the budget is raised. The parser refuses depth over 32 by itself.
- **Regex and time.** `matches` is RE2: a backreference or lookahead is refused, and `(a+)+$` over 30 `a`s returns in
  5 ms. An invalid literal pattern is reported only at evaluation. `getHours('Asia/Ho_Chi_Minh')` works in the image,
  which has `/usr/share/zoneinfo`, and fails with "Invalid timezone" on Windows; `'+07:00'` works on both. A naive
  `datetime` is read in the host's local time (01:30 naive gives `getHours()` 18 on a UTC+7 host and 1 in a UTC
  container), so the adapter refuses one. There is no `now()`.
- **Rust binding.** It has no environment declarations and no type checker: `compile("1 + 'x'")` and an undeclared
  variable both compile, and `references()` lists names only. It exposes no AST, so the pre-check had nothing to
  walk. It has no budget either: a single map over 10,000 elements ran 10.8 s, a nested map over 1,000 × 1,000 ran
  107 s, and the triple-nested map over 22 completed in 138 ms. It lacks the timestamp accessors (`getHours`
  undefined), and it reads a naive `datetime` as UTC where the C++ binding reads local time.

What changed, as the agent's call under Đạt's delegation of 31/10/2026:

- Decision 2: one adapter, `CelCppEngine`, and no setting. The Rust fallback could pass neither the type-checking
  cases nor the budget cases of one contract suite. Keeping it would mean a second type checker and parser in
  Python, a second answer to "does this hold?" (failure-modes #2). `check` returns the result type and issues, and
  drops "references" and "cost estimate", because the binding exposes neither and nothing reads them.
  Nếu sai thì: a second adapter comes back only with its own checker and a process boundary, and passes the whole
  suite first.
- Decision 4: comprehension nesting over 2 is no longer refused at submit. The rule existed for the Rust pre-check,
  and with no AST exposed nothing could enforce it; the budget bounds every nesting. Evaluation runs in an evaluator
  process with a 1 s wall clock, and the compiled-program cache key carries the tenant id, because `CLAUDE.md`
  (Tenancy and authorization) requires cache keys to include the tenant and the key did not. Nếu sai thì: evaluation
  returns to the caller's process, and the measured 5-7 s holds are accepted by Đạt as a risk.
- Status stays Accepted: decision 2's own condition (FOG-50 holds for the C++ binding) is met.
