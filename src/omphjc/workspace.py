"""A directory that a run works in, and how every run clears and seals it.

A workspace carries a stamp (:mod:`omphjc.stamps`). The stamp names the
purpose of the workspace and the process it serves.

When a run ends, it seals its artifacts. Only a hard kill prevents the seal.
A later run deletes an artifact only when the artifact was sealed and nothing
in it has changed since. Anything else that a run may have left is moved into
``omphjc-set-aside/`` with its contents. This happens, for example, when a run
was killed before it could seal its artifacts. Nothing else in the directory
is ever touched.

:class:`Workspace` implements these rules and nothing more. A subclass names
its purpose and what a run makes, and it adds the steps of its run.

:class:`ProgramWorkspace` adds an external program, which a subclass also
names in class attributes. The class holds:

- the program file;
- the time that the runs of the program may take;
- the log that the runs append to;
- what the runs took.

:class:`omphjc.tools.madgraph.driver.MadGraphWorkspace` is one such subclass.

A run returns a record. The record derives from :class:`Run`, or from
:class:`ProgramRun` when the run is of an external program. These two classes
carry the fields that every run shares, and the record of a driver adds its
own fields.
"""

import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class Run:
    """The output of one run: the file it is for and what it set aside.

    The run record of a driver derives from this class and adds its own
    fields. When the run is of an external program, the record derives from
    :class:`ProgramRun` instead.

    Parameters
    ----------
    output_path : Path
        The file the run is for.
    set_aside : Path or None
        Folder in the working directory that holds what an earlier run left
        and this run could not confirm as its own. This run moved it there
        instead of deleting it. It is ``None`` when nothing was set aside.
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
    """The directory of one process's runs for one purpose.

    The directory is stamped, cleared and sealed. A subclass does the
    following:

    - It names its purpose in the class attribute below.
    - It lists what a run makes in :attr:`artifacts`.
    - It adds the steps of its run, each inside
      ``with workspace.sealed_run():``.

    Parameters
    ----------
    process_name : str
        The process whose runs the directory holds. The stamp names it.
    workdir : Path
        The working directory. :meth:`sealed_run` creates it when it is
        missing. It must not be a filesystem root.

    Attributes
    ----------
    process_name : str
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

    def __init__(self, process_name: str, workdir: Path) -> None:
        self.process_name = process_name
        self.workdir = working_directory(workdir)
        self.details = {"process": process_name}

    @property
    @abstractmethod
    def artifacts(self) -> list[str]:
        """What a run makes in the directory, as POSIX paths relative to it."""

    @contextmanager
    def sealed_run(self) -> Iterator[Path | None]:
        """Make the directory ready for the run in the block, and seal it after.

        On entry, the method does the following, in this order:

        - It clears what an earlier run left (:meth:`clear_earlier_run`).
          This comes first, so that a directory the run must not touch is
          refused before anything is created.
        - It creates the directory when the directory is missing.
        - It stamps the directory when the directory carries no stamp.

        On exit, the method records in the stamp what the run made. It does
        so whether the block ended normally or with an exception. A later run
        can then tell whether anyone has changed these artifacts since.

        Entering the block removes what an earlier run left. Anything that
        the caller can refuse, such as an occupied output or an invalid
        request, therefore belongs before the block.

        Yields
        ------
        Path or None
            The folder that holds what was moved aside, or ``None`` when
            nothing was moved aside.

        Raises
        ------
        StampError
            For the reasons that :meth:`clear_earlier_run` gives. Nothing is
            created in that case.
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
            Artifacts to move aside even when they are sealed and unchanged,
            because they lack a sign that the run leaves.

        Returns
        -------
        Path or None
            The folder that holds what was moved aside, or ``None`` when
            nothing was moved aside.

        Raises
        ------
        StampError
            If the directory is in one of these states:

            - it is stamped for another purpose or other details;
            - it holds artifacts of a run but carries no stamp;
            - it holds something other than a stamp where the stamp belongs.

            Nothing is changed in that case.
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

    A subclass names its program in the class attributes below, in the way it
    names its purpose for :class:`Workspace`. It also adds what its run makes
    to :attr:`artifacts`.

    Parameters
    ----------
    process_name, workdir
        The same as for :class:`Workspace`.
    program_path : Path or None
        The program file to use instead of the one on PATH.
    timeout : float or None
        Seconds the run may take, counted from the creation of the workspace.
        ``None`` sets no limit.
    log_dir : Path or None, optional
        An existing directory for the log. With ``None``, the default, the
        log is kept in `workdir` and is one of the artifacts of the run.

        A log in another directory is not an artifact, so a later run in
        `workdir` leaves it in place.

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
        process_name: str,
        workdir: Path,
        *,
        program_path: Path | None,
        timeout: float | None,
        log_dir: Path | None = None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        super().__init__(process_name, workdir)
        self.log_dir = log_dir
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
        return (self.workdir if self.log_dir is None else self.log_dir) / self.log_name

    @property
    def artifacts(self) -> list[str]:
        """The log, when it is in the directory; a subclass adds what its run makes."""
        return [self.log_name] if self.log_dir is None else []

    def run(
        self, command: Sequence[str | os.PathLike[str]], *, failure_message: str
    ) -> ProgramUsage:
        """Run `command` in the directory, appending its output to the log.

        Parameters
        ----------
        command : sequence of str or path-like
            The program and its arguments.
        failure_message : str
            How a failure is described, for example
            ``"MadGraph failed running launch.mg5"``. The error of the
            program follows it.

        Returns
        -------
        ProgramUsage
            What this run took. It is also added to `usage`.

        Raises
        ------
        ProgramError
            If the program exits with a failing status or is still active at
            the deadline. The error is of the workspace's `error_type`.
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
        """Return an error of the workspace's type with `message` and the log's end."""
        return self.error_type(f"{message}\n{log_tail(self.log_path)}")
