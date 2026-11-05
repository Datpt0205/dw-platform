# 05 — Nâng deepagents lên 0.7.32 và khóa những gì nó đổi bằng test hợp đồng

Status: ready-for-agent
Area: studio
Yêu cầu: không (W2 "deepagents `>=0.7.23`" ở Ngoài phạm vi của spec; ADR-0116 (Accepted) quyết 7, FOG-34)

## Mục tiêu

Đổi ghim `deepagents==0.7.15` (`packages/python/dw_agent_runtime/pyproject.toml:24`) sang bản chính xác mà discovery/15
đã đo, cùng các gói nó kéo theo, trước khi kỹ năng của W2 dùng `SkillsMiddleware` với `include_tools`
(ADR-0116 (Accepted) quyết 7), và khóa bằng test hợp đồng hai sự thật mà bản mới thêm: `include_tools` của một kỹ năng
đưa một công cụ cho model sau lớp lọc `OfferedToolsOnlyMiddleware` khi lớp lọc đứng ngoài, và chạy công cụ đó ở cả hai
thứ tự (discovery/15 `## Answer`, câu 3). Ticket không dựng kỹ năng; nó làm cho lần dựng kỹ năng đứng trên một bản đã
đo.

## Việc cần làm

1. Ghim `deepagents==0.7.32` (lên PyPI 23/10/2026, bản discovery/15 đo) và khóa lại. Mỗi gói mà `uv.lock` đổi bản phải
   lên PyPI ít nhất 14 ngày trước ngày khóa (cùng luật với ghim LiteLLM của model-connections/01), kể cả deepagents
   0.7.32, nên ticket chỉ khóa từ 6/11/2026. Đo ngày 5/11/2026 trên một bản xuất sạch,
   `uv lock --upgrade-package deepagents` kéo theo: langchain 1.4.1 → 1.4.9, langchain-core 1.6.3 → 1.7.6, langgraph 1.2.11 → 1.2.20,
   langgraph-checkpoint 4.2.0 → 4.3.1, langsmith 0.12.6 → 0.14.17, langchain-anthropic 1.7.2 → 1.7.10,
   langchain-google-genai 4.4.0 → 4.4.3, langchain-protocol 0.0.19 → 0.0.20; trong đó langchain 1.4.9 (4/11),
   langchain-core 1.7.6 (5/11), langgraph 1.2.20 (5/11), langsmith 0.14.17 (2/11), langchain-anthropic 1.7.10 (4/11) và
   langchain-google-genai 4.4.3 (4/11) chưa đủ 14 ngày. Mức tối thiểu bắt buộc: langchain ≥ 1.4.7 (kéo langgraph ≥ 1.2.12,
   langchain-core ≥ 1.6.13), langchain-core ≥ 1.7.0, langsmith ≥ 0.14.12, langchain-anthropic ≥ 1.7.6,
   langchain-google-genai ≥ 4.4.2 (`Requires-Dist` của deepagents 0.7.32). Người dựng chọn, cho mỗi gói, bản mới nhất
   vừa đủ 14 ngày tuổi ở ngày khóa và không dưới mức bắt buộc (ngày lên PyPI đọc từ `https://pypi.org/pypi/<gói>/json`),
   khóa bằng `uv lock --upgrade-package <gói>==<bản>` cho từng gói của bộ, không dùng `--exclude-newer`, và kiểm
   `git diff uv.lock`: một gói ngoài danh sách trên mà resolver buộc đổi theo (như langgraph-prebuilt) cũng theo luật
   14 ngày và được ghi ở Comments; gói nào resolver không buộc đổi thì không đổi. Ở các mức `>=` hiện có trong
   `packages/python/dw_agent_runtime/pyproject.toml` (`langchain-core>=1,<2`, `langgraph>=0.6,<2`, `langchain>=1,<2`),
   nâng chặn dưới lên mức bắt buộc ở trên, để lần `uv lock` sau không lùi xuống dưới nó. Nếu một gói chưa có bản nào
   vừa đủ 14 ngày tuổi mà không dưới mức bắt buộc, ticket chờ tới ngày có, không khóa bản trẻ hơn.
2. Hai test hợp đồng mới trong `packages/python/dw_agent_runtime/tests/unit/test_library_contracts.py`, docstring nêu
   phiên bản đã đo:
    - (d) với `SkillsMiddleware(tools=[t])`, một kỹ năng khai `include_tools: t`, và `OfferedToolsOnlyMiddleware` dựng
      với một tập offer KHÔNG chứa `t` (như `billing__refund` của discovery/15), sau khi model đọc `SKILL.md`: `t` có
      trong `request.tools` mà model nhận khi `OfferedToolsOnlyMiddleware` đứng trước (ngoài) `SkillsMiddleware` và
      không có khi nó đứng sau (trong), và lời gọi `t` mà model giả trả về chạy (handler của `t` được gọi đúng 1 lần) ở
      cả hai thứ tự. Model của (d) là model giả không có `mid_conversation_tools`, để đường lộ đi qua `request.tools`.
    - (e) với một `langchain_openai.ChatOpenAI` thật dựng với `profile={"mid_conversation_tools": True}` (nhánh
      `_inline_block_builder` của `deepagents/middleware/_skill_tools.py` chỉ nhận model Anthropic hay OpenAI theo
      `isinstance`, không nhận model giả), không gọi mạng: một middleware trong cùng, đứng sau mọi middleware khác, ghi
      lại `request` và trả một `AIMessage` dựng sẵn thay vì gọi handler. Khẳng định: `t` không có trong `request.tools`
      và có trong một `SystemMessage` chèn vào `request.messages`; cùng ca với `profile={"mid_conversation_tools": False}`
      (truyền tường minh, không để langchain-openai điền profile theo tên model) thì `t` có trong
      `request.tools` và không có `SystemMessage` chèn, để (e) đỏ khi thư viện đổi đường lộ.

    Hai test này nói điều ADR-0116 (Accepted) quyết 7 ("một kỹ năng không bao giờ cấp công cụ") phải giữ bằng cách nào;
    cách giữ là của ticket kỹ năng W2. Viết `mutations/05.yaml` với một đột biến: `OfferedToolsOnlyMiddleware`
    (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py`) giữ mọi công cụ của
    `request.tools` thay vì chỉ những công cụ đã offer, với test (d) phải đỏ (ở thứ tự lọc trong, `t` hiện ra).

3. Chạy lại trên bộ đã khóa: toàn bộ `-m unit` (5/11/2026 trên Windows, bộ mới nhất: 4.985 xanh, 9 bỏ qua), gồm ba test
   hợp đồng (a)-(c) và test hợp đồng R6.6 trên danh sách công cụ offer
   (`test_agent_factory.py::test_the_model_is_given_exactly_the_toolset_and_nothing_else`, mà ghi chú trên ghim ở
   `pyproject.toml` nói mọi lần nâng phải qua); thư mục `packages/python/dw_agent_runtime/tests/prototype/` của
   agent-builder/01 khi nó còn (gồm `test_approval_reaches_the_runner.py` và `test_resume_runs_no_call_twice.py` của
   discovery/15), hay các test thay nó của agent-builder/03 khi ticket đó đã xóa thư mục; bốn test tích hợp checkpoint
   (langgraph-checkpoint đổi bản phụ): `packages/python/dw_agent_runtime/tests/integration/test_checkpoint_writes.py`,
   `test_checkpoint_retention.py`, `test_resume_after_restart.py`, `test_resume_once_db.py`; và `measure_compile.py`
   (`--keys 256`, cả hai `--mode`; khi agent-builder/03 đã xóa thư mục thì chạy bản ở commit trước khi xóa, lấy bằng
   `git show <commit>:<đường dẫn>` ra thư mục tạm).
4. Thêm `SkillsMiddleware` vào tập wrapper của `test_approval_reaches_the_runner.py` (hay test thay nó ở ticket
   agent-builder/03): từ 0.7.22 nó có `awrap_tool_call`, nên interrupt phê duyệt phải qua được nó. Công cụ cần duyệt là
   công cụ nền tảng dựng (qua executor, như `lead.send_offer` hôm nay), có trong tập offer của
   `OfferedToolsOnlyMiddleware` và nằm trong `include_tools` của một kỹ năng mà model đã đọc, nhưng chỉ được trao cho
   `SkillsMiddleware(tools=[...])`, không cho `tools` của `create_agent`: ở 0.7.32, một công cụ đã có trong
   `request.tools` thì `SkillsMiddleware.awrap_tool_call` chuyển thẳng (`request.tool is not None`), còn công cụ chỉ Skills
   giữ mới đi nhánh `_with_disclosed_skill_tool`, đúng đường mà kỹ năng W2 sẽ dùng. "Hai vị trí" là đầu và cuối danh
   sách `platform_middleware`, như `FilesystemMiddleware` của discovery/15.
5. Sửa ghi chú trên ghim ở `packages/python/dw_agent_runtime/pyproject.toml` theo bản mới, và ghi FOG-34 đã trả lời ở
   ADR-0116 (Accepted) Open 5: bộ phiên bản đã khóa, discovery/15 và ticket này.

Bước 3 chạy trước khi commit ghim, không đợi lúc đóng hàng (`.claude/rules/wave-close.md`): `uv.lock` chạm mọi gói nên
`-m unit` toàn repo là unit test của các gói ticket chạm; bốn test checkpoint và thư mục nguyên mẫu chạy theo câu "Ask"
của luật đó, vì một ghim đỏ trên `main` để mọi lane dựng trên nó tới lúc đóng hàng.

Không dựng song song với agent-builder/03 (cùng thư mục `tests/prototype/`, mà ticket đó xóa) hay với ticket nào khác
đổi `uv.lock`.

## Tiêu chí chấp nhận

- [ ] `uv.lock` ghim `deepagents==0.7.32` và mỗi gói đổi bản cùng nó ở một bản đã lên PyPI ít nhất 14 ngày trước ngày
      khóa, không dưới mức bắt buộc của bước 1; `git diff uv.lock` không đổi gói nào mà resolver không buộc đổi;
      Comments ghi bộ phiên bản,
      ngày lên PyPI của từng bản và ngày khóa.
- [ ] Test (d) và (e) xanh trên bộ đã khóa; đổi thứ tự hai middleware trong (d) làm đúng khẳng định về thứ tự đỏ; ca đối
      chứng không cờ của (e) đỏ nếu khẳng định của ca có cờ được dùng cho nó; đột biến của `mutations/05.yaml` làm (d) đỏ.
- [ ] Interrupt phê duyệt tới bên gọi graph (và ở `aget_state().interrupts`) với `SkillsMiddleware` ở cả hai vị trí,
      công cụ chạy 0 lần trước khi quyết và đúng 1 lần sau khi duyệt; một bản bọc `SkillsMiddleware` bắt `BaseException`
      làm test đỏ.
- [ ] `-m unit`, bốn test tích hợp checkpoint và thư mục nguyên mẫu (hay test thay nó) xanh trên bộ đã khóa trước khi
      commit ghim. Một test đỏ cả ở commit gốc của ticket (chạy lại ở đó để biết) được ghi ở Comments với ticket riêng
      của nó và không chặn; một test chỉ đỏ trên bộ mới được sửa trong ticket này, hay ticket dừng, không đẩy ghim lên
      `main`, và mở ticket cho chỗ đỏ.
- [ ] `measure_compile.py` ở 256 khóa: cache còn 256 mục sau khóa thứ 257; P50, P95 biên dịch mỗi khóa và RSS của bộ
      đã khóa và của 0.7.15 ở commit gốc, đo lại trong cùng phiên trên một bản xuất của commit đó (`latency.md` bước 3),
      ghi ở Comments cạnh số của discovery/15 (0.7.15 trên Windows 6,6 / 10,0 ms, RSS 145,1 → 187,0 MiB) để tham khảo;
      P95 tệ hơn 20% so với 0.7.15 đo lại thì kèm lý do hay sửa (`.claude/rules/latency.md`).
- [ ] Xong: `uv run python -m pytest packages/python/dw_agent_runtime/tests/unit/test_library_contracts.py packages/python/dw_agent_runtime/tests/prototype` xanh.

## Nguồn

- `.claude/plans/studio/discovery/issues/15-agent-runtime.md` (`## Answer`); ADR-0116 (Accepted) quyết 7 và Open 5;
  spec tools-and-skills, Ngoài phạm vi (dòng W2 deepagents).

## Comments

- 2026-11-05 (agent, discovery/15): tách từ discovery/15. Bản 0.7.32 không làm đỏ test hợp đồng nào của 0.7.15 (ba
  test (a)-(c) và 18 test nguyên mẫu xanh trên cả hai bộ); điều nó đổi là `SkillsMiddleware` có `include_tools`, mà
  thứ tự với bộ lọc của nền tảng quyết định model thấy gì, và không thứ tự nào chặn được lời gọi.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate (builder check; không migration, không route nên không đi biên).
  Sửa sáu HIGH theo khuyến nghị: (B1) `t` không thuộc tập offer của (d), không thì hai thứ tự cho cùng kết quả;
  (B2) luật 14 ngày áp cho mọi gói đổi bản, kể cả deepagents 0.7.32 (đủ 14 ngày từ 6/11/2026), vì đo PyPI ngày
  5/11/2026 thì langchain 1.4.9, langsmith 0.14.17, langchain-anthropic 1.7.10 và langchain-google-genai 4.4.3 cũng chưa
  đủ, chứ không chỉ langchain-core 1.7.6 và langgraph 1.2.20; tiêu chí 1 ghim đúng 0.7.32 thay vì "≥ 0.7.23"; khóa bằng
  `--upgrade-package <gói>==<bản>` thay `--exclude-newer`; (B4) (e) dùng `ChatOpenAI` thật với `profile`, vì
  `_inline_block_builder` của 0.7.32 kiểm `isinstance` (đọc ở bản trong cache uv), có ca đối chứng không cờ; (B5)
  `mutations/05.yaml` nêu đột biến của mã repo (`OfferedToolsOnlyMiddleware`), vì hành vi được khóa nằm trong thư viện;
  (B8) không đẩy ghim khi một test chỉ đỏ trên bộ mới; (cặp) không chạy song song với agent-builder/03. Nếu sai thì:
  ghim bộ mới nhất của discovery/15 và tiêu chí 1 về "≥ 0.7.23".
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): MEDIUM, sửa luôn: (B3) chặn dưới của `pyproject.toml` nâng lên mức bắt
  buộc; (B6) công cụ cần duyệt của bước 4 đi qua `include_tools`, hai vị trí là đầu và cuối `platform_middleware`;
  (B7) tiêu chí đo biên dịch ở 256 khóa; (B9) test R6.6 nêu tên ở bước 3, ghi chú ghim và ADR-0116 (Accepted) Open 5 ở bước 5;
  ticket chưa có dòng trong Danh sách ticket của spec (thêm). Còn lại: docstring của `OfferedToolsOnlyMiddleware` nói
  "measured on the pinned deepagents 0.7.5", cũ từ trước 0.7.15; người dựng sửa khi chạm tệp đó.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) sửa thêm: công cụ cần duyệt của bước 4
  chỉ Skills giữ, vì ở 0.7.32 một công cụ đã có trong `request.tools` đi nhánh chuyển thẳng của
  `SkillsMiddleware.awrap_tool_call` (đọc `skills.py` của bản trong cache uv); mức `langchain-anthropic ≥ 1.7.6`,
  `langchain-google-genai ≥ 4.4.2` từ `Requires-Dist`; gói resolver buộc đổi ngoài danh sách theo cùng luật; ca đối
  chứng của (e) truyền cờ tắt tường minh; mốc biên dịch đo lại 0.7.15 trong cùng phiên; bước 3 chạy trước commit ghim,
  lý do ghi cạnh nó. Nếu sai thì: bước 4 trao công cụ cho cả `create_agent` và Skills, và test chỉ phủ nhánh chuyển
  thẳng.
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
