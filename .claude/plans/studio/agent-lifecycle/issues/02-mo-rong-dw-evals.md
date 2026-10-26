# 02 — Mở rộng dw_evals: quan sát, bộ chấm theo quan sát, JudgePort, lần chạy lặp, chính sách cổng thuần

Status: needs-triage
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, G1

## Mục tiêu

Cổng chất lượng cần một bộ chạy kiểm định chấm theo quan sát có cấu trúc, lặp k lần và kết luận bằng
một hàm thuần có test; `dw_evals` được mở rộng chứ không thay, và giữ nguyên hành vi CI hiện có (spec
R3, G1).

## Việc cần làm

1. `dw_evals/dataset.py`: thêm `CaseCategory.SIDE_EFFECT_WITHOUT_APPROVAL`; giữ nguyên
   `SECURITY_CATEGORIES` (đó là luật phủ CI; đổi nó làm `platform@1.2.0` đỏ); `EvalCase` thêm `input`
   và `expected` nội tuyến (đúng một trong ref hoặc nội tuyến mỗi trường, có validator) và `trials: int = 1`
   (1..10).
2. `dw_evals/graders.py`: `GradeResult` thêm `unknown: bool = False` và `score: float | None`; model
   `Observation` (đầu ra cuối, lời gọi công cụ kèm cờ đã chạy hay giả lập và mã băm tham số, phê duyệt
   đã xin, tác động bị giả lập, tham chiếu bằng chứng, chi phí, độ trễ, lỗi); `ObservationGrader` và
   `JudgePort` (Protocol `judge(rubric, case_input, output, reference) -> JudgeVerdict`), làm docstring
   gói thành đúng; `GRADERS` và `merge_graders` không đổi.
3. `dw_evals/runner.py`: giữ `run_dataset` cho CI; thêm `run_cases(cases, target, graders, *, trials)`
   bất đồng bộ với pass^k, trong đó `EvalTargetPort.run(case, trial) -> Observation` khai ở `dw_evals`
   và đáp ứng ở composition root bằng bộ chạy Studio ở chế độ Mô phỏng; `EvalReport` thêm số lần thử
   mỗi câu và số theo category; `ok` giữ nghĩa.
4. `dw_evals/gate.py` mới, thuần: `GatePolicy` (Pydantic) và
   `evaluate_gate(report, policy, baseline=None) -> GateVerdict(passed, reasons)`, chủ duy nhất của
   "câu này đạt không": một Câu an ninh trượt hay `unknown` làm `passed=False` kèm lý do.
5. Sửa docstring `dw_evals/__init__.py`. `dw_evals` không import gói Studio nào (hợp đồng import-linter
   giữ nguyên hướng phụ thuộc).
6. Dataset CI mới chấm các quan sát đã ghi bằng bộ chấm Studio, mỗi bộ chấm một quan sát xấu để thấy nó
   đỏ (chuẩn bị cho ticket 06); không đổi dataset nền tảng nào.

## Tiêu chí chấp nhận

- [ ] R3.1: `run_cases` chạy một câu `consistency` với `pass_k = 3` và một bộ chấm giả xen kẽ → câu
      trượt; cả 3 lần đạt → câu đạt.
- [ ] R3.2: một bộ chấm theo quan sát trả `unknown` → `evaluate_gate` tính câu đó như trượt kèm lý do.
- [ ] R3.3: một `EvalCase` có cả ref lẫn nội tuyến cho `input` → lỗi validate, câu không chạy.
- [ ] R3.4: `evaluate_gate` cho cùng kết quả với cùng `(report, policy)` bất kể thứ tự câu; mỗi luật
      của nó có test đỏ khi gỡ luật.
- [ ] R3.5: test import-linter chặn `dw_evals` import gói Studio.
- [ ] G1: `make eval-smoke` và `apps/api/tests/unit/test_eval_datasets.py` xanh, không đổi dataset nào.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_evals/src/dw_evals/dataset.py:14-31`; spec: R3.3, G1.
- `packages/python/dw_evals/src/dw_evals/graders.py:56`; spec: R3.1, R3.2.
- `packages/python/dw_evals/src/dw_evals/__init__.py:1-2`; spec: R3.4 (docstring claim without code);
  ADR-0120 (Accepted) quyết 4.

## Comments

- 2026-10-23 (agent): từ B10a agent-lifecycle 02. Băm RFC 8785 cho Mã băm định nghĩa là một chủ ở
  tenant-config/01 (`dw_kernel.canonical`), không ở đây.
- 2026-10-26 (agent): lượt h, đợt 2: Cổng chất lượng nay ở ticket 06 (V4.31), nơi ca kịch bản tất định của quy trình
  dùng lại `run_cases`, `EvalTargetPort` và bộ chấm theo quan sát của ticket này, thêm `CaseCategory.SCENARIO`, trường
  `Observation.state` và luật `scenario` của `evaluate_gate` (V4.37; H-23); ticket này không đổi phạm vi.
