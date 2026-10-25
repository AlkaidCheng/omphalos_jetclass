"""A directory a run works in, and the care every run takes there.

A workspace carries a stamp (:mod:`omphjc.stamps`) naming its purpose and the
process it serves. When a run ends, short of a hard kill, it seals its
artifacts. A later run deletes an artifact only when it was sealed and nothing
in it changed since; anything else a run may have left, as after a kill before
sealing, is moved into ``omphjc-set-aside/`` with its contents. Nothing else in
the directory is ever touched.

:class:`Workspace` is that care alone: a subclass names its purpose and what a
run makes, and adds the steps of its run. :class:`ProgramWorkspace` adds an
external program, named in class attributes too: the program file, the time
its runs may take, the log they append to and what they took.
:class:`omphjc.madgraph.MadGraphWorkspace` is one.

A run returns a record deriving from :class:`Run`, or from :class:`ProgramRun`
when an external program ran, which carry the fields every run shares; a
driver's record adds its own.
"""

import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.processes.catalogue import ProcessSpec
from omphjc.programs import (
    ProgramError,
    ProgramUsage,
    find_program,
    log_tail,
    run_program,
)
from omphjc.safe_paths import working_directory
from omphjc.stamps import clear_artifacts, read_stamp, seal, write_stamp


@dataclass(frozen=True, kw_only=True)
class Run:
    """The output of one run: the file it is for and what it set aside.

    A driver's run record derives from this class, or from :class:`ProgramRun`
    when the run is of an external program, and adds its own fields.

    Parameters
    ----------
    output_path : Path
        The file the run is for.
    set_aside : Path or None
        Folder in the working directory holding what an earlier run left and
        this run could not confirm as its own, moved there rather than deleted;
        ``None`` when nothing was set aside.
    """

    output_path: Path
    set_aside: Path | None = None


@dataclass(frozen=True, kw_only=True)
class ProgramRun(Run):
    """The output of one run of an external program, with its log and usage.

    Parameters
    ----------
    log_path : Path
        The program's output for the run.
    usage : ProgramUsage
        Wall time, CPU time and peak memory of the program's runs in the working
        directory, combined.
    """

    log_path: Path
    usage: ProgramUsage


class Workspace(ABC):
    """The directory of one process's runs for one purpose: stamped, cleared and sealed.

    A subclass names its purpose in the class attribute below, lists what a
    run makes in :attr:`artifacts` and adds the steps of its run, each inside
    ``with workspace.sealed_run():``.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds; its name goes in the stamp.
    workdir : Path
        The working directory, created by :meth:`sealed_run` when missing; it
        must not be a filesystem root.

    Attributes
    ----------
    spec : ProcessSpec
    workdir : Path
        The working directory, normalized.
    details : dict[str, str]
        Details of the purpose written in the stamp: the process's name.

    Raises
    ------
    ValueError
        If `workdir` is a filesystem root.
    """

    purpose: ClassVar[str]
    """What the directory is used for, written in its stamp."""

    def __init__(self, spec: ProcessSpec, workdir: Path) -> None:
        self.spec = spec
        self.workdir = working_directory(workdir)
        self.details = {"process": spec.name}

    @property
    @abstractmethod
    def artifacts(self) -> list[str]:
        """What a run makes in the directory, as POSIX paths relative to it."""

    @contextmanager
    def sealed_run(self) -> Iterator[Path | None]:
        """Make the directory ready for the run in the block, and seal it after.

        On entry, clears what an earlier run left (:meth:`clear_earlier_run`)
        first, so that a directory the run must not touch is refused before
        anything is created; then creates the directory when it is missing
        and stamps it when it carries no stamp. On exit, however the block
        ended, records in the stamp what the run made, so that a later run can
        tell whether anyone changed it since. Anything the caller can refuse,
        an occupied output or an invalid request, belongs before the block,
        since entering it removes what an earlier run left.

        Yields
        ------
        Path or None
            The folder holding what was moved aside, ``None`` when nothing was.

        Raises
        ------
        StampError
            As :meth:`clear_earlier_run`; nothing is created in that case.
        """
        set_aside = self.clear_earlier_run()
        self.workdir.mkdir(parents=True, exist_ok=True)
        if read_stamp(self.workdir) is None:
            write_stamp(self.workdir, self.purpose, self.details)
        try:
            yield set_aside
        finally:
            seal(self.workdir, self.artifacts)

    def clear_earlier_run(self, *, unconfirmed: Iterable[str] = ()) -> Path | None:
        """Clear what an earlier run left in the directory, and nothing else.

        Parameters
        ----------
        unconfirmed : iterable of str, optional
            Artifacts to move aside however they were sealed, because they
            lack a sign the run leaves.

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


class ProgramWorkspace(Workspace):
    """The directory of one process's runs of one external program.

    A subclass names its program in the class attributes below, as it names
    its purpose and artifacts for :class:`Workspace`.

    Parameters
    ----------
    spec, workdir
        As :class:`Workspace`.
    program_path : Path or None
        The program file to run instead of the one on PATH.
    timeout : float or None
        Seconds the run may take from now; ``None`` sets no limit.

    Attributes
    ----------
    program_path : Path
        The program file the run uses.
    deadline : float or None
        ``time.monotonic`` value at which a running program is stopped.
    usage : ProgramUsage
        What the program's runs in this directory took so far, combined.

    Raises
    ------
    ValueError
        If `timeout` is not positive or `workdir` is a filesystem root.
    FileNotFoundError
        If `program_path` is not a file, or none is given and PATH has no
        `program`.
    """

    program: ClassVar[str]
    """The program's name on PATH."""
    description: ClassVar[str]
    """How the program is called in messages, for example ``"MadGraph's bin/mg5_aMC"``."""
    log_name: ClassVar[str]
    """Name of the log file in the directory."""
    error_type: ClassVar[type[ProgramError]] = ProgramError
    """The exception a failed run raises; a subclass names its own."""

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        program_path: Path | None,
        timeout: float | None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        super().__init__(spec, workdir)
        self.program_path = find_program(
            self.program, program_path, description=self.description
        )
        self.deadline = None if timeout is None else time.monotonic() + timeout
        self.usage = ProgramUsage(
            wall_seconds=0.0, cpu_seconds=0.0, peak_memory_mib=None
        )

    @property
    def log_path(self) -> Path:
        """The program's output for the run."""
        return self.workdir / self.log_name

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

    def make_error(self, message: str) -> ProgramError:
        """Return an error of the workspace's type carrying `message` and the log's end."""
        return self.error_type(f"{message}\n{log_tail(self.log_path)}")
