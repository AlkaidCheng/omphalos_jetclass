"""A job: one process and one job number, in a directory of its own.

::

    <outdir>/<process>/job_<n>/
      manifest.json      what ran, with what, and what came out (omphjc.jobs.manifest)
      <stage>/           one directory per task, named and laid out by its stage

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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import FrameType
from typing import Any

from omphjc.jobs.manifest import (
    DONE,
    EVENTS_OUTPUT,
    MANIFEST_FILE,
    EventOutput,
    Manifest,
    TaskOutcome,
    TaskRecord,
    timestamp,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.safe_paths import inside, working_directory
from omphjc.stamps import SetAsideFolder, clear_set_aside_folders, set_aside_folders
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT

JOB_DIR_PREFIX = "job_"


class TerminationError(RuntimeError):
    """The process received a termination signal."""


TaskBody = Callable[[bool], TaskOutcome]
"""Runs a task; the argument says whether to replace what an earlier run left."""


class StageStatus(Enum):
    """How a stage of a job stands, by the manifest and the output files."""

    NOT_DONE = "not done"
    """The manifest does not record the stage as done."""
    OUTPUT_MISSING = "output missing"
    """The stage is recorded as done and one of its outputs is not on disk."""
    OUTPUT_SIZE_MISMATCH = "output size mismatch"
    """The stage is recorded as done and one of its outputs has another size
    than the manifest records."""
    DONE = "done"
    """The stage is recorded as done and each output has its recorded size."""


@dataclass(frozen=True)
class StageCheck:
    """What :meth:`Job.check_stage` found.

    Parameters
    ----------
    status : StageStatus
        How the stage stands.
    detail : str
        A clause that names the output that is missing, or the output of
        another size with the size found and the size recorded. It is empty
        for the other statuses.
    """

    status: StageStatus
    detail: str = ""


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
    """One job of a process: its directory, its seed and its manifest.

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
    manifest : Manifest
        The job's manifest, read from the directory or new.

    Raises
    ------
    ValueError
        If `job_id` is not positive, the seed exceeds Pythia's limit, `outdir`
        is a filesystem root, or the directory holds the manifest of another
        job.
    """

    def __init__(self, spec: ProcessSpec, outdir: Path, job_id: int) -> None:
        self.spec = spec
        self.job_id = job_id
        self.seed = job_seed(spec, job_id)
        self.root_dir = inside(
            working_directory(outdir), spec.name, f"{JOB_DIR_PREFIX}{job_id}"
        )
        self.manifest = self._load_manifest()

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / MANIFEST_FILE

    def task_dir(self, stage: str) -> Path:
        """Return the directory of the `stage` task, ``<root>/<stage>``."""
        return inside(self.root_dir, stage)

    def relative_path(self, path: Path) -> str:
        """Return `path` as a POSIX path relative to the job directory."""
        return path.relative_to(self.root_dir).as_posix()

    def check_stage(self, stage: str) -> StageCheck:
        """Return how `stage` stands, by the manifest and its output files.

        The size of each output of a stage recorded as done is compared with
        the size in the manifest. An output of another size is reported
        before a missing one.
        """
        record = self.manifest.stages.get(stage)
        if record is None or record.status != DONE:
            return StageCheck(StageStatus.NOT_DONE)
        check = StageCheck(StageStatus.DONE)
        for output in record.result.outputs.values():
            try:
                n_bytes = output.path.stat().st_size
            except FileNotFoundError:
                check = StageCheck(
                    StageStatus.OUTPUT_MISSING, f"{output.path} is missing"
                )
                continue
            if n_bytes != output.n_bytes:
                return StageCheck(
                    StageStatus.OUTPUT_SIZE_MISMATCH,
                    f"{output.path} holds {n_bytes} bytes, not the "
                    f"{output.n_bytes} the {stage} stage recorded",
                )
        return check

    def require_done(self, stage: str) -> TaskRecord:
        """Return the record of `stage`, which must be done with its outputs as recorded.

        Raises
        ------
        ValueError
            If `stage` is not done or an output is missing; the message names
            the command to run first. If an output has another size than the
            manifest records; the message names the file, both sizes and
            ``--force``.
        """
        check = self.check_stage(stage)
        if check.status is StageStatus.OUTPUT_SIZE_MISMATCH:
            raise ValueError(
                f"{check.detail}; run omphjc {stage} with --force to regenerate "
                "the file"
            )
        if check.status is not StageStatus.DONE:
            raise ValueError(
                f"The {stage} stage of {self.root_dir} has not run to completion; "
                f"run omphjc {stage} first"
            )
        return self.manifest.stages[stage]

    def require_events(self, stage: str) -> EventOutput:
        """Return the events `stage` made, which must be done with its outputs as recorded.

        Raises
        ------
        ValueError
            As :meth:`require_done` does, or if the stage made no event file.
        """
        events = self.require_done(stage).result.outputs.get(EVENTS_OUTPUT)
        if not isinstance(events, EventOutput):
            raise ValueError(f"The {stage} stage of {self.root_dir} made no event file")
        return events

    def run_task(
        self,
        stage: str,
        parameters: dict[str, Any],
        body: TaskBody,
        *,
        force: bool = False,
    ) -> TaskRecord:
        """Run `stage` through `body` unless its result can be kept; record it.

        A task recorded as done, with its outputs present and the same
        `parameters`, is kept. One recorded as done with other parameters, or
        with an output of another size than the manifest records, is refused
        unless `force` is set. One recorded as failed or interrupted,
        or run under `force`, runs again, and `body` is told to replace what
        the earlier run left. The manifest is written before `body` runs and
        after it returns or raises, so a failed or interrupted job records
        how far it got.

        Parameters
        ----------
        stage : str
            Name of the stage; its task's directory is ``<root>/<stage>``.
        parameters : dict
            What the task is asked for, as JSON values.
        body : TaskBody
            Runs the task; receives whether to replace an earlier run's files.
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
            output of another size than the manifest records, and `force` is
            not set.
        Exception
            Whatever `body` raised, after the failure is recorded.
        """
        earlier = self.manifest.stages.get(stage)
        if earlier is not None and earlier.status == DONE and not force:
            if earlier.parameters != parameters:
                raise ValueError(
                    f"{stage} in {self.root_dir} ran with {earlier.parameters}; "
                    f"pass force to run it with {parameters}"
                )
            check = self.check_stage(stage)
            if check.status is StageStatus.DONE:
                return earlier
            if check.status is StageStatus.OUTPUT_SIZE_MISMATCH:
                raise ValueError(
                    f"{check.detail}; run omphjc {stage} with --force to "
                    "regenerate the file"
                )
        overwrite = force or earlier is not None
        started = timestamp()
        clock = time.monotonic()
        self.manifest.stages[stage] = TaskRecord.running(
            started=started, parameters=parameters
        )
        self._write_manifest()
        try:
            outcome = body(overwrite)
        except BaseException as error:
            self.manifest.stages[stage] = TaskRecord.failed(
                started=started, parameters=parameters, error=str(error)
            )
            self._write_manifest()
            raise
        record = TaskRecord.done(
            outcome,
            started=started,
            parameters=parameters,
            wall_seconds=time.monotonic() - clock,
            root_dir=self.root_dir,
        )
        self.manifest.stages[stage] = record
        self._write_manifest()
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
            for stage in self.manifest.stages
            for folder in set_aside_folders(self.task_dir(stage))
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
            for stage in self.manifest.stages
            for folder in clear_set_aside_folders(self.task_dir(stage))
        ]
        return sorted(removed, key=lambda folder: (folder.created, folder.path))

    def _load_manifest(self) -> Manifest:
        if not self.manifest_path.exists():
            return Manifest(process=self.spec.name, job_id=self.job_id)
        manifest = Manifest.read(self.manifest_path)
        if (manifest.process, manifest.job_id) != (self.spec.name, self.job_id):
            raise ValueError(
                f"{self.manifest_path} belongs to {manifest.process} job {manifest.job_id}"
            )
        return manifest

    def _write_manifest(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.manifest.write(self.manifest_path)


@contextmanager
def exception_on_termination() -> Iterator[None]:
    """Raise :class:`TerminationError` on ``SIGTERM`` while the block runs.

    A batch system ends a job that exceeds its time limit with ``SIGTERM``,
    which would otherwise end the process without running any ``finally``;
    as an exception it stops the running program, records the failure in the
    manifest and leaves the run's files sealed.
    """

    def raise_terminated(signum: int, frame: FrameType | None) -> None:
        raise TerminationError(f"terminated by signal {signum}")

    previous = signal.signal(signal.SIGTERM, raise_terminated)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
