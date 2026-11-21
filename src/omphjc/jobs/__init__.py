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
                    TaskOutcome, what a stage function returns
    identity.py     JobIdentity, the content of job.json
    manifest.py     Manifest, the content of manifest.json, which lists a
                    TaskSummary of each task's record
    job_file.py     JobFile, the base class of the job's JSON files
    stage.py        Stage, the base class of each stage's class: the name of
                    its task and the stage whose events it reads
    stages/         one function and one Stage class per stage: generate,
                    shower, simulate

How a stage is recorded:

1. The stage calls a driver, such as
   :func:`omphjc.tools.madgraph.driver.generate_events`. The driver returns a
   run record with absolute paths. The simulation stage calls its simulator
   (:class:`DetectorSimulator`), which calls the driver of its tool.
2. The stage function, or the simulator, builds a :class:`TaskOutcome` from
   the run record. The outcome holds the result of the run
   (:class:`omphjc.runs.RunResult`) and its usage. The result holds the
   task's outputs and cards by name, and its metadata. An output is a :class:`~omphjc.data_files.FileRecord`, or an
   :class:`~omphjc.events.formats.EventFileRecord` for an event file. A card
   is a :class:`~omphjc.data_files.FileRecord` that the driver's workspace
   made (:meth:`omphjc.workspace.ProgramWorkspace.card_records`).
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
    task_parameters,
)
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.stage import Stage
from omphjc.jobs.stages import (
    DetectorSimulator,
    GenerateStage,
    ShowerStage,
    SimulateStage,
    generate,
    shower,
    simulate,
)
from omphjc.jobs.task import (
    DONE,
    FAILED,
    INPUT_FINGERPRINT_PARAMETER,
    INTERRUPTED,
    RUNNING,
    AcceptedInput,
    Task,
    TaskOutcome,
    TaskRecord,
    TaskRun,
    TaskStatus,
)

__all__ = [
    "DONE",
    "FAILED",
    "INPUT_FINGERPRINT_PARAMETER",
    "INTERRUPTED",
    "RUNNING",
    "TaskRun",
    "AcceptedInput",
    "DetectorSimulator",
    "GenerateStage",
    "Job",
    "JobIdentity",
    "Manifest",
    "ShowerStage",
    "SimulateStage",
    "Stage",
    "Task",
    "TaskOutcome",
    "TaskRecord",
    "TaskStatus",
    "TaskSummary",
    "ReplacedRunError",
    "TerminationError",
    "exception_on_termination",
    "generate",
    "job_seed",
    "shower",
    "simulate",
    "task_parameters",
]
