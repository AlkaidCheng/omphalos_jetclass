"""Jobs: one process and one job number, run in a directory of their own.

A job directory, ``<outdir>/<process>/job_<n>/``, holds ``job.json``,
``manifest.json`` and one directory per task. A task is the work of one stage
in the job, and its directory holds its record, ``task.json``.

The job number fixes the seed of every program in the job.
``docs/reproducibility.md`` lists what else the events of a repeated job
depend on.

The modules, by what they hold::

    job.py          Job: the job directory, its seed, and the rules that decide
                    whether a task runs again (Job.run_task)
    task.py         Task and TaskStatus, a task as found on disk; TaskRecord, the
                    content of task.json, with a TaskRun for each run, and
                    what a task makes: TaskResult, TaskOutput, EventOutput,
                    TaskCard, TaskOutcome
    identity.py     JobIdentity, the content of job.json
    manifest.py     Manifest, the content of manifest.json, which lists a
                    TaskSummary of each task's record
    record_file.py  RecordFile, the base class of the job's JSON files
    stage.py        Stage, the base class of each stage's class: the name of
                    its task and the stage whose events it reads
    stages/         one function and one Stage class per stage: generate,
                    shower, simulate

How a stage is recorded:

1. The stage calls a driver, such as
   :func:`omphjc.tools.madgraph.driver.generate_events`. The driver returns a
   run record with absolute paths.
2. The stage function builds a :class:`TaskOutcome` from it. The outcome holds
   the :class:`TaskResult` and the usage of the run. The result holds the
   task's outputs and cards by name, and its metadata. An output is a
   :class:`TaskOutput`, or an :class:`EventOutput` for an event file. A card
   is a :class:`TaskCard`.
3. :meth:`Job.run_task` records the run as a :class:`TaskRun`, with its
   status, start and finish times, log and usage. It writes the run, the
   parameters and the result to ``task.json`` as a :class:`TaskRecord`, with
   every path relative to the job directory.
"""

from omphjc.jobs.identity import JobIdentity
from omphjc.jobs.job import (
    Job,
    ReplacedRunError,
    TerminationError,
    exception_on_termination,
    job_seed,
)
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.stage import Stage
from omphjc.jobs.stages import (
    GenerateStage,
    ShowerStage,
    SimulateStage,
    generate,
    shower,
    simulate,
)
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
    TaskCard,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskResult,
    TaskRun,
    TaskStatus,
    read_cards,
)

__all__ = [
    "DONE",
    "EVENTS_OUTPUT",
    "FAILED",
    "INPUT_FINGERPRINT_PARAMETER",
    "INTERRUPTED",
    "RUNNING",
    "TaskRun",
    "AcceptedInput",
    "EventOutput",
    "GenerateStage",
    "Job",
    "JobIdentity",
    "Manifest",
    "ShowerStage",
    "SimulateStage",
    "Stage",
    "Task",
    "TaskCard",
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
    "read_cards",
    "shower",
    "simulate",
]
