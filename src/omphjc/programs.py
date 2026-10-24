"""Run external programs such as MadGraph and DelphesPythia8.

A program runs with its input closed and its output appended to a log file, in
a process group of its own, so that stopping it at a time limit or on an
interrupt also stops every process it started, such as MadGraph's parallel
jobs.
"""

import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None  # type: ignore[assignment]

# ru_maxrss is in bytes on macOS and in kibibytes elsewhere.
_MAXRSS_BYTES = 1 if sys.platform == "darwin" else 1024

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


def find_program(program: str, program_path: Path | None, *, description: str) -> Path:
    """Return `program_path`, or the program `program` on PATH when it is ``None``.

    Parameters
    ----------
    program : str
        The program's name on PATH.
    program_path : Path or None
        The program file to use instead of the one on PATH.
    description : str
        How the program is called in messages, for example
        ``"MadGraph's bin/mg5_aMC"``.

    Raises
    ------
    FileNotFoundError
        If `program_path` is not a file, or none is given and PATH has no
        `program`.
    """
    if program_path is not None:
        if not program_path.is_file():
            raise FileNotFoundError(f"{description} {str(program_path)!r} not found")
        return program_path
    found = shutil.which(program)
    if found is None:
        raise FileNotFoundError(
            f"{program} is not on PATH; give the path of {description}"
        )
    return Path(found)


@dataclass(frozen=True)
class ProgramUsage:
    """What a run of an external program took.

    Parameters
    ----------
    wall_seconds : float
        Time from the program's start to its exit.
    cpu_seconds : float or None
        User and system CPU time of the program and of every process it
        waited for, so MadGraph's parallel jobs count; ``None`` where the
        platform does not report it.
    max_memory_mb : float or None
        Peak resident memory, in MiB, of the largest process this Python
        process has waited for so far, this program's or an earlier one's;
        ``None`` where the platform does not report it.
    """

    wall_seconds: float
    cpu_seconds: float | None
    max_memory_mb: float | None

    def combined(self, other: "ProgramUsage") -> "ProgramUsage":
        """Return the usage of this run and `other` together."""
        cpu = (
            None
            if self.cpu_seconds is None or other.cpu_seconds is None
            else self.cpu_seconds + other.cpu_seconds
        )
        memories = [
            m for m in (self.max_memory_mb, other.max_memory_mb) if m is not None
        ]
        return ProgramUsage(
            wall_seconds=self.wall_seconds + other.wall_seconds,
            cpu_seconds=cpu,
            max_memory_mb=max(memories) if memories else None,
        )

    def recorded(self) -> dict[str, float]:
        """Return the CPU time and peak memory as manifest values, the unknown left out."""
        record = {}
        if self.cpu_seconds is not None:
            record["cpu_seconds"] = round(self.cpu_seconds, 3)
        if self.max_memory_mb is not None:
            record["max_memory_mb"] = round(self.max_memory_mb, 1)
        return record


def _children_usage() -> tuple[float, int] | None:
    """Return the CPU seconds and peak resident size of the processes waited for so far."""
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime, usage.ru_maxrss


def run_program(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    log_path: Path,
    timeout: float | None = None,
) -> ProgramUsage:
    """Run `command` in `cwd`, appending a line naming it and its output to `log_path`.

    Parameters
    ----------
    command : sequence of str or path-like
        The program and its arguments.
    cwd : Path
        Directory the program runs in.
    log_path : Path
        File that receives the program's standard output and error.
    timeout : float or None, optional
        Seconds the program may run; ``None`` sets no limit. At the limit, the
        program and every process it started are stopped.

    Returns
    -------
    ProgramUsage
        The wall time, CPU time and peak memory of the run.

    Raises
    ------
    ValueError
        If `timeout` is negative.
    ProgramError
        If the program exits with a failing status or is still running at the
        time limit; the message ends with the last lines of `log_path`.
    """
    if timeout is not None and timeout < 0:
        raise ValueError(f"timeout must not be negative, got {timeout}")
    arguments = [os.fspath(part) for part in command]
    name = Path(arguments[0]).name
    started = time.monotonic()
    before = _children_usage()
    with log_path.open("a", encoding="utf-8") as stream:
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
                f"{name} was stopped at the time limit\n{log_tail(log_path)}"
            ) from None
        except BaseException:
            stop_process(process)
            raise
    if returncode != 0:
        raise ProgramError(
            f"{name} exited with status {returncode}\n{log_tail(log_path)}"
        )
    wall = time.monotonic() - started
    after = _children_usage()
    if before is None or after is None:
        return ProgramUsage(wall_seconds=wall, cpu_seconds=None, max_memory_mb=None)
    return ProgramUsage(
        wall_seconds=wall,
        cpu_seconds=after[0] - before[0],
        max_memory_mb=after[1] * _MAXRSS_BYTES / 2**20,
    )


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


def log_tail(log_path: Path, lines: int = _LOG_TAIL_LINES) -> str:
    """Return the last `lines` lines of `log_path`, headed by its path."""
    text = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return f"Last lines of {log_path}:\n" + "\n".join(text[-lines:])
