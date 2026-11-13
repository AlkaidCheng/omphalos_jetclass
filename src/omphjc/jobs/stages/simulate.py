"""The simulation stage: Delphes on the showered events, through ``DelphesROOT``."""

import hashlib
from pathlib import Path

from omphjc.events.formats import EventFormat
from omphjc.jobs.job import Job, sha256
from omphjc.jobs.stages.shower import SHOWER
from omphjc.jobs.task import (
    EVENTS_OUTPUT,
    EventOutput,
    TaskOutcome,
    TaskRecord,
    TaskResult,
)
from omphjc.tools.delphes.driver import detector_card_text, simulate_events

SIMULATE = "simulate"
"""The stage's name and directory, ``<job>/simulate/``."""


def simulate(
    job: Job,
    *,
    card_path: Path | None = None,
    timeout: float | None = None,
    force: bool = False,
    delphes_root_path: Path | None = None,
) -> TaskRecord:
    """Simulate the detector on the showered events of `job` with Delphes.

    Runs :func:`omphjc.tools.delphes.driver.simulate_events` in the job's ``simulate/``
    directory on the file the shower stage made, with the job's seed. The
    stage's parameters are the seed, the SHA-256 of the detector card chosen
    and the fingerprint of the event file read, so a shower run again with
    the same events keeps its simulation, and another card is refused unless
    `force` is set. Its events are the ROOT file with the number of entries
    in its tree and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`), and its metadata
    the SHA-256 of the card as run.

    Parameters
    ----------
    job : Job
        The job; its shower stage must be done.
    card_path : Path or None, optional
        The detector card to run instead of the process's.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    force : bool, optional
        Run the stage again even when its result could be kept.
    delphes_root_path : Path or None, optional
        Delphes's ``DelphesROOT``; ``None`` for the one on PATH.

    Returns
    -------
    TaskRecord
        The stage's record, kept or new.

    Raises
    ------
    ValueError
        If the shower stage of `job` has not run to completion.
    FileNotFoundError
        If `card_path` is given and is not a file.
    """
    events = job.require_events(SHOWER)
    task_dir = job.task_dir(SIMULATE)
    card_text = detector_card_text(job.spec, card_path)
    card_hash = hashlib.sha256(card_text.encode("utf-8")).hexdigest()

    def body(overwrite: bool) -> TaskOutcome:
        # This module loads the array libraries, so it is imported here and
        # not when a command starts.
        from omphjc.events.delphes_root import DelphesROOTFile

        run = simulate_events(
            job.spec,
            events_path=events.path,
            workdir=task_dir,
            seed=job.seed,
            card_path=card_path,
            timeout=timeout,
            overwrite=overwrite,
            delphes_root_path=delphes_root_path,
        )
        delphes_file = DelphesROOTFile.read(run.output_path)
        return TaskOutcome(
            TaskResult(
                outputs={
                    EVENTS_OUTPUT: EventOutput(
                        run.output_path,
                        n_bytes=run.output_path.stat().st_size,
                        format=EventFormat.DELPHES_ROOT,
                        n_events=delphes_file.n_entries,
                        fingerprint=delphes_file.fingerprint(),
                    )
                },
                metadata={
                    "card": {job.relative_path(run.card_path): sha256(run.card_path)}
                },
            ),
            log_path=run.log_path,
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    parameters = {
        "seed": job.seed,
        "card": card_hash,
        "input_fingerprint": events.fingerprint,
    }
    return job.run_task(SIMULATE, parameters, body, force=force)
