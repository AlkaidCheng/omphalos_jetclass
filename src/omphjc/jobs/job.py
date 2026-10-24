"""A job: one process and one job number, in a directory of its own.

::

    <outdir>/<process>/job_<n>/
      manifest.json      what ran, with what, and what came out (omphjc.jobs.manifest)
      <stage>/           one directory per stage, laid out by the stage

The job number fixes the seed of every program the job runs
(:func:`job_seed`), so a job is reproducible from its process and number
alone. Paths are built from screened names (:mod:`omphjc.safe_paths`), so a
process name from a catalogue cannot place a job outside `outdir`.
"""

import hashlib
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any

from omphjc.jobs.manifest import (
    DONE,
    FAILED,
    MANIFEST_FILE,
    RUNNING,
    Manifest,
    StageRecord,
    timestamp,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.pythia.cmnd import PYTHIA_SEED_LIMIT
from omphjc.safe_paths import inside, working_directory
from omphjc.stamps import SetAsideFolder, clear_set_aside_folders, set_aside_folders

JOB_DIR_PREFIX = "job_"


class TerminationError(RuntimeError):
    """The process received a termination signal."""


@dataclass(frozen=True)
class StageOutcome:
    """What a stage hands back once it has run.

    Parameters
    ----------
    metadata : dict
        What is known about the stage and what it made, as JSON values. The
        keys are the stage's own.
    outputs : list[Path]
        The files the stage made, inside the job directory.
    log_path : Path or None
        The stage's log, inside the job directory.
    usage : dict[str, float]
        What the stage's program took beyond the wall time the job measures
        itself, such as ``cpu_seconds`` and ``peak_memory_mib``.
    set_aside : Path or None
        The folder into which the run moved what an earlier run left and it
        could not confirm as that run's, inside the job directory; ``None``
        when it moved nothing.
    """

    metadata: dict[str, Any]
    outputs: list[Path]
    log_path: Path | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: Path | None = None


StageBody = Callable[[bool], StageOutcome]
"""Runs a stage; the argument says whether to replace what an earlier run left."""


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

    def stage_dir(self, stage: str) -> Path:
        """Return the directory of `stage`, ``<root>/<stage>``."""
        return inside(self.root_dir, stage)

    def relative_path(self, path: Path) -> str:
        """Return `path` as a POSIX path relative to the job directory."""
        return path.relative_to(self.root_dir).as_posix()

    def is_done(self, stage: str) -> bool:
        """Return whether `stage` is recorded as done with its outputs present."""
        record = self.manifest.stages.get(stage)
        if record is None or record.status != DONE:
            return False
        return all((self.root_dir / output).exists() for output in record.outputs)

    def run_stage(
        self,
        stage: str,
        parameters: dict[str, Any],
        body: StageBody,
        *,
        force: bool = False,
    ) -> StageRecord:
        """Run `stage` through `body` unless its result can be kept; record it.

        A stage recorded as done, with its outputs present and the same
        `parameters`, is kept. One recorded as done with other parameters is
        refused unless `force` is set. One recorded as failed or interrupted,
        or run under `force`, runs again, and `body` is told to replace what
        the earlier run left. The manifest is written before `body` runs and
        after it returns or raises, so a failed or interrupted job records
        how far it got.

        Parameters
        ----------
        stage : str
            Name of the stage; its directory is ``<root>/<stage>``.
        parameters : dict
            What the stage is asked for, as JSON values.
        body : StageBody
            Runs the stage; receives whether to replace an earlier run's files.
        force : bool, optional
            Run the stage even when its result could be kept.

        Returns
        -------
        StageRecord
            The record of the stage, kept or new.

        Raises
        ------
        ValueError
            If the stage is recorded as done with other parameters and `force`
            is not set.
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
            if self.is_done(stage):
                return earlier
        overwrite = force or earlier is not None
        started = timestamp()
        clock = time.monotonic()
        self.manifest.stages[stage] = StageRecord(
            status=RUNNING, started=started, parameters=parameters
        )
        self._write_manifest()
        try:
            outcome = body(overwrite)
        except BaseException as error:
            self.manifest.stages[stage] = StageRecord(
                status=FAILED,
                started=started,
                finished=timestamp(),
                parameters=parameters,
                error=str(error),
            )
            self._write_manifest()
            raise
        record = StageRecord(
            status=DONE,
            started=started,
            finished=timestamp(),
            parameters=parameters,
            metadata=outcome.metadata,
            outputs=[self.relative_path(output) for output in outcome.outputs],
            log=(
                None
                if outcome.log_path is None
                else self.relative_path(outcome.log_path)
            ),
            usage={
                "wall_seconds": round(time.monotonic() - clock, 3),
                **outcome.usage,
            },
            set_aside=(
                None
                if outcome.set_aside is None
                else self.relative_path(outcome.set_aside)
            ),
        )
        self.manifest.stages[stage] = record
        self._write_manifest()
        return record

    def set_aside_folders(self) -> list[SetAsideFolder]:
        """Return what earlier runs of the job's stages set aside, oldest first.

        A run that cannot confirm an artifact an earlier run left, as after a
        kill before sealing, moves it into ``<stage>/omphjc-set-aside/``
        rather than deleting it (:mod:`omphjc.stamps`). The folders stay until
        :meth:`clear_set_aside_folders` or the user deletes them.
        """
        found = [
            folder
            for stage in self.manifest.stages
            for folder in set_aside_folders(self.stage_dir(stage))
        ]
        return sorted(found, key=lambda folder: (folder.created, folder.path))

    def clear_set_aside_folders(self) -> list[SetAsideFolder]:
        """Delete what earlier runs of the job's stages set aside; return it.

        Raises
        ------
        StampError
            If a stage directory holds set-aside folders but no stamp; nothing
            in that directory is changed.
        """
        removed = [
            folder
            for stage in self.manifest.stages
            for folder in clear_set_aside_folders(self.stage_dir(stage))
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
