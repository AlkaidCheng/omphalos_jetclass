"""A job: one process and one job number, in a directory of its own.

::

    <outdir>/<process>/job_<n>/
      job.json           the process, the job number and the seed (omphjc.jobs.identity)
      manifest.json      an index of the tasks and their records (omphjc.jobs.manifest)
      <stage>/           one directory per task, named and laid out by its stage
        task.json        what the task ran with and what came out (omphjc.jobs.task)
        runs/<run_id>/   one directory per run of the task, with that run's log

The job number fixes the seed of every program the job runs
(:func:`job_seed`); ``docs/reproducibility.md`` lists what else a rerun's
events depend on. Paths are built from screened names (:mod:`omphjc.safe_paths`), so a
process name from a catalogue cannot place a job outside `outdir`.
"""

import hashlib
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any

from omphjc.comparison import Difference
from omphjc.jobs.identity import JobIdentity
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.task import (
    EventOutput,
    Task,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.safe_paths import inside, working_directory
from omphjc.stamps import SetAsideFolder, clear_set_aside_folders, set_aside_folders
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT

JOB_DIR_PREFIX = "job_"
RUNS_DIR = "runs"
"""The directory, in a task's directory, that holds one directory per run."""


class TerminationError(RuntimeError):
    """The process received a termination signal."""


class ReplacedRunError(RuntimeError):
    """A newer run of the task started before this one ended, so its end is not recorded."""


# What ends a run without its program or omphjc failing.
_INTERRUPTIONS = (TerminationError, KeyboardInterrupt)


TaskBody = Callable[[bool, Path], TaskOutcome]
"""Runs a task; the arguments say whether to replace what an earlier run left,
and give the directory of this run, where the program writes its log."""


def sha256(path: Path) -> str:
    """Return the SHA-256 of the file at `path`, as hexadecimal digits."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_seed(spec: ProcessSpec, job_id: int) -> int:
    """Return the seed of job `job_id` of `spec`: ``seed_offset + job_id``.

    MadGraph (``iseed``), Pythia (``Random:seed``) and Delphes (``RandomSeed``)
    all receive it.

    Raises
    ------
    ValueError
        If `job_id` is not positive or the seed exceeds Pythia's limit.
    """
    if job_id <= 0:
        raise ValueError(f"job_id must be positive, got {job_id}")
    seed = spec.seed_offset + job_id
    if seed > PYTHIA_SEED_LIMIT:
        raise ValueError(f"Seed {seed} exceeds Pythia's limit of {PYTHIA_SEED_LIMIT}")
    return seed


class Job:
    """One job of a process: its directory, its identity and the records of its tasks.

    Parameters
    ----------
    spec : ProcessSpec
        The process the job generates.
    outdir : Path
        Directory holding the jobs of every process.
    job_id : int
        Positive job number within the process.

    Attributes
    ----------
    spec : ProcessSpec
    job_id : int
    root_dir : Path
        The job directory, ``<outdir>/<process>/job_<n>``; created by the
        first stage that runs.
    seed : int
        The seed of every program the job runs. A stage that uses it records
        it among its parameters.
    identity : JobIdentity
        The process, the job number and the seed. The first task that runs
        writes it to ``job.json`` in the job directory.

    Raises
    ------
    ValueError
        If `job_id` is not positive, the seed exceeds Pythia's limit, `outdir`
        is a filesystem root, or the directory holds the ``job.json`` of
        another job.
    """

    def __init__(self, spec: ProcessSpec, outdir: Path, job_id: int) -> None:
        self.spec = spec
        self.job_id = job_id
        self.seed = job_seed(spec, job_id)
        self.root_dir = inside(
            working_directory(outdir), spec.name, f"{JOB_DIR_PREFIX}{job_id}"
        )
        self.identity = JobIdentity(process=spec.name, job_id=job_id, seed=self.seed)
        if self.identity_path.exists():
            self._check_identity()

    @property
    def identity_path(self) -> Path:
        return self.root_dir / JobIdentity.file_name

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / Manifest.file_name

    def task_dir(self, name: str) -> Path:
        """Return the directory of the task `name`, ``<root>/<name>``."""
        return inside(self.root_dir, name)

    def run_dir(self, name: str, run_id: str) -> Path:
        """Return the directory of run `run_id` of task `name`.

        It is ``<root>/<name>/runs/<run_id>``.
        """
        return inside(self.task_dir(name), RUNS_DIR, run_id)

    def relative_path(self, path: Path) -> str:
        """Return `path` as a POSIX path relative to the job directory."""
        return path.relative_to(self.root_dir).as_posix()

    def task_record_path(self, name: str) -> Path:
        """Return the file of the record of task `name`, ``<root>/<name>/task.json``."""
        return self.task_dir(name) / TaskRecord.file_name

    def task_record(self, name: str) -> TaskRecord | None:
        """Return the record of task `name`, or ``None`` when it has no record.

        Raises
        ------
        ValueError
            If the ``task.json`` of the task cannot be read as a record.
        """
        try:
            return TaskRecord.read(self.task_record_path(name), root_dir=self.root_dir)
        except FileNotFoundError:
            return None

    def task_names(self) -> list[str]:
        """Return the names of the tasks that have a record, in alphabetical order.

        A task has a record when its directory holds a ``task.json``. Only the
        directories directly inside the job directory are looked at.
        """
        record_paths = self.root_dir.glob(f"*/{TaskRecord.file_name}")
        return sorted(record_path.parent.name for record_path in record_paths)

    def task(self, name: str) -> Task:
        """Return the task `name` as it stands, by its record and its output files.

        The size of each output of a task recorded as done is compared with
        the size in the record. An output of another size is reported before
        a missing one.
        """
        record = self.task_record(name)
        if record is None or not record.is_done:
            return Task(name, TaskStatus.NOT_DONE, record=record)
        status, detail = TaskStatus.DONE, ""
        for output in record.outputs.values():
            try:
                n_bytes = output.path.stat().st_size
            except FileNotFoundError:
                status, detail = TaskStatus.MISSING_OUTPUT, f"{output.path} is missing"
                continue
            if n_bytes != output.n_bytes:
                status = TaskStatus.CHANGED
                detail = (
                    f"{output.path} holds {n_bytes} bytes, not the "
                    f"{output.n_bytes} the {name} stage recorded"
                )
                break
        return Task(name, status, detail, record)

    def require_done(self, name: str) -> TaskRecord:
        """Return the record of task `name`, which must be done with its outputs intact.

        Raises
        ------
        ValueError
            If the task is not done or an output is missing; the message names
            the command to run first. If an output has another size than
            recorded; the message names the file, both sizes and ``--force``.
        """
        task = self.task(name)
        if task.status is TaskStatus.CHANGED:
            raise ValueError(
                f"{task.detail}; run omphjc {name} with --force to regenerate "
                "the file"
            )
        if task.record is None or task.status is not TaskStatus.DONE:
            raise ValueError(
                f"The {name} stage of {self.root_dir} has not run to completion; "
                f"run omphjc {name} first"
            )
        return task.record

    def require_events(self, name: str) -> EventOutput:
        """Return the events task `name` made; it must be done with its outputs intact.

        Raises
        ------
        ValueError
            As :meth:`require_done` does, or if the task made no event file.
        """
        events = self.require_done(name).events
        if events is None:
            raise ValueError(f"The {name} stage of {self.root_dir} made no event file")
        return events

    def run_task(
        self,
        name: str,
        parameters: dict[str, Any],
        body: TaskBody,
        *,
        log_name: str | None = None,
        force: bool = False,
    ) -> TaskRecord:
        """Run task `name` through `body` unless its result can be kept; record it.

        A task recorded as done, with its outputs present and the same
        `parameters`, is kept. One recorded as done with other parameters, or
        with an output of another size than recorded, is refused unless
        `force` is set. One that failed, was interrupted or lost an output
        runs again, and the run is added to its record when `parameters` are
        the same; with other parameters, or under `force`, it runs as a new
        task with a new record. Either way `body` is told to replace what the
        earlier run left. The first task that runs creates the job directory
        with its ``job.json``. Each run gets a run ID and a directory,
        ``<root>/<name>/runs/<run_id>``, that `body` receives for the
        program's log. The record of the task, ``task.json`` in its
        directory, is written before `body` runs and after it returns or
        raises, so a failed or interrupted run records how far it got and
        where its log is. A run that ``SIGTERM`` or a keyboard interrupt ended
        is recorded as interrupted, and one that raised anything else as
        failed. How a run ended is written only while it is still the latest
        run in the record on disk.
        The manifest is written again after each of these writes.

        Parameters
        ----------
        name : str
            Name of the task, the name of its stage; its directory is
            ``<root>/<name>``.
        parameters : dict
            What the task is asked for, as JSON values.
        body : TaskBody
            Runs the task; receives whether to replace an earlier run's files
            and the directory of this run.
        log_name : str or None, optional
            The name of the file the task's program writes its log to in the
            directory of the run; ``None`` for a task without a log.
        force : bool, optional
            Run the task even when its result could be kept.

        Returns
        -------
        TaskRecord
            The record of the task, kept or new.

        Raises
        ------
        ValueError
            If the task is recorded as done with other parameters, or with an
            output of another size than recorded, and `force` is not set; the
            message names each parameter that differs. If the ``job.json`` of
            the directory identifies another job. If the ``task.json`` of a
            task of the job cannot be read as a record. If `log_name` is not
            a plain file name.
        FileNotFoundError
            If the ``job.json`` of the directory was removed while the task
            ran. The task is then not recorded.
        ReplacedRunError
            If a newer run of the task started before this one ended. The
            record of the newer run is left unchanged, and the end of this
            one is not recorded.
        Exception
            Whatever `body` raised, after the failure is recorded.
        """
        task = self.task(name)
        previous_record = task.record
        if previous_record is not None and previous_record.is_done and not force:
            self._check_parameters(name, previous_record.parameters, parameters)
            if task.status is TaskStatus.DONE:
                return previous_record
            if task.status is TaskStatus.CHANGED:
                raise ValueError(
                    f"{task.detail}; run omphjc {name} with --force to "
                    "regenerate the file"
                )
        overwrite = force or previous_record is not None
        clock = time.monotonic()
        self._record_identity()
        if previous_record is None or force or previous_record.parameters != parameters:
            record = TaskRecord.running(parameters)
        else:
            record = previous_record.rerun()
        run_dir = self.run_dir(name, record.latest_run.run_id)
        if log_name is not None:
            record = record.with_log(self.relative_path(inside(run_dir, log_name)))
        self._write_record(name, record)
        try:
            run_dir.mkdir(parents=True)
            outcome = body(overwrite, run_dir)
        except BaseException as error:
            message = str(error) or type(error).__name__
            if isinstance(error, _INTERRUPTIONS):
                self._write_run_end(name, record.interrupted(error=message))
            else:
                self._write_run_end(name, record.failed(error=message))
            raise
        record = record.done(
            outcome, wall_seconds=time.monotonic() - clock, root_dir=self.root_dir
        )
        self._write_run_end(name, record)
        return record

    def set_aside_folders(self) -> list[SetAsideFolder]:
        """Return what earlier runs of the job's tasks set aside, oldest first.

        A run that cannot confirm an artifact an earlier run left, as after a
        kill before sealing, moves it into ``<stage>/omphjc-set-aside/``
        rather than deleting it (:mod:`omphjc.stamps`). The folders stay until
        :meth:`clear_set_aside_folders` or the user deletes them.
        """
        found = [
            folder
            for name in self.task_names()
            for folder in set_aside_folders(self.task_dir(name))
        ]
        return sorted(found, key=lambda folder: (folder.created, folder.path))

    def clear_set_aside_folders(self) -> list[SetAsideFolder]:
        """Delete what earlier runs of the job's tasks set aside; return it.

        Raises
        ------
        StampError
            If a task directory holds set-aside folders but no stamp; nothing
            in that directory is changed.
        """
        removed = [
            folder
            for name in self.task_names()
            for folder in clear_set_aside_folders(self.task_dir(name))
        ]
        return sorted(removed, key=lambda folder: (folder.created, folder.path))

    def _record_identity(self) -> None:
        """Create the job directory with its ``job.json``, or check the one it holds."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.identity.create(self.identity_path)
        except FileExistsError:
            self._check_identity()

    def _check_identity(self) -> None:
        """Refuse a job directory whose ``job.json`` identifies another job."""
        recorded = JobIdentity.read(self.identity_path)
        differences = self.identity.differences(recorded)
        if differences:
            raise ValueError(
                "The current configuration is inconsistent with that of the "
                f"existing job in {self.root_dir} ({JobIdentity.file_name}):"
                + "".join(f"\n  {difference}" for difference in differences)
                + "\nRerun with the configuration the job was created with, or "
                "choose another output directory."
            )

    def _check_parameters(
        self, name: str, recorded: dict[str, Any], parameters: dict[str, Any]
    ) -> None:
        """Refuse `parameters` when task `name` ran with other ones.

        The message names each parameter that differs, a nested one by the
        dotted path of its keys, with the value the task ran with as expected.
        """
        if parameters == recorded:
            return
        differences = Difference.between_nested_mappings(parameters, recorded)
        record_path = self.relative_path(self.task_record_path(name))
        raise ValueError(
            "The current parameters are inconsistent with those of the existing "
            f"{name} task in {self.root_dir} ({record_path}):"
            + "".join(f"\n  {difference}" for difference in differences)
            + "\nRerun with the parameters the task ran with, or run omphjc "
            f"{name} with --force to replace its result."
        )

    def _write_run_end(self, name: str, record: TaskRecord) -> None:
        """Write `record`, which says how its latest run ended, for task `name`.

        Raises
        ------
        ReplacedRunError
            If the record on disk already holds a newer run of the task.
            That record is left unchanged.
        """
        run = record.latest_run
        recorded = self.task_record(name)
        if recorded is not None and recorded.latest_run.run_id != run.run_id:
            raise ReplacedRunError(
                f"Run {run.run_id!r} of the {name} task in {self.root_dir} is not "
                f"recorded as {run.status}: run {recorded.latest_run.run_id!r} of "
                "the task started before it ended"
            )
        self._write_record(name, record)

    def _write_record(self, name: str, record: TaskRecord) -> None:
        """Write `record` as the record of task `name`, then the manifest.

        The job directory must still hold its ``job.json``. The manifest
        lists every task that has a record, so the record of every task is
        read.
        """
        if not self.identity_path.exists():
            raise FileNotFoundError(
                f"{self.identity_path} was removed while the {name} task ran; "
                "the outcome of the task is not recorded"
            )
        record_path = self.task_record_path(name)
        record_path.parent.mkdir(exist_ok=True)
        record.write(record_path, root_dir=self.root_dir)
        tasks = {}
        for task_name in self.task_names():
            path = self.task_record_path(task_name)
            task_record = TaskRecord.read(path, root_dir=self.root_dir)
            tasks[task_name] = TaskSummary(
                task_record.latest_run.status,
                task_record.latest_run.run_id,
                len(task_record.runs),
                path,
            )
        Manifest(self.identity, tasks).write(self.manifest_path)


@contextmanager
def exception_on_termination() -> Iterator[None]:
    """Raise :class:`TerminationError` on ``SIGTERM`` while the block runs.

    A batch system ends a job that exceeds its time limit with ``SIGTERM``,
    which would otherwise end the process without running any ``finally``;
    as an exception it stops the program, records the run as interrupted
    and leaves the run's files sealed.
    """

    def raise_terminated(signum: int, frame: FrameType | None) -> None:
        raise TerminationError(f"terminated by signal {signum}")

    previous = signal.signal(signal.SIGTERM, raise_terminated)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
