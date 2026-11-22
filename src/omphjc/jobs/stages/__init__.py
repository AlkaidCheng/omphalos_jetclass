"""The stages of a job, one module each.

A stage is a function that takes a :class:`Job` and its own arguments. It
builds the parameters of its task and passes :meth:`omphjc.jobs.Job.run_task`
a body that returns what the task made. Each module names the identity of
its task (:data:`GENERATE_TASK`, :data:`SHOWER_TASK`, :func:`simulate_task`),
and the shower and the simulation name the task whose events they read.

The stages so far:

- MadGraph generation (:mod:`omphjc.jobs.stages.generate`);
- the Pythia shower (:mod:`omphjc.jobs.stages.shower`);
- the detector simulation (:mod:`omphjc.jobs.stages.simulate`), run by a
  simulator such as :class:`omphjc.tools.delphes.adapter.DelphesSimulator`.
"""

from omphjc.jobs.stages.generate import GENERATE_TASK, generate
from omphjc.jobs.stages.shower import SHOWER_TASK, shower
from omphjc.jobs.stages.simulate import DetectorSimulator, simulate, simulate_task

__all__ = [
    "GENERATE_TASK",
    "SHOWER_TASK",
    "DetectorSimulator",
    "generate",
    "shower",
    "simulate",
    "simulate_task",
]
