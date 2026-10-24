"""The generation stage: parton-level events from MadGraph."""

import shutil
from pathlib import Path

from omphjc.jobs.job import Job, StageOutcome, sha256
from omphjc.jobs.manifest import StageRecord
from omphjc.madgraph.driver import generate_events

GENERATE = "generate"
"""The stage's name and directory, ``<job>/generate/``."""

_CARDS_DIR = "cards"
# The cards MadGraph writes into its Cards directory that a job keeps as run.
_MADGRAPH_CARDS = (
    "proc_card_mg5.dat",
    "run_card.dat",
    "param_card.dat",
    "madspin_card.dat",
)


def generate(
    job: Job,
    *,
    n_events: int,
    n_cores: int | None = None,
    timeout: float | None = None,
    force: bool = False,
    mg5_path: Path | None = None,
) -> StageRecord:
    """Generate the parton-level events of `job` with MadGraph.

    Runs :func:`omphjc.madgraph.generate_events` in the job's ``generate/``
    directory and copies the cards MadGraph ran with into ``generate/cards/``.
    The stage's parameters are the event count and the job's seed, so a
    changed seed is refused like any other change unless `force` is set. Its
    metadata are the MadGraph version, the events made, the cross section with
    its error in pb, and the SHA-256 of each card by path.

    Parameters
    ----------
    job : Job
        The job.
    n_events : int
        Events to generate.
    n_cores : int or None, optional
        Cores MadGraph may use; ``None`` for every usable CPU.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    force : bool, optional
        Run the stage again even when its result could be kept.
    mg5_path : Path or None, optional
        MadGraph's ``bin/mg5_aMC``; ``None`` for the one on PATH.

    Returns
    -------
    StageRecord
        The stage's record, kept or new.
    """
    stage_dir = job.stage_dir(GENERATE)

    def body(overwrite: bool) -> StageOutcome:
        run = generate_events(
            job.spec,
            workdir=stage_dir,
            n_events=n_events,
            seed=job.seed,
            n_cores=n_cores,
            timeout=timeout,
            overwrite=overwrite,
            mg5_path=mg5_path,
        )
        cards = _copy_cards(run.process_dir / "Cards", stage_dir / _CARDS_DIR, job)
        return StageOutcome(
            metadata={
                "madgraph_version": run.banner.version,
                "events": run.banner.n_events,
                "cross_section_pb": run.banner.cross_section_pb,
                "cross_section_error_pb": run.banner.cross_section_error_pb,
                "cards": cards,
            },
            outputs=[run.events_path],
            log_path=run.log_path,
            usage=run.usage.as_record(),
            set_aside=run.set_aside,
        )

    parameters = {"events": n_events, "seed": job.seed}
    return job.run_stage(GENERATE, parameters, body, force=force)


def _copy_cards(source_dir: Path, target_dir: Path, job: Job) -> dict[str, str]:
    """Copy the cards present in `source_dir` into `target_dir`; return their SHA-256."""
    target_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in _MADGRAPH_CARDS:
        card_path = source_dir / name
        if not card_path.is_file():
            continue
        target_path = target_dir / name
        shutil.copyfile(card_path, target_path)
        hashes[job.relative_path(target_path)] = sha256(target_path)
    return hashes
