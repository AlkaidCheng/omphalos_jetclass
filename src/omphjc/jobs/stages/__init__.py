"""The stages of a job, one module each; a stage is a function of a :class:`Job`.

A stage takes the job and its own arguments, builds the parameters it runs
with, and hands :meth:`omphjc.jobs.Job.run_stage` a body that returns what it
made. MadGraph generation (:mod:`omphjc.jobs.stages.generate`), the Pythia
shower (:mod:`omphjc.jobs.stages.shower`) and the Delphes simulation
(:mod:`omphjc.jobs.stages.simulate`) are the stages so far.
"""

from omphjc.jobs.stages.generate import GENERATE, generate
from omphjc.jobs.stages.shower import SHOWER, shower
from omphjc.jobs.stages.simulate import SIMULATE, simulate

__all__ = ["GENERATE", "SHOWER", "SIMULATE", "generate", "shower", "simulate"]
