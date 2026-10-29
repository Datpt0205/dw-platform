# 01 — Mỗi phiên docgen chạy dưới một uid riêng

Status: ready-for-agent
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

- [ ] Shell của phiên A không đọc được tệp của phiên B và không liệt kê được `/work`: bỏ dấu xfail ở
      `test_a_session_shell_cannot_read_another_sessions_files`, và test xanh. Bỏ `chown` hoặc `0700` thì
      test đỏ.
- [ ] Hai phiên chạy dưới hai uid khác nhau trong dải, và `CapEff` bằng 0. Bỏ `user=` ở `Popen` thì test
      đỏ.
- [ ] Không phiên nào đọc được biến `DW_DOCGEN_` trong `/proc/*/environ`. Nay đọc được, nên test đỏ ở
      commit gốc.
- [ ] Một `setsid sleep 300 &` không sống qua lệnh của nó: đối chứng dương thấy nó trong lệnh, và lệnh sau
      đếm được 0. Thay kill theo uid bằng `_kill_group` thì test đỏ.
- [ ] Những gì phiên để lại ở `/tmp`, `/dev/shm` và `/dev/mqueue`, và một đoạn SysV shm tạo bằng `ipcmk`,
      đều biến mất sau lệnh, còn trong lệnh thì vẫn thấy. Bỏ bước xóa thì test đỏ.
- [ ] Một upload `sub/dir/f.txt` xóa được bằng `rm -r sub` từ shell của phiên. Bỏ `chown` ở upload thì test
      đỏ.
- [ ] Download một FIFO do shell tạo trả `invalid_path` ngay, và lệnh kế của phiên vẫn chạy. Bỏ phép kiểm
      tệp thường thì test treo tới timeout của client và đỏ.
- [ ] Upload của một phiên đang có lệnh chạy chỉ xong sau khi lệnh xong (unit, giữ semaphore). Bỏ
      semaphore ở upload thì test đỏ.
- [ ] Lifespan từ chối từng trường hợp ở mục 6 (unit, một test mỗi trường hợp; trường hợp "tắt mà là root"
      giả euid bằng monkeypatch). Bỏ một phép kiểm thì test của nó đỏ.
- [ ] Một thư mục phiên có chủ ngoài dải thì `uid_of` từ chối (unit). Bỏ phép kiểm thì test đỏ.
- [ ] Dải đã đầy (mọi uid có thư mục giữ) thì một phiên mới nhận 503, và phiên quá TTL đã bị quét trước đó
      (unit). Bỏ việc kiểm "rảnh" hoặc bỏ lượt quét thì test đỏ.
- [ ] Một uid còn tiến trình sống không được giao, kể cả khi không thư mục nào giữ nó (unit, POSIX; dải là
      uid của chính tiến trình test). Bỏ phép kiểm `/proc` thì test đỏ.
- [ ] Phiên có uid còn tiến trình sống nhận 503 ở execute và ở route tệp (unit, POSIX). Bỏ phép kiểm thì test
      đỏ.
- [ ] `purge_uid` xóa mục của uid ở các thư mục được chỉ, và để yên mục của uid khác (unit). Bỏ phép so chủ
      thì test đỏ.
- [ ] Lượt sweep sau execute chạy khi semaphore đang bị giữ (unit). Đưa sweep ra ngoài thì test đỏ.
- [ ] `adopt_root()` xóa mục có chủ ngoài dải, giữ `.service`, và đặt `0711` (unit). Bỏ một bước thì test
      đỏ.
- [ ] Release một phiên chưa có trả 204 và không tạo thư mục (unit). Cho release tạo phiên thì test đỏ.
- [ ] Download một phiên chưa có không tạo thư mục phiên (unit). Bỏ `create=False` thì test đỏ.
- [ ] LibreOffice vẫn chuyển DOCX sang PDF, và các test chứa (fork bomb, memory bomb, mạng) vẫn xanh trong
      `test_sandbox_image.py`.
- [ ] Xong: `uv run python -m pytest apps/docgen/tests -q` xanh.

## Nguồn

- `apps/docgen/src/dw_docgen/settings.py:40`, `apps/docgen/src/dw_docgen/runner.py:219`,
  `apps/docgen/src/dw_docgen/workspace.py:52`, `apps/docgen/src/dw_docgen/api.py:113`,
  `infra/compose/docker-compose.yml:370`, `infra/docker/docgen.Dockerfile:97`; ADR 0025, ADR 0119
  (Proposed; runner gVisor cho mã tenant, không thay docgen).

## Comments

- 2026-10-29 (Đạt): Duyệt ticket. Ghi từ câu trả lời trong chat 2026-10-29: Đạt chọn phương án "uid riêng
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
