import hashlib
import json
import os
import re
import shutil
import signal
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import awkward as ak
import pytest
from delphes_records import write_delphes_file

from omphjc import __version__
from omphjc.comparison import Difference
from omphjc.events import EventFormat
from omphjc.events.delphes_root import DelphesROOTFile
from omphjc.jobs import (
    EVENTS_OUTPUT,
    AcceptedInput,
    EventOutput,
    GenerateStage,
    Job,
    JobIdentity,
    Manifest,
    ReplacedRunError,
    ShowerStage,
    SimulateStage,
    Stage,
    Task,
    TaskCard,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskResult,
    TaskRun,
    TaskStatus,
    TaskSummary,
    TerminationError,
    exception_on_termination,
    generate,
    job_seed,
    read_cards,
    shower,
    simulate,
)
from omphjc.processes import ProcessSpec, get_process
from omphjc.programs import available_cores
from omphjc.stamps import COMPACT_UTC_FORMAT, read_stamp
from omphjc.tools.madgraph.driver import MadGraphError
from omphjc.tools.madgraph.lhe_file import LHEFile
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT

RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


@dataclass(frozen=True)
class FakeStage(Stage):
    """A stage for a test, whose task has the name the test gives it."""

    name: ClassVar[str] = "fake"
    fake_task_name: str

    @property
    def task_name(self) -> str:
        return self.fake_task_name

    @property
    def command(self) -> str:
        return f"omphjc {self.fake_task_name}"


STAGE_X = FakeStage("x")
STAGE_Y = FakeStage("y")
STAGE_Z = FakeStage("z")


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


def test_a_stage_names_its_task_its_command_and_the_stage_it_reads() -> None:
    stages = [GenerateStage(), ShowerStage(), SimulateStage()]
    assert [stage.task_name for stage in stages] == ["generate", "shower", "simulate"]
    assert [stage.command for stage in stages] == [
        "omphjc generate",
        "omphjc shower",
        "omphjc simulate",
    ]
    assert [stage.upstream_stage for stage in stages] == [None, *stages[:2]]
    assert STAGE_X.task_name == "x" and STAGE_X != STAGE_Y


def test_a_job_has_a_directory_per_process_and_number(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path / "runs", 7)
    assert job.root_dir == (tmp_path / "runs").resolve() / "HToBB" / "job_7"
    assert job.manifest_path == job.root_dir / "manifest.json"
    assert job.task_dir(GenerateStage()) == job.root_dir / "generate"
    assert job.relative_path(job.root_dir / "generate" / "x.log") == "generate/x.log"
    assert job.seed == 10000007
    assert job.identity_path == job.root_dir / "job.json"
    assert job.identity == JobIdentity(process="HToBB", job_id=7, seed=10000007)
    assert (
        job.task_record_path(GenerateStage()) == job.root_dir / "generate" / "task.json"
    )
    assert job.task_record(GenerateStage()) is None
    assert job.task_names() == []
    assert not job.root_dir.exists()
    with pytest.raises(ValueError, match="job_id"):
        Job(specs["HToBB"], tmp_path, 0)
    with pytest.raises(ValueError, match="filesystem root"):
        Job(specs["HToBB"], Path("/"), 1)


def test_a_task_record_round_trips_through_json(tmp_path: Path) -> None:
    output_path = tmp_path / "x" / "out"
    record = TaskRecord(
        parameters={"events": 10},
        runs=(_run("done", finished="u"),),
        result=TaskResult(
            outputs={
                EVENTS_OUTPUT: EventOutput(
                    output_path,
                    n_bytes=7,
                    format=EventFormat.LHE,
                    n_events=10,
                    fingerprint="lhe-v1:abc",
                ),
                "summary": TaskOutput(tmp_path / "x" / "summary.txt", n_bytes=3),
            },
            cards={"run_card": TaskCard(tmp_path / "x" / "run_card.dat", "abc")},
            metadata={"version": "1.0"},
        ),
    )
    path = tmp_path / "x" / "task.json"
    path.parent.mkdir()
    record.write(path, root_dir=tmp_path)
    written = json.loads(path.read_text())
    assert written["schema"] == 1
    assert written["parameters"] == {"events": 10}
    assert written["runs"] == [
        {
            "run_id": "r1",
            "status": "done",
            "started": "t",
            "host": "h",
            "finished": "u",
            "usage": {},
            "log": None,
            "set_aside": None,
            "error": None,
        }
    ]
    assert written["accepted_input"] is None
    assert written["result"] == {
        "outputs": {
            "events": {
                "path": "x/out",
                "n_bytes": 7,
                "format": "lhe",
                "n_events": 10,
                "fingerprint": "lhe-v1:abc",
            },
            "summary": {"path": "x/summary.txt", "n_bytes": 3},
        },
        "cards": {"run_card": {"path": "x/run_card.dat", "sha256": "abc"}},
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
    with pytest.raises(ValueError, match="task.json is not valid JSON"):
        TaskRecord.read(path, root_dir=tmp_path)


def test_a_task_record_needs_a_run_and_a_result_that_fits_its_status(
    tmp_path: Path,
) -> None:
    done = _run("done")
    with pytest.raises(ValueError, match="the record has no runs"):
        TaskRecord(parameters={}, runs=())
    with pytest.raises(
        ValueError, match="has status 'done' but the record has no result"
    ):
        TaskRecord(parameters={}, runs=(done,))
    failed = _run("failed", error="boom")
    with pytest.raises(
        ValueError, match="has status 'failed' but the record has a result"
    ):
        TaskRecord(parameters={}, runs=(failed,), result=TaskResult())
    with pytest.raises(ValueError, match="unknown run status 'paused'"):
        _run("paused")
    path = tmp_path / "x" / "task.json"
    path.parent.mkdir()
    without_runs = {"schema": 1, "parameters": {}, "result": None}
    path.write_text(json.dumps(without_runs))
    with pytest.raises(ValueError, match="invalid content: the record has no runs"):
        TaskRecord.read(path, root_dir=tmp_path)


def test_a_record_gives_its_outputs_only_when_its_latest_run_is_done(
    tmp_path: Path,
) -> None:
    events = EventOutput(tmp_path / "e.lhe", 7, EventFormat.LHE, 10, "lhe-v1:abc")
    done = TaskRecord(
        parameters={},
        runs=(_run("done"),),
        result=TaskResult(outputs={EVENTS_OUTPUT: events}, metadata={"n": 1}),
    )
    assert done.events == events and done.metadata == {"n": 1}
    assert done.is_done
    no_events = TaskRecord({}, (_run("done"),), TaskResult())
    assert no_events.events is None
    failed = TaskRecord({}, (_run("failed", error="boom"),))
    assert not failed.is_done
    refusal = "The task record has no result: its latest run has status 'failed'"
    with pytest.raises(ValueError, match=re.escape(refusal)):
        _ = failed.outputs


def test_a_task_record_refuses_a_path_outside_its_root_directory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "job" / "x" / "task.json"
    path.parent.mkdir(parents=True)
    record = TaskRecord(
        parameters={},
        runs=(_run("done"),),
        result=TaskResult(
            outputs={"out": TaskOutput(tmp_path / "elsewhere" / "out", n_bytes=0)}
        ),
    )
    with pytest.raises(ValueError, match="elsewhere"):
        record.write(path, root_dir=tmp_path / "job")
    card_elsewhere = TaskCard(tmp_path / "elsewhere" / "card.dat", "abc")
    record = TaskRecord(
        parameters={},
        runs=(_run("done"),),
        result=TaskResult(cards={"card": card_elsewhere}),
    )
    with pytest.raises(ValueError, match="elsewhere"):
        record.write(path, root_dir=tmp_path / "job")
    assert list(path.parent.iterdir()) == []


def test_a_manifest_round_trips_through_json(tmp_path: Path) -> None:
    manifest = Manifest(
        JobIdentity(process="HToBB", job_id=1, seed=10000001),
        {
            "x": TaskSummary("done", "r1", 1, tmp_path / "x" / "task.json"),
            "y": TaskSummary("running", "r2", 2, tmp_path / "y" / "task.json"),
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
                "record_path": "x/task.json",
            },
            "y": {
                "status": "running",
                "latest_run_id": "r2",
                "n_runs": 2,
                "record_path": "y/task.json",
            },
        },
    }
    assert Manifest.read(path) == manifest


def _make_output(job: Job) -> TaskOutcome:
    directory = job.task_dir(STAGE_X)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "out.txt"
    output.write_text("made")
    return TaskOutcome(
        TaskResult(
            outputs={"out": TaskOutput(output, n_bytes=len("made"))},
            metadata={"n": 1},
        )
    )


def test_a_card_is_recorded_with_the_hash_of_its_file(tmp_path: Path) -> None:
    card_path = tmp_path / "run_card.dat"
    card_path.write_text("10 = nevents\n")
    card = TaskCard.from_path(card_path)
    assert card.path == card_path
    assert card.sha256 == hashlib.sha256(b"10 = nevents\n").hexdigest()
    assert read_cards({"run_card": card_path}) == {"run_card": card}
    assert read_cards({}) == {}


def test_a_changed_or_deleted_card_leaves_the_task_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    card_path = job.task_dir(STAGE_X) / "card.dat"

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        outcome = _make_output(job)
        card_path.write_text("as run")
        cards = {"card": TaskCard.from_path(card_path)}
        return replace(outcome, result=replace(outcome.result, cards=cards))

    record = job.run_task(STAGE_X, {}, body)
    assert record.cards == {"card": TaskCard.from_path(card_path)}
    card_path.write_text("edited since")
    assert job.task(STAGE_X).status is TaskStatus.DONE
    card_path.unlink()
    assert job.task(STAGE_X).status is TaskStatus.DONE
    assert job.run_task(STAGE_X, {}, body) == record


def test_a_stage_runs_once_and_its_result_is_kept(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_task(STAGE_X, {"events": 10}, body)
    assert calls == [False]
    assert record.is_done and record.latest_run.finished is not None
    assert len(record.runs) == 1
    assert record.parameters == {"events": 10}
    assert record.result == TaskResult(
        outputs={"out": TaskOutput(job.root_dir / "x" / "out.txt", n_bytes=4)},
        metadata={"n": 1},
    )
    assert record.latest_run.log is None
    assert job.task_record(STAGE_X) == record

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task(STAGE_X) == Task("x", TaskStatus.DONE, record=record)
    assert job.run_task(STAGE_X, {"events": 10}, body) == record
    assert calls == [False]


def test_other_parameters_need_force_and_force_replaces(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, {"events": 10}, body)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError) as refusal:
        job.run_task(STAGE_X, {"events": 20}, body)
    assert str(refusal.value) == (
        "The current parameters are inconsistent with those of the existing x "
        f"task in {job.root_dir} (x/task.json):\n"
        "  events: expected 10, got 20\n"
        "Rerun with the parameters the task ran with, or run omphjc x with "
        "--force to replace its result."
    )
    forced = job.run_task(STAGE_X, {"events": 20}, body, force=True)
    assert forced.parameters == {"events": 20}
    assert len(forced.runs) == 1
    assert calls == [False, True]


def test_a_refusal_names_only_the_parameters_that_differ(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    pythia = {"Main:timesAllowErrors": 5, "Tune:pp": 14}
    job.run_task(
        STAGE_X, {"events": 10, "pythia": pythia}, lambda *_: _make_output(job)
    )
    changed = {**pythia, "Main:timesAllowErrors": 7, "Next:numberCount": 0}
    with pytest.raises(ValueError) as refusal:
        job.run_task(
            STAGE_X, {"events": 10, "pythia": changed}, lambda *_: _make_output(job)
        )
    assert str(refusal.value).splitlines()[1:-1] == [
        "  pythia.Main:timesAllowErrors: expected 5, got 7",
        "  unexpected pythia.Next:numberCount: 0",
    ]


def test_a_stage_with_missing_outputs_or_left_running_runs_again(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        outcome = _make_output(job)
        return replace(
            outcome, result=replace(outcome.result, metadata={"n": len(calls)})
        )

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task(STAGE_X) == Task("x", TaskStatus.NOT_DONE)
    record = job.run_task(STAGE_X, {}, body)
    output_path = job.root_dir / "x" / "out.txt"
    output_path.unlink()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task(STAGE_X) == Task(
        "x", TaskStatus.MISSING_OUTPUT, f"{output_path} is missing", record
    )
    rerun = job.run_task(STAGE_X, {}, body)
    assert calls == [False, True]
    assert [run.status for run in rerun.runs] == ["done", "done"]
    assert rerun.metadata == {"n": 2}

    running = TaskRecord({}, (_run("running"),))
    running.write(job.task_record_path(STAGE_X), root_dir=job.root_dir)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task(STAGE_X) == Task("x", TaskStatus.NOT_DONE, record=running)
    after_kill = job.run_task(STAGE_X, {}, body)
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
    not_done = "The x stage of .* has not run to completion; run omphjc x first"
    with pytest.raises(ValueError, match=not_done):
        job.require_done(STAGE_X)
    record = job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    assert job.require_done(STAGE_X) == record
    (job.root_dir / "x" / "out.txt").unlink()
    with pytest.raises(ValueError, match=not_done):
        job.require_done(STAGE_X)


def test_a_stage_whose_output_has_another_size_is_refused_unless_forced(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_task(STAGE_X, {}, body)
    output_path = job.root_dir / "x" / "out.txt"
    output_path.write_text("made and changed")
    job = Job(specs["HToBB"], tmp_path, 1)
    detail = f"{output_path} holds 16 bytes, not the 4 the x stage recorded"
    assert job.task(STAGE_X) == Task("x", TaskStatus.CHANGED, detail, record)
    refused = re.escape(f"{detail}; run omphjc x with --force to regenerate the file")
    with pytest.raises(ValueError, match=refused):
        job.require_done(STAGE_X)
    with pytest.raises(ValueError, match=refused):
        job.run_task(STAGE_X, {}, body)
    assert calls == [False]
    assert job.run_task(STAGE_X, {}, body, force=True).is_done
    assert calls == [False, True]
    assert job.require_done(STAGE_X).result.outputs["out"].n_bytes == 4


def test_an_output_of_another_size_is_reported_before_a_missing_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    first_path = job.task_dir(STAGE_X) / "first.txt"
    second_path = job.task_dir(STAGE_X) / "second.txt"

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        job.task_dir(STAGE_X).mkdir(parents=True, exist_ok=True)
        outputs = {}
        for name, path in (("first", first_path), ("second", second_path)):
            path.write_text("made")
            outputs[name] = TaskOutput(path, n_bytes=len("made"))
        return TaskOutcome(TaskResult(outputs=outputs))

    record = job.run_task(STAGE_X, {}, body)
    first_path.unlink()
    second_path.write_text("made and changed")
    assert job.task(STAGE_X) == Task(
        "x",
        TaskStatus.CHANGED,
        f"{second_path} holds 16 bytes, not the 4 the x stage recorded",
        record,
    )
    with pytest.raises(ValueError, match="with --force to regenerate the file"):
        job.run_task(STAGE_X, {}, body)


def test_require_events_returns_the_events_a_done_stage_made(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="has not run to completion"):
        job.require_events(STAGE_X)
    job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    with pytest.raises(ValueError, match="The x stage of .* made no event file"):
        job.require_events(STAGE_X)

    events = EventOutput(
        job.task_dir(STAGE_X) / "out.txt",
        n_bytes=len("made"),
        format=EventFormat.LHE,
        n_events=3,
        fingerprint="lhe-v1:abc",
    )
    job.run_task(
        STAGE_X,
        {},
        lambda overwrite, run_dir: TaskOutcome(
            TaskResult(outputs={EVENTS_OUTPUT: events})
        ),
        force=True,
    )
    assert Job(specs["HToBB"], tmp_path, 1).require_events(STAGE_X) == events


def test_a_failed_stage_is_recorded_raised_and_replaced_on_retry(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool, run_dir: Path) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_X, {"events": 10}, failing)
    record = job.task_record(STAGE_X)
    assert record is not None
    assert (
        record.latest_run.status == "failed" and record.latest_run.finished is not None
    )
    assert record.parameters == {"events": 10} and record.result is None
    assert record.latest_run.error == "boom"

    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    rerun = job.run_task(STAGE_X, {"events": 10}, body)
    assert [run.status for run in rerun.runs] == ["failed", "done"]
    assert rerun.runs[0].usage == {}
    assert rerun.runs[1].usage["wall_seconds"] >= 0
    assert calls == [True]

    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_Y, {"events": 10}, failing)
    other = job.run_task(STAGE_Y, {"events": 20}, body)
    assert len(other.runs) == 1


def _fail(overwrite: bool, run_dir: Path) -> TaskOutcome:
    raise RuntimeError("boom")


def test_each_run_has_an_id_that_begins_with_its_start_time(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_X, {}, _fail)
    record = job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    first, second = record.runs
    assert first.run_id != second.run_id
    for run in record.runs:
        assert RUN_ID.fullmatch(run.run_id)
        start_time = datetime.fromisoformat(run.started)
        assert run.run_id.startswith(start_time.strftime(COMPACT_UTC_FORMAT))
    assert Manifest.read(job.manifest_path).tasks["x"].latest_run_id == second.run_id


def test_a_run_records_the_host_it_ran_on(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    assert record.latest_run.host == socket.gethostname()


def test_a_run_directory_stays_when_the_task_runs_again(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def write_log_then_stop(overwrite: bool, run_dir: Path) -> TaskOutcome:
        (run_dir / "x.log").write_text("first run")
        raise TerminationError("terminated by signal 15")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(TerminationError):
        job.run_task(STAGE_X, {}, write_log_then_stop)
    run_dirs: list[Path] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        run_dirs.append(run_dir)
        return _make_output(job)

    first, second = job.run_task(STAGE_X, {}, body).runs
    assert run_dirs == [job.run_dir(STAGE_X, second.run_id)]
    assert (job.run_dir(STAGE_X, first.run_id) / "x.log").read_text() == "first run"


def test_a_record_names_the_log_of_a_run_from_its_start(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    logs: list[str | None] = []

    def read_record_then_fail(overwrite: bool, run_dir: Path) -> TaskOutcome:
        record = job.task_record(STAGE_X)
        assert record is not None
        logs.append(record.latest_run.log)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_X, {}, read_record_then_fail, log_name="x.log")
    record = job.task_record(STAGE_X)
    assert record is not None
    failed_run = record.latest_run
    assert failed_run.status == "failed"
    assert logs == [failed_run.log] == [f"x/runs/{failed_run.run_id}/x.log"]
    with pytest.raises(ValueError, match="x.log"):
        job.run_task(STAGE_X, {}, _fail, log_name="../x.log")


def test_a_run_whose_directory_cannot_be_made_is_recorded_as_failed(
    specs: Mapping[str, ProcessSpec],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_directory = Path.mkdir

    def refuse_run_directories(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.parent.name == "runs":
            raise PermissionError("no run directory")
        make_directory(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_run_directories)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(PermissionError):
        job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    record = job.task_record(STAGE_X)
    assert record is not None
    assert record.latest_run.status == "failed"
    assert record.latest_run.error == "no run directory"


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
    def stop(overwrite: bool, run_dir: Path) -> TaskOutcome:
        raise error

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(type(error)):
        job.run_task(STAGE_X, {}, stop)
    record = job.task_record(STAGE_X)
    assert record is not None
    interrupted_run = record.latest_run
    assert interrupted_run.status == "interrupted"
    assert interrupted_run.error == recorded_error
    assert interrupted_run.finished is not None
    rerun = job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    assert [run.status for run in rerun.runs] == ["interrupted", "done"]


def test_a_failure_without_a_message_is_recorded_by_its_type(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def fail_without_message(overwrite: bool, run_dir: Path) -> TaskOutcome:
        raise AssertionError

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(AssertionError):
        job.run_task(STAGE_X, {}, fail_without_message)
    record = job.task_record(STAGE_X)
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

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        replaced_run_ids.append(run_dir.name)
        newer_record = TaskRecord.running({"events": 20})
        newer_record.write(job.task_record_path(STAGE_X), root_dir=job.root_dir)
        newer_records.append(newer_record)
        if fails:
            raise RuntimeError("boom")
        return _make_output(job)

    with pytest.raises(ReplacedRunError) as refusal:
        job.run_task(STAGE_X, {"events": 10}, body)
    (replaced_run_id,) = replaced_run_ids
    (newer_record,) = newer_records
    assert job.task_record(STAGE_X) == newer_record
    status = "failed" if fails else "done"
    assert str(refusal.value) == (
        f"Run {replaced_run_id!r} of the x task in {job.root_dir} is not recorded "
        f"as {status}: run {newer_record.latest_run.run_id!r} of the task started "
        "before it ended"
    )
    assert isinstance(refusal.value.__context__, RuntimeError) is fails


def test_a_run_whose_record_was_deleted_records_its_end(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)

    def delete_record_then_finish(overwrite: bool, run_dir: Path) -> TaskOutcome:
        job.task_record_path(STAGE_X).unlink()
        return _make_output(job)

    record = job.run_task(STAGE_X, {}, delete_record_then_finish)
    assert record.is_done
    assert job.task_record(STAGE_X) == record


PARAMETERS = {"events": 10, "input_fingerprint": "v1:original"}
CHANGED_INPUT_PARAMETERS = {"events": 10, "input_fingerprint": "v1:changed"}


def _body(job: Job) -> Callable[[bool, Path], TaskOutcome]:
    """Return a body that makes the output of task ``x`` of `job`."""
    return lambda overwrite, run_dir: _make_output(job)


def test_an_accepted_input_keeps_a_done_task_without_a_run(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = job.run_task(STAGE_X, PARAMETERS, _body(job))
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job))
    accepted_record = job.run_task(
        STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True
    )
    assert accepted_record.accepted_input is not None
    assert accepted_record.accepted_input.fingerprint == "v1:changed"
    assert accepted_record.is_done
    assert (
        accepted_record.parameters,
        accepted_record.runs,
        accepted_record.result,
    ) == (
        done_record.parameters,
        done_record.runs,
        done_record.result,
    )
    assert job.task_record(STAGE_X) == accepted_record
    assert (
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job)) == accepted_record
    )
    assert job.run_task(STAGE_X, PARAMETERS, _body(job)) == accepted_record
    assert (
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
        == accepted_record
    )
    assert (
        job.run_task(STAGE_X, PARAMETERS, _body(job), accept_input=True)
        == accepted_record
    )


def test_a_later_acceptance_replaces_the_earlier_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, PARAMETERS, _body(job))
    job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
    later_parameters = {**PARAMETERS, "input_fingerprint": "v1:later"}
    later_record = job.run_task(
        STAGE_X, later_parameters, _body(job), accept_input=True
    )
    assert later_record.accepted_input is not None
    assert later_record.accepted_input.fingerprint == "v1:later"
    assert job.run_task(STAGE_X, later_parameters, _body(job)) == later_record
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job))


def test_an_input_is_accepted_only_when_nothing_else_differs(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = job.run_task(STAGE_X, PARAMETERS, _body(job))
    other_parameters = {**CHANGED_INPUT_PARAMETERS, "events": 20}
    with pytest.raises(ValueError, match="events: expected 10") as refusal:
        job.run_task(STAGE_X, other_parameters, _body(job), accept_input=True)
    assert "input_fingerprint" not in str(refusal.value)
    with pytest.raises(ValueError, match="events: expected 10"):
        job.run_task(STAGE_X, {"events": 20}, _body(job), accept_input=True)
    with pytest.raises(ValueError, match="cannot both be set"):
        job.run_task(
            STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True, force=True
        )
    assert job.task_record(STAGE_X) == done_record


def test_accept_input_changes_nothing_for_a_task_that_is_not_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_X, PARAMETERS, _fail, accept_input=True)
    failed_record = job.task_record(STAGE_X)
    assert failed_record is not None
    assert failed_record.latest_run.status == "failed"
    record = job.run_task(
        STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True
    )
    assert record.is_done and len(record.runs) == 1
    assert record.parameters == CHANGED_INPUT_PARAMETERS
    assert record.accepted_input is None


def test_a_record_holds_an_accepted_input_only_when_its_latest_run_is_done() -> None:
    with pytest.raises(ValueError, match="has an accepted input"):
        TaskRecord({}, (_run("failed"),), accepted_input=AcceptedInput("f", "t"))


def test_a_task_run_again_after_an_acceptance_compares_the_input_it_ran_on(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, PARAMETERS, _body(job))
    job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
    (job.task_dir(STAGE_X) / "out.txt").unlink()
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job))
    rerun = job.run_task(STAGE_X, PARAMETERS, _body(job))
    assert len(rerun.runs) == 2
    assert rerun.accepted_input is None
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job))
    forced = job.run_task(STAGE_X, CHANGED_INPUT_PARAMETERS, _body(job), force=True)
    assert (
        forced.parameters == CHANGED_INPUT_PARAMETERS and forced.accepted_input is None
    )


def test_two_jobs_opened_on_one_directory_keep_the_records_of_both_tasks(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    first = Job(specs["HToBB"], tmp_path, 1)
    second = Job(specs["HToBB"], tmp_path, 1)
    x_record = first.run_task(
        STAGE_X, {}, lambda overwrite, run_dir: _make_output(first)
    )
    y_record = second.run_task(
        STAGE_Y, {}, lambda overwrite, run_dir: TaskOutcome(TaskResult())
    )
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task_names() == ["x", "y"]
    assert job.task_record(STAGE_X) == x_record
    assert job.task_record(STAGE_Y) == y_record
    assert set(Manifest.read(job.manifest_path).tasks) == {"x", "y"}


def test_the_manifest_lists_every_task_and_is_written_again_when_deleted(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool, run_dir: Path) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    x_record = job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task(STAGE_Y, {}, failing)
    y_record = job.task_record(STAGE_Y)
    assert y_record is not None
    manifest = Manifest(
        job.identity,
        {
            "x": TaskSummary(
                "done", x_record.latest_run.run_id, 1, job.task_record_path(STAGE_X)
            ),
            "y": TaskSummary(
                "failed", y_record.latest_run.run_id, 1, job.task_record_path(STAGE_Y)
            ),
        },
    )
    assert Manifest.read(job.manifest_path) == manifest

    job.manifest_path.unlink()
    assert (
        job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
        == x_record
    )
    assert not job.manifest_path.exists()
    z_record = job.run_task(
        STAGE_Z, {}, lambda overwrite, run_dir: TaskOutcome(TaskResult())
    )
    entry = TaskSummary(
        "done", z_record.latest_run.run_id, 1, job.task_record_path(STAGE_Z)
    )
    assert Manifest.read(job.manifest_path) == Manifest(
        job.identity, {**manifest.tasks, "z": entry}
    )


def test_a_task_is_found_by_the_record_in_its_own_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    record_path = job.task_record_path(STAGE_X)
    deeper_dir = job.task_dir(STAGE_X) / "deeper"
    deeper_dir.mkdir()
    shutil.copy(record_path, deeper_dir / "task.json")
    shutil.copy(record_path, job.root_dir / "task.json")
    (job.root_dir / "empty").mkdir()
    assert job.task_names() == ["x"]


def test_a_task_record_that_cannot_be_read_stops_every_task_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, {}, body)
    record_path = job.task_record_path(STAGE_X)
    record_path.write_text("{")
    unreadable = re.escape(f"{record_path} is not valid JSON")
    with pytest.raises(ValueError, match=unreadable):
        job.task(STAGE_X)
    with pytest.raises(ValueError, match=unreadable):
        job.run_task(STAGE_X, {}, body, force=True)
    with pytest.raises(ValueError, match=unreadable):
        job.run_task(STAGE_Y, {}, body)
    assert calls == [False]
    assert job.set_aside_folders() == []


def test_the_first_task_writes_the_identity_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
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
    record = later.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(later))
    assert record.is_done
    assert JobIdentity.read(job.identity_path).omphjc_version == "0.0.1"


def test_a_directory_of_another_job_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    shifted = Job(replace(specs["HToBB"], seed_offset=20_000_000), tmp_path, 1)
    job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))
    refusal = (
        "The current configuration is inconsistent with that of the existing"
        " job in .*job_1 \\(job.json\\):"
        "\n  seed: expected 10000001, got 20000001"
        "\nRerun with the configuration the job was created with, or choose"
        " another output directory.$"
    )
    calls = []
    with pytest.raises(ValueError, match=refusal):
        shifted.run_task(STAGE_Y, {}, calls.append, force=True)
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

    def remove_then_finish(overwrite: bool, run_dir: Path) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        return _make_output(job)

    with pytest.raises(
        FileNotFoundError, match="job.json was removed while the x task ran"
    ):
        job.run_task(STAGE_X, {}, remove_then_finish)
    assert not job.identity_path.exists()
    assert not job.manifest_path.exists()

    def remove_then_fail(overwrite: bool, run_dir: Path) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        raise RuntimeError("the program stopped")

    with pytest.raises(FileNotFoundError, match="is not recorded") as failure:
        Job(specs["HToBB"], tmp_path, 1).run_task(STAGE_X, {}, remove_then_fail)
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
    with pytest.raises(ValueError, match="job.json has invalid content"):
        Job(specs["HToBB"], tmp_path, 1)
    job.identity_path.write_text("not json")
    with pytest.raises(ValueError, match="job.json is not valid JSON"):
        job.run_task(STAGE_X, {}, lambda overwrite, run_dir: _make_output(job))


def test_generate_records_what_madgraph_made(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["TTBar"], tmp_path, 3)
    record = generate(job, n_events=10, mg5_path=mg5_path)
    assert job.task_record(GenerateStage()) == record
    assert record.is_done
    assert record.parameters == {"events": 10, "seed": 3}
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
        "generate/TTBar/Events/run_01_decayed_1/unweighted_events.lhe.gz"
    )
    assert lhe_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventOutput(
            lhe_path,
            n_bytes=lhe_path.stat().st_size,
            format=EventFormat.LHE,
            n_events=10000,
            fingerprint=LHEFile.read(lhe_path).fingerprint(),
        )
    }
    assert (
        record.latest_run.log
        == f"generate/runs/{record.latest_run.run_id}/madgraph.log"
    )
    card = job.root_dir / "generate" / "cards" / "proc_card_mg5.dat"
    assert card.is_file()
    assert record.cards["proc_card"] == TaskCard(
        card, hashlib.sha256(card.read_bytes()).hexdigest()
    )
    assert set(record.cards) == {"proc_card", "madspin_card"}
    assert "cards" not in metadata
    assert (card.parent / "madspin_card.dat").is_file()
    launch = (job.root_dir / "generate" / "launch.mg5").read_text().splitlines()
    assert "set iseed 3" in launch and "set python_seed 3" in launch


@pytest.mark.parametrize("n_cores", [2, None])
def test_generate_records_the_cores_as_metadata(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    n_cores: int | None,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = generate(job, n_events=10, n_cores=n_cores, mg5_path=mg5_path)
    expected = available_cores() if n_cores is None else n_cores
    assert record.result.metadata["n_cores"] == expected
    rerun = generate(job, n_events=10, n_cores=expected + 1, mg5_path=mg5_path)
    assert rerun == record


def test_generate_keeps_a_finished_run_unless_forced(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    first = generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    runs_dir = tmp_path / "HToBB" / "job_1" / "generate" / "runs"
    first_run_id = first.latest_run.run_id
    assert [path.name for path in runs_dir.iterdir()] == [first_run_id]
    assert (
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
        == first
    )
    assert [path.name for path in runs_dir.iterdir()] == [first_run_id]
    with pytest.raises(ValueError, match="events: expected 10, got 20"):
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=20, mg5_path=mg5_path)
    shifted = replace(specs["HToBB"], seed_offset=20_000_000)
    with pytest.raises(ValueError, match="seed: expected 10000001, got 20000001"):
        generate(Job(shifted, tmp_path, 1), n_events=10, mg5_path=mg5_path)
    again = generate(
        Job(specs["HToBB"], tmp_path, 1), n_events=20, mg5_path=mg5_path, force=True
    )
    assert again.is_done
    assert again.parameters == {"events": 20, "seed": 10000001}
    assert len(again.runs) == 1
    run_ids = sorted([first_run_id, again.latest_run.run_id])
    assert sorted(path.name for path in runs_dir.iterdir()) == run_ids
    assert (runs_dir / first_run_id / "madgraph.log").is_file()


def test_a_failed_madgraph_run_is_recorded_and_retried(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", "launch")
    with pytest.raises(MadGraphError):
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    record = Job(specs["HToBB"], tmp_path, 1).task_record(GenerateStage())
    assert record is not None
    assert (
        record.latest_run.status == "failed" and record.latest_run.finished is not None
    )
    assert (
        record.latest_run.error is not None and "launch.mg5" in record.latest_run.error
    )
    monkeypatch.delenv("FAKE_MG5_FAIL")
    done = generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    assert done.is_done
    failed_run, done_run = done.runs
    assert failed_run.run_id != done_run.run_id
    runs_dir = tmp_path / "HToBB" / "job_1" / "generate" / "runs"
    for run in done.runs:
        assert (runs_dir / run.run_id / "madgraph.log").is_file()
    for run in done.runs:
        assert run.log == f"generate/runs/{run.run_id}/madgraph.log"


def test_shower_needs_a_finished_madgraph_stage(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc generate first"):
        shower(
            Job(specs["HToBB"], tmp_path, 1), delphes_pythia8_path=delphes_pythia8_path
        )
    assert not (tmp_path / "HToBB").exists()


def test_shower_records_what_it_made_and_keeps_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    tmp_path: Path,
) -> None:
    generated = generate(
        Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path
    )
    job = Job(specs["HToBB"], tmp_path, 1)
    record = shower(job, delphes_pythia8_path=delphes_pythia8_path)
    assert job.task_record(ShowerStage()) == record
    assert record.is_done
    assert record.parameters == {
        "events": 10000,
        "seed": 10000001,
        "pythia": {},
        "input_fingerprint": generated.result.outputs[EVENTS_OUTPUT].fingerprint,
    }
    metadata = record.result.metadata
    assert metadata["pythia_version"] == "8.318"
    assert metadata["events_read"] == 1
    assert "matching_efficiency" not in metadata
    assert record.cards == {
        "command_file": TaskCard.from_path(job.root_dir / "shower" / "pythia.cmnd"),
        "particles_card": TaskCard.from_path(
            job.root_dir / "shower" / "particles_card.tcl"
        ),
    }
    assert "settings" not in metadata
    root_path = job.root_dir / "shower" / "particles.root"
    assert root_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventOutput(
            root_path,
            n_bytes=root_path.stat().st_size,
            format=EventFormat.DELPHES_ROOT,
            n_events=1,
            fingerprint=DelphesROOTFile.read(root_path).fingerprint(),
        )
    }
    assert record.latest_run.log == f"shower/runs/{record.latest_run.run_id}/shower.log"
    cmnd = (job.root_dir / "shower" / "pythia.cmnd").read_text()
    assert "Random:seed = 10000001" in cmnd and "Main:numberOfEvents = 10000" in cmnd
    card = (job.root_dir / "shower" / "particles_card.tcl").read_text()
    assert "TreeWriter" in card and "RandomSeed" not in card

    kept = shower(
        Job(specs["HToBB"], tmp_path, 1), delphes_pythia8_path=delphes_pythia8_path
    )
    assert kept == record
    overrides = {"Main:timesAllowErrors": 5}
    added = re.escape("unexpected pythia.Main:timesAllowErrors: 5")
    with pytest.raises(ValueError, match=added):
        shower(
            Job(specs["HToBB"], tmp_path, 1),
            overrides=overrides,
            delphes_pythia8_path=delphes_pythia8_path,
        )
    forced = shower(
        Job(specs["HToBB"], tmp_path, 1),
        overrides=overrides,
        force=True,
        delphes_pythia8_path=delphes_pythia8_path,
    )
    assert forced.parameters["pythia"] == overrides
    assert (
        "Main:timesAllowErrors = 5"
        in (job.root_dir / "shower" / "pythia.cmnd").read_text()
    )


def test_shower_records_the_matching_efficiency_of_a_matched_process(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    tmp_path: Path,
) -> None:
    generate(Job(specs["ZJetsToNuNu"], tmp_path, 2), n_events=10, mg5_path=mg5_path)
    record = shower(
        Job(specs["ZJetsToNuNu"], tmp_path, 2),
        delphes_pythia8_path=delphes_pythia8_path,
    )
    assert record.result.metadata["matching_efficiency"] == 1.0
    cmnd = (tmp_path / "ZJetsToNuNu" / "job_2" / "shower" / "pythia.cmnd").read_text()
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

    def body(overwrite: bool, run_dir: Path) -> TaskOutcome:
        aside = job.task_dir(STAGE_X) / "omphjc-set-aside" / "20260101T000000Z-abc"
        aside.mkdir(parents=True)
        return replace(_make_output(job), set_aside_dir=aside)

    record = job.run_task(STAGE_X, {"events": 10}, body)
    assert record.latest_run.set_aside == "x/omphjc-set-aside/20260101T000000Z-abc"
    assert job.task_record(STAGE_X) == record


def test_a_job_lists_and_clears_what_its_stages_set_aside(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omphjc.workspace as workspace

    with monkeypatch.context() as killed_before_sealing:
        killed_before_sealing.setattr(workspace, "seal", lambda *_: None)
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.set_aside_folders() == []
    record = generate(job, n_events=10, force=True, mg5_path=mg5_path)
    assert record.latest_run.set_aside is not None
    assert record.latest_run.set_aside.startswith("generate/omphjc-set-aside/")
    folders = job.set_aside_folders()
    assert [job.relative_path(folder.path) for folder in folders] == [
        record.latest_run.set_aside
    ]
    assert folders[0].size() > 0
    assert job.clear_set_aside_folders() == folders
    assert job.set_aside_folders() == []
    assert not (job.task_dir(GenerateStage()) / "omphjc-set-aside").exists()
    assert job.task(GenerateStage()).status is TaskStatus.DONE


def test_simulate_needs_a_finished_shower_stage(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc shower first"):
        simulate(Job(specs["HToBB"], tmp_path, 1), delphes_root_path=delphes_root_path)
    assert not (tmp_path / "HToBB" / "job_1" / "simulate").exists()


def _run_all(
    job: Job, mg5_path: Path, delphes_pythia8_path: Path, delphes_root_path: Path
) -> tuple[TaskRecord, TaskRecord, TaskRecord]:
    return (
        generate(job, n_events=10, mg5_path=mg5_path),
        shower(job, delphes_pythia8_path=delphes_pythia8_path),
        simulate(job, delphes_root_path=delphes_root_path),
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
    generate(job, n_events=10, mg5_path=mg5_path, force=True)
    assert shower(job, delphes_pythia8_path=delphes_pythia8_path) == showered
    shower(job, delphes_pythia8_path=delphes_pythia8_path, force=True)
    assert simulate(job, delphes_root_path=delphes_root_path) == simulated


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
    generate(job, n_events=10, mg5_path=mg5_path, force=True)
    lhe_fingerprint = job.require_events(GenerateStage()).fingerprint
    assert lhe_fingerprint != generated.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(ValueError, match="input_fingerprint: expected lhe-v1:"):
        shower(job, delphes_pythia8_path=delphes_pythia8_path)
    forced = shower(job, delphes_pythia8_path=delphes_pythia8_path, force=True)
    assert forced.parameters["input_fingerprint"] == lhe_fingerprint
    root_fingerprint = forced.result.outputs[EVENTS_OUTPUT].fingerprint
    assert root_fingerprint != showered.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(
        ValueError, match="input_fingerprint: expected delphes_root-v1:"
    ):
        simulate(job, delphes_root_path=delphes_root_path)
    forced = simulate(job, delphes_root_path=delphes_root_path, force=True)
    assert forced.parameters["input_fingerprint"] == root_fingerprint


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
    generate(job, n_events=10, mg5_path=mg5_path, force=True)
    lhe_fingerprint = job.require_events(GenerateStage()).fingerprint
    accepted_record = shower(
        job, delphes_pythia8_path=delphes_pythia8_path, accept_input=True
    )
    assert accepted_record.accepted_input is not None
    assert accepted_record.accepted_input.fingerprint == lhe_fingerprint
    assert accepted_record.parameters == showered.parameters
    assert accepted_record.runs == showered.runs
    assert shower(job, delphes_pythia8_path=delphes_pythia8_path) == accepted_record
    assert simulate(job, delphes_root_path=delphes_root_path) == simulated
    assert (
        simulate(job, delphes_root_path=delphes_root_path, accept_input=True)
        == simulated
    )
    with pytest.raises(ValueError, match="cannot both be set"):
        shower(job, accept_input=True, force=True)
    with pytest.raises(ValueError, match="cannot both be set"):
        simulate(job, accept_input=True, force=True)


def test_a_kept_stage_reads_no_event_file(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done = _run_all(job, mg5_path, delphes_pythia8_path, delphes_root_path)
    for stage in (GenerateStage(), ShowerStage(), SimulateStage()):
        event_path = job.require_events(stage).path
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
    generate(job, n_events=10, mg5_path=mg5_path)
    shower(job, delphes_pythia8_path=delphes_pythia8_path)
    root_path = job.require_events(ShowerStage()).path
    recorded = root_path.stat().st_size
    root_path.write_bytes(root_path.read_bytes()[: recorded // 2])
    refused = re.escape(
        f"{root_path} holds {recorded // 2} bytes, not the {recorded} the shower "
        "stage recorded; run omphjc shower with --force to regenerate the file"
    )
    with pytest.raises(ValueError, match=refused):
        shower(job, delphes_pythia8_path=delphes_pythia8_path)
    with pytest.raises(ValueError, match=refused):
        simulate(job, delphes_root_path=delphes_root_path)
    shower(job, delphes_pythia8_path=delphes_pythia8_path, force=True)
    assert simulate(job, delphes_root_path=delphes_root_path).is_done


def test_simulate_records_what_it_made_and_keeps_it(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    generate(job, n_events=10, mg5_path=mg5_path)
    showered = shower(job, delphes_pythia8_path=delphes_pythia8_path)
    record = simulate(job, delphes_root_path=delphes_root_path)
    assert record.is_done
    assert record.parameters["seed"] == job.seed
    assert (
        record.parameters["input_fingerprint"]
        == showered.result.outputs[EVENTS_OUTPUT].fingerprint
    )
    assert len(record.parameters["card"]) == 64
    card_path = job.root_dir / "simulate" / "delphes_card.tcl"
    assert record.cards == {"detector_card": TaskCard.from_path(card_path)}
    assert record.metadata == {}
    root_path = job.root_dir / "simulate" / "delphes.root"
    assert root_path.is_file()
    assert record.result.outputs == {
        EVENTS_OUTPUT: EventOutput(
            root_path,
            n_bytes=root_path.stat().st_size,
            format=EventFormat.DELPHES_ROOT,
            n_events=1,
            fingerprint=DelphesROOTFile.read(root_path).fingerprint(),
        )
    }
    assert (
        record.latest_run.log
        == f"simulate/runs/{record.latest_run.run_id}/simulate.log"
    )
    card = (job.root_dir / "simulate" / "delphes_card.tcl").read_text()
    assert card.endswith("\nset RandomSeed 10000001\n")
    log = (job.root_dir / record.latest_run.log).read_text()
    assert f"** Reading {job.root_dir / 'shower' / 'particles.root'}" in log

    kept = simulate(
        Job(specs["HToBB"], tmp_path, 1), delphes_root_path=delphes_root_path
    )
    assert kept == record
    other = tmp_path / "other.tcl"
    other.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    with pytest.raises(ValueError, match="card: expected "):
        simulate(
            Job(specs["HToBB"], tmp_path, 1),
            card_path=other,
            delphes_root_path=delphes_root_path,
        )
    forced = simulate(
        Job(specs["HToBB"], tmp_path, 1),
        card_path=other,
        force=True,
        delphes_root_path=delphes_root_path,
    )
    assert forced.is_done and forced.parameters["card"] != record.parameters["card"]
    assert (
        (job.root_dir / "simulate" / "delphes_card.tcl")
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
    generate(job, n_events=10, mg5_path=mg5_path)
    shower(job, delphes_pythia8_path=delphes_pythia8_path)
    showered = job.require_events(ShowerStage())
    # The fake DelphesROOT copies its input, so the simulated file holds three
    # events while the shower stage recorded one.
    pids = ak.Array([[2212, 211], [2212], [211, 211, 22]])
    write_delphes_file(showered.path, {"PID": pids}, omit=omit)
    # The shower stage is recorded with the size of the file put in its place.
    record = job.task_record(ShowerStage())
    assert record is not None
    record.result.outputs[EVENTS_OUTPUT] = replace(
        showered, n_bytes=showered.path.stat().st_size
    )
    record.write(job.task_record_path(ShowerStage()), root_dir=job.root_dir)
    simulate(job, delphes_root_path=delphes_root_path)
    assert showered.n_events == 1
    assert job.require_events(SimulateStage()).n_events == 3


def test_a_forced_rerun_of_each_program_leaves_the_record_of_its_task(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    runs = {
        GenerateStage(): lambda force: generate(
            job, n_events=10, force=force, mg5_path=mg5_path
        ),
        ShowerStage(): lambda force: shower(
            job, force=force, delphes_pythia8_path=delphes_pythia8_path
        ),
        SimulateStage(): lambda force: simulate(
            job, force=force, delphes_root_path=delphes_root_path
        ),
    }
    for stage, run in runs.items():
        run(False)
        record = run(True)
        assert record.latest_run.set_aside is None
        assert job.task_record(stage) == record
        stamp = read_stamp(job.task_dir(stage))
        assert stamp is not None and "task.json" not in stamp.artifacts
