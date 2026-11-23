"""A job: one process and one job number, in a directory of its own.

::

    <outdir>/<process>/job_<n>/
      job.json           the process, the job number and the seed (omphjc.jobs.identity)
      manifest.json      an index of the tasks and their records (omphjc.jobs.manifest)
      <stage>-<tool>/    one directory per task, named after its identity
                         (omphjc.jobs.identity)
        task.json        what the task ran with and what came out (omphjc.jobs.task)
        logs/<run_id>.log   the log of each run of the task

The job number fixes the seed of every program in the job
(:func:`job_seed`). ``docs/reproducibility.md`` lists what else the events of
a repeated job depend on.

Paths are built from screened names (:mod:`omphjc.safe_paths`). A process
name from a catalogue therefore cannot place a job outside `outdir`.
"""

import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import FrameType
from typing import Any

from omphjc.comparison import Difference
from omphjc.jobs.identity import JobIdentity, TaskIdentity
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.task import (
    INPUT_FINGERPRINT_PARAMETER,
    TASK_REGISTRY,
    Task,
    TaskRecord,
    TaskRun,
    TaskStatus,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.safe_paths import inside, working_directory
from omphjc.stamps import SetAsideFolder, clear_set_aside_folders, set_aside_folders
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT

JOB_DIR_PREFIX = "job_"


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


class TerminationError(RuntimeError):
    """The process received a termination signal."""


class ReplacedRunError(RuntimeError):
    """A newer run of the task started before this one ended.

    The end of this run is then not recorded.
    """


# What ends a run without its program or omphjc failing.
_INTERRUPTIONS = (TerminationError, KeyboardInterrupt)


class Job:
    """One job of a process: its directory, its identity and its tasks.

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
        The job directory, ``<outdir>/<process>/job_<n>``. The first task
        that runs creates it.
    seed : int
        The seed of every program the job runs. A task that uses it records
        it among its parameters.
    identity : JobIdentity
        The process, the job number and the seed. The first task that runs
        writes it to ``job.json`` in the job directory.

    Two jobs are equal when they are the same process in the same job
    directory.

    Raises
    ------
    ValueError
        If `job_id` is not positive. If the seed exceeds Pythia's limit. If
        `outdir` is a filesystem root. If the directory holds the
        ``job.json`` of another job.
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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Job):
            return NotImplemented
        return (self.spec, self.root_dir) == (other.spec, other.root_dir)

    def __hash__(self) -> int:
        return hash(self.root_dir)

    def __repr__(self) -> str:
        return (
            f"Job({self.spec.name!r}, {self.job_id}, root_dir={str(self.root_dir)!r})"
        )

    @property
    def identity_path(self) -> Path:
        return self.root_dir / JobIdentity.file_name

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / Manifest.file_name

    def task_dir(self, identity: TaskIdentity) -> Path:
        """Return the directory of the task `identity`, ``<root>/<task name>``."""
        return inside(self.root_dir, identity.name)

    def relative_path(self, path: Path) -> str:
        """Return `path` as a POSIX path relative to the job directory."""
        return path.relative_to(self.root_dir).as_posix()

    def tasks(self, stage: str | None = None) -> list[Task]:
        """Return the tasks that have a record, in the order of their names.

        A task has a record when its directory holds a ``task.json``. Only the
        directories directly inside the job directory are looked at.

        Each task is made from its record (:meth:`task_from_record`).

        Parameters
        ----------
        stage : str or None, optional
            The name of a stage. When it is given, only the tasks of that
            stage are returned. A stage can have none, one or several.

        Raises
        ------
        ValueError
            If a ``task.json`` cannot be read as a record, or its directory
            is not named after the task it identifies. If one of the tasks to
            return cannot be made from its record.
        """
        records = [
            TaskRecord.read(record_path, root_dir=self.root_dir)
            for record_path in self._task_record_paths().values()
        ]
        return [
            self.task_from_record(record)
            for record in records
            if stage is None or record.identity.stage == stage
        ]

    def task_from_record(self, record: TaskRecord) -> Task:
        """Return the task of this job that `record` describes.

        The task is an object of the class registered for the stage and the
        tool in the record (:data:`~omphjc.jobs.task.TASK_REGISTRY`,
        :meth:`Task.from_record`).

        Raises
        ------
        ValueError
            If no class is registered for the stage and the tool in the
            record. If the settings in the record are not those of the class.
        """
        task_class = TASK_REGISTRY.get(record.identity)
        return task_class.from_record(self, record)

    def _task_record_paths(self) -> dict[str, Path]:
        """Return the path of the record of each task that has one, by the task's name.

        The tasks are in the alphabetical order of their names.
        """
        record_paths = sorted(self.root_dir.glob(f"*/{TaskRecord.file_name}"))
        return {record_path.parent.name: record_path for record_path in record_paths}

    def _task_dirs(self) -> list[Path]:
        """Return the directory of each task that has a record."""
        return [
            record_path.parent for record_path in self._task_record_paths().values()
        ]

    def run_task(
        self, task: Task, *, accept_input: bool = False, force: bool = False
    ) -> TaskRecord:
        """Run `task` unless its result can be kept.

        The parameters of the request are those of :meth:`Task.parameters`, with
        the fingerprint of the events that the task reads
        (:data:`~omphjc.jobs.task.INPUT_FINGERPRINT_PARAMETER`). The run is
        recorded in the record of the task, with the settings of the task.

        The events that the task reads are found once, before anything else,
        and given to :meth:`Task.parameters` and to :meth:`Task.execute`.

        **A task recorded as done.**

        - It is kept when its outputs are present and the parameters are the
          same.
        - It is refused when the parameters differ, or when an output has
          another size than recorded. `force` overrides the refusal.
        - With `accept_input`, it is also kept when its outputs are present
          and the parameters differ only in the fingerprint of its input.
          The record then stores that fingerprint and the time as its
          ``accepted_input``, which replaces an earlier one. Its parameters
          keep the fingerprint of the input the task read, and it gains no
          run. From then on the task is kept for either input, without
          `accept_input` too.

        **A task that is not kept.** A task without a record runs. A task
        that failed, was interrupted or lost an output runs again. The new
        run is added to the record when the parameters are the same. With
        other parameters, or under `force`, the task starts a new record,
        and the logs of the runs that the earlier record listed are removed.
        In both cases :meth:`Task.execute` is told to replace what the earlier
        run left.

        **What is written.** The first task of a job creates the job
        directory with its ``job.json``. Each run gets a run ID and a log,
        ``logs/<run_id>.log`` in the directory of the task
        (:meth:`Task.log_path`).

        The record, ``task.json`` in the directory of the task, is written
        before :meth:`Task.execute` is called and again after it returns or
        raises. A failed or interrupted run therefore records how far it got.
        The manifest of the job is written again after each of these writes.

        A run that ``SIGTERM`` or a keyboard interrupt ended is recorded as
        interrupted, and a run that raised anything else as failed. The end
        of a run is written only while that run is still the latest one in
        the record on disk.

        Parameters
        ----------
        task : Task
            The task to run.
        accept_input : bool, optional
            Keep a done task whose input alone has changed, and record the
            acceptance. It changes nothing for a task that is not done or has
            lost an output.
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
            task of the job cannot be read as a record. If `accept_input` and
            `force` are both set. If the record that a new one replaces lists
            a run whose ID is not a plain name; the record is then left as it
            was. If the events that the task reads cannot be given
            (:meth:`Task.input_events`). If the parameters of the task use the key
            of the input fingerprint.
        FileNotFoundError
            If the ``job.json`` of the directory was removed while the task
            ran. The task is then not recorded.
        ReplacedRunError
            If a newer run of the task started before this one ended. The
            record of the newer run is left unchanged, and the end of this
            one is not recorded.
        Exception
            Whatever :meth:`Task.parameters` raised, before anything is recorded.
            Whatever :meth:`Task.execute` raised, after the failure is recorded.
        """
        if accept_input and force:
            raise ValueError("accept_input and force cannot both be set")
        input_events = task.input_events()
        parameters = task.requested_parameters(input_events)
        previous_record = task.record
        if not force:
            kept_record = self._kept_record(
                task, previous_record, parameters, accept_input=accept_input
            )
            if kept_record is not None:
                return kept_record
        overwrite = force or previous_record is not None
        clock = time.monotonic()
        self._record_identity()
        dropped_runs: tuple[TaskRun, ...] = ()
        if previous_record is None or force or previous_record.parameters != parameters:
            record = TaskRecord.running(task.identity, task.settings(), parameters)
            if previous_record is not None:
                dropped_runs = previous_record.runs
        else:
            record = replace(previous_record.rerun(), settings=task.settings())
        log_path = task.log_path(record.latest_run.run_id)
        # Named before the record is replaced, so that a run ID that is not a
        # plain name is refused while the earlier record is still in place.
        dropped_logs = [task.log_path(run.run_id) for run in dropped_runs]
        self._write_record(task, record)
        try:
            task.remove_logs(dropped_logs)
            log_path.parent.mkdir(exist_ok=True)
            outcome = task.execute(input_events, overwrite, log_path)
        except BaseException as error:
            message = str(error) or type(error).__name__
            if isinstance(error, _INTERRUPTIONS):
                self._write_run_end(task, record.interrupted(error=message))
            else:
                self._write_run_end(task, record.failed(error=message))
            raise
        record = record.done(
            outcome, wall_seconds=time.monotonic() - clock, root_dir=self.root_dir
        )
        self._write_run_end(task, record)
        return record

    def _kept_record(
        self,
        task: Task,
        record: TaskRecord | None,
        parameters: dict[str, Any],
        *,
        accept_input: bool,
    ) -> TaskRecord | None:
        """Return `record` when the result of the task is kept for `parameters`.

        `record` is the record of the task as found on disk.

        Return ``None`` when the task has to run. That is the case for a
        task without a record, for a task that is not done, and for a task
        that lost an output and has the same parameters.

        Raises
        ------
        ValueError
            As :meth:`run_task` refuses a task recorded as done.
        """
        if record is None or not record.is_done:
            return None
        status, detail = record.current_status()
        if status is TaskStatus.DONE:
            if record.is_accepted_for(parameters):
                return record
            if accept_input:
                return self._accept_input(task, record, parameters)
        self._check_parameters(task, record, parameters)
        if status is TaskStatus.DONE:
            return record
        if status is TaskStatus.CHANGED:
            raise ValueError(
                f"{detail}; run {task.identity.command} with --force to "
                "regenerate the file"
            )
        return None

    def _accept_input(
        self, task: Task, record: TaskRecord, parameters: dict[str, Any]
    ) -> TaskRecord:
        """Keep the done task for the input in `parameters`; record that.

        `record` is returned as it is when `parameters` are those of the
        task. Otherwise they may differ in the input fingerprint alone, and
        the record is written with that fingerprint as its accepted input.

        Raises
        ------
        ValueError
            If another parameter differs; the message names each one, and
            leaves out the input fingerprint.
        """
        if parameters == record.parameters:
            return record
        key = INPUT_FINGERPRINT_PARAMETER
        # The parameters the task ran with, with the requested input in place.
        acceptable_parameters = dict(record.parameters)
        if key in parameters:
            acceptable_parameters[key] = parameters[key]
        self._check_parameters(task, record, parameters, recorded=acceptable_parameters)
        record = record.with_accepted_input(parameters[key])
        self._write_record(task, record)
        return record

    def _check_parameters(
        self,
        task: Task,
        record: TaskRecord,
        parameters: dict[str, Any],
        *,
        recorded: dict[str, Any] | None = None,
    ) -> None:
        """Refuse `parameters` when the task ran with other ones.

        The message names each parameter that differs. A nested parameter
        is named by the dotted path of its keys. The value the task ran with
        is shown as the expected one.

        `recorded` are the parameters to compare with, when they are not
        those of `record`.
        """
        if recorded is None:
            recorded = record.parameters
        if parameters == recorded:
            return
        differences = Difference.between_nested_mappings(parameters, recorded)
        record_path = self.relative_path(task.record_path)
        raise ValueError(
            "The current parameters are inconsistent with those of the existing "
            f"{task.name} task in {self.root_dir} ({record_path}):"
            + "".join(f"\n  {difference}" for difference in differences)
            + "\nRerun with the parameters the task ran with, or run "
            f"{task.identity.command} with --force to replace its result."
        )

    def _write_run_end(self, task: Task, record: TaskRecord) -> None:
        """Write `record`, which says how the latest run of the task ended.

        Raises
        ------
        ReplacedRunError
            If the record on disk already holds a newer run of the task.
            That record is left unchanged.
        """
        run = record.latest_run
        recorded = task.record
        if recorded is not None and recorded.latest_run.run_id != run.run_id:
            raise ReplacedRunError(
                f"Run {run.run_id!r} of the {task.name} task in "
                f"{self.root_dir} is not "
                f"recorded as {run.status}: run {recorded.latest_run.run_id!r} of "
                "the task started before it ended"
            )
        self._write_record(task, record)

    def _write_record(self, task: Task, record: TaskRecord) -> None:
        """Write `record` as the record of the task, then the manifest of the job.

        The job directory must still hold its ``job.json``.
        """
        if not self.identity_path.exists():
            raise FileNotFoundError(
                f"{self.identity_path} was removed while the "
                f"{task.name} task ran; "
                "the outcome of the task is not recorded"
            )
        task.record_path.parent.mkdir(exist_ok=True)
        record.write(task.record_path, root_dir=self.root_dir)
        self._write_manifest()

    def set_aside_folders(self) -> list[SetAsideFolder]:
        """Return what earlier runs of the job's tasks set aside, oldest first.

        A run does not delete an artifact that it cannot confirm as an
        earlier run's own. It moves the artifact into
        ``<task>/omphjc-set-aside/`` (:mod:`omphjc.stamps`). This happens,
        for example, when the earlier run was killed before it sealed its
        artifacts.

        The folders stay until :meth:`clear_set_aside_folders` or the user
        deletes them.
        """
        found = [
            folder
            for task_dir in self._task_dirs()
            for folder in set_aside_folders(task_dir)
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
            for task_dir in self._task_dirs()
            for folder in clear_set_aside_folders(task_dir)
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

    def _write_manifest(self) -> None:
        """Write the manifest from the record of every task that has one."""
        tasks = {}
        for task_name, record_path in self._task_record_paths().items():
            record = TaskRecord.read(record_path, root_dir=self.root_dir)
            tasks[task_name] = TaskSummary(
                record.latest_run.status,
                record.latest_run.run_id,
                len(record.runs),
                record_path,
            )
        Manifest(self.identity, tasks).write(self.manifest_path)


@contextmanager
def exception_on_termination() -> Iterator[None]:
    """Raise :class:`TerminationError` on ``SIGTERM`` while the block runs.

    A batch system ends a job that exceeds its time limit with ``SIGTERM``.
    By default the signal ends the process without executing any ``finally``
    block. Raised as an exception, it stops the program, records the run as
    interrupted and leaves the run's files sealed.
    """

    def raise_terminated(signum: int, frame: FrameType | None) -> None:
        raise TerminationError(f"terminated by signal {signum}")

    previous = signal.signal(signal.SIGTERM, raise_terminated)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
