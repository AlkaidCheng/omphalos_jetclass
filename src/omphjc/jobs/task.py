"""A task of a job: its class, its record, what it made, and its status.

A task is one piece of the work of a stage in a job, done with one tool.
The tasks that do the same work, such as showering events with Pythia, are
objects of one class, a subclass of :class:`Task`. The classes of omphjc's
tasks are in :mod:`omphjc.tasks`.

A task has a directory of its own in the job directory. Its record is the
file ``task.json`` in that directory, written as::

    {
      "schema": 1,
      "identity": {"stage": "generate", "tool": "madgraph", "tag": null},
      "settings": {
        "timeout_seconds": null, "program_path": null, "n_events": 1000, "n_cores": null
      },
      "parameters": {"n_events": 1000, "seed": 10000001},
      "inputs": {},
      "result": {
        "outputs": {
          "events": {
            "path": "generate-madgraph/HToBB/Events/run_01/unweighted_events.lhe.gz",
            "n_bytes": 12345678,
            "fingerprint": "lhe-v1:<sha256>",
            "format": "lhe",
            "n_events": 1000
          }
        },
        "cards": {
          "run_card": {
            "path": "generate-madgraph/cards/run_card.dat",
            "n_bytes": 18446,
            "fingerprint": "run_card-v1:<sha256>"
          }
        },
        "metadata": {
          "madgraph_version": "3.8.1",
          "cross_section_pb": 1.23,
          "cross_section_error_pb": 0.01
        }
      },
      "runs": [
        {
          "run_id": "20261023T010000Z-4f9c2a1e",
          "status": "failed",
          "started": "2026-10-23T01:00:00+00:00",
          "host": "node01",
          "finished": "2026-10-23T01:05:00+00:00",
          "usage": {"wall_seconds": 301.2},
          "set_aside": null,
          "error": "MadGraph exited with status 1"
        },
        {
          "run_id": "20261023T020000Z-b81d07c3",
          "status": "done",
          "started": "2026-10-23T02:00:00+00:00",
          "host": "node01",
          "finished": "2026-10-23T02:20:00+00:00",
          "usage": {
            "wall_seconds": 1203.4, "cpu_seconds": 9012.7, "peak_memory_mib": 812.5
          },
          "set_aside": null,
          "error": null
        }
      ]
    }

Every path in the record is relative to the job directory. The top-level
keys are:

``schema``
    The layout version of the file (:mod:`omphjc.jobs.record_file`).
``identity``
    The stage, the tool and the tag of the task
    (:class:`~omphjc.jobs.identity.TaskIdentity`). The directory of the task
    is named after them.
``settings``
    What the task was made with: the fields of its class, such as the event
    count of a generation or the time limit of its program
    (:meth:`Task.settings`). A job makes the task again from them
    (:meth:`omphjc.jobs.Job.get_task`).
``parameters``
    What fixes the files of the task apart from its inputs, including the
    seed when the task uses one (:meth:`Task.parameters`). A later request
    compares its own parameters with these to decide whether the result can
    be kept. A setting that does not change the files, such as the time
    limit, is not among them.
``inputs``
    What the task read from other tasks of its job, by the name of the input
    (:attr:`Task.inputs`). The mapping is empty for a task without an input.
``result``
    What the task made (:class:`~omphjc.runs.RunResult`). It is ``null`` unless the
    latest run is done.
``runs``
    The runs of the task, oldest first.

**The result.** ``outputs`` holds the files the task made, under the names
its class gives them. Each output has its ``path``, its size in bytes,
``n_bytes``, and the ``fingerprint`` of its content in its format, which is
``null`` for a file recorded without being read
(:class:`~omphjc.file_content.FileRecord`). An event file also has its
``format`` and the number of events it holds
(:class:`~omphjc.events.formats.EventFileRecord`). The next task reads the
output named ``events``.

``cards`` holds the cards of the task, under the names their classes give
them. A card is a file that steers the task's program, such as a run card or
a detector card. Each card is recorded as an output is, with the fingerprint
of its parsed content (:class:`~omphjc.file_content.Card`), so that two cards
that differ only in comments and layout have one fingerprint. The cards are
a record for the reader: they do not count when the status of the task is
judged.

``metadata`` is what is known about the task and the sample it made. The
class of the task chooses its keys.

**The runs.** Repeating a task with the same parameters adds a run to the
record. This happens after a failure, an interruption or the loss of an
output. A run with other parameters, or under ``force``, starts a new record
with one run, and the logs of the earlier runs are removed.

The programs of a run write their output to a log of its own,
``logs/<run_id>.log`` in the directory of the task (:meth:`Task.log_path`).
The file is missing when no program of the run started.

The record does not store why a task was repeated. The status of the
previous run says it: that run failed, was interrupted, or was ``"done"`` and
an output went missing afterwards.

Each run has these keys:

``run_id``
    The start time of the run in UTC, followed by eight random hexadecimal
    digits. The IDs of a task's runs therefore sort by start time.
``status``
    How the run ended: ``"running"``, ``"done"``, ``"failed"`` or
    ``"interrupted"`` (:class:`RunStatus`). A run is ``"failed"`` when its
    program or omphjc failed. It is ``"interrupted"`` when a signal ended
    it, and ``error`` then holds the signal. A run that a killed process left
    ``"running"`` is marked ``"interrupted"`` when the next run starts.
``started``, ``finished``
    The times at which the run started and ended, in UTC. ``finished`` is
    ``null`` for a run whose end was not recorded.
``host``
    The name of the machine the run was on.
``usage``
    What the run took: its wall time, and the CPU time and peak memory (MiB)
    of the external program's processes where the platform reports them.
``set_aside``
    The folder into which the run moved what an earlier run left and it
    could not confirm as that run's (:mod:`omphjc.stamps`). The value is
    ``null`` when the run moved nothing.
``error``
    The error of a failed run, or the signal that ended an interrupted one.
    The value is ``null`` otherwise.

**The inputs.** Each input (:class:`InputRecord`) holds the name of the
``task`` that made its file, the ``fingerprint`` of the file that the task
read, and ``accepted``. The record of a shower holds::

    "inputs": {
      "events": {
        "task": "generate-madgraph",
        "fingerprint": "lhe-v1:<sha256>",
        "accepted": null
      }
    }

A later request compares the fingerprint of the file of each input with
the recorded one, as it compares the parameters. The task is not compared.

``accepted`` is set when the task was kept for another file of the input
than the one it read (:meth:`Task.run`). It holds its ``fingerprint`` and the
time of the acceptance, ``accepted_at``, and it is ``null`` otherwise. A
further run of the task clears it.

**Making a record.** These methods of :class:`TaskRecord` return a new
record:

- :meth:`TaskRecord.running` starts the record of a task.
- :meth:`TaskRecord.rerun` adds a run to it.
- :meth:`TaskRecord.with_accepted_inputs` records an acceptance.
- :meth:`TaskRecord.failed`, :meth:`TaskRecord.interrupted` and
  :meth:`TaskRecord.done` record how the latest run ended. ``done`` also
  stores the result of the :class:`TaskOutcome` that
  :meth:`Task.execute` returned, unchanged.

**Record and status.** A record only says how each run of the task ended.
Whether the task is done at this moment also depends on its output files,
because they may have been deleted or changed since. The status of a task
(:attr:`Task.status`, a :class:`TaskStatus`) takes the record and the files
into account. A task whose latest run is done has :attr:`TaskStatus.DONE`
only while its outputs are intact.
"""

import secrets
import socket
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, get_args

from omphjc.comparison import Difference
from omphjc.events.formats import EventFileRecord
from omphjc.file_content import FileRecord
from omphjc.jobs.identity import TaskIdentity
from omphjc.jobs.record_file import RecordFile, RecordFileError
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.safe_paths import inside, remove_inside
from omphjc.stages import Stage
from omphjc.stamps import COMPACT_UTC_FORMAT

if TYPE_CHECKING:
    from omphjc.jobs.job import Job

_RUN_ID_RANDOM_BYTES = 4
"""Random bytes in a run ID, written as twice as many hexadecimal digits."""


@dataclass(frozen=True)
class TaskOutcome:
    """What :meth:`Task.execute` returns: the task's result and the run's own facts.

    Parameters
    ----------
    result : RunResult
        What the task made.
    usage : dict[str, float]
        Resources the task's program used, such as ``cpu_seconds`` and
        ``peak_memory_mib``. :meth:`Task.run` adds ``wall_seconds``.
    set_aside_dir : Path or None
        The folder, inside the job directory, that holds what an earlier run
        left and this run could not confirm as that run's
        (:mod:`omphjc.stamps`). It is ``None`` when nothing was moved.
    """

    result: RunResult
    usage: dict[str, float] = field(default_factory=dict)
    set_aside_dir: Path | None = None


class RunStatus(str, Enum):
    """How a run of a task ended, or that it is still running.

    A status is written to ``task.json`` as its value, such as ``"done"``.
    """

    RUNNING = "running"
    """The run has started, and its end is not recorded."""
    DONE = "done"
    """The run made the files of the task."""
    FAILED = "failed"
    """The program of the run, or omphjc, failed."""
    INTERRUPTED = "interrupted"
    """A signal ended the run, or a later run found it left running."""


@dataclass(frozen=True, kw_only=True)
class TaskRun:
    """One run of a task; the module docstring describes the fields."""

    run_id: str
    status: RunStatus
    started: str
    host: str
    finished: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: str | None = None
    error: str | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "TaskRun":
        """Return the run that `record` describes, as ``task.json`` holds it.

        Raises
        ------
        ValueError
            If the status of the run is not a value of :class:`RunStatus`.
        """
        try:
            status = RunStatus(record["status"])
        except ValueError:
            values = [repr(status.value) for status in RunStatus]
            expected = f"{', '.join(values[:-1])} or {values[-1]}"
            raise ValueError(
                f"the status of a run must be {expected}, got {record['status']!r}"
            ) from None
        return cls(**{**record, "status": status})

    @classmethod
    def started_now(cls) -> "TaskRun":
        """Record a run that starts now on this host, with a new run ID."""
        start_time = datetime.now(timezone.utc)
        random_digits = secrets.token_hex(_RUN_ID_RANDOM_BYTES)
        return cls(
            run_id=f"{start_time.strftime(COMPACT_UTC_FORMAT)}-{random_digits}",
            status=RunStatus.RUNNING,
            started=start_time.isoformat(timespec="seconds"),
            host=socket.gethostname(),
        )

    def ended_now(
        self,
        status: RunStatus,
        *,
        error: str | None = None,
        usage: dict[str, float] | None = None,
        set_aside: str | None = None,
    ) -> "TaskRun":
        """Record that the run ended now with `status`.

        The run keeps its ID, its start time and its host. `error`, `usage` and
        `set_aside` hold what the module docstring describes, and each is empty
        unless it is given.
        """
        return replace(
            self,
            status=status,
            finished=timestamp(),
            error=error,
            usage={} if usage is None else usage,
            set_aside=set_aside,
        )


@dataclass(frozen=True)
class AcceptedInput:
    """A file of an input that a task was kept for although it read another.

    Parameters
    ----------
    fingerprint : str
        The fingerprint of the file that the task was kept for.
    accepted_at : str
        The time of the acceptance, in the format of :func:`timestamp`.
    """

    fingerprint: str
    accepted_at: str


@dataclass(frozen=True)
class InputRecord:
    """What a task read for one of its inputs.

    Parameters
    ----------
    task : str
        The name of the task that made the file, such as
        ``"generate-madgraph"``.
    fingerprint : str
        The fingerprint of the file that the task read.
    accepted : AcceptedInput or None, optional
        Another file of the input that the task was kept for, or ``None``.
    """

    task: str
    fingerprint: str
    accepted: AcceptedInput | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "InputRecord":
        """Return the input that `record` describes, as ``task.json`` holds it."""
        accepted = record["accepted"]
        return cls(
            **{
                **record,
                "accepted": None if accepted is None else AcceptedInput(**accepted),
            }
        )

    def is_kept_for(self, fingerprint: str) -> bool:
        """Whether the task is kept for the file with `fingerprint`.

        It must be the file that the task read or the one that it was
        accepted for.
        """
        return fingerprint == self.fingerprint or (
            self.accepted is not None and self.accepted.fingerprint == fingerprint
        )


class TaskRecordError(RecordFileError):
    """A ``task.json`` that cannot be read as the record of its task.

    Unless the error is given another remedy, the message ends with the likely
    cause and the ways to go on:

    - The cause: the file was changed after omphjc wrote it, or another version
      of omphjc wrote it.
    - The ways to go on: restore the file, or remove it and run the task again.
    """

    def __init__(self, path: Path, problem: str, remedy: str | None = None) -> None:
        if remedy is None:
            remedy = (
                "The file was changed after omphjc wrote it, or another version "
                "of omphjc wrote it. Restore the file, or remove it and run the "
                "task again."
            )
        super().__init__(path, problem, remedy)


@dataclass(frozen=True)
class TaskRecord(RecordFile):
    """What one task did; the module docstring describes the fields.

    Raises
    ------
    ValueError
        If the record has no run. If it holds a result while its latest run
        is not done, or no result while that run is done. If it holds an
        accepted input while its latest run is not done.
    """

    file_name: ClassVar[str] = "task.json"
    read_error: ClassVar[type[RecordFileError]] = TaskRecordError

    identity: TaskIdentity
    settings: dict[str, Any]
    parameters: dict[str, Any]
    runs: tuple[TaskRun, ...]
    result: RunResult | None = None
    inputs: dict[str, InputRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.runs:
            raise ValueError(
                "the record lists no run, and a task record lists at least the run "
                "that made it"
            )
        status = self.latest_run.status.value
        if self.is_done and self.result is None:
            raise ValueError(
                f"the latest run is {status!r}, so the record should hold the "
                "result of that run, but it holds none"
            )
        if not self.is_done and self.result is not None:
            raise ValueError(
                f"the latest run is {status!r}, so the record should hold no "
                "result, but it holds one"
            )
        accepted_names = [
            repr(input_name)
            for input_name, input_record in self.inputs.items()
            if input_record.accepted is not None
        ]
        if not self.is_done and accepted_names:
            raise ValueError(
                f"the latest run is {status!r}, so no input should hold an "
                f"acceptance, but {' and '.join(accepted_names)} "
                f"{'holds' if len(accepted_names) == 1 else 'hold'} one"
            )

    @property
    def latest_run(self) -> TaskRun:
        """The latest run of the task."""
        return self.runs[-1]

    @property
    def is_done(self) -> bool:
        """Whether the latest run of the task is done."""
        return self.latest_run.status is RunStatus.DONE

    @property
    def input_fingerprints(self) -> dict[str, str]:
        """The fingerprint of the file of each input that the task read, by name."""
        return {
            input_name: input_record.fingerprint
            for input_name, input_record in self.inputs.items()
        }

    @property
    def outputs(self) -> dict[str, FileRecord]:
        """The outputs of the task, under the names its class gives them.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().outputs

    @property
    def events(self) -> EventFileRecord | None:
        """The event file the task made, which the next task reads.

        It is ``None`` when the task made no event file.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().events

    @property
    def cards(self) -> dict[str, FileRecord]:
        """The cards the task's program read, under the names its stage gives them.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().cards

    @property
    def metadata(self) -> dict[str, Any]:
        """What is known about the task and the sample it made.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().metadata

    def as_record(self) -> dict[str, Any]:
        """Return the identity, the settings, the parameters, the inputs, the
        result and the runs by name."""
        return {
            "identity": asdict(self.identity),
            "settings": self.settings,
            "parameters": self.parameters,
            "inputs": {
                input_name: asdict(input_record)
                for input_name, input_record in self.inputs.items()
            },
            "result": None if self.result is None else asdict(self.result),
            "runs": [asdict(run) for run in self.runs],
        }

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "TaskRecord":
        """Return the task record that `record` describes.

        A path in the result becomes an absolute path under `root_dir`. A
        record without runs is refused.
        """
        values = dict(record)
        identity = TaskIdentity(**values.pop("identity"))
        runs = tuple(TaskRun.from_record(run) for run in values.pop("runs", ()))
        result = values.pop("result")
        inputs = {
            input_name: InputRecord.from_record(input_record)
            for input_name, input_record in values.pop("inputs").items()
        }
        return cls(
            identity=identity,
            **values,
            runs=runs,
            result=None if result is None else RunResult.from_record(result, root_dir),
            inputs=inputs,
        )

    @classmethod
    def read(cls, path: Path, *, root_dir: Path | None = None) -> "TaskRecord":
        """Return the record in the file `path`, the ``task.json`` of a task.

        Raises
        ------
        TaskRecordError
            If :meth:`omphjc.jobs.record_file.RecordFile.read` refuses the file, or
            if the directory of `path` is not named after the task that the
            record identifies.
        """
        record = super().read(path, root_dir=root_dir)
        if record.identity.name != path.parent.name:
            raise TaskRecordError(
                path,
                f"is the record of the task {record.identity.name}, but its "
                f"directory is named {path.parent.name}",
                f"Name the directory {record.identity.name} again, or remove it.",
            )
        return record

    @classmethod
    def running(
        cls,
        identity: TaskIdentity,
        settings: dict[str, Any],
        parameters: dict[str, Any],
        inputs: dict[str, InputRecord],
    ) -> "TaskRecord":
        """Start the record of the task `identity` with its first run."""
        return cls(
            identity, settings, parameters, (TaskRun.started_now(),), inputs=inputs
        )

    def rerun(self) -> "TaskRecord":
        """Record that the task runs again.

        A latest run that is still ``running`` was left by a killed process,
        so it becomes ``interrupted``. The new run has no result yet, and no
        input holds an acceptance.
        """
        earlier_runs = self.runs
        if self.latest_run.status is RunStatus.RUNNING:
            abandoned_run = replace(self.latest_run, status=RunStatus.INTERRUPTED)
            earlier_runs = (*self.runs[:-1], abandoned_run)
        runs = (*earlier_runs, TaskRun.started_now())
        inputs = {
            input_name: replace(input_record, accepted=None)
            for input_name, input_record in self.inputs.items()
        }
        return replace(self, runs=runs, result=None, inputs=inputs)

    def with_accepted_inputs(
        self, input_fingerprints: Mapping[str, str]
    ) -> "TaskRecord":
        """Record that the task is kept for the changed inputs of `input_fingerprints`.

        `input_fingerprints` holds the current fingerprint of each input, by
        the name of the input. An input that is not kept for its fingerprint
        (:meth:`InputRecord.is_kept_for`) is accepted for it, and the time of
        the acceptance is recorded; it replaces an earlier acceptance. The
        other inputs are left as they are.
        """
        accepted_at = timestamp()
        inputs = {}
        for input_name, input_record in self.inputs.items():
            fingerprint = input_fingerprints[input_name]
            if not input_record.is_kept_for(fingerprint):
                accepted = AcceptedInput(fingerprint, accepted_at)
                input_record = replace(input_record, accepted=accepted)
            inputs[input_name] = input_record
        return replace(self, inputs=inputs)

    def is_kept_for(self, input_fingerprints: Mapping[str, str]) -> bool:
        """Whether the task is kept for inputs with the given fingerprints.

        `input_fingerprints` holds the fingerprint of each input, by the name
        of the input. Each must be the one that the task read or the one that
        it was accepted for.
        """
        return input_fingerprints.keys() == self.inputs.keys() and all(
            self.inputs[input_name].is_kept_for(fingerprint)
            for input_name, fingerprint in input_fingerprints.items()
        )

    def failed(self, *, error: str) -> "TaskRecord":
        """Record that the latest run failed with `error`."""
        run = self.latest_run.ended_now(RunStatus.FAILED, error=error)
        return replace(self, runs=(*self.runs[:-1], run))

    def interrupted(self, *, error: str) -> "TaskRecord":
        """Record that a signal interrupted the latest run; `error` names it."""
        run = self.latest_run.ended_now(RunStatus.INTERRUPTED, error=error)
        return replace(self, runs=(*self.runs[:-1], run))

    def done(
        self, outcome: TaskOutcome, *, wall_seconds: float, root_dir: Path
    ) -> "TaskRecord":
        """Record that the latest run is done, with what `outcome` says it made.

        `wall_seconds` is added to the usage of `outcome`, and its set-aside
        folder is made relative to `root_dir`, the job directory.
        """
        set_aside_dir = outcome.set_aside_dir
        run = self.latest_run.ended_now(
            RunStatus.DONE,
            usage={"wall_seconds": round(wall_seconds, 3), **outcome.usage},
            set_aside=(
                None
                if set_aside_dir is None
                else set_aside_dir.relative_to(root_dir).as_posix()
            ),
        )
        return replace(self, runs=(*self.runs[:-1], run), result=outcome.result)

    def current_status(self) -> "tuple[TaskStatus, str]":
        """Return the status of the task now, with its output files validated.

        The record says how the latest run ended. The output files may have
        been deleted or changed since, so the status is:

        - not done, when the latest run is not done;
        - done, when every output file has the size in the record;
        - missing output, when an output file is not there;
        - changed, when an output file has another size. A changed file
          counts before a missing one.

        Returns
        -------
        tuple[TaskStatus, str]
            The status, and a clause that names the output that is missing,
            or the output of another size with the size found and the size
            recorded. The clause is empty for the other statuses.
        """
        if not self.is_done:
            return TaskStatus.NOT_DONE, ""
        status, detail = TaskStatus.DONE, ""
        for output in self.outputs.values():
            try:
                n_bytes = output.path.stat().st_size
            except FileNotFoundError:
                status, detail = TaskStatus.MISSING_OUTPUT, f"{output.path} is missing"
                continue
            if n_bytes != output.n_bytes:
                status = TaskStatus.CHANGED
                detail = (
                    f"{output.path} holds {n_bytes} bytes, not the "
                    f"{output.n_bytes} the {self.identity.name} task recorded"
                )
                break
        return status, detail

    def _done_result(self) -> RunResult:
        """Return the result of a record whose latest run is done."""
        if self.result is None:
            raise ValueError(
                "The task record has no result: its latest run has status "
                f"{self.latest_run.status.value!r}"
            )
        return self.result


LOGS_DIR = "logs"
"""The directory, in a task's directory, that holds the log of each run."""


class TaskStatus(Enum):
    """The state of a task, judged from its record and its output files."""

    NOT_DONE = "not done"
    """The task has no record, or its record does not say done."""
    MISSING_OUTPUT = "missing output"
    """The task is recorded as done and one of its outputs is not on disk."""
    CHANGED = "changed"
    """The task is recorded as done and one of its outputs has another size
    than recorded."""
    DONE = "done"
    """The task is recorded as done and each output has its recorded size."""


class TerminationError(RuntimeError):
    """The process received a termination signal."""


class ReplacedRunError(RuntimeError):
    """A newer run of the task started before this one ended.

    The end of this run is then not recorded.
    """


# What ends a run without its program or omphjc failing.
_INTERRUPTIONS = (TerminationError, KeyboardInterrupt)

# The names of the fields of a task that are not settings: its job; its tag,
# which is a part of its identity; and the tasks it names for its inputs, which
# the record holds in its inputs.
_NON_SETTING_FIELD_NAMES = ("job", "tag", "upstream")


@dataclass(frozen=True)
class TaskOutput:
    """An output of a task: a file that each run of the task makes, under a name.

    Parameters
    ----------
    name : str
        The name of the output in the result of a run, such as ``"events"``.
    file_format : str
        The format of the file: the :attr:`~omphjc.file_content.FileContent.format_name`
        of the class that reads it, such as ``"lhe"`` or ``"delphes_root"``.
        A task that reads the output knows its parser from it, and the
        fingerprint of the file in a record carries it
        (:attr:`~omphjc.file_content.FileRecord.file_format`).
    """

    name: str
    file_format: str


@dataclass(frozen=True)
class TaskInput:
    """An input of a task: a file that another task of its job made.

    The input is a contract of the task's class: it states the class of the
    task that makes the file and which of that class's outputs it reads, so
    the format of the file is the one that the output declares. When a task
    is made, each input is bound to the only task of that class in its job,
    unless the task names another (:attr:`Task.upstream`).

    Parameters
    ----------
    name : str
        The name of the input, such as ``"events"``.
    upstream_class : type[Task]
        The class of the task that makes the file. It is a family of tasks,
        such as :class:`omphjc.tasks.ShowerTask` for a shower with any tool,
        or one class of task.
    upstream_output : str, optional
        The name of the output of the upstream class that the input reads
        (:attr:`Task.outputs`). It is ``"events"`` unless given.

    Raises
    ------
    ValueError
        If the upstream class declares no output of that name.
    """

    name: str
    upstream_class: type["Task"]
    upstream_output: str = EVENTS_OUTPUT

    def __post_init__(self) -> None:
        upstream_class_name = self.upstream_class.__name__
        output_names = sorted(output.name for output in self.upstream_class.outputs)
        if self.upstream_output not in output_names:
            declared = f"the outputs {output_names}" if output_names else "no output"
            fix = "Declare the output on the class."
            if output_names:
                fix = "Name one of them in upstream_output, or " + fix.lower()
            raise ValueError(
                f"The {self.name} input reads the {self.upstream_output} output "
                f"of a {upstream_class_name} task, but {upstream_class_name} "
                f"declares {declared}. {fix}"
            )

    @property
    def file_format(self) -> str:
        """The file format that the input reads, as its upstream class declares it."""
        return next(
            output.file_format
            for output in self.upstream_class.outputs
            if output.name == self.upstream_output
        )


EVENTS_INPUT = "events"
"""The name of the input that holds the events a task reads."""


_TaskT = TypeVar("_TaskT", bound="Task")


@dataclass(frozen=True, kw_only=True)
class Task(ABC):
    """One task of a job.

    A task is one piece of the work of a stage, done with one tool, in a
    directory of its own. This is the base class. The tasks that do the same
    work are objects of one subclass, such as
    :class:`omphjc.tasks.PythiaShower` for the showers with Pythia. A
    subclass:

    - states its stage and its tool;
    - holds its settings as fields;
    - gives its parameters (:meth:`parameters`);
    - does the work of a run (:meth:`execute`).

    The base class gives every task, whatever its class:

    - its identity and its directory;
    - its record, its status and its logs, read from disk each time they
      are asked for;
    - the run of the task and the writing of its record (:meth:`run`).

    A task is made in one of two ways. A caller makes it from its class, its
    job and its settings, as in ``PythiaShower(job, timeout_seconds=600)``. A
    job makes the tasks it finds on disk from their records
    (:meth:`omphjc.jobs.Job.tasks`, :meth:`omphjc.jobs.Job.get_task`),
    each as an object of its own class with the settings it ran with and the
    tasks it read.

    Two tasks are equal when they are of the same class and the same job,
    with the same tag, the same upstream and the same settings.

    Raises
    ------
    ValueError
        If `upstream` names a task for something that is not an input of the
        task. If an input that `upstream` leaves out has no task of its class
        in the job, or several; the message says what to run or to name.

    Parameters
    ----------
    job : Job
        The job that the task belongs to.
    tag : str or None, optional
        A label that tells the task apart from another task of the same stage
        and tool. Most tasks have none.
    upstream : Mapping[str, str], optional
        The name of the task to read an input from, by the name of the input.
        An input that it leaves out is bound, when the task is made, to the
        only task of the input's upstream class in the job. After that,
        `upstream` names the task of every input.
    timeout_seconds : float or None, optional
        The time limit of the programs of a run. ``None`` sets no limit.
    program_path : Path or None, optional
        The file of the task's program. By default the program is looked up
        on PATH.
    """

    stage: ClassVar[Stage]
    """The stage that the task belongs to."""

    tool: ClassVar[str]
    """The name of the tool that the task uses and is named after, such as
    ``"pythia"``."""

    inputs: ClassVar[tuple[TaskInput, ...]] = ()
    """What the task reads from other tasks of its job."""

    outputs: ClassVar[tuple[TaskOutput, ...]] = ()
    """What each run of the task makes, under the names that inputs read."""

    job: "Job" = field(kw_only=False)
    tag: str | None = None
    upstream: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    program_path: Path | None = None

    def __post_init__(self) -> None:
        input_names = sorted(task_input.name for task_input in self.inputs)
        unknown_names = sorted(set(self.upstream) - set(input_names))
        if unknown_names:
            reads = f"the inputs {input_names}" if input_names else "no input"
            raise ValueError(
                f"The {self.name} task reads {reads}, but its upstream names a "
                f"task for {unknown_names}. Leave those out of upstream."
            )
        upstream = dict(self.upstream)
        for task_input in self.inputs:
            if task_input.name not in upstream:
                upstream[task_input.name] = self._only_task_of(task_input).name
        object.__setattr__(self, "upstream", upstream)

    @cached_property
    def identity(self) -> TaskIdentity:
        """The stage, the tool and the tag of the task."""
        return TaskIdentity(self.stage.name, self.tool, self.tag)

    @property
    def name(self) -> str:
        """The name of the task in its job (:attr:`TaskIdentity.name`)."""
        return self.identity.name

    @cached_property
    def directory(self) -> Path:
        """The directory of the task, which holds its record, its logs and its files."""
        return self.job.task_dir(self.identity)

    @cached_property
    def record_path(self) -> Path:
        """The file of the record of the task, ``task.json`` in its directory."""
        return self.directory / TaskRecord.file_name

    @property
    def record(self) -> TaskRecord | None:
        """The record of the task as it is on disk, or ``None`` when it has none.

        Raises
        ------
        ValueError
            If the ``task.json`` of the task cannot be read as a record. If
            it is the record of another task: one with another stage, tool
            or tag that has the same name, and so the same directory.
        """
        try:
            record = TaskRecord.read(self.record_path, root_dir=self.job.root_dir)
        except FileNotFoundError:
            return None
        if record.identity != self.identity:
            raise ValueError(
                f"{self.record_path} is the record of another task named "
                f"{self.name}: expected {self.identity}, got {record.identity}. "
                "Give one of the two tasks another tag."
            )
        return record

    @property
    def status(self) -> TaskStatus:
        """Whether the task is done now, with its output files validated.

        A task without a record is not done. Otherwise the status is the one
        its record gives (:meth:`TaskRecord.current_status`).
        """
        record = self.record
        return TaskStatus.NOT_DONE if record is None else record.current_status()[0]

    @property
    def events(self) -> EventFileRecord:
        """The events that the task made.

        Raises
        ------
        ValueError
            For the reasons that :meth:`require_done` gives. If the task made
            no event file.
        """
        events = self.require_done().events
        if events is None:
            raise ValueError(
                f"The {self.name} task of {self.job.root_dir} made no event file"
            )
        return events

    @property
    def latest_log(self) -> Path:
        """The log of the latest run of the task.

        Raises
        ------
        ValueError
            If the task has no record, and so no run.
        """
        record = self.record
        if record is None:
            raise ValueError(f"The {self.name} task in {self.directory} has no run")
        return self.log_path(record.latest_run.run_id)

    def log_path(self, run_id: str) -> Path:
        """Return the log of run `run_id`, ``logs/<run_id>.log`` in the directory.

        The file exists once a program of the run has written to it.

        Raises
        ------
        ValueError
            If `run_id` is not a plain name.
        """
        return inside(self.directory, LOGS_DIR, f"{run_id}.log")

    def remove_logs(self, log_paths: Iterable[Path]) -> None:
        """Remove the logs `log_paths` of the task.

        Only regular files are removed, and nothing else in the directory of
        the logs is touched.
        """
        logs = [path for path in log_paths if path.is_file() and not path.is_symlink()]
        remove_inside(self.directory / LOGS_DIR, logs)

    @abstractmethod
    def parameters(self, input_files: Mapping[str, FileRecord]) -> dict[str, Any]:
        """Return what fixes the files of the task, as JSON values.

        A later request compares its parameters with these to decide whether
        the result can be kept. They hold the seed of the job when the task
        uses it. They leave out the files that the task reads, which
        :meth:`run` records and compares by their fingerprints.

        Parameters
        ----------
        input_files : Mapping[str, FileRecord]
            The files that the task reads, by the name of the input
            (:meth:`input_files`). It is empty for a task without an input.
        """

    @abstractmethod
    def execute(
        self,
        input_files: Mapping[str, FileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        """Carry out one run of the task and return what it made.

        A class runs the program of its tool here. The method is called
        when the task has to run, and what it returns is recorded.

        Parameters
        ----------
        input_files : Mapping[str, FileRecord]
            The files that the task reads, by the name of the input
            (:meth:`input_files`). It is empty for a task without an input.
        overwrite : bool
            Whether to replace what an earlier run left in the directory.
        log_path : Path
            The file that the programs of this run write their output to.
        """

    def settings(self) -> dict[str, Any]:
        """Return the settings the task was made with, as JSON values.

        They are the fields of the task, without its job and its tag. A path
        is recorded as it was given. The record of a task holds them, and
        :meth:`from_record` makes the task again from them.
        """
        settings = {}
        for task_field in fields(self):
            if task_field.name in _NON_SETTING_FIELD_NAMES:
                continue
            value = getattr(self, task_field.name)
            if isinstance(value, Path):
                value = str(value)
            elif isinstance(value, Mapping):
                value = dict(value)
            settings[task_field.name] = value
        return settings

    @classmethod
    def from_record(cls: type[_TaskT], job: "Job", record: TaskRecord) -> _TaskT:
        """Return the task of this class in `job` that `record` describes.

        The record gives the tag of the task, the settings it was made with
        (:meth:`settings`) and the task it read each input from, which
        becomes its :attr:`upstream`. A path that was recorded as a string is
        a :class:`~pathlib.Path` again.

        Parameters
        ----------
        job : Job
            The job that the task belongs to.
        record : TaskRecord
            The record of the task.

        Raises
        ------
        ValueError
            If `record` is that of a task of another stage or tool. If its
            settings are not those of the class.
        """
        identity = record.identity
        if (identity.stage, identity.tool) != (cls.stage.name, cls.tool):
            raise ValueError(
                f"{cls.__name__} expects the record of a task with stage "
                f"{cls.stage.name!r} and tool {cls.tool!r}, got the record of "
                f"the {identity.name} task. Use Job.get_task, which "
                "picks the class of a record."
            )
        settings = dict(record.settings)
        for task_field in fields(cls):
            value = settings.get(task_field.name)
            if isinstance(value, str) and _is_path_type(task_field.type):
                settings[task_field.name] = Path(value)
        upstream = {
            input_name: input_record.task
            for input_name, input_record in record.inputs.items()
        }
        try:
            return cls(job, tag=identity.tag, upstream=upstream, **settings)
        except TypeError as error:
            raise ValueError(
                f"The settings recorded for the {identity.name} task are not "
                f"those of {cls.__name__} ({error}). Run {identity.command} "
                "with --force to make the task again."
            ) from None

    def upstream_tasks(self) -> dict[str, "Task"]:
        """Return the task that makes each input, by the name of the input.

        It is the task that :attr:`upstream` names for the input. A task
        without an input gives an empty mapping.

        Raises
        ------
        ValueError
            If a task that :attr:`upstream` names has no record, or is not of
            the input's upstream class (:attr:`TaskInput.upstream_class`).
        """
        return {
            task_input.name: self._upstream_task(task_input)
            for task_input in self.inputs
        }

    def input_files(
        self, upstream_tasks: Mapping[str, "Task"] | None = None
    ) -> dict[str, FileRecord]:
        """Return the files that the task reads, by the name of the input.

        The file of an input is the output of its upstream task that the input
        reads (:attr:`TaskInput.upstream_output`), in the format that the
        upstream class declares for it. A task without an input gives an
        empty mapping.

        Parameters
        ----------
        upstream_tasks : Mapping[str, Task] or None, optional
            The tasks of :meth:`upstream_tasks`, when the caller has them.

        Raises
        ------
        ValueError
            As :meth:`upstream_tasks` refuses. If an upstream task is not
            done (:meth:`require_done`). If it made no file under the output
            that the input reads, or one in another format.
        """
        if upstream_tasks is None:
            upstream_tasks = self.upstream_tasks()
        input_files = {}
        for task_input in self.inputs:
            upstream_task = upstream_tasks[task_input.name]
            upstream_outputs = upstream_task.require_done().outputs
            input_file = upstream_outputs.get(task_input.upstream_output)
            reads = (
                f"{self.name} reads the {task_input.upstream_output} output of the "
                f"{upstream_task.name} task of {self.job.root_dir}"
            )
            if input_file is None:
                raise ValueError(f"{reads}, but that task made no file of that name")
            if input_file.file_format != task_input.file_format:
                raise ValueError(
                    f"{reads} as a {task_input.file_format} file, but that task "
                    f"made {_format_phrase(input_file.file_format)}"
                )
            input_files[task_input.name] = input_file
        return input_files

    def require_done(self) -> TaskRecord:
        """Return the record of the task, which must be done with its outputs intact.

        Raises
        ------
        ValueError
            If the task is not done or an output is missing. The message
            names the command to run first.

            If an output has another size than recorded. The message names
            the file, both sizes and ``--force``.
        """
        record = self.record
        status, detail = (
            (TaskStatus.NOT_DONE, "") if record is None else record.current_status()
        )
        command = self.identity.command
        if status is TaskStatus.CHANGED:
            raise ValueError(
                f"{detail}; run {command} with --force to regenerate the file"
            )
        if record is None or status is not TaskStatus.DONE:
            raise ValueError(
                f"The {self.name} task of {self.job.root_dir} has not run to "
                f"completion; run {command} first"
            )
        return record

    def run(self, *, accept_input: bool = False, force: bool = False) -> TaskRecord:
        """Run the task unless its result can be kept.

        A request is compared with the record of the task in two parts: the
        parameters of the task (:meth:`parameters`), and the fingerprint of
        the file of each input that it reads. A run is recorded with both,
        with the task that made each input and with the settings of the task.

        The files that the task reads are found once, before anything else,
        and given to :meth:`parameters` and to :meth:`execute`.

        **A task recorded as done.**

        - It is kept when its outputs are present and the parameters and the
          inputs are the same.
        - It is refused when the parameters or the inputs differ, or when an
          output has another size than recorded. `force` overrides the
          refusal.
        - With `accept_input`, it is also kept when its outputs are present
          and only the inputs differ. Each input whose file changed then
          records the fingerprint of the current file and the time as
          ``accepted``, which replaces an earlier acceptance of that input.
          The fingerprints that the task read stay, and the record gains no
          run. From then on the task is kept for the files it read and for
          the accepted ones, without `accept_input` too.

        **A task that is not kept.** A task without a record runs. A task
        that failed, was interrupted or lost an output runs again. The new
        run is added to the record when the parameters and the inputs are the
        same. Otherwise, or under `force`, the task starts a new record, and
        the logs of the runs that the earlier record listed are removed. In
        both cases :meth:`execute` is told to replace what the earlier run
        left.

        **What is written.** The first task of a job creates the job
        directory with its ``job.json``. Each run gets a run ID and a log,
        ``logs/<run_id>.log`` in the directory of the task
        (:meth:`log_path`).

        The record, ``task.json`` in the directory of the task, is written
        before :meth:`execute` is called and again after it returns or
        raises. A failed or interrupted run therefore records how far it got.
        The manifest of the job is written again after each of these writes.

        A run that ``SIGTERM`` or a keyboard interrupt ended is recorded as
        interrupted, and a run that raised anything else as failed. The end
        of a run is written only while that run is still the latest one in
        the record on disk.

        Parameters
        ----------
        accept_input : bool, optional
            Keep a done task whose input alone has changed, and record the
            acceptance. It changes nothing for a task that is not done or has
            lost an output.
        force : bool, optional
            Run the task even when its result could be kept.

        Returns
        -------
        TaskRecord
            The record of the task, kept or new.

        Raises
        ------
        ValueError
            If the task is recorded as done with other parameters or other
            inputs, or with an output of another size than recorded, and
            `force` is not set; the message names each parameter or each
            input that differs. If the ``job.json`` of
            the directory identifies another job. If the ``task.json`` of a
            task of the job cannot be read as a record. If `accept_input` and
            `force` are both set. If the record that a new one replaces lists
            a run whose ID is not a plain name; the record is then left as it
            was. If the files that the task reads cannot be given
            (:meth:`input_files`), or one of them has no fingerprint.
        FileNotFoundError
            If the ``job.json`` of the directory was removed while the task
            ran. The task is then not recorded.
        ReplacedRunError
            If a newer run of the task started before this one ended. The
            record of the newer run is left unchanged, and the end of this
            one is not recorded.
        Exception
            Whatever :meth:`parameters` raised, before anything is recorded.
            Whatever :meth:`execute` raised, after the failure is recorded.
        """
        if accept_input and force:
            raise ValueError("accept_input and force cannot both be set")
        upstream_tasks = self.upstream_tasks()
        input_files = self.input_files(upstream_tasks)
        parameters = self.parameters(input_files)
        inputs = self._input_records(upstream_tasks, input_files)
        input_fingerprints = {
            input_name: input_record.fingerprint
            for input_name, input_record in inputs.items()
        }
        previous_record = self.record
        if not force:
            kept_record = self._kept_record(
                previous_record,
                parameters,
                input_fingerprints,
                accept_input=accept_input,
            )
            if kept_record is not None:
                return kept_record
        overwrite = force or previous_record is not None
        clock = time.monotonic()
        self.job.record_identity()
        dropped_runs: tuple[TaskRun, ...] = ()
        if (
            previous_record is None
            or force
            or previous_record.parameters != parameters
            or previous_record.input_fingerprints != input_fingerprints
        ):
            record = TaskRecord.running(
                self.identity, self.settings(), parameters, inputs
            )
            if previous_record is not None:
                dropped_runs = previous_record.runs
        else:
            record = replace(
                previous_record.rerun(), settings=self.settings(), inputs=inputs
            )
        log_path = self.log_path(record.latest_run.run_id)
        # Named before the record is replaced, so that a run ID that is not a
        # plain name is refused while the earlier record is still in place.
        dropped_logs = [self.log_path(run.run_id) for run in dropped_runs]
        self._write_record(record)
        try:
            self.remove_logs(dropped_logs)
            log_path.parent.mkdir(exist_ok=True)
            outcome = self.execute(input_files, overwrite, log_path)
            self._validate_outputs(outcome.result)
        except BaseException as error:
            message = str(error) or type(error).__name__
            if isinstance(error, _INTERRUPTIONS):
                self._write_run_end(record.interrupted(error=message))
            else:
                self._write_run_end(record.failed(error=message))
            raise
        record = record.done(
            outcome, wall_seconds=time.monotonic() - clock, root_dir=self.job.root_dir
        )
        self._write_run_end(record)
        return record

    def _upstream_task(self, task_input: TaskInput) -> "Task":
        """Return the task that :attr:`upstream` names for the input `task_input`."""
        upstream_class = task_input.upstream_class
        upstream_name = self.upstream[task_input.name]
        upstream_task = self.job.get_task(upstream_name)
        if not isinstance(upstream_task, upstream_class):
            raise ValueError(
                f"{self.name} reads its {task_input.name} input from a "
                f"{upstream_class.__name__} task, but its upstream names "
                f"{upstream_name}, a {type(upstream_task).__name__} task. Name a "
                f"{upstream_class.__name__} task instead."
            )
        return upstream_task

    def _only_task_of(self, task_input: TaskInput) -> "Task":
        """Return the only task of the job of the upstream class of `task_input`."""
        upstream_class = task_input.upstream_class
        reads = (
            f"{self.name} reads its {task_input.name} input from a "
            f"{upstream_class.__name__} task"
        )
        stage_name = upstream_class.stage.name
        candidates = [
            stage_task
            for stage_task in self.job.tasks(stage_name)
            if isinstance(stage_task, upstream_class)
        ]
        if not candidates:
            raise ValueError(
                f"{reads}, and {self.job.root_dir} has none; run omphjc "
                f"{stage_name} first"
            )
        if len(candidates) > 1:
            names = ", ".join(candidate.name for candidate in candidates)
            raise ValueError(
                f"{reads}, and {self.job.root_dir} has several ({names}). Name "
                "the one to read in upstream, such as "
                f"upstream={{{task_input.name!r}: {candidates[0].name!r}}}."
            )
        return candidates[0]

    def _input_records(
        self,
        upstream_tasks: Mapping[str, "Task"],
        input_files: Mapping[str, FileRecord],
    ) -> dict[str, InputRecord]:
        """Name the task that made each file the task reads, and its fingerprint.

        Raises
        ------
        ValueError
            If a file is recorded without a fingerprint, so that a change to
            it could not be told.
        """
        input_records = {}
        for input_name, input_file in input_files.items():
            if input_file.fingerprint is None:
                raise ValueError(
                    f"{self.name} reads {input_file.path} as its {input_name} "
                    "input, but the file is recorded without a fingerprint, so a "
                    "change to it could not be told. Record it with "
                    "FileContent.record_file, which reads it."
                )
            upstream_name = upstream_tasks[input_name].name
            input_records[input_name] = InputRecord(
                upstream_name, input_file.fingerprint
            )
        return input_records

    def _validate_outputs(self, result: RunResult) -> None:
        """Refuse a result that does not hold each declared output in its format."""
        for declared in self.outputs:
            output = result.outputs.get(declared.name)
            if output is None:
                raise ValueError(
                    f"{self.name} declares the output {declared.name}, but its "
                    "run made none"
                )
            if output.file_format != declared.file_format:
                raise ValueError(
                    f"{self.name} declares the output {declared.name} as a "
                    f"{declared.file_format} file, but its run made "
                    f"{_format_phrase(output.file_format)}"
                )

    def _kept_record(
        self,
        record: TaskRecord | None,
        parameters: dict[str, Any],
        input_fingerprints: dict[str, str],
        *,
        accept_input: bool,
    ) -> TaskRecord | None:
        """Return `record` when the result of the task is kept for a request.

        `record` is the record of the task as found on disk. The request has
        `parameters`, and its inputs have `input_fingerprints`. The
        parameters are compared first, then the inputs.

        Return ``None`` when the task has to run. That is the case for a
        task without a record, for a task that is not done, and for a task
        that lost an output and has the same parameters and inputs.

        Raises
        ------
        ValueError
            As :meth:`run` refuses a task recorded as done.
        """
        if record is None or not record.is_done:
            return None
        self._validate_parameters(record, parameters)
        status, detail = record.current_status()
        is_intact = status is TaskStatus.DONE
        if input_fingerprints != record.input_fingerprints:
            if is_intact and record.is_kept_for(input_fingerprints):
                return record
            same_inputs = input_fingerprints.keys() == record.inputs.keys()
            can_accept_input = is_intact and same_inputs
            if accept_input and can_accept_input:
                record = record.with_accepted_inputs(input_fingerprints)
                self._write_record(record)
                return record
            raise self._changed_inputs_error(
                record, input_fingerprints, can_accept_input=can_accept_input
            )
        if is_intact:
            return record
        if status is TaskStatus.CHANGED:
            raise ValueError(
                f"{detail}; run {self.identity.command} with --force to "
                "regenerate the file"
            )
        return None

    def _validate_parameters(
        self, record: TaskRecord, parameters: dict[str, Any]
    ) -> None:
        """Refuse `parameters` when the task ran with other ones.

        The message names each parameter that differs. A nested parameter
        is named by the dotted path of its keys. The value the task ran with
        is shown as the expected one.
        """
        if parameters == record.parameters:
            return
        raise self._inconsistency_error(
            "parameters",
            Difference.between_nested_mappings(parameters, record.parameters),
            "Rerun with the parameters the task ran with, or run "
            f"{self.identity.command} with --force to replace its result.",
        )

    def _changed_inputs_error(
        self,
        record: TaskRecord,
        input_fingerprints: dict[str, str],
        *,
        can_accept_input: bool,
    ) -> ValueError:
        """Return the error of a request whose inputs are not those the task read.

        The message names each input whose fingerprint differs. The
        fingerprint of the input that the task read is shown as the expected
        one.

        The message names ``--accept-input`` only when the option would keep
        the result (`can_accept_input`): the outputs of the task are present,
        and the task reads inputs of the same names as before.
        """
        command = self.identity.command
        if can_accept_input:
            fix = (
                f"Run {command} with --accept-input to keep its result for "
                "the current inputs, or with --force to replace it."
            )
        else:
            fix = f"Run {command} with --force to replace its result."
        differences = Difference.between_mappings(
            input_fingerprints,
            record.input_fingerprints,
            name=lambda input_name: f"fingerprint of {input_name}",
        )
        return self._inconsistency_error("inputs", differences, fix)

    def _inconsistency_error(
        self, subject: str, differences: list[Difference], fix: str
    ) -> ValueError:
        """Return the error of a request that differs from the record of the task.

        Parameters
        ----------
        subject : str
            What differs, in the plural: ``"parameters"`` or ``"inputs"``.
        differences : list[Difference]
            The differences, each of which is one line of the message.
        fix : str
            The sentence that says how to resolve the refusal.
        """
        record_path = self.job.relative_path(self.record_path)
        return ValueError(
            f"The current {subject} are inconsistent with those of the existing "
            f"{self.name} task in {self.job.root_dir} ({record_path}):"
            + "".join(f"\n  {difference}" for difference in differences)
            + f"\n{fix}"
        )

    def _write_run_end(self, record: TaskRecord) -> None:
        """Write `record`, which says how the latest run of the task ended.

        Raises
        ------
        ReplacedRunError
            If the record on disk already holds a newer run of the task.
            That record is left unchanged.
        """
        run = record.latest_run
        recorded = self.record
        if recorded is not None and recorded.latest_run.run_id != run.run_id:
            raise ReplacedRunError(
                f"Run {run.run_id!r} of the {self.name} task in "
                f"{self.job.root_dir} is not "
                f"recorded as {run.status.value}: run {recorded.latest_run.run_id!r} of "
                "the task started before it ended"
            )
        self._write_record(record)

    def _write_record(self, record: TaskRecord) -> None:
        """Write `record` as the record of the task, then the manifest of the job.

        The job directory must still hold its ``job.json``.
        """
        if not self.job.identity_path.exists():
            raise FileNotFoundError(
                f"{self.job.identity_path} was removed while the "
                f"{self.name} task ran; "
                "the outcome of the task is not recorded"
            )
        self.record_path.parent.mkdir(exist_ok=True)
        record.write(self.record_path, root_dir=self.job.root_dir)
        self.job.write_manifest(record)


def _format_phrase(file_format: str | None) -> str:
    """Name a file by its format in a message, or say that it has none."""
    if file_format is None:
        return "a file recorded without its format"
    return f"a {file_format} file"


class TaskRegistry:
    """The classes of the tasks, by the stage and the tool of each.

    A job finds the class of a task on disk here, from the identity in its
    record. A class is registered where it is defined::

        @TASK_REGISTRY.register
        @dataclass(frozen=True, kw_only=True)
        class PythiaShower(Task): ...
    """

    def __init__(self) -> None:
        self._classes: dict[tuple[str, str], type[Task]] = {}

    def register(self, task_class: type[_TaskT]) -> type[_TaskT]:
        """Register `task_class` under its stage and its tool, and return it.

        Raises
        ------
        ValueError
            If another class is registered for the same stage and tool.
        """
        key = (task_class.stage.name, task_class.tool)
        registered_class = self._classes.setdefault(key, task_class)
        if registered_class is not task_class:
            raise ValueError(
                f"The tasks of stage {key[0]!r} and tool {key[1]!r} already have "
                f"the class {registered_class.__name__}, so "
                f"{task_class.__name__} cannot be registered for them"
            )
        return task_class

    def get(self, identity: TaskIdentity) -> type[Task]:
        """Return the class registered for the stage and the tool of `identity`.

        Raises
        ------
        ValueError
            If no class is registered for them. The message names the module
            that registers the classes of omphjc's own tasks.
        """
        try:
            return self._classes[identity.stage, identity.tool]
        except KeyError:
            raise ValueError(
                f"No task class is registered for the stage {identity.stage!r} "
                f"and the tool {identity.tool!r}; importing omphjc.tasks registers "
                "the classes of omphjc's own tasks"
            ) from None


TASK_REGISTRY = TaskRegistry()
"""The registry of the task classes."""


def _is_path_type(field_type: Any) -> bool:
    """Whether a field of the type `field_type` holds a path, or a path or ``None``."""
    if isinstance(field_type, str):
        return "Path" in field_type
    return field_type is Path or Path in get_args(field_type)


def timestamp() -> str:
    """The current time in the format of a record, ISO 8601 UTC to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
