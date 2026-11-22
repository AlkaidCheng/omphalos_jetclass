"""The generation stage: parton-level events from MadGraph."""

import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from omphjc.data_files import FileRecord
from omphjc.jobs.identity import TaskIdentity
from omphjc.jobs.job import Job
from omphjc.jobs.task import TaskOutcome, TaskRecord
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.stages import GenerateStage
from omphjc.tools.madgraph.driver import generate_events
from omphjc.tools.madgraph.lhe_file import LHEFile

GENERATE_TASK = TaskIdentity(GenerateStage.name, "madgraph")
"""The task that generates the events of a job with MadGraph."""

_CARDS_DIR = "cards"


def generate(
    job: Job,
    *,
    n_events: int,
    n_cores: int | None = None,
    timeout: float | None = None,
    force: bool = False,
    mg5_path: Path | None = None,
) -> TaskRecord:
    """Generate the parton-level events of `job` with MadGraph.

    The task (:data:`GENERATE_TASK`) runs
    :func:`omphjc.tools.madgraph.driver.generate_events` in the job's
    ``generate-madgraph/`` directory. It then copies the cards MadGraph ran
    with into ``generate-madgraph/cards/``.

    Its parameters are the event count and the job's seed. A changed seed is
    therefore refused like any other change unless `force` is set.

    Its events are the LHE file, recorded with the event count in its banner
    and the fingerprint of its content
    (:class:`omphjc.tools.madgraph.lhe_file.LHEFile`).

    Its cards are the copies in ``generate-madgraph/cards/``: the process card, the run
    card, the parameter card and, with MadSpin, the MadSpin card.

    Its metadata holds:

    - the MadGraph version;
    - the cross section and its error, in pb;
    - the number of cores MadGraph ran on.

    Parameters
    ----------
    job : Job
        The job.
    n_events : int
        Events to generate.
    n_cores : int or None, optional
        Cores MadGraph may use; ``None`` for every usable CPU. A sample with
        MadSpin is reproduced only on the same number of cores.
    timeout : float or None, optional
        Seconds the stage may take; ``None`` for no limit.
    force : bool, optional
        Run the stage again even when its result could be kept.
    mg5_path : Path or None, optional
        MadGraph's ``bin/mg5_aMC``; ``None`` for the one on PATH.

    Returns
    -------
    TaskRecord
        The stage's record, kept or new.
    """
    task_dir = job.task_dir(GENERATE_TASK)

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        run = generate_events(
            job.spec,
            workdir=task_dir,
            n_events=n_events,
            seed=job.seed,
            n_cores=n_cores,
            timeout=timeout,
            overwrite=overwrite,
            log_path=log_path,
            mg5_path=mg5_path,
        )
        return TaskOutcome(
            RunResult(
                outputs={EVENTS_OUTPUT: LHEFile.record_file(run.output_path)},
                cards=_copy_cards(run.cards, task_dir / _CARDS_DIR),
                metadata={
                    "madgraph_version": run.banner.version,
                    "cross_section_pb": run.banner.cross_section_pb,
                    "cross_section_error_pb": run.banner.cross_section_error_pb,
                    "n_cores": run.n_cores,
                },
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    parameters = {"events": n_events, "seed": job.seed}
    return job.run_task(GENERATE_TASK, parameters, body, force=force)


def _copy_cards(
    cards: Mapping[str, FileRecord], target_dir: Path
) -> dict[str, FileRecord]:
    """Copy the file of each card of `cards` into `target_dir`.

    The record of each copy is returned under the name of the card. A copy
    has the size and the content of its card, so its record differs only in
    its path.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    copies = {}
    for name, card in cards.items():
        copy_path = target_dir / card.path.name
        shutil.copyfile(card.path, copy_path)
        copies[name] = replace(card, path=copy_path)
    return copies
