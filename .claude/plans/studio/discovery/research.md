# Nghiên cứu nền cho Studio

Status: needs-triage
Area: studio · Viết: 23/10/2026

Chỉ mục của phần nghiên cứu mà 26 ADR của Studio (0100-0125) và 25 spec của area `studio` dựa vào,
để người duyệt kiểm được bằng chứng sau từng ADR mà không cần ghi chú nháp. Nghiên cứu chạy ngày
22/10/2026 trên 17 chủ đề; ghi chú gốc không nằm trong repo, nên mỗi phát hiện dưới đây trỏ thẳng vào
nguồn chính. Quyết định của bên yêu cầu (D1-D14) là hướng đã chọn, chưa qua Đạt duyệt; chỗ bản thiết
kế không theo khuyến nghị của nghiên cứu được gom ở mục "Chỗ bản thiết kế không theo nghiên cứu".

## Cách đọc

- Mỗi chủ đề có câu hỏi, 3 đến 6 phát hiện chịu lực (mỗi phát hiện kèm nguồn, ngày, loại), phần chưa
  kiểm, và các ADR, spec dựa vào nó.
- Loại: _documented_ là tài liệu chính thức, văn bản luật (ghi rõ khi là bản dịch hay bài thứ cấp),
  LICENSE, mã nguồn thư viện hoặc advisory; _measured_ là chạy hoặc đọc mã trong môi trường nghiên cứu,
  có ghi phiên bản; _vendor claim_ là con số hay khẳng định của nhà cung cấp hoặc người viết khác mà
  đợt này không kiểm lại.
- Ngày là ngày của nguồn (phát hành, `ms.date`, advisory); trang không ghi ngày thì ghi ngày đọc.
- `path:line` trong repo đã kiểm trên `main` ngày 23/10/2026. ADR nằm ở `docs/adr/01NN-*.md`, spec ở
  `.claude/plans/studio/<spec>/spec.md`. `FOG-NN` là ticket khám phá của blueprint sẽ trả lời phần
  chưa kiểm tương ứng.

## 1. Lưu trữ đối tượng tùy biến dưới RLS

**Câu hỏi.** Bản ghi của đối tượng do tenant định nghĩa nằm ở đâu để vẫn lọc, sắp, phân trang nhanh
dưới RLS trên bảng dùng chung, mà không sinh DDL lúc chạy?

- Sản phẩm tạo DDL thật cho từng đối tượng (Dataverse, Frappe, Odoo, Twenty, Teable, Baserow) đều đi cùng database hoặc schema riêng mỗi tenant; hệ thống dùng chung bảng như Salesforce lưu lược đồ dưới dạng dữ liệu.
  Nguồn: <https://architect.salesforce.com/fundamentals/platform-multitenant-architecture> (không ghi ngày), <https://docs.frappe.io/framework/user/en/bench/guides/setup-multitenancy> (17/02/2026); _documented_.
- Dưới RLS, planner chỉ dùng index cho điều kiện có toán tử LEAKPROOF; jsonb, numeric, LIKE/trigram, `@@` và mảng thì không, nên rơi về quét cả tenant: khoảng 1,1-1,2 s mỗi 1 triệu bản ghi, tìm toàn văn 781 ms so với 0,8 ms khi tắt RLS; chỉ superuser đổi được tính leakproof.
  _measured_ 22/10/2026 trên PostgreSQL 16.15 và 18.6, 1,2 triệu bản ghi (một tenant giữ 1 triệu trong một object); quy tắc ở <https://www.postgresql.org/docs/current/sql-createpolicy.html> (_documented_, bản 18.6).
- DDL lúc chạy không hợp: `CREATE INDEX CONCURRENTLY` không chạy được trong transaction, function hay procedure, còn `CREATE INDEX` cần quyền chủ bảng.
  _measured_ 22/10/2026; <https://www.postgresql.org/docs/current/sql-createindex.html> (_documented_).
- Twenty, sản phẩm sinh DDL lúc chạy, phải chặn migration lược đồ khi còn index đang dựng vì khóa ACCESS EXCLUSIVE (PR 26446, 23/09/2026), và có sự cố migration lỗi đồng thời làm cạn pool, server treo khoảng 56 phút trong khi `/healthz` vẫn trả 200 (issue 26895, 29/09/2026).
  Nguồn: <https://github.com/twentyhq/twenty/pull/26446>, <https://github.com/twentyhq/twenty/issues/26895>; _documented_.
- Bảng bản ghi chia hash theo tenant, gồm cột hệ thống, một jsonb có trần cho trường không lọc và một ngân sách slot có kiểu (text, float8, bigint, date, timestamptz, bool) với btree từng phần, đo nhanh nhất và nhỏ nhất dưới RLS; partition pruning vẫn chạy với một dạng policy. _measured_ 22/10/2026, cùng bộ dữ liệu.
- Nhúng sản phẩm có sẵn bị giấy phép loại: NocoDB dùng Sustainable Use License từ 09/01/2026 (<https://nocodb.com/docs/self-hosting/license>), Directus dùng MSCL cấm "competing use" (<https://directus.com/mscl>, 21/10/2026), Twenty là AGPL-3.0 kèm phần EE thương mại (<https://github.com/twentyhq/twenty/blob/main/LICENSE>); _documented_.

**Chưa kiểm.** Ngưỡng của Salesforce (số flex column, 40 lookup, LDV) vì trang trả 403; Postgres managed có cho `ALTER FUNCTION ... LEAKPROOF` không; thời gian lập kế hoạch với 8 partition và khoảng 80 index slot (FOG-41 `records-storage-perf`); quy mô D12 (10 triệu bản ghi mỗi object, 50 triệu mỗi tenant).

**Dựa vào.** ADR 0107, 0105, 0100; spec `custom-objects`, `record-access`, `app-standards`.

## 2. Mô hình quyền trên bản ghi và trường

**Câu hỏi.** Tenant tự cấu hình vai và quyền tới từng bản ghi, từng trường thế nào, khi RLS của
PostgreSQL đã giữ ranh giới tenant và danh sách lớn vẫn phải nhanh?

- Salesforce và Dataverse hội tụ: quyền là khóa cộng dồn từ một danh mục do code sở hữu, gộp thành vai và bộ quyền do tenant định nghĩa; tầm với bản ghi là độ sâu trên cột của bản ghi, chia sẻ từng bản ghi chỉ cho ngoại lệ; bảo mật trường không bao giờ cấp quyền vào bản ghi; tính lại là chi phí chính (lệch khi một người phụ trách giữ hơn 10 nghìn bản ghi).
  Nguồn: <https://learn.microsoft.com/en-us/power-platform/admin/wp-security-cds> (05/10/2026), <https://learn.microsoft.com/en-us/power-platform/admin/hierarchy-security> (22/06/2026), <https://resources.docs.salesforce.com/256/latest/en-us/sfdc/pdf/draes.pdf> (16/05/2025); _documented_.
- PostgreSQL 16.15 với 2 triệu bản ghi một tenant: policy RLS join một bảng chia sẻ theo từng bản ghi mất 1,1-1,4 s cho trang đầu của người thấy rộng (tới 1,2 s cho một lần đọc theo khóa); điều kiện độ sâu trên cột có index cộng một mảng ngoại lệ GIN trả cùng tập trong 0,13-0,4 ms. _measured_ 22/10/2026.
- Toán tử không leakproof (jsonb `->>`, numeric, ILIKE, enum, mảng) mất index dưới RLS, chậm khoảng 100 lần. _measured_ cùng benchmark; cơ chế ở <https://www.postgresql.org/docs/current/ddl-rowsecurity.html> (_documented_).
- Engine ReBAC vẫn cần chỉ mục cục bộ cho danh sách lớn có sắp xếp và sẽ thành nguồn sự thật thứ hai: OpenFGA `ListObjects` mặc định hạn 3 s và tối đa 1000 kết quả (<https://openfga.dev/docs/interacting/relationship-queries>), SpiceDB gọi `LookupResources` là "heavy" khi quá 10 nghìn kết quả (<https://authzed.com/docs/spicedb/concepts/querying-data>); _documented_, đọc 22/10/2026.
- `x = ANY ((SELECT f()))` trong policy bị hiểu là dạng subquery và lỗi "operator does not exist: uuid = uuid[]"; lần chạy đầu để lại bảng bật RLS mà không có policy, trả 0 dòng. _measured_ 22/10/2026; migration tạo policy cần một test đọc lại bản ghi.
- Danh mục `platform.roles` và `platform.permission_sets` hôm nay toàn cục và chỉ đổi qua migration (`db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:7-10`). _measured_ (đọc mã).

**Chưa kiểm.** Khóa tổng hợp theo object ở 10^7 bản ghi (FOG-40 `record-access-perf`); chi phí `platform.effective_grants` mỗi request (FOG-38 `rbac-cost`); upsert dưới policy theo từng lệnh (FOG-42 `upsert-under-rls`); trang HTML của Salesforce trả 403 nên đọc qua bản PDF và trích đoạn tìm kiếm.

**Dựa vào.** ADR 0105, 0104, 0106, 0103; spec `record-access`, `tenant-rbac`, `field-security`, `org-and-principals`.

## 3. Bộ máy quy trình: tự dựng hay nhúng, và giấy phép

**Câu hỏi.** Nhúng một engine quy trình có sẵn hay tự dựng, khi chính tenant sẽ vẽ quy trình của họ?

- n8n Sustainable Use License: "You may use or modify the software only for your own internal business purposes or for non-commercial or personal use"; FAQ cấm "Host n8n as a service and allow your clients to build workflows"; bản OEM cần hợp đồng riêng và bắt buộc hiện thương hiệu n8n.
  Nguồn: <https://github.com/n8n-io/n8n/blob/master/LICENSE.md>, <https://docs.n8n.io/embed/>; _documented_, đọc 22/10/2026.
- Dify: "you may not use the Dify source code to operate a multi-tenant environment" (<https://github.com/langgenius/dify/blob/main/LICENSE>); Windmill CE cấm bọc hay phục vụ như dịch vụ (<https://github.com/windmill-labs/windmill>); server Inngest là SSPL (<https://github.com/inngest/inngest/blob/main/LICENSE.md>); Activepieces và Kestra để đa tenant và nhúng ở bản trả phí (<https://www.activepieces.com/docs/about/license>, <https://kestra.io/docs/oss-vs-paid>); _documented_.
- Biểu thức chạy được mã là mặt RCE: n8n CVE-2025-68613 vào danh sách KEV của CISA ngày 11/03/2026 (<https://www.theregister.com/2026/03/12/cisa_n8n_rce/>), CVE-2026-27577 thoát sandbox biểu thức (<https://advisories.gitlab.com/npm/n8n/CVE-2026-27577/>, 25/02/2026), Jinja2 có ba advisory thoát sandbox 2024-2025 (<https://github.com/pallets/jinja/security/advisories>); _documented_.
- `cel-expr-python` 0.1.3 (25/06/2026, Apache-2.0, bọc runtime CEL C++) dừng ở ngân sách có sẵn khoảng 10 nghìn vòng lặp, 13,2 µs mỗi lần tính, từ chối biến chưa khai báo khi biên dịch; binding Rust, JSONata, Jinja2 và Liquid mặc định không có giới hạn. _measured_ 22/10/2026; đặc tả ở <https://github.com/google/cel-spec> (_documented_).
- Temporal (MIT) là engine bền vững mạnh nhất nhưng thêm một cụm có trạng thái thứ hai, lịch sử chứa dữ liệu tenant ngoài RLS, mỗi lần chạy tối đa 51.200 sự kiện hoặc 50 MB. Nguồn: <https://docs.temporal.io/workflow-execution/limits> (không ghi ngày); _documented_.
- React Flow 12.12.0 (24/09/2026) là MIT, nhưng "Only remove this attribution, if you are subscribed to React Flow Pro". Nguồn: <https://reactflow.dev/learn/troubleshooting/remove-attribution>; _documented_.

**Chưa kiểm.** Trang editions của Activepieces trả 404, đọc qua trích đoạn tìm kiếm; plugin LangGraph của `temporalio` 1.34 còn thử nghiệm; ngân sách vòng lặp của `cel-expr-python` không chỉnh được từ Python và runtime CEL còn chưa chọn (FOG-50 `cel-runtime`); `@xyflow/react` dưới CSP nonce và React 19 (FOG-51 `canvas`).

**Dựa vào.** ADR 0112, 0114, 0101, 0100; spec `workflow-engine`, `workflow-nodes`, `workflow-builder-ui`.

## 4. Hành vi LangGraph đo trên đúng phiên bản repo ghim

**Câu hỏi.** Với `langgraph` 1.2.11, `langgraph-checkpoint` 4.2.0 và `deepagents` 0.7.15
(`uv.lock:2073-2074`, `uv.lock:2090-2091`, `uv.lock:679-680`), thư viện thật sự làm gì khi một quy
trình do tenant vẽ được biên dịch, tạm dừng, chạy tiếp và chạy lại?

- Giới hạn đệ quy mặc định là `10007` (`langgraph/_internal/_config.py:32`, ghi đè được bằng `LANGGRAPH_DEFAULT_RECURSION_LIMIT`) trong khi tài liệu <https://docs.langchain.com/oss/python/langgraph/graph-api> ghi 1000; subagent biên dịch của deepagents tự đặt `"recursion_limit": 9_999` (`deepagents/graph.py:973`). _measured_: đọc wheel đúng phiên bản, kiểm lại 23/10/2026.
- Chạy tiếp sau `interrupt()` khởi động lại cả node từ đầu, "any code that ran before the `interrupt` will execute again" (<https://docs.langchain.com/oss/python/langgraph/interrupts>, _documented_); gọi lại từ checkpoint cũ hay `update_state` chạy lại các node phía sau cùng tác động phụ của chúng (_measured_ 22/10/2026).
- Chạy tiếp trên graph đã đổi: xóa chính node đang dừng thì lượt chạy kết thúc không lỗi và các node sau không bao giờ chạy; `Command(resume={})` làm node dừng lại lần nữa mà không báo; đổi reducer hay đọc khóa state mới thì lỗi rõ. _measured_ 22/10/2026 với 1.2.11 và checkpoint 4.2.0.
- `error_handler` bị bỏ qua khi từ hai task LangGraph trở lên chung một superstep (song song, map); timeout của node chỉ chạy với node async; hai cạnh vào thường chạy node join hai lần; node không tới được vẫn biên dịch. _measured_ 22/10/2026.
- msgpack nghiêm ngặt trả object Pydantic tạo lúc chạy về `dict`; bật `EncryptedSerializer` rồi quay về bản không mã hóa thì lỗi "Unknown serialization type: msgpack+aes". _measured_ 22/10/2026. Lịch sử RCE khi giải tuần tự: GHSA-wwqv-p2pp-99h5 (CVE-2025-64439, `langgraph-checkpoint` dưới 3.0, 05/11/2025, <https://github.com/langchain-ai/langgraph/security/advisories/GHSA-wwqv-p2pp-99h5>); _documented_.

**Chưa kiểm.** Host một graph `create_agent` đã biên dịch dưới runner với checkpointer SQL (FOG-36 `agent-hosting`); allowlist msgpack cho kiểu state thật (FOG-37 `checkpoint-allowlist`); `FilesystemMiddleware` có để `GraphBubbleUp` đi qua không (FOG-35 `middleware-compose`); chặn ghi từ bên giữ lease cũ trong saver (FOG-56 `runtime-mechanics`); bản 1.2.16 mới nhất chưa đo lại.

**Dựa vào.** ADR 0112, 0113, 0109, 0117, 0121; spec `workflow-engine`, `workflow-nodes`, `agent-builder`, `foundations-hardening`.

## 5. Quy mô thực thi và chờ dài

**Câu hỏi.** Checkpointer Postgres của nền tảng có chịu nổi lượng run của Studio không, một run chờ
nhiều ngày tốn gì, và run đang đỗ có sống qua một lần phát hành mã không?

- Saver hiện tại ghi cả state thành một blob mỗi superstep (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:128-138`) và dọn checkpoint bị thay sau 7 ngày (`configs/policies/retention@1.7.0.yaml:142-144`); số byte tăng theo bình phương số bước nhân kích thước đầu ra, 8,5 MB mỗi run 20 bước với đầu ra 100 KB. _measured_ 22/10/2026, PostgreSQL 16.15 trên container 4 vCPU / 3 GiB.
- 1000 run cùng lúc, đầu ra 1 KB: saver hiện tại đạt 444 trên 500 bước/s đặt tải, khoảng cách bước p95 0,54 s, chờ pool tới 5,8 s; saver blob theo kênh với đường ghi gộp đạt 488 bước/s, p95 125 ms. Với đầu ra 100 KB, saver hiện tại không chở nổi 100 run (INSERT checkpoint trung bình 203 ms). _measured_ 22/10/2026.
- Một map 100 phần tử trong chuỗi 20 node ở 1000 run cùng lúc làm 506 run hỏng vì `PoolTimeout` sau 30 s, trong khi database không phải nút thắt. _measured_ 22/10/2026.
- Engine tham chiếu đều chặn độ dài một lần chạy: Temporal 51.200 sự kiện hoặc 50 MB rồi continue-as-new, Step Functions 1 năm và 25.000 sự kiện, Power Automate 30 ngày, n8n đưa một lần chờ dài hơn 65 s ra khỏi tiến trình.
  Nguồn: <https://docs.temporal.io/workflow-execution/limits>, <https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html>, <https://learn.microsoft.com/en-us/power-automate/limits-and-config> (17/07/2026), <https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/>; _documented_.
- graphile-worker tự công bố khoảng 183.000 job mỗi giây khi gộp lô trên Postgres (<https://worker.graphile.org/docs/performance>, không ghi ngày); _vendor claim_.

**Chưa kiểm.** Ghi chú nghiên cứu để trống các số quyết định: dung lượng mỗi worker và mỗi database, chi phí một thread đang đỗ, lane hẹn giờ ở quy mô lớn và chi phí dọn dữ liệu (benchmark retention hỏng, FOG-57 `retention-mechanics`); không đo trên host 2 vCPU / 8 GB (FOG-13 `pilot-capacity`); giới hạn đệ quy trigger của Salesforce chỉ là kiến thức nền vì trang trả 403.

**Dựa vào.** ADR 0113, 0112, 0109, 0122; spec `workflow-engine`, `workflow-triggers`, `telemetry-and-audit`.

## 6. Công cụ và kỹ năng trong LangChain v1 và deepagents

**Câu hỏi.** Công cụ và kỹ năng do tenant định nghĩa có thể là dữ liệu thay vì mã không, và LangChain
v1, deepagents cho sẵn những gì?

- `args_schema` dạng dict JSON Schema được chuyển cho model mà không kiểm đầu vào; cả `StructuredTool` lẫn `ToolStrategy` đều không kiểm. _measured_ 22/10/2026: đọc `langchain-core` 1.6.13 và chạy trên 1.6.3 mà repo khóa (`uv.lock:2001-2002`); <https://docs.langchain.com/oss/python/langchain/tools> (_documented_).
- `create_agent` có sẵn middleware giới hạn số lần gọi model và công cụ, thử lại, duyệt trước khi gọi công cụ, che dữ liệu cá nhân và chọn công cụ bằng LLM. Nguồn: <https://docs.langchain.com/oss/python/langchain/middleware/built-in>; _documented_.
- `create_deep_agent` của deepagents 0.7.30 vẫn cài builtin hệ tệp và `task` không gỡ được; `FilesystemMiddleware(tools=[...])` thu hẹp được. `SkillsMiddleware` nạp `SKILL.md` theo định dạng Agent Skills khi cần, từ 0.7.22 `include_tools` ẩn công cụ của một kỹ năng tới khi agent đọc nó, từ 0.7.23 có kỹ năng ghim.
  _measured_ (đọc wheel 0.7.15 và 0.7.30); <https://docs.langchain.com/oss/python/deepagents/skills>, <https://agentskills.io/specification>; _documented_.
- deepagents ra khoảng 15 bản từ 16/09 đến 22/10/2026, và 0.7.22 kéo theo `langchain>=1.4.3`, `langchain-core>=1.6.6`. _measured_ qua PyPI JSON, 22/10/2026.
- Số công cụ mỗi lượt làm giảm độ chính xác: OpenAI khuyên dưới 20 công cụ (<https://developers.openai.com/api/docs/guides/function-calling>, _documented_); Anthropic báo độ chính xác tăng mạnh khi nạp công cụ trễ (<https://anthropic.com/engineering/advanced-tool-use>, 24/11/2025, _vendor claim_); tìm công cụ phía nhà cung cấp chỉ có ở Anthropic và OpenAI.
- Chế độ strict khác nhau giữa nhà cung cấp (Anthropic: tối đa 20 công cụ strict mỗi request, không có ràng buộc số), nên schema phải theo một profile dùng chung và được kiểm ở phía server. Nguồn: <https://platform.claude.com/docs/en/build-with-claude/structured-outputs>; _documented_.

**Chưa kiểm.** Ảnh hưởng của mô tả công cụ tiếng Việt và số công cụ lên việc chọn công cụ (FOG-67 `tool-selection`); bản deepagents chính xác và những gì kéo theo (FOG-34 `deepagents-pin`); chi phí `jsonschema` mỗi lần gọi (FOG-58 `jsonschema-cost`); Composio, Arcade, Pipedream chưa được đánh giá vì hết ngân sách tìm kiếm.

**Dựa vào.** ADR 0116, 0117, 0124, 0125; spec `tools-and-skills`, `agent-builder`, `mcp-client`.

## 7. MCP 2026-07-28 và các advisory bảo mật

**Câu hỏi.** Studio nối tới máy chủ MCP do tenant đăng ký thế nào cho an toàn, theo bản đặc tả nào,
bằng thư viện nào?

- Bản 2026-07-28 bỏ trạng thái: không còn `initialize` và `Mcp-Session-Id`, mỗi request mang phiên bản và năng lực trong `_meta`, có `server/discover`, MRTR thay lời gọi từ server xuống client, Streamable HTTP cần header `Mcp-Method` và `Mcp-Name`; Roots, Sampling, Logging, DCR và HTTP+SSE bị đánh dấu bỏ, sớm nhất gỡ ở bản từ 28/07/2027.
  Nguồn: <https://modelcontextprotocol.io/specification/2026-07-28/changelog> (28/07/2026); _documented_.
- Client phải dò Protected Resource Metadata (RFC 9728), dùng PKCE S256, gửi `resource` (RFC 8707), kiểm `iss` (RFC 9207) và lưu quyền được cấp theo issuer; cấm chuyển token của dịch vụ này sang dịch vụ khác; annotation của công cụ chỉ là gợi ý không tin được. Nguồn: <https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization>; _documented_.
- SDK Python `mcp` sửa ở 2.2.0 (2.3.0 là bản hiện hành) ba lỗi phía client: gửi client secret, mã cấp quyền và PKCE verifier tới authorization server do server MCP chọn (GHSA-qx49-fqc8-xw99, 28/09/2026), SSRF qua `$ref` trong output schema (GHSA-rwrf-2pqf-9j8j, 28/09/2026), lộ header khi chuyển hướng sang origin khác (GHSA-5h93-6whr-6q8j, 02/10/2026).
  Nguồn: <https://github.com/modelcontextprotocol/python-sdk/security/advisories>; _documented_.
- FastMCP có RCE mức Critical ở client do output schema của server gây ra (GHSA-gpgx-58w2-xwwf, 16/10/2026) và hơn 10 advisory trong 16-20/10/2026 (<https://github.com/PrefectHQ/fastmcp/security/advisories>); `langchain.mcp` của LangChain 1.4 còn beta và dựng trên FastMCP; `langchain-mcp-adapters` lưu trữ từ 17/09/2026 (<https://github.com/langchain-ai/langchain-mcp-adapters>); _documented_.
- Blog đếm CVE của MCP không khớp nhau ("30+" trong 60 ngày đầu 2026 so với "14" tới tháng 7) và có mã CVE sai dạng, nên dùng mã GHSA (<https://bex.co/blog/2026/09/23/mcp-cve-wave-2026-deploy-mcp-supply-chain>); _vendor claim_.

**Chưa kiểm.** Client Python đã hỗ trợ extension Tasks chưa; giới hạn tên công cụ của nhà cung cấp (giả định 64 ký tự); `mcp` 2.x có nhận httpx2 client tiêm vào kèm proxy, timeout và chỉ theo chuyển hướng cùng origin không (FOG-69 `mcp-sdk`); nhận định phần lớn server còn ở giao thức 2025 chưa được đo.

**Dựa vào.** ADR 0116, 0115, 0125, 0120; spec `mcp-client`, `tools-and-skills`, `connections-and-vault`.

## 8. Trình kết nối, kho bí mật, OAuth và egress

**Câu hỏi.** Trình kết nối, bí mật của tenant, OAuth và lưu lượng ra ngoài nên dựng hay mua, và SSRF
bị chặn ở đâu?

- Giấy phép loại sản phẩm có sẵn: Nango là ELv2, "You may not provide the software to third parties as a hosted or managed service" (<https://raw.githubusercontent.com/NangoHQ/nango/master/LICENSE>), và bản tự host miễn phí bỏ syncs, webhook, RBAC, SSO, audit (<https://www.nango.dev/docs/guides/platform/self-hosting>); _documented_, đọc 22/10/2026.
- OpenBao (MPL-2.0, 2.7.x) giữ API Transit của Vault: `datakey`, `rewrap` mã hóa lại mà không lộ bản rõ, `rotate`, `associated_data` cho khóa AEAD; Vault là BUSL 1.1.
  Nguồn: <https://developer.hashicorp.com/vault/api-docs/secret/transit>, <https://openbao.org/community/release-notes/2-7-0/>, <https://raw.githubusercontent.com/hashicorp/vault/main/LICENSE>; _documented_, riêng tính tương đương của OpenBao là giả định.
- `net_guard` phân giải tên rồi kiểm (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:36-45`) nhưng để lọt 100.64.0.0/10 (`ipaddress` trả `is_private=False` cho 100.64.0.1) và trả URL về để HTTP client phân giải lần nữa (`net_guard.py:70`), nên có cửa sổ DNS rebinding; ghim IP đã kiểm ngay lúc kết nối chạy được với `httpx` 0.28.1. _measured_ 22/10/2026, kiểm lại 23/10/2026 trên Python 3.13.
- RFC 9700: "Public clients MUST use PKCE" (<https://www.rfc-editor.org/rfc/rfc9700.html>, _documented_); refresh token của Zalo chỉ dùng được một lần nên làm mới phải single-flight (<https://developers.zalo.me/community/detail/d546eda3d1e638b861f7>, diễn đàn nhà phát triển; _vendor claim_).
- Một ứng dụng OAuth của nền tảng chia giới hạn của nhà cung cấp cho mọi tenant: Google Sheets 300 lượt đọc và 300 lượt ghi mỗi phút mỗi project. Nguồn: <https://developers.google.com/workspace/sheets/api/limits>; _documented_.
- Webhook vào và ra theo Standard Webhooks (<https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md>, _documented_); endpoint nhận vào theo `docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md`.

**Chưa kiểm.** Zalo OA v4 và ZNS trên một OA thật: thời hạn token, công thức `X-ZEvent-Signature` (FOG-04 `zalo-zns`); thời gian duyệt ứng dụng của Meta và Google (FOG-05 `meta-google`); giấy phép, image và dải chặn mặc định của smokescreen (FOG-26 `smokescreen`); Transit và độ trễ của OpenBao (FOG-25 `openbao`); bộ nhớ của OpenBao, smokescreen, `mcp-gateway`, `model-proxy` trên host (FOG-23 `host-memory`); API của CRM Việt Nam và TikTok Lead Gen.

**Dựa vào.** ADR 0115, 0110, 0113, 0116; spec `connections-and-vault`, `workflow-triggers`, `marketing-pilot`.

## 9. Model của tenant qua LiteLLM và sự cố chuỗi cung ứng 2026

**Câu hỏi.** Cho tenant nối model và khóa của chính họ qua LiteLLM (D8) thế nào để nền tảng vẫn giữ
mọi quyết định và mọi bí mật?

- Chuỗi phát hành của LiteLLM bị chiếm hai lần năm 2026: `litellm` 1.82.7 và 1.82.8 trên PyPI ngày 24/03/2026 (mã đánh cắp thông tin xác thực), và ngày 21/10/2026 bản 1.107.0 trên PyPI cùng các tag Docker `latest`, `main-latest`, `main-stable` chứa mã độc, điều tra chưa xong.
  Nguồn: <https://docs.litellm.ai/blog/security-update-march-2026>, <https://docs.litellm.ai/blog/security-incident-oct-21-2026>; _documented_ (báo cáo sự cố của chính nhà cung cấp).
- Bản 1.106.2 mà nhà cung cấp khuyên ghim được tải lên lúc 10:44 UTC, 36 phút sau khi kẻ tấn công vượt bảo vệ nhánh lúc 10:08; bản thận trọng hơn là 1.106.1 (20/10/2026). _measured_ từ giờ tải lên trên <https://pypi.org/pypi/litellm/json>, 22/10/2026.
- Khoảng 17 advisory năm 2026, có SSRF qua chính tham số `api_base` phía client mà model proxy phải nhận, chặn bằng một denylist từng bị vượt (GHSA-3cv6-jpf6-8222, GHSA-hx8v-g79f-8w5f). Nguồn: <https://github.com/BerriAI/litellm/security/advisories>; _documented_.
- Không chạy LiteLLM trong tiến trình được: `litellm` 1.106.2 đòi `openai<3.0.0`, repo khóa `openai` 3.14.1 (`uv.lock:2717-2718`), uv báo "requirements are unsatisfiable". _measured_ 22/10/2026.
- Model do team quản lý (cách LiteLLM tự làm đa tenant), audit log và xoay khóa là bản Enterprise. Nguồn: <https://docs.litellm.ai/docs/enterprise>; _documented_.
- Hôm nay cả deployment dùng một bộ khóa model, `OPENAI_BASE_URL` và `OPENAI_API_KEY` trỏ tới FPT AI Gateway (`.env.example:171-177`). _measured_ (đọc mã).

**Chưa kiểm.** Hành vi LiteLLM theo từng nhà cung cấp: usage khi stream, token cache và reasoning, công cụ (FOG-19 `litellm-behaviour`); tiêm `api_key` và `api_base` qua transport httpx2 của `openai` 3.14.1 (FOG-21 `openai-transport`); gateway hiện có của bên yêu cầu là gì (FOG-18 `requester-gateway`); báo cáo cuối của sự cố 21/10/2026; nơi xử lý dữ liệu của endpoint do tenant khai báo không kiểm được.

**Dựa vào.** ADR 0118, 0123, 0121, 0115; spec `model-connections`, `compliance-pdpl`, `usage-and-limits`.

## 10. Mỗi lần chạy mã một container trên host không có KVM

**Câu hỏi.** Trên host 2 vCPU / 8 GB hiện tại, lớp cô lập nào mạnh hơn runc mà vẫn chạy được, để mỗi
lần chạy mã của tenant có container mới riêng (D7)?

- gVisor trên nền systrap "is a better choice when running inside a VM, or on a machine without virtualization support", còn KVM "runs poorly with nested virtualization"; Kata, Firecracker, E2B Embed và microsandbox đều cần `/dev/kvm`.
  Nguồn: <https://gvisor.dev/docs/architecture_guide/platforms/>, <https://github.com/kata-containers/kata-containers>; _documented_, đọc 22/10/2026.
- Tắt mạng ngay ở runtime: thêm `--network=none` vào `runtimeArgs` của runsc, để một lỗi của runner gắn nhầm mạng vẫn không có mạng. Nguồn: <https://gvisor.dev/docs/user_guide/networking/>; _documented_.
- Plugin AuthZ của Docker áp cho cả daemon và từng bị vượt (CVE-2024-41110, vá 23/07/2024, <https://www.docker.com/blog/docker-security-advisory-docker-engine-authz-plugin/>); proxy socket lọc theo endpoint không chặn được lệnh tạo container privileged hay mount host (<https://github.com/Tecnativa/docker-socket-proxy>); _documented_. Vì vậy chỉ `sandbox-runner` giữ socket.
- `BaseSandbox` của deepagents cần tệp còn lại giữa các lần gọi; mã nguồn 0.7.15 và 0.7.30 trái với tài liệu <https://docs.langchain.com/oss/python/deepagents/sandboxes>, nên công cụ mã của agent cần một container cho mỗi phiên agent. _measured_ (đọc mã), 22/10/2026.
- Số đo công khai của gVisor chạy trên máy cũ với nền ptrace, không phải systrap (<https://gvisor.dev/performance/startup.csv>), nên không dùng để định cỡ; _documented_.
- Dịch vụ `apps/docgen` hiện có chạy mọi lời gọi trong một container, `max_concurrency: int = 1` (`apps/docgen/src/dw_docgen/settings.py:41`); D7 không chấp nhận cách đó cho mã của tenant. _measured_ (đọc mã).

**Chưa kiểm.** Host có `/dev/kvm` không; engine rootless chạy cạnh daemon rootful hiện có; runsc với ủy quyền cgroup rootless; giới hạn pids, bộ nhớ, tmpfs và `docker stats` dưới runsc; bộ script tấn công chưa chạy trên runsc (FOG-24 `gvisor`).

**Dựa vào.** ADR 0119, 0121, 0112; spec `code-sandbox`, `workflow-nodes`, `usage-and-limits`.

## 11. Hạn mức, đo sử dụng và telemetry

**Câu hỏi.** Ai sở hữu hạn mức cứng, đo sử dụng ở đâu, và telemetry mang gì để tenant thấy lịch sử
chạy mà nội dung không rời nền tảng?

- Quy ước OTel GenAI vẫn ở mức Development, đã chuyển sang repo riêng chưa có bản phát hành, và thư viện hỗ trợ chính thức đặt tên metric khác đặc tả. Nguồn: <https://github.com/open-telemetry/semantic-conventions-genai>, <https://opentelemetry.io/docs/specs/semconv/gen-ai/>; _documented_, đọc 22/10/2026.
- Langfuse để thời hạn giữ dữ liệu, che dữ liệu và audit log ở bản Enterprise (<https://langfuse.com/self-hosting/license-key>); v4 cần ClickHouse từ 25.12 (<https://langfuse.com/self-hosting>) trong khi compose chạy `clickhouse-server:24.8-alpine` và tag trôi `langfuse:3` (`infra/compose/docker-compose.yml:510`, `:532`, `:563`). _documented_ và _measured_ (đọc mã).
- Không gateway nào làm chủ hạn mức được: LiteLLM giữ ngân sách trong Redis và để ngân sách theo tag ở bản trả phí (<https://docs.litellm.ai/docs/proxy/users>), TensorZero lưu trữ từ 12/06/2026 (<https://github.com/tensorzero/tensorzero>); _documented_.
- Model suy luận cần chừa phần đầu ra lớn, OpenAI khuyên ít nhất 25.000 token (<https://developers.openai.com/api/docs/guides/reasoning>, _documented_), nên lease giữ trước quá dè dặt sẽ bóp nghẹt chạy đồng thời.
- Repo hôm nay: bảng `platform.model_usage_ledger` đã bị gỡ theo yêu cầu của Đạt (`db/migrations/versions/0013_drop_model_usage_ledger.py:1-10`, revision `aefe7c1f5d9b` ở dòng 35, commit 21/09/2026), và không gói nào đặt trần chi tiêu theo ngày (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:17-36` chỉ có `runs_per_day`). _measured_ (đọc mã).

**Chưa kiểm.** Danh sách mục của OWASP Agentic Top 10 (chỉ xác nhận ngày 09/12/2025); giấy phép Hatchet và Agent Router; giá input đã cache; số token của văn bản tiếng Việt; chi phí hai lần ghi lease mỗi lời gọi khi chiến dịch dồn tải (FOG-70 `lease-cost`); đặt `max_tokens` trên đường Responses API (FOG-20 `max-tokens`); commit quy ước GenAI để ghim (FOG-71 `otel-genai`); trường usage của embedding và rerank (FOG-22 `embed-rerank-usage`).

**Dựa vào.** ADR 0121, 0122, 0120, 0118; spec `usage-and-limits`, `telemetry-and-audit`, `agent-lifecycle`.

## 12. Bảo mật và luật Việt Nam: Luật 91/2025/QH15, Nghị định 356/2025/NĐ-CP, Luật 134/2025/QH15

**Câu hỏi.** Bán Studio ở Việt Nam thì luật biến tính năng nào thành bắt buộc, và kiểm soát kiến trúc
nào chặn được kiểu tấn công riêng của agent?

- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 thông qua 26/06/2025, hiệu lực 01/01/2026; Nghị định 356/2025/NĐ-CP ký 31/12/2025, hiệu lực cùng ngày với luật, thay Nghị định 13/2023.
  Nguồn (bản dịch tiếng Anh không chính thức): <https://static3.luatvietnam.vn/uploaded/vietlawfile/2025/7/91_2025_qh15_incom_110725173542.pdf>, <https://www.qtsc.com.vn/uploads/files/2026/02/02/356_2025_ND-CP_689146.pdf>; _documented_.
- Điều 21 Nghị định 356 xếp việc cung cấp và vận hành hệ thống, phần mềm tự động xử lý dữ liệu cá nhân vào "dịch vụ xử lý dữ liệu cá nhân", và dịch vụ đó cần giấy chứng nhận của Bộ Công an (Điều 24-25). _documented_ (cùng bản dịch); Studio có thuộc diện này không là việc của luật sư.
- Thời hạn cụ thể: hồ sơ đánh giá tác động chuyển dữ liệu cá nhân ra nước ngoài nộp trong 60 ngày từ lần chuyển đầu, phạt tới 5% doanh thu năm trước, A05 có thể buộc dừng chuyển (Luật, Điều 20.5); trả lời yêu cầu của chủ thể dữ liệu trong 2 ngày làm việc; báo sự cố cho A05 trong 72 giờ. _documented_ (cùng bản dịch).
- Luật Trí tuệ nhân tạo 134/2025/QH15 hiệu lực 01/03/2026 thêm phân loại rủi ro, thông báo đang tương tác với AI, gắn nhãn và báo sự cố. Nguồn: <https://www.allenandgledhill.com/perspectives/publications/bulletins-vietnam/2026/vietnam-s-new-law-on-artificial-intelligence-risk-based-regulatory-framework-in-force-1-march-2026/> (30/03/2026); _documented_ thứ cấp, chưa đọc văn bản luật.
- Kênh rò giữa tenant nằm ngoài RLS: cache prompt của nhà cung cấp (<https://arxiv.org/abs/2502.07776>, đo bởi tác giả), prefix cache của vLLM chỉ tách khi mỗi request có `cache_salt` (<https://docs.vllm.ai/en/latest/design/prefix_caching.html>), Qdrant dùng chung thống kê IDF giữa tenant theo mặc định (<https://qdrant.tech/documentation/guides/multiple-partitions/>); _documented_.
- Bộ ba nguy hiểm (đầu vào không tin được, dữ liệu riêng, tác động ra ngoài) và các mẫu thiết kế chống prompt injection dẫn tới kiểm soát kiến trúc thay vì bộ lọc đầu vào. Nguồn: <https://arxiv.org/abs/2506.08837> (10/06/2025), <https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/> (16/06/2025), <https://ai.meta.com/blog/practical-ai-agent-security/> (31/10/2025); _documented_ (bài nghiên cứu; hai bài sau là quan điểm).

**Chưa kiểm.** Chưa có ý kiến luật sư Việt Nam; Studio có cần giấy chứng nhận và có thời gian chuyển tiếp không (FOG-73 `pdpl-certificate`); tình trạng các nghị định hướng dẫn Luật AI, nghị định xử phạt về dữ liệu cá nhân, Luật An ninh mạng mới và bản thay Nghị định 53 (FOG-74 `vn-law-status`); giới hạn chống tin rác của Nghị định 91/2020/NĐ-CP hoặc bản thay thế (FOG-75 `anti-spam`); độ chính xác của Presidio với dữ liệu cá nhân tiếng Việt (FOG-77 `presidio`).

**Dựa vào.** ADR 0123, 0124, 0125, 0106, 0122; spec `compliance-pdpl`, `field-security`, `model-connections`, `marketing-pilot`, `telemetry-and-audit`.

## 13. Định danh và danh bạ

**Câu hỏi.** Mỗi tenant đăng nhập bằng IdP riêng thế nào trên một deployment, người dùng và cơ cấu tổ
chức vào hệ thống bằng đường nào, và thu hồi quyền nhanh đến đâu?

- Lúc đăng nhập, định danh mới được nối với người dùng có sẵn theo `(issuer, subject)`, rồi theo `subject` bất kể issuer, rồi theo `lower(email)` trên bảng người dùng toàn cục, không lọc tenant (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:156-165`). Keycloak 26.7.2 đưa được đầu vào đó từ một IdP chưa gắn, 26.8.1 từ IdP của tenant gắn vào Organization: một đường chiếm tài khoản khi tenant tự mang IdP. _measured_ 22/10/2026.
- Token truy cập và phiên SSO sống 8 giờ (`infra/keycloak/dw-realm.json:12-14`; mặc định của Keycloak là 300 s), nên JWT còn hợp lệ 8 giờ sau khi IdP khóa một người. _measured_ 22/10/2026.
- Organizations của Keycloak cho một realm, mỗi tenant một organization; realm riêng mỗi tenant tốn tuyến tính (129 realm thành 1031 client, khoảng 0,2 MB mỗi realm trong database). _measured_ trên Keycloak 26.7.2, bản repo ghim (`infra/compose/docker-compose.yml:172`), trên host bị tranh tài nguyên nên chỉ dùng tỉ lệ; <https://www.keycloak.org/docs/latest/server_admin/index.html> (_documented_).
- Keycloak 26.8.0 (01/10/2026) đổi cách kiểm domain của Organization (<https://www.keycloak.org/2026/10/keycloak-2680-released>, đo lại trên 26.8.1); SCIM của Keycloak mới là tính năng thử nghiệm (<https://www.keycloak.org/2026/04/scim-as-experimental-feature>, 10/04/2026); _documented_.
- Microsoft dặn không dùng claim `email` để phân quyền vì claim đó đổi được (<https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation>, cập nhật 15/06/2026, _documented_); kiểu tấn công nOAuth vẫn bị khai thác năm 2025 (<https://www.semperis.com/blog/noauth-abuse-alert-full-account-takeover/>, 26/06/2025, _vendor claim_).

**Chưa kiểm.** MFA của Entra hay Google có tới được `amr` qua brokering không (FOG-78 `keycloak`); cột và mã trong file nhân sự của khách hàng thí điểm (FOG-15 `hr-exports`); API của MISA AMIS, Base, 1Office; danh tính agent có quyền riêng có thành yêu cầu không (FOG-80 `agent-identities`); độ trễ tuyệt đối, vì host đo bị tranh tài nguyên.

**Dựa vào.** ADR 0103, 0102, 0104; spec `org-and-principals`, `foundations-hardening`, `tenant-rbac`.

## 14. Môi trường, đưa lên và tiến hóa lược đồ

**Câu hỏi.** Tenant thử cấu hình mà không gây tác động thật thế nào, đưa thay đổi lên bằng gì, và đổi
lược đồ ra sao khi các version đã ghim vẫn đang chạy?

- Sản phẩm nào cũng đặt môi trường vào một vùng dữ liệu riêng (môi trường Power Platform, org sandbox của Salesforce, tài khoản sandbox của HubSpot, môi trường Workato); gói chỉ mang định nghĩa và điểm gắn, không mang bản ghi hay bí mật.
  Nguồn: <https://learn.microsoft.com/en-us/power-platform/alm/solution-concepts-alm> (29/01/2025), <https://docs.workato.com/features/environments.html>; _documented_, riêng Salesforce chỉ là kiến thức nền vì trang trả 403.
- Workato khớp khi nhập theo tên và thư mục, "Moving a recipe to a different folder in the source creates a second copy in the target", nên định danh qua các lần đưa lên phải là khóa bất biến. Nguồn: <https://docs.workato.com/en/recipe-development-lifecycle/import>; _documented_.
- Chế độ thử của nhà cung cấp không đều và có khi rò: sự kiện gửi kèm `test_event_code` của Meta Conversions API "are not dropped" mà còn dùng cho nhắm quảng cáo (<https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api>); hướng dẫn API ZNS không có tham số thử (<https://zalo.solutions/business-message/guidelines/gui-api>); _documented_. Vì vậy run mode phải được ép tại ToolExecutor và egress client.
- FK lookup toàn tenant cho một bản ghi trỏ tới bản ghi nó không thấy và thành phép thử sự tồn tại; FK của chỉ mục phụ thuộc với `ON DELETE RESTRICT` chặn xóa vĩnh viễn một trường đang được dùng nhưng không chặn xóa mềm. _measured_ 22/10/2026 trên PostgreSQL 16.15.
- Hash hiện tại dùng `json.dumps(..., sort_keys=True)` (`scripts/release_manifest.py:253-254`), khác RFC 8785 (JCS) ở `1.0`, khóa ngoài BMP và số nguyên lớn hơn 2^53. _measured_ với `rfc8785` 0.1.4 trên Python 3.12.15; <https://www.rfc-editor.org/rfc/rfc8785> (_documented_).

**Chưa kiểm.** Chi tiết Salesforce và ServiceNow (trang bị chặn); ZNS còn chế độ phát triển trong console không (FOG-04 `zalo-zns`); đối thủ có môi trường hay chế độ thử không (FOG-01 `chang`); chi phí dựng và ghi bản kê lượt chạy lúc nhận run (FOG-59 `run-manifest-cost`); vùng tạm theo run cho lần ghi bị chặn (FOG-60 `test-scratch`).

**Dựa vào.** ADR 0111, 0109, 0110, 0107, 0124; spec `tenant-config`, `domain-packs`, `workflow-engine`, `tools-and-skills`.

## 15. Chuẩn ứng dụng

**Câu hỏi.** API bản ghi sinh từ metadata theo chuẩn nào cho lọc, phân trang, đồng thời, chống lặp,
lỗi và tìm tiếng Việt, mà không dựng song song thứ nền tảng đã có?

- Thân lỗi hiện tại không theo RFC 9457; chuyển một lần cho cả nền tảng sang problem+json, giữ `code`, `message`, `details`, `request_id` làm thành viên mở rộng. Nguồn: <https://www.rfc-editor.org/rfc/rfc9457.html> (07/2023); _documented_.
- Bản nháp IETF cho header `Idempotency-Key` hết hạn ở bản -07 (15/10/2025), RateLimit headers còn ở bản nháp -11 (23/05/2026), nên hành vi của nền tảng phải tự ghi thành hợp đồng. Nguồn: <https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/>, <https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/>; _documented_.
- Google AIP cho sắp xếp (AIP-132), xóa mềm (AIP-164) và lọc; chính AIP-160 viết "Developers who need deterministic evaluation should refer to CEL". Nguồn: <https://google.aip.dev/132>, <https://google.aip.dev/160>, <https://google.aip.dev/164>; _documented_.
- Trên image `postgres:16-alpine` (16.15), tiếng Việt sắp theo code point nếu truy vấn không ghi `COLLATE "vi-x-icu"`; collation không tất định cho tiếng Việt không giúp tìm không dấu; hàm bọc `unaccent` IMMUTABLE với index GIN `pg_trgm` tìm không dấu nhanh khoảng 10 lần so với quét tuần tự. _measured_ 22/10/2026.
- Giấy phép và kiến trúc loại các sản phẩm sinh API: Directus v12 (MSCL cấm competing use, <https://directus.com/mscl>), Twenty (AGPL-3.0, <https://github.com/twentyhq/twenty/blob/main/LICENSE>), Hasura (thêm một bộ máy phân quyền thứ hai); _documented_.

**Chưa kiểm.** HTTP QUERY (RFC 10008) có đi qua Caddy, uvicorn, Starlette và preflight CORS không, nên tạm dùng `POST`; runtime CEL nào và giới hạn chi phí có thật sự được ép không (FOG-50 `cel-runtime`); `CREATE EXTENSION unaccent` dưới `dw_migrator` (FOG-55 `unaccent`); `application/merge-patch+json` trên FastAPI 0.141.1 (FOG-54 `merge-merge-api`); tần suất file nhập dùng VNI hay TCVN3 (FOG-14 `vn-encodings`); danh sách tỉnh sau sáp nhập 2025 (FOG-08 `province-list`).

**Dựa vào.** ADR 0108, 0107, 0114; spec `app-standards`, `custom-objects`, `foundations-hardening`.

## 16. Bối cảnh cạnh tranh

**Câu hỏi.** Cuối 2026 thị trường agent và quy trình đã hội tụ về những khái niệm nào, sản phẩm nào
nhúng được, và Studio nên khác ở đâu?

- Canvas cho logic agent đang rút lui: OpenAI đóng Agent Builder và Evals ngày 30/11/2026 (thông báo 03/06/2026, <https://developers.openai.com/api/docs/deprecations>); Flowise thành repo chỉ đọc từ 13/08/2026 (<https://github.com/FlowiseAI/Flowise/discussions/6727>); _documented_.
- Các hãng lớn hội tụ về một bộ khái niệm điều khiển: sổ đăng ký agent có vòng đời duyệt (AWS Agent Registry GA tháng 8/2026, <https://aws.amazon.com/about-aws/whats-new/2026/08/aws-agent-registry-generally-available>), danh tính agent có người chịu trách nhiệm (Entra Agent ID, <https://learn.microsoft.com/en-us/entra/agent-id/what-are-agent-identities>), chính sách ép tại cổng công cụ ngoài LLM (<https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html>); _documented_.
- Copilot Studio tính credit từ lúc dựng: soạn bằng ngôn ngữ tự nhiên, xem thử và sinh bộ đánh giá đều tốn credit (<https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/billing-credit-overview>, 06/10/2026); khi hết dung lượng, run mới bị chặn còn run đang chạy được chạy xong (<https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-messages-management>); _documented_.
- Không sản phẩm nào gộp đủ tách tenant và workspace, phân quyền tới bản ghi, đối tượng tùy biến, quy trình kéo thả, MCP, hạn mức và vòng đời: Salesforce, ServiceNow, Dataverse có mô hình dữ liệu và quyền; n8n, Dify, Zapier thì không và để phần quản trị ở bản Enterprise. Nhận định của nghiên cứu, tổng hợp từ các nguồn của mục này và mục 3.
- Đối thủ Việt Nam cạnh tranh bằng mẫu, model tiếng Việt và xử lý trong nước, ít công bố về quản trị; MISA nói có hơn 500 mẫu theo ngành (<https://amis.misa.vn/278249/misa-xay-dung-nha-may-ai-tren-nen-tang-nvidia/>, 06/2026); _vendor claim_.

**Chưa kiểm.** Salesforce Testing Center, giá Gemini Enterprise và Workato, trạng thái Connector Registry của OpenAI (trang trả 403 hoặc 404, hết ngân sách tìm kiếm); chang.fpt.net là sản phẩm nào của FPT và "Brain (Beta)" làm gì (FOG-01 `chang`, chỉ quan sát như người dùng thường theo DO-23).

**Dựa vào.** ADR 0100, 0117, 0120, 0121, 0101; spec `studio-skeleton`, `agent-builder`, `agent-lifecycle`, `usage-and-limits`, `marketing-pilot`.

## 17. Đánh giá công cụ phát triển theo spec

**Câu hỏi.** Có nên cài một bộ công cụ spec-driven development cho việc lập kế hoạch Studio, hay chỉ
lấy kỹ thuật của chúng vào quy trình `.claude/plans` sẵn có?

- Năm nhóm được đọc ở bản ghim: GitHub Spec Kit 1.2.2 (19/10/2026, MIT, <https://github.com/github/spec-kit>); skill của Matt Pocock 1.3.1 ở commit `49dd158` (09/10/2026, MIT, <https://github.com/mattpocock/skills>), cũng là plugin repo đã bật (`CLAUDE.md:375-377`); superpowers 7.0.1 (21/10/2026, MIT, <https://github.com/obra/superpowers>) cùng anthropics/skills; BMAD Method 6.12.4 (14/10/2026, MIT kèm điều khoản thương hiệu, <https://github.com/bmad-code-org/BMAD-METHOD>); OpenSpec 1.14.3, cc-sdd 3.1.0, Kiro (<https://kiro.dev/docs/specs/>), Agent OS và Taskmaster; _documented_.
- Kết luận cho cả năm nhóm: lấy kỹ thuật, không cài. Cài nguyên bản nhóm nào cũng thêm một tracker hay một nguồn sự thật thứ hai cạnh `.claude/plans` và `CLAUDE.md`; trình cài của cc-sdd còn ghi một `CLAUDE.md` ở gốc repo. _documented_ (đọc trình cài và README).
- Kỹ thuật được lấy: tối đa ba dấu cần làm rõ mỗi bản nháp, checklist chất lượng spec, lượt kiểm nhất quán chỉ đọc giữa các tài liệu, bảng roadmap, yêu cầu nguyên tử kiểu EARS viết bằng tiếng Việt, đọc thử bởi một agent không có ngữ cảnh, và từ vựng kiểm trung thực ("Đạt", "Không đạt", "Không áp dụng", "Chưa kiểm"); _documented_ (tài liệu của từng công cụ).
- Bằng chứng độc lập mỏng và lẫn lộn: thử nghiệm ngẫu nhiên của METR thấy lập trình viên giàu kinh nghiệm chậm hơn 19% khi dùng AI (<https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/>, 10/07/2025); tệp ngữ cảnh kiểu AGENTS.md có xu hướng giảm tỉ lệ thành công và tăng chi phí (<https://arxiv.org/abs/2602.11988>, 12/02/2026); Thoughtworks Radar cảnh báo "agent instruction bloat" (<https://www.thoughtworks.com/radar/techniques/agent-instruction-bloat>, 15/04/2026); _documented_.
- Taskmaster là MIT cộng Commons Clause: không phải giấy phép OSI và cấm bán; _documented_.

**Chưa kiểm.** Kỹ thuật đã lấy có làm spec của area này tốt hơn không, vì chưa chạy đánh giá có đối chứng; vài vị trí trên Radar chỉ đọc qua bản tóm tắt thứ cấp.

**Dựa vào.** Không ADR nào. Quy trình lập kế hoạch của area `studio` dựa vào nó: yêu cầu kiểu EARS, báo cáo nhất quán của blueprint, cổng sẵn sàng trước `ready-for-agent`, và giữ nguyên plugin đã ghim.

## Chỉ mục ngược: ADR dựa vào mục nào

| ADR  | Quyết định (rút gọn)                                                      | Mục       |
| ---- | ------------------------------------------------------------------------- | --------- |
| 0100 | Studio là mã nền tảng trong repo này, nội dung miền đi dưới dạng dữ liệu  | 16, 3, 1  |
| 0101 | Canvas `@xyflow/react` là ngoại lệ có allowlist, bố cục tính từ cây Bước  | 3, 16     |
| 0102 | Workspace là đơn vị lồng nhau sở hữu dữ liệu                              | 13, 2     |
| 0103 | Chỉ người và tài khoản dịch vụ hành động; agent là giới hạn dữ liệu       | 13, 2     |
| 0104 | Vai là dữ liệu của tenant, mỗi quyền có độ sâu                            | 2         |
| 0105 | PostgreSQL quyết định tầm với bản ghi                                     | 2, 1      |
| 0106 | Mỗi trường có loại dữ liệu cá nhân, một hàm quyết định quyền trường       | 2, 12     |
| 0107 | Đối tượng là metadata trên bảng cố định, một RecordService                | 1, 15, 14 |
| 0108 | Một vỏ lỗi problem+json, khóa chống lặp gắn với người gọi                 | 15        |
| 0109 | Một vỏ phiên bản, một hàm băm chuẩn, bản kê lượt chạy                     | 14, 4, 5  |
| 0110 | Cấu hình của tenant qua người đề xuất và người duyệt, nhu cầu là điểm gắn | 14, 8     |
| 0111 | Môi trường v1 là phiên bản cộng chế độ chạy                               | 14        |
| 0112 | Quy trình biên dịch sang StateGraph, một tác động mỗi bước                | 3, 4      |
| 0113 | Mọi lượt chạy qua một cửa, xếp hàng trong Postgres                        | 5, 4, 8   |
| 0114 | CEL là ngôn ngữ biểu thức duy nhất                                        | 3, 15     |
| 0115 | Kho bí mật theo tenant, một egress client                                 | 8, 9, 7   |
| 0116 | Công cụ là dữ liệu của tenant, một ToolExecutor                           | 6, 7      |
| 0117 | Agent cấu hình bằng form trong runner hiện có                             | 6, 16     |
| 0118 | Một ModelResolver, model của tenant qua model proxy LiteLLM               | 9         |
| 0119 | Mỗi lần chạy mã một container gVisor mới                                  | 10        |
| 0120 | Cổng phát hành, tắt khẩn cấp và đóng băng                                 | 11, 16, 7 |
| 0121 | Sổ sử dụng trở lại, hạn mức là khoản giữ trước trong Postgres             | 11, 9, 10 |
| 0122 | Lịch sử chạy đọc từ Postgres, telemetry chỉ mang định danh                | 11, 5     |
| 0123 | Dữ liệu ở lại Việt Nam, mọi lời gọi model qua cổng lộ trình dữ liệu       | 12, 9     |
| 0124 | Tin marketing phải qua sàn gửi tin                                        | 12, 14, 8 |
| 0125 | Đường có đủ bộ ba nguy hiểm phải qua người trước khi tác động             | 12, 7, 6  |

## Chỗ bản thiết kế không theo nghiên cứu

| Nghiên cứu khuyến nghị                                                                                                      | Bản thiết kế chọn                                                                                                                    | Căn cứ                                                     |
| --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Workspace làm môi trường: một workspace sandbox đưa lên một workspace production, định nghĩa object theo workspace (mục 14) | Run mode `live`, `test`, `simulate` trong một tenant; sandbox tenant ở v2; định nghĩa object toàn tenant                             | D1, S3; ADR 0111, 0107                                     |
| Chờ dài thì kết thúc segment và vào lại qua timer bền (mục 5)                                                               | Run chờ tại chỗ, thread đang đỗ được nén; segment là bước leo thang khi số đo đòi                                                    | ADR 0113, câu hỏi cho Đạt; số đo chi phí thread đỗ chưa có |
| Agent là một loại principal có người chịu trách nhiệm (mục 13)                                                              | Agent và quy trình là giới hạn dữ liệu, không bao giờ là principal                                                                   | ADR 0103                                                   |
| Đơn vị tổ chức riêng với closure table; SCIM của nền tảng ngay v1 (mục 13)                                                  | Cây workspace qua `parent_id` và hàm, không closure table; SCIM ở W3                                                                 | D1; ADR 0102; roadmap W3                                   |
| Code node ở v1.5; công cụ mã trên E2B tự host (mục 3, 6)                                                                    | Code node ở v1, mỗi lần chạy mã một container gVisor qua `sandbox-runner`                                                            | D7; ADR 0119                                               |
| Agent dựng trên deepagents (mục 16)                                                                                         | Agent của tenant ở trên `create_agent` của nền tảng, deepagents chỉ góp `SkillsMiddleware` và `FilesystemMiddleware` thu hẹp (mục 6) | S8; ADR 0116, 0117                                         |
| `langchain.mcp` đứng sau một port của nền tảng (mục 6)                                                                      | SDK `mcp` chính thức 2.x trong `mcp-gateway` tách biệt (mục 7)                                                                       | S9; ADR 0116                                               |
| Route bản ghi `/api/v1/objects/...` (mục 15)                                                                                | `/api/v1/studio/objects/...`                                                                                                         | ADR 0100, 0107                                             |
| smokescreen bắt buộc trước đích đầu tiên do tenant khai báo (mục 8)                                                         | W1 dựa vào ghim địa chỉ trong tiến trình, `net_guard` và allowlist; smokescreen sang W2                                              | roadmap, mục cắt giảm khỏi P1                              |

## Giới hạn chung của đợt nghiên cứu

- Ngân sách tìm kiếm web dùng chung hết giữa chừng ngày 22/10/2026; các chủ đề sau đó đọc trực tiếp URL nguồn chính đã biết, và trang của Salesforce trả 403. Mọi điều không mở được nằm ở phần chưa kiểm của chủ đề.
- Số đo chạy trên máy dev (Windows 11, Docker Desktop, container PostgreSQL 16.15 và 18.6); phép đo quy mô thực thi dùng container 4 vCPU / 3 GiB; phép đo định danh chạy trên host bị tranh tài nguyên. Không số nào đo trên host 2 vCPU / 8 GB (FOG-13, FOG-23) hay ở quy mô D12.
- Văn bản luật đọc qua bản dịch tiếng Anh không chính thức và bài của công ty luật; chưa có ý kiến luật sư Việt Nam.
- Thư viện đổi nhanh: deepagents khoảng 15 bản trong năm tuần, `mcp` 2.x mới ba tháng, sự cố LiteLLM ngày 21/10/2026 chưa đóng. Một nhận định về thư viện chỉ đúng cho một phiên bản, nên mỗi lần nâng bản phải đo lại (`.claude/rules/failure-modes.md`, mục 4).
- Ghi chú gốc không vào repo; file này giữ nguồn chính để người duyệt tự kiểm và không chép lại ghi chú.
