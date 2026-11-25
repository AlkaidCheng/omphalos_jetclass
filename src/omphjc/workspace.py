"""Working directories for the runs of the tools.

- :class:`Workspace` prepares a directory for one run and records what the
  run made.
- :class:`ProgramWorkspace` is the base class of a tool's driver, which runs
  the tool's program in a workspace.
- :class:`Run` is what a driver returns after a run.
"""

import os
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from omphjc.data_files import Card, FileRecord
from omphjc.programs import ProgramError, ProgramSession, ProgramUsage, find_program
from omphjc.safe_paths import working_directory
from omphjc.stamps import clear_artifacts, read_stamp, seal, write_stamp

LOG_NAME = "run.log"
"""The file name of the log of a run that is given no other place for it."""


@dataclass(frozen=True, kw_only=True)
class Run:
    """What a driver returns after a run.

    Each driver has a subclass of its own with more fields. A driver that
    runs an external program derives its class from :class:`ProgramRun`.

    Parameters
    ----------
    output_path : Path
        The main file that the run made, such as its event file.
    set_aside : Path or None
        The folder that holds the files the run moved out of its way, or
        ``None`` when it moved none. A run deletes only what an earlier run
        made and left unchanged. Anything else found where the run writes,
        such as a file that changed after its run ended or one that a
        killed run left, is moved into a new folder under
        ``omphjc-set-aside/`` (:class:`Workspace`).
    cards : Mapping[str, FileRecord]
        The record of each card that the run used, by the name of the card
        (:meth:`ProgramWorkspace.card_records`). A card is an input file that
        configures the run's program.
    """

    output_path: Path
    set_aside: Path | None = None
    cards: Mapping[str, FileRecord] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ProgramRun(Run):
    """What a driver returns after a run of an external program.

    Parameters
    ----------
    log_path : Path
        The log file of the run's programs.
    usage : ProgramUsage
        The wall time and CPU time that the run's programs took in total, and
        their peak memory.
    """

    log_path: Path
    usage: ProgramUsage


class Workspace:
    """A working directory for one run of a tool.

    A run happens inside ``with workspace.sealed_run(...):``. In the block,
    the programs of the run (:attr:`programs`) run in the directory and write
    their output to one log file. A workspace is used for one run, and
    creating it changes nothing on disk.

    A later run can use the same directory again. When it starts, its
    workspace clears the paths that the run is about to write:

    - A file or folder that the earlier run made, and that has not changed
      since, is deleted.
    - Anything else found at those paths, such as a file that changed
      after its run ended or one that a killed run left, is moved into a
      new folder under ``omphjc-set-aside/`` (:attr:`set_aside_dir`). It
      stays there until someone deletes it.
    - The rest of the directory is left alone.

    The workspace knows what the earlier run made from the stamp, a small
    file that it keeps in the directory (:mod:`omphjc.stamps`). The stamp also
    records what the directory is used for and which process it belongs to.

    Parameters
    ----------
    workdir : Path
        The working directory. :meth:`sealed_run` creates it if it does not
        exist. It must not be a filesystem root.
    process_name : str
        The name of the process that the directory belongs to. It is written
        in the stamp.
    log_path : Path or None, optional
        The file that the programs of the run write their output to. Its
        directory must exist, and a later run leaves the file in place. By
        default the log is ``run.log`` in `workdir`, where a later run
        replaces it.

    Attributes
    ----------
    workdir : Path
        The working directory, as an absolute path.
    process_name : str
    log_path : Path
        The log file of the run's programs.
    programs : ProgramSession
        Runs the programs of the run in `workdir` and writes their output to
        `log_path`.
    set_aside_dir : Path or None
        The folder under ``omphjc-set-aside/`` that holds what
        :meth:`sealed_run` found at the run's paths and did not delete. It
        is ``None`` before the run, and when nothing was moved.

    Raises
    ------
    ValueError
        If `workdir` is a filesystem root.
    """

    def __init__(
        self,
        workdir: Path,
        *,
        process_name: str,
        log_path: Path | None = None,
    ) -> None:
        self.workdir = working_directory(workdir)
        self.process_name = process_name
        self.log_path = self.workdir / LOG_NAME if log_path is None else log_path
        self.programs = ProgramSession(self.workdir, self.log_path)
        self.set_aside_dir: Path | None = None
        self._log_is_artifact = log_path is None
        self._entered = False

    @contextmanager
    def sealed_run(
        self,
        purpose: str,
        artifacts: Sequence[str],
        *,
        unconfirmed: Iterable[str] = (),
        timeout: float | None = None,
    ) -> Iterator[None]:
        """Prepare the directory for a run and record what the run makes.

        Use it as ``with workspace.sealed_run(purpose, artifacts):`` and do
        the work of the run inside the block. The programs of the run can be
        started only there.

        When the block starts, the method:

        1. clears the paths in `artifacts`, and the log if it is kept in the
           directory, as the class description explains;
        2. creates the directory if it does not exist;
        3. writes the stamp if the directory has none.

        When the block ends, even if it raises, the method records in the
        stamp what the run made. A later run uses this record to tell whether
        a file has changed.

        Entering the block deletes files of an earlier run. Validate everything
        that could stop the run, such as an occupied output or an invalid
        request, before entering it.

        Parameters
        ----------
        purpose : str
            What the directory is used for. It is written in the stamp.
        artifacts : sequence of str
            The files and folders that the run makes in the directory, as
            POSIX paths relative to it. The log is not listed.
        unconfirmed : iterable of str, optional
            The paths in `artifacts` to move aside instead of deleting, even
            when they have not changed. List a path here when nothing in it
            shows that an earlier run finished making it.
        timeout : float or None, optional
            The time limit of the run's programs, in seconds from the start
            of the block. ``None`` sets no limit.

        Raises
        ------
        ValueError
            If `timeout` is not positive, or a path in `artifacts` contains a
            name that is not plain
            (:func:`~omphjc.safe_paths.require_plain_name`).
        RuntimeError
            If the workspace was already used for a run.
        StampError
            If the directory cannot be used for this run, in one of these
            cases:

            - its stamp names another purpose or another process;
            - it holds one of `artifacts` but has no stamp;
            - something other than a stamp is in the stamp's place.

            Nothing is changed in that case.
        OSError
            If the directory cannot be created or written to, for example
            for lack of permission.
        """
        if self._entered:
            raise RuntimeError(
                f"The workspace of {self.workdir} holds one run and was entered before"
            )
        with self.programs.opened(timeout):
            self._entered = True
            artifacts = [
                *artifacts,
                *([LOG_NAME] if self._log_is_artifact else []),
            ]
            details = {"process": self.process_name}
            self.set_aside_dir = clear_artifacts(
                self.workdir,
                artifacts,
                purpose,
                details=details,
                unconfirmed=unconfirmed,
            )
            self.workdir.mkdir(parents=True, exist_ok=True)
            if read_stamp(self.workdir) is None:
                write_stamp(self.workdir, purpose, details)
            try:
                yield
            finally:
                seal(self.workdir, artifacts)


class ProgramWorkspace:
    """Base class for running one tool's program in a :class:`Workspace`.

    A subclass describes its tool in the class attributes below and lists
    the files that its run makes in :attr:`artifacts`. Each step of a run is
    a method of the subclass, to be called inside
    ``with workspace.sealed_run():``.

    Parameters
    ----------
    process_name : str
        The name of the process that the directory belongs to. It is written
        in the stamp.
    workdir : Path
        The working directory. :class:`Workspace` states which directories
        it refuses.
    program_path : Path or None
        The program file to run. With ``None``, the program is looked up on
        PATH.
    timeout : float or None
        The time limit of the run's programs, in seconds from the start of
        :meth:`sealed_run`. ``None`` sets no limit.
    log_path : Path or None, optional
        See the `log_path` parameter of :class:`Workspace`.

    Attributes
    ----------
    program_path : Path
        The program file that the run uses.
    timeout : float or None

    Raises
    ------
    ValueError
        If `workdir` is not a valid working directory (:class:`Workspace`).
    FileNotFoundError
        If `program_path` is not a file, or it is ``None`` and the program is
        not on PATH.
    """

    purpose: ClassVar[str]
    """What the directory is used for. It is written in the stamp."""

    program: ClassVar[str]
    """The program's name on PATH."""

    description: ClassVar[str]
    """The name of the program in messages, such as ``"MadGraph's bin/mg5_aMC"``."""

    card_classes: ClassVar[tuple[type[Card], ...]] = ()
    """The classes of the tool's cards. Each one names its card and its file."""

    def __init__(
        self,
        process_name: str,
        workdir: Path,
        *,
        program_path: Path | None,
        timeout: float | None,
        log_path: Path | None = None,
    ) -> None:
        self._workspace = Workspace(
            workdir, process_name=process_name, log_path=log_path
        )
        self.program_path = find_program(
            self.program, program_path, description=self.description
        )
        self.timeout = timeout

    @property
    def workdir(self) -> Path:
        """The working directory, as an absolute path."""
        return self._workspace.workdir

    @property
    def process_name(self) -> str:
        """The name of the process that the directory belongs to."""
        return self._workspace.process_name

    @property
    def log_path(self) -> Path:
        """The path of the log file of the run's programs."""
        return self._workspace.log_path

    @property
    def usage(self) -> ProgramUsage:
        """Wall time, CPU time and peak memory of the run's programs so far."""
        return self._workspace.programs.usage

    @property
    def cards_dir(self) -> Path:
        """The directory that holds the cards of a run.

        It is the working directory. A subclass overrides the property when
        its program keeps the cards in another folder.
        """
        return self.workdir

    @property
    def artifacts(self) -> list[str]:
        """The files and folders that a run makes in the directory, without the log.

        Each one is a POSIX path relative to the working directory. The base
        class lists the card files when the cards are kept in the working
        directory. A subclass adds everything else that its run makes, and the
        folder of its cards when it keeps them in another one.
        """
        if self.cards_dir != self.workdir:
            return []
        return [card_class.file_name for card_class in self.card_classes]

    @property
    def unconfirmed_artifacts(self) -> list[str]:
        """The artifacts that a run moves aside instead of deleting.

        A run moves them aside even when they have not changed since an
        earlier run. The base class lists none. A subclass lists an artifact
        here when nothing in it shows that an earlier run finished making it.
        """
        return []

    def card_records(self) -> dict[str, FileRecord]:
        """Return the record of each card in :attr:`cards_dir`, by the name of the card.

        A record holds the fingerprint of the card's content as the program
        reads it (:meth:`Card.record_file`). A card whose file does not exist
        is left out.
        """
        return {
            card_class.card_name: card_class.record_file(path)
            for card_class in self.card_classes
            if (path := self.cards_dir / card_class.file_name).is_file()
        }

    @contextmanager
    def sealed_run(self) -> Iterator[Path | None]:
        """Prepare the directory for a run and record what the run makes.

        Use it as a ``with`` block and call the steps of the run inside it
        (:meth:`Workspace.sealed_run`).

        Yields
        ------
        Path or None
            The folder that holds what was moved out of the run's way
            (:attr:`Workspace.set_aside_dir`), or ``None`` when nothing was
            moved.
        """
        with self._workspace.sealed_run(
            self.purpose,
            self.artifacts,
            unconfirmed=self.unconfirmed_artifacts,
            timeout=self.timeout,
        ):
            yield self._workspace.set_aside_dir

    def run(
        self, command: Sequence[str | os.PathLike[str]], *, failure_message: str
    ) -> ProgramUsage:
        """Run `command` in the directory and add its output to the log.

        See :meth:`omphjc.programs.ProgramSession.run`.
        """
        return self._workspace.programs.run(command, failure_message=failure_message)

    def make_error(self, message: str) -> ProgramError:
        """Return an error with `message` and the last lines of the log."""
        return self._workspace.programs.make_error(message)
