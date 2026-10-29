# 01 — Mỗi phiên docgen chạy dưới một uid riêng

Status: resolved (2026-10-29, main)
Area: platform-runtime
Yêu cầu: không (việc cỡ A, một câu: shell của mỗi phiên docgen chạy dưới uid riêng của phiên, nên không đọc được gì của phiên khác; quyết định ở ADR 0025)

## Mục tiêu

Một container docgen phục vụ mọi tenant, và tên phiên mang tenant
(`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sandbox.py:156`). Hiện mọi phiên chạy
chung uid 1001 trên chung `/work` (`infra/compose/docker-compose.yml:370`,
`infra/compose/docker-compose.yml:375`), nên một agent bị prompt injection qua tệp đính kèm đọc được bản
nháp của tenant khác bằng `cat ../<phiên khác>/...`. Test xfail
`apps/docgen/tests/integration/test_sandbox_image.py:237` ghi nhận lỗ hổng này. Cùng uid đó còn đọc được
`/proc/<service>/environ`, tức `DW_DOCGEN_TOKEN`. Và một tiến trình đã `setsid` thì thoát khỏi lệnh
`killpg` của `apps/docgen/src/dw_docgen/runner.py:219`, nên sống qua lệnh đã sinh ra nó. Ticket này cho
mỗi phiên một uid trong một dải cố định. Thư mục phiên là `0700` của uid đó, còn service chạy bằng uid 0
của container với năm capability (ADR 0025).

## Việc cần làm

1. `apps/docgen/src/dw_docgen/settings.py`, thêm các setting sau:
    - `session_uid_base: int = 20000`, `session_uid_count: int = 1024`, với validator đòi base ≥ 10000;
    - `shared_temp_dirs: tuple[str, ...] = ("/tmp", "/dev/shm", "/dev/mqueue")`.

    Sửa luôn chú thích của `max_concurrency` (`apps/docgen/src/dw_docgen/settings.py:40`) cho trỏ tới
    ADR 0025.

2. `apps/docgen/src/dw_docgen/workspace.py`, `SessionWorkspace(root, uids: range | None)`:
    - Một phiên mới nhận uid nhỏ nhất trong dải còn rảnh, dưới một `threading.Lock`. Rảnh nghĩa là không
      thư mục phiên nào giữ uid đó và `/proc` không còn tiến trình nào của nó. Trước khi giao uid, xóa mọi
      thứ của uid đó: các mục ở `shared_temp_dirs`, và SysV IPC bằng `ipcrm --all` chạy dưới uid đó. Xóa
      lỗi thì bỏ qua uid đó và thử uid kế. Thư mục được tạo `0700` và `chown` cho uid.
    - Hết dải thì quét các phiên quá TTL một lượt rồi thử lại. Vẫn hết thì ném `SessionPoolExhaustedError`,
      và API trả 503.
    - Chỉ execute và upload được tạo phiên. Download của một phiên chưa có trả `file_not_found` cho từng
      đường dẫn; release của một phiên chưa có là 204.
    - `uid_of(session_id)` đọc chủ của thư mục phiên. Chủ nằm ngoài dải (uid 0 chẳng hạn) thì ném
      `SessionIsolationError`: API trả 500, ghi log mức error, và không chạy lệnh.
    - `scratch_dir` thuộc root, mode `0700`. Shell chỉ nhận fd của tệp output, không cần đường dẫn.
    - `uids=None` giữ nguyên hành vi cũ. Chỉ unit test dùng nó, và mục 6 cấm nó khi service là root.
    - `adopt_root()`, lifespan gọi:
        - đặt `/work` về `0711`;
        - xóa mọi mục ở `/work` mà chủ không thuộc dải, trừ `.service`.
    - Trước execute và mọi route tệp, nếu uid của phiên còn tiến trình sống (kill lần trước không hội tụ),
      API trả 503 và không làm gì.
3. `apps/docgen/src/dw_docgen/runner.py`, `run_command(..., uid: int | None)`, tham số bắt buộc:
    - Khi có uid, `Popen` nhận `user=uid, group=uid, extra_groups=[], umask=0o077`.
    - Sau lệnh, kể cả khi quá giờ, chạy `kill -9 -1` dưới uid đó cho tới khi `/proc` không còn tiến trình
      nào của uid (tối đa `_KILL_ROUNDS` vòng). Không hội tụ thì ghi log mức error; uid đó không về lại
      dải chừng nào còn tiến trình, theo luật "rảnh" ở mục 2.
    - Sau khi kill, xóa các mục của uid ở `shared_temp_dirs` và SysV IPC của nó, bằng cùng hàm
      `purge_uid` mà mục 2 dùng. Xóa lỗi thì ghi log mức error. uid còn bẩn sẽ được xóa lại trước khi giao,
      và bị bỏ qua nếu vẫn lỗi.
    - Không có uid thì giữ `_kill_group` như cũ.
4. `apps/docgen/src/dw_docgen/files.py`:
    - Thư mục cha mà upload tạo, và tệp upload ghi, đều `chown` cho uid của phiên, để shell của phiên sửa
      và xóa được.
    - Upload và download chỉ đụng tệp thường. Mục đã có mà không phải tệp thường (FIFO, socket, thiết bị)
      trả `invalid_path`, kiểm bằng `lstat` trước khi mở, và mở với `O_NOFOLLOW | O_NONBLOCK`.
5. `apps/docgen/src/dw_docgen/api.py`: upload, download, release và lượt sweep sau execute đều giữ cùng
   semaphore với execute. Lý do: service ghi bằng `DAC_OVERRIDE`, nên tiến trình của một phiên không được
   đổi một thành phần đường dẫn thành symlink giữa lúc kiểm và lúc ghi, và sweep không được xóa một phiên
   đang upload.
6. `apps/docgen/src/dw_docgen/main.py`: `create_app(settings=None, *, isolate_sessions: bool = True)`.
   Đây là tham số trong code, không phải setting đọc từ env, nên không biến môi trường nào tắt được cách
   ly; factory của uvicorn luôn cách ly. Lifespan ném `RuntimeError` (service không lên) khi:
    - cách ly bật mà euid khác 0;
    - cách ly tắt mà euid bằng 0;
    - cách ly bật mà `max_concurrency` khác 1;
    - một uid trong dải không có dòng `passwd` tên `dws<n>`, trong đó n là vị trí của uid trong dải.

    Ngoài ra lifespan gọi `adopt_root()` và đưa dải uid cho `SessionWorkspace`.

7. `infra/docker/docgen.Dockerfile`: thêm dòng `passwd` và `group` cho 1024 uid `dws<n>` từ 20000, vì
   LibreOffice không dựng được user installation cho một uid không có dòng `passwd` (đo 2026-10-29).
   `USER dw` giữ nguyên, nên image chạy trần sẽ không lên, thay vì chạy không cách ly.
8. `infra/compose/docker-compose.yml`, service `docgen`:
    - `user: "0:0"`;
    - `cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER]`;
    - `/work:mode=0711`.

    `docgen-gateway` giữ `user: "1001:1001"`.

9. Unit test dựng app bằng `create_app(settings, isolate_sessions=False)`.
10. `docs/adr/0025-each-docgen-session-runs-under-its-own-uid.md`.
11. Dựng lại image và chạy `docgen` cùng `docgen-gateway`
    (`docker compose ... --profile infra up -d --build docgen docgen-gateway`) trước khi chạy test
    integration, vì test đó gọi container thật.

## Tiêu chí chấp nhận

- [x] Shell của phiên A không đọc được tệp của phiên B và không liệt kê được `/work`: bỏ dấu xfail ở
      `test_a_session_shell_cannot_read_another_sessions_files`, và test xanh. Bỏ `chown` hoặc `0700` thì
      test đỏ.
- [x] Hai phiên chạy dưới hai uid khác nhau trong dải, và `CapEff` bằng 0. Bỏ `user=` ở `Popen` thì test
      đỏ.
- [x] Không phiên nào đọc được biến `DW_DOCGEN_` trong `/proc/*/environ`. Nay đọc được, nên test đỏ ở
      commit gốc.
- [x] Một `setsid sleep 300 &` không sống qua lệnh của nó: đối chứng dương thấy nó trong lệnh, và lệnh sau
      đếm được 0. Thay kill theo uid bằng `_kill_group` thì test đỏ.
- [x] Những gì phiên để lại ở `/tmp`, `/dev/shm` và `/dev/mqueue`, và một đoạn SysV shm tạo bằng `ipcmk`,
      đều biến mất sau lệnh, còn trong lệnh thì vẫn thấy. Bỏ bước xóa thì test đỏ.
- [x] Một upload `sub/dir/f.txt` xóa được bằng `rm -r sub` từ shell của phiên. Bỏ `chown` ở upload thì test
      đỏ.
- [x] Download một FIFO do shell tạo trả `invalid_path` ngay, và lệnh kế của phiên vẫn chạy. Bỏ phép kiểm
      tệp thường thì test treo tới timeout của client và đỏ.
- [x] Upload của một phiên đang có lệnh chạy chỉ xong sau khi lệnh xong (unit, giữ semaphore). Bỏ
      semaphore ở upload thì test đỏ.
- [x] Lifespan từ chối từng trường hợp ở mục 6 (unit, một test mỗi trường hợp; trường hợp "tắt mà là root"
      giả euid bằng monkeypatch). Bỏ một phép kiểm thì test của nó đỏ.
- [x] Một thư mục phiên có chủ ngoài dải thì `uid_of` từ chối (unit). Bỏ phép kiểm thì test đỏ.
- [x] Dải đã đầy (mọi uid có thư mục giữ) thì một phiên mới nhận 503, và phiên quá TTL đã bị quét trước đó
      (unit). Bỏ việc kiểm "rảnh" hoặc bỏ lượt quét thì test đỏ.
- [x] Một uid còn tiến trình sống không được giao, kể cả khi không thư mục nào giữ nó (unit, POSIX; dải là
      uid của chính tiến trình test). Bỏ phép kiểm `/proc` thì test đỏ.
- [x] Phiên có uid còn tiến trình sống nhận 503 ở execute và ở route tệp (unit, POSIX). Bỏ phép kiểm thì test
      đỏ.
- [x] `purge_uid` xóa mục của uid ở các thư mục được chỉ, và để yên mục của uid khác (unit). Bỏ phép so chủ
      thì test đỏ.
- [x] Lượt sweep sau execute chạy khi semaphore đang bị giữ (unit). Đưa sweep ra ngoài thì test đỏ.
- [x] `adopt_root()` xóa mục có chủ ngoài dải, giữ `.service`, và đặt `0711` (unit). Bỏ một bước thì test
      đỏ.
- [x] Release một phiên chưa có trả 204 và không tạo thư mục (unit). Cho release tạo phiên thì test đỏ.
- [x] Download một phiên chưa có không tạo thư mục phiên (unit). Bỏ `create=False` thì test đỏ.
- [x] LibreOffice vẫn chuyển DOCX sang PDF, và các test chứa (fork bomb, memory bomb, mạng) vẫn xanh trong
      `test_sandbox_image.py`.
- [x] Xong: `uv run python -m pytest apps/docgen/tests -q` xanh.

## Nguồn

- `apps/docgen/src/dw_docgen/settings.py:40`, `apps/docgen/src/dw_docgen/runner.py:219`,
  `apps/docgen/src/dw_docgen/workspace.py:52`, `apps/docgen/src/dw_docgen/api.py:113`,
  `infra/compose/docker-compose.yml:370`, `infra/docker/docgen.Dockerfile:97`; ADR 0025, ADR 0119
  (Proposed; runner gVisor cho mã tenant, không thay docgen).

## Comments

- 2026-10-29 (Đạt): Duyệt ticket.
- 2026-10-29 (agent): dòng trên ghi từ câu trả lời trong chat 2026-10-29: Đạt chọn phương án "uid riêng
  mỗi phiên", mà mô tả có câu "Ticket tier A ở platform-runtime, tôi tự gate và tự duyệt"; chọn service
  chạy bằng uid 0 trong container với năm capability; và chọn ghi quyết định ở ADR 0025.
- 2026-10-29 (agent): checking-plan-readiness, lượt 1 (builder check và boundary walk), 0 CRITICAL, 3 HIGH:
    - tắt cách ly khi service là root;
    - `max_concurrency` khác 1 mở lại TOCTOU;
    - uid được cấp lại khi còn tiến trình hoặc SysV IPC.

    Các MEDIUM:
    - FIFO treo semaphore chung;
    - sweep đua với upload;
    - dải uid không được kiểm;
    - cạn dải;
    - mã lỗi của `uid_of`;
    - thư mục cũ ở `/work`.

    Đã sửa vào mục 1-6 và vào tiêu chí.

- 2026-10-29 (agent, tạm): không có hạn mức uid theo tenant. Dải 1024 uid và sweep theo TTL 1 giờ là chặn
  trên; một tenant mở hơn 1024 hội thoại trong một giờ thì mọi tenant nhận 503 cho tới lượt sweep kế. Nếu
  sai thì: thêm hạn mức theo tiền tố tenant của tên phiên ở mục 2, không đổi gì khác.
- 2026-10-29 (agent, tạm): không có test cho `threading.Lock` khi cấp uid. Mọi lời gọi tạo phiên đã nằm dưới
  semaphore, nên lock là lớp thứ hai và không có cách làm nó đỏ một cách tất định. Nếu sai thì: thêm một
  test hai thread gọi `session_dir` cho hai phiên mới.
- 2026-10-29 (agent): lượt xác nhận gate, 0 CRITICAL. Sửa theo nó:
    - N1 (HIGH): cách ly tắt được bằng env khi service không phải root. Nay `isolate_sessions` là tham số
      của `create_app` (mục 6).
    - C3, C5, C7, C9: thêm tiêu chí cho luật "rảnh", sweep dưới semaphore, quét trước 503, và
      `adopt_root`.
    - N2: phiên còn tiến trình sống nhận 503.
    - N3: xóa lỗi sau lệnh.
    - N4: chủ của `scratch_dir`.
- 2026-10-29 (agent, tạm): bước xóa trước khi giao uid (mục 2) và bước xóa sau lệnh (mục 3) gọi chung
  `purge_uid`. Test image chỉ làm đỏ được bước sau lệnh, vì muốn tàn dư sống qua bước đó thì phải gỡ chính
  nó. Nếu sai thì: thêm một test image tạo tàn dư bằng một uid trong dải rồi mở một phiên mới.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-29 (agent): Đã làm.
    - `dw_docgen/identity.py` mới: `child_identity`, `run_as`, `process_owners`, `kill_all`, `signal_all`,
      `purge`.
    - Workspace cấp uid theo luật "rảnh", có `uid_of` và `adopt_root`; `resolve` không tạo phiên.
    - Runner chạy dưới uid với `umask 077`, kill theo uid, rồi xóa tàn dư.
    - Files chỉ đụng tệp thường và `chown` cho uid.
    - API: mọi route giữ semaphore, sweep ở bên trong; lỗi cách ly trả 400/413/503/500.
    - Main có bốn phép từ chối khởi động.
    - Dockerfile có 1024 dòng `dws<n>`; compose chạy uid 0 với năm capability, `/work` 0711.
    - Test: `tests/unit/test_isolation.py` (16), một test FIFO ở `test_files.py`, và bảy test image mới.
      Test xuyên phiên bỏ xfail và kiểm thêm `ls ../<phiên khác>`.
- 2026-10-29 (agent, tạm): xóa SysV IPC theo id đọc từ `/proc/sysvipc/*`, không dùng `ipcrm --all` như mục 2. Đo trên image: `--all` trả 1 ngay khi có đối tượng của uid khác, nên mã thoát của nó không phân biệt
  được xóa lỗi với container đang bận. Nếu sai thì: chỉ đổi `identity._purge_ipc`.
- 2026-10-29 (agent, tạm): lượt `kill -9 -1` đầu tiên chỉ chạy khi shell còn sống (hết giờ). Bình thường
  shell đã được `wait` thu, và `kill_all` kiểm `/proc` trước khi sinh tiến trình, nên không tốn một bash
  mỗi lệnh. Mục 3 viết "sau lệnh chạy `kill -9 -1`". Nếu sai thì: bỏ điều kiện `process.poll()` ở
  `runner._kill_uid`.
- 2026-10-29 (agent, tạm): thêm `sessions_isolated` vào `/health`, có test image khẳng định nó, để một
  compose chạy service mà không cách ly đỏ ở CI. Ngoài chữ của ticket.
- 2026-10-29 (agent, tạm): tệp upload tạo mới có mode 0600 (trước là 0644), và download chỉ đọc tối đa
  ngân sách cộng một byte.
- 2026-10-29 (agent, tạm): tiêu chí "environ đọc được ở commit gốc" được chứng minh bằng đột biến "bỏ đổi
  uid" (test đỏ), không bằng cách chạy image cũ. Image cũ đã bị dựng đè; cách đo bằng probe cùng uid ở
  phần trên cho cùng kết quả.
- 2026-10-29 (agent): reviewing-feature-security:
    - **Tenant:** phiên A không đọc, không liệt kê được phiên B, và không đọc được environ của service
      (test image).
    - **Quyền:** token không đổi. `/health` không cần token như trước, chỉ thêm một boolean.
    - **Công cụ agent và sandbox:**
        - kill theo uid gom được tiến trình `setsid`;
        - tàn dư ở `/tmp`, `/dev/shm`, `/dev/mqueue` và SysV IPC bị xóa;
        - FIFO không treo route;
        - uid còn tiến trình không được giao, và phiên của nó nhận 503.
    - **Container:** thêm năm capability cho service; rủi ro còn lại ghi ở ADR 0025. Shell có `CapEff` 0
      (test).
    - **Job nền:** sweep chạy dưới semaphore (test).
    - **Phụ thuộc:** không thêm gói nào.
    - `reviewing-deployment-security` cho service compose đã đổi để tới cuối đợt (wave-close.md).
- 2026-10-29 (agent): mutation check, 22 đột biến, đối chứng chưa đột biến xanh ở cả ba nơi, cả 22 đều đỏ:
    - **Image** (6): thư mục 0755, bỏ đổi uid, kill theo nhóm, bỏ xóa tàn dư, bỏ `chown` upload, FIFO coi
      như tệp.
    - **Unit Windows** (9): bỏ từ chối khi không phải root, cho root chạy không cách ly, bỏ kiểm
      `max_concurrency`, bỏ validator base, nhận chủ ngoài dải, bỏ sweep trước 503, `adopt_root` giữ mục
      lạ, sweep ngoài semaphore, upload ngoài semaphore. Thêm đột biến "download tạo phiên".
    - **Unit Linux, uid 1000** (6): bỏ kiểm `passwd`, giao uid còn tiến trình, phục vụ phiên còn tiến
      trình, `purge` bỏ so chủ, `adopt_root` bỏ chmod, FIFO ở unit.

    Đột biến 0755 lúc đầu không bị bắt: tệp upload 0600 vẫn chặn `cat`. Test đã siết thêm phần kiểm
    `ls ../<phiên khác>`, rồi bắt được.

- 2026-10-29 (agent): gate nhanh:
    - ruff, format và `python -m mypy` (449 tệp) sạch;
    - `make test-unit` 1533 qua; `make test-contract` 24 qua; `make test-architecture` 7 contract giữ;
    - `verify_invariants` đạt;
    - toàn bộ `apps/docgen/tests` trên container dựng lại: 77 qua, 8 bỏ qua (POSIX, xanh trên Linux).
- 2026-10-29 (agent): độ trễ, ngoài yêu cầu của latency.md vì ticket không đổi cách truy cập DB. Đo 200
  lệnh `echo`, ấm, gọi thẳng vào container (không qua gateway), cùng image và cùng cờ:
    - commit gốc `0e4af59` (uid 1001): P50 9,0 ms, P95 10,9 ms, P99 14,7 ms;
    - sau ticket: P50 17,5 ms, P95 21,2 ms, P99 26,6 ms;
    - upload sau ticket: P50 5,0 ms, P95 7,4 ms, P99 12,2 ms.

    P95 tệ hơn quá 20%. Lý do: phần cách ly mỗi lệnh (đổi uid, quét `/proc` tìm tiến trình sống sót, xóa
    ba thư mục và bảng SysV IPC, kiểm uid của phiên) đo trong tiến trình là khoảng 3,8 ms. Bản đầu tốn hơn,
    P50 27 ms; đã sửa bằng cách bỏ bash kill thừa khi không còn tiến trình. Vẫn trong ngân sách 300 ms, và
    một lệnh tài liệu thật tốn hàng giây.

- 2026-10-29 (agent): `docs/adr/0119-each-code-execution-gets-a-fresh-gvisor-container.md:28` và `:113` vẫn
  tả docgen là "một uid". Đó là bối cảnh của một ADR đang Proposed, nên tôi không sửa; Đạt quyết có cập
  nhật hay không.
