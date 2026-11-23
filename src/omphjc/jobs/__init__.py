"""Jobs: one process and one job number, run in a directory of their own.

A job directory, ``<outdir>/<process>/job_<n>/``, holds ``job.json``,
``manifest.json`` and one directory per task. A task is one piece of the work
of a stage in the job, done with one tool. Its directory is named after its
identity, such as ``shower-pythia``, and holds its record, ``task.json``. A
stage can have several tasks.

The job number fixes the seed of every program in the job.
``docs/reproducibility.md`` lists what else the events of a repeated job
depend on.

The modules, by what they hold::

    job.py          Job: the job directory, its seed, and the rules that decide
                    whether a task runs again (Job.run_task)
    task.py         Task, a task of a job; TaskStatus, whether a task is done
                    and its output files are intact; TaskRecord, the content
                    of task.json, with a TaskRun for each run; TaskOutcome,
                    what a stage function returns
    identity.py     JobIdentity, the content of job.json, and TaskIdentity, the
                    stage, the tool and the tag of a task
    manifest.py     Manifest, the content of manifest.json, which lists a
                    TaskSummary of each task's record
    job_file.py     JobFile, the base class of the job's JSON files
    stages/         one function per stage: generate, shower, simulate; each
                    names the identity of its task

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
   status, start and finish times and usage. It writes the identity of the
   task, the run, the parameters and the result to ``task.json`` as a
   :class:`TaskRecord`, with
   every path relative to the job directory.
"""

from omphjc.jobs.identity import JobIdentity, TaskIdentity
from omphjc.jobs.job import (
    Job,
    ReplacedRunError,
    TerminationError,
    exception_on_termination,
    job_seed,
    task_parameters,
)
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.stages import (
    GENERATE_TASK,
    SHOWER_TASK,
    DetectorSimulator,
    generate,
    shower,
    simulate,
    simulate_task,
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
    "GENERATE_TASK",
    "INTERRUPTED",
    "RUNNING",
    "SHOWER_TASK",
    "TaskRun",
    "AcceptedInput",
    "DetectorSimulator",
    "Job",
    "JobIdentity",
    "Manifest",
    "Task",
    "TaskIdentity",
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
    "simulate_task",
    "task_parameters",
]
