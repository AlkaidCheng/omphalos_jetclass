"""The stages of a job, one module each; a stage is a function of a :class:`Job`.

A stage takes the job and its own arguments, builds the parameters it runs
with, and hands :meth:`omphjc.jobs.Job.run_stage` a body that returns what it
made. MadGraph generation (:mod:`omphjc.jobs.stages.generate`) is the only
stage so far.
"""

from omphjc.jobs.stages.generate import MADGRAPH, generate

__all__ = ["MADGRAPH", "generate"]
