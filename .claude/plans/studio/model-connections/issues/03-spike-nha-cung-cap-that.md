# 03 — Spike: model proxy với từng nhà cung cấp thật

Status: ready-for-human (Chờ Đạt 21: một khóa thử cho mỗi nhà cung cấp và một máy GPU cho vLLM)
Blocked by: 01
Area: studio
Yêu cầu: không (spike đo đạc; phần cần khóa thật, tách khỏi ticket 01 ngày 2/11/2026)

## Mục tiêu

Trên stack và transport của ticket 01, đo bảy nhà cung cấp mà một máy không có khóa không đo được: OpenAI, Azure OpenAI, Anthropic, Gemini AI Studio, Bedrock khóa tĩnh, vLLM và FPT AI Factory (FOG-19). Đo thêm usage mà LiteLLM báo so với usage mà nhà cung cấp tính, và prompt cache giữa hai công ty (`.claude/plans/studio/discovery/issues/17-litellm-model-proxy.md`, mục Phép đo quyết định). Ticket thuộc Chờ Đạt 21: cần một khóa thử cho mỗi nhà cung cấp, thêm một khóa OpenAI thứ hai thuộc project hay org khác khóa thứ nhất cho phép đo cache ở bước 4, và một máy chạy vLLM có GPU. Không khóa nào được vào môi trường của `model-proxy` hay vào repo.

## Việc cần làm

0. Điều kiện trước. Ticket 01 đã `resolved` mà không dừng ở bước 0 hay bước 6 của nó; nếu ticket 01 dừng và đề xuất sửa
   ADR-0118 (Accepted) quyết định 8, ticket này chờ bản sửa đó và qua gate lại. Ngay trước bước 1, đọc lại advisory như
   bước 0 của ticket 01 (cùng hai địa chỉ) và ghi giờ đọc vào Comments; có advisory chạm 1.106.1 thì dừng ở đây.
1. Khóa chỉ nằm trong môi trường của tiến trình test trên host, dưới tên `DW_SPIKE_<PROVIDER>_*`:
    - Azure: khóa, endpoint và deployment;
    - Bedrock: cặp khóa tĩnh và vùng;
    - vLLM và FPT AI Factory: khóa và `api_base`.

    Khóa chỉ tới `model-proxy` qua transport của ticket 01, từng lượt gọi. `egress-standin` thêm một danh sách máy được
    phép, đúng các máy của bảy nhà cung cấp này, đọc từ biến của host; kết nối tới máy khác bị từ chối và ghi lại.

    Nhà cung cấp mà Đạt ghi ở Comments là không cấp khóa (hay không có máy GPU cho vLLM) vào
    `infra/spikes/model-proxy/tests/skipped_providers.yaml` với ngày của dòng Comments đó; test của nó báo "bỏ theo Đạt
    <ngày>" và bảng số đo ghi đúng chữ đó.

2. Với mỗi nhà cung cấp, đo:
    - streaming có usage;
    - gọi công cụ;
    - `response_format`, cả `json_object` lẫn `json_schema`;
    - ánh xạ lỗi: 401 khi khóa sai, 400, và 429 nếu tạo ra được;
    - usage LiteLLM báo so với usage nhà cung cấp tính: ghi độ lệch cho từng nhà cung cấp, chưa đặt ngưỡng;
    - token cache và token reasoning, nếu nhà cung cấp có.
3. Một nhà cung cấp cần tham số phía client ngoài `api_key` và `api_base` mà ticket 01 chặn hay cấu hình của quyết định
   8 không cho (Bedrock khóa tĩnh cần `aws_*`; Azure cần `api_version` và tên deployment): đo xem có cách nào cho giá trị
   đi qua mà không mở lại các tham số đó (chẳng hạn đặt trong chuỗi model hay trong `api_base` khớp regex). Không có cách
   thì dừng đo nhà cung cấp đó, ghi ô "cần sửa quyết định 8" và đề xuất sửa ADR-0118 (Accepted) quyết định 8 vào
   Comments; không tự nới cấu hình, không thêm tên vào `configurable_clientside_auth_params`.
4. Prompt cache trên OpenAI: dùng khóa A, rồi khóa B của một project hay org khác (`DW_SPIKE_OPENAI_KEY_B`), với cùng một prompt dài ít nhất 1024 token. Ghi `cached_tokens` của lời gọi B và ghi `cache_salt` có được chuyển tiếp không.
5. Giới hạn chi phí và dữ liệu:
    - mỗi lời gọi có `max_tokens` không quá 64, và cả lượt không quá 300 lời gọi;
    - chỉ dùng nội dung tổng hợp, không dữ liệu cá nhân hay dữ liệu của công ty nào, vì xử lý ở nước ngoài là chuyển dữ liệu (ADR-0123 (Accepted)).
6. Ghi bảng số đo vào Comments, và một dòng Quyết định vào `spec.md`.

## Tiêu chí chấp nhận

- [ ] Bảng số đo có trong Comments, và mỗi ô của bảy nhà cung cấp có giá trị đo, "không hỗ trợ" kèm đầu ra, "cần sửa quyết định 8" (bước 3) hay "bỏ theo Đạt <ngày>" (bước 1); sai nếu thiếu một nhà cung cấp hay một ô trống.
- [ ] `config.yaml` của spike chỉ khác bản của ticket 01 ở danh sách regex `api_base`, thêm mỗi máy của bảy nhà cung cấp một regex neo hai đầu (`git diff` của tệp chỉ có các dòng đó); sai nếu một tham số khác `api_base` được thêm vào `configurable_clientside_auth_params`, một regex không neo, hay `allow_client_side_credentials` thành `true`.
- [ ] Không có khóa thật nào trong `docker logs` của `model-proxy` và `egress-standin`, hay trong callback, ở cả bốn dạng của ticket 01; sai nếu bộ quét không tìm thấy một canary trồng sẵn.
- [ ] Thiếu một biến `DW_SPIKE_*` của một nhà cung cấp không có trong `skipped_providers.yaml` thì test của nhà cung cấp đó đỏ và nêu tên nó, không bỏ qua; sai nếu xóa biến mà test xanh.
- [ ] Xong: `uv run python -m pytest infra/spikes/model-proxy/tests -k litellm_providers` xanh.

## Nguồn

- `uv.lock:2741-2742`; `uv.lock:1736-1737`; spec: không.

## Comments

- 2026-11-02 (agent, theo ủy quyền 31/10/2026): tách từ ticket 01 theo gate `checking-plan-readiness` (HIGH 2), vì sáu nhà cung cấp cần khóa thật và vLLM cần GPU (Chờ Đạt 21). Ticket chưa qua gate. Nếu sai thì: gộp lại vào ticket 01.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): sửa theo gate `checking-plan-readiness`, builder check (không migration,
  không route; đo trên `c8dab56`). 0 CRITICAL; 3 HIGH, đã sửa như khuyến nghị:
    - (1) không có lối ra khi Đạt không cấp khóa cho một nhà cung cấp hay không có máy GPU: thêm
      `skipped_providers.yaml` với ngày dòng Comments của Đạt (bước 1, tiêu chí 1 và 3);
    - (2) Azure cần `api_version` và deployment ngoài `api_base`, như Bedrock cần `aws_*`: luật "dừng và đề xuất sửa
      quyết định 8" áp cho mọi nhà cung cấp như thế, kèm tiêu chí `config.yaml` không đổi (bước 3);
    - (3) ticket chạy sau ticket 01 có thể nhiều tuần: điều kiện trước là ticket 01 không dừng ở bước 6, và đọc lại
      advisory (bước 0).

    MEDIUM: danh sách máy được phép của `egress-standin` ghi rõ ở bước 1, vì ticket 01 chỉ ghi lại máy đích.
    Lượt xác nhận: 2 HIGH, đã sửa: regex `api_base` cho máy thật là thay đổi duy nhất được phép của `config.yaml`
    (tiêu chí 2); phép đo cache cần khóa B ở project hay org khác (bước 4, Chờ Đạt 21).
    Nếu sai thì: bỏ `skipped_providers.yaml` và giữ ticket mở tới khi đủ bảy khóa; áp luật dừng chỉ cho Bedrock.

- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-human (Chờ Đạt 21), không `ready-for-agent` vì cần khóa thật.
- 2026-11-05 (agent): ticket 01 dừng ở bước 0, vì GHSA-w4c7-34wj-hqm8 (Critical) chạm 1.106.1; số đo nằm ở Comments
  của ticket 01. Ticket này chờ đúng như bước 0 của nó đã ghi. Khi ADR-0118 (Accepted) quyết định 8 đổi bản ghim, bước 0
  ở đây đổi 1.106.1 theo bản mới trong cùng lần sửa.
