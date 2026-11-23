"""The shower stage: Pythia 8 on the generated events, through ``DelphesPythia8``."""

from collections.abc import Mapping
from pathlib import Path

import omphjc.tasks
from omphjc.jobs.identity import TaskIdentity
from omphjc.jobs.job import Job
from omphjc.jobs.task import TaskRecord
from omphjc.processes.catalogue import SettingValue
from omphjc.stages import ShowerStage

SHOWER_TASK = TaskIdentity(ShowerStage.name, "pythia")
"""The task that showers the generated events of a job with Pythia 8."""


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

    It makes a :class:`~omphjc.tasks.PythiaShower` from its arguments and
    runs it.

    Parameters
    ----------
    job : Job
        The job; its generation task must be done.
    overrides : Mapping[str, SettingValue] or None, optional
        Pythia settings that replace or add to those of the process.
    timeout : float or None, optional
        Seconds ``DelphesPythia8`` may take. ``None`` sets no limit.
    accept_input : bool, optional
        Keep the result of the task although the events it reads have
        changed since it ran, and record that.
    force : bool, optional
        Run the task again even when its result could be kept.
    delphes_pythia8_path : Path or None, optional
        Path of Delphes's ``DelphesPythia8``. By default the program is
        looked up on PATH.

    Returns
    -------
    TaskRecord
        The record of the task, kept or new.

    Raises
    ------
    Exception
        As :meth:`omphjc.jobs.Task.run` raises.
    """
    task = omphjc.tasks.PythiaShower(
        job,
        overrides=dict(overrides or {}),
        timeout_seconds=timeout,
        program_path=delphes_pythia8_path,
    )
    return task.run(accept_input=accept_input, force=force)
