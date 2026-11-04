# 01 — Spike: model proxy LiteLLM theo nhà cung cấp và tiêm khóa ở transport

Status: ready-for-agent (chỉ chạy từ 2026-11-10 19:45 UTC, 11/11/2026 02:45 giờ Việt Nam, sau một lần kiểm advisory mới ở bước 0)
Area: studio
Yêu cầu: không (spike đo đạc trước khi W2 dựng model proxy thật theo ADR-0118 (Accepted), D8 và D13)

## Mục tiêu

Đo, trên máy này (Windows 11, Docker Desktop) và không dùng khóa thật nào, rằng một model proxy LiteLLM 1.106.5 không trạng thái dịch được lời gọi mà không lưu khóa, với khóa tiêm ở transport mỗi lượt gọi, và rằng cấu hình của ADR-0118 (Accepted) quyết định 8 giữ được từng điều nó hứa; kết quả chốt cấu hình và bản ghim trước khi W2 dựng dịch vụ `model-proxy` thật (FOG-19, FOG-21 ở `.claude/plans/studio/discovery/issues/17-litellm-model-proxy.md`). Ticket này đo hai đích: một upstream giả nói dialect OpenAI và Ollama chạy tại chỗ. Bảy nhà cung cấp cần khóa thật hay GPU được đo ở ticket 03 (Chờ Đạt 21). Ticket không tạo bảng, route, migration, tệp dưới `configs/` hay dịch vụ nào trong `infra/compose/`.

## Việc cần làm

0. Điều kiện trước. Không chạy LiteLLM, và không tạo tệp nào của bước 1 trở đi, trước 2026-11-10 19:45 UTC (11/11/2026 02:45 giờ Việt Nam): bánh xe 1.106.5 lên PyPI lúc 2026-10-27 19:44 UTC (đo ngày 4/11/2026 18:02 UTC trên `https://pypi.org/pypi/litellm/1.106.5/json`), nên 14 ngày của ADR-0118 (Accepted) quyết định 8 (sửa 5/11/2026) hết lúc 2026-11-10 19:44 UTC. Ngay trước bước 1, đọc lại giờ tải lên ở địa chỉ đó (khác giờ trên thì tính lại giờ mở và ghi vào Comments), rồi kiểm advisory: đọc `https://github.com/BerriAI/litellm/security/advisories` (mọi trang), `https://docs.litellm.ai/blog/security-incident-oct-21-2026` và `https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain`, rồi ghi vào Comments giờ đọc và mọi advisory chạm 1.106.5. "Chạm" nghĩa là khoảng bị ảnh hưởng của advisory chứa 1.106.5, dù advisory nói điều kiện tiên quyết là gì. Có advisory chạm 1.106.5, hay nhà cung cấp công bố sự cố mới sau báo cáo ngày 23/10/2026, thì ticket dừng ở đây và ghi lại; không tự chọn bản khác, vì đổi bản ghim là sửa ADR-0118 (Accepted).
1. Mọi tệp của spike nằm dưới `infra/spikes/model-proxy/`, commit trên `main` như mọi ticket (không nhánh, không worktree):
    - `Dockerfile` dựng từ `python:3.12-slim@sha256:<digest>` ghim digest, chạy `pip install --no-deps --require-hashes -r requirements.txt`;
    - `requirements.txt` sinh bằng `uv pip compile --generate-hashes --exclude-newer <giờ chạy trừ 14 ngày, UTC>` cho `litellm[proxy]==1.106.5` (Python 3.12, linux x86_64), để mọi gói phụ thuộc cũng đã qua 14 ngày, và ghi giờ đó vào đầu tệp (không giải được thì dừng và đề xuất như bước 6, không nới cho riêng gói phụ thuộc); sinh trong thư mục spike và không bao giờ trong workspace uv. Lý do: LiteLLM đòi `openai<3`, còn repo khóa `openai` 3.14.1 (`uv.lock:2833-2834`); CLAUDE.md cấm import LiteLLM;
    - `config.yaml` đúng cấu hình của ADR-0118 (Accepted) quyết định 8: không `DATABASE_URL`, không biến nhà cung cấp, `cache: false`, `disable_cooldowns: true`, `num_retries: 0`, `turn_off_message_logging: true`, log chi tiêu và log lỗi tắt, `allow_client_side_credentials: false`, và `configurable_clientside_auth_params` chỉ gồm `api_base`, dưới đúng một regex neo hai đầu, `^https://fake-upstream(:443)?/v1/?$`, đặt trong `litellm_params` của từng mục `fake-*`, không đặt toàn cục và không đặt cho `qwen`. Không thêm khóa nào khác, kể cả khóa timeout; `num_retries: 0` nằm đúng chỗ gói đã cài đọc nó (ghi `path:line`). Ngoại lệ duy nhất: nếu một lời gọi tới `fake-500` sinh hơn một request upstream vì client `openai` bên trong LiteLLM tự retry, thêm `max_retries: 0` vào `litellm_params` của mỗi mục, ghi số đo trước và sau vào Comments, vì đó là siết, cùng ý "retry tắt" của quyết định 8. `model_list` khai mỗi alias một mục riêng, không wildcard: `fake-ok`, `fake-400`, `fake-429`, `fake-500`, `fake-hang` (`openai/<tên>`, không `api_base` trong cấu hình, nên đích đến từ `api_base` của lượt gọi) và `qwen` (`ollama_chat/qwen2.5:0.5b`, `api_base: http://ollama:11434` trong cấu hình: một tên máy, không phải bí mật, và route này không nhận `api_base` từ client);
    - `compose.yml` với tên project `dw-spike-model-proxy`.

    Biến môi trường duy nhất có giá trị bí mật là `LITELLM_MASTER_KEY`: khóa truy cập của chính proxy, một giá trị thử cố định. `HTTPS_PROXY` và `HTTP_PROXY` trỏ `egress-standin`.

2. Bốn dịch vụ trong `compose.yml`, mọi ảnh tự dựng đi từ cùng ảnh nền ghim:
    - `model-proxy`, cổng `127.0.0.1:8010`;
    - `egress-standin`: một proxy HTTP và CONNECT ghi tên máy đích của mỗi kết nối, chỉ chuyển tới `fake-upstream` và `ollama`; kết nối tới máy khác (chẳng hạn LiteLLM tự tải bảng giá model) bị từ chối và ghi lại. Nó đứng thay smokescreen, vì smokescreen thật còn chờ `.claude/plans/studio/discovery/issues/21-vault-and-egress.md` và connections-and-vault;
    - `fake-upstream`: nói dialect OpenAI qua HTTPS, với một CA thử gắn vào `model-proxy`. Nó ghi đầu và thân của mỗi request, trả 401 khi thiếu `Authorization`, trả 400, 429, 500 hay treo tùy tên model, stream SSE có chunk usage, và trả `tool_calls` khi request có `tools`. Cổng điều khiển `127.0.0.1:8011` để test đọc các request đã ghi;
    - `ollama`: ảnh `ollama/ollama` ghim digest, model `qwen2.5:0.5b`, không mở cổng ra host. Model nằm trong volume ngoài `dw-spike-model-proxy-ollama` (`external: true`, nên `down -v` không xóa); fixture của bước 4 kéo model vào volume đó bằng chính ảnh ghim, chạy riêng ngoài stack, khi volume chưa có nó.

    `model-proxy` chỉ nằm trên mạng `ingress`, chung với `egress-standin`. `fake-upstream` và `ollama` chỉ nằm trên mạng `upstream` (`internal: true`), chung với `egress-standin`. Vì vậy một lời gọi đi thẳng từ `model-proxy` không tới được upstream. `ingress` không thể `internal: true` vì phải mở cổng 8010, nên `model-proxy` còn đường ra Internet thẳng; spike không đo đường đó, và mạng `dw-llm` nội bộ của `model-proxy` thật ở W2 (ADR-0118 (Accepted) quyết định 8) đóng nó. Các cổng 8000, 3000, 3010, 3020 thuộc dự án khác trên máy này; spike chỉ dùng 8010 và 8011.

3. Transport ở `infra/spikes/model-proxy/tests/key_transport.py`: một `httpx2.AsyncBaseTransport` bọc transport mặc định.
    - Nó đọc `api_key` và `api_base` từ một `contextvars.ContextVar` đặt cho từng lượt gọi (vai của `StudioModelSelection` ở ADR-0118 (Accepted) quyết định 8, chưa có trong mã), rồi thêm hai giá trị đó vào thân JSON của request `/chat/completions`, kể cả request stream. Chỉ `api_key` là bắt buộc; `api_base` trống thì không thêm (route `qwen`). `ContextVar` không có `api_key` thì transport ném lỗi và không gửi gì: thiếu ngữ cảnh là từ chối, không gửi tiếp không khóa (`failure-modes.md` #7).
    - Không truyền qua `extra_body`, header của model hay `model_kwargs`.
    - Client là `ChatOpenAI` của `langchain-openai` 1.6.2 (`uv.lock:2153-2154`) trên `openai` 3.14.1 và `httpx2` 2.13.0 (`uv.lock:1828-1829`), trỏ `http://127.0.0.1:8010` với `LITELLM_MASTER_KEY`, `max_retries=0` và `timeout=10` giây. "Một lời gọi" trong các tiêu chí là một request từ client tới `model-proxy`.
    - Các request cố ý sai hình dạng (thiếu `api_key`, tham số cấm, `api_base` lồng trong `metadata`, `litellm_params` hay một khóa `extra_body` thật trong thân JSON) gửi thẳng bằng `httpx2` tới `model-proxy`, không qua `ChatOpenAI` hay transport, vì `ChatOpenAI` gộp `extra_body` lên cấp gốc của thân.
4. Test ở `infra/spikes/model-proxy/tests/test_litellm_lane.py`.
    - Một fixture phạm vi phiên dựng và chạy stack bằng `docker compose -p dw-spike-model-proxy -f infra/spikes/model-proxy/compose.yml up -d --build --wait`, rồi `down -v` khi xong.
    - Docker không trả lời thì test đỏ, không bỏ qua. Test không mang marker nào và `infra/` nằm ngoài `testpaths` của `pyproject.toml`, nên `make test-unit`, `make test-integration` và CI không thu nó; chỉ lệnh `Xong:` chạy nó.
    - Hai biến thể của stack chạy trong cùng lệnh `Xong:`, mỗi biến thể là một tệp compose override dựng dưới tên project riêng: `compose.bait.yml` (thêm `OPENAI_API_KEY=<canary>` cho số đo biến mồi của tiêu chí thiếu khóa) và `compose.no-proxy.yml` (bỏ `HTTPS_PROXY` và `HTTP_PROXY`, cho tiêu chí ra ngoài qua proxy).
    - Mỗi vế "Sai nếu" của tiêu chí là một mục trong `.claude/plans/studio/model-connections/mutations/01.yaml`, sửa `compose.yml`, `config.yaml` hay `key_transport.py` tại chỗ; viết trong ticket, chạy bằng `scripts/mutate.py` lúc đóng hàng đợi (`.claude/rules/wave-close.md`).
    - Khóa trong test là canary sinh mới mỗi lượt chạy (`sk-canary-<uuid4 hex>`), không bao giờ là khóa thật. Biến `OPENAI_API_KEY` và `OPENAI_BASE_URL` của `.env` không được đọc.
5. Đo trên hai route, `openai/<model>` trỏ `fake-upstream` và `ollama_chat/qwen2.5:0.5b`, các mục sau:
    - streaming có usage;
    - gọi công cụ;
    - `response_format`, cả `json_object` lẫn `json_schema`;
    - ánh xạ lỗi 400, 401, 429, 500 và quá hạn: mã HTTP và kiểu lỗi client nhận được, và thân lỗi của upstream có bị chép ra không. Quá hạn: `fake-hang` treo 60 giây, client cắt ở 10 giây; ghi kiểu lỗi client nhận, và giờ `model-proxy` đóng kết nối tới upstream sau đó, theo log của `egress-standin` (thời hạn mặc định của LiteLLM, đọc từ gói đã cài, ghi `path:line`). Thân lỗi bị chép thì ghi lại, không dừng: không chép thân lỗi là việc của adapter nền tảng ở W2 (ADR-0118 (Accepted) quyết định 6).

    Ghi bảng số đo vào Comments, và một dòng Quyết định vào `spec.md` nêu cấu hình chốt cùng các mục FOG-19, FOG-21 đã đo.

6. Nếu cấu hình của ADR-0118 (Accepted) quyết định 8 không cho `api_key` trong thân request đi qua (chẳng hạn chỉ `allow_client_side_credentials: true` mới cho), dừng, ghi số đo và ghi đề xuất sửa quyết định 8 vào Comments. Không tự nới cấu hình: nới nó là mở lại đúng đường của GHSA-3cv6-jpf6-8222. Một tiêu chí dưới đây mà LiteLLM 1.106.5 với cấu hình đó không giữ được (chẳng hạn proxy không đi qua `egress-standin`, hay thiếu khóa mà trả mã khác 401) cũng được xử lý như vậy: dừng, ghi số đo và đề xuất. Không sửa tiêu chí cho xanh.

## Tiêu chí chấp nhận

- [ ] Bảng số đo của bước 5 có trong Comments, và mỗi ô (2 route nhân với streaming usage, công cụ, hai dạng `response_format`, năm lỗi) có giá trị đo, "không hỗ trợ" kèm đầu ra, hoặc, chỉ ở các ô lỗi của route `qwen` mà Ollama không sinh ra được (401, 429, 500, quá hạn), "không tạo được" kèm lý do một dòng; sai nếu một ô trống.
- [ ] Thiếu khóa. Một request tới alias `fake-ok`, có `api_base` khớp regex mà không có `api_key`, qua `model-proxy` làm client nhận mã 401, và `fake-upstream` không ghi request nào có `Authorization` mang giá trị. 401 do LiteLLM tự trả (không gửi đi) hay 401 của `fake-upstream` chuyển qua đều đạt; ghi trường hợp nào. `docker inspect` của `model-proxy` không có biến nào khớp `(OPENAI|AZURE|ANTHROPIC|GEMINI|GOOGLE|VERTEX|AWS|BEDROCK|OLLAMA|HOSTED_VLLM|FPT)_.*` hay `.*_API_KEY`, ngoài `LITELLM_MASTER_KEY`, và không có biến `LITELLM_LICENSE` (ADR-0118 (Accepted) quyết định 8, sửa 5/11/2026: không license Enterprise, để mã mà GHSA-w4c7-34wj-hqm8 cần không bao giờ được nạp). Sai nếu thêm `OPENAI_API_KEY=<canary>`, hay `LITELLM_LICENSE=<canary>`, vào `compose.yml` mà test không đỏ. Ghi thêm hai số đo: với biến mồi đó, LiteLLM có tự điền khóa không; và route `qwen` không có `api_key` trả gì (Ollama không kiểm khóa, nên số đo này không làm tiêu chí đỏ).
- [ ] Tham số cấm. Gửi lần lượt từng tham số `base_url`, `user_config`, `aws_access_key_id`, `aws_secret_access_key`, `aws_region_name`, `vertex_credentials`, `azure_ad_token`, cùng mọi tên trong bước kiểm tham số cấm của LiteLLM 1.106.5 (đọc từ gói đã cài, ghi `path:line` vào Comments). Mỗi request hoặc bị proxy trả 4xx, hoặc tới đúng máy đã cấu hình mà request upstream đã ghi không mang tên nào trong số đó; báo cáo ghi từng tham số rơi vào trường hợp nào. Sai nếu một tham số tới được upstream hay đổi được đích, và sai nếu đặt `allow_client_side_credentials: true` mà test không đỏ.
- [ ] `api_base`. Một `api_base` không khớp regex bị từ chối 4xx ở cả bốn chỗ: thân gốc, trong `metadata`, trong `litellm_params` và trong `extra_body`; `egress-standin` không ghi kết nối nào tới máy đó. Một `api_base` khớp regex (`https://fake-upstream/...`) thì tới. Một `api_base` gửi tới alias `qwen` bị từ chối 4xx hay bị bỏ qua mà request vẫn tới `ollama`; ghi trường hợp nào. Sai nếu thay regex bằng danh sách `api_base` không neo mà test không đỏ.
- [ ] Cooldown và retry. Gọi 5 lần liền với khóa A tới model `fake-500`, rồi gọi một lần với khóa B tới cùng alias: `fake-upstream` vẫn ghi request của B. Mỗi lời gọi trả 500 sinh đúng một request upstream. Sai nếu `disable_cooldowns: false` kèm `allowed_fails: 1`, hay `num_retries: 2`, mà test không đỏ. LiteLLM có thể không làm nguội một nhóm chỉ có một deployment; nếu phép đột biến cooldown không đỏ vì thế, alias `fake-500` khai hai mục cùng tên trỏ cùng upstream và ghi lý do vào Comments, không bỏ phép đột biến.
- [ ] Transport. Chạy 20 cặp lời gọi đồng thời (`asyncio.gather`) với khóa A và khóa B, có stream (`stream_usage=True`) và không stream. Mỗi request upstream mang đúng khóa của lượt gọi đó và không lần nào mang khóa của lượt khác; mỗi lời gọi stream trả `usage_metadata`. Một lời gọi qua `ChatOpenAI` khi `ContextVar` không có `api_key` ném lỗi ở transport, và `fake-upstream` không ghi request nào của lời gọi đó. Sai nếu đổi `ContextVar` thành một biến cấp module mà test không đỏ, và sai nếu transport gửi tiếp không khóa mà test không đỏ.
- [ ] Không lộ khóa. Canary không xuất hiện ở bốn dạng (nguyên văn, JSON-escaped, URL-encoded, base64) trong `docker logs` của `model-proxy` và `egress-standin` suốt lượt chạy, trong `serialized` và `invocation_params` của `on_chat_model_start`, và trong `on_llm_end` của một callback LangChain ghi lại. Sai nếu truyền khóa qua `extra_body` mà test callback không đỏ, và sai nếu bộ quét không tìm thấy một canary trồng sẵn ở đủ bốn dạng.
- [ ] Ra ngoài qua proxy. `fake-upstream` ghi địa chỉ nguồn của mỗi request, và mọi địa chỉ đó là địa chỉ của `egress-standin` trên mạng `upstream`; mỗi máy đích mà `fake-upstream` hay `ollama` nhận request có ít nhất một dòng CONNECT hay request proxy trong log của `egress-standin` (một đường hầm giữ kết nối có thể chở nhiều request). Bỏ `HTTPS_PROXY` và `HTTP_PROXY` khỏi `model-proxy` thì lời gọi thất bại. Sai nếu gắn `model-proxy` vào mạng `upstream` và bỏ hai biến proxy đó mà test địa chỉ nguồn không đỏ. Mọi máy đích khác mà `egress-standin` ghi trong lượt chạy (chẳng hạn LiteLLM tự tải bảng giá model) được liệt kê trong Comments.
- [ ] Xong: `uv run python -m pytest infra/spikes/model-proxy/tests -k litellm_lane` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/chat_model.py:33`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:76`; `uv.lock:2833-2834`; `uv.lock:1828-1829`; `uv.lock:2153-2154`; spec: không.

## Comments

- 2026-10-23 (agent): đổi "lane LiteLLM" thành model proxy theo glossary (phát hiện kiểm nhất quán ngày 23/10/2026); tên tệp giữ nguyên. Đạt chấp nhận ADR-0118 (Accepted) ngày 23/10/2026: LiteLLM ghim 1.106.1 theo luật 14 ngày và kiểm advisory (bước 1).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): sửa theo gate `checking-plan-readiness`, chỉ builder check vì ticket không có migration hay route (đo trên `6593e0e`). Có 10 HIGH, tất cả đã sửa như khuyến nghị:
    - (1) `Xong:` trỏ `packages/python/dw_studio`, gói chưa tồn tại (studio-skeleton/02 mới dựng nó, nên hai ticket đụng nhau mà không có đường phụ thuộc), và dùng `uv run pytest`. Nay spike nằm ở `infra/spikes/model-proxy/`, lệnh là `uv run python -m pytest`.
    - (2) Bước 2 cần khóa thật của sáu nhà cung cấp và một máy GPU cho vLLM (Chờ Đạt 21). Tách ra ticket 03; ticket này đo upstream giả và Ollama tại chỗ.
    - (3) smokescreen chưa có trong repo (discovery/21). Thay bằng `egress-standin`, kèm phép đo proxy ra ngoài có được tôn trọng không.
    - (4) Tham số cấm chưa được liệt kê. Nay có danh sách và nguồn của LiteLLM.
    - (5) Thêm hai phép đo mà ADR-0118 (Accepted) Consequences và discovery/17 nêu: regex `api_base` ở mọi chỗ lồng nhau, và cooldown hay retry thật sự tắt (một công ty không được làm nguội alias của công ty khác).
    - (6) Tiêu chí về log trộn log của proxy với trường callback của LangChain. Nay tách thành hai nơi, quét bốn dạng mã hóa, có canary trồng sẵn.
    - (7) Luật 14 ngày: 1.106.1 lên PyPI ngày 20/10/2026, nên chỉ chạy được từ 4/11/2026; kiểm advisory được định nghĩa ở bước 0.
    - (8) Bỏ "kết luận một model proxy hay hai": D13 và ADR-0118 (Accepted) quyết định 8 đã chốt, và câu đó dựa vào FOG-18 của bên đặt yêu cầu. Bỏ "nhánh thử", vì mọi việc làm trên `main`. Thay các dẫn chiếu B9-8.6, M5, O6/F7 (brief không có trong repo) bằng FOG-19, FOG-21.
    - (9) Tiêu chí thiếu khóa không thể đỏ khi môi trường không có biến nào. Nay kiểm danh sách biến môi trường, đo với một biến mồi.
    - (10) Thêm bước 6: cấu hình của quyết định 8 không cho `api_key` đi qua thì dừng và đề xuất, không tự nới.

    Nếu sai thì: đặt lại `Xong:` dưới `packages/python/dw_studio/tests/spike` sau studio-skeleton/02, gộp ticket 03 trở lại đây, và chạy spike trên một bản LiteLLM khác chỉ sau khi sửa ADR-0118 (Accepted).

- 2026-11-02 (agent): MEDIUM để lại, chưa sửa:
    - ADR-0118 (Accepted) dẫn `uv.lock:2717-2718` và `uv.lock:1712-1713`; hôm nay là `uv.lock:2741-2742` (`openai` 3.14.1) và `uv.lock:1736-1737` (`httpx2` 2.13.0).
    - Hiện trạng của spec dẫn `.env.example:171`; khối gateway nay ở `.env.example:178-193`.
    - `--require-hashes` ghim mọi gói phụ thuộc, nhưng luật 14 ngày chưa nói có áp cho gói phụ thuộc của LiteLLM không.
    - `compose.yml` của spike nằm ngoài `infra/compose/*.yml`, nên `verify_compose_policy.py` của studio-skeleton/04 và CI không thấy nó; luật đó áp cho `model-proxy` thật ở W2.
    - `ResidencyGate` chưa có trong mã (chỉ một chú thích ở `apps/api/tests/integration/test_wf_ai_wiring.py:4`). Spike chỉ gửi nội dung tổng hợp tới upstream giả và Ollama tại chỗ; cổng đi cùng adapter của W2 (ADR-0123 (Accepted) quyết định 4).
    - Discovery/17 câu 2 hỏi cả khóa còn trong bộ nhớ tiến trình; ticket này không đo mục đó.
    - Trên checkout này `.env` có `OPENAI_BASE_URL` khác rỗng, trái với ghi chú của Chờ Đạt 21; spike không đọc biến đó.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): dừng ở bước 0, đúng luật của bước đó. Chưa cài, chưa dựng, chưa chạy
  LiteLLM; không có tệp nào dưới `infra/spikes/model-proxy/`. Đọc trên `ef4d4b0`.
    - Giờ đọc: 2026-11-04 18:00-18:10 UTC (5/11/2026 01:00-01:10 giờ Việt Nam), sau giờ mở 4/11/2026 02:00.
      Đã đọc `https://github.com/BerriAI/litellm/security/advisories` (hai trang, 18 advisory) và trang chi tiết của
      GHSA-w4c7-34wj-hqm8, GHSA-7hp6-4w63-5g45, GHSA-3cv6-jpf6-8222, GHSA-g5ff-637f-6q2m và GHSA-hhww-mrg2-969h.
      Đã đọc `https://docs.litellm.ai/blog/security-incident-oct-21-2026` (cập nhật cuối 30/10/2026) và bản ghi mà
      trang đó trỏ tới, `https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain` (23/10/2026).
      Đối chiếu thêm với OSV (`POST https://api.osv.dev/v1/query`, gói PyPI `litellm`): có 85 bản ghi, không bản ghi
      nào có khoảng chứa 1.106.1, và OSV chưa có GHSA-w4c7-34wj-hqm8.
    - Advisory chạm 1.106.1: một advisory, **GHSA-w4c7-34wj-hqm8** (Critical, 27/10/2026), "Unauthenticated file read
      leaks master key on Enterprise proxy".
        - Affected: `< 1.103.10`, `< 1.104.8`, `< 1.105.6`, `< 1.106.5`. Patched: 1.103.10, 1.104.8, 1.105.6, 1.106.5.
        - Một request không xác thực tới bất kỳ route LLM nào làm proxy đọc một tệp cục bộ (chẳng hạn
          `/proc/self/environ`, lộ `LITELLM_MASTER_KEY` và khóa nhà cung cấp) rồi gửi nội dung ra một URL do kẻ tấn công
          chọn.
        - Theo advisory, mã đó chỉ nạp khi có license Enterprise ("Open source deployments without a license are not
          affected"). Giảm nhẹ: chặn ở biên, và giới hạn lối ra về endpoint của nhà cung cấp.
        - Mười bảy advisory còn lại có bản sửa dưới 1.106.1. Khoảng cao nhất là của GHSA-7hp6-4w63-5g45, tới 1.104.0rc2.
    - Báo cáo sự cố: bản ghi "attack chain" ngày 23/10/2026 tự nhận là "canonical source of truth" và "completed our
      investigation", và chỉ nêu 1.107.0 là bản độc. Thay đổi quy trình hẹn "next week". Trang trạng thái chưa gọi nó là
      báo cáo cuối.
    - PyPI (`https://pypi.org/pypi/litellm/<bản>/json`, đọc 18:02 UTC), giờ tải lên UTC:

        | Bản     | Tải lên          | Hết 14 ngày      |
        | ------- | ---------------- | ---------------- |
        | 1.106.2 | 2026-10-21 10:44 | 2026-11-04 10:44 |
        | 1.106.3 | 2026-10-24 09:14 | 2026-11-07 09:15 |
        | 1.106.4 | 2026-10-25 09:32 | 2026-11-08 09:33 |
        | 1.106.5 | 2026-10-27 19:44 | 2026-11-10 19:45 |
        | 1.106.6 | 2026-10-28 22:48 | 2026-11-11 22:49 |
        | 1.106.7 | 2026-11-04 04:16 | 2026-11-18 04:17 |
        | 1.108.0 | 2026-11-04 03:31 | 2026-11-18 03:32 |

        1.107.0 không còn trên PyPI. Bản sửa thấp nhất của nhánh 1.106 là 1.106.5, nên mọi bản đã qua luật 14 ngày hôm
        nay (tới 1.106.4) đều nằm trong khoảng của advisory.

    - Đề xuất sửa ADR-0118 (Accepted) quyết định 8. Theo bước 0, ticket không tự chọn bản khác:

        | #   | Câu hỏi                                                                                        | Khuyến nghị                                                                                                                                                                                                                                                                                                                                              |
        | --- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
        | 1   | Bản nào thay 1.106.1?                                                                          | 1.106.5, bản sửa thấp nhất của nhánh, chạy sớm nhất 2026-11-10 19:45 UTC (11/11/2026 02:45 giờ Việt Nam), kèm một lần kiểm advisory lúc đó. Không giữ 1.106.1 với lý do proxy không có license Enterprise: làm vậy là nhận một Critical dựa vào lời nhà cung cấp về điều kiện tiên quyết (failure-modes #4), trong khi mã Enterprise nằm trong cùng gói. |
        | 2   | Bản ghi "attack chain" ngày 23/10/2026 có là báo cáo cuối mà quyết định 8 và FOG-19 chờ không? | Có. Nó tự nhận đã hoàn tất điều tra, là nguồn chuẩn, và chỉ nêu 1.107.0 là bản độc. 1.106.5 lên sau khi khóa ký cosign được xoay ngày 23/10. Nếu sai thì: chờ nhà cung cấp gọi rõ một báo cáo là báo cáo cuối, và ticket chờ theo.                                                                                                                       |
        | 3   | Ticket này đổi gì?                                                                             | Bước 0 và Mục tiêu đổi 1.106.1 thành 1.106.5, với giờ mở 11/11/2026 02:45. `requirements.txt` ghim `litellm[proxy]==1.106.5`. Tiêu chí thiếu khóa thêm `LITELLM_LICENSE` vào danh sách biến cấm trong `docker inspect` của `model-proxy`, để phòng thủ thêm cho chính GHSA này. Sau đó gate lại bằng builder check.                                      |
        | 4   | Chỗ nào khác ghi 1.106.1?                                                                      | Cùng lần sửa đó: ADR-0118 (Accepted) dòng 110, 180, 183 và 203; Quyết định của spec; bước 0 của ticket 03.                                                                                                                                                                                                                                               |

    - Nếu sai thì: nếu Đạt đọc "chạm" là "khoảng chứa bản đó và điều kiện tiên quyết có thể xảy ra với cấu hình của
      quyết định 8", ticket chạy lại trên 1.106.1 mà không đổi gì khác, và bước 0 ghi rõ cách đọc đó.
    - Chưa đo: bước 1 tới 6 và mọi tiêu chí chấp nhận. FOG-19 và FOG-21 vẫn mở (discovery/17, câu 1-3).
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): nhận cả bốn ý của bảng đề xuất ở trên, theo `## Ủy quyền` của studio.md.
    - (1) ADR-0118 (Accepted) quyết định 8 ghim 1.106.5, chạy sớm nhất 2026-11-10 19:45 UTC (11/11/2026 02:45 giờ Việt
      Nam), sau một lần kiểm advisory lúc đó; ghi ở Amendments (2026-11-05) của ADR. Nếu sai thì: nếu Đạt đọc "chạm" là
      "khoảng chứa bản đó và điều kiện tiên quyết có thể xảy ra với cấu hình của quyết định 8", ticket chạy lại trên
      1.106.1 mà không đổi gì khác, và bước 0 ghi rõ cách đọc đó.
    - (2) Bản ghi "attack chain" ngày 23/10/2026 là báo cáo sự cố cuối mà quyết định 8 và FOG-19 chờ. Nếu sai thì: chờ
      nhà cung cấp gọi rõ một báo cáo là báo cáo cuối, và ticket chờ theo.
    - (3) Mục tiêu, bước 0, bước 1 (`requirements.txt`), bước 6 và tiêu chí tham số cấm đổi 1.106.1 thành 1.106.5; tiêu
      chí thiếu khóa cấm thêm `LITELLM_LICENSE`, như quyết định 8 nay cấm. Bước 0 nói rõ "chạm" là khoảng chứa bản đó,
      đọc thêm bản ghi "attack chain", và đọc lại giờ tải lên của 1.106.5 trước khi chạy.
    - (4) ADR-0118 (Accepted) dòng 110, 180, 183 và 203, Quyết định của spec và bước 0 của ticket 03 đổi cùng lần này.
    - Thêm: dẫn chiếu `uv.lock` dời theo tệp hôm nay (`openai` 3.14.1 ở `uv.lock:2833-2834`, `httpx2` 2.13.0 ở
      `uv.lock:1828-1829`, `langchain-openai` 1.6.2 ở `uv.lock:2153-2154`).
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate lại bằng `checking-plan-readiness` sau bản sửa ở trên, builder check
  vì ticket không có migration hay route, cùng một lượt xác nhận; `check_plans.py` 24 Đạt, 0 cảnh báo. 0 CRITICAL; 14
  HIGH, tất cả đã sửa như khuyến nghị:
    - builder check, 7 HIGH: ai cắt lời gọi treo (client ở 10 giây, không khóa timeout mới); route Ollama lấy
      `api_base` từ cấu hình, regex chỉ cho `fake-upstream`, tiêu chí 401 chỉ cho `fake-ok`; tiêu chí ra ngoài qua proxy
      đo địa chỉ nguồn thay cho khớp từng dòng log, vì một đường hầm chở nhiều request; `ChatOpenAI` `max_retries=0`;
      bốn chỗ lồng `api_base` gửi bằng `httpx2` thô; `model_list` khai từng alias, không wildcard, kèm lối ra khi LiteLLM
      không làm nguội nhóm một deployment; transport từ chối khi thiếu `api_key`;
    - lượt xác nhận, 7 HIGH: regex đúng một máy; `egress-standin` chỉ chuyển tới hai upstream, và đường ra thẳng của
      mạng `ingress` được ghi là không đo; hai biến thể stack (`compose.bait.yml`, `compose.no-proxy.yml`) chạy trong
      lệnh `Xong:`, còn mỗi vế "Sai nếu" là một mục của `mutations/01.yaml` chạy lúc đóng hàng đợi; retry của client
      `openai` bên trong LiteLLM; ô lỗi Ollama không sinh được ghi "không tạo được"; `configurable_clientside_auth_params`
      theo từng mục `fake-*`; một tiêu chí cho transport từ chối khi thiếu khóa.
    - Gọi tạm (agent, tạm): `requirements.txt` sinh với `--exclude-newer` lùi 14 ngày, nên luật 14 ngày áp cả cho gói
      phụ thuộc, và không giải được thì dừng; `max_retries: 0` trong `litellm_params` được thêm chỉ khi đo thấy client
      `openai` bên trong LiteLLM tự retry, vì đó là siết cùng ý "retry tắt" của quyết định 8. Nếu sai thì: luật 14 ngày
      chỉ áp cho `litellm`, và thấy retry của client thì dừng và đề xuất như bước 6.

    MEDIUM, sửa luôn trong cùng lượt: model Ollama ở volume ngoài; test spike ngoài `testpaths`, không marker; không
    tạo tệp nào trước khi bước 0 qua; 401 của LiteLLM hay của upstream đều đạt, ghi trường hợp nào. MEDIUM để lại:
    `model-proxy` của spike còn đường ra Internet thẳng qua mạng `ingress` (Docker không mở cổng trên mạng `internal`),
    chỉ `dw-llm` nội bộ ở W2 đóng nó; thân lỗi upstream bị chép thì chỉ ghi lại, vì quyết định 6 là việc của adapter
    W2; ticket 03 còn dẫn `uv.lock:2741-2742` và `uv.lock:1736-1737` (nay `uv.lock:2833-2834` và `uv.lock:1828-1829`),
    sửa khi ticket 03 gate lại; tiêu chí 2 của ticket 03 ("`config.yaml` chỉ khác ở danh sách regex `api_base`") cần
    tính tới việc regex nay nằm theo từng mục của `model_list`, nên mỗi nhà cung cấp thêm một mục, cũng sửa khi gate lại.

- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent. Chỉ chạy từ 2026-11-10 19:45 UTC (11/11/2026 02:45
  giờ Việt Nam), sau một lần kiểm advisory mới ở bước 0.
