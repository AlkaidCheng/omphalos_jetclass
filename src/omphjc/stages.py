"""The stages of a job, each with a class that names it.

A stage is a physics step. The stages so far, in the order a job runs them:

1. the generation, which makes the parton-level events;
2. the shower, which reads the generated events;
3. the detector simulation, which reads the showered events.

A stage can have several tasks in a job, which differ in their tool or in
their tag. The identity of a task names its stage
(:class:`omphjc.jobs.identity.TaskIdentity`).

This module imports no other module of omphjc, so that the tools and the
jobs layer can both import it.
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Stage:
    """A physics step of a job, such as the parton shower.

    Each stage is a subclass that states its :attr:`name`.
    """

    name: ClassVar[str]
    """The name of the stage, which is also the name of its command."""


@dataclass(frozen=True)
class GenerateStage(Stage):
    """The generation of parton-level events, the first stage of a job."""

    name: ClassVar[str] = "generate"


@dataclass(frozen=True)
class ShowerStage(Stage):
    """The parton shower of a job, which reads the generated events."""

    name: ClassVar[str] = "shower"


@dataclass(frozen=True)
class SimulateStage(Stage):
    """The detector simulation of a job, which reads the showered events."""

    name: ClassVar[str] = "simulate"
