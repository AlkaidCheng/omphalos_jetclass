"""A task of a job: its record, what it made, and its status.

A task is the work of one stage in a job. Its record is the file
``task.json`` in the directory of the task, written as::

    {
      "schema": 1,
      "status": "done",
      "started": "2026-10-23T01:00:00+00:00",
      "finished": "2026-10-23T01:20:00+00:00",
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
        "metadata": {
          "madgraph_version": "3.8.1",
          "cross_section_pb": 1.23,
          "cross_section_error_pb": 0.01,
          "cards": {"generate/cards/run_card.dat": "<sha256>"}
        }
      },
      "log": "generate/madgraph.log",
      "usage": {"wall_seconds": 1203.4, "cpu_seconds": 9012.7, "peak_memory_mib": 812.5},
      "set_aside": null,
      "error": null
    }

:mod:`omphjc.jobs.record_file` describes ``schema``.
``status`` is ``"running"``, ``"done"`` or ``"failed"``. ``parameters`` is
what the task was asked for, the seed included where its stage uses one, and
decides whether a later run may keep its result. ``result`` is what the task
made (:class:`TaskResult`). ``outputs`` holds its files under the names the
stage gives them: each has its ``path`` and its size in bytes, ``n_bytes``,
and an event file also its ``format``, the number of events it holds and the
``fingerprint`` of its content; the next task reads the one named ``events``.
``metadata`` is what is known about the task and the sample it made; its keys
are the stage's own. Every path is relative to the job directory;
``set_aside`` names the folder into which the run moved what an
earlier run left and it could not confirm as that run's
(:mod:`omphjc.stamps`), ``null`` when it moved nothing. ``usage`` is what the
task took: its wall time, and the CPU time and peak memory (MiB) of the
external program's processes where the platform reports them.

:class:`TaskRecord` has one constructor per status. :meth:`TaskRecord.running`
records a task that has started, :meth:`TaskRecord.failed` one that raised,
and :meth:`TaskRecord.done` one that returned a :class:`TaskOutcome`, whose
result it holds unchanged.

A record says how the last run of the task ended. Whether its result can be
used also depends on its output files, which may have been deleted or changed
since: :class:`Task` holds a task as found on disk, and its
:class:`TaskStatus` takes both into account.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from omphjc.events.formats import EventFormat
from omphjc.jobs.record_file import RecordFile

DONE = "done"
RUNNING = "running"
FAILED = "failed"

EVENTS_OUTPUT = "events"
"""The name of the output that holds the events the next task reads."""


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
class TaskResult:
    """What a task made.

    Parameters
    ----------
    outputs : dict[str, TaskOutput]
        The task's outputs under the names its stage gives them. The next
        task reads the :class:`EventOutput` named :data:`EVENTS_OUTPUT`; a
        task that makes no events has none.
    metadata : dict
        What is known about the task and the sample it made, as JSON values;
        the keys are the stage's own.
    """

    outputs: dict[str, TaskOutput] = field(default_factory=dict)
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
        return cls(outputs=outputs, metadata=record["metadata"])


@dataclass(frozen=True)
class TaskOutcome:
    """What a stage function returns: the task's result and the run's own facts.

    Parameters
    ----------
    result : TaskResult
        What the task made.
    log_path : Path or None
        The log of the task's program, inside the job directory.
    usage : dict[str, float]
        Resources the task's program used, such as ``cpu_seconds`` and
        ``peak_memory_mib``; the job adds ``wall_seconds``.
    set_aside_dir : Path or None
        The folder, inside the job directory, holding what an earlier run left
        and this run could not confirm as that run's (:mod:`omphjc.stamps`);
        ``None`` when nothing was moved.
    """

    result: TaskResult
    log_path: Path | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside_dir: Path | None = None


@dataclass
class TaskRecord(RecordFile):
    """What one task did; the module docstring describes the fields."""

    file_name: ClassVar[str] = "task.json"

    status: str
    started: str
    finished: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    result: TaskResult = field(default_factory=TaskResult)
    log: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: str | None = None
    error: str | None = None

    def as_record(self) -> dict[str, Any]:
        """Return the fields by name."""
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "TaskRecord":
        """Return the task record that `record` describes.

        A path in the result becomes an absolute path under `root_dir`.
        """
        result = TaskResult.from_record(record.pop("result"), root_dir)
        return cls(**record, result=result)

    @classmethod
    def running(cls, *, started: str, parameters: dict[str, Any]) -> "TaskRecord":
        """Return the record of a task that has started."""
        return cls(status=RUNNING, started=started, parameters=parameters)

    @classmethod
    def failed(
        cls, *, started: str, parameters: dict[str, Any], error: str
    ) -> "TaskRecord":
        """Return the record of a task that has just raised `error`."""
        return cls(
            status=FAILED,
            started=started,
            finished=timestamp(),
            parameters=parameters,
            error=error,
        )

    @classmethod
    def done(
        cls,
        outcome: TaskOutcome,
        *,
        started: str,
        parameters: dict[str, Any],
        wall_seconds: float,
        root_dir: Path,
    ) -> "TaskRecord":
        """Return the record of a task that has just returned `outcome`.

        The log and the set-aside folder of `outcome` are made relative to
        `root_dir`, the job directory, and `wall_seconds` is added to its usage.
        """

        def relative(path: Path) -> str:
            return path.relative_to(root_dir).as_posix()

        return cls(
            status=DONE,
            started=started,
            finished=timestamp(),
            parameters=parameters,
            result=outcome.result,
            log=None if outcome.log_path is None else relative(outcome.log_path),
            usage={"wall_seconds": round(wall_seconds, 3), **outcome.usage},
            set_aside=(
                None
                if outcome.set_aside_dir is None
                else relative(outcome.set_aside_dir)
            ),
        )


class TaskStatus(Enum):
    """How a task of a job stands, by its record and its output files."""

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
