"""The stage functions: each makes the task of its stage and runs it.

The work of a stage is that of its task class in :mod:`omphjc.tasks`.
"""

from omphjc.jobs.stages.generate import GENERATE_TASK, generate
from omphjc.jobs.stages.shower import SHOWER_TASK, shower
from omphjc.jobs.stages.simulate import simulate

__all__ = ["GENERATE_TASK", "SHOWER_TASK", "generate", "shower", "simulate"]
