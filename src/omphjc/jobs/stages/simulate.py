"""The simulation stage: the Delphes simulation of the showered events."""

from typing import TYPE_CHECKING

import omphjc.tasks
from omphjc.jobs.job import Job
from omphjc.jobs.task import TaskRecord

if TYPE_CHECKING:
    # The adapter loads the array libraries, so it is not imported when a
    # command starts.
    from omphjc.tools.delphes.adapter import DelphesSimulator


def simulate(
    job: Job,
    simulator: "DelphesSimulator",
    *,
    accept_input: bool = False,
    force: bool = False,
) -> TaskRecord:
    """Simulate the detector on the showered events of `job` with Delphes.

    It makes a :class:`~omphjc.tasks.DelphesSimulation` from the options that
    `simulator` holds and runs it.

    Parameters
    ----------
    job : Job
        The job; its shower task must be done.
    simulator : DelphesSimulator
        The detector card, the time limit and the path of ``DelphesROOT``.
    accept_input : bool, optional
        Keep the result of the task although the events it reads have
        changed since it ran, and record that.
    force : bool, optional
        Run the task again even when its result could be kept.

    Returns
    -------
    TaskRecord
        The record of the task, kept or new.

    Raises
    ------
    Exception
        As :meth:`omphjc.jobs.Task.run` raises.
    """
    task = omphjc.tasks.DelphesSimulation(
        job,
        detector_card_path=simulator.detector_card_path,
        timeout_seconds=simulator.timeout_seconds,
        program_path=simulator.delphes_root_path,
    )
    return task.run(accept_input=accept_input, force=force)
