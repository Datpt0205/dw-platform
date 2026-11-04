# 01 — Spike: model proxy LiteLLM theo nhà cung cấp và tiêm khóa ở transport

Status: ready-for-agent
Area: studio
Yêu cầu: không (spike đo đạc trước khi W2 dựng model proxy thật theo ADR-0118 (Accepted), D8 và D13)

## Mục tiêu

Đo, trên máy này (Windows 11, Docker Desktop) và không dùng khóa thật nào, rằng một model proxy LiteLLM 1.106.1 không trạng thái dịch được lời gọi mà không lưu khóa, với khóa tiêm ở transport mỗi lượt gọi, và rằng cấu hình của ADR-0118 (Accepted) quyết định 8 giữ được từng điều nó hứa; kết quả chốt cấu hình và bản ghim trước khi W2 dựng dịch vụ `model-proxy` thật (FOG-19, FOG-21 ở `.claude/plans/studio/discovery/issues/17-litellm-model-proxy.md`). Ticket này đo hai đích: một upstream giả nói dialect OpenAI và Ollama chạy tại chỗ. Bảy nhà cung cấp cần khóa thật hay GPU được đo ở ticket 03 (Chờ Đạt 21). Ticket không tạo bảng, route, migration, tệp dưới `configs/` hay dịch vụ nào trong `infra/compose/`.

## Việc cần làm

0. Điều kiện trước. Không chạy LiteLLM trước 4/11/2026 02:00 giờ Việt Nam: bánh xe 1.106.1 lên PyPI lúc 2026-10-20 18:54 UTC (đo ngày 2/11/2026 trên `https://pypi.org/pypi/litellm/1.106.1/json`), nên 14 ngày của ADR-0118 (Accepted) quyết định 8 hết lúc 2026-11-03 18:54 UTC. Ngay trước bước 1, kiểm advisory: đọc `https://github.com/BerriAI/litellm/security/advisories` và `https://docs.litellm.ai/blog/security-incident-oct-21-2026`, rồi ghi vào Comments giờ đọc và mọi advisory chạm 1.106.1. Có advisory chạm 1.106.1 thì ticket dừng ở đây và ghi lại; không tự chọn bản khác, vì đổi bản ghim là sửa ADR-0118 (Accepted).
1. Mọi tệp của spike nằm dưới `infra/spikes/model-proxy/`, commit trên `main` như mọi ticket (không nhánh, không worktree):
    - `Dockerfile` dựng từ `python:3.12-slim@sha256:<digest>` ghim digest, chạy `pip install --no-deps --require-hashes -r requirements.txt`;
    - `requirements.txt` sinh bằng `uv pip compile --generate-hashes` cho `litellm[proxy]==1.106.1` (Python 3.12, linux x86_64), sinh trong thư mục spike và không bao giờ trong workspace uv. Lý do: LiteLLM đòi `openai<3`, còn repo khóa `openai` 3.14.1 (`uv.lock:2741-2742`); CLAUDE.md cấm import LiteLLM;
    - `config.yaml` đúng cấu hình của ADR-0118 (Accepted) quyết định 8: không `DATABASE_URL`, không biến nhà cung cấp, `cache: false`, `disable_cooldowns: true`, `num_retries: 0`, `turn_off_message_logging: true`, log chi tiêu và log lỗi tắt, `allow_client_side_credentials: false`, và `configurable_clientside_auth_params` chỉ gồm `api_base`, dưới regex neo hai đầu;
    - `compose.yml` với tên project `dw-spike-model-proxy`.

    Biến môi trường duy nhất có giá trị bí mật là `LITELLM_MASTER_KEY`: khóa truy cập của chính proxy, một giá trị thử cố định. `HTTPS_PROXY` và `HTTP_PROXY` trỏ `egress-standin`.

2. Bốn dịch vụ trong `compose.yml`, mọi ảnh tự dựng đi từ cùng ảnh nền ghim:
    - `model-proxy`, cổng `127.0.0.1:8010`;
    - `egress-standin`: một proxy HTTP và CONNECT ghi tên máy đích của mỗi kết nối. Nó đứng thay smokescreen, vì smokescreen thật còn chờ `.claude/plans/studio/discovery/issues/21-vault-and-egress.md` và connections-and-vault;
    - `fake-upstream`: nói dialect OpenAI qua HTTPS, với một CA thử gắn vào `model-proxy`. Nó ghi đầu và thân của mỗi request, trả 401 khi thiếu `Authorization`, trả 400, 429, 500 hay treo tùy tên model, stream SSE có chunk usage, và trả `tool_calls` khi request có `tools`. Cổng điều khiển `127.0.0.1:8011` để test đọc các request đã ghi;
    - `ollama`: ảnh `ollama/ollama` ghim digest, model `qwen2.5:0.5b`, không mở cổng ra host.

    `model-proxy` chỉ nằm trên mạng `ingress`, chung với `egress-standin`. `fake-upstream` và `ollama` chỉ nằm trên mạng `upstream`, chung với `egress-standin`. Vì vậy một lời gọi đi thẳng từ `model-proxy` không tới được upstream. Các cổng 8000, 3000, 3010, 3020 thuộc dự án khác trên máy này; spike chỉ dùng 8010 và 8011.

3. Transport ở `infra/spikes/model-proxy/tests/key_transport.py`: một `httpx2.AsyncBaseTransport` bọc transport mặc định.
    - Nó đọc `api_key` và `api_base` từ một `contextvars.ContextVar` đặt cho từng lượt gọi (vai của `StudioModelSelection` ở ADR-0118 (Accepted) quyết định 8, chưa có trong mã), rồi thêm hai giá trị đó vào thân JSON của request `/chat/completions`, kể cả request stream.
    - Không truyền qua `extra_body`, header của model hay `model_kwargs`.
    - Client là `ChatOpenAI` của `langchain-openai` 1.6.2 (`uv.lock:2061-2062`) trên `openai` 3.14.1 và `httpx2` 2.13.0 (`uv.lock:1736-1737`), trỏ `http://127.0.0.1:8010` với `LITELLM_MASTER_KEY`.
4. Test ở `infra/spikes/model-proxy/tests/test_litellm_lane.py`.
    - Một fixture phạm vi phiên dựng và chạy stack bằng `docker compose -p dw-spike-model-proxy -f infra/spikes/model-proxy/compose.yml up -d --build --wait`, rồi `down -v` khi xong.
    - Docker không trả lời thì test đỏ, không bỏ qua.
    - Khóa trong test là canary sinh mới mỗi lượt chạy (`sk-canary-<uuid4 hex>`), không bao giờ là khóa thật. Biến `OPENAI_API_KEY` và `OPENAI_BASE_URL` của `.env` không được đọc.
5. Đo trên hai route, `openai/<model>` trỏ `fake-upstream` và `ollama_chat/qwen2.5:0.5b`, các mục sau:
    - streaming có usage;
    - gọi công cụ;
    - `response_format`, cả `json_object` lẫn `json_schema`;
    - ánh xạ lỗi 400, 401, 429, 500 và quá hạn: mã HTTP và kiểu lỗi client nhận được, và thân lỗi của upstream có bị chép ra không.

    Ghi bảng số đo vào Comments, và một dòng Quyết định vào `spec.md` nêu cấu hình chốt cùng các mục FOG-19, FOG-21 đã đo.

6. Nếu cấu hình của ADR-0118 (Accepted) quyết định 8 không cho `api_key` trong thân request đi qua (chẳng hạn chỉ `allow_client_side_credentials: true` mới cho), dừng, ghi số đo và ghi đề xuất sửa quyết định 8 vào Comments. Không tự nới cấu hình: nới nó là mở lại đúng đường của GHSA-3cv6-jpf6-8222. Một tiêu chí dưới đây mà LiteLLM 1.106.1 với cấu hình đó không giữ được (chẳng hạn proxy không đi qua `egress-standin`, hay thiếu khóa mà trả mã khác 401) cũng được xử lý như vậy: dừng, ghi số đo và đề xuất. Không sửa tiêu chí cho xanh.

## Tiêu chí chấp nhận

- [ ] Bảng số đo của bước 5 có trong Comments, và mỗi ô (2 route nhân với streaming usage, công cụ, hai dạng `response_format`, năm lỗi) có giá trị đo hoặc "không hỗ trợ" kèm đầu ra; sai nếu một ô trống.
- [ ] Thiếu khóa. Một request không có `api_key` qua `model-proxy` làm client nhận mã 401, và `fake-upstream` không ghi request nào có `Authorization` mang giá trị. `docker inspect` của `model-proxy` không có biến nào khớp `(OPENAI|AZURE|ANTHROPIC|GEMINI|GOOGLE|VERTEX|AWS|BEDROCK|OLLAMA|HOSTED_VLLM|FPT)_.*` hay `.*_API_KEY`, ngoài `LITELLM_MASTER_KEY`. Sai nếu thêm `OPENAI_API_KEY=<canary>` vào `compose.yml` mà test không đỏ. Ghi thêm một số đo: với biến mồi đó, LiteLLM có tự điền khóa không.
- [ ] Tham số cấm. Gửi lần lượt từng tham số `base_url`, `user_config`, `aws_access_key_id`, `aws_secret_access_key`, `aws_region_name`, `vertex_credentials`, `azure_ad_token`, cùng mọi tên trong bước kiểm tham số cấm của LiteLLM 1.106.1 (đọc từ gói đã cài, ghi `path:line` vào Comments). Mỗi request hoặc bị proxy trả 4xx, hoặc tới đúng máy đã cấu hình mà request upstream đã ghi không mang tên nào trong số đó; báo cáo ghi từng tham số rơi vào trường hợp nào. Sai nếu một tham số tới được upstream hay đổi được đích, và sai nếu đặt `allow_client_side_credentials: true` mà test không đỏ.
- [ ] `api_base`. Một `api_base` không khớp regex bị từ chối 4xx ở cả bốn chỗ: thân gốc, trong `metadata`, trong `litellm_params` và trong `extra_body`; `egress-standin` không ghi kết nối nào tới máy đó. Một `api_base` khớp regex (`fake-upstream`) thì tới. Sai nếu thay regex bằng danh sách `api_base` không neo mà test không đỏ.
- [ ] Cooldown và retry. Gọi 5 lần liền với khóa A tới model `fake-500`, rồi gọi một lần với khóa B tới cùng alias: `fake-upstream` vẫn ghi request của B. Mỗi lời gọi trả 500 sinh đúng một request upstream. Sai nếu `disable_cooldowns: false` kèm `allowed_fails: 1`, hay `num_retries: 2`, mà test không đỏ.
- [ ] Transport. Chạy 20 cặp lời gọi đồng thời (`asyncio.gather`) với khóa A và khóa B, có stream (`stream_usage=True`) và không stream. Mỗi request upstream mang đúng khóa của lượt gọi đó và không lần nào mang khóa của lượt khác; mỗi lời gọi stream trả `usage_metadata`. Sai nếu đổi `ContextVar` thành một biến cấp module mà test không đỏ.
- [ ] Không lộ khóa. Canary không xuất hiện ở bốn dạng (nguyên văn, JSON-escaped, URL-encoded, base64) trong `docker logs` của `model-proxy` và `egress-standin` suốt lượt chạy, trong `serialized` và `invocation_params` của `on_chat_model_start`, và trong `on_llm_end` của một callback LangChain ghi lại. Sai nếu truyền khóa qua `extra_body` mà test callback không đỏ, và sai nếu bộ quét không tìm thấy một canary trồng sẵn ở đủ bốn dạng.
- [ ] Ra ngoài qua proxy. Mỗi request mà `fake-upstream` và `ollama` ghi có một dòng tương ứng trong log của `egress-standin`; bỏ `HTTPS_PROXY` và `HTTP_PROXY` khỏi `model-proxy` thì lời gọi thất bại. Sai nếu có request tới upstream mà `egress-standin` không ghi.
- [ ] Xong: `uv run python -m pytest infra/spikes/model-proxy/tests -k litellm_lane` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/chat_model.py:33`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:76`; `uv.lock:2741-2742`; `uv.lock:1736-1737`; `uv.lock:2061-2062`; spec: không.

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
