"""The simulation stage: Delphes on the showered events, through ``DelphesROOT``."""

import hashlib
from pathlib import Path

from omphjc.delphes.driver import detector_card_text, simulate_events
from omphjc.jobs.job import Job, sha256
from omphjc.jobs.manifest import StageOutcome, StageRecord
from omphjc.jobs.stages.shower import SHOWER

SIMULATE = "simulate"
"""The stage's name and directory, ``<job>/simulate/``."""


def simulate(
    job: Job,
    *,
    card_path: Path | None = None,
    timeout: float | None = None,
    force: bool = False,
    delphes_root_path: Path | None = None,
) -> StageRecord:
    """Simulate the detector on the showered events of `job` with Delphes.

    Runs :func:`omphjc.delphes.simulate_events` in the job's ``simulate/``
    directory on the file the shower stage made, with the job's seed. The
    stage's parameters are the seed, the SHA-256 of the detector card chosen
    and the settings the events were showered with, so a shower rerun with
    the same settings keeps its simulation, and another card is refused
    unless `force` is set. Its metadata are the events simulated and the
    SHA-256 of the card as run.

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
    StageRecord
        The stage's record, kept or new.

    Raises
    ------
    ValueError
        If the shower stage of `job` has not run to completion.
    FileNotFoundError
        If `card_path` is given and is not a file.
    """
    shower_record = job.manifest.stages.get(SHOWER)
    if shower_record is None or not job.is_done(SHOWER):
        raise ValueError(
            f"The shower stage of {job.root_dir} has not run to completion; run "
            "omphjc shower first"
        )
    events_path = job.root_dir / shower_record.outputs[0]
    stage_dir = job.stage_dir(SIMULATE)
    card_text = detector_card_text(job.spec, card_path)
    card_hash = hashlib.sha256(card_text.encode("utf-8")).hexdigest()

    def body(overwrite: bool) -> StageOutcome:
        run = simulate_events(
            job.spec,
            events_path=events_path,
            workdir=stage_dir,
            seed=job.seed,
            card_path=card_path,
            timeout=timeout,
            overwrite=overwrite,
            delphes_root_path=delphes_root_path,
        )
        return StageOutcome(
            metadata={
                "events": shower_record.metadata.get("events_accepted"),
                "card": {job.relative_path(run.card_path): sha256(run.card_path)},
            },
            outputs=[run.output_path],
            log_path=run.log_path,
            usage=run.usage.as_record(),
            set_aside=run.set_aside,
        )

    parameters = {
        "seed": job.seed,
        "card": card_hash,
        "showered_with": shower_record.metadata.get("settings", {}),
    }
    return job.run_stage(SIMULATE, parameters, body, force=force)
