"""Run external programs such as MadGraph and DelphesPythia8.

A program runs with its input closed and its output appended to a log file, in
a process group of its own, so that stopping it at a time limit or on an
interrupt also stops every process it started, such as MadGraph's parallel
jobs.
"""

import contextlib
import os
import shlex
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_LOG_TAIL_LINES = 20


class ProgramError(RuntimeError):
    """An external program failed or ran past its time limit."""


def available_cores() -> int:
    """Return the number of CPUs this process may run on.

    On Linux this is the CPU affinity of the process, which a batch system such
    as Slurm restricts to the job's allocation; elsewhere it is every CPU of the
    machine.
    """
    if sys.platform == "linux":
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def run_program(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    log: Path,
    timeout: float | None = None,
) -> None:
    """Run `command` in `cwd`, appending a line naming it and its output to `log`.

    Parameters
    ----------
    command : sequence of str or path-like
        The program and its arguments.
    cwd : Path
        Directory the program runs in.
    log : Path
        File that receives the program's standard output and error.
    timeout : float or None, optional
        Seconds the program may run; ``None`` sets no limit. At the limit, the
        program and every process it started are stopped.

    Raises
    ------
    ValueError
        If `timeout` is negative.
    ProgramError
        If the program exits with a failing status or is still running at the
        time limit; the message ends with the last lines of `log`.
    """
    if timeout is not None and timeout < 0:
        raise ValueError(f"timeout must not be negative, got {timeout}")
    arguments = [os.fspath(part) for part in command]
    name = Path(arguments[0]).name
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"$ {shlex.join(arguments)}\n")
        stream.flush()
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process(process)
            raise ProgramError(
                f"{name} was stopped at the time limit\n{log_tail(log)}"
            ) from None
        except BaseException:
            stop_process(process)
            raise
    if returncode != 0:
        raise ProgramError(f"{name} exited with status {returncode}\n{log_tail(log)}")


def stop_process(process: subprocess.Popen[Any]) -> None:
    """Kill `process`, with every process of its group when it leads one, and reap it.

    A process started with ``start_new_session=True``, as :func:`run_program`
    starts one, leads its own group, which holds the processes it started.
    """
    # A group whose ID is the PID of a living process is that process's own.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.kill()
    process.wait()


def log_tail(log: Path, lines: int = _LOG_TAIL_LINES) -> str:
    """Return the last `lines` lines of `log`, headed by its path."""
    text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return f"Last lines of {log}:\n" + "\n".join(text[-lines:])
