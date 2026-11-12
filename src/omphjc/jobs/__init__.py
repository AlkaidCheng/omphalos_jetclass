"""Jobs: one process and one job number, run in a directory of their own.

A job directory, ``<outdir>/<process>/job_<n>/``, holds ``manifest.json`` and
one directory per task, the work of one stage in the job. The job number fixes
the seed of every program the job runs; ``docs/reproducibility.md`` lists what
else a rerun's events depend on.
:class:`Job` builds the directory, keeps the manifest and applies the rerun
rules; :mod:`omphjc.jobs.manifest` defines the file; the functions in
:mod:`omphjc.jobs.stages` run the stages: MadGraph generation, the Pythia
shower, then the Delphes simulation.

Each stage calls a driver, such as :func:`omphjc.tools.madgraph.driver.generate_events`,
which returns a run record with absolute paths. The stage function builds a
:class:`TaskOutcome` from it: the :class:`TaskResult`, which holds the task's
outputs by name (a :class:`TaskOutput` each, an :class:`EventOutput` for an
event file) and its metadata, with the log and usage of the run.
:meth:`Job.run_task` adds the status, the start and finish times and the
parameters and stores them as a :class:`TaskRecord` in the job's
:class:`Manifest`, which writes every path relative to the job directory.
"""

from omphjc.jobs.job import (
    Job,
    StageCheck,
    StageStatus,
    TerminationError,
    exception_on_termination,
    job_seed,
    sha256,
)
from omphjc.jobs.manifest import (
    DONE,
    EVENTS_OUTPUT,
    FAILED,
    RUNNING,
    EventOutput,
    Manifest,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskResult,
)
from omphjc.jobs.stages import GENERATE, SHOWER, SIMULATE, generate, shower, simulate

__all__ = [
    "DONE",
    "EVENTS_OUTPUT",
    "FAILED",
    "GENERATE",
    "RUNNING",
    "SHOWER",
    "SIMULATE",
    "EventOutput",
    "Job",
    "Manifest",
    "StageCheck",
    "StageStatus",
    "TaskOutcome",
    "TaskOutput",
    "TaskRecord",
    "TaskResult",
    "TerminationError",
    "exception_on_termination",
    "generate",
    "job_seed",
    "sha256",
    "shower",
    "simulate",
]
