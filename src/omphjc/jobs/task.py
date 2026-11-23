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
      "parameters": {"events": 1000, "seed": 10000001},
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
      ],
      "accepted_input": null
    }

Every path in the record is relative to the job directory. The top-level
keys are:

``schema``
    The layout version of the file (:mod:`omphjc.jobs.job_file`).
``identity``
    The stage, the tool and the tag of the task
    (:class:`~omphjc.jobs.identity.TaskIdentity`). The directory of the task
    is named after them.
``settings``
    What the task was made with: the fields of its class, such as the event
    count of a generation or the time limit of its program
    (:meth:`Task.settings`). A job makes the task again from them
    (:meth:`omphjc.jobs.Job.task_from_record`).
``parameters``
    What fixes the files of the task, including the seed when the task uses
    one (:meth:`Task.parameters`). A later request compares its own
    parameters with these to decide whether the result can be kept. A
    setting that does not change the files, such as the time limit, is not
    among them.
``result``
    What the task made (:class:`~omphjc.runs.RunResult`). It is ``null`` unless the
    latest run is done.
``runs``
    The runs of the task, oldest first.
``accepted_input``
    An input that the task was kept for although it read another one. It is
    ``null`` when there is none.

**The result.** ``outputs`` holds the files the task made, under the names
its class gives them. Each output has its ``path``, its size in bytes,
``n_bytes``, and the ``fingerprint`` of its content in its format, which is
``null`` for a file recorded without being read
(:class:`~omphjc.data_files.FileRecord`). An event file also has its
``format`` and the number of events it holds
(:class:`~omphjc.events.formats.EventFileRecord`). The next task reads the
output named ``events``.

``cards`` holds the cards of the task, under the names their classes give
them. A card is a file that steers the task's program, such as a run card or
a detector card. Each card is recorded as an output is, with the fingerprint
of its parsed content (:class:`~omphjc.data_files.Card`), so that two cards
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
- :meth:`TaskRecord.with_accepted_input` records an acceptance.
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
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, get_args

from omphjc.data_files import FileRecord
from omphjc.events.formats import EventFileRecord, EventFormat
from omphjc.jobs.identity import TaskIdentity
from omphjc.jobs.job_file import JobFile
from omphjc.runs import RunResult
from omphjc.safe_paths import inside, remove_inside
from omphjc.stages import Stage
from omphjc.stamps import COMPACT_UTC_FORMAT

if TYPE_CHECKING:
    from omphjc.jobs.job import Job

# How a run ended, or that it is still running.
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"

_STATUSES = (RUNNING, DONE, FAILED, INTERRUPTED)

_RUN_ID_RANDOM_BYTES = 4
"""Random bytes in a run ID, written as twice as many hexadecimal digits."""

INPUT_FINGERPRINT_PARAMETER = "input_fingerprint"
"""The parameter that holds the fingerprint of the events a task reads."""


@dataclass(frozen=True)
class TaskOutcome:
    """What :meth:`Task.execute` returns: the task's result and the run's own facts.

    Parameters
    ----------
    result : RunResult
        What the task made.
    usage : dict[str, float]
        Resources the task's program used, such as ``cpu_seconds`` and
        ``peak_memory_mib``. The job adds ``wall_seconds``.
    set_aside_dir : Path or None
        The folder, inside the job directory, that holds what an earlier run
        left and this run could not confirm as that run's
        (:mod:`omphjc.stamps`). It is ``None`` when nothing was moved.
    """

    result: RunResult
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
class TaskRecord(JobFile):
    """What one task did; the module docstring describes the fields.

    Raises
    ------
    ValueError
        If the record has no run. If it holds a result while its latest run
        is not done, or no result while that run is done. If it holds an
        accepted input while its latest run is not done.
    """

    file_name: ClassVar[str] = "task.json"

    identity: TaskIdentity
    settings: dict[str, Any]
    parameters: dict[str, Any]
    runs: tuple[TaskRun, ...]
    result: RunResult | None = None
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
        """Return the identity, the settings, the parameters, the result, the runs
        and the accepted input by name."""
        accepted_input = self.accepted_input
        return {
            "identity": asdict(self.identity),
            "settings": self.settings,
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
        values = dict(record)
        identity = TaskIdentity(**values.pop("identity"))
        runs = tuple(TaskRun(**run) for run in values.pop("runs"))
        result = values.pop("result")
        accepted_input = values.pop("accepted_input")
        return cls(
            identity=identity,
            **values,
            runs=runs,
            result=None if result is None else RunResult.from_record(result, root_dir),
            accepted_input=(
                None if accepted_input is None else AcceptedInput(**accepted_input)
            ),
        )

    @classmethod
    def read(cls, path: Path, *, root_dir: Path | None = None) -> "TaskRecord":
        """Return the record in the file `path`, the ``task.json`` of a task.

        Raises
        ------
        ValueError
            As :meth:`omphjc.jobs.job_file.JobFile.read` refuses a file. If
            the directory of `path` is not named after the task that the
            record identifies.
        """
        record = super().read(path, root_dir=root_dir)
        if record.identity.name != path.parent.name:
            raise ValueError(
                f"{path} is the record of the task {record.identity.name}, "
                f"but its directory is named {path.parent.name}. Name the "
                f"directory {record.identity.name} again, or remove it."
            )
        return record

    @classmethod
    def running(
        cls,
        identity: TaskIdentity,
        settings: dict[str, Any],
        parameters: dict[str, Any],
    ) -> "TaskRecord":
        """Return the record of the new task `identity`, whose first run starts now."""
        return cls(identity, settings, parameters, (TaskRun.started_now(),))

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

    def current_status(self) -> "tuple[TaskStatus, str]":
        """Return the status of the task now, with its output files checked.

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

    def _runs_with_latest(self, **changes: Any) -> tuple[TaskRun, ...]:
        """Return the runs, the latest with its fields replaced by `changes`."""
        return (*self.runs[:-1], replace(self.latest_run, **changes))

    def _done_result(self) -> RunResult:
        """Return the result of a record whose latest run is done."""
        if self.result is None:
            raise ValueError(
                "The task record has no result: its latest run has status "
                f"{self.latest_run.status!r}"
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


# The names of the fields of a task that are not settings: its job, and its
# tag, which is a part of its identity.
_NON_SETTING_FIELD_NAMES = ("job", "tag")


@dataclass(frozen=True)
class TaskInput:
    """An input of a task: events that another task of its job made.

    Parameters
    ----------
    name : str
        The name of the input, such as ``"events"``.
    formats : frozenset[EventFormat]
        The formats of event file that the task reads for this input.
    upstream_stage : Stage
        The stage whose task makes the events. The job must hold exactly one
        task of that stage.
    """

    name: str
    formats: frozenset[EventFormat]
    upstream_stage: Stage


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
    job makes the
    tasks it finds on disk from their records (:meth:`omphjc.jobs.Job.tasks`,
    :meth:`omphjc.jobs.Job.task_from_record`), each as an object of its own
    class with the settings it ran with.

    Two tasks are equal when they are of the same class and the same job,
    with the same tag and the same settings.

    Parameters
    ----------
    job : Job
        The job that the task belongs to.
    tag : str or None, optional
        A label that tells the task apart from another task of the same stage
        and tool. Most tasks have none.
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
    """What the task reads from another task of its job. A task has at most one
    input."""

    job: "Job" = field(kw_only=False)
    tag: str | None = None
    timeout_seconds: float | None = None
    program_path: Path | None = None

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
        """Whether the task is done now, with its output files checked.

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
    def parameters(self, input_events: Mapping[str, EventFileRecord]) -> dict[str, Any]:
        """Return what fixes the files of the task, as JSON values.

        A later request compares its parameters with these to decide whether
        the result can be kept. They hold the seed of the job when the task
        uses it. The fingerprint of the events that the task reads is added
        by :meth:`run`.

        Parameters
        ----------
        input_events : Mapping[str, EventFileRecord]
            The events that the task reads, by the name of the input. It is
            empty for a task without an input.
        """

    @abstractmethod
    def execute(
        self,
        input_events: Mapping[str, EventFileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        """Carry out one run of the task and return what it made.

        A class runs the program of its tool here. The method is called
        when the task has to run, and what it returns is recorded.

        Parameters
        ----------
        input_events : Mapping[str, EventFileRecord]
            The events that the task reads, by the name of the input. It is
            empty for a task without an input.
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

        The record gives the tag of the task and the settings it was made
        with (:meth:`settings`). A path that was recorded as a string is a
        :class:`~pathlib.Path` again.

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
                f"the {identity.name} task. Use Job.task_from_record, which "
                "picks the class of a record."
            )
        settings = dict(record.settings)
        for task_field in fields(cls):
            value = settings.get(task_field.name)
            if isinstance(value, str) and _is_path_type(task_field.type):
                settings[task_field.name] = Path(value)
        try:
            return cls(job, tag=identity.tag, **settings)
        except TypeError as error:
            raise ValueError(
                f"The settings recorded for the {identity.name} task are not "
                f"those of {cls.__name__} ({error}). Run {identity.command} "
                "with --force to make the task again."
            ) from None

    def upstream_tasks(self) -> dict[str, "Task"]:
        """Return the task that makes each input of the task, by the name of the input.

        The task of an input is the only task of the input's stage that the
        job holds. A task without an input gives an empty mapping.

        Raises
        ------
        ValueError
            If the job holds no task of an input's stage, or several. The
            message names the command to run first, or the tasks.
        """
        upstream_tasks = {}
        for task_input in self.inputs:
            stage_name = task_input.upstream_stage.name
            stage_tasks = self.job.tasks(stage_name)
            if not stage_tasks:
                raise ValueError(
                    f"The {stage_name} stage of {self.job.root_dir} has no task; "
                    f"run omphjc {stage_name} first"
                )
            if len(stage_tasks) > 1:
                names = ", ".join(stage_task.name for stage_task in stage_tasks)
                raise ValueError(
                    f"The {stage_name} stage of {self.job.root_dir} has several "
                    f"tasks ({names}), and {self.name} reads the events of one"
                )
            upstream_tasks[task_input.name] = stage_tasks[0]
        return upstream_tasks

    def input_events(self) -> dict[str, EventFileRecord]:
        """Return the events that the task reads, by the name of the input.

        The events of an input are those that its upstream task made
        (:meth:`upstream_tasks`). A task without an input gives an empty
        mapping.

        Raises
        ------
        ValueError
            As :meth:`upstream_tasks` and :attr:`events` refuse. If the events
            of an input are in a format that the input does not state.
        """
        input_events = {}
        upstream_tasks = self.upstream_tasks()
        for task_input in self.inputs:
            upstream_task = upstream_tasks[task_input.name]
            events = upstream_task.events
            if events.format not in task_input.formats:
                readable_formats = sorted(
                    event_format.value for event_format in task_input.formats
                )
                raise ValueError(
                    f"{self.name} reads {', '.join(readable_formats)} files, but "
                    f"the {upstream_task.name} task of {self.job.root_dir} made a "
                    f"{events.format.value} file"
                )
            input_events[task_input.name] = events
        return input_events

    def requested_parameters(
        self, input_events: Mapping[str, EventFileRecord]
    ) -> dict[str, Any]:
        """Return the parameters that a run is recorded and compared with.

        They are the task's own parameters (:meth:`parameters`) and, for a
        task that reads events, the fingerprint of those events under the key
        :data:`INPUT_FINGERPRINT_PARAMETER`.

        Parameters
        ----------
        input_events : Mapping[str, EventFileRecord]
            The events that the task reads, by the name of the input
            (:meth:`input_events`).

        Raises
        ------
        ValueError
            If the task's own parameters use the key of the fingerprint.
        """
        parameters = self.parameters(input_events)
        for task_input in self.inputs:
            if INPUT_FINGERPRINT_PARAMETER in parameters:
                raise ValueError(
                    f"The parameters of {self.name} use the key "
                    f"{INPUT_FINGERPRINT_PARAMETER}, which holds the fingerprint "
                    "of its input"
                )
            fingerprint = input_events[task_input.name].fingerprint
            parameters = {INPUT_FINGERPRINT_PARAMETER: fingerprint, **parameters}
        return parameters

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
        """Run the task unless its result can be kept, and return its record.

        The job of the task runs it and records the run
        (:meth:`omphjc.jobs.Job.run_task`).

        Parameters
        ----------
        accept_input : bool, optional
            Keep a done task whose input alone has changed, and record the
            acceptance.
        force : bool, optional
            Run the task even when its result could be kept.

        Returns
        -------
        TaskRecord
            The record of the task, kept or new.

        Raises
        ------
        Exception
            As :meth:`omphjc.jobs.Job.run_task` raises.
        """
        return self.job.run_task(self, accept_input=accept_input, force=force)


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
