"""A directory an external program runs in, and the care every run takes there.

A workspace carries a stamp (:mod:`omphjc.stamps`) naming its purpose and
details, such as the process it serves. When a run ends, short of a hard
kill, it seals its artifacts. A later run deletes an artifact only when it
was sealed and nothing in it changed since; anything else a run may have left,
as after a kill before sealing, is moved into ``omphjc-set-aside/`` with its
contents. Nothing else in the directory is ever touched.

A subclass names the program, the purpose, the log and the artifacts a run
makes, and adds the steps of its program's run;
:class:`omphjc.madgraph.MadGraphWorkspace` is one.
"""

import os
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar

from omphjc.programs import (
    ProgramError,
    ProgramUsage,
    find_program,
    log_tail,
    run_program,
)
from omphjc.safe_paths import working_directory
from omphjc.stamps import clear_artifacts, read_stamp, seal, write_stamp


class Workspace:
    """The working directory of one external program's runs.

    Parameters
    ----------
    workdir : Path
        The working directory, created by :meth:`prepare` when missing; it
        must not be a filesystem root.
    program : str
        The program's name on PATH.
    program_path : Path or None
        The program file to run instead of the one on PATH.
    description : str
        How the program is called in messages, for example
        ``"MadGraph's bin/mg5_aMC"``.
    purpose : str
        What the directory is used for, written in its stamp.
    details : Mapping[str, str]
        Details of the purpose written in the stamp, for example the process.
    log_name : str
        Name of the log file in the directory.
    timeout : float or None
        Seconds the run may take from now; ``None`` sets no limit.

    Attributes
    ----------
    workdir : Path
        The working directory, normalized.
    program_path : Path
        The program file the run uses.
    deadline : float or None
        ``time.monotonic`` value at which a running program is stopped.
    usage : ProgramUsage
        What the program's runs in this workspace took so far, combined.

    Raises
    ------
    ValueError
        If `timeout` is not positive or `workdir` is a filesystem root.
    FileNotFoundError
        If `program_path` is not a file, or none is given and PATH has no
        `program`.
    """

    error_type: ClassVar[type[ProgramError]] = ProgramError
    """The exception a failed run raises; a subclass names its own."""

    def __init__(
        self,
        workdir: Path,
        *,
        program: str,
        program_path: Path | None,
        description: str,
        purpose: str,
        details: Mapping[str, str],
        log_name: str,
        timeout: float | None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        self.workdir = working_directory(workdir)
        self.program_path = find_program(program, program_path, description=description)
        self.purpose = purpose
        self.details = dict(details)
        self.deadline = None if timeout is None else time.monotonic() + timeout
        self.usage = ProgramUsage(wall_seconds=0.0, cpu_seconds=0.0, max_memory_mb=None)
        self._log_name = log_name

    @property
    def artifacts(self) -> list[str]:
        """What a run makes in the directory, as POSIX paths relative to it."""
        raise NotImplementedError

    @property
    def log_path(self) -> Path:
        """The program's output for the run."""
        return self.workdir / self._log_name

    def prepare(self, *, unconfirmed: Iterable[str] = ()) -> Path | None:
        """Make the directory ready for a run.

        Clears what an earlier run left (:meth:`clear_earlier_run`) first, so
        that a directory the program must not touch is refused before anything
        is created; then creates the directory when it is missing and stamps
        it when it carries no stamp.

        Parameters
        ----------
        unconfirmed : iterable of str, optional
            Passed to :meth:`clear_earlier_run`.

        Returns
        -------
        Path or None
            The folder holding what was moved aside, ``None`` when nothing was.

        Raises
        ------
        StampError
            As :meth:`clear_earlier_run`; nothing is created in that case.
        """
        set_aside = self.clear_earlier_run(unconfirmed=unconfirmed)
        self.workdir.mkdir(parents=True, exist_ok=True)
        if read_stamp(self.workdir) is None:
            write_stamp(self.workdir, self.purpose, self.details)
        return set_aside

    def clear_earlier_run(self, *, unconfirmed: Iterable[str] = ()) -> Path | None:
        """Clear what an earlier run left in the directory, and nothing else.

        Parameters
        ----------
        unconfirmed : iterable of str, optional
            Artifacts to move aside however they were sealed, because they
            lack a sign the program's run leaves.

        Returns
        -------
        Path or None
            The folder holding what was moved aside, ``None`` when nothing was.

        Raises
        ------
        StampError
            If the directory is stamped for another purpose or details, holds
            what a run makes without a stamp, or holds something other than a
            stamp in the stamp's place. Nothing is changed in that case.
        """
        return clear_artifacts(
            self.workdir,
            self.artifacts,
            self.purpose,
            details=self.details,
            unconfirmed=unconfirmed,
        )

    def run(
        self, command: Sequence[str | os.PathLike[str]], *, failure_message: str
    ) -> ProgramUsage:
        """Run `command` in the directory, appending its output to the log.

        Parameters
        ----------
        command : sequence of str or path-like
            The program and its arguments.
        failure_message : str
            How a failure is described, for example ``"MadGraph failed
            running launch.mg5"``; the program's error follows it.

        Returns
        -------
        ProgramUsage
            What this run took; `usage` accumulates it.

        Raises
        ------
        ProgramError
            Of the workspace's `error_type`, if the program exits with a
            failing status or is still running at the deadline.
        """
        timeout = (
            None
            if self.deadline is None
            else max(self.deadline - time.monotonic(), 0.0)
        )
        try:
            usage = run_program(
                command,
                cwd=self.workdir,
                log_path=self.log_path,
                timeout=timeout,
            )
        except ProgramError as error:
            raise self.error_type(f"{failure_message}: {error}") from error
        self.usage = self.usage.combined_with(usage)
        return usage

    def seal_artifacts(self) -> None:
        """Record in the stamp what this run made, for later runs to compare with."""
        seal(self.workdir, self.artifacts)

    def make_error(self, message: str) -> ProgramError:
        """Return an error of the workspace's type carrying `message` and the log's end."""
        return self.error_type(f"{message}\n{log_tail(self.log_path)}")
