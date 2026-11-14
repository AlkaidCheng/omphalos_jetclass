"""A stage of a job: the name of its task and the stage whose events it reads.

A stage is a physics step, such as generation, the shower or the detector
simulation. The task of a stage in a job is the work the stage does there.
Each stage has a class, which derives from :class:`Stage` and lives in the
module of the stage (:mod:`omphjc.jobs.stages`).
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Stage:
    """A physics step of a job.

    A subclass names the stage in the class attribute below. It replaces
    :attr:`upstream_stage` when the stage reads the events of another stage.
    """

    name: ClassVar[str]
    """The name of the stage, which is also the name of its command."""

    @property
    def task_name(self) -> str:
        """The name of the stage's task in a job.

        It is also the directory of the task inside the job directory.
        """
        return self.name

    @property
    def upstream_stage(self) -> "Stage | None":
        """The stage whose events this stage reads, ``None`` for the first stage."""
        return None

    @property
    def command(self) -> str:
        """The command that runs the stage's task, as a message names it."""
        return f"omphjc {self.name}"
