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
        "metadata": {
          "madgraph_version": "3.8.1",
          "cross_section_pb": 1.23,
          "cross_section_error_pb": 0.01,
          "cards": {"generate/cards/run_card.dat": "<sha256>"}
        }
      },
      "runs": [
        {
          "status": "failed",
          "started": "2026-10-23T01:00:00+00:00",
          "finished": "2026-10-23T01:05:00+00:00",
          "usage": {"wall_seconds": 301.2},
          "log": "generate/madgraph.log",
          "set_aside": null,
          "error": "MadGraph exited with status 1"
        },
        {
          "status": "done",
          "started": "2026-10-23T02:00:00+00:00",
          "finished": "2026-10-23T02:20:00+00:00",
          "usage": {
            "wall_seconds": 1203.4, "cpu_seconds": 9012.7, "peak_memory_mib": 812.5
          },
          "log": "generate/madgraph.log",
          "set_aside": null,
          "error": null
        }
      ]
    }

:mod:`omphjc.jobs.record_file` describes ``schema``. ``parameters`` is what
the task was asked for, the seed included where its stage uses one, and
decides whether a later run may keep its result. ``result`` is what the task
made (:class:`TaskResult`), ``null`` unless its latest run is done.
``outputs`` holds its files under the names the stage gives them: each has
its ``path`` and its size in bytes, ``n_bytes``, and an event file also its
``format``, the number of events it holds and the ``fingerprint`` of its
content; the next task reads the one named ``events``. ``metadata`` is what is
known about the task and the sample it made; its keys are the stage's own.

``runs`` lists the runs of the task, oldest first. Running a task again with
the same parameters, after a failure, an interruption or the loss of an
output, adds a run; a run with other parameters, or under ``force``, starts a
new task with one run. The ``status`` of a run says how it ended:
``"running"``, ``"done"``, ``"failed"`` or ``"interrupted"``. A run that a
killed process left ``"running"`` is marked ``"interrupted"`` when the next
one starts. What a rerun follows is the status of the run before it: a
failure, an interruption, or, after a ``"done"`` run, a missing output. Every
path is relative to the job directory; ``set_aside`` names the folder into
which the run moved what an earlier run left and it could not confirm as that
run's (:mod:`omphjc.stamps`), ``null`` when it moved nothing. ``usage`` is
what the run took: its wall time, and the CPU time and peak memory (MiB) of
the external program's processes where the platform reports them.

:meth:`TaskRecord.running` starts the record of a task, and
:meth:`TaskRecord.rerun` adds a run to it. :meth:`TaskRecord.failed`
and :meth:`TaskRecord.done` record how the latest run ended, the second
with the result of the :class:`TaskOutcome` it returned, unchanged.

A record says how each run of the task ended, nothing more. Whether the task
is done now also depends on its output files, which may have been deleted or
changed since: :class:`Task` holds a task as found on disk, and its
:class:`TaskStatus` takes the record and the files into account. A task whose
latest run is done has :attr:`TaskStatus.DONE` only while its outputs are
intact.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from omphjc.events.formats import EventFormat
from omphjc.jobs.record_file import RecordFile

# How a run ended, or that it is still running.
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"

_STATUSES = (RUNNING, DONE, FAILED, INTERRUPTED)

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


@dataclass(frozen=True)
class TaskRun:
    """One run of a task; the module docstring describes the fields.

    Raises
    ------
    ValueError
        If `status` is not one the module docstring lists.
    """

    status: str
    started: str
    finished: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    log: str | None = None
    set_aside: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown run status {self.status!r}")


@dataclass(frozen=True)
class TaskRecord(RecordFile):
    """What one task did; the module docstring describes the fields.

    Raises
    ------
    ValueError
        If the record has no run, or holds a result while its latest
        run is not done, or none while it is.
    """

    file_name: ClassVar[str] = "task.json"

    parameters: dict[str, Any]
    runs: tuple[TaskRun, ...]
    result: TaskResult | None = None

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
    def metadata(self) -> dict[str, Any]:
        """What is known about the task and the sample it made.

        Raises
        ------
        ValueError
            If the latest run is not done.
        """
        return self._done_result().metadata

    def as_record(self) -> dict[str, Any]:
        """Return the parameters, the result and the runs by name."""
        return {
            "parameters": self.parameters,
            "result": None if self.result is None else asdict(self.result),
            "runs": [asdict(run) for run in self.runs],
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
        return cls(
            **fields,
            runs=runs,
            result=None if result is None else TaskResult.from_record(result, root_dir),
        )

    @classmethod
    def running(cls, parameters: dict[str, Any], *, started: str) -> "TaskRecord":
        """Return the record of a new task whose first run has started."""
        return cls(parameters, (TaskRun(RUNNING, started),))

    def rerun(self, *, started: str) -> "TaskRecord":
        """Return the record with a further run that has started.

        A run still ``running``, left by a killed process, becomes
        ``interrupted``. The record holds no result until the new run is
        done.
        """
        latest = self.latest_run
        previous_runs = self.runs
        if latest.status == RUNNING:
            interrupted = replace(latest, status=INTERRUPTED)
            previous_runs = (*previous_runs[:-1], interrupted)
        run = TaskRun(RUNNING, started)
        return replace(self, runs=(*previous_runs, run), result=None)

    def failed(self, *, error: str) -> "TaskRecord":
        """Return the record with its latest run failed with `error`."""
        latest = replace(
            self.latest_run, status=FAILED, finished=timestamp(), error=error
        )
        return replace(self, runs=(*self.runs[:-1], latest))

    def done(
        self, outcome: TaskOutcome, *, wall_seconds: float, root_dir: Path
    ) -> "TaskRecord":
        """Return the record with its latest run done and the result of `outcome`.

        The log and the set-aside folder of `outcome` are made relative to
        `root_dir`, the job directory, and `wall_seconds` is added to its usage.
        """

        def relative(path: Path) -> str:
            return path.relative_to(root_dir).as_posix()

        latest = replace(
            self.latest_run,
            status=DONE,
            finished=timestamp(),
            usage={"wall_seconds": round(wall_seconds, 3), **outcome.usage},
            log=None if outcome.log_path is None else relative(outcome.log_path),
            set_aside=(
                None
                if outcome.set_aside_dir is None
                else relative(outcome.set_aside_dir)
            ),
        )
        return replace(self, runs=(*self.runs[:-1], latest), result=outcome.result)

    def _done_result(self) -> TaskResult:
        """Return the result, which only a record whose latest run is done holds."""
        if self.result is None:
            raise ValueError(
                "The task record has no result: its latest run has status "
                f"{self.latest_run.status!r}"
            )
        return self.result


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
