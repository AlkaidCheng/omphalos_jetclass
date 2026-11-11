"""The manifest of a job, ``manifest.json``: what ran, with what, and what came out.

The manifest names the process and job number, the omphjc version that
created the job, and one record per task, the work of one stage in the
job, under the stage's name::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "omphjc_version": "0.1.0",
      "stages": {
        "generate": {
          "status": "done",
          "started": "2026-10-23T01:00:00+00:00",
          "finished": "2026-10-23T01:20:00+00:00",
          "parameters": {"events": 1000, "seed": 10000001},
          "result": {
            "outputs": {
              "events": {
                "path": "generate/HToBB/Events/run_01/unweighted_events.lhe.gz",
                "format": "lhe",
                "n_events": 1000
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
      }
    }

``schema`` numbers this layout; a manifest of another schema is refused.
``status`` is ``"running"``, ``"done"`` or ``"failed"``. ``parameters`` is
what the task was asked for, the seed included where its stage uses one, and
decides whether a later run may keep its result. ``result`` is what the task
made (:class:`TaskResult`). ``outputs`` holds its files under the names the
stage gives them: each has its ``path``, and an event file also its ``format``
and the number of events it holds; the next task reads the one named
``events``. ``metadata`` is what is known about the task and the sample it
made; its keys are the stage's own. Every path is relative to the job
directory; ``set_aside`` names the folder into which the run moved what an
earlier run left and it could not confirm as that run's
(:mod:`omphjc.stamps`), ``null`` when it moved nothing. ``usage`` is what the
task took: its wall time, and the CPU time and peak memory (MiB) of the
external program's processes where the platform reports them. The file is
replaced in one step whenever it changes, so a crash never leaves a
half-written manifest.

:class:`TaskRecord` has one constructor per status. :meth:`TaskRecord.running`
records a task that has started, :meth:`TaskRecord.failed` one that raised,
and :meth:`TaskRecord.done` one that returned a :class:`TaskOutcome`, whose
result it holds unchanged.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omphjc import __version__
from omphjc.events.formats import EventFormat

MANIFEST_FILE = "manifest.json"
SCHEMA_VERSION = 1

DONE = "done"
RUNNING = "running"
FAILED = "failed"

EVENTS_OUTPUT = "events"
"""The name of the output that holds the events the next task reads."""


@dataclass(frozen=True)
class TaskOutput:
    """A file a task made, inside the job directory."""

    path: Path


@dataclass(frozen=True)
class EventOutput(TaskOutput):
    """An event file a task made, with its format and the number of events it holds."""

    format: EventFormat
    n_events: int


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
        """Return the result a manifest in `root_dir` holds as `record`.

        An output recorded with an event count is an :class:`EventOutput`.
        """
        outputs: dict[str, TaskOutput] = {}
        for name, output in record["outputs"].items():
            path = root_dir / output["path"]
            if "n_events" in output:
                outputs[name] = EventOutput(
                    path, EventFormat(output["format"]), output["n_events"]
                )
            else:
                outputs[name] = TaskOutput(path)
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
class TaskRecord:
    """What one task did; the module docstring describes the fields."""

    status: str
    started: str
    finished: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    result: TaskResult = field(default_factory=TaskResult)
    log: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: str | None = None
    error: str | None = None

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


@dataclass
class Manifest:
    """The manifest of one job; the module docstring describes the fields."""

    process: str
    job_id: int
    omphjc_version: str = __version__
    stages: dict[str, TaskRecord] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        """Write the manifest to `path`, replacing it in one step.

        A path in a result is written relative to the directory of `path`.

        Raises
        ------
        ValueError
            If a result names a path outside that directory.
        """

        def relative_path(value: object) -> str:
            if isinstance(value, Path):
                return value.relative_to(path.parent).as_posix()
            raise TypeError(f"{value!r} is not a JSON value")

        record = {"schema": SCHEMA_VERSION, **asdict(self)}
        text = json.dumps(record, indent=2, default=relative_path)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manifest-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
        os.replace(temporary, path)

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        """Read the manifest at `path`.

        Raises
        ------
        ValueError
            If the file is not a manifest of a known schema.
        """
        try:
            record: Any = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None
        if not isinstance(record, dict) or "schema" not in record:
            raise ValueError(f"{path} is not a manifest: no schema field")
        if record["schema"] != SCHEMA_VERSION:
            raise ValueError(
                f"{path} was written with manifest schema {record['schema']}; this "
                f"version of omphjc reads schema {SCHEMA_VERSION}"
            )
        try:
            stages = {}
            for name, stage in record["stages"].items():
                result = TaskResult.from_record(stage.pop("result"), path.parent)
                stages[name] = TaskRecord(**stage, result=result)
            return cls(
                process=record["process"],
                job_id=record["job_id"],
                omphjc_version=record["omphjc_version"],
                stages=stages,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None


def timestamp() -> str:
    """The current time in the manifest's format, ISO 8601 UTC to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
