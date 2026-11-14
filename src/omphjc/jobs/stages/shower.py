"""The shower stage: Pythia 8 on the generated events, through ``DelphesPythia8``."""

from collections.abc import Mapping
from pathlib import Path

from omphjc.events.formats import EventFormat
from omphjc.jobs.job import Job
from omphjc.jobs.stages.generate import GENERATE
from omphjc.jobs.task import (
    EVENTS_OUTPUT,
    INPUT_FINGERPRINT_PARAMETER,
    EventOutput,
    TaskOutcome,
    TaskRecord,
    TaskResult,
    read_cards,
)
from omphjc.processes.catalogue import SettingValue
from omphjc.tools.pythia.driver import ShowerWorkspace, shower_events

SHOWER = "shower"
"""The stage's name and directory, ``<job>/shower/``."""


def shower(
    job: Job,
    *,
    overrides: Mapping[str, SettingValue] | None = None,
    timeout: float | None = None,
    accept_input: bool = False,
    force: bool = False,
    delphes_pythia8_path: Path | None = None,
) -> TaskRecord:
    """Shower the generated events of `job` with Pythia 8.

    The stage runs :func:`omphjc.tools.pythia.driver.shower_events` in the job's
    ``shower/`` directory. It reads the event file the generate stage made, and
    uses the job's seed and the event count that stage recorded.

    Its parameters are the event count, the seed, the Pythia overrides and the
    fingerprint of the event file it reads. A sample that is generated again
    with the same events therefore keeps its shower.

    Its events are the ROOT file, recorded with the number of events Pythia
    accepted and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`).

    Its cards are the Pythia command file and the Delphes card that writes the
    generator record, both as the run used them.

    Its metadata holds:

    - the Pythia version;
    - the number of events read;
    - the fraction of events kept by matching, for a matched process.

    Parameters
    ----------
    job : Job
        The job; its generate stage must be done.
    overrides : Mapping[str, SettingValue] or None, optional
        Pythia settings applied over the catalogue's.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    accept_input : bool, optional
        Keep the stage's result although the events it reads have changed
        since it ran, and record that (:meth:`omphjc.jobs.Job.run_task`). A
        stage that is not done runs as it does without the option.
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
        If the generate stage of `job` has not run to completion, or
        `accept_input` and `force` are both set.
    """
    events = job.require_events(GENERATE)
    task_dir = job.task_dir(SHOWER)
    pythia_overrides = dict(overrides or {})

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
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
            log_dir=run_dir,
            delphes_pythia8_path=delphes_pythia8_path,
        )
        statistics = run.statistics
        metadata = {
            "pythia_version": statistics.pythia_version,
            "events_read": statistics.events_read,
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
                        n_bytes=run.output_path.stat().st_size,
                        format=EventFormat.DELPHES_ROOT,
                        n_events=statistics.events_accepted,
                        fingerprint=DelphesROOTFile.read(run.output_path).fingerprint(),
                    )
                },
                cards=read_cards(run.card_paths),
                metadata=metadata,
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    parameters = {
        "events": events.n_events,
        "seed": job.seed,
        "pythia": pythia_overrides,
        INPUT_FINGERPRINT_PARAMETER: events.fingerprint,
    }
    return job.run_task(
        SHOWER,
        parameters,
        body,
        log_name=ShowerWorkspace.log_name,
        accept_input=accept_input,
        force=force,
    )
