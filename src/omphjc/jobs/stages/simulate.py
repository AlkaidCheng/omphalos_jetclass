"""The simulation stage: a detector simulation of the showered events."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

from omphjc.data_files import Card
from omphjc.events.formats import EventFile, EventFormat
from omphjc.jobs.job import Job, task_parameters
from omphjc.jobs.stage import Stage
from omphjc.jobs.stages.shower import ShowerStage
from omphjc.jobs.task import INPUT_FINGERPRINT_PARAMETER, TaskOutcome, TaskRecord


@dataclass(frozen=True)
class SimulateStage(Stage):
    """The detector simulation of a job, which reads the showered events.

    Its task is named ``simulate`` and works in ``<job>/simulate/``.
    """

    name: ClassVar[str] = "simulate"

    @property
    def upstream_stage(self) -> ShowerStage:
        return ShowerStage()


class DetectorSimulator(Protocol):
    """A tool that simulates a detector on the showered events of a job.

    A simulator holds the configuration of its tool and the options of a run.
    The simulation stage asks it for its parameters and calls it to make the
    events.
    """

    @property
    def name(self) -> str:
        """The name of the simulator, such as ``"delphes"``."""
        ...

    @property
    def input_formats(self) -> frozenset[EventFormat]:
        """The formats of event file the simulator reads."""
        ...

    @property
    def log_name(self) -> str:
        """The name of the log file the simulator's program writes."""
        ...

    @property
    def card_classes(self) -> tuple[type[Card], ...]:
        """The class of each card a run of the simulator uses.

        Each class names its card, so the names are those of the cards in the
        result of the task.
        """
        ...

    def parameters(self, *, seed: int) -> dict[str, Any]:
        """Return the simulator's part of the task's parameters, as JSON values.

        The parameters hold `seed` only when the simulator uses it.
        """
        ...

    def simulate(
        self,
        event_file: EventFile,
        *,
        workdir: Path,
        seed: int,
        overwrite: bool,
        log_dir: Path,
    ) -> TaskOutcome:
        """Simulate the detector on the events in `event_file`.

        Parameters
        ----------
        event_file : EventFile
            The showered events, in one of :attr:`input_formats`.
        workdir : Path
            The directory of the task, where the simulator works.
        seed : int
            The seed of the job.
        overwrite : bool
            Whether to replace what an earlier run left in `workdir`.
        log_dir : Path
            The directory of the run, where the program writes its log.

        Returns
        -------
        TaskOutcome
            The simulated events as the output named
            :data:`~omphjc.jobs.task.EVENTS_OUTPUT`, the simulator's cards
            and metadata, and what the run took and set aside.
        """
        ...


def simulate(
    job: Job,
    simulator: DetectorSimulator,
    *,
    accept_input: bool = False,
    force: bool = False,
) -> TaskRecord:
    """Simulate the detector on the showered events of `job` with `simulator`.

    The stage reads the event file the shower stage made. `simulator` works
    in the job's ``simulate/`` directory with the job's seed.

    The parameters of the task are the fingerprint of the event file it
    reads and the parameters of `simulator`. A shower that is repeated with
    the same events therefore keeps its simulation.

    Parameters
    ----------
    job : Job
        The job; its shower stage must be done.
    simulator : DetectorSimulator
        The tool that simulates the detector.
    accept_input : bool, optional
        Keep the stage's result although the events it reads have changed
        since it ran, and record that (:meth:`omphjc.jobs.Job.run_task`). A
        stage that is not done runs as it does without the option.
    force : bool, optional
        Run the stage again even when its result could be kept.

    Returns
    -------
    TaskRecord
        The stage's record, kept or new.

    Raises
    ------
    ValueError
        If the shower stage of `job` has not run to completion. If
        `simulator` cannot read the format of the showered events. If the
        parameters of `simulator` use a key of the stage. If `accept_input`
        and `force` are both set.
    """
    stage = SimulateStage()
    events = job.require_events(stage.upstream_stage, for_tool=simulator)
    workdir = job.task_dir(stage)
    parameters = task_parameters(
        {INPUT_FINGERPRINT_PARAMETER: events.fingerprint},
        simulator.parameters(seed=job.seed),
        tool_name=simulator.name,
    )

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        return simulator.simulate(
            EventFile(events.path, events.format),
            workdir=workdir,
            seed=job.seed,
            overwrite=overwrite,
            log_dir=run_dir,
        )

    return job.run_task(
        stage,
        parameters,
        body,
        log_name=simulator.log_name,
        accept_input=accept_input,
        force=force,
    )
