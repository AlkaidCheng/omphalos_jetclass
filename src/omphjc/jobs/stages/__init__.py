"""The stages of a job, one module each.

A stage is a function that takes a :class:`Job` and its own arguments. It
builds the parameters of its task and passes :meth:`omphjc.jobs.Job.run_task`
a body that returns what the task made. The class of each stage, which names
its task and the stage whose events it reads, is in :mod:`omphjc.stages`.

The stages so far:

- MadGraph generation (:mod:`omphjc.jobs.stages.generate`);
- the Pythia shower (:mod:`omphjc.jobs.stages.shower`);
- the detector simulation (:mod:`omphjc.jobs.stages.simulate`), run by a
  simulator such as :class:`omphjc.tools.delphes.adapter.DelphesSimulator`.
"""

from omphjc.jobs.stages.generate import generate
from omphjc.jobs.stages.shower import shower
from omphjc.jobs.stages.simulate import DetectorSimulator, simulate

__all__ = [
    "DetectorSimulator",
    "generate",
    "shower",
    "simulate",
]
