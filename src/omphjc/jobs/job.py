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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from omphjc.jobs.identity import JobIdentity, TaskIdentity
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.task import TASK_REGISTRY, Task, TaskRecord, TerminationError
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

    def record_identity(self) -> None:
        """Create the job directory with its ``job.json``, or check the one it holds.

        Raises
        ------
        ValueError
            If the ``job.json`` of the directory identifies another job.
        """
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

    def write_manifest(self, written_record: TaskRecord | None = None) -> None:
        """Write the manifest from the record of every task that has one.

        Parameters
        ----------
        written_record : TaskRecord or None, optional
            A record that was written just before the call. It is used as it
            is, and its file is not read again.

        Raises
        ------
        ValueError
            If a ``task.json`` of the job cannot be read as a record.
        """
        tasks = {}
        for task_name, record_path in self._task_record_paths().items():
            if written_record is not None and written_record.identity.name == task_name:
                record = written_record
            else:
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
