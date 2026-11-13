"""Jobs: one process and one job number, run in a directory of their own.

A job directory, ``<outdir>/<process>/job_<n>/``, holds ``job.json``,
``manifest.json`` and one directory per task, the work of one stage in the
job. A task directory holds the record of its task, ``task.json``. The job
number fixes the seed of every program the job runs;
``docs/reproducibility.md`` lists what else a rerun's events depend on.

The modules, by what they hold::

    job.py          Job: the job directory, its seed, and the rules that decide
                    whether a task runs again (Job.run_task)
    task.py         Task and TaskStatus, a task as found on disk; TaskRecord, the
                    content of task.json, with a TaskRun for each run, and
                    what a task makes: TaskResult, TaskOutput, EventOutput,
                    TaskOutcome
    identity.py     JobIdentity, the content of job.json
    manifest.py     Manifest, the content of manifest.json, which lists a
                    TaskSummary of each task's record
    record_file.py  RecordFile, the base class of the job's JSON files
    stages/         one function per stage: generate, shower, simulate

Each stage calls a driver, such as :func:`omphjc.tools.madgraph.driver.generate_events`,
which returns a run record with absolute paths. The stage function builds a
:class:`TaskOutcome` from it: the :class:`TaskResult`, which holds the task's
outputs by name (a :class:`TaskOutput` each, an :class:`EventOutput` for an
event file) and its metadata, with the log and usage of the run.
:meth:`Job.run_task` records the run as a :class:`TaskRun`, with its
status, start and finish times, log and usage, and writes it with the
parameters and the result as a :class:`TaskRecord` to ``task.json``, with
every path relative to the job directory.
"""

from omphjc.jobs.identity import JobIdentity
from omphjc.jobs.job import (
    Job,
    ReplacedRunError,
    TerminationError,
    exception_on_termination,
    job_seed,
    sha256,
)
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.stages import GENERATE, SHOWER, SIMULATE, generate, shower, simulate
from omphjc.jobs.task import (
    DONE,
    EVENTS_OUTPUT,
    FAILED,
    INPUT_FINGERPRINT_PARAMETER,
    INTERRUPTED,
    RUNNING,
    AcceptedInput,
    EventOutput,
    Task,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskResult,
    TaskRun,
    TaskStatus,
)

__all__ = [
    "DONE",
    "EVENTS_OUTPUT",
    "FAILED",
    "GENERATE",
    "INPUT_FINGERPRINT_PARAMETER",
    "INTERRUPTED",
    "RUNNING",
    "SHOWER",
    "SIMULATE",
    "TaskRun",
    "AcceptedInput",
    "EventOutput",
    "Job",
    "JobIdentity",
    "Manifest",
    "Task",
    "TaskOutcome",
    "TaskOutput",
    "TaskRecord",
    "TaskResult",
    "TaskStatus",
    "TaskSummary",
    "ReplacedRunError",
    "TerminationError",
    "exception_on_termination",
    "generate",
    "job_seed",
    "sha256",
    "shower",
    "simulate",
]
