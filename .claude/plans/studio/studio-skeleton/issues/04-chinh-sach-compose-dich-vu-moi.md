# 04 — Chính sách compose cho dịch vụ mới

Status: needs-triage
Blocked by: 01, .claude/plans/studio/runtime-hardening/issues/02-bien-mang-va-kho-du-lieu.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, SKEL16, SKEL17

## Mục tiêu

Lát này cho người thêm smokescreen, OpenBao, `mcp-gateway`, `model-proxy` hay `sandbox-runner` một bộ luật được test thay cho một lần duyệt tay: dịch vụ mới không vào `dw-internal`, có mạng riêng, ảnh ghim digest, không publish cổng ngoài dev, được cứng hóa, có profile riêng và có mặt trong CI (R8). OpenBao của connections-and-vault là dịch vụ đầu tiên chịu luật; dịch vụ có trước luật được nêu tên trong danh sách ngoại lệ kèm lý do. Ticket này chờ runtime-hardening/02, nơi mọi ảnh bên thứ ba được ghim digest và bước trivy quét chúng, nên danh sách ngoại lệ không có phần ghim ảnh (OPS-b).

## Việc cần làm

1. `scripts/verify_compose_policy.py`: với mỗi tổ hợp tệp gốc kèm profile `infra`, `full`, `observability` và profile riêng của từng dịch vụ mới, tệp gốc kèm `docker-compose.uat.yml`, kèm `docker-compose.prod.yml`, kèm `docker-compose.host.yml` và kèm `docker-compose.dev.yml`, chạy `docker compose --env-file .env -f ... config --format json` và xét luật trên mô hình đã giải; đọc thêm văn bản `.github/workflows/ci.yml` cho R8.7 và dòng `FROM` trong Dockerfile của ảnh tự dựng cho R8.3. Đo trước rằng `config --format json` của bản compose trong CI trả đủ `networks`, `ports`, `profiles` và `deploy` (failure-modes #4).
2. Dữ liệu luật nằm ở một chỗ, trong script: `EXCEPTIONS["dw-internal"]` là các dịch vụ hôm nay nối `dw-internal` (`postgres`, `qdrant`, `valkey`, `s3`, `s3-setup`, `keycloak`, `migrate`, `api`, `docgen-gateway`, `worker`, `web`, `clickhouse`, `langfuse-worker`, `langfuse-web`, `postgres-exporter`, `alertmanager-config`, `alertmanager`, `prometheus`), mỗi tên kèm lý do; `EXCEPTIONS` là bảng luật sang `{dịch vụ: lý do}`, mỗi luật gồm đúng các dịch vụ hôm nay vi phạm nó, lý do "có trước luật, 23/10/2026"; `BASE_SHA` là commit nền của ticket này; kiểm chạy chính các luật trên các tệp compose của `git show <BASE_SHA>:<tệp>` (chép vào thư mục tạm) để có tập vi phạm nền, và một dòng `EXCEPTIONS` không thuộc tập đó phải nêu `adr` trỏ tới một ADR Accepted trong `docs/adr/` mà văn bản nhắc tên dịch vụ và tên luật (R8.10); không có ngoại lệ ghim ảnh, vì runtime-hardening/02 đã ghim digest mọi ảnh bên thứ ba trước ticket này; `CALLERS` là bảng dịch vụ sang các dịch vụ được chung mạng với nó, rỗng ở ticket này.
3. Mỗi luật áp cho mọi dịch vụ không có tên trong `EXCEPTIONS` của luật đó: mọi mạng của nó có `internal: true` và chỉ chung với dịch vụ trong `CALLERS` của nó; ảnh kéo về có `@sha256:`, ảnh tự dựng có mọi dòng `FROM` mang `@sha256:`; `ports` chỉ có ở `docker-compose.dev.yml`; có `healthcheck`, `read_only: true`, `cap_drop: [ALL]`, `security_opt` gồm `no-new-privileges:true`, `init: true`, `user` không phải root, `mem_limit`, `pids_limit`; không `network_mode`, không `privileged: true`, không `cap_add`, không `pid: host` hay `ipc: host`, không volume gắn `/var/run/docker.sock`; có `deploy.resources` khi gộp overlay uat và prod; `profiles` có profile mang tên dịch vụ; `.github/workflows/ci.yml` có lệnh `docker compose ... --profile` với profile đó và `config -q`, có bước smoke nêu healthcheck của dịch vụ, và ảnh của dịch vụ có trong vòng trivy. Mỗi điều kiện ở trên là một luật có tên riêng (`dw-internal`, `internal-network`, `digest`, `ports`, `healthcheck`, `read_only`, `cap_drop`, `no-new-privileges`, `init`, `user`, `mem_limit`, `pids_limit`, `deploy-resources`, `network_mode`, `privileged`, `cap_add`, `pid-host`, `ipc-host`, `docker-socket`, `profile`, `ci`), và `EXCEPTIONS` khóa theo tên đó. Mỗi vi phạm in một dòng nêu dịch vụ và luật; mỗi dòng `EXCEPTIONS` cho dịch vụ không còn tồn tại hay không còn vi phạm luật đó in một dòng và làm kiểm đỏ (R8.9).
4. `scripts/test_compose_policy.sh` theo mẫu `scripts/test_check_plans.sh`: ca đầu chạy kiểm trên các tệp compose của checkout và phải xanh; mỗi ca sau chép các tệp compose và `.github/workflows/ci.yml` vào thư mục tạm, thêm một dịch vụ thử vi phạm đúng một luật (nối `dw-internal`; ảnh không digest; `ports` trong tệp gốc; thiếu `read_only`; `network_mode: "service:qdrant"`; `network_mode: host`; `privileged: true`; `cap_add`; `pid: host`; `ipc: host`; volume `/var/run/docker.sock`; không profile riêng; không có trong vòng trivy) và đòi kiểm thoát 1 với dòng nêu luật đó; ca nào không trồng được lỗi thì cả test đỏ (failure-modes #3).
5. CI, job `contracts`: sau bước "Compose profiles validate", chạy `uv run python scripts/verify_compose_policy.py` rồi `bash scripts/test_compose_policy.sh`.

## Tiêu chí chấp nhận

- [ ] R8.1 (SKEL16): dịch vụ thử `probe-svc` nối `dw-internal` làm kiểm đỏ với dòng nêu `probe-svc` và luật `dw-internal`; gỡ luật khỏi script thì ca này đỏ; thêm `probe-svc` vào `EXCEPTIONS["dw-internal"]` không kèm ADR Accepted nhắc nó thì kiểm vẫn đỏ.
- [ ] R8.2 (SKEL17): dịch vụ thử trên một mạng không `internal: true`, và dịch vụ thử chung mạng với `api` mà `CALLERS` không khai, mỗi cái làm kiểm đỏ.
- [ ] R8.3 (SKEL17): dịch vụ thử với ảnh `alpine:3.20` không digest làm kiểm đỏ; cùng ảnh có `@sha256:` thì qua luật này.
- [ ] R8.4 (SKEL17): dịch vụ thử có `ports` trong tệp gốc làm kiểm đỏ; cùng `ports` chỉ trong `docker-compose.dev.yml` thì qua.
- [ ] R8.5 (SKEL17): dịch vụ thử thiếu `read_only`, thiếu `init: true`, thiếu `deploy.resources` ở overlay prod, hay có một trong `network_mode: "service:qdrant"`, `network_mode: host`, `privileged: true`, `cap_add: [NET_ADMIN]`, `pid: host`, `ipc: host`, volume `/var/run/docker.sock`, mỗi cái làm kiểm đỏ, nêu luật.
- [ ] R8.6 (SKEL17): dịch vụ thử chỉ có profile `full` làm kiểm đỏ.
- [ ] R8.7 (SKEL17): dịch vụ thử đủ luật compose nhưng ảnh không có trong vòng trivy của `.github/workflows/ci.yml` làm kiểm đỏ.
- [ ] R8.8: `uv run python scripts/verify_compose_policy.py` xanh trên checkout; xóa `postgres` khỏi `EXCEPTIONS["dw-internal"]` thì kiểm đỏ, nêu `postgres` và luật `dw-internal`.
- [ ] R8.9 (SKEL17): thêm vào `EXCEPTIONS` của luật `read_only` một dịch vụ đang có `read_only: true` thì kiểm đỏ, nêu dòng; bỏ `read_only` khỏi `postgres` trong cây thử mà không có dòng ngoại lệ thì kiểm đỏ.
- [ ] R8.10 (SKEL17): dòng ngoại lệ luật `internal` cho dịch vụ thử `probe-svc` không nêu `adr` thì kiểm đỏ; nêu một ADR Accepted không nhắc `probe-svc` thì vẫn đỏ; nêu ADR thử Accepted có nhắc `probe-svc` và luật `internal` thì qua; thêm cho `postgres` một dòng ngoại lệ luật `privileged` không ADR (vi phạm không có ở commit nền) thì đỏ; `postgres`, đang có ngoại lệ luật `read_only`, thêm `privileged: true` mà không có dòng ngoại lệ luật `privileged` thì đỏ.
- [ ] Xong: `bash scripts/test_compose_policy.sh` xanh.

## Nguồn

- `infra/compose/docker-compose.yml:16-28`, `infra/compose/docker-compose.yml:343-370`; spec: R8.1, R8.5.
- `infra/compose/docker-compose.yml:45`, `infra/compose/docker-compose.yml:94`, `infra/compose/docker-compose.yml:532`, `infra/compose/docker-compose.yml:563`; spec: R8.3, R8.8.
- `infra/compose/docker-compose.yml:81-83`, `infra/compose/docker-compose.yml:307-309`; spec: R8.4, R8.8.
- `.github/workflows/ci.yml:32-46`, `.github/workflows/ci.yml:281-290`, `.github/workflows/ci.yml:309-313`; spec: R8.7.
- `scripts/test_check_plans.sh:1-15`; spec: SKEL16, SKEL17.

## Comments

- 2026-10-27 (agent): chờ ticket 01, vì cả hai sửa `.github/workflows/ci.yml` (Quyết định 27/10/2026 của spec).
- 2026-10-27 (agent): sửa theo khuyến nghị của gate chạy lại trên `bce52d4` (Đạt ủy quyền 27/10/2026): `EXCEPTIONS` theo từng luật thay `PREDATING` toàn phần, đỏ hai chiều (R8, R8.9), thêm `init: true` (R8.5).
- 2026-10-27 (agent): sửa theo khuyến nghị của gate trên `d9fc4da` (Đạt chọn phương án A): chặn `network_mode`, `privileged`, `cap_add`, `pid`/`ipc: host`, docker socket (R8.5); ngoại lệ ngoài tập có trước luật phải nêu ADR Accepted (R8.10).
- 2026-10-27 (agent): sau bước xác nhận trên `e9084eb`: ngoại lệ khóa bằng vi phạm ở `BASE_SHA`, ADR phải nhắc dịch vụ và luật (R8.10); mọi lối lách compose có ca trồng lỗi (R8.5).
- 2026-10-27 (agent): sau lần xác nhận thứ hai trên `2639c06`: mỗi điều kiện là một luật có tên, `dw-internal` dùng chung cơ chế ngoại lệ khóa theo commit nền và ADR.
