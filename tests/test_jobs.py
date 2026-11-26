import json
import os
import re
import shutil
import signal
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import awkward as ak
import pytest
from delphes_records import write_delphes_file

from omphjc import __version__
from omphjc.comparison import Difference
from omphjc.data_files import FileRecord
from omphjc.events import EventFileRecord, EventFormat
from omphjc.events.delphes_root import DelphesROOTFile
from omphjc.jobs import (
    EVENTS_INPUT,
    TASK_REGISTRY,
    AcceptedInput,
    InputRecord,
    Job,
    JobFileError,
    JobIdentity,
    Manifest,
    ReplacedRunError,
    Task,
    TaskIdentity,
    TaskInput,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskRecordError,
    TaskRegistry,
    TaskRun,
    TaskStatus,
    TaskSummary,
    TerminationError,
    exception_on_termination,
    job_seed,
)
from omphjc.processes import ProcessSpec, get_process
from omphjc.programs import ProgramError, available_cores
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.stages import GenerateStage, ShowerStage, SimulateStage, Stage
from omphjc.stamps import COMPACT_UTC_FORMAT, read_stamp
from omphjc.tasks import (
    DelphesSimulation,
    GenerationTask,
    MadGraphGeneration,
    PythiaShower,
    ShowerTask,
)
from omphjc.tools.delphes.card import DetectorCard, ParticlesCard
from omphjc.tools.delphes.driver import SimulationWorkspace
from omphjc.tools.madgraph.lhe_file import LHEFile
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT, PythiaCmnd

RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


TaskBody = Callable[[bool, Path], TaskOutcome]


@dataclass(frozen=True)
class XStage(Stage):
    name: ClassVar[str] = "x"


@dataclass(frozen=True)
class YStage(Stage):
    name: ClassVar[str] = "y"


@dataclass(frozen=True)
class ZStage(Stage):
    name: ClassVar[str] = "z"


@dataclass(frozen=True, kw_only=True)
class FakeTask(Task):
    """A task for tests: its parameters are given, and a function makes its files."""

    tool: ClassVar[str] = "fake"

    given_parameters: dict[str, Any] = field(default_factory=dict)
    body: TaskBody | None = None

    def parameters(self, input_files: Mapping[str, FileRecord]) -> dict[str, Any]:
        return dict(self.given_parameters)

    def execute(
        self,
        input_files: Mapping[str, FileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        assert self.body is not None
        return self.body(overwrite, log_path)

    def settings(self) -> dict[str, Any]:
        settings = super().settings()
        del settings["body"]
        return settings


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeX(FakeTask):
    stage: ClassVar[Stage] = XStage()


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeY(FakeTask):
    stage: ClassVar[Stage] = YStage()


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeZ(FakeTask):
    stage: ClassVar[Stage] = ZStage()


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class OtherToolX(FakeTask):
    """A task of stage ``x`` whose untagged name is that of ``x-fake`` tagged ``tuneA``."""

    stage: ClassVar[Stage] = XStage()
    tool: ClassVar[str] = "fake-tuneA"


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeShower(FakeTask):
    """A task of the shower stage, whose events the simulation tasks read."""

    stage: ClassVar[Stage] = ShowerStage()
    outputs: ClassVar[tuple[TaskOutput, ...]] = (
        TaskOutput(EVENTS_OUTPUT, DelphesROOTFile.format_name),
    )


@dataclass(frozen=True)
class FakeUpstream:
    """Stands for the task that makes an input of a ``FakeReader``."""

    name: str
    events: EventFileRecord


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeReader(FakeTask):
    """A task of stage ``x`` with two inputs, whose fingerprints a test gives."""

    stage: ClassVar[Stage] = XStage()
    tool: ClassVar[str] = "reader"
    inputs: ClassVar[tuple[TaskInput, ...]] = (
        TaskInput(EVENTS_INPUT, FakeShower),
        TaskInput("pileup", FakeShower),
    )

    upstream: Mapping[str, str] = field(
        default_factory=lambda: {EVENTS_INPUT: "y-events", "pileup": "y-pileup"}
    )
    given_input_fingerprints: dict[str, str | None] = field(default_factory=dict)

    def upstream_tasks(self) -> dict[str, Task]:
        return {
            input_name: FakeUpstream(
                f"y-{input_name}",
                EventFileRecord(Path(input_name), 0, fingerprint, EventFormat.LHE, 0),
            )
            for input_name, fingerprint in self.given_input_fingerprints.items()
        }

    def input_files(
        self, upstream_tasks: Mapping[str, Task] | None = None
    ) -> dict[str, FileRecord]:
        if upstream_tasks is None:
            upstream_tasks = self.upstream_tasks()
        return {
            input_name: upstream_task.events
            for input_name, upstream_task in upstream_tasks.items()
        }

    def settings(self) -> dict[str, Any]:
        settings = super().settings()
        del settings["given_input_fingerprints"]
        return settings


TASK_X = TaskIdentity("x", "fake")
TASK_Y = TaskIdentity("y", "fake")
TASK_Z = TaskIdentity("z", "fake")
TASK_FAKE_SHOWER = TaskIdentity("shower", "fake")
TASK_READER = TaskIdentity("x", "reader")


def _task(job: Job, identity: TaskIdentity, **fields: Any) -> Task:
    """Return the task `identity` of `job`, made from the class registered for it."""
    return TASK_REGISTRY.get(identity)(job, tag=identity.tag, **fields)


def _run_task(
    job: Job,
    identity: TaskIdentity,
    parameters: dict[str, Any],
    body: TaskBody,
    **options: bool,
) -> TaskRecord:
    """Run the task `identity` of `job` with `parameters`; `body` makes its files."""
    return _task(job, identity, given_parameters=parameters, body=body).run(**options)


def _status_detail_and_record(
    job: Job, identity: TaskIdentity
) -> tuple[TaskStatus, str, TaskRecord | None]:
    """Return the status of the task `identity` of `job`, its detail and its record."""
    task = _task(job, identity)
    record = task.record
    detail = "" if record is None else record.current_status()[1]
    return task.status, detail, record


def _run(status: str, **fields: Any) -> TaskRun:
    """Return a run with `status`, `fields` and a placeholder ID, start and host."""
    return TaskRun(run_id="r1", status=status, started="t", host="h", **fields)


def test_job_seed_is_the_process_offset_plus_the_job_number() -> None:
    assert job_seed(get_process("HToBB"), 7) == 10000007
    assert job_seed(get_process("HToCC"), 7) == 20000007
    assert job_seed(get_process("TTBar"), 1) == 1
    with pytest.raises(ValueError, match="job_id"):
        job_seed(get_process("HToBB"), 0)
    with pytest.raises(ValueError, match="limit"):
        job_seed(get_process("HToBB"), PYTHIA_SEED_LIMIT)


def test_a_task_identity_names_the_task_and_its_command() -> None:
    assert [stage.name for stage in (GenerateStage, ShowerStage, SimulateStage)] == [
        "generate",
        "shower",
        "simulate",
    ]
    untagged = TaskIdentity("shower", "pythia")
    assert (untagged.name, untagged.command) == ("shower-pythia", "omphjc shower")
    tagged = TaskIdentity("shower", "pythia", "tuneA")
    assert (tagged.name, tagged.command) == ("shower-pythia-tuneA", "omphjc shower")
    assert tagged != untagged and TaskIdentity("shower", "pythia") == untagged


@pytest.mark.parametrize(
    "parts", [("../x", "fake"), ("x", "a/b"), ("x", "fake", ""), ("x", "fake", "..")]
)
def test_a_task_identity_refuses_a_part_that_is_not_a_plain_name(
    parts: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="must consist of"):
        TaskIdentity(*parts)


def test_a_job_has_a_directory_per_process_and_number(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path / "runs", 7)
    assert job.root_dir == (tmp_path / "runs").resolve() / "HToBB" / "job_7"
    assert job.manifest_path == job.root_dir / "manifest.json"
    assert job.task_dir(TASK_X) == job.root_dir / "x-fake"
    assert (
        job.relative_path(job.root_dir / "generate-madgraph" / "x.log")
        == "generate-madgraph/x.log"
    )
    assert job.seed == 10000007
    assert job.identity_path == job.root_dir / "job.json"
    assert job.identity == JobIdentity(process="HToBB", job_id=7, seed=10000007)
    assert job.tasks() == []
    assert not job.root_dir.exists()
    with pytest.raises(ValueError, match="job_id"):
        Job(specs["HToBB"], tmp_path, 0)
    with pytest.raises(ValueError, match="filesystem root"):
        Job(specs["HToBB"], Path("/"), 1)


def test_a_task_record_round_trips_through_json(tmp_path: Path) -> None:
    output_path = tmp_path / "x-fake" / "out"
    record = TaskRecord(
        TASK_X,
        settings={"timeout_seconds": 30.0},
        parameters={"n_events": 10},
        inputs={
            "events": InputRecord(
                "generate-fake", "lhe-v1:def", AcceptedInput("lhe-v1:ghi", "t")
            )
        },
        runs=(_run("done", finished="u"),),
        result=RunResult(
            outputs={
                EVENTS_OUTPUT: EventFileRecord(
                    output_path,
                    n_bytes=7,
                    fingerprint="lhe-v1:abc",
                    format=EventFormat.LHE,
                    n_events=10,
                ),
                "summary": FileRecord(
                    tmp_path / "x-fake" / "summary.txt", n_bytes=3, fingerprint=None
                ),
            },
            cards={
                "run_card": FileRecord(
                    tmp_path / "x-fake" / "run_card.dat", 5, "run_card-v1:abc"
                )
            },
            metadata={"version": "1.0"},
        ),
    )
    path = tmp_path / "x-fake" / "task.json"
    path.parent.mkdir()
    record.write(path, root_dir=tmp_path)
    written = json.loads(path.read_text())
    assert written["schema"] == 1
    assert written["identity"] == {"stage": "x", "tool": "fake", "tag": None}
    assert written["settings"] == {"timeout_seconds": 30.0}
    assert written["parameters"] == {"n_events": 10}
    assert written["inputs"] == {
        "events": {
            "task": "generate-fake",
            "fingerprint": "lhe-v1:def",
            "accepted": {"fingerprint": "lhe-v1:ghi", "accepted_at": "t"},
        }
    }
    assert written["runs"] == [
        {
            "run_id": "r1",
            "status": "done",
            "started": "t",
            "host": "h",
            "finished": "u",
            "usage": {},
            "set_aside": None,
            "error": None,
        }
    ]
    assert written["result"] == {
        "outputs": {
            "events": {
                "path": "x-fake/out",
                "n_bytes": 7,
                "fingerprint": "lhe-v1:abc",
                "format": "lhe",
                "n_events": 10,
            },
            "summary": {
                "path": "x-fake/summary.txt",
                "n_bytes": 3,
                "fingerprint": None,
            },
        },
        "cards": {
            "run_card": {
                "path": "x-fake/run_card.dat",
                "n_bytes": 5,
                "fingerprint": "run_card-v1:abc",
            }
        },
        "metadata": {"version": "1.0"},
    }
    assert TaskRecord.read(path, root_dir=tmp_path) == record
    events = written["result"]["outputs"]["events"]
    events["format"] = "hepmc"
    path.write_text(json.dumps(written))
    with pytest.raises(ValueError, match="task.json has invalid content: 'hepmc'"):
        TaskRecord.read(path, root_dir=tmp_path)
    events["format"] = "lhe"
    del events["fingerprint"]
    path.write_text(json.dumps(written))
    with pytest.raises(ValueError, match="has invalid content: 'fingerprint'"):
        TaskRecord.read(path, root_dir=tmp_path)
    events["fingerprint"] = "lhe-v1:abc"
    del written["result"]["outputs"]["summary"]["n_bytes"]
    path.write_text(json.dumps(written))
    with pytest.raises(ValueError, match="has invalid content: 'n_bytes'"):
        TaskRecord.read(path, root_dir=tmp_path)
    path.write_text('{"schema": 99}')
    with pytest.raises(ValueError, match="schema 99; .* reads schema 1"):
        TaskRecord.read(path, root_dir=tmp_path)
    path.write_text('{"status": "done"}')
    with pytest.raises(ValueError, match="no schema"):
        TaskRecord.read(path, root_dir=tmp_path)
    path.write_text("not json")
    with pytest.raises(TaskRecordError, match="task.json is not valid JSON"):
        TaskRecord.read(path, root_dir=tmp_path)


def test_a_task_record_needs_a_run_and_a_result_that_fits_its_status(
    tmp_path: Path,
) -> None:
    done = _run("done")
    with pytest.raises(ValueError, match="the record lists no run"):
        TaskRecord(TASK_X, settings={}, parameters={}, runs=())
    no_result = (
        "the latest run is 'done', so the record should hold the result of that "
        "run, but it holds none"
    )
    with pytest.raises(ValueError, match=no_result):
        TaskRecord(TASK_X, settings={}, parameters={}, runs=(done,))
    failed = _run("failed", error="boom")
    with pytest.raises(ValueError, match="should hold no result, but it holds one"):
        TaskRecord(
            TASK_X, settings={}, parameters={}, runs=(failed,), result=RunResult()
        )
    with pytest.raises(ValueError, match="unknown run status 'paused'"):
        _run("paused")
    path = tmp_path / "x-fake" / "task.json"
    path.parent.mkdir()
    TaskRecord(
        TASK_X, settings={}, parameters={}, runs=(done,), result=RunResult()
    ).write(path, root_dir=tmp_path)
    without_runs = json.loads(path.read_text())
    del without_runs["runs"]
    path.write_text(json.dumps(without_runs))
    with pytest.raises(TaskRecordError) as refusal:
        TaskRecord.read(path, root_dir=tmp_path)
    assert refusal.value.path == path
    assert str(refusal.value) == (
        f"{path} has invalid content: the record lists no run, and a task record "
        "lists at least the run that made it.\n"
        "The file was changed after omphjc wrote it, or another version of omphjc "
        "wrote it. Restore the file, or remove it and run the task again."
    )


def test_a_record_gives_its_outputs_only_when_its_latest_run_is_done(
    tmp_path: Path,
) -> None:
    events = EventFileRecord(tmp_path / "e.lhe", 7, "lhe-v1:abc", EventFormat.LHE, 10)
    done = TaskRecord(
        TASK_X,
        settings={},
        parameters={},
        runs=(_run("done"),),
        result=RunResult(outputs={EVENTS_OUTPUT: events}, metadata={"n": 1}),
    )
    assert done.events == events and done.metadata == {"n": 1}
    assert done.is_done
    no_events = TaskRecord(TASK_X, {}, {}, (_run("done"),), RunResult())
    assert no_events.events is None
    failed = TaskRecord(TASK_X, {}, {}, (_run("failed", error="boom"),))
    assert not failed.is_done
    refusal = "The task record has no result: its latest run has status 'failed'"
    with pytest.raises(ValueError, match=re.escape(refusal)):
        _ = failed.outputs


def test_a_task_record_refuses_a_path_outside_its_root_directory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "job" / "x-fake" / "task.json"
    path.parent.mkdir(parents=True)
    record = TaskRecord(
        TASK_X,
        settings={},
        parameters={},
        runs=(_run("done"),),
        result=RunResult(
            outputs={"out": FileRecord(tmp_path / "elsewhere" / "out", 0, None)}
        ),
    )
    with pytest.raises(ValueError, match="elsewhere"):
        record.write(path, root_dir=tmp_path / "job")
    card_elsewhere = FileRecord(tmp_path / "elsewhere" / "card.dat", 5, None)
    record = TaskRecord(
        TASK_X,
        settings={},
        parameters={},
        runs=(_run("done"),),
        result=RunResult(cards={"card": card_elsewhere}),
    )
    with pytest.raises(ValueError, match="elsewhere"):
        record.write(path, root_dir=tmp_path / "job")
    assert list(path.parent.iterdir()) == []


def test_a_manifest_round_trips_through_json(tmp_path: Path) -> None:
    manifest = Manifest(
        JobIdentity(process="HToBB", job_id=1, seed=10000001),
        {
            "x": TaskSummary("done", "r1", 1, tmp_path / "x-fake" / "task.json"),
            "y": TaskSummary("running", "r2", 2, tmp_path / "y-fake" / "task.json"),
        },
    )
    path = tmp_path / "manifest.json"
    manifest.write(path)
    assert json.loads(path.read_text()) == {
        "schema": 1,
        "process": "HToBB",
        "job_id": 1,
        "seed": 10000001,
        "omphjc_version": __version__,
        "tasks": {
            "x": {
                "status": "done",
                "latest_run_id": "r1",
                "n_runs": 1,
                "record_path": "x-fake/task.json",
            },
            "y": {
                "status": "running",
                "latest_run_id": "r2",
                "n_runs": 2,
                "record_path": "y-fake/task.json",
            },
        },
    }
    assert Manifest.read(path) == manifest


def _make_output(job: Job, identity: TaskIdentity = TASK_X) -> TaskOutcome:
    directory = job.task_dir(identity)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "out.txt"
    output.write_text("made")
    return TaskOutcome(
        RunResult(
            outputs={"out": FileRecord(output, len("made"), None)},
            metadata={"n": 1},
        )
    )


def test_a_changed_or_deleted_card_leaves_the_task_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    card_path = job.task_dir(TASK_X) / "card.dat"

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        outcome = _make_output(job)
        card_path.write_text("as run")
        cards = {"card": FileRecord(card_path, len("as run"), None)}
        return replace(outcome, result=replace(outcome.result, cards=cards))

    record = _run_task(job, TASK_X, {}, body)
    assert record.cards == {"card": FileRecord(card_path, len("as run"), None)}
    card_path.write_text("edited since")
    assert _task(job, TASK_X).status is TaskStatus.DONE
    card_path.unlink()
    assert _task(job, TASK_X).status is TaskStatus.DONE
    assert _run_task(job, TASK_X, {}, body) == record


def test_a_stage_runs_once_and_its_result_is_kept(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(job, TASK_X, {"n_events": 10}, body)
    assert calls == [False]
    assert record.is_done and record.latest_run.finished is not None
    assert len(record.runs) == 1
    assert record.parameters == {"n_events": 10}
    assert record.inputs == {}
    assert record.result == RunResult(
        outputs={"out": FileRecord(job.root_dir / "x-fake" / "out.txt", 4, None)},
        metadata={"n": 1},
    )
    assert _task(job, TASK_X).record == record

    job = Job(specs["HToBB"], tmp_path, 1)
    assert _status_detail_and_record(job, TASK_X) == (TaskStatus.DONE, "", record)
    assert _run_task(job, TASK_X, {"n_events": 10}, body) == record
    assert calls == [False]


def test_other_parameters_need_force_and_force_replaces(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {"n_events": 10}, body)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError) as refusal:
        _run_task(job, TASK_X, {"n_events": 20}, body)
    assert str(refusal.value) == (
        "The current parameters are inconsistent with those of the existing "
        f"x-fake task in {job.root_dir} (x-fake/task.json):\n"
        "  n_events: expected 10, got 20\n"
        "Rerun with the parameters the task ran with, or run omphjc x with "
        "--force to replace its result."
    )
    forced = _run_task(job, TASK_X, {"n_events": 20}, body, force=True)
    assert forced.parameters == {"n_events": 20}
    assert len(forced.runs) == 1
    assert calls == [False, True]


def test_a_refusal_names_only_the_parameters_that_differ(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    overrides = {"Main:timesAllowErrors": 5, "Tune:pp": 14}
    _run_task(
        job,
        TASK_X,
        {"n_events": 10, "overrides": overrides},
        lambda *_: _make_output(job),
    )
    changed = {**overrides, "Main:timesAllowErrors": 7, "Next:numberCount": 0}
    with pytest.raises(ValueError) as refusal:
        _run_task(
            job,
            TASK_X,
            {"n_events": 10, "overrides": changed},
            lambda *_: _make_output(job),
        )
    assert str(refusal.value).splitlines()[1:-1] == [
        "  overrides.Main:timesAllowErrors: expected 5, got 7",
        "  unexpected overrides.Next:numberCount: 0",
    ]


def test_a_stage_with_missing_outputs_or_left_running_runs_again(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        outcome = _make_output(job)
        return replace(
            outcome, result=replace(outcome.result, metadata={"n": len(calls)})
        )

    job = Job(specs["HToBB"], tmp_path, 1)
    assert _status_detail_and_record(job, TASK_X) == (TaskStatus.NOT_DONE, "", None)
    record = _run_task(job, TASK_X, {}, body)
    output_path = job.root_dir / "x-fake" / "out.txt"
    output_path.unlink()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert _status_detail_and_record(job, TASK_X) == (
        TaskStatus.MISSING_OUTPUT,
        f"{output_path} is missing",
        record,
    )
    rerun = _run_task(job, TASK_X, {}, body)
    assert calls == [False, True]
    assert [run.status for run in rerun.runs] == ["done", "done"]
    assert rerun.metadata == {"n": 2}

    running = TaskRecord(TASK_X, {}, {}, (_run("running"),))
    running.write(_task(job, TASK_X).record_path, root_dir=job.root_dir)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert _status_detail_and_record(job, TASK_X) == (TaskStatus.NOT_DONE, "", running)
    after_kill = _run_task(job, TASK_X, {}, body)
    assert [run.status for run in after_kill.runs] == [
        "interrupted",
        "done",
    ]
    assert after_kill.runs[0].finished is None
    assert calls == [False, True, True]


def test_require_done_returns_the_record_or_says_which_stage_to_run(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    not_done = "The x-fake task of .* has not run to completion; run omphjc x first"
    with pytest.raises(ValueError, match=not_done):
        _task(job, TASK_X).require_done()
    record = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    assert _task(job, TASK_X).require_done() == record
    (job.root_dir / "x-fake" / "out.txt").unlink()
    with pytest.raises(ValueError, match=not_done):
        _task(job, TASK_X).require_done()


def test_a_stage_whose_output_has_another_size_is_refused_unless_forced(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(job, TASK_X, {}, body)
    output_path = job.root_dir / "x-fake" / "out.txt"
    output_path.write_text("made and changed")
    job = Job(specs["HToBB"], tmp_path, 1)
    detail = f"{output_path} holds 16 bytes, not the 4 the x-fake task recorded"
    assert _status_detail_and_record(job, TASK_X) == (
        TaskStatus.CHANGED,
        detail,
        record,
    )
    refused = re.escape(f"{detail}; run omphjc x with --force to regenerate the file")
    with pytest.raises(ValueError, match=refused):
        _task(job, TASK_X).require_done()
    with pytest.raises(ValueError, match=refused):
        _run_task(job, TASK_X, {}, body)
    assert calls == [False]
    assert _run_task(job, TASK_X, {}, body, force=True).is_done
    assert calls == [False, True]
    assert _task(job, TASK_X).require_done().result.outputs["out"].n_bytes == 4


def test_an_output_of_another_size_is_reported_before_a_missing_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    first_path = job.task_dir(TASK_X) / "first.txt"
    second_path = job.task_dir(TASK_X) / "second.txt"

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        job.task_dir(TASK_X).mkdir(parents=True, exist_ok=True)
        outputs = {}
        for name, path in (("first", first_path), ("second", second_path)):
            path.write_text("made")
            outputs[name] = FileRecord(path, len("made"), None)
        return TaskOutcome(RunResult(outputs=outputs))

    record = _run_task(job, TASK_X, {}, body)
    first_path.unlink()
    second_path.write_text("made and changed")
    assert _status_detail_and_record(job, TASK_X) == (
        TaskStatus.CHANGED,
        f"{second_path} holds 16 bytes, not the 4 the x-fake task recorded",
        record,
    )
    with pytest.raises(ValueError, match="with --force to regenerate the file"):
        _run_task(job, TASK_X, {}, body)


def test_a_task_gives_its_events_only_once_it_is_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="has not run to completion"):
        _ = _task(job, TASK_X).events
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    with pytest.raises(ValueError, match="The x-fake task of .* made no event file"):
        _ = _task(job, TASK_X).events

    events = EventFileRecord(
        job.task_dir(TASK_X) / "out.txt",
        n_bytes=len("made"),
        fingerprint="lhe-v1:abc",
        format=EventFormat.LHE,
        n_events=3,
    )
    _run_task(
        job,
        TASK_X,
        {},
        lambda overwrite, log_path: TaskOutcome(
            RunResult(outputs={EVENTS_OUTPUT: events})
        ),
        force=True,
    )
    assert _task(Job(specs["HToBB"], tmp_path, 1), TASK_X).events == events


def test_a_failed_stage_is_recorded_raised_and_replaced_on_retry(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool, log_path: Path) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_X, {"n_events": 10}, failing)
    record = _task(job, TASK_X).record
    assert record is not None
    assert (
        record.latest_run.status == "failed" and record.latest_run.finished is not None
    )
    assert record.parameters == {"n_events": 10} and record.result is None
    assert record.latest_run.error == "boom"

    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    rerun = _run_task(job, TASK_X, {"n_events": 10}, body)
    assert [run.status for run in rerun.runs] == ["failed", "done"]
    assert rerun.runs[0].usage == {}
    assert rerun.runs[1].usage["wall_seconds"] >= 0
    assert calls == [True]

    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_Y, {"n_events": 10}, failing)
    other = _run_task(job, TASK_Y, {"n_events": 20}, body)
    assert len(other.runs) == 1


def _fail(overwrite: bool, log_path: Path) -> TaskOutcome:
    raise RuntimeError("boom")


def test_each_run_has_an_id_that_begins_with_its_start_time(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_X, {}, _fail)
    record = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    first, second = record.runs
    assert first.run_id != second.run_id
    for run in record.runs:
        assert RUN_ID.fullmatch(run.run_id)
        start_time = datetime.fromisoformat(run.started)
        assert run.run_id.startswith(start_time.strftime(COMPACT_UTC_FORMAT))
    manifest = Manifest.read(job.manifest_path)
    assert manifest.tasks["x-fake"].latest_run_id == second.run_id


def test_a_run_records_the_host_it_ran_on(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    assert record.latest_run.host == socket.gethostname()


def _write_log_then_stop(overwrite: bool, log_path: Path) -> TaskOutcome:
    log_path.write_text("stopped")
    raise TerminationError("terminated by signal 15")


def _write_log(job: Job) -> TaskBody:
    """Return a body that writes its log and makes the output of `job`."""

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        log_path.write_text("finished")
        return _make_output(job)

    return body


def test_each_run_of_a_task_has_a_log_named_by_its_run_id(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(TerminationError):
        _run_task(job, TASK_X, {}, _write_log_then_stop)
    first, second = _run_task(job, TASK_X, {}, _write_log(job)).runs
    logs_dir = job.task_dir(TASK_X) / "logs"
    assert _task(job, TASK_X).log_path(first.run_id) == logs_dir / f"{first.run_id}.log"
    assert _task(job, TASK_X).log_path(first.run_id).read_text() == "stopped"
    assert _task(job, TASK_X).log_path(second.run_id).read_text() == "finished"
    assert {path.name for path in logs_dir.iterdir()} == {
        f"{first.run_id}.log",
        f"{second.run_id}.log",
    }
    assert _task(job, TASK_X).latest_log == logs_dir / f"{second.run_id}.log"


def test_a_task_states_its_identity_its_directory_and_its_record_path(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    task = FakeX(job)
    assert (task.identity, task.name) == (TASK_X, "x-fake")
    assert task.directory == job.task_dir(TASK_X) == job.root_dir / "x-fake"
    assert task.record_path == job.root_dir / "x-fake" / "task.json"
    assert (task.record, task.status) == (None, TaskStatus.NOT_DONE)
    tagged = FakeX(job, tag="tuneA")
    assert tagged.identity == TaskIdentity("x", "fake", "tuneA")
    assert tagged.directory == job.root_dir / "x-fake-tuneA"
    with pytest.raises(ValueError, match="must consist of"):
        _ = FakeX(job, tag="../elsewhere").identity
    assert not job.root_dir.exists()


def test_the_task_classes_state_their_stage_tool_and_input(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    tasks = [
        MadGraphGeneration(job, n_events=10),
        PythiaShower(job, upstream={EVENTS_INPUT: "generate-madgraph"}),
        DelphesSimulation(job, upstream={EVENTS_INPUT: "shower-pythia"}),
    ]
    assert [task.name for task in tasks] == [
        "generate-madgraph",
        "shower-pythia",
        "simulate-delphes",
    ]
    assert [task.stage for task in tasks] == [
        GenerateStage(),
        ShowerStage(),
        SimulateStage(),
    ]
    assert [TASK_REGISTRY.get(task.identity) for task in tasks] == [
        MadGraphGeneration,
        PythiaShower,
        DelphesSimulation,
    ]
    upstream_classes = [
        task_input.upstream_class for task in tasks for task_input in task.inputs
    ]
    assert upstream_classes == [GenerationTask, ShowerTask]
    assert [task.outputs for task in tasks] == [
        (TaskOutput(EVENTS_OUTPUT, LHEFile.format_name),),
        (TaskOutput(EVENTS_OUTPUT, DelphesROOTFile.format_name),),
        (TaskOutput(EVENTS_OUTPUT, DelphesROOTFile.format_name),),
    ]


def test_a_task_records_its_settings_and_is_made_again_from_them(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    task = MadGraphGeneration(job, n_events=10, n_cores=2, program_path=mg5_path)
    settings = {
        "timeout_seconds": None,
        "program_path": str(mg5_path),
        "n_events": 10,
        "n_cores": 2,
    }
    assert task.settings() == settings
    record = task.run()
    assert record.settings == settings
    assert json.loads(task.record_path.read_text())["settings"] == settings
    reopened_job = Job(specs["HToBB"], tmp_path, 1)
    assert reopened_job.tasks() == [task]
    assert reopened_job.get_task(record) == task
    assert reopened_job.get_task(task.name) == task
    assert MadGraphGeneration.from_record(reopened_job, record) == task
    refusal = (
        "PythiaShower expects the record of a task with stage 'shower' and tool "
        "'pythia', got the record of the generate-madgraph task"
    )
    with pytest.raises(ValueError, match=refusal):
        PythiaShower.from_record(reopened_job, record)
    tagged = PythiaShower(
        job, tag="tuneA", overrides={"Tune:pp": 14}, timeout_seconds=60.0
    )
    assert tagged.settings() == {
        "timeout_seconds": 60.0,
        "program_path": None,
        "overrides": {"Tune:pp": 14},
    }


def test_a_job_makes_each_task_on_disk_as_an_object_of_its_class(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(job, TASK_X, {"n_events": 10}, _write_log(job))
    _run_task(job, TaskIdentity("x", "fake", "tuneA"), {}, _write_log(job))
    _run_task(job, TASK_Y, {}, _write_log(job))
    x_task, tagged_task, y_task = Job(specs["HToBB"], tmp_path, 1).tasks()
    assert [type(task) for task in (x_task, tagged_task, y_task)] == [
        FakeX,
        FakeX,
        FakeY,
    ]
    assert x_task == FakeX(job, given_parameters={"n_events": 10})
    assert tagged_task == FakeX(job, tag="tuneA")
    assert (x_task.status, x_task.record) == (TaskStatus.DONE, record)
    assert x_task.latest_log.read_text() == "finished"
    assert job.tasks("x") == [x_task, tagged_task]
    assert job.tasks("y") == [y_task]
    assert job.tasks("z") == []


def test_a_record_of_a_stage_and_tool_without_a_class_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, _write_log(job))
    unknown = TaskIdentity("x", "unknown")
    record = TaskRecord(unknown, {}, {}, (_run("failed"),))
    job.task_dir(unknown).mkdir()
    record.write(job.task_dir(unknown) / "task.json", root_dir=job.root_dir)
    refusal = "No task class is registered for the stage 'x' and the tool 'unknown'"
    with pytest.raises(ValueError, match=refusal):
        job.tasks()


def test_a_record_with_settings_that_are_not_those_of_its_class_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = TaskRecord(TASK_X, {"n_events": 10}, {}, (_run("failed"),))
    job.task_dir(TASK_X).mkdir(parents=True)
    record.write(FakeX(job).record_path, root_dir=job.root_dir)
    refusal = "The settings recorded for the x-fake task are not those of FakeX"
    with pytest.raises(ValueError, match=refusal):
        job.tasks()


def test_a_registry_holds_one_class_per_stage_and_tool() -> None:
    registry = TaskRegistry()
    assert registry.register(FakeX) is FakeX
    assert registry.register(FakeX) is FakeX
    assert registry.get(TaskIdentity("x", "fake", "tuneA")) is FakeX

    @dataclass(frozen=True, kw_only=True)
    class SecondFakeX(FakeTask):
        stage: ClassVar[Stage] = XStage()

    refusal = (
        "The tasks of stage 'x' and tool 'fake' already have the class FakeX, so "
        "SecondFakeX cannot be registered for them"
    )
    with pytest.raises(ValueError, match=refusal):
        registry.register(SecondFakeX)
    with pytest.raises(ValueError, match="No task class is registered"):
        registry.get(TASK_Y)


def test_a_task_without_a_record_has_no_latest_log(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    task = _task(Job(specs["HToBB"], tmp_path, 1), TASK_X)
    assert task.record is None
    with pytest.raises(ValueError, match="has no run"):
        _ = task.latest_log


@pytest.mark.parametrize(
    ("parameters", "force"), [({"n_events": 20}, False), ({}, True)]
)
def test_a_new_record_removes_the_logs_of_the_runs_it_drops(
    specs: Mapping[str, ProcessSpec],
    tmp_path: Path,
    parameters: dict[str, Any],
    force: bool,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(TerminationError):
        _run_task(job, TASK_X, {}, _write_log_then_stop)
    logs_dir = job.task_dir(TASK_X) / "logs"
    (logs_dir / "notes.txt").write_text("mine")
    record = _run_task(job, TASK_X, parameters, _write_log(job), force=force)
    assert len(record.runs) == 1
    assert sorted(path.name for path in logs_dir.iterdir()) == [
        f"{record.latest_run.run_id}.log",
        "notes.txt",
    ]


def test_a_dropped_run_whose_id_is_not_a_plain_name_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    outside_path = tmp_path / "outside.log"
    outside_path.write_text("not a log of the task")
    record = TaskRecord(
        TASK_X,
        {},
        {},
        (
            TaskRun(
                run_id="../../../../outside", status="failed", started="t", host="h"
            ),
        ),
    )
    job.task_dir(TASK_X).mkdir(parents=True)
    record.write(_task(job, TASK_X).record_path, root_dir=job.root_dir)
    with pytest.raises(ValueError, match="Path component"):
        _run_task(job, TASK_X, {"n_events": 20}, _write_log(job))
    assert outside_path.read_text() == "not a log of the task"
    assert _task(job, TASK_X).record == record


def test_a_run_whose_log_directory_cannot_be_made_is_recorded_as_failed(
    specs: Mapping[str, ProcessSpec],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_directory = Path.mkdir

    def refuse_log_directories(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "logs":
            raise PermissionError("no log directory")
        make_directory(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_log_directories)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(PermissionError):
        _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    record = _task(job, TASK_X).record
    assert record is not None
    assert record.latest_run.status == "failed"
    assert record.latest_run.error == "no log directory"


@pytest.mark.parametrize(
    ("error", "recorded_error"),
    [
        (TerminationError("terminated by signal 15"), "terminated by signal 15"),
        (KeyboardInterrupt(), "KeyboardInterrupt"),
    ],
    ids=["sigterm", "keyboard"],
)
def test_a_run_that_a_signal_ended_is_recorded_as_interrupted(
    specs: Mapping[str, ProcessSpec],
    tmp_path: Path,
    error: BaseException,
    recorded_error: str,
) -> None:
    def stop(overwrite: bool, log_path: Path) -> TaskOutcome:
        raise error

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(type(error)):
        _run_task(job, TASK_X, {}, stop)
    record = _task(job, TASK_X).record
    assert record is not None
    interrupted_run = record.latest_run
    assert interrupted_run.status == "interrupted"
    assert interrupted_run.error == recorded_error
    assert interrupted_run.finished is not None
    rerun = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    assert [run.status for run in rerun.runs] == ["interrupted", "done"]


def test_a_failure_without_a_message_is_recorded_by_its_type(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def fail_without_message(overwrite: bool, log_path: Path) -> TaskOutcome:
        raise AssertionError

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(AssertionError):
        _run_task(job, TASK_X, {}, fail_without_message)
    record = _task(job, TASK_X).record
    assert record is not None
    assert record.latest_run.status == "failed"
    assert record.latest_run.error == "AssertionError"


@pytest.mark.parametrize("fails", [False, True], ids=["finishes", "fails"])
def test_a_run_replaced_by_a_newer_run_leaves_that_runs_record(
    specs: Mapping[str, ProcessSpec], tmp_path: Path, fails: bool
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    replaced_run_ids: list[str] = []
    newer_records: list[TaskRecord] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        replaced_run_ids.append(log_path.stem)
        newer_record = TaskRecord.running(TASK_X, {}, {"n_events": 20}, {})
        newer_record.write(_task(job, TASK_X).record_path, root_dir=job.root_dir)
        newer_records.append(newer_record)
        if fails:
            raise RuntimeError("boom")
        return _make_output(job)

    with pytest.raises(ReplacedRunError) as refusal:
        _run_task(job, TASK_X, {"n_events": 10}, body)
    (replaced_run_id,) = replaced_run_ids
    (newer_record,) = newer_records
    assert _task(job, TASK_X).record == newer_record
    status = "failed" if fails else "done"
    assert str(refusal.value) == (
        f"Run {replaced_run_id!r} of the x-fake task in {job.root_dir} is not recorded "
        f"as {status}: run {newer_record.latest_run.run_id!r} of the task started "
        "before it ended"
    )
    assert isinstance(refusal.value.__context__, RuntimeError) is fails


def test_a_run_whose_record_was_deleted_records_its_end(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)

    def delete_record_then_finish(overwrite: bool, log_path: Path) -> TaskOutcome:
        _task(job, TASK_X).record_path.unlink()
        return _make_output(job)

    record = _run_task(job, TASK_X, {}, delete_record_then_finish)
    assert record.is_done
    assert _task(job, TASK_X).record == record


PARAMETERS = {"n_events": 10}
INPUT_FINGERPRINTS = {"events": "v1:original", "pileup": "v1:minimum-bias"}
CHANGED_INPUT_FINGERPRINTS = {**INPUT_FINGERPRINTS, "events": "v1:changed"}
CHANGED_INPUT = "  fingerprint of events: expected v1:original, got v1:changed\n"


def _run_on_inputs(
    job: Job,
    input_fingerprints: dict[str, str | None],
    *,
    parameters: Mapping[str, Any] = PARAMETERS,
    body: TaskBody | None = None,
    **options: bool,
) -> TaskRecord:
    """Run the reader task of `job` on inputs with `input_fingerprints`.

    The task has `parameters`. `body` makes its files, and by default it makes
    one output in the directory of the task.
    """
    task = _task(
        job,
        TASK_READER,
        given_parameters=dict(parameters),
        given_input_fingerprints=input_fingerprints,
        body=body or (lambda overwrite, log_path: _make_output(job, TASK_READER)),
    )
    return task.run(**options)


def test_a_task_refuses_an_input_file_recorded_without_a_fingerprint(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    refusal = (
        "x-reader reads events as its events input, but the file is recorded "
        "without a fingerprint"
    )
    with pytest.raises(ValueError, match=refusal):
        _run_on_inputs(job, {EVENTS_INPUT: None, "pileup": "pileup-v1:a"})
    assert not _task(job, TASK_READER).record_path.exists()


def _acceptances(record: TaskRecord) -> dict[str, str | None]:
    """Return the fingerprint each input of `record` was accepted for, or ``None``."""
    return {
        input_name: (
            None if input_record.accepted is None else input_record.accepted.fingerprint
        )
        for input_name, input_record in record.inputs.items()
    }


def test_a_task_records_each_input_apart_from_its_parameters(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_on_inputs(job, INPUT_FINGERPRINTS)
    assert record.parameters == PARAMETERS
    assert record.inputs == {
        "events": InputRecord("y-events", "v1:original"),
        "pileup": InputRecord("y-pileup", "v1:minimum-bias"),
    }
    assert record.input_fingerprints == INPUT_FINGERPRINTS
    assert _run_on_inputs(job, INPUT_FINGERPRINTS) == record
    other_pileup = {**INPUT_FINGERPRINTS, "pileup": "v1:other"}
    with pytest.raises(ValueError) as refusal:
        _run_on_inputs(job, other_pileup)
    assert str(refusal.value).splitlines()[1:-1] == [
        "  fingerprint of pileup: expected v1:minimum-bias, got v1:other"
    ]


def test_a_done_task_whose_inputs_changed_is_refused_with_the_ways_out(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_on_inputs(job, INPUT_FINGERPRINTS)
    with pytest.raises(ValueError) as refusal:
        _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS)
    assert str(refusal.value) == (
        "The current inputs are inconsistent with those of the existing "
        f"x-reader task in {job.root_dir} (x-reader/task.json):\n" + CHANGED_INPUT + ""
        "Run omphjc x with --accept-input to keep its result for the current "
        "inputs, or with --force to replace it."
    )
    assert _task(job, TASK_READER).record == done_record
    forced = _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, force=True)
    assert forced.input_fingerprints == CHANGED_INPUT_FINGERPRINTS
    assert len(forced.runs) == 1


def test_a_done_task_that_reads_other_inputs_is_told_to_use_force(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_on_inputs(job, INPUT_FINGERPRINTS)
    events_only = {EVENTS_INPUT: INPUT_FINGERPRINTS[EVENTS_INPUT]}
    for accept_input in (False, True):
        with pytest.raises(ValueError) as refusal:
            _run_on_inputs(job, events_only, accept_input=accept_input)
        assert str(refusal.value).splitlines()[-1] == (
            "Run omphjc x with --force to replace its result."
        )
    assert _task(job, TASK_READER).record == done_record


def test_an_accepted_input_keeps_a_done_task_without_a_run(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_on_inputs(job, INPUT_FINGERPRINTS)
    accepted_record = _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=True)
    assert _acceptances(accepted_record) == {"events": "v1:changed", "pileup": None}
    assert accepted_record.is_done
    assert (
        accepted_record.parameters,
        accepted_record.input_fingerprints,
        accepted_record.runs,
        accepted_record.result,
    ) == (
        done_record.parameters,
        done_record.input_fingerprints,
        done_record.runs,
        done_record.result,
    )
    assert _task(job, TASK_READER).record == accepted_record
    for input_fingerprints in (CHANGED_INPUT_FINGERPRINTS, INPUT_FINGERPRINTS):
        for accept_input in (False, True):
            kept_record = _run_on_inputs(
                job, input_fingerprints, accept_input=accept_input
            )
            assert kept_record == accepted_record


def test_each_input_is_accepted_on_its_own(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_on_inputs(job, INPUT_FINGERPRINTS)
    other_pileup = {**INPUT_FINGERPRINTS, "pileup": "v1:other"}
    pileup_record = _run_on_inputs(job, other_pileup, accept_input=True)
    assert _acceptances(pileup_record) == {"events": None, "pileup": "v1:other"}
    both_changed = {**other_pileup, "events": "v1:changed"}
    both_record = _run_on_inputs(job, both_changed, accept_input=True)
    assert _acceptances(both_record) == {"events": "v1:changed", "pileup": "v1:other"}
    assert both_record.inputs["pileup"] == pileup_record.inputs["pileup"]
    assert _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS) == both_record
    assert _run_on_inputs(job, other_pileup) == both_record


def test_a_later_acceptance_replaces_the_earlier_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_on_inputs(job, INPUT_FINGERPRINTS)
    _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=True)
    later_input_fingerprints = {**INPUT_FINGERPRINTS, "events": "v1:later"}
    later_record = _run_on_inputs(job, later_input_fingerprints, accept_input=True)
    assert _acceptances(later_record) == {"events": "v1:later", "pileup": None}
    assert _run_on_inputs(job, later_input_fingerprints) == later_record
    with pytest.raises(ValueError, match=CHANGED_INPUT):
        _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS)


def test_other_parameters_are_refused_before_the_inputs_are_compared(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_on_inputs(job, INPUT_FINGERPRINTS)
    for accept_input in (False, True):
        with pytest.raises(ValueError, match="n_events: expected 10") as refusal:
            _run_on_inputs(
                job,
                CHANGED_INPUT_FINGERPRINTS,
                parameters={"n_events": 20},
                accept_input=accept_input,
            )
        assert "fingerprint of events" not in str(refusal.value)
    with pytest.raises(ValueError, match="cannot both be set"):
        _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=True, force=True)
    assert _task(job, TASK_READER).record == done_record


def test_accept_input_changes_nothing_for_a_task_that_is_not_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        _run_on_inputs(job, INPUT_FINGERPRINTS, body=_fail, accept_input=True)
    failed_record = _task(job, TASK_READER).record
    assert failed_record is not None
    assert failed_record.latest_run.status == "failed"
    record = _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=True)
    assert record.is_done and len(record.runs) == 1
    assert record.input_fingerprints == CHANGED_INPUT_FINGERPRINTS
    assert _acceptances(record) == {"events": None, "pileup": None}


def test_a_record_holds_an_accepted_input_only_when_its_latest_run_is_done() -> None:
    accepted = InputRecord("y-events", "v1:original", AcceptedInput("v1:changed", "t"))
    acceptance = "so no input should hold an acceptance, but 'events' holds one"
    with pytest.raises(ValueError, match=acceptance):
        TaskRecord(TASK_READER, {}, {}, (_run("failed"),), inputs={"events": accepted})
    both = "but 'events' and 'pileup' hold one"
    with pytest.raises(ValueError, match=both):
        TaskRecord(
            TASK_READER,
            {},
            {},
            (_run("failed"),),
            inputs={"events": accepted, "pileup": accepted},
        )


def test_a_task_that_lost_an_output_runs_again_only_on_the_inputs_it_ran_on(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_on_inputs(job, INPUT_FINGERPRINTS)
    _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=True)
    (job.task_dir(TASK_READER) / "out.txt").unlink()
    refusal = CHANGED_INPUT + "Run omphjc x with --force to replace its result."
    for accept_input in (False, True):
        with pytest.raises(ValueError, match=re.escape(refusal)):
            _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, accept_input=accept_input)
    rerun = _run_on_inputs(job, INPUT_FINGERPRINTS)
    assert len(rerun.runs) == 2
    assert _acceptances(rerun) == {"events": None, "pileup": None}
    with pytest.raises(ValueError, match=CHANGED_INPUT):
        _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS)
    forced = _run_on_inputs(job, CHANGED_INPUT_FINGERPRINTS, force=True)
    assert forced.input_fingerprints == CHANGED_INPUT_FINGERPRINTS
    assert _acceptances(forced) == {"events": None, "pileup": None}


def test_two_jobs_opened_on_one_directory_keep_the_records_of_both_tasks(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    first = Job(specs["HToBB"], tmp_path, 1)
    second = Job(specs["HToBB"], tmp_path, 1)
    x_record = _run_task(
        first, TASK_X, {}, lambda overwrite, log_path: _make_output(first)
    )
    y_record = _run_task(
        second, TASK_Y, {}, lambda overwrite, log_path: TaskOutcome(RunResult())
    )
    job = Job(specs["HToBB"], tmp_path, 1)
    assert [task.name for task in job.tasks()] == ["x-fake", "y-fake"]
    assert [task.name for task in job.tasks("y")] == ["y-fake"]
    assert _task(job, TASK_X).record == x_record
    assert _task(job, TASK_Y).record == y_record
    assert set(Manifest.read(job.manifest_path).tasks) == {"x-fake", "y-fake"}


def test_the_manifest_lists_every_task_and_is_written_again_when_deleted(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool, log_path: Path) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    x_record = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_Y, {}, failing)
    y_record = _task(job, TASK_Y).record
    assert y_record is not None
    manifest = Manifest(
        job.identity,
        {
            "x-fake": TaskSummary(
                "done", x_record.latest_run.run_id, 1, _task(job, TASK_X).record_path
            ),
            "y-fake": TaskSummary(
                "failed", y_record.latest_run.run_id, 1, _task(job, TASK_Y).record_path
            ),
        },
    )
    assert Manifest.read(job.manifest_path) == manifest

    job.manifest_path.unlink()
    assert (
        _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
        == x_record
    )
    assert not job.manifest_path.exists()
    z_record = _run_task(
        job, TASK_Z, {}, lambda overwrite, log_path: TaskOutcome(RunResult())
    )
    entry = TaskSummary(
        "done", z_record.latest_run.run_id, 1, _task(job, TASK_Z).record_path
    )
    assert Manifest.read(job.manifest_path) == Manifest(
        job.identity, {**manifest.tasks, "z-fake": entry}
    )


def test_a_record_of_another_identity_with_the_same_name_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    tagged = TaskIdentity("x", "fake", "tuneA")
    record = _run_task(job, tagged, {}, lambda overwrite, log_path: _make_output(job))
    assert _task(job, tagged).name == "x-fake-tuneA"
    same_name = TaskIdentity("x", "fake-tuneA")
    assert same_name.name == tagged.name
    another_task = (
        "task.json is the record of another task named x-fake-tuneA: expected "
        "stage 'x', tool 'fake-tuneA' and no tag, got stage 'x', tool 'fake' and "
        "tag 'tuneA'. Give one of the two tasks another tag."
    )
    with pytest.raises(ValueError, match=re.escape(another_task)):
        _ = _task(job, same_name).record
    with pytest.raises(ValueError, match="is the record of"):
        _run_task(job, same_name, {}, lambda overwrite, log_path: _make_output(job))
    assert _task(job, tagged).record == record


def test_a_record_in_a_directory_of_another_name_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    job.task_dir(TASK_X).rename(job.root_dir / "renamed")
    renamed = "its directory is named renamed.\nName the directory x-fake again"
    with pytest.raises(TaskRecordError, match=renamed):
        job.tasks()


def test_a_record_without_an_identity_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    record_path = _task(job, TASK_X).record_path
    written = json.loads(record_path.read_text())
    del written["identity"]
    record_path.write_text(json.dumps(written))
    with pytest.raises(ValueError, match="invalid content"):
        _ = _task(job, TASK_X).record


def test_a_task_is_found_by_the_record_in_its_own_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    record_path = _task(job, TASK_X).record_path
    deeper_dir = job.task_dir(TASK_X) / "deeper"
    deeper_dir.mkdir()
    shutil.copy(record_path, deeper_dir / "task.json")
    shutil.copy(record_path, job.root_dir / "task.json")
    (job.root_dir / "empty").mkdir()
    assert [task.name for task in job.tasks()] == ["x-fake"]


def test_a_task_record_that_cannot_be_read_stops_every_task_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, body)
    record_path = _task(job, TASK_X).record_path
    record_path.write_text("{")
    unreadable = re.escape(f"{record_path} is not valid JSON")
    with pytest.raises(ValueError, match="Restore the file, or remove it"):
        _ = _task(job, TASK_X).record
    with pytest.raises(ValueError, match=unreadable):
        _ = _task(job, TASK_X).record
    with pytest.raises(ValueError, match=unreadable):
        _run_task(job, TASK_X, {}, body, force=True)
    with pytest.raises(ValueError, match=unreadable):
        _run_task(job, TASK_Y, {}, body)
    assert calls == [False]
    assert job.set_aside_folders() == []


def test_the_first_task_writes_the_identity_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    assert json.loads(job.identity_path.read_text()) == {
        "schema": 1,
        "process": "HToBB",
        "job_id": 1,
        "seed": 10000001,
        "omphjc_version": __version__,
    }


def test_a_later_task_keeps_the_identity_file(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.root_dir.mkdir(parents=True)
    created = JobIdentity(
        process="HToBB", job_id=1, seed=10000001, omphjc_version="0.0.1"
    )
    created.create(job.identity_path)
    later = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(
        later, TASK_X, {}, lambda overwrite, log_path: _make_output(later)
    )
    assert record.is_done
    assert JobIdentity.read(job.identity_path).omphjc_version == "0.0.1"


def test_a_directory_of_another_job_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    shifted = Job(replace(specs["HToBB"], seed_offset=20_000_000), tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    refusal = (
        "The current configuration is inconsistent with that of the existing"
        " job in .*job_1 \\(job.json\\):"
        "\n  seed: expected 10000001, got 20000001"
        "\nRerun with the configuration the job was created with, or choose"
        " another output directory.$"
    )
    calls = []
    with pytest.raises(ValueError, match=refusal):
        _run_task(shifted, TASK_Y, {}, calls.append, force=True)
    assert calls == []
    with pytest.raises(ValueError, match=refusal):
        Job(shifted.spec, tmp_path, 1)
    JobIdentity(process="HToGG", job_id=1, seed=5).write(job.identity_path)
    with pytest.raises(
        ValueError,
        match=(
            "\n  process: expected HToGG, got HToBB"
            "\n  seed: expected 5, got 10000001\nRerun"
        ),
    ):
        Job(specs["HToBB"], tmp_path, 1)


def test_two_jobs_are_equal_when_they_are_one_process_in_one_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job == Job(specs["HToBB"], tmp_path, 1)
    assert hash(job) == hash(Job(specs["HToBB"], tmp_path, 1))
    assert job != Job(specs["HToBB"], tmp_path, 2)
    assert job != Job(specs["HToBB"], tmp_path / "elsewhere", 1)
    assert job != Job(replace(specs["HToBB"], seed_offset=20_000_000), tmp_path, 1)
    assert repr(job) == f"Job('HToBB', 1, root_dir={str(job.root_dir)!r})"
    assert FakeX(job) == FakeX(Job(specs["HToBB"], tmp_path, 1))
    assert FakeX(job) != FakeX(Job(specs["HToBB"], tmp_path, 2))
    assert FakeX(job) != FakeX(job, tag="tuneA")


def test_identities_differ_by_process_job_number_and_seed() -> None:
    identity = JobIdentity(process="HToBB", job_id=1, seed=10000001)
    same = JobIdentity(process="HToBB", job_id=1, seed=10000001, omphjc_version="0.0.1")
    assert identity.differences(same) == []
    other = JobIdentity(process="HToBB", job_id=2, seed=10000002)
    assert identity.differences(other) == [
        Difference("job_id", expected="2", actual="1"),
        Difference("seed", expected="10000002", actual="10000001"),
    ]


def test_a_job_directory_removed_during_a_task_is_not_recreated(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)

    def remove_then_finish(overwrite: bool, log_path: Path) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        return _make_output(job)

    with pytest.raises(
        FileNotFoundError, match="job.json was removed while the x-fake task ran"
    ):
        _run_task(job, TASK_X, {}, remove_then_finish)
    assert not job.identity_path.exists()
    assert not job.manifest_path.exists()

    def remove_then_fail(overwrite: bool, log_path: Path) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        raise RuntimeError("the program stopped")

    with pytest.raises(FileNotFoundError, match="is not recorded") as failure:
        _run_task(Job(specs["HToBB"], tmp_path, 1), TASK_X, {}, remove_then_fail)
    assert isinstance(failure.value.__context__, RuntimeError)
    assert not job.root_dir.exists()


def test_an_identity_file_that_cannot_be_read_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.root_dir.mkdir(parents=True)
    job.identity_path.write_text('{"schema": 99}')
    with pytest.raises(ValueError, match="schema 99; .* reads schema 1"):
        Job(specs["HToBB"], tmp_path, 1)
    job.identity_path.write_text('{"schema": 1, "process": "HToBB"}')
    with pytest.raises(JobFileError, match="job.json has invalid content") as refusal:
        Job(specs["HToBB"], tmp_path, 1)
    assert refusal.value.remedy is None
    job.identity_path.write_text("not json")
    with pytest.raises(ValueError, match="job.json is not valid JSON"):
        _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))


def test_generate_records_what_madgraph_made(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["TTBar"], tmp_path, 3)
    task = MadGraphGeneration(job, n_events=10, program_path=mg5_path)
    record = task.run()
    assert task.record == record
    assert record.is_done
    assert record.parameters == {"n_events": 10, "seed": 3}
    metadata = record.result.metadata
    assert metadata["madgraph_version"] == "3.5.7"
    assert metadata["cross_section_pb"] == pytest.approx(1.052824254921272)
    assert metadata["cross_section_error_pb"] == pytest.approx(2.3983749989e-3)
    assert record.latest_run.usage["wall_seconds"] > 0
    assert (
        record.latest_run.usage["cpu_seconds"] >= 0
        and record.latest_run.usage["peak_memory_mib"] > 0
    )
    lhe_path = job.root_dir / (
        "generate-madgraph/TTBar/Events/run_01_decayed_1/unweighted_events.lhe.gz"
    )
    assert lhe_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventFileRecord(
            lhe_path,
            n_bytes=lhe_path.stat().st_size,
            fingerprint=LHEFile.read(lhe_path).fingerprint(),
            format=EventFormat.LHE,
            n_events=10000,
        )
    }
    assert task.log_path(record.latest_run.run_id).is_file()
    card = job.root_dir / "generate-madgraph" / "cards" / "proc_card_mg5.dat"
    assert card.is_file()
    assert record.cards["proc_card"] == ProcCard.record_file(card)
    assert set(record.cards) == {"proc_card", "madspin_card"}
    assert "cards" not in metadata
    assert (card.parent / "madspin_card.dat").is_file()
    launch = (
        (job.root_dir / "generate-madgraph" / "launch.mg5").read_text().splitlines()
    )
    assert "set iseed 3" in launch and "set python_seed 3" in launch


@pytest.mark.parametrize("n_cores", [2, None])
def test_generate_records_the_cores_as_metadata(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    n_cores: int | None,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = MadGraphGeneration(
        job, n_events=10, n_cores=n_cores, program_path=mg5_path
    ).run()
    expected = available_cores() if n_cores is None else n_cores
    assert record.result.metadata["n_cores"] == expected
    rerun = MadGraphGeneration(
        job, n_events=10, n_cores=expected + 1, program_path=mg5_path
    ).run()
    assert rerun == record


def test_generate_keeps_a_finished_run_unless_forced(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    first = MadGraphGeneration(
        Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
    ).run()
    logs_dir = tmp_path / "HToBB" / "job_1" / "generate-madgraph" / "logs"
    first_log = f"{first.latest_run.run_id}.log"
    assert [path.name for path in logs_dir.iterdir()] == [first_log]
    assert (
        MadGraphGeneration(
            Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
        ).run()
        == first
    )
    assert [path.name for path in logs_dir.iterdir()] == [first_log]
    with pytest.raises(ValueError, match="n_events: expected 10, got 20"):
        MadGraphGeneration(
            Job(specs["HToBB"], tmp_path, 1), n_events=20, program_path=mg5_path
        ).run()
    shifted = replace(specs["HToBB"], seed_offset=20_000_000)
    with pytest.raises(ValueError, match="seed: expected 10000001, got 20000001"):
        MadGraphGeneration(
            Job(shifted, tmp_path, 1), n_events=10, program_path=mg5_path
        ).run()
    again = MadGraphGeneration(
        Job(specs["HToBB"], tmp_path, 1), n_events=20, program_path=mg5_path
    ).run(force=True)
    assert again.is_done
    assert again.parameters == {"n_events": 20, "seed": 10000001}
    assert len(again.runs) == 1
    assert [path.name for path in logs_dir.iterdir()] == [
        f"{again.latest_run.run_id}.log"
    ]


def test_a_failed_madgraph_run_is_recorded_and_retried(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", "launch")
    with pytest.raises(ProgramError):
        MadGraphGeneration(
            Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
        ).run()
    (task,) = Job(specs["HToBB"], tmp_path, 1).tasks()
    record = task.record
    assert record is not None
    assert (
        record.latest_run.status == "failed" and record.latest_run.finished is not None
    )
    assert (
        record.latest_run.error is not None and "launch.mg5" in record.latest_run.error
    )
    monkeypatch.delenv("FAKE_MG5_FAIL")
    done = MadGraphGeneration(
        Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
    ).run()
    assert done.is_done
    failed_run, done_run = done.runs
    assert failed_run.run_id != done_run.run_id
    logs_dir = tmp_path / "HToBB" / "job_1" / "generate-madgraph" / "logs"
    for run in done.runs:
        assert (logs_dir / f"{run.run_id}.log").is_file()


def test_shower_needs_a_finished_madgraph_stage(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc generate first"):
        PythiaShower(
            Job(specs["HToBB"], tmp_path, 1), program_path=delphes_pythia8_path
        ).run()
    assert not (tmp_path / "HToBB").exists()


def test_shower_records_what_it_made_and_keeps_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    tmp_path: Path,
) -> None:
    generated = MadGraphGeneration(
        Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
    ).run()
    job = Job(specs["HToBB"], tmp_path, 1)
    record = PythiaShower(job, program_path=delphes_pythia8_path).run()
    assert PythiaShower(job).record == record
    assert record.is_done
    assert record.parameters == {
        "n_events": 10000,
        "seed": 10000001,
        "overrides": {},
    }
    assert record.inputs == {
        EVENTS_INPUT: InputRecord(
            "generate-madgraph", generated.result.outputs[EVENTS_OUTPUT].fingerprint
        )
    }
    metadata = record.result.metadata
    assert metadata["pythia_version"] == "8.318"
    assert metadata["events_read"] == 1
    assert "matching_efficiency" not in metadata
    assert record.cards == {
        "command_file": PythiaCmnd.record_file(
            job.root_dir / "shower-pythia" / "pythia.cmnd"
        ),
        "particles_card": ParticlesCard.record_file(
            job.root_dir / "shower-pythia" / "particles_card.tcl"
        ),
    }
    assert "settings" not in metadata
    root_path = job.root_dir / "shower-pythia" / "particles.root"
    assert root_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventFileRecord(
            root_path,
            n_bytes=root_path.stat().st_size,
            fingerprint=DelphesROOTFile.read(root_path).fingerprint(),
            format=EventFormat.DELPHES_ROOT,
            n_events=1,
        )
    }
    assert PythiaShower(job).log_path(record.latest_run.run_id).is_file()
    cmnd = (job.root_dir / "shower-pythia" / "pythia.cmnd").read_text()
    assert "Random:seed = 10000001" in cmnd and "Main:numberOfEvents = 10000" in cmnd
    card = (job.root_dir / "shower-pythia" / "particles_card.tcl").read_text()
    assert "TreeWriter" in card and "RandomSeed" not in card

    kept = PythiaShower(
        Job(specs["HToBB"], tmp_path, 1), program_path=delphes_pythia8_path
    ).run()
    assert kept == record
    overrides = {"Main:timesAllowErrors": 5}
    added = re.escape("unexpected overrides.Main:timesAllowErrors: 5")
    with pytest.raises(ValueError, match=added):
        PythiaShower(
            Job(specs["HToBB"], tmp_path, 1),
            overrides=overrides,
            program_path=delphes_pythia8_path,
        ).run()
    forced = PythiaShower(
        Job(specs["HToBB"], tmp_path, 1),
        overrides=overrides,
        program_path=delphes_pythia8_path,
    ).run(force=True)
    assert forced.parameters["overrides"] == overrides
    assert (
        "Main:timesAllowErrors = 5"
        in (job.root_dir / "shower-pythia" / "pythia.cmnd").read_text()
    )


def test_shower_records_the_matching_efficiency_of_a_matched_process(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    tmp_path: Path,
) -> None:
    MadGraphGeneration(
        Job(specs["ZJetsToNuNu"], tmp_path, 2), n_events=10, program_path=mg5_path
    ).run()
    record = PythiaShower(
        Job(specs["ZJetsToNuNu"], tmp_path, 2), program_path=delphes_pythia8_path
    ).run()
    assert record.result.metadata["matching_efficiency"] == 1.0
    cmnd = (
        tmp_path / "ZJetsToNuNu" / "job_2" / "shower-pythia" / "pythia.cmnd"
    ).read_text()
    assert "JetMatching:merge = on" in cmnd


def test_sigterm_becomes_an_exception_inside_the_block() -> None:
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(TerminationError, match="signal"), exception_on_termination():
        os.kill(os.getpid(), signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) == before


def test_a_stage_records_the_folder_its_run_set_aside(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        aside = job.task_dir(TASK_X) / "omphjc-set-aside" / "20260101T000000Z-abc"
        aside.mkdir(parents=True)
        return replace(_make_output(job), set_aside_dir=aside)

    record = _run_task(job, TASK_X, {"n_events": 10}, body)
    assert record.latest_run.set_aside == "x-fake/omphjc-set-aside/20260101T000000Z-abc"
    assert _task(job, TASK_X).record == record


def test_a_job_lists_and_clears_what_its_stages_set_aside(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omphjc.workspace as workspace

    with monkeypatch.context() as killed_before_sealing:
        killed_before_sealing.setattr(workspace, "seal", lambda *_: None)
        MadGraphGeneration(
            Job(specs["HToBB"], tmp_path, 1), n_events=10, program_path=mg5_path
        ).run()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.set_aside_folders() == []
    record = MadGraphGeneration(job, n_events=10, program_path=mg5_path).run(force=True)
    assert record.latest_run.set_aside is not None
    assert record.latest_run.set_aside.startswith("generate-madgraph/omphjc-set-aside/")
    folders = job.set_aside_folders()
    assert [job.relative_path(folder.path) for folder in folders] == [
        record.latest_run.set_aside
    ]
    assert folders[0].size() > 0
    assert job.clear_set_aside_folders() == folders
    assert job.set_aside_folders() == []
    (task,) = job.tasks()
    assert not (task.directory / "omphjc-set-aside").exists()
    assert task.status is TaskStatus.DONE


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeSimulation(Task):
    """A simulation task for tests: it writes one small file and no events."""

    stage: ClassVar[Stage] = SimulateStage()
    tool: ClassVar[str] = "fake-simulator"
    inputs: ClassVar[tuple[TaskInput, ...]] = (TaskInput(EVENTS_INPUT, FakeShower),)

    def parameters(self, input_files: Mapping[str, FileRecord]) -> dict[str, Any]:
        return {"seed": self.job.seed}

    def execute(
        self,
        input_files: Mapping[str, FileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        events = input_files[EVENTS_INPUT]
        self.directory.mkdir(parents=True, exist_ok=True)
        output_path = self.directory / "simulated.txt"
        output_path.write_text(f"{events.path.name} {self.job.seed}")
        log_path.write_text("simulated")
        output = FileRecord(output_path, output_path.stat().st_size, None)
        return TaskOutcome(
            RunResult(
                outputs={"out": output},
                metadata={"input_format": events.file_format},
            )
        )


def _record_showered_events(
    job: Job, tag: str | None = None, tool: str = "fake"
) -> EventFileRecord:
    """Record a done task of the shower stage of `job`, in the format of its class."""
    identity = TaskIdentity("shower", tool, tag)
    (output,) = TASK_REGISTRY.get(identity).outputs
    events_path = job.task_dir(identity) / "events.dat"

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("events")
        fingerprint = f"{output.file_format}-v1:abc"
        events = EventFileRecord(
            events_path, 6, fingerprint, EventFormat.DELPHES_ROOT, 1
        )
        return TaskOutcome(RunResult(outputs={EVENTS_OUTPUT: events}))

    record = _run_task(job, identity, {}, body)
    assert record.events is not None
    return record.events


def test_a_task_reads_the_only_task_of_the_class_of_its_input(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    events = _record_showered_events(job)
    task = FakeSimulation(job)
    assert task.upstream == {EVENTS_INPUT: "shower-fake"}
    upstream_identities = {
        name: upstream_task.identity
        for name, upstream_task in task.upstream_tasks().items()
    }
    assert upstream_identities == {EVENTS_INPUT: TASK_FAKE_SHOWER}
    assert task.input_files() == {EVENTS_INPUT: events}
    record = task.run()
    assert record.is_done
    assert record.parameters == {"seed": job.seed}
    assert record.inputs == {
        EVENTS_INPUT: InputRecord("shower-fake", events.fingerprint)
    }
    assert record.metadata == {"input_format": "delphes_root"}
    assert record.identity == TaskIdentity("simulate", "fake-simulator")
    assert task.directory == job.root_dir / "simulate-fake-simulator"
    assert (task.directory / "simulated.txt").read_text() == f"events.dat {job.seed}"
    assert task.latest_log.read_text() == "simulated"
    assert FakeSimulation(job).run() == record


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeLHEShower(FakeShower):
    """A shower task whose events are LHE files, not the files of its class."""

    tool: ClassVar[str] = "fake-lhe"
    outputs: ClassVar[tuple[TaskOutput, ...]] = (
        TaskOutput(EVENTS_OUTPUT, LHEFile.format_name),
    )


def test_a_shower_reads_the_event_count_of_its_input_from_its_record(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    shower = PythiaShower(job, upstream={EVENTS_INPUT: "generate-madgraph"})
    lhe_path = tmp_path / "events.lhe"
    events = EventFileRecord(lhe_path, 6, "lhe-v1:a", EventFormat.LHE, 25)
    assert shower.parameters({EVENTS_INPUT: events})["n_events"] == 25
    refusal = (
        f"shower-pythia reads the number of events in {lhe_path} from its record, "
        "but the record holds none. Run the task that made the file again."
    )
    with pytest.raises(ValueError, match=re.escape(refusal)):
        shower.parameters({EVENTS_INPUT: FileRecord(lhe_path, 6, "lhe-v1:a")})


def test_a_task_refuses_events_in_a_format_it_does_not_read(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _record_showered_events(job, tool="fake-lhe")
    refusal = (
        "simulate-fake-simulator reads the events output of the shower-fake-lhe "
        f"task of {job.root_dir} as a delphes_root file, but that task made a lhe "
        "file"
    )
    with pytest.raises(ValueError, match=re.escape(refusal)):
        FakeSimulation(job).run()
    assert job.tasks("simulate") == []


def test_a_task_reads_the_task_its_upstream_names_when_its_class_has_several(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    reads = "simulate-fake-simulator reads its events input from a FakeShower task"
    no_task = f"{reads}, and {job.root_dir} has none; run omphjc shower first"
    with pytest.raises(ValueError, match=re.escape(no_task)):
        FakeSimulation(job)
    assert not job.root_dir.exists()
    _record_showered_events(job)
    tuned_events = _record_showered_events(job, tag="tuneA")
    several = (
        f"{reads}, and {job.root_dir} has several (shower-fake, shower-fake-tuneA). "
        "Name the one to read in upstream, such as upstream={'events': 'shower-fake'}."
    )
    with pytest.raises(ValueError, match=re.escape(several)):
        FakeSimulation(job)
    named = FakeSimulation(job, upstream={EVENTS_INPUT: "shower-fake-tuneA"})
    record = named.run()
    assert record.inputs == {
        EVENTS_INPUT: InputRecord("shower-fake-tuneA", tuned_events.fingerprint)
    }
    assert job.tasks("simulate") == [named]


def test_an_input_names_an_output_that_its_upstream_class_declares() -> None:
    with pytest.raises(ValueError) as refusal:
        TaskInput(EVENTS_INPUT, FakeShower, upstream_output="summary")
    assert str(refusal.value) == (
        "The events input reads the summary output of a FakeShower task, but "
        "FakeShower declares the outputs ['events']. Name one of them in "
        "upstream_output, or declare the output on the class."
    )
    with pytest.raises(ValueError, match="FakeY declares no output. Declare"):
        TaskInput(EVENTS_INPUT, FakeY)
    reads_lhe = TaskInput(EVENTS_INPUT, GenerationTask)  # type: ignore[type-abstract]
    assert reads_lhe.file_format == LHEFile.format_name


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class FakeGenerator(FakeTask):
    """A task of stage ``z`` that declares LHE events as its output."""

    stage: ClassVar[Stage] = ZStage()
    tool: ClassVar[str] = "fake-generator"
    outputs: ClassVar[tuple[TaskOutput, ...]] = (
        TaskOutput(EVENTS_OUTPUT, LHEFile.format_name),
    )


def test_a_run_must_make_the_outputs_that_its_class_declares(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    without_events = "shower-fake declares the output events, but its run made none"
    with pytest.raises(ValueError, match=without_events):
        _run_task(job, TASK_FAKE_SHOWER, {}, lambda *_: _make_output(job))
    assert _task(job, TASK_FAKE_SHOWER).record.latest_run.status == "failed"
    generator = TaskIdentity("z", "fake-generator")
    events_path = job.task_dir(generator) / "events.root"

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("events")
        fingerprint = "delphes_root-v1:a"
        events = EventFileRecord(
            events_path, 6, fingerprint, EventFormat.DELPHES_ROOT, 1
        )
        return TaskOutcome(RunResult(outputs={EVENTS_OUTPUT: events}))

    other_format = (
        "z-fake-generator declares the output events as a lhe file, but its run "
        "made a delphes_root file"
    )
    with pytest.raises(ValueError, match=other_format):
        _run_task(job, generator, {}, body)


def test_a_task_refuses_an_upstream_that_does_not_fit_its_inputs(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _record_showered_events(job)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    other_class = FakeSimulation(job, upstream={EVENTS_INPUT: "x-fake"})
    with pytest.raises(ValueError) as refusal:
        other_class.run()
    assert str(refusal.value) == (
        "simulate-fake-simulator reads its events input from a FakeShower task, but "
        "its upstream names x-fake, a FakeX task. Name a FakeShower task instead."
    )
    missing = FakeSimulation(job, upstream={EVENTS_INPUT: "shower-other"})
    with pytest.raises(
        ValueError, match=f"{job.root_dir} has no task named shower-other"
    ):
        missing.run()
    with pytest.raises(ValueError) as refusal:
        FakeSimulation(job, upstream={"pileup": "shower-fake"})
    assert str(refusal.value) == (
        "The simulate-fake-simulator task reads the inputs ['events'], but its "
        "upstream names a task for ['pileup']. Leave those out of upstream."
    )
    with pytest.raises(ValueError, match="The x-fake task reads no input"):
        FakeX(job, upstream={EVENTS_INPUT: "shower-fake"})
    assert job.tasks("simulate") == []


def test_simulate_needs_a_finished_shower_stage(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc shower first"):
        job = Job(specs["HToBB"], tmp_path, 1)
        DelphesSimulation(job, program_path=delphes_root_path).run()
    assert not (tmp_path / "HToBB" / "job_1" / "simulate-delphes").exists()


def _run_all(
    job: Job, mg5_path: Path, delphes_pythia8_path: Path, delphes_root_path: Path
) -> tuple[TaskRecord, TaskRecord, TaskRecord]:
    return (
        MadGraphGeneration(job, n_events=10, program_path=mg5_path).run(),
        PythiaShower(job, program_path=delphes_pythia8_path).run(),
        DelphesSimulation(job, program_path=delphes_root_path).run(),
    )


def test_a_stage_run_again_with_the_same_events_keeps_the_stages_after_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _, showered, simulated = _run_all(
        job, mg5_path, delphes_pythia8_path, delphes_root_path
    )
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run(force=True)
    assert PythiaShower(job, program_path=delphes_pythia8_path).run() == showered
    PythiaShower(job, program_path=delphes_pythia8_path).run(force=True)
    assert DelphesSimulation(job, program_path=delphes_root_path).run() == simulated


def test_a_stage_whose_input_events_changed_is_refused_unless_forced(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    generated, showered, _ = _run_all(
        job, mg5_path, delphes_pythia8_path, delphes_root_path
    )
    monkeypatch.setenv("FAKE_MG5_EVENTS", "2")
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run(force=True)
    lhe_fingerprint = job.tasks("generate")[0].events.fingerprint
    assert lhe_fingerprint != generated.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(ValueError, match="fingerprint of events: expected lhe-v1:"):
        PythiaShower(job, program_path=delphes_pythia8_path).run()
    forced = PythiaShower(job, program_path=delphes_pythia8_path).run(force=True)
    assert forced.input_fingerprints == {EVENTS_INPUT: lhe_fingerprint}
    root_fingerprint = forced.result.outputs[EVENTS_OUTPUT].fingerprint
    assert root_fingerprint != showered.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(
        ValueError, match="fingerprint of events: expected delphes_root-v1:"
    ):
        DelphesSimulation(job, program_path=delphes_root_path).run()
    forced = DelphesSimulation(job, program_path=delphes_root_path).run(force=True)
    assert forced.input_fingerprints == {EVENTS_INPUT: root_fingerprint}


def test_an_accepted_input_keeps_a_stage_and_the_stages_after_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _, showered, simulated = _run_all(
        job, mg5_path, delphes_pythia8_path, delphes_root_path
    )
    monkeypatch.setenv("FAKE_MG5_EVENTS", "2")
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run(force=True)
    lhe_fingerprint = job.tasks("generate")[0].events.fingerprint
    accepted_record = PythiaShower(job, program_path=delphes_pythia8_path).run(
        accept_input=True
    )
    accepted = accepted_record.inputs[EVENTS_INPUT].accepted
    assert accepted is not None and accepted.fingerprint == lhe_fingerprint
    assert accepted_record.parameters == showered.parameters
    assert accepted_record.input_fingerprints == showered.input_fingerprints
    assert accepted_record.runs == showered.runs
    assert PythiaShower(job, program_path=delphes_pythia8_path).run() == accepted_record
    assert DelphesSimulation(job, program_path=delphes_root_path).run() == simulated
    assert (
        DelphesSimulation(job, program_path=delphes_root_path).run(accept_input=True)
        == simulated
    )
    with pytest.raises(ValueError, match="cannot both be set"):
        PythiaShower(job).run(force=True, accept_input=True)
    with pytest.raises(ValueError, match="cannot both be set"):
        DelphesSimulation(job).run(accept_input=True, force=True)


def test_a_kept_stage_reads_no_event_file(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done = _run_all(job, mg5_path, delphes_pythia8_path, delphes_root_path)
    for task in job.tasks():
        event_path = task.events.path
        event_path.write_bytes(bytes(event_path.stat().st_size))
    job = Job(specs["HToBB"], tmp_path, 1)
    assert _run_all(job, mg5_path, delphes_pythia8_path, delphes_root_path) == done


def test_an_event_file_of_another_size_is_refused_by_its_stage_and_the_next(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run()
    PythiaShower(job, program_path=delphes_pythia8_path).run()
    root_path = PythiaShower(job).events.path
    recorded = root_path.stat().st_size
    root_path.write_bytes(root_path.read_bytes()[: recorded // 2])
    refused = re.escape(
        f"{root_path} holds {recorded // 2} bytes, not the {recorded} the "
        "shower-pythia task recorded; run omphjc shower with --force to "
        "regenerate the file"
    )
    with pytest.raises(ValueError, match=refused):
        PythiaShower(job, program_path=delphes_pythia8_path).run()
    with pytest.raises(ValueError, match=refused):
        DelphesSimulation(job, program_path=delphes_root_path).run()
    PythiaShower(job, program_path=delphes_pythia8_path).run(force=True)
    assert DelphesSimulation(job, program_path=delphes_root_path).run().is_done


def test_simulate_records_what_it_made_and_keeps_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run()
    showered = PythiaShower(job, program_path=delphes_pythia8_path).run()
    record = DelphesSimulation(job, program_path=delphes_root_path).run()
    assert record.is_done
    assert record.parameters["seed"] == job.seed
    assert record.inputs == {
        EVENTS_INPUT: InputRecord(
            "shower-pythia", showered.result.outputs[EVENTS_OUTPUT].fingerprint
        )
    }
    assert len(record.parameters["card"]) == 64
    card_path = job.root_dir / "simulate-delphes" / "delphes_card.tcl"
    assert record.cards == {"detector_card": DetectorCard.record_file(card_path)}
    card_classes = SimulationWorkspace.card_classes
    card_names = {card_class.card_name for card_class in card_classes}
    assert set(record.cards) == card_names
    assert record.metadata == {}
    root_path = job.root_dir / "simulate-delphes" / "delphes.root"
    assert root_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventFileRecord(
            root_path,
            n_bytes=root_path.stat().st_size,
            fingerprint=DelphesROOTFile.read(root_path).fingerprint(),
            format=EventFormat.DELPHES_ROOT,
            n_events=1,
        )
    }
    card = (job.root_dir / "simulate-delphes" / "delphes_card.tcl").read_text()
    assert card.endswith("\nset RandomSeed 10000001\n")
    log = DelphesSimulation(job).log_path(record.latest_run.run_id).read_text()
    assert f"** Reading {job.root_dir / 'shower-pythia' / 'particles.root'}" in log

    reopened_job = Job(specs["HToBB"], tmp_path, 1)
    assert (
        DelphesSimulation(reopened_job, program_path=delphes_root_path).run() == record
    )
    other = tmp_path / "other.tcl"
    other.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    with pytest.raises(ValueError, match="card: expected "):
        DelphesSimulation(
            job, program_path=delphes_root_path, detector_card_path=other
        ).run()
    forced = DelphesSimulation(
        job, program_path=delphes_root_path, detector_card_path=other
    ).run(force=True)
    assert forced.is_done and forced.parameters["card"] != record.parameters["card"]
    assert (
        (job.root_dir / "simulate-delphes" / "delphes_card.tcl")
        .read_text()
        .startswith(other.read_text())
    )


# A detector card may leave out branches of the generator record, which the
# count does not read.
@pytest.mark.parametrize("omit", [(), ("Particle.Charge",)])
def test_simulate_counts_the_events_of_its_output(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
    omit: tuple[str, ...],
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    MadGraphGeneration(job, n_events=10, program_path=mg5_path).run()
    PythiaShower(job, program_path=delphes_pythia8_path).run()
    showered = PythiaShower(job).events
    # The fake DelphesROOT copies its input, so the simulated file holds three
    # events while the shower stage recorded one.
    pids = ak.Array([[2212, 211], [2212], [211, 211, 22]])
    write_delphes_file(showered.path, {"PID": pids}, omit=omit)
    # The shower stage is recorded with the size of the file put in its place.
    record = PythiaShower(job).record
    assert record is not None
    record.result.outputs[EVENTS_OUTPUT] = replace(
        showered, n_bytes=showered.path.stat().st_size
    )
    record.write(PythiaShower(job).record_path, root_dir=job.root_dir)
    DelphesSimulation(job, program_path=delphes_root_path).run()
    assert showered.n_events == 1
    assert DelphesSimulation(job).events.n_events == 3


def test_a_forced_rerun_of_each_program_leaves_the_record_of_its_task(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    # Made before any of them ran, so the tasks they read are named.
    tasks: list[Task] = [
        MadGraphGeneration(job, n_events=10, program_path=mg5_path),
        PythiaShower(
            job,
            upstream={EVENTS_INPUT: "generate-madgraph"},
            program_path=delphes_pythia8_path,
        ),
        DelphesSimulation(
            job,
            upstream={EVENTS_INPUT: "shower-pythia"},
            program_path=delphes_root_path,
        ),
    ]
    for task in tasks:
        task.run()
        record = task.run(force=True)
        assert record.latest_run.set_aside is None
        assert task.record == record
        stamp = read_stamp(task.directory)
        assert stamp is not None and "task.json" not in stamp.artifacts
