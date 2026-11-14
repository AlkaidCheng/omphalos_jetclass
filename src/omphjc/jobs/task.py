"""A task of a job: its record, what it made, and its status.

A task is the work of one stage in a job. Its record is the file
``task.json`` in the directory of the task, written as::

    {
      "schema": 1,
      "parameters": {"events": 1000, "seed": 10000001},
      "result": {
        "outputs": {
          "events": {
            "path": "generate/HToBB/Events/run_01/unweighted_events.lhe.gz",
            "n_bytes": 12345678,
            "format": "lhe",
            "n_events": 1000,
            "fingerprint": "lhe-v1:<sha256>"
          }
        },
        "cards": {
          "run_card": {"path": "generate/cards/run_card.dat", "sha256": "<sha256>"}
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
          "log": "generate/runs/20261023T010000Z-4f9c2a1e/madgraph.log",
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
          "log": "generate/runs/20261023T020000Z-b81d07c3/madgraph.log",
          "set_aside": null,
          "error": null
        }
      ],
      "accepted_input": null
    }

Every path in the record is relative to the job directory. The top-level
keys are:

``schema``
    The layout version of the file (:mod:`omphjc.jobs.record_file`).
``parameters``
    What the task was asked for, including the seed when its stage uses one.
    A later run compares its own parameters with these to decide whether the
    result can be kept.
``result``
    What the task made (:class:`TaskResult`). It is ``null`` unless the
    latest run is done.
``runs``
    The runs of the task, oldest first.
``accepted_input``
    An input that the task was kept for although it read another one. It is
    ``null`` when there is none.

**The result.** ``outputs`` holds the files the task made, under the names
the stage gives them. Each output has its ``path`` and its size in bytes,
``n_bytes``. An event file also has its ``format``, the number of events it
holds and the ``fingerprint`` of its content. The next task reads the output
named ``events``.

``cards`` holds the cards of the task, under the names its stage gives them.
A card is a file that steers the task's program, such as a run card or a
detector card. Each card has its ``path`` and the ``sha256`` of the file as
the run used it. The cards are a record for the reader: they do not count
when the status of the task is judged.

``metadata`` is what is known about the task and the sample it made. The
stage chooses its keys.

**The runs.** Repeating a task with the same parameters adds a run to the
record. This happens after a failure, an interruption or the loss of an
output. A run with other parameters, or under ``force``, starts a new record
with one run.

The record does not store why a task was repeated. The status of the
previous run says it: that run failed, was interrupted, or was ``"done"`` and
an output went missing afterwards.

Each run has these keys:

``run_id``
    The start time of the run in UTC, followed by eight random hexadecimal
    digits. The IDs of a task's runs therefore sort by start time.
``status``
    How the run ended: ``"running"``, ``"done"``, ``"failed"`` or
    ``"interrupted"``. A run is ``"failed"`` when its program or omphjc
    failed. It is ``"interrupted"`` when a signal ended it, and ``error``
    then holds the signal. A run that a killed process left ``"running"`` is
    marked ``"interrupted"`` when the next run starts.
``started``, ``finished``
    The times at which the run started and ended, in UTC. ``finished`` is
    ``null`` for a run whose end was not recorded.
``host``
    The name of the machine the run was on.
``usage``
    What the run took: its wall time, and the CPU time and peak memory (MiB)
    of the external program's processes where the platform reports them.
``log``
    The file that the run's program writes its log to. It is in the
    directory of the run (:mod:`omphjc.jobs.job`). The value is ``null`` for
    a task without a log. The file is missing when the run ended before its
    program started.
``set_aside``
    The folder into which the run moved what an earlier run left and it
    could not confirm as that run's (:mod:`omphjc.stamps`). The value is
    ``null`` when the run moved nothing.
``error``
    The error of a failed run, or the signal that ended an interrupted one.
    The value is ``null`` otherwise.

**The accepted input.** ``accepted_input`` is set when the task was kept for
another input than the one it read (:meth:`omphjc.jobs.Job.run_task`). It
holds the ``fingerprint`` of that input and the time of the acceptance,
``accepted_at``. ``parameters`` still hold the fingerprint of the input the
task read. A further run of the task clears ``accepted_input``.

**Making a record.** These methods of :class:`TaskRecord` return a new
record:

- :meth:`TaskRecord.running` starts the record of a task.
- :meth:`TaskRecord.rerun` adds a run to it.
- :meth:`TaskRecord.with_log` names the log of that run.
- :meth:`TaskRecord.with_accepted_input` records an acceptance.
- :meth:`TaskRecord.failed`, :meth:`TaskRecord.interrupted` and
  :meth:`TaskRecord.done` record how the latest run ended. ``done`` also
  stores the result of the :class:`TaskOutcome` that the stage returned,
  unchanged.

**Record and status.** A record only says how each run of the task ended.
Whether the task is done at this moment also depends on its output files,
because they may have been deleted or changed since. :class:`Task` holds a
task as found on disk, and its :class:`TaskStatus` takes the record and the
files into account. A task whose latest run is done has
:attr:`TaskStatus.DONE` only while its outputs are intact.
"""

import hashlib
import secrets
import socket
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from omphjc.events.formats import EventFormat
from omphjc.jobs.record_file import RecordFile
from omphjc.stamps import COMPACT_UTC_FORMAT

# How a run ended, or that it is still running.
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"

_STATUSES = (RUNNING, DONE, FAILED, INTERRUPTED)

_RUN_ID_RANDOM_BYTES = 4
"""Random bytes in a run ID, written as twice as many hexadecimal digits."""

EVENTS_OUTPUT = "events"
"""The name of the output that holds the events the next task reads."""
INPUT_FINGERPRINT_PARAMETER = "input_fingerprint"
"""The parameter that holds the fingerprint of the events a task reads."""


@dataclass(frozen=True)
class TaskOutput:
    """A file a task made.

    Parameters
    ----------
    path : Path
        The file, inside the job directory.
    n_bytes : int
        The size of the file in bytes when the task finished.
    """

    path: Path
    n_bytes: int


@dataclass(frozen=True)
class EventOutput(TaskOutput):
    """An event file a task made.

    Parameters
    ----------
    path : Path
        The file, inside the job directory.
    n_bytes : int
        The size of the file in bytes when the task finished.
    format : EventFormat
        The format of the file.
    n_events : int
        The number of events the file holds.
    fingerprint : str
        The fingerprint of the file's content
        (:meth:`omphjc.data_files.DataFile.fingerprint`). Two files with the
        same events have the same fingerprint.
    """

    format: EventFormat
    n_events: int
    fingerprint: str


@dataclass(frozen=True)
class TaskCard:
    """A card of a task: a file that steered the task's program.

    Parameters
    ----------
    path : Path
        The file as the run used it, inside the job directory.
    sha256 : str
        The SHA-256 of the file, as hexadecimal digits.
    """

    path: Path
    sha256: str

    @classmethod
    def from_path(cls, path: Path) -> "TaskCard":
        """Return the card at `path`, with the SHA-256 of the file as it is."""
        return cls(path, hashlib.sha256(path.read_bytes()).hexdigest())


@dataclass(frozen=True)
class TaskResult:
    """What a task made.

    Parameters
    ----------
    outputs : dict[str, TaskOutput]
        The task's outputs under the names its stage gives them. The next
        task reads the :class:`EventOutput` named :data:`EVENTS_OUTPUT`. A
        task that makes no events has no such output.
    cards : dict[str, TaskCard]
        The cards the task's program read, under the names its stage gives
        them.
    metadata : dict
        What is known about the task and the sample it made, as JSON values.
        The stage chooses the keys.
    """

    outputs: dict[str, TaskOutput] = field(default_factory=dict)
    cards: dict[str, TaskCard] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any], root_dir: Path) -> "TaskResult":
        """Return the result that `record` describes, with its paths under `root_dir`.

        An output recorded with an event count is an :class:`EventOutput`.
        """
        outputs: dict[str, TaskOutput] = {}
        for name, output in record["outputs"].items():
            path = root_dir / output["path"]
            if "n_events" in output:
                outputs[name] = EventOutput(
                    path,
                    output["n_bytes"],
                    EventFormat(output["format"]),
                    output["n_events"],
                    output["fingerprint"],
                )
            else:
                outputs[name] = TaskOutput(path, output["n_bytes"])
        cards = {
            name: TaskCard(root_dir / card["path"], card["sha256"])
            for name, card in record["cards"].items()
        }
        return cls(outputs=outputs, cards=cards, metadata=record["metadata"])


@dataclass(frozen=True)
class TaskOutcome:
    """What a stage function returns: the task's result and the run's own facts.

    Parameters
    ----------
    result : TaskResult
        What the task made.
    usage : dict[str, float]
        Resources the task's program used, such as ``cpu_seconds`` and
        ``peak_memory_mib``. The job adds ``wall_seconds``.
    set_aside_dir : Path or None
        The folder, inside the job directory, that holds what an earlier run
        left and this run could not confirm as that run's
        (:mod:`omphjc.stamps`). It is ``None`` when nothing was moved.
    """

    result: TaskResult
    usage: dict[str, float] = field(default_factory=dict)
    set_aside_dir: Path | None = None


@dataclass(frozen=True, kw_only=True)
class TaskRun:
    """One run of a task; the module docstring describes the fields.

    Raises
    ------
    ValueError
        If `status` is not one the module docstring lists.
    """

    run_id: str
    status: str
    started: str
    host: str
    finished: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    log: str | None = None
    set_aside: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown run status {self.status!r}")

    @classmethod
    def started_now(cls) -> "TaskRun":
        """Return a run that starts now on this host, with a new run ID."""
        start_time = datetime.now(timezone.utc)
        random_digits = secrets.token_hex(_RUN_ID_RANDOM_BYTES)
        return cls(
            run_id=f"{start_time.strftime(COMPACT_UTC_FORMAT)}-{random_digits}",
            status=RUNNING,
            started=start_time.isoformat(timespec="seconds"),
            host=socket.gethostname(),
        )


@dataclass(frozen=True)
class AcceptedInput:
    """An input that a task was kept for although it read another one.

    Parameters
    ----------
    fingerprint : str
        The fingerprint of the events the task was kept for.
    accepted_at : str
        The time of the acceptance, in the format of :func:`timestamp`.
    """

    fingerprint: str
    accepted_at: str


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

    parameters: dict[str, Any]
    runs: tuple[TaskRun, ...]
    result: TaskResult | None = None
    accepted_input: AcceptedInput | None = None

    def __post_init__(self) -> None:
        if not self.runs:
            raise ValueError("the record has no runs")
        status = self.latest_run.status
        if self.is_done and self.result is None:
            raise ValueError(
                f"the latest run has status {status!r} but the record has no result"
            )
        if not self.is_done and self.result is not None:
            raise ValueError(
                f"the latest run has status {status!r} but the record has a result"
            )
        if not self.is_done and self.accepted_input is not None:
            raise ValueError(
                f"the latest run has status {status!r} but the record has an "
                "accepted input"
            )

    @property
    def latest_run(self) -> TaskRun:
        """The latest run of the task."""
        return self.runs[-1]

    @property
    def is_done(self) -> bool:
        """Whether the latest run of the task is done."""
        return self.latest_run.status == DONE

    @property
    def outputs(self) -> dict[str, TaskOutput]:
        """The outputs of the task, under the names its stage gives them.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().outputs

    @property
    def events(self) -> EventOutput | None:
        """The event file the task made, which the next task reads.

        It is ``None`` when the task made no event file.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        events = self.outputs.get(EVENTS_OUTPUT)
        return events if isinstance(events, EventOutput) else None

    @property
    def cards(self) -> dict[str, TaskCard]:
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
        """Return the parameters, the result, the runs and the accepted input by name."""
        accepted_input = self.accepted_input
        return {
            "parameters": self.parameters,
            "result": None if self.result is None else asdict(self.result),
            "runs": [asdict(run) for run in self.runs],
            "accepted_input": (
                None if accepted_input is None else asdict(accepted_input)
            ),
        }

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "TaskRecord":
        """Return the task record that `record` describes.

        A path in the result becomes an absolute path under `root_dir`. A
        record without runs is refused.
        """
        if "runs" not in record:
            raise ValueError("the record has no runs")
        fields = dict(record)
        runs = tuple(TaskRun(**run) for run in fields.pop("runs"))
        result = fields.pop("result")
        accepted_input = fields.pop("accepted_input")
        return cls(
            **fields,
            runs=runs,
            result=None if result is None else TaskResult.from_record(result, root_dir),
            accepted_input=(
                None if accepted_input is None else AcceptedInput(**accepted_input)
            ),
        )

    @classmethod
    def running(cls, parameters: dict[str, Any]) -> "TaskRecord":
        """Return the record of a new task whose first run starts now."""
        return cls(parameters, (TaskRun.started_now(),))

    def rerun(self) -> "TaskRecord":
        """Return the record with a further run that starts now.

        A latest run that is still ``running`` was left by a killed process,
        so it becomes ``interrupted``. The returned record has no result and
        no accepted input.
        """
        previous_runs = self.runs
        if self.latest_run.status == RUNNING:
            previous_runs = self._runs_with_latest(status=INTERRUPTED)
        runs = (*previous_runs, TaskRun.started_now())
        return replace(self, runs=runs, result=None, accepted_input=None)

    def with_log(self, log: str) -> "TaskRecord":
        """Return the record with `log` as the log of its latest run.

        `log` is the path of the file, relative to the job directory.
        """
        return replace(self, runs=self._runs_with_latest(log=log))

    def with_accepted_input(self, fingerprint: str) -> "TaskRecord":
        """Return the record with `fingerprint` as its accepted input, dated now."""
        accepted_input = AcceptedInput(fingerprint, accepted_at=timestamp())
        return replace(self, accepted_input=accepted_input)

    def is_accepted_for(self, parameters: Mapping[str, Any]) -> bool:
        """Whether the task was accepted for the input in `parameters`.

        The other parameters must be those of the task. It is ``False`` for a
        record without an accepted input.
        """
        if self.accepted_input is None:
            return False
        fingerprint = self.accepted_input.fingerprint
        return parameters == {
            **self.parameters,
            INPUT_FINGERPRINT_PARAMETER: fingerprint,
        }

    def failed(self, *, error: str) -> "TaskRecord":
        """Return the record with its latest run failed with `error`."""
        runs = self._runs_with_latest(status=FAILED, finished=timestamp(), error=error)
        return replace(self, runs=runs)

    def interrupted(self, *, error: str) -> "TaskRecord":
        """Return the record with its latest run interrupted by `error`."""
        runs = self._runs_with_latest(
            status=INTERRUPTED, finished=timestamp(), error=error
        )
        return replace(self, runs=runs)

    def done(
        self, outcome: TaskOutcome, *, wall_seconds: float, root_dir: Path
    ) -> "TaskRecord":
        """Return the record with its latest run done and the result of `outcome`.

        The set-aside folder of `outcome` is made relative to `root_dir`, the
        job directory, and `wall_seconds` is added to its usage.
        """
        set_aside_dir = outcome.set_aside_dir
        runs = self._runs_with_latest(
            status=DONE,
            finished=timestamp(),
            usage={"wall_seconds": round(wall_seconds, 3), **outcome.usage},
            set_aside=(
                None
                if set_aside_dir is None
                else set_aside_dir.relative_to(root_dir).as_posix()
            ),
        )
        return replace(self, runs=runs, result=outcome.result)

    def _runs_with_latest(self, **changes: Any) -> tuple[TaskRun, ...]:
        """Return the runs, the latest with its fields replaced by `changes`."""
        return (*self.runs[:-1], replace(self.latest_run, **changes))

    def _done_result(self) -> TaskResult:
        """Return the result of a record whose latest run is done."""
        if self.result is None:
            raise ValueError(
                "The task record has no result: its latest run has status "
                f"{self.latest_run.status!r}"
            )
        return self.result


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


@dataclass(frozen=True)
class Task:
    """A task of a job, as found on disk when :meth:`omphjc.jobs.Job.task` looked.

    Parameters
    ----------
    name : str
        The name of the task, which is also the name of its directory.
    status : TaskStatus
        How the task stands, by its record and its output files.
    detail : str
        A clause that names the output that is missing, or the output of
        another size with the size found and the size recorded. It is empty
        for the other statuses.
    record : TaskRecord or None
        The record of the task, ``None`` when the task has no record.
    """

    name: str
    status: TaskStatus
    detail: str = ""
    record: TaskRecord | None = None


def timestamp() -> str:
    """The current time in the format of a record, ISO 8601 UTC to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
