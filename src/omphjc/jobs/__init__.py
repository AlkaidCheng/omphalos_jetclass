"""Jobs: one process and one job number, run in a directory of their own.

A job directory, ``<outdir>/<process>/job_<n>/``, holds ``manifest.json`` and
one directory per stage. The job number fixes the seed of every program the
job runs, so a job is reproducible from its process and number alone.
:class:`Job` builds the directory, keeps the manifest and applies the rerun
rules; :mod:`omphjc.jobs.manifest` defines the file; the functions in
:mod:`omphjc.jobs.stages` run the stages: MadGraph generation, the Pythia
shower, then the Delphes simulation.
"""

from omphjc.jobs.job import (
    Job,
    StageOutcome,
    TerminationError,
    exception_on_termination,
    job_seed,
    sha256,
)
from omphjc.jobs.manifest import DONE, FAILED, RUNNING, Manifest, StageRecord
from omphjc.jobs.stages import MADGRAPH, SHOWER, SIMULATE, generate, shower, simulate

__all__ = [
    "DONE",
    "FAILED",
    "MADGRAPH",
    "RUNNING",
    "SHOWER",
    "SIMULATE",
    "Job",
    "Manifest",
    "StageOutcome",
    "StageRecord",
    "TerminationError",
    "exception_on_termination",
    "generate",
    "job_seed",
    "sha256",
    "shower",
    "simulate",
]
