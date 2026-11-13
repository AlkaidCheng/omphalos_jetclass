"""The stages of a job, one module each.

A stage is a function that takes a :class:`Job` and its own arguments. It
builds the parameters of its task and passes :meth:`omphjc.jobs.Job.run_task`
a body that returns what the task made.

The stages so far:

- MadGraph generation (:mod:`omphjc.jobs.stages.generate`);
- the Pythia shower (:mod:`omphjc.jobs.stages.shower`);
- the Delphes simulation (:mod:`omphjc.jobs.stages.simulate`).
"""

from omphjc.jobs.stages.generate import GENERATE, generate
from omphjc.jobs.stages.shower import SHOWER, shower
from omphjc.jobs.stages.simulate import SIMULATE, simulate

__all__ = ["GENERATE", "SHOWER", "SIMULATE", "generate", "shower", "simulate"]
