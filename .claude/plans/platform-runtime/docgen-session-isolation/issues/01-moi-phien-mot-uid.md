# 01 — Mỗi phiên docgen chạy dưới một uid riêng

Status: needs-triage
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
    - `isolate_sessions: bool = True`;
    - `session_uid_base: int = 20000`, `session_uid_count: int = 1024`;
    - `shared_temp_dirs: tuple[str, ...] = ("/tmp", "/dev/shm", "/dev/mqueue")`.

    Sửa luôn chú thích của `max_concurrency` (`apps/docgen/src/dw_docgen/settings.py:40`) cho trỏ tới
    ADR 0025.

2. `apps/docgen/src/dw_docgen/workspace.py`, `SessionWorkspace(root, uids: range | None)`:
    - Một phiên mới nhận uid nhỏ nhất trong dải mà chưa thư mục phiên nào giữ, dưới một
      `threading.Lock`. Thư mục được tạo `0700` và `chown` cho uid đó. Hết dải thì ném
      `SessionPoolExhaustedError`, và API trả 503.
    - `uid_of(session_id)` đọc chủ của thư mục phiên. Chủ nằm ngoài dải (uid 0 chẳng hạn) thì ném lỗi, không
      chạy lệnh.
    - `scratch_dir` là `0700`.
    - `uids=None` giữ nguyên hành vi cũ. Chỉ unit test dùng nó.
3. `apps/docgen/src/dw_docgen/runner.py`, `run_command(..., uid: int | None)`:
    - Khi có uid, `Popen` nhận `user=uid, group=uid, extra_groups=[], umask=0o077`.
    - Sau lệnh, kể cả khi quá giờ, chạy `kill -9 -1` dưới uid đó cho tới khi `/proc` không còn tiến trình
      nào của uid (tối đa `_KILL_ROUNDS` vòng).
    - Sau khi kill, xóa mọi mục của uid đó ở `shared_temp_dirs`.
    - Không có uid thì giữ `_kill_group` như cũ.
4. `apps/docgen/src/dw_docgen/files.py`: thư mục cha mà upload tạo và tệp upload ghi đều `chown` cho uid
   của phiên, để shell của phiên sửa và xóa được.
5. `apps/docgen/src/dw_docgen/api.py`: upload, download và release giữ cùng semaphore với execute. Một
   tiến trình của phiên không được đổi một thành phần đường dẫn thành symlink giữa lúc kiểm và lúc ghi,
   vì service ghi bằng `DAC_OVERRIDE`.
6. `apps/docgen/src/dw_docgen/main.py`:
    - Khi `isolate_sessions` mà euid khác 0, hoặc một uid trong dải không có dòng `passwd`, thì lifespan
      ném `RuntimeError`, và service không lên.
    - Lifespan đặt `/work` về `0711`.
    - `SessionWorkspace` nhận dải uid.
7. `infra/docker/docgen.Dockerfile`: thêm dòng `passwd` và `group` cho 1024 uid `dws<n>` từ 20000, vì
   LibreOffice không dựng được user installation cho một uid không có dòng `passwd` (đo 2026-10-29).
   `USER dw` giữ nguyên, nên image chạy trần sẽ không lên, thay vì chạy không cách ly.
8. `infra/compose/docker-compose.yml`, service `docgen`:
    - `user: "0:0"`;
    - `cap_add: [SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER]`;
    - `/work:mode=0711`.

    `docgen-gateway` giữ `user: "1001:1001"`.

9. Unit test `apps/docgen/tests/conftest.py` đặt `isolate_sessions=False`.
10. `docs/adr/0025-each-docgen-session-runs-under-its-own-uid.md`.
11. Dựng lại image và chạy `docgen` cùng `docgen-gateway` (`docker compose ... --profile infra up -d --build docgen docgen-gateway`) trước khi chạy test integration, vì test đó gọi container thật.

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
- [ ] Những gì phiên để lại ở `/tmp` và `/dev/shm` biến mất sau lệnh, còn trong lệnh thì vẫn thấy. Bỏ bước
      xóa thì test đỏ.
- [ ] Một upload `sub/dir/f.txt` xóa được bằng `rm -r sub` từ shell của phiên. Bỏ `chown` ở upload thì test
      đỏ.
- [ ] Upload của một phiên đang có lệnh chạy chỉ xong sau khi lệnh xong (unit, giữ semaphore). Bỏ
      semaphore ở upload thì test đỏ.
- [ ] Bật `isolate_sessions` mà không phải root thì lifespan ném lỗi (unit). Bỏ phép kiểm thì test đỏ.
- [ ] Một thư mục phiên có chủ ngoài dải thì `uid_of` từ chối (unit). Bỏ phép kiểm thì test đỏ.
- [ ] LibreOffice vẫn chuyển DOCX sang PDF, và các test chứa (fork bomb, memory bomb, mạng) vẫn xanh trong
      `test_sandbox_image.py`.
- [ ] Xong: `uv run python -m pytest apps/docgen/tests -q` xanh.

## Nguồn

- `apps/docgen/src/dw_docgen/settings.py:40`, `apps/docgen/src/dw_docgen/runner.py:219`,
  `apps/docgen/src/dw_docgen/workspace.py:52`, `apps/docgen/src/dw_docgen/api.py:113`,
  `infra/compose/docker-compose.yml:370`, `infra/docker/docgen.Dockerfile:97`; ADR 0025, ADR 0119
  (Proposed; runner gVisor cho mã tenant, không thay docgen).

## Comments

- 2026-10-29 (agent, tạm theo ủy quyền): Duyệt ticket. Trong chat 2026-10-29, Đạt chọn mỗi phiên một uid
  riêng, với service chạy bằng uid 0 trong container và năm capability, chọn ghi quyết định ở ADR 0025,
  và giao agent tự gate, tự duyệt ticket này.
