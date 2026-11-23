"""The generation stage: parton-level events from MadGraph."""

from pathlib import Path

import omphjc.tasks
from omphjc.jobs.identity import TaskIdentity
from omphjc.jobs.job import Job
from omphjc.jobs.task import TaskRecord
from omphjc.stages import GenerateStage

GENERATE_TASK = TaskIdentity(GenerateStage.name, "madgraph")
"""The task that generates the events of a job with MadGraph."""


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

    It makes a :class:`~omphjc.tasks.MadGraphGeneration` from its arguments
    and runs it.

    Parameters
    ----------
    job : Job
        The job.
    n_events : int
        Events to generate.
    n_cores : int or None, optional
        Cores MadGraph may use. By default it uses every usable CPU.
    timeout : float or None, optional
        Seconds MadGraph may take. ``None`` sets no limit.
    force : bool, optional
        Run the task again even when its result could be kept.
    mg5_path : Path or None, optional
        Path of MadGraph's ``bin/mg5_aMC``. By default the program is looked
        up on PATH.

    Returns
    -------
    TaskRecord
        The record of the task, kept or new.

    Raises
    ------
    Exception
        As :meth:`omphjc.jobs.Task.run` raises.
    """
    task = omphjc.tasks.MadGraphGeneration(
        job,
        n_events=n_events,
        n_cores=n_cores,
        timeout_seconds=timeout,
        program_path=mg5_path,
    )
    return task.run(force=force)
