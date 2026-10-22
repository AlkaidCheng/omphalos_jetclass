import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from omphjc.programs import (
    ProgramError,
    available_cores,
    log_tail,
    run_program,
    stop_process,
)

# Starts a job of its own, records the job's PID in job.pid, then waits.
STARTS_A_JOB_AND_WAITS = """\
import subprocess, sys, time
from pathlib import Path
job = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path("job.pid").write_text(str(job.pid))
time.sleep(60)
"""


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_the_command_and_its_output_go_to_the_log(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("earlier run\n")
    code = "import sys; print('to stdout', flush=True); print('to stderr', file=sys.stderr)"
    run_program(python(code), cwd=tmp_path, log=log)
    lines = log.read_text().splitlines()
    assert lines[0] == "earlier run"
    assert lines[1].startswith("$ ") and "to stdout" in lines[1]
    assert lines[2:] == ["to stdout", "to stderr"]


def test_the_program_runs_in_the_given_directory_without_input(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    run_program(
        python("import os, sys; print(os.getcwd()); print(repr(sys.stdin.read()))"),
        cwd=tmp_path,
        log=log,
    )
    assert log.read_text().splitlines()[1:] == [str(tmp_path.resolve()), "''"]


def test_a_failing_status_raises_with_the_end_of_the_log(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    command = python("import sys; print('last words'); sys.exit(3)")
    with pytest.raises(ProgramError, match="exited with status 3") as error:
        run_program(command, cwd=tmp_path, log=log)
    assert str(error.value).endswith("last words")


def test_the_time_limit_stops_the_program_and_its_jobs(tmp_path: Path) -> None:
    with pytest.raises(ProgramError, match="stopped at the time limit"):
        run_program(
            python(STARTS_A_JOB_AND_WAITS),
            cwd=tmp_path,
            log=tmp_path / "run.log",
            timeout=1,
        )
    assert _ends_within(int((tmp_path / "job.pid").read_text()), seconds=5)


def test_an_interrupt_stops_the_program_and_its_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_file = tmp_path / "job.pid"
    wait = subprocess.Popen.wait
    calls = 0

    def wait_interrupted_once_the_job_runs(
        process: subprocess.Popen[bytes], timeout: float | None = None
    ) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert _appears_within(job_file, seconds=10)
            raise KeyboardInterrupt
        return wait(process, timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", wait_interrupted_once_the_job_runs)
    with pytest.raises(KeyboardInterrupt):
        run_program(
            python(STARTS_A_JOB_AND_WAITS), cwd=tmp_path, log=tmp_path / "run.log"
        )
    assert _ends_within(int(job_file.read_text()), seconds=5)


def test_a_process_outside_a_group_of_its_own_is_stopped() -> None:
    process = subprocess.Popen(python("import time; time.sleep(60)"))
    stop_process(process)
    assert process.returncode is not None


def test_a_negative_time_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout"):
        run_program(python("pass"), cwd=tmp_path, log=tmp_path / "run.log", timeout=-1)


def test_log_tail_gives_the_last_lines_after_the_path(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("".join(f"line {number}\n" for number in range(30)))
    assert log_tail(log, lines=2) == f"Last lines of {log}:\nline 28\nline 29"
    assert log_tail(log).count("\n") == 20


def test_available_cores_counts_the_cpus_this_process_may_use() -> None:
    cores = available_cores()
    if sys.platform == "linux":
        assert cores == len(os.sched_getaffinity(0))
    else:
        assert cores == os.cpu_count()


def _ends_within(pid: int, *, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _appears_within(path: Path, *, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True
