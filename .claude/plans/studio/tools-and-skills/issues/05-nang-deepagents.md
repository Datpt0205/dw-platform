# 05 — Nâng deepagents lên 0.7.32 và khóa những gì nó đổi bằng test hợp đồng

Status: needs-triage
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

1. `uv lock --upgrade-package deepagents` với ghim `deepagents==0.7.32` (bản mới nhất trên PyPI, 23/10/2026). Đo ngày
   5/11/2026 trên một bản xuất sạch, lệnh đó kéo theo: langchain 1.4.1 → 1.4.9, langchain-core 1.6.3 → 1.7.6, langgraph
   1.2.11 → 1.2.20, langgraph-checkpoint 4.2.0 → 4.3.1, langsmith 0.12.6 → 0.14.17, langchain-anthropic 1.7.2 → 1.7.10,
   langchain-google-genai 4.4.0 → 4.4.3, langchain-protocol 0.0.19 → 0.0.20. Mức tối thiểu bắt buộc: langchain ≥ 1.4.7
   (kéo langgraph ≥ 1.2.12, langchain-core ≥ 1.6.13), langchain-core ≥ 1.7.0, langsmith ≥ 0.14.12. langchain-core 1.7.6
   và langgraph 1.2.20 lên PyPI ngày 5/11/2026: người dựng chọn bản ít nhất hai tuần tuổi trong khoảng đó, ghi lý do,
   và đo lại bước 3 trên đúng bộ đã chọn.
2. Hai test hợp đồng mới trong `packages/python/dw_agent_runtime/tests/unit/test_library_contracts.py`, docstring nêu
   phiên bản đã đo: (d) với `SkillsMiddleware(tools=[t])` và một kỹ năng khai `include_tools: t`, sau khi model đọc
   `SKILL.md`, `t` có trong công cụ gửi model khi `OfferedToolsOnlyMiddleware` đứng trước (ngoài) và không có khi nó
   đứng sau (trong), và lời gọi `t` chạy ở cả hai thứ tự; (e) với một model có `mid_conversation_tools` (Anthropic,
   OpenAI), công cụ được lộ đi vào tin nhắn hệ thống chứ không vào `request.tools`, nên một bộ lọc chỉ đọc
   `request.tools` không thấy nó (`deepagents/middleware/_skill_tools.py:_inline_block_builder`). Hai test này nói
   điều ADR-0116 (Accepted) quyết 7 ("một kỹ năng không bao giờ cấp công cụ") phải giữ bằng cách nào; cách giữ là của
   ticket kỹ năng W2.
3. Chạy lại trên bộ mới: toàn bộ `-m unit` (5/11/2026 trên Windows: 4.985 xanh, 9 bỏ qua), ba test hợp đồng (a)-(c), thư mục
   `tests/prototype/` của agent-builder/01 khi nó còn (gồm `test_approval_reaches_the_runner.py` và
   `test_resume_runs_no_call_twice.py` của discovery/15), test tích hợp checkpoint (langgraph-checkpoint đổi bản phụ),
   và `measure_compile.py` ở 256 khóa.
4. Thêm `SkillsMiddleware` vào tập wrapper của `test_approval_reaches_the_runner.py` (hay test thay nó ở ticket
   agent-builder/03): từ 0.7.22 nó có `awrap_tool_call`, nên interrupt phê duyệt phải qua được nó ở cả hai vị trí.

## Tiêu chí chấp nhận

- [ ] `uv.lock` ghim `deepagents` đúng một bản ≥ 0.7.23 và mọi gói nó kéo theo; Comments ghi bộ phiên bản và lý do.
- [ ] Test (d) và (e) xanh trên bộ mới; đổi thứ tự hai middleware trong (d) làm đúng khẳng định về thứ tự đỏ; sai nếu
      một đột biến của `mutations/05.yaml` để mọi test xanh.
- [ ] Interrupt phê duyệt tới bên gọi graph với `SkillsMiddleware` ở cả hai vị trí, và một bản bọc nuốt nó làm test
      đỏ.
- [ ] `-m unit`, test tích hợp checkpoint và thư mục nguyên mẫu xanh trên bộ mới, hoặc mỗi chỗ đỏ có ticket riêng.
- [ ] Xong: `uv run python -m pytest packages/python/dw_agent_runtime/tests/unit/test_library_contracts.py packages/python/dw_agent_runtime/tests/prototype` xanh.

## Nguồn

- `.claude/plans/studio/discovery/issues/15-agent-runtime.md` (`## Answer`); ADR-0116 (Accepted) quyết 7 và Open 5;
  spec tools-and-skills, Ngoài phạm vi (dòng W2 deepagents).

## Comments

- 2026-11-05 (agent, discovery/15): tách từ discovery/15. Bản 0.7.32 không làm đỏ test hợp đồng nào của 0.7.15 (ba
  test (a)-(c) và 18 test nguyên mẫu xanh trên cả hai bộ); điều nó đổi là `SkillsMiddleware` có `include_tools`, mà
  thứ tự với bộ lọc của nền tảng quyết định model thấy gì, và không thứ tự nào chặn được lời gọi.
