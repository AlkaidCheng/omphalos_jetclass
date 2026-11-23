"""The task classes of omphjc, one for each piece of work that a job is made of.

A task class states its stage and its tool, holds its settings and makes its
files (:class:`omphjc.jobs.task.Task`):

- :class:`MadGraphGeneration` generates the parton-level events;
- :class:`PythiaShower` showers the generated events;
- :class:`DelphesSimulation` simulates the detector on the showered events.

Importing this package registers the three classes
(:data:`omphjc.jobs.task.TASK_REGISTRY`), so that a job can make the tasks it
finds on disk.
"""

from omphjc.tasks.delphes_simulation import DelphesSimulation
from omphjc.tasks.madgraph_generation import MadGraphGeneration
from omphjc.tasks.pythia_shower import PythiaShower

__all__ = ["DelphesSimulation", "MadGraphGeneration", "PythiaShower"]
