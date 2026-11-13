"""Run external programs such as MadGraph and DelphesPythia8.

A program is started with its input closed, and its output is appended to a
log file. The program leads a process group of its own. Stopping the program
at a time limit or on an interrupt therefore also stops every process that it
started, such as MadGraph's parallel jobs.
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

# The soft limit on open files under an unlimited hard limit: MadGraph reads an
# unlimited soft limit as 2500 channel directories (do_combine_events,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/madevent_interface.py#L3913-L3914),
# so a finite one is set, macOS's OPEN_MAX from
# https://github.com/apple-oss-distributions/xnu/blob/xnu-12377.121.6/bsd/sys/syslimits.h#L108.
_OPEN_MAX = 10240

_LOG_TAIL_LINES = 20


class ProgramError(RuntimeError):
    """An external program failed or ran past its time limit."""


def available_cores() -> int:
    """Return the number of CPUs this process may run on.

    On Linux this is the CPU affinity of the process. A batch system such as
    Slurm restricts the affinity to the allocation of the job. On other
    platforms the number counts every CPU of the machine.
    """
    if sys.platform == "linux":
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


class RaisedOpenFileLimit:
    """Raise the soft limit on open files to the hard limit within a ``with`` block.

    Programs started in the block inherit the raised limit. When the hard
    limit is unlimited, the soft limit becomes 10240, which is macOS's
    ``OPEN_MAX``.

    The limit is left unchanged in these cases:

    - The soft limit is already that high or unlimited.
    - The system refuses the change.
    - The platform has no resource limits.

    Parameters
    ----------
    enabled : bool, optional
        Whether to raise the limit. When false, the limit is left unchanged
        in the block.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._replaced: tuple[int, int] | None = None

    def __enter__(self) -> None:
        if not self.enabled or resource is None:
            return
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = _OPEN_MAX if hard == resource.RLIM_INFINITY else hard
        # RLIM_INFINITY is -1 on Linux, so it is compared for equality.
        if soft != resource.RLIM_INFINITY and soft < target:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
                self._replaced = (soft, hard)

    def __exit__(self, *exc_info: object) -> None:
        if self._replaced is not None:
            resource.setrlimit(resource.RLIMIT_NOFILE, self._replaced)
            self._replaced = None


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
    """The time and memory that one run of an external program took.

    Parameters
    ----------
    wall_seconds : float
        Time from the program's start to its exit.
    cpu_seconds : float or None
        User and system CPU time of the program and of every process that
        the program waited for. MadGraph's parallel jobs are therefore
        counted. It is ``None`` on a platform that does not report it.
    peak_memory_mib : float or None
        Peak resident memory, in MiB, of the largest process that this Python
        process has waited for so far. That process may belong to this
        program or to a program started earlier. It is ``None`` on a
        platform that does not report it.
    """

    wall_seconds: float
    cpu_seconds: float | None
    peak_memory_mib: float | None

    def combined_with(self, other: "ProgramUsage") -> "ProgramUsage":
        """Return the usage of this run and `other` together."""
        cpu = (
            None
            if self.cpu_seconds is None or other.cpu_seconds is None
            else self.cpu_seconds + other.cpu_seconds
        )
        memories = [
            m for m in (self.peak_memory_mib, other.peak_memory_mib) if m is not None
        ]
        return ProgramUsage(
            wall_seconds=self.wall_seconds + other.wall_seconds,
            cpu_seconds=cpu,
            peak_memory_mib=max(memories) if memories else None,
        )

    def as_record(self) -> dict[str, float]:
        """Return the CPU time and peak memory as values for a record.

        A value that is unknown is left out.
        """
        record = {}
        if self.cpu_seconds is not None:
            record["cpu_seconds"] = round(self.cpu_seconds, 3)
        if self.peak_memory_mib is not None:
            record["peak_memory_mib"] = round(self.peak_memory_mib, 1)
        return record


def _children_usage() -> tuple[float, int] | None:
    """Return the CPU seconds and the peak resident size of the child processes.

    The values cover every process that this process has waited for so far.
    """
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
    """Run `command` in `cwd` and append its output to `log_path`.

    A line that names the command is appended to the log before the output.

    Parameters
    ----------
    command : sequence of str or path-like
        The program and its arguments.
    cwd : Path
        Directory the program runs in.
    log_path : Path
        File that receives the program's standard output and error.
    timeout : float or None, optional
        Seconds the program may take. ``None`` sets no limit. At the limit,
        the program and every process it started are stopped.

    Returns
    -------
    ProgramUsage
        The wall time, CPU time and peak memory of the run.

    Raises
    ------
    ValueError
        If `timeout` is negative.
    ProgramError
        If the program exits with a failing status or is still active at the
        time limit. The message ends with the last lines of `log_path`.
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
        return ProgramUsage(wall_seconds=wall, cpu_seconds=None, peak_memory_mib=None)
    return ProgramUsage(
        wall_seconds=wall,
        cpu_seconds=after[0] - before[0],
        peak_memory_mib=after[1] * _MAXRSS_BYTES / 2**20,
    )


def stop_process(process: subprocess.Popen[Any]) -> None:
    """Kill `process` and reap it.

    When `process` leads a process group, every process of the group is
    killed too. A process started with ``start_new_session=True`` leads its
    own group, and the group holds the processes that it started.
    :func:`run_program` starts its program in this way.
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
