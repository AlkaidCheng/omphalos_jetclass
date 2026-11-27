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

    job.py          Job: the job directory, its seed, its tasks and its manifest
    task.py         Task, the base class of a task, which runs the task and
                    writes its record; TaskRegistry and TASK_REGISTRY, the
                    registry of the task classes; TaskRecord, the content
                    of task.json, with a TaskRun for each run and its
                    RunStatus, and TaskRecordError, the refusal of a
                    task.json that cannot be read; TaskOutcome, what a run
                    made
    identity.py     JobIdentity, the content of job.json, and TaskIdentity, the
                    stage, the tool and the tag of a task
    manifest.py     Manifest, the content of manifest.json, which lists a
                    TaskSummary of each task's record
    job_file.py     JobFile, the base class of the job's JSON files, and
                    JobFileError, the refusal of a file that cannot be read

The classes of the tasks are in :mod:`omphjc.tasks`.

How a task is recorded:

1. :meth:`Task.run` calls :meth:`Task.execute` of the task's class, which
   calls a driver, such as
   :func:`omphjc.tools.madgraph.driver.generate_events`. The driver returns a
   run record with absolute paths.
2. :meth:`Task.execute` builds a :class:`TaskOutcome` from the run record.
   The outcome holds the result of the run (:class:`omphjc.runs.RunResult`)
   and its usage. The result holds the task's outputs and cards by name, and
   its metadata. An output is a :class:`~omphjc.data_files.FileRecord`, or an
   :class:`~omphjc.events.formats.EventFileRecord` for an event file. A card
   is a :class:`~omphjc.data_files.FileRecord` that the driver's workspace
   made (:meth:`omphjc.workspace.ProgramWorkspace.card_records`).
3. :meth:`Task.run` records the run as a :class:`TaskRun`, with its status,
   start and finish times and usage. It writes the identity of the task, its
   settings, the run, the parameters, its inputs (an
   :class:`InputRecord` each) and the result to ``task.json`` as a
   :class:`TaskRecord`, with every path relative to the job directory.
"""

from omphjc.jobs.identity import JobIdentity, TaskIdentity
from omphjc.jobs.job import Job, exception_on_termination, job_seed
from omphjc.jobs.job_file import JobFileError
from omphjc.jobs.manifest import Manifest, TaskSummary
from omphjc.jobs.task import (
    EVENTS_INPUT,
    TASK_REGISTRY,
    AcceptedInput,
    InputRecord,
    ReplacedRunError,
    RunStatus,
    Task,
    TaskInput,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskRecordError,
    TaskRegistry,
    TaskRun,
    TaskStatus,
    TerminationError,
)

__all__ = [
    "EVENTS_INPUT",
    "TASK_REGISTRY",
    "AcceptedInput",
    "InputRecord",
    "Job",
    "JobFileError",
    "JobIdentity",
    "Manifest",
    "ReplacedRunError",
    "RunStatus",
    "Task",
    "TaskIdentity",
    "TaskInput",
    "TaskOutput",
    "TaskOutcome",
    "TaskRecord",
    "TaskRecordError",
    "TaskRegistry",
    "TaskRun",
    "TaskStatus",
    "TaskSummary",
    "TerminationError",
    "exception_on_termination",
    "job_seed",
]
