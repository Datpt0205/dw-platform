"""What the containment budget actually does to a command.

Scripts are written to a file and run by path rather than passed with `-c`:
that is how the model works too, and it keeps the tests off the differences
between how `sh` and `cmd.exe` treat quotes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from dw_docgen.runner import SIGKILL_EXIT_CODE, limit_preamble, run_command
from dw_docgen.settings import DocgenSettings

pytestmark = pytest.mark.unit

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="the sandbox image is Linux")


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    work = tmp_path / "session"
    work.mkdir()
    return work


def script(cwd: Path, body: str) -> str:
    """Write `body` as `run.py` in the session and return the command to run it."""
    (cwd / "run.py").write_text(body, encoding="utf-8")
    return f'"{sys.executable}" run.py'


def test_a_benign_command_returns_its_output_and_exit_code(
    settings: DocgenSettings, cwd: Path
) -> None:
    result = run_command(
        script(cwd, "print(2 + 2)"),
        cwd=cwd,
        sink_dir=cwd,
        settings=settings,
        timeout_seconds=10,
        uid=None,
    )

    assert result.exit_code == 0
    assert "4" in result.output
    assert not result.timed_out


def test_stderr_comes_back_alongside_stdout(settings: DocgenSettings, cwd: Path) -> None:
    command = script(cwd, 'import sys\nsys.stderr.write("boom")\nsys.exit(3)\n')

    result = run_command(
        command, cwd=cwd, sink_dir=cwd, settings=settings, timeout_seconds=10, uid=None
    )

    assert result.exit_code == 3
    assert "boom" in result.output


def test_the_command_runs_in_the_session_directory(settings: DocgenSettings, cwd: Path) -> None:
    command = script(cwd, 'open("made.txt", "w").write("x")\n')

    run_command(command, cwd=cwd, sink_dir=cwd, settings=settings, timeout_seconds=10, uid=None)

    assert (cwd / "made.txt").read_text(encoding="utf-8") == "x"


def test_a_command_that_never_finishes_is_killed(settings: DocgenSettings, cwd: Path) -> None:
    command = script(cwd, "import time\ntime.sleep(60)\n")

    result = run_command(
        command, cwd=cwd, sink_dir=cwd, settings=settings, timeout_seconds=2, uid=None
    )

    assert result.timed_out
    assert result.exit_code == SIGKILL_EXIT_CODE
    assert "killed after 2s" in result.output


def test_endless_output_is_capped_and_flagged(settings: DocgenSettings, cwd: Path) -> None:
    command = script(cwd, 'print("x" * 10000)\n')

    result = run_command(
        command, cwd=cwd, sink_dir=cwd, settings=settings, timeout_seconds=10, uid=None
    )

    assert result.truncated
    assert len(result.output) <= settings.max_output_bytes


def test_the_parent_environment_does_not_reach_the_command(
    settings: DocgenSettings, cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DW_DOCGEN_TOKEN", "super-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "also-secret")
    command = script(
        cwd,
        "import os\n"
        "leaked = [k for k in os.environ if k.startswith('DW_') or 'PASSWORD' in k]\n"
        "print('LEAKED', sorted(leaked))\n",
    )

    result = run_command(
        command, cwd=cwd, sink_dir=cwd, settings=settings, timeout_seconds=10, uid=None
    )

    assert "LEAKED []" in result.output


@POSIX_ONLY
def test_the_preamble_caps_the_shell_before_the_command_runs(
    settings: DocgenSettings, cwd: Path
) -> None:
    result = run_command(
        "ulimit -t; ulimit -c",
        cwd=cwd,
        sink_dir=cwd,
        settings=settings,
        timeout_seconds=10,
        uid=None,
    )

    assert str(settings.cpu_seconds) in result.output
    assert result.exit_code == 0


@POSIX_ONLY
def test_a_memory_bomb_dies_inside_the_budget(settings: DocgenSettings, cwd: Path) -> None:
    small = settings.model_copy(update={"address_space_mb": 128})
    command = script(cwd, "b = bytearray(512 * 1024 * 1024)\nprint(len(b))\n")

    result = run_command(
        command, cwd=cwd, sink_dir=cwd, settings=small, timeout_seconds=20, uid=None
    )

    assert result.exit_code != 0
    assert not result.timed_out


def test_the_preamble_caps_forks_and_file_size(settings: DocgenSettings) -> None:
    """The fork bomb itself is run against the built image, not on a CI runner
    whose other processes share this uid; here we prove the caps are asked for."""
    preamble = limit_preamble(settings.model_copy(update={"root": "/work"}))

    if settings.enforce_limits:
        assert f"ulimit -u {settings.max_processes}" in preamble
        assert f"ulimit -f {settings.max_file_bytes // 512}" in preamble


def test_no_preamble_where_the_platform_cannot_apply_limits(settings: DocgenSettings) -> None:
    assert bool(limit_preamble(settings)) is settings.enforce_limits
