"""The families of tasks: one abstract class for the tasks of each stage.

A task class is a member of the family of its stage, such as
:class:`ShowerTask` for a shower with Pythia or with another tool. The family
states the stage of its tasks, what they read and what they make. An input
names the family of the task it reads from
(:attr:`omphjc.jobs.task.TaskInput.upstream_class`) and one of its outputs, so
a simulation reads a shower whatever tool made it.
"""

from dataclasses import dataclass
from typing import ClassVar

from omphjc.jobs.task import EVENTS_INPUT, Task, TaskInput, TaskOutput
from omphjc.runs import EVENTS_OUTPUT
from omphjc.stages import GenerateStage, ShowerStage, SimulateStage, Stage

# The formats of the files that the families make: the format names of the
# classes that read them, omphjc.tools.madgraph.lhe_file.LHEFile and
# omphjc.events.delphes_root.DelphesROOTFile. The names are written here
# because importing the second class loads the array libraries.
LHE_FORMAT = "lhe"
DELPHES_ROOT_FORMAT = "delphes_root"


@dataclass(frozen=True, kw_only=True)
class GenerationTask(Task):
    """A task that generates the parton-level events of a job."""

    stage: ClassVar[Stage] = GenerateStage()
    outputs: ClassVar[tuple[TaskOutput, ...]] = (TaskOutput(EVENTS_OUTPUT, LHE_FORMAT),)


@dataclass(frozen=True, kw_only=True)
class ShowerTask(Task):
    """A task that showers the LHE events of the generation of its job."""

    stage: ClassVar[Stage] = ShowerStage()
    # A family is abstract: an input only tests a task with isinstance, so mypy's
    # rule against passing an abstract class as type[Task] does not apply.
    inputs: ClassVar[tuple[TaskInput, ...]] = (
        TaskInput(EVENTS_INPUT, GenerationTask),  # type: ignore[type-abstract]
    )
    outputs: ClassVar[tuple[TaskOutput, ...]] = (
        TaskOutput(EVENTS_OUTPUT, DELPHES_ROOT_FORMAT),
    )


@dataclass(frozen=True, kw_only=True)
class SimulationTask(Task):
    """A task that simulates the detector on the showered events of its job."""

    stage: ClassVar[Stage] = SimulateStage()
    inputs: ClassVar[tuple[TaskInput, ...]] = (
        TaskInput(EVENTS_INPUT, ShowerTask),  # type: ignore[type-abstract]
    )
    outputs: ClassVar[tuple[TaskOutput, ...]] = (
        TaskOutput(EVENTS_OUTPUT, DELPHES_ROOT_FORMAT),
    )
