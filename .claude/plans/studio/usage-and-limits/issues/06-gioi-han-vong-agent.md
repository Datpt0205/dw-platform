# 06 — Giới hạn hành vi của vòng agent: lời gọi model, lời gọi công cụ và recursion_limit của subagent

Status: ready-for-agent
Blocked by: 04, .claude/plans/studio/agent-builder/issues/03-runtime-agent.md
Area: studio
Yêu cầu: R6.3, UL13

## Mục tiêu

Một lượt chạy agent dừng sạch ở ranh giới kế tiếp với `limit_exceeded` khi chạm số lời gọi model, số lời gọi công cụ
hay độ sâu đệ quy mà `RunLimits` của ticket 04 kẹp theo Trần của gói, kể cả trong Agent con của `SubAgentMiddleware`
(`adapters/sub_agents.py`), dựng trên ngăn xếp `create_agent` của nền tảng, không bao giờ `create_deep_agent`
(ADR-0117 (Accepted) Context), và chính sách lỗi của node không áp (spec R6.3, UL13). Đây là phần agent tách khỏi ticket 04 (V4.31): nó thuộc làn trợ lý và lối
ra W1b, không thuộc lối ra W1a, nên không ticket W1a nào chờ nó.

## Việc cần làm

1. Vòng agent của agent-builder/03 đọc `RunLimits` của ticket 04 (không tự kẹp lại):
   `ModelCallLimitMiddleware` và `ToolCallLimitMiddleware` (`exit_behavior="error"`) vào ngăn xếp middleware ở chỗ mà
   agent-builder/03 giữ thứ tự (ADR-0117 (Accepted) quyết 5), sau `ResidencyGate` và `LimitsMiddleware` (lời gọi hai
   cửa đó từ chối không tính), `ModelCallLimitMiddleware` bên trong middleware thử lại model để mỗi lần thử lại là một
   lời gọi, và middleware thử lại cùng middleware lỗi công cụ loại `LimitExceededError` khỏi tập lỗi chúng bắt hay thử lại;
   một lời gọi công cụ tính lúc model xin nó, kể cả lời gọi người duyệt từ chối và `ask__<agent>`; lời gọi của compaction không tính (đã tính tiền qua
   lease); ticket này không đổi thứ tự của `ResidencyGate` và `LimitsMiddleware` (spec R6.5).
2. Bộ đếm sống qua mọi lần tiếp tục: trước khi viết, đo trên `langchain`, `langgraph` và `deepagents` đang ghim xem
   `thread_limit` của hai middleware có giữ số qua một lần dừng chờ người rồi tiếp tục từ checkpoint không, và
   `run_limit` có đặt lại không; ghi kết quả vào Comments (failure-modes #4). Giữ được → dùng `thread_limit` bằng giá trị
   của `RunLimits`; không giữ → bộ đếm trong trạng thái của lượt (như bộ đếm Bước của wrapper nút,
   workflow-engine:R4.20), hai middleware đọc nó (gate 4/11/2026 (b)).
3. Agent con của `SubAgentMiddleware` dùng chung bộ đếm của lượt gốc: `sub_agent_spec` trao middleware của con cùng
   một đối tượng đếm, như nó trao cùng sổ chi hôm nay (`adapters/sub_agents.py`), nên Agent con không nhân được trần; số
   con đã tiêu cộng vào bộ đếm trong trạng thái của lượt cha khi lời gọi `task` kết thúc, trong cùng bước được ghi
   checkpoint, nên lượt tiếp tục ở tiến trình khác vẫn thấy; Agent con không dừng chờ người ở W1;
   agent liên kết là lượt con có `RunLimits` của phiên bản của nó, chung lease tiền với lượt gốc (ADR-0117 (Accepted)
   quyết 7; spec R5.6) (gate 4/11/2026 (c)).
4. `recursion_limit` bằng `RunLimits.max_steps` (trường `steps` của phiên bản agent, kẹp theo `max_steps_per_run` của
   gói), truyền ở mọi lần gọi vòng agent và ở mỗi lần Agent con chạy; `GraphRecursionError` là `metric` `steps` (gate
   4/11/2026 (d), sửa ở lượt xác nhận để trường `steps` có bên đọc).
5. Một phản hồi model mang nhiều lời gọi công cụ mà tổng vượt phần còn lại → không lời gọi nào của lô chạy, lượt dừng
   `limit_exceeded`; đo cách `ToolCallLimitMiddleware` xử lô trên phiên bản đang ghim, bọc lại nếu nó chạy một phần lô
   (gate 4/11/2026 (e)).
6. Vi phạm ở vòng agent → `LimitExceededError(metric)` với `metric` `model_calls`, `tool_calls` hay `steps` (tên của
   ticket 04), một chỗ đổi `ModelCallLimitExceededError`, `ToolCallLimitExceededError` và `GraphRecursionError` sang lỗi
   đó; run `failed`, `error.code = limit_exceeded`, không áp chính sách lỗi của node, audit `run.limit_stopped` qua cùng
   đường ticket 04 ghi. Lượt agent là lượt con của một Bước `ai.agent` chạm trần hành vi của chính nó → lượt con
   `failed` `limit_exceeded`, Bước cha áp `on_error` của nó (cổng lỗi của ADR-0117 (Accepted) quyết 1), vì trần của lượt
   cha chưa cạn; agent liên kết chạm trần hành vi của mình → agent cha nhận lời gọi `ask__<agent>` lỗi như một lỗi công
   cụ; còn lease tiền hay token chung cạn (`metric` `cost_usd`, `tokens`) thì cả cây dừng như ticket 04 (gate 4/11/2026
   (f)).
7. Test trong `packages/python/dw_agent_runtime/tests/`: model giả trả lời gọi công cụ mãi; một lượt có hai lời gọi
   công cụ song song khi chỉ còn chỗ cho một; một Agent con gọi công cụ; một lượt dừng chờ người rồi tiếp tục.

## Tiêu chí chấp nhận

- [ ] R6.3 (UL13): agent với `max_tool_calls_per_run` 3 và model giả gọi công cụ mãi → lời gọi công cụ thứ tư không
      chạy, run `failed` với `limit_exceeded`, audit `run.limit_stopped`; gỡ `ToolCallLimitMiddleware` khỏi ngăn xếp →
      lời gọi thứ tư chạy, test đỏ.
- [ ] R6.3 (UL13): còn chỗ cho một lời gọi công cụ mà model trả hai lời gọi song song → không lời gọi nào của lô chạy,
      run `failed` với `limit_exceeded`; cho lô chạy một phần → lời gọi thứ nhất chạy, test đỏ.
- [ ] R6.3: chạm `max_model_calls_per_run` → dừng `limit_exceeded`, không hạ ngầm sang model rẻ hơn; một lời gọi thử
      lại tính hai; gỡ `ModelCallLimitMiddleware` → test đỏ.
- [ ] R6.3: trần 3 lời gọi công cụ, lời gọi thứ ba chờ duyệt, người duyệt, sau khi tiếp tục model xin lời gọi thứ tư →
      không chạy, `limit_exceeded`; cho bộ đếm đặt lại khi tiếp tục → lời gọi thứ tư chạy, test đỏ.
- [ ] R6.3: trần 3 lời gọi công cụ, agent cha gọi 1, Agent con gọi tiếp → lời gọi thứ tư (của con) không chạy; trao
      con một bộ đếm riêng → test đỏ.
- [ ] R6.3: một Agent con lặp vượt `recursion_limit` của lượt → dừng `limit_exceeded`; bỏ phép truyền `recursion_limit`
      cho lần chạy của con → con chạy quá giới hạn, test đỏ.
- [ ] R6.3: lượt agent con của Bước `ai.agent` khai `on_error: continue` chạm trần lời gọi công cụ của nó → lượt con
      `failed` `limit_exceeded`, Bước cha đi theo `continue`; lease chung cạn trong lượt con → cả cây `failed`.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sub_agents.py:1-40`; ADR-0117 (Accepted) Context: Agent
  con của `SubAgentMiddleware`, middleware của cha không bọc lời gọi của con, cùng sổ chi.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py:207-209`; spec: R6.3 (ngăn xếp
  middleware của vòng agent hôm nay có trần tiền `RunBudgetMiddleware` và `recursion_limit`, không trần số lời gọi).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:193-197`; spec: R6.3
  (`recursion_limit` truyền ở lời gọi của runner).
- ADR-0112 (Accepted) Context (`recursion_limit` đặt lại mỗi lần tiếp tục, đo trên LangGraph 1.2.11); ADR-0121 (Accepted)
  quyết 9; spec: R6.3 (đọc `RunLimits` mà ticket 04 kẹp theo R6.4).

## Comments

- 2026-10-26 (agent): tách từ ticket 04 theo V4.31 (mục C của lượt h): phần agent của bước 2 và các ca agent của tiêu
  chí R6.3 dời về đây, cạnh tới agent-builder/03 dời theo; R6.3 ở dòng Yêu cầu của cả hai ticket, mỗi ticket một nửa
  (quy trình ở 04, agent ở đây), UL13 cùng ticket 03; không mã nào đổi số.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; không migration, không
  route) trên `0baced0`: `check_plans.py` 24 Đạt; 1 CRITICAL, 7 HIGH, sửa theo khuyến nghị; mỗi quyết định cùng `Nếu sai
thì:` ở mục Quyết định của spec, dòng 4/11/2026 của ticket 06, (a)-(h). CRITICAL (a): ticket nói "subagent
  `create_deep_agent`", trái ADR-0117 (Accepted) Context (agent dựng trên `create_agent`, không bao giờ
  `create_deep_agent`): Agent con là của `SubAgentMiddleware` trên ngăn xếp của nền tảng. HIGH: (b) `run_limit` đặt lại
  mỗi lần tiếp tục như `recursion_limit`: đo, rồi `thread_limit` hay bộ đếm trong trạng thái; (c) Agent con nhân được
  trần: chung bộ đếm; (d) giá trị của `recursion_limit`; (e) lô lời gọi song song vượt phần còn lại; (f) ai đổi lỗi của
  thư viện sang `LimitExceededError`, tên `metric`, lượt con của `ai.agent`; (g) lời gọi nào tính và vị trí trong ngăn
  xếp; (h) bộ đếm qua tiếp tục có ca thử.
- 2026-11-04 (agent): MEDIUM, chưa sửa: (M1) công cụ `ask__<agent>` của agent liên kết là một lời gọi công cụ của cha và
  lượt con có trần riêng: một lượt gốc có thể tiêu `max_tool_calls` của cha cộng của mỗi con, giới hạn bằng lease tiền
  chung; (M2) dòng `Xong:` đọc theo `.claude/rules/wave-close.md`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên 04 và 06 cùng lúc): 0 CRITICAL, 4
  HIGH cho ticket này, sửa: vị trí của bộ đếm model mâu thuẫn với "thử lại tính hai" (bên trong thử lại, lỗi giới hạn bị
  loại khỏi tập thử lại); số của Agent con sống qua tiếp tục (cộng vào trạng thái của cha khi `task` xong); `recursion_limit`
  đọc `max_steps` để trường `steps` có bên đọc; agent liên kết chạm trần trả lỗi công cụ cho cha. Sửa của lượt này không
  có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây. MEDIUM: (M3)
  chính sách phạm vi `agent` không chặn agent chạy làm lượt con (ticket 03 M7).
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent): đo được ở discovery/15 (`5cb1074b`, `## Answer`), cho người dựng ticket này: (a) `recursion_limit` 20 của lượt cha không chặn agent liên kết (con chạy 60 lần gọi model tới khi kịch bản tự dừng; hôm nay chỉ lease tiền chung chặn con chạy vòng), còn gắn giới hạn lên agent con đã biên dịch bằng `.with_config` thì chặn được, nên bước 4 đi theo cách đó; (b) với lời gọi công cụ song song, `ToolCallLimitMiddleware` ở chế độ `continue` chạy một phần lô, `error` và `end` không chạy phần nào, nên bước 5 dùng `error` chứ không `continue`.
