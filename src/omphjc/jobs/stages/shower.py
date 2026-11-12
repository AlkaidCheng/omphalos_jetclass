"""The shower stage: Pythia 8 on the generated events, through ``DelphesPythia8``."""

from collections.abc import Mapping
from pathlib import Path

from omphjc.events.formats import EventFormat
from omphjc.jobs.job import Job, sha256
from omphjc.jobs.manifest import (
    EVENTS_OUTPUT,
    EventOutput,
    TaskOutcome,
    TaskRecord,
    TaskResult,
)
from omphjc.jobs.stages.generate import GENERATE
from omphjc.processes.catalogue import SettingValue
from omphjc.tools.pythia.driver import shower_events

SHOWER = "shower"
"""The stage's name and directory, ``<job>/shower/``."""


def shower(
    job: Job,
    *,
    overrides: Mapping[str, SettingValue] | None = None,
    timeout: float | None = None,
    force: bool = False,
    delphes_pythia8_path: Path | None = None,
) -> TaskRecord:
    """Shower the generated events of `job` with Pythia 8.

    Runs :func:`omphjc.tools.pythia.driver.shower_events` in the job's ``shower/``
    directory on the event file the generate stage made, with the job's seed
    and as many events as that stage recorded. The stage's parameters are the
    event count, the seed, the Pythia overrides and the fingerprint of the
    event file read, so a sample generated again with the same events keeps
    its shower. Its events are the ROOT file with the count Pythia accepted
    and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`), and its metadata
    the Pythia version, the events read, the fraction kept by
    matching for a matched process, and the SHA-256 of the command file and
    the record-only card as run.

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
    TaskRecord
        The stage's record, kept or new.

    Raises
    ------
    ValueError
        If the generate stage of `job` has not run to completion.
    """
    events = job.require_events(GENERATE)
    task_dir = job.task_dir(SHOWER)
    pythia_overrides = dict(overrides or {})

    def body(overwrite: bool) -> TaskOutcome:
        # This module loads the array libraries, so it is imported here and
        # not when a command starts.
        from omphjc.events.delphes_root import DelphesROOTFile

        run = shower_events(
            job.spec,
            lhe_path=events.path,
            workdir=task_dir,
            n_events=events.n_events,
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
            "settings": {
                job.relative_path(run.cmnd_path): sha256(run.cmnd_path),
                job.relative_path(run.card_path): sha256(run.card_path),
            },
        }
        if job.spec.matching and statistics.events_read > 0:
            metadata["matching_efficiency"] = (
                statistics.events_accepted / statistics.events_read
            )
        return TaskOutcome(
            TaskResult(
                outputs={
                    EVENTS_OUTPUT: EventOutput(
                        run.output_path,
                        EventFormat.DELPHES_ROOT,
                        n_events=statistics.events_accepted,
                        fingerprint=DelphesROOTFile.read(run.output_path).fingerprint(),
                    )
                },
                metadata=metadata,
            ),
            log_path=run.log_path,
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    parameters = {
        "events": events.n_events,
        "seed": job.seed,
        "pythia": pythia_overrides,
        "input_fingerprint": events.fingerprint,
    }
    return job.run_task(SHOWER, parameters, body, force=force)
