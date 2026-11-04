# 02 — Mở rộng dw_evals: quan sát, bộ chấm theo quan sát, JudgePort, lần chạy lặp, chính sách cổng thuần

Status: resolved
Blocked by: .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, G1

## Mục tiêu

Cổng chất lượng cần một bộ chạy kiểm định chấm theo quan sát có cấu trúc, lặp k lần và kết luận bằng
một hàm thuần có test; `dw_evals` được mở rộng chứ không thay, và giữ nguyên hành vi CI hiện có (spec
R3, G1).

## Việc cần làm

1. `dw_evals/dataset.py`: thêm `CaseCategory.SIDE_EFFECT_WITHOUT_APPROVAL` (bên đọc: các câu của Bộ kiểm định an ninh
   nền tảng ở ticket 06 và fixture của bước 6); giữ nguyên `SECURITY_CATEGORIES` (đó là luật phủ CI; đổi nó làm
   `platform@1.2.0` đỏ); `EvalCase` thêm `input` và `expected` nội tuyến (`dict[str, Any] | None`), `input_ref` và
   `expected_ref` thành `str | None`, với một `model_validator`: mỗi trường có đúng một trong ref hoặc nội tuyến, cả hai
   hay không cái nào là lỗi validate; và `trials: int = 1` (`ge=1, le=10`). `run_dataset` đọc giá trị nội tuyến khi có,
   ref khi không, và bỏ qua `trials` (bộ chấm CI tất định).
2. `dw_evals/graders.py`: `GradeResult` thêm `unknown: bool = False` và `score: float | None = None`, với một
   `model_validator` từ chối `passed=True` cùng `unknown=True`, và hàm dựng `GradeResult.abstain(reason, **details)`
   (`passed=False, unknown=True`), để mọi cửa đếm `unknown` như trượt, kể cả `EvalReport.ok` của CI. Model
   `Observation` (Pydantic, `frozen`, `extra="forbid"`): `final_output: dict[str, Any] | None`, `tool_calls:
tuple[ObservedToolCall, ...]` (mỗi phần tử `tool` dạng `name@version`, `side_effect_level` là `SideEffectLevel` của
   `dw_agent_runtime.contracts`, `simulated: bool`, `args_sha256` hex 64 ký tự; tác động bị giả lập là các phần tử có
   `simulated=True`, không phải một trường thứ hai), `approval_requests: tuple[str, ...]` (loại phê duyệt lần thử đã
   xin, thật hay giả lập), `evidence_refs: tuple[str, ...]`, `cost_usd: Decimal` (`ge=0`), `latency_ms: int` (`ge=0`),
   `error_code: str | None`. `ObservationGrader` là Protocol bất đồng bộ
   `async __call__(case: EvalCase, observation: Observation) -> GradeResult`, khóa `<context>.<gate>` như `Grader`.
   `JudgeVerdict` (`verdict: Literal["pass", "fail", "abstain"]`, `reasons: tuple[str, ...]`, `score: float | None`) và
   `JudgePort` (Protocol bất đồng bộ `judge(rubric, case_input, output, reference) -> JudgeVerdict`); `judge_grader(judge,
rubric) -> ObservationGrader` chấm `final_output` qua port, `abstain` thành `GradeResult.abstain`, `fail` thành trượt
   kèm `reasons`. Adapter giả `ScriptedJudge` (trả verdict theo `case_id` và đếm lời gọi) ở `dw_evals/testing.py`;
   adapter giám khảo thật là W2 (ADR-0120 (Accepted), Consequences) và sẽ đi qua `ModelGateway`, nên qua
   `ResidencyGate`. `GRADERS` không đổi; `merge_graders` thành generic theo kiểu giá trị (`Mapping[str, G]` →
   `dict[str, G]`), cùng hành vi từ chối tên trùng, để ticket 06 hợp nhất bộ chấm `studio.*` theo quan sát bằng chính
   nó. Docstring gói thành đúng.
3. `dw_evals/runner.py`: giữ `run_dataset` cho CI; thêm `EvalTargetPort` (Protocol bất đồng bộ
   `run(case, trial) -> Observation`) và `run_cases(cases, target, graders, *, pass_k)` bất đồng bộ. Số lần thử của một
   câu là `pass_k` khi `"consistency"` có trong `tags` của câu (R3.1), và `case.trials` khi không; `pass_k` do bên gọi
   truyền từ `GatePolicy.pass_k` (bước 4), là chủ duy nhất của số đó. Câu đạt chỉ khi mọi lần thử đạt; một lần thử
   `unknown` làm câu `unknown`; tên bộ chấm không có trong bảng → trượt `unknown grader`, bộ chấm ném lỗi → trượt
   `grader raised`, target ném lỗi → lần thử trượt `target_error`, như `_grade`. `CaseResult` thêm `unknown`, `trials`,
   `trials_passed` và `reason_code` (lý do của lần thử trượt đầu tiên, `None` khi đạt); `EvalReport` thêm `unknown` và
   `by_category: dict[CaseCategory, CategoryCount]` (`total`, `passed`, `failed`, `unknown`), câu `unknown` tính vào
   `failed`; `ok` giữ nghĩa. Adapter `RecordedTarget` (phát lại quan sát đã ghi theo `(case_id, trial)`) ở
   `dw_evals/testing.py`; adapter thật, bộ chạy Studio ở chế độ Mô phỏng nối ở composition root của worker, là của
   ticket 06.
4. `dw_evals/gate.py` mới, thuần: `GatePolicy` (Pydantic, `frozen`, `extra="forbid"`) chỉ với các trường có bên đọc ở
   ticket này: `policy_id`, `version` (semver), `security_pass_rate: Literal[1.0]`, `pass_k: int` (`ge=1, le=10`; bên
   đọc: bên gọi `run_cases`); ticket 06 thêm các trường còn lại của DO-29.1 cùng bên đọc của chúng. `evaluate_gate(report,
policy) -> GateVerdict(passed, reasons)`, không tham số nào khác (R3.4), là chủ duy nhất của "Lượt kiểm định này đạt
   không" (ADR-0120 (Accepted) quyết 4), còn "câu này đạt không qua k lần thử" là của `run_cases` (R3.1). Luật ở ticket
   này: báo cáo không có câu nào → `no_cases`; mỗi câu `unknown` → `case_unknown:<case_id>`; mỗi câu trượt mà không
   `unknown` → `case_failed:<case_id>`; `passed` chỉ khi không có lý do nào; `reasons` sắp theo `case_id` nên không phụ thuộc thứ tự
   câu. Ở W1 mọi câu không phải `scenario` là Câu an ninh, vì cổng W1 chỉ chạy Bộ kiểm định an ninh nền tảng (spec R4.1);
   luật `scenario` là của ticket 06.
5. Sửa docstring `dw_evals/__init__.py`. `dw_evals` không import gói Studio nào: hợp đồng import-linter là của
   studio-skeleton/02 (studio-skeleton:R5.1), ticket này không viết bản thứ hai mà chứng minh nó đỏ cho `dw_evals`.
6. Test đầu-cuối trong `packages/python/dw_evals/tests/unit` trên quan sát đã ghi (JSON dưới
   `packages/python/dw_evals/tests/fixtures/observations/`), qua `RecordedTarget`, `judge_grader` trên `ScriptedJudge`,
   `run_cases` và `evaluate_gate`, với một quan sát tốt, một quan sát xấu và một quan sát giám khảo kiêng, mỗi cái thấy
   kết quả của nó (chuẩn bị cho ticket 06). Không thêm tệp nào dưới `evals/datasets` và không đổi dataset nào ở đó (G1),
   gồm cả `leadcare_injection_v1.jsonl` và `wf_ai_injection_v1.jsonl` của `make eval-leadcare` và `make eval-wf-ai`;
   bộ chấm an ninh theo category và bộ chấm `studio.*` là của ticket 06.

## Tiêu chí chấp nhận

- [x] R3.1: `run_cases` chạy một câu có tag `consistency` với `pass_k = 3` và một bộ chấm giả đạt, trượt, đạt → câu
      trượt với `trials = 3`, `trials_passed = 2`; cả 3 lần đạt → câu đạt; target giả nhận đúng 3 lời gọi; một câu không
      có tag đó với `trials = 1` → target nhận 1 lời gọi dù `pass_k = 3`.
- [x] R3.2: một bộ chấm theo quan sát trả `GradeResult.abstain` → `CaseResult.unknown` và `evaluate_gate` trả
      `passed=False` với `case_unknown:<case_id>`; `GradeResult(passed=True, unknown=True)` → lỗi validate; gỡ validator
      đó hay luật `unknown` của `evaluate_gate` → test đỏ.
- [x] R3.2: test đầu-cuối của bước 6 qua `RecordedTarget` và `judge_grader` trên `ScriptedJudge`: quan sát tốt (verdict
      `pass`) → cổng đạt; quan sát xấu (`fail`) → `case_failed:<case_id>`; giám khảo kiêng (`abstain`) →
      `case_unknown:<case_id>`; `ScriptedJudge` nhận đúng một lời gọi mỗi lần thử; không lời gọi model nào.
- [x] R3.3: một `EvalCase` có cả ref lẫn nội tuyến cho `input`, hay cho `expected`, hay không có cái nào → lỗi validate,
      câu không chạy; câu chỉ có `input` và `expected` nội tuyến chạy qua `run_dataset` với giá trị đó.
- [x] R3.4: `evaluate_gate` cho cùng `GateVerdict` với cùng `(report, policy)` khi đảo thứ tự câu; báo cáo rỗng →
      `no_cases`; mỗi luật của nó (`no_cases`, `case_unknown`, `case_failed`) có test đỏ khi gỡ luật; `GatePolicy` có
      trường lạ hay `security_pass_rate` khác 1.0 → lỗi validate.
- [x] R3.5: thêm `import dw_studio` vào một module của `dw_evals` → `lint-imports` đỏ ở hợp đồng của
      studio-skeleton:R5.1; gỡ lại → xanh.
- [x] G1: `make eval-smoke` và `apps/api/tests/unit/test_eval_datasets.py` xanh, không đổi tệp nào dưới
      `evals/datasets`.
- [x] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_evals/src/dw_evals/dataset.py:14-31`; spec: R3.3, G1.
- `packages/python/dw_evals/src/dw_evals/graders.py:25-58`; spec: R3.1, R3.2.
- `packages/python/dw_evals/src/dw_evals/graders.py:229-239` (`merge_graders`); spec: R3.2.
- `packages/python/dw_evals/src/dw_evals/runner.py:61-100` (`_grade`, `run_dataset`); spec: R3.1, G1.
- `packages/python/dw_evals/src/dw_evals/__init__.py:1-2`; spec: R3.4 (docstring claim without code);
  ADR-0120 (Accepted) quyết 4.
- `scripts/run_evals.py:56` (glob `*.json`, nên tệp `.jsonl` của `make eval-leadcare` và `make eval-wf-ai` không vào
  `make eval-smoke`); spec: G1.
- `.claude/plans/studio/studio-skeleton/spec.md` R5.1; spec: R3.5.

## Comments

- 2026-10-23 (agent): từ B10a agent-lifecycle 02. Băm RFC 8785 cho Mã băm định nghĩa là một chủ ở
  tenant-config/01 (`dw_kernel.canonical`), không ở đây.
- 2026-10-26 (agent): lượt h, đợt 2: Cổng chất lượng nay ở ticket 06 (V4.31), nơi ca kịch bản tất định của quy trình
  dùng lại `run_cases`, `EvalTargetPort` và bộ chấm theo quan sát của ticket này, thêm `CaseCategory.SCENARIO`, trường
  `Observation.state` và luật `scenario` của `evaluate_gate` (V4.37; H-23); ticket này không đổi phạm vi.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` cho ticket này (gate nhẹ: không
  migration, không route, nên chỉ builder check, chạy trong ngữ cảnh chính; đo trên `f95a89f`), 0 CRITICAL, 7 HIGH, đã
  sửa theo khuyến nghị:
  (1) bước 6 cũ ("dataset CI mới chấm quan sát đã ghi bằng bộ chấm Studio") không nói bộ chấm nào, tệp ở đâu, CI chạy nó
  bằng gì (`make eval-smoke` chỉ chạy `run_dataset` đồng bộ trên `evals/datasets/*.json`), quan sát xấu cố ý đỏ trái G1,
  và không tiêu chí nào phủ; sửa: bước 6 là test đầu-cuối trong `dw_evals/tests/unit` qua `RecordedTarget` và
  `judge_grader`, không tệp nào dưới `evals/datasets`, thêm tiêu chí R3.2 thứ hai. Nếu sai thì: một dataset `.json` dưới
  `evals/datasets` và `run_evals.py` gọi thêm `run_cases`, G1 đổi thành "không đổi dataset nền tảng".
  (2) `JudgePort` chỉ có Protocol, không adapter giả, không bên đọc (CLAUDE.md, Work style 6; failure-modes #1); sửa:
  `JudgeVerdict`, port bất đồng bộ, `judge_grader`, `ScriptedJudge`, adapter thật W2 qua `ModelGateway`. Nếu sai thì:
  `JudgePort` rời sang W2 cùng giám khảo, ADR-0120 (Accepted) quyết 4 sửa theo.
  (3) số lần thử có ba chỗ (`EvalCase.trials`, `run_cases(trials=)`, `pass_k` của Chính sách cổng) trong khi R3.1 nói
  `pass_k` cho câu `consistency`; sửa: `run_cases(..., pass_k)`, câu `consistency` chạy `pass_k` lần, câu khác
  `case.trials` lần, câu đạt chỉ khi mọi lần đạt. Nếu sai thì: bỏ `EvalCase.trials`, mọi câu chạy `pass_k` lần, và ticket
  06 bỏ `trials` 1 của ca kịch bản.
  (4) `GradeResult.unknown` không ràng với `passed`, nên `passed=True, unknown=True` lọt qua `run_dataset` và
  `EvalReport.ok`, một cửa vòng qua `evaluate_gate` (failure-modes #5, #7); sửa: validator, `GradeResult.abstain`, câu
  `unknown` tính vào `failed`. Nếu sai thì: `GradeResult.status` ba giá trị thay cho cặp cờ.
  (5) `evaluate_gate(report, policy, baseline=None)` trái R3.4 (chỉ hai đầu vào) và `baseline` không có bên đọc; trường
  của `GatePolicy` và luật của hàm không nêu, nên "mỗi luật có test đỏ khi gỡ" không kiểm được; "chủ duy nhất của câu
  này đạt không" chồng lên R3.1; sửa: bỏ `baseline`, `GatePolicy` bốn trường có bên đọc, ba luật có tên, `evaluate_gate`
  là chủ của "Lượt kiểm định đạt không" (ADR-0120 (Accepted) quyết 4). Nếu sai thì: so với lượt trước là W2 cùng bộ đề của tenant,
  vào qua một trường của báo cáo, không qua tham số thứ ba.
  (6) `ObservationGrader` không có chữ ký, mà ticket 06 bước 3 hợp nhất bộ chấm `studio.*` theo quan sát bằng
  `merge_graders`, hàm ticket này giữ ở kiểu `Grader`; sửa: Protocol bất đồng bộ `(case, observation)`, `merge_graders`
  generic với cùng hành vi. Nếu sai thì: một `merge_observation_graders` riêng dùng chung phần từ chối tên trùng.
  (7) tiêu chí R3.5 không đỏ được ở `f95a89f`: chưa có `dw_studio`, và hợp đồng cấm `dw_evals` import `dw_studio` là của
  studio-skeleton:R5.1 (studio-skeleton/02), nên viết lại ở đây là hai bản một sự thật (failure-modes #2); sửa: `Blocked
by` studio-skeleton/02, tiêu chí là đột biến `import dw_studio` làm `lint-imports` đỏ. Nếu sai thì: ticket này tự
  thêm hợp đồng `forbidden` cho `dw_evals` và studio-skeleton/02 bỏ `dw_evals` khỏi R5.1.
- 2026-11-02 (agent): MEDIUM của gate, chưa sửa, cho người dựng: Hiện trạng của spec (đọc ở `ab33703`) chưa biết
  `make eval-leadcare` và `make eval-wf-ai` (từ 30/10): dataset `.jsonl` riêng, bảng chấm riêng
  (`dw_agent_runtime.testing.wf_ai.GRADERS`), gọi model thật, ngoài CI; ticket này không chuyển chúng sang `run_cases`
  (chủ: leadcare, wf-ai). Neo `graders.py:56` của Hiện trạng đã trôi, `Grader` nay ở `:58`. `Observation.tool_calls`
  của ticket này và `state.tool_calls` của ticket 06 là hai bản một sự thật: ticket 06 nên dựng cái sau từ cái trước.
  `CaseCategory.SIDE_EFFECT_WITHOUT_APPROVAL` chỉ có bên đọc ở Bộ kiểm định an ninh nền tảng của ticket 06, mà ticket 06
  chưa nêu category đó. Ticket 06 bước 3 phải thêm vào `GatePolicy` các trường DO-29.1 còn lại, nếu không
  `extra="forbid"` làm `studio_gate@1.0.0.yaml` đỏ. Mọi tiêu chí chạy với bộ chấm, target và giám khảo giả, không cần
  khóa model.
- 2026-11-02 (agent): bảng cặp: ticket này với 01, 03, 04, 05 (không đường phụ thuộc) không chạm chung bảng, route,
  migration, config hay prompt nào: nó chỉ chạm `packages/python/dw_evals` và test của nó; 06 và 07 chờ nó.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent): resolved. Mã ở `packages/python/dw_evals/src/dw_evals/` (`dataset.py`, `graders.py`, `runner.py`,
  `gate.py` mới, `testing.py` mới, docstring `__init__.py`); test ở `packages/python/dw_evals/tests/unit/`
  (`test_dataset.py`, `test_observation_graders.py`, `test_run_cases.py`, `test_gate.py`, `test_recorded_gate_run.py`),
  ba quan sát đã ghi ở `tests/fixtures/observations/`; không tệp nào dưới `evals/datasets` đổi, `run_evals.py` không
  đổi. `mutations/02.yaml` có 16 đột biến, chạy tay từng cái (sao lưu, sửa, chạy, chép lại), cả 16 đỏ. R3.5: thêm
  `import dw_studio` vào `dw_evals/gate.py` → `lint-imports` đỏ ở "Platform core does not import Studio"
  (`dw_evals.gate -> dw_studio`), gỡ → 15 kept; test chỉ đọc hợp đồng đó từ `pyproject.toml`, không viết bản thứ hai.
  Cổng (trên bản xuất sạch của HEAD cộng tệp của ticket, vì cây chung có sửa dở của phiên khác ở `wflite/`): ruff,
  format, mypy, lint-imports, bandit, verify_invariants, verify_architecture, test_verify_architecture.sh, check_hygiene,
  generate_contracts, release_manifest, `run_evals.py --smoke` xanh; unit qua cổng coverage, một test đỏ ngoài ticket
  (MEDIUM (d) dưới đây).
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `security_pass_rate` là `float` với `Field(ge=1.0, le=1.0)` thay
  `Literal[1.0]`: kiểu không có Literal số thực và mypy từ chối nó; mọi giá trị khác 1.0 vẫn lỗi validate. Nếu sai thì:
  một validator nêu tên 1.0, cùng test.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): báo cáo của `run_cases` dùng `EvalReport` với `dataset_id`,
  `dataset_version`, `worker_id` là `None` (câu có thể đến từ nhiều nguồn: bộ an ninh và ca kịch bản của ticket 06);
  `security_coverage_ok` tính từ category của các câu bằng một hàm `has_full_security_coverage` mà `EvalDataset` cũng
  gọi, nên luật phủ có một chủ. Nếu sai thì: `run_cases` nhận danh tính dataset qua tham số từ khóa.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `judge_grader`: câu khai `input` hay `expected` bằng tham chiếu tệp →
  `abstain` `judge_needs_inline_case` mà không hỏi giám khảo (bộ chấm không có thư mục gốc để đọc tệp; `unknown` chặn
  như trượt); lần thử không có `final_output` → trượt `no_final_output`, không hỏi. `ScriptedJudge` đọc `case_id` từ
  `case_input["case_id"]`, vì chữ ký `JudgePort.judge(rubric, case_input, output, reference)` của ticket không mang id
  câu. Nếu sai thì: `run_cases` đọc tham chiếu trước khi chấm, và `JudgePort.judge` nhận id câu.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): `run_cases`: lần thử đánh số từ 1, chạy lần lượt, không dừng sớm (tiêu
  chí R3.1 đòi đủ 3 lời gọi); tên bộ chấm không có trong bảng → câu trượt `unknown grader` với `trials = 0`, không gọi
  target (như `scenario_invalid` 0 lần thử của ticket 06); `pass_k` ngoài 1-10 hay hai câu cùng `case_id` →
  `ValueError` trước lần thử đầu. `merge_graders` generic bằng tham số kiểu PEP 695 (ruff UP047). Nếu sai thì: chạy các
  lần thử của câu không chấm được và trượt từng lần.
- 2026-11-05 (agent): MEDIUM, cho lượt đóng hàng đợi và ticket 06: (a) `GatePolicy.policy_id` và `version` chỉ định
  danh chính sách, chưa ai đọc tới khi ticket 06 ghi chúng với Lượt kiểm định; `security_pass_rate` chỉ được đọc như cận
  của validator, luật từng câu của `evaluate_gate` là nghĩa của 1.0; (b) `EvalReport.ok` của một báo cáo `run_cases`
  đòi đủ ba category an ninh của CI, mà Bộ kiểm định an ninh nền tảng có thể không có: cổng của ticket 06 kết luận bằng
  `evaluate_gate`, không bằng `ok`; (c) ở cây làm việc chung, mypy báo 6 lỗi ở `dw_agent_runtime/wflite/*` và pytest
  lỗi khi thu test (`validate()` thiếu `rules`), từ sửa dở chưa commit của phiên khác, không của ticket này; (d) bộ unit
  toàn repo trên bản xuất sạch: 3011 passed, 1 failed, coverage 76.97% (ngưỡng 70%); test đỏ là
  `dw_agent_runtime/tests/unit/test_telemetry_usage.py::test_a_gateway_call_emits_only_pinned_names_and_no_input_value`,
  xanh khi chạy riêng và trong 928 test của gói, chạy trước mọi test của `dw_evals` và không gói nào của nó import
  `dw_evals`: phụ thuộc thứ tự, ngoài ticket này, để lượt đóng hàng đợi tìm.
- 2026-11-05 (agent): cho lúc đóng hàng đợi: `scripts/mutate.py` với `mutations/02.yaml`. Không test integration nào
  thêm, không đo trễ (không route hay trang nào đổi), không ảnh chụp.
