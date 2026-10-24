"""The shower stage: Pythia 8 on the generated events, through ``DelphesPythia8``."""

from collections.abc import Mapping
from pathlib import Path

from omphjc.jobs.job import Job, StageOutcome, sha256
from omphjc.jobs.manifest import StageRecord
from omphjc.jobs.stages.generate import GENERATE
from omphjc.processes.catalogue import SettingValue
from omphjc.pythia.driver import shower_events

SHOWER = "shower"
"""The stage's name and directory, ``<job>/shower/``."""


def shower(
    job: Job,
    *,
    overrides: Mapping[str, SettingValue] | None = None,
    timeout: float | None = None,
    force: bool = False,
    delphes_pythia8_path: Path | None = None,
) -> StageRecord:
    """Shower the generated events of `job` with Pythia 8.

    Runs :func:`omphjc.pythia.shower_events` in the job's ``shower/``
    directory on the event file the generate stage made, with the job's seed
    and as many events as that stage recorded. The stage's parameters are the
    event count, the seed, the Pythia overrides and the cards the events were
    generated with, so a sample regenerated with the same seed keeps its
    shower. Its metadata are the Pythia version, the events read and
    accepted, the fraction kept by matching for a matched process, and the
    SHA-256 of the command file and the record-only card as run.

    Parameters
    ----------
    job : Job
        The job; its generate stage must be done.
    overrides : Mapping[str, SettingValue] or None, optional
        Pythia settings applied over the catalogue's.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    force : bool, optional
        Run the stage again even when its result could be kept.
    delphes_pythia8_path : Path or None, optional
        Delphes's ``DelphesPythia8``; ``None`` for the one on PATH.

    Returns
    -------
    StageRecord
        The stage's record, kept or new.

    Raises
    ------
    ValueError
        If the generate stage of `job` has not run to completion.
    """
    generated = job.manifest.stages.get(GENERATE)
    if generated is None or not job.is_done(GENERATE):
        raise ValueError(
            f"The generate stage of {job.root_dir} has not run to completion; run "
            "omphjc generate first"
        )
    lhe_path = job.root_dir / generated.outputs[0]
    n_events = int(generated.metadata["events"])
    stage_dir = job.stage_dir(SHOWER)
    pythia_overrides = dict(overrides or {})

    def body(overwrite: bool) -> StageOutcome:
        run = shower_events(
            job.spec,
            lhe_path=lhe_path,
            workdir=stage_dir,
            n_events=n_events,
            seed=job.seed,
            overrides=pythia_overrides,
            timeout=timeout,
            overwrite=overwrite,
            delphes_pythia8_path=delphes_pythia8_path,
        )
        statistics = run.statistics
        metadata = {
            "pythia_version": statistics.pythia_version,
            "events_read": statistics.events_read,
            "events_accepted": statistics.events_accepted,
            "settings": {
                job.relative_path(run.cmnd_path): sha256(run.cmnd_path),
                job.relative_path(run.card_path): sha256(run.card_path),
            },
        }
        if job.spec.matching and statistics.events_read > 0:
            metadata["matching_efficiency"] = (
                statistics.events_accepted / statistics.events_read
            )
        return StageOutcome(
            metadata=metadata,
            outputs=[run.output_path],
            log_path=run.log_path,
            usage=run.usage.as_record(),
            set_aside=run.set_aside,
        )

    parameters = {
        "events": n_events,
        "seed": job.seed,
        "pythia": pythia_overrides,
        "generated_with": generated.metadata.get("cards", {}),
    }
    return job.run_stage(SHOWER, parameters, body, force=force)
