"""The simulation stage: Delphes on the showered events, through ``DelphesROOT``."""

import hashlib
from pathlib import Path

from omphjc.events.formats import EventFormat
from omphjc.jobs.job import Job
from omphjc.jobs.stages.shower import SHOWER
from omphjc.jobs.task import (
    EVENTS_OUTPUT,
    INPUT_FINGERPRINT_PARAMETER,
    EventOutput,
    TaskOutcome,
    TaskRecord,
    TaskResult,
    read_cards,
)
from omphjc.tools.delphes.driver import (
    SimulationWorkspace,
    detector_card_text,
    simulate_events,
)

SIMULATE = "simulate"
"""The stage's name and directory, ``<job>/simulate/``."""


def simulate(
    job: Job,
    *,
    card_path: Path | None = None,
    timeout: float | None = None,
    accept_input: bool = False,
    force: bool = False,
    delphes_root_path: Path | None = None,
) -> TaskRecord:
    """Simulate the detector on the showered events of `job` with Delphes.

    The stage runs :func:`omphjc.tools.delphes.driver.simulate_events` in the
    job's ``simulate/`` directory. It reads the file the shower stage made and
    uses the job's seed.

    Its parameters are the seed, the SHA-256 of the chosen detector card and
    the fingerprint of the event file it reads. A shower that is repeated with
    the same events therefore keeps its simulation. Another card is refused
    unless `force` is set.

    Its events are the ROOT file, recorded with the number of entries in its
    tree and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`).

    Its card is the detector card as the run used it, with the seed.

    Parameters
    ----------
    job : Job
        The job; its shower stage must be done.
    card_path : Path or None, optional
        The detector card to run instead of the process's.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    accept_input : bool, optional
        Keep the stage's result although the events it reads have changed
        since it ran, and record that (:meth:`omphjc.jobs.Job.run_task`). A
        stage that is not done runs as it does without the option.
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
        If the shower stage of `job` has not run to completion, or
        `accept_input` and `force` are both set.
    FileNotFoundError
        If `card_path` is given and is not a file.
    """
    events = job.require_events(SHOWER)
    task_dir = job.task_dir(SIMULATE)
    card_text = detector_card_text(job.spec, card_path)
    card_hash = hashlib.sha256(card_text.encode("utf-8")).hexdigest()

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
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
            log_dir=run_dir,
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
                cards=read_cards(run.card_paths),
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    parameters = {
        "seed": job.seed,
        "card": card_hash,
        INPUT_FINGERPRINT_PARAMETER: events.fingerprint,
    }
    return job.run_task(
        SIMULATE,
        parameters,
        body,
        log_name=SimulationWorkspace.log_name,
        accept_input=accept_input,
        force=force,
    )
