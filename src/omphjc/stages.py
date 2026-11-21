"""The stages of a job, each with a class that names it.

A stage is a physics step. The stages so far, in the order a job runs them:

1. the generation, which makes the parton-level events;
2. the shower, which reads the generated events;
3. the detector simulation, which reads the showered events.

The class of a stage states the name of the stage, the name of its task in a
job, and the stage whose events it reads.

This module imports no other module of omphjc, so that the tools and the
jobs layer can both import it.
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Stage:
    """A physics step of a job, such as the parton shower.

    Each stage is a subclass that states its :attr:`name`. A stage that reads
    the events of another stage also overrides :attr:`upstream_stage`.
    """

    name: ClassVar[str]
    """The name of the stage, which is also the name of its command."""

    @property
    def task_name(self) -> str:
        """The name of the stage's task in a job.

        The directory of the task, inside the job directory, has the same
        name.
        """
        return self.name

    @property
    def upstream_stage(self) -> "Stage | None":
        """The stage whose events this stage reads, ``None`` for the first stage."""
        return None

    @property
    def command(self) -> str:
        """The command that runs the stage's task, such as ``omphjc shower``."""
        return f"omphjc {self.name}"


@dataclass(frozen=True)
class GenerateStage(Stage):
    """The generation of parton-level events, the first stage of a job.

    Its task is named ``generate`` and works in ``<job>/generate/``.
    """

    name: ClassVar[str] = "generate"


@dataclass(frozen=True)
class ShowerStage(Stage):
    """The parton shower of a job, which reads the generated events.

    Its task is named ``shower`` and works in ``<job>/shower/``.
    """

    name: ClassVar[str] = "shower"

    @property
    def upstream_stage(self) -> GenerateStage:
        return GenerateStage()


@dataclass(frozen=True)
class SimulateStage(Stage):
    """The detector simulation of a job, which reads the showered events.

    Its task is named ``simulate`` and works in ``<job>/simulate/``.
    """

    name: ClassVar[str] = "simulate"

    @property
    def upstream_stage(self) -> ShowerStage:
        return ShowerStage()
