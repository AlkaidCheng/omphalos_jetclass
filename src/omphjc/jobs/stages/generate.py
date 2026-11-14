"""The generation stage: parton-level events from MadGraph."""

import shutil
from pathlib import Path

from omphjc.events.formats import EventFormat
from omphjc.jobs.job import Job
from omphjc.jobs.task import (
    EVENTS_OUTPUT,
    EventOutput,
    TaskCard,
    TaskOutcome,
    TaskRecord,
    TaskResult,
)
from omphjc.tools.madgraph.driver import MadGraphWorkspace, generate_events
from omphjc.tools.madgraph.lhe_file import LHEFile

GENERATE = "generate"
"""The stage's name and directory, ``<job>/generate/``."""

_CARDS_DIR = "cards"
# The cards MadGraph writes into its Cards directory that a job keeps as run:
# the file of each, under the name the record gives the card.
_MADGRAPH_CARD_FILE_NAMES = {
    "proc_card": "proc_card_mg5.dat",
    "run_card": "run_card.dat",
    "param_card": "param_card.dat",
    "madspin_card": "madspin_card.dat",
}


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

    The stage runs :func:`omphjc.tools.madgraph.driver.generate_events` in the
    job's ``generate/`` directory. It then copies the cards MadGraph ran with
    into ``generate/cards/``.

    Its parameters are the event count and the job's seed. A changed seed is
    therefore refused like any other change unless `force` is set.

    Its events are the LHE file, recorded with the event count in its banner
    and the fingerprint of its content
    (:class:`omphjc.tools.madgraph.lhe_file.LHEFile`).

    Its cards are the copies in ``generate/cards/``: the process card, the run
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
    task_dir = job.task_dir(GENERATE)

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        run = generate_events(
            job.spec,
            workdir=task_dir,
            n_events=n_events,
            seed=job.seed,
            n_cores=n_cores,
            timeout=timeout,
            overwrite=overwrite,
            log_dir=run_dir,
            mg5_path=mg5_path,
        )
        cards = _copy_cards(run.process_dir / "Cards", task_dir / _CARDS_DIR)
        return TaskOutcome(
            TaskResult(
                outputs={
                    EVENTS_OUTPUT: EventOutput(
                        run.output_path,
                        n_bytes=run.output_path.stat().st_size,
                        format=EventFormat.LHE,
                        n_events=run.banner.n_events,
                        fingerprint=LHEFile.read(run.output_path).fingerprint(),
                    )
                },
                cards=cards,
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
    return job.run_task(
        GENERATE, parameters, body, log_name=MadGraphWorkspace.log_name, force=force
    )


def _copy_cards(source_dir: Path, target_dir: Path) -> dict[str, TaskCard]:
    """Copy the cards present in `source_dir` into `target_dir`; return the copies."""
    target_dir.mkdir(parents=True, exist_ok=True)
    cards = {}
    for name, file_name in _MADGRAPH_CARD_FILE_NAMES.items():
        card_path = source_dir / file_name
        if not card_path.is_file():
            continue
        copy_path = target_dir / file_name
        shutil.copyfile(card_path, copy_path)
        cards[name] = TaskCard.from_path(copy_path)
    return cards
