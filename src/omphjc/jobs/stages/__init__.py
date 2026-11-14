"""The stages of a job, one module each.

A stage is a function that takes a :class:`Job` and its own arguments. It
builds the parameters of its task and passes :meth:`omphjc.jobs.Job.run_task`
a body that returns what the task made. Each stage also has a class, a
:class:`~omphjc.jobs.stage.Stage`, that names its task and the stage whose
events it reads.

The stages so far:

- MadGraph generation (:mod:`omphjc.jobs.stages.generate`);
- the Pythia shower (:mod:`omphjc.jobs.stages.shower`);
- the Delphes simulation (:mod:`omphjc.jobs.stages.simulate`).
"""

from omphjc.jobs.stages.generate import GenerateStage, generate
from omphjc.jobs.stages.shower import ShowerStage, shower
from omphjc.jobs.stages.simulate import SimulateStage, simulate

__all__ = [
    "GenerateStage",
    "ShowerStage",
    "SimulateStage",
    "generate",
    "shower",
    "simulate",
]
