# 15 — Agent của tenant trên runner hiện có: bản deepagents, ghép middleware, host graph đã biên dịch

Type: prototype
Status: resolved
Area: studio · Viết: 23/10/2026
FOG: FOG-34 `deepagents-pin`, FOG-35 `middleware-compose`, FOG-36 `agent-hosting`

## Câu hỏi

1. Bản deepagents chính xác nào (0.7.23 trở lên; repo khóa 0.7.15 ở `uv.lock:680`) và những gì đi theo: langchain
   1.4.1 lên 1.4.6, langchain-core 1.6.3 lên 1.6.12, langsmith 0.12 lên 0.14 (FOG-34)?
2. Stack middleware của agent con có còn chỉ dựng từ `sub_agent_spec`, để middleware kiểm soát lượt chạy tới được agent
   liên kết không; `CompiledSubAgent` có giữ `recursion_limit` 9999 không, và gắn lại có sửa được không (FOG-34)?
3. Wrapper công cụ của `FilesystemMiddleware` có để `GraphBubbleUp` (interrupt phê duyệt) đi qua không; disclosure
   `include_tools` và các middleware Offered, Scoped, chọn công cụ của nền tảng có ghép đúng theo cả hai thứ tự không;
   `ToolCallLimitMiddleware` và `ModelCallLimitMiddleware` làm gì với lời gọi công cụ song song (FOG-35)?
4. Runner có host được một graph `create_agent` đã biên dịch với checkpointer SQL, resume sạch sau khi lượt chạy bị
   dừng ở middleware hay executor mà không chạy lại lời gọi công cụ đã xong không; thời gian biên dịch, bộ nhớ và cỡ
   LRU theo (tenant, phiên bản, mã băm đã ghim) mà worker trên host 2 vCPU chịu được, khi mỗi nội dung của một bản Nháp
   đem chạy mô phỏng là một mục riêng (FOG-36)?

## Vì sao

Kỹ năng, công tắc tắt khẩn cấp và trần số bước dựa vào bên trong thư viện đã từng đổi (failure-modes #4). Một interrupt
phê duyệt bị wrapper nuốt là cổng duyệt bị vượt (failure-modes #5). Câu 4 quyết đóng băng có dừng rồi tiếp tục được
không, và đặt trần cho cache biên dịch (failure-modes #6).

## Mở khóa

- Spec: `agent-builder` (01, 03), `agent-lifecycle` (01, công tắc), `tools-and-skills` (02, kỹ năng),
  `usage-and-limits` (04, trần số bước), `workflow-engine` (bước agent).
- ADR: 0116 (Open 5), 0117, 0120.
- DO: DO-28 (Đạt chốt 23/10/2026, phương án C: đóng băng hủy lượt đang chạy ở cửa kế tiếp, từ chối ngay lượt tương
  tác và giữ lượt do trình kích hoạt tới khi gỡ; đóng băng tiếp tục được ở W3, `requirements.md` mục Không làm), DO-45.
- Ticket W1: `agent-builder/01`, `agent-lifecycle/01` (P0).

## Dựng tối thiểu

Một agent `create_agent` với hai công cụ giả (một cần phê duyệt) và một agent liên kết; stack middleware của nền tảng ở
hai thứ tự; chạy trong runner hiện có với checkpointer SQL; nâng deepagents trên nhánh nháp rồi chạy lại bộ test agent.

## Phép đo quyết định

| Đo                                             | Ngưỡng                                                                                   | Quyết định                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Interrupt phê duyệt ở cả hai thứ tự middleware | Luôn tới runner; test đỏ khi wrapper nuốt nó                                             | Thứ tự middleware cố định                         |
| Lời gọi công cụ chạy lại sau resume            | 0                                                                                        | Đóng băng dừng rồi tiếp tục (W3) có khả thi không |
| Middleware kiểm soát trong agent liên kết      | Có mặt ở mọi lời gọi                                                                     | Bản deepagents và cách gắn                        |
| Biên dịch: thời gian, RSS mỗi graph            | Ghi số dưới giới hạn worker 1 CPU / 1 GB (`infra/compose/docker-compose.prod.yml:40-41`) | Cỡ LRU theo (tenant, phiên bản, mã băm đã ghim)   |

## Nguồn

- Brief B8b, B9, B10a, B10b; `uv.lock:1974`, `uv.lock:2002`, `uv.lock:2133` (langchain, langchain-core, langsmith).
- [research.md](../research.md) mục 4 và 6 (host graph `create_agent`, `FilesystemMiddleware`, bản deepagents chưa
  kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 1-4.
- Cách làm: chính agent-builder/01 (`ready-for-agent`, model giả, không cần khóa): nguyên mẫu dưới
  `tests/prototype/`, ba test hợp đồng thư viện trong
  `packages/python/dw_agent_runtime/tests/unit/test_library_contracts.py`, đo biên dịch ở 10, 100 và 256 khóa, resume
  qua `SqlAlchemyCheckpointSaver` với `os._exit`. Thêm cho câu 1: chạy lại các test đó trên deepagents mới nhất
  (≥ 0.7.23) trong venv tạm, không đổi `uv.lock` (đang 0.7.15), và ghi những gì đổi.
- Đầu ra: Comments của agent-builder/01; ticket này đóng bằng một `## Answer` trỏ tới đó.
- Đạt khi: bảng Phép đo quyết định ở trên: interrupt phê duyệt luôn tới runner ở cả hai thứ tự và test đỏ khi
  wrapper nuốt nó; 0 lời gọi công cụ chạy lại sau resume; middleware kiểm soát có ở mọi lời gọi của agent liên kết;
  RSS ở 256 khóa dưới 1 GiB của worker.

## Answer

Đo ngày 5/11/2026 trên máy dev Windows, model giả, PostgreSQL của compose `dwskel`, `durability="sync"`; deepagents
0.7.15 của `uv.lock` và 0.7.32 trong một bản xuất sạch có `uv lock --upgrade-package deepagents` (venv tạm, đã xóa;
`uv.lock` của repo không đổi). Mã thử ở `packages/python/dw_agent_runtime/tests/prototype/`: của agent-builder/01
(`3f23034`, `8cf73a5`) cùng hai tệp của ticket này, `test_approval_reaches_the_runner.py` và
`test_resume_runs_no_call_twice.py`. Kết quả đọc lại ở Comments của agent-builder/01.

Phép đo quyết định, cả bốn ĐẠT, trên cả 0.7.15 và 0.7.32:

- **Interrupt phê duyệt ở cả hai thứ tự.** `test_approval_reaches_the_runner.py`: `FilesystemMiddleware` đứng ngoài
  (đầu danh sách) hay trong (cuối danh sách) `platform_middleware`, trên agent gọi và trên agent liên kết (qua `task`):
  đúng một interrupt `studio.agent.lead.send_offer` tới bên gọi graph và ở `aget_state().interrupts` (cái runner đọc),
  công cụ chạy 0 lần trước khi quyết và đúng 1 lần sau khi duyệt, lượt con chạy tiếp từ chỗ dừng (model con 2 lượt,
  không hỏi lại). Test đỏ khi wrapper nuốt: đổi wrapper thành lớp con có `except BaseException` thì 4/4 ca đỏ (thử tay,
  khôi phục từ bản sao); ca nuốt cũng là test thường trực thứ hai (4 ca, không còn interrupt nào). Thứ tự giữa các
  middleware của nền tảng đã đo ở `test_agent_factory.py` (720 thứ tự, và một middleware nuốt tất cả làm mất phê duyệt).
  Quyết: thứ tự không quyết interrupt, điều kiện là không wrapper nào bắt `BaseException` (cảnh báo sẵn của
  `platform_middleware`); thứ tự cố định có một chỗ ở câu 3: `SkillsMiddleware` đứng ngoài bộ lọc công cụ.
- **0 lời gọi công cụ chạy lại sau resume.** `test_resume_runs_no_call_twice.py`, ba cách dừng sau khi một trong hai
  lời gọi song song của cùng bước đã xong: tiến trình chết bằng `os._exit` trong lời gọi kia; executor dừng chờ duyệt
  lời gọi kia; công ty bị đóng băng giữa bước và cửa model kế tiếp ném `RunHaltedError`. Tiến trình thứ hai (cache rỗng,
  executor và model mới) chạy tiếp từ `SqlAlchemyCheckpointSaver`: lời gọi đã xong chạy 0 lần, model được hỏi 1 lần,
  danh sách tin nhắn cuối như lượt chạy trọn. Đỏ tay: `durability="exit"` (ca chết không để lại checkpoint nào) và saver
  bỏ pending writes ở tiến trình đầu (ca chết và ca duyệt chạy lại `lead.find` 1 lần). Điều kiện: `durability="sync"` và
  `aput_writes` ghi bền. Quyết: về phía thư viện, đóng băng dừng rồi tiếp tục (W3) khả thi: lượt bị chặn ở cửa model
  tiếp tục bằng `ainvoke(None)` mà không chạy lại công cụ nào; trạng thái run và ai mở lại là việc của agent-lifecycle.
- **Middleware kiểm soát trong agent liên kết.** `test_studio_sub_agent_stack.py` (agent-builder/01): cả hai lời gọi
  model của con đi qua `run_control` rồi chọn model của chính con, model mặc định của con 0 lượt; đột biến ở
  `agent-builder/mutations/01.yaml`. Quyết: 0.7.15 hay 0.7.32 đều được; gắn bằng `sub_agent_spec` (ngăn xếp của con dựng
  lại, không thừa hưởng), không dùng `CompiledSubAgent`.
- **Biên dịch: thời gian, RSS.** Bảng ở mục Quyết định của `agent-builder/spec.md` (`3f23034`): 256 khóa, biên dịch
  5,1 / 7,5 ms P50 / P95 mỗi khóa (Linux), RSS cả tiến trình 183,8 MiB (Windows 182,4), cache 37-39 MiB, 18% của 1 GiB;
  LRU còn 256 mục sau khóa thứ 257. Đo lại 256 khóa trên Windows ngày 5/11/2026: 0.7.15 6,6 / 10,0 ms, RSS 145,1 →
  187,0 MiB; 0.7.32 5,4 / 8,6 ms, RSS 149,0 → 190,3 MiB (+41,3), cả hai còn 256 mục. Quyết: trần 256 của ADR-0117
  (Accepted) quyết 5 giữ nguyên.

Câu hỏi:

1. **0.7.32** (mới nhất trên PyPI, 23/10/2026). `uv lock --upgrade-package deepagents` kéo theo: langchain 1.4.1 →
   1.4.9, langchain-core 1.6.3 → 1.7.6, langgraph 1.2.11 → 1.2.20, langgraph-checkpoint 4.2.0 → 4.3.1, langsmith 0.12.6
   → 0.14.17, langchain-anthropic 1.7.2 → 1.7.10, langchain-google-genai 4.4.0 → 4.4.3, langchain-protocol 0.0.19 →
   0.0.20. Mức bắt buộc: langchain ≥ 1.4.7 (kéo langgraph ≥ 1.2.12), langchain-core ≥ 1.7.0, langsmith ≥ 0.14.12;
   langchain-core 1.7.6 và langgraph 1.2.20 ra ngày 5/11/2026. Trên bộ đó: ba test hợp đồng (a)-(c) và 18 test nguyên
   mẫu xanh, cả bộ `-m unit` của repo 4.985 xanh, 9 bỏ qua (Windows); mọi số đo của câu 2 và 3 giống hệt 0.7.15.
   Không nâng ở đây: tools-and-skills/05 (`needs-triage`) nâng và khóa hai sự thật mới của câu 3 bằng test hợp đồng.
2. **Có.** Con khai báo được biên dịch bằng `create_agent(model, tools, middleware=spec["middleware"])`, cộng
   `HumanInTheLoopMiddleware` chỉ khi khai `interrupt_on` (`deepagents/middleware/subagents.py:543-547` ở 0.7.15); đo:
   con với `middleware=[]` chỉ thấy công cụ của nó và prompt hệ thống rỗng, ở cả hai bản. `create_deep_agent` gắn
   `recursion_limit` 9999 (`deepagents/graph.py:973`) và giữ nó khi làm `CompiledSubAgent`: dưới lượt cha
   `recursion_limit` 20, con chạy 60 lời gọi model tới khi chốt chặn của script dừng nó; gắn lại bằng
   `.with_config({"recursion_limit": 12})` sửa được (`GraphRecursionError` sau 6 lời gọi của con). Nhưng
   `recursion_limit` của cha không chặn con nào, kể cả con khai báo và `CompiledSubAgent` dựng bằng `create_agent` (cả
   hai 60 lời gọi dưới cha 20): hôm nay chỉ `LimitsMiddleware` với lease của cha (`sub_agent_spec`) chặn một con lặp. Vậy
   bước 4 của usage-and-limits/06 (truyền `recursion_limit` ở mỗi lần con chạy) là cần, và cách truyền đo được là
   `CompiledSubAgent` với `.with_config`, vì `SubAgent` khai báo không có trường nào cho nó.
3. **`FilesystemMiddleware` để `GraphBubbleUp` đi qua**: `awrap_tool_call` không bắt gì ("propagate unhandled by
   design", `filesystem.py:3605-3651`), đo ở cả hai vị trí (trên). **`include_tools` thì không ghép đúng ở thứ tự nào**
   (0.7.32; từ 0.7.22): với `SkillsMiddleware(tools=[billing__refund])` và một kỹ năng mà `include_tools` nêu
   `billing__refund`, sau khi model đọc `SKILL.md`, `OfferedToolsOnlyMiddleware` đứng ngoài thì model được đưa
   `billing__refund` dù nó không được offer, đứng trong thì không thấy; ở cả hai thứ tự lời gọi `billing__refund` vẫn
   chạy, vì `SkillsMiddleware.awrap_tool_call` gắn công cụ vào lời gọi. Với model có `mid_conversation_tools`
   (Anthropic, OpenAI), công cụ được lộ đi vào tin nhắn hệ thống, không vào `request.tools`, nên `OfferedToolsOnly` và
   `ScopedTools` (cùng lọc `request.tools`) không thấy nó ở thứ tự nào (đọc mã `_skill_tools.py:_inline_block_builder`,
   chưa chạy với model thật). Hệ quả cho ADR-0116 (Accepted) quyết 7 ("một kỹ năng không bao giờ cấp công cụ"):
   `SkillsMiddleware` chỉ được nhận công cụ đã ghim do nền tảng dựng (qua executor), đứng ngoài bộ lọc, và cần một cổng ở
   lúc gọi công cụ, không chỉ lúc gửi model. Middleware chọn công cụ của nền tảng chưa có (W2), không đo.
   **`ToolCallLimitMiddleware`** với lô 3 lời gọi song song và `run_limit=2`: `continue` chạy 2 lời gọi đầu và trả lỗi
   cho lời gọi thứ ba (chạy một phần lô); `error` ném trước khi chạy lời gọi nào; `end` không chạy lời gọi nào và kết
   thúc lượt. **`ModelCallLimitMiddleware`** (`run_limit=1`) đếm lời gọi model: cả 3 lời gọi công cụ song song chạy, lời
   gọi model kế tiếp bị chặn (`end` kết thúc lượt, `error` ném). Bước 5 của usage-and-limits/06 vì vậy dùng `error`
   (hay bọc), không `continue`. Giống hệt trên 0.7.15 và 0.7.32.
4. **Có.** Graph `create_agent` đã biên dịch, giữ trong LRU của nguồn, resume sạch qua `SqlAlchemyCheckpointSaver` sau
   khi dừng ở executor (chờ duyệt), ở middleware (`RunHaltedError` ở cửa model) hay vì tiến trình chết, 0 lời gọi chạy
   lại (trên); điều kiện là `durability="sync"`, như agent-builder/01 đo. Cỡ LRU 256 theo (tenant, phiên bản, mã băm đã
   ghim), mỗi nội dung Nháp một mục: số ở dòng biên dịch trên.

Chưa đo: middleware chọn công cụ (W2), đường lộ công cụ trong tin nhắn với model Anthropic hay OpenAI thật, ảnh worker
thật với giới hạn 1 GiB của compose, Linux cho bản 0.7.32.

## Comments

- 2026-10-24 (agent, tạm): câu 4 và dòng biên dịch của Phép đo quyết định đo cache graph agent theo khóa
  `(tenant_id, agent_version_id, pinned_hash)`, vì Kiểm định thử nhận bản Nháp của agent, và một bản Nháp chỉ được
  biên dịch dưới mã băm tạm mà bản kê của lượt `simulate` ghim (ADR-0117 (Accepted) quyết 5, ADR-0109 (Accepted)
  quyết 6), nên mỗi nội dung nháp đem chạy mô phỏng là một mục cache riêng; quy trình đã khóa cache như vậy
  (ADR-0112 (Accepted) quyết 4). Sửa: Câu hỏi (câu 4), Phép đo quyết định (dòng biên dịch). Nếu sai thì: bản Nháp
  của agent không chạy được, cache giữ khóa `(tenant_id, agent_version_id)`, và câu 4 đo cỡ LRU theo (tenant, phiên
  bản) như trước.
- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Chưa câu nào được đo: agent-builder/01 gate xong (2/11/2026) nhưng chưa dựng, `uv.lock` vẫn khóa deepagents 0.7.15. Không cần người, khóa hay máy riêng.
