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
from omphjc.data_files import Card, FileRecord
from omphjc.events import EventFileRecord, EventFormat, EventSource
from omphjc.events.delphes_root import DelphesROOTFile
from omphjc.jobs import (
    GENERATE_TASK,
    SHOWER_TASK,
    AcceptedInput,
    Job,
    JobIdentity,
    Manifest,
    ReplacedRunError,
    Task,
    TaskIdentity,
    TaskOutcome,
    TaskRecord,
    TaskRun,
    TaskStatus,
    TaskSummary,
    TerminationError,
    exception_on_termination,
    generate,
    job_seed,
    shower,
    simulate,
    task_parameters,
)
from omphjc.jobs.job import TaskBody
from omphjc.processes import ProcessSpec, get_process
from omphjc.programs import ProgramError, available_cores
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.stages import GenerateStage, ShowerStage, SimulateStage
from omphjc.stamps import COMPACT_UTC_FORMAT, read_stamp
from omphjc.tools.delphes.adapter import DelphesSimulator
from omphjc.tools.delphes.card import DetectorCard, ParticlesCard
from omphjc.tools.madgraph.lhe_file import LHEFile
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT, PythiaCmnd

RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


TASK_X = TaskIdentity("x", "fake")
TASK_Y = TaskIdentity("y", "fake")
TASK_Z = TaskIdentity("z", "fake")
SIMULATE_TASK = TaskIdentity("simulate", "delphes")


def _delphes_simulator(
    job: Job, delphes_root_path: Path, **options: Any
) -> DelphesSimulator:
    """Return a Delphes simulator for the process of `job`."""
    return DelphesSimulator(job.spec, delphes_root_path=delphes_root_path, **options)


def _task(job: Job, identity: TaskIdentity) -> Task:
    """Return the task `identity` of `job`."""
    return job.task(identity)


def _run_task(
    job: Job,
    identity: TaskIdentity,
    parameters: dict[str, Any],
    body: TaskBody,
    **options: bool,
) -> TaskRecord:
    """Run the task `identity` of `job` with `parameters`; `body` makes its files."""
    return job.run_task(identity, parameters, body, **options)


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
    tasks = [GENERATE_TASK, SHOWER_TASK, SIMULATE_TASK]
    assert [task.name for task in tasks] == [
        "generate-madgraph",
        "shower-pythia",
        "simulate-delphes",
    ]
    assert [task.command for task in tasks] == [
        "omphjc generate",
        "omphjc shower",
        "omphjc simulate",
    ]
    tagged = TaskIdentity("shower", "pythia", "tuneA")
    assert tagged.name == "shower-pythia-tuneA"
    assert tagged != SHOWER_TASK and TaskIdentity("shower", "pythia") == SHOWER_TASK


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
    assert job.task_dir(GENERATE_TASK) == job.root_dir / "generate-madgraph"
    assert (
        job.relative_path(job.root_dir / "generate-madgraph" / "x.log")
        == "generate-madgraph/x.log"
    )
    assert job.seed == 10000007
    assert job.identity_path == job.root_dir / "job.json"
    assert job.identity == JobIdentity(process="HToBB", job_id=7, seed=10000007)
    assert (
        job.task_record_path(GENERATE_TASK)
        == job.root_dir / "generate-madgraph" / "task.json"
    )
    assert job.task_record(GENERATE_TASK) is None
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
        parameters={"events": 10},
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
    assert written["parameters"] == {"events": 10}
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
    assert written["accepted_input"] is None
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
    with pytest.raises(ValueError, match="task.json is not valid JSON"):
        TaskRecord.read(path, root_dir=tmp_path)


def test_a_task_record_needs_a_run_and_a_result_that_fits_its_status(
    tmp_path: Path,
) -> None:
    done = _run("done")
    with pytest.raises(ValueError, match="the record has no runs"):
        TaskRecord(TASK_X, parameters={}, runs=())
    with pytest.raises(
        ValueError, match="has status 'done' but the record has no result"
    ):
        TaskRecord(TASK_X, parameters={}, runs=(done,))
    failed = _run("failed", error="boom")
    with pytest.raises(
        ValueError, match="has status 'failed' but the record has a result"
    ):
        TaskRecord(TASK_X, parameters={}, runs=(failed,), result=RunResult())
    with pytest.raises(ValueError, match="unknown run status 'paused'"):
        _run("paused")
    path = tmp_path / "x-fake" / "task.json"
    path.parent.mkdir()
    without_runs = {"schema": 1, "parameters": {}, "result": None}
    path.write_text(json.dumps(without_runs))
    with pytest.raises(ValueError, match="invalid content: the record has no runs"):
        TaskRecord.read(path, root_dir=tmp_path)


def test_a_record_gives_its_outputs_only_when_its_latest_run_is_done(
    tmp_path: Path,
) -> None:
    events = EventFileRecord(tmp_path / "e.lhe", 7, "lhe-v1:abc", EventFormat.LHE, 10)
    done = TaskRecord(
        TASK_X,
        parameters={},
        runs=(_run("done"),),
        result=RunResult(outputs={EVENTS_OUTPUT: events}, metadata={"n": 1}),
    )
    assert done.events == events and done.metadata == {"n": 1}
    assert done.is_done
    no_events = TaskRecord(TASK_X, {}, (_run("done"),), RunResult())
    assert no_events.events is None
    failed = TaskRecord(TASK_X, {}, (_run("failed", error="boom"),))
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


def _make_output(job: Job) -> TaskOutcome:
    directory = job.task_dir(TASK_X)
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
    record = _run_task(job, TASK_X, {"events": 10}, body)
    assert calls == [False]
    assert record.is_done and record.latest_run.finished is not None
    assert len(record.runs) == 1
    assert record.parameters == {"events": 10}
    assert record.result == RunResult(
        outputs={"out": FileRecord(job.root_dir / "x-fake" / "out.txt", 4, None)},
        metadata={"n": 1},
    )
    assert job.task_record(TASK_X) == record

    job = Job(specs["HToBB"], tmp_path, 1)
    assert _task(job, TASK_X) == Task(
        TASK_X, job.task_dir(TASK_X), TaskStatus.DONE, record=record
    )
    assert _run_task(job, TASK_X, {"events": 10}, body) == record
    assert calls == [False]


def test_other_parameters_need_force_and_force_replaces(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {"events": 10}, body)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError) as refusal:
        _run_task(job, TASK_X, {"events": 20}, body)
    assert str(refusal.value) == (
        "The current parameters are inconsistent with those of the existing "
        f"x-fake task in {job.root_dir} (x-fake/task.json):\n"
        "  events: expected 10, got 20\n"
        "Rerun with the parameters the task ran with, or run omphjc x with "
        "--force to replace its result."
    )
    forced = _run_task(job, TASK_X, {"events": 20}, body, force=True)
    assert forced.parameters == {"events": 20}
    assert len(forced.runs) == 1
    assert calls == [False, True]


def test_a_refusal_names_only_the_parameters_that_differ(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    pythia = {"Main:timesAllowErrors": 5, "Tune:pp": 14}
    _run_task(
        job, TASK_X, {"events": 10, "pythia": pythia}, lambda *_: _make_output(job)
    )
    changed = {**pythia, "Main:timesAllowErrors": 7, "Next:numberCount": 0}
    with pytest.raises(ValueError) as refusal:
        _run_task(
            job, TASK_X, {"events": 10, "pythia": changed}, lambda *_: _make_output(job)
        )
    assert str(refusal.value).splitlines()[1:-1] == [
        "  pythia.Main:timesAllowErrors: expected 5, got 7",
        "  unexpected pythia.Next:numberCount: 0",
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
    assert _task(job, TASK_X) == Task(TASK_X, job.task_dir(TASK_X), TaskStatus.NOT_DONE)
    record = _run_task(job, TASK_X, {}, body)
    output_path = job.root_dir / "x-fake" / "out.txt"
    output_path.unlink()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert _task(job, TASK_X) == Task(
        TASK_X,
        job.task_dir(TASK_X),
        TaskStatus.MISSING_OUTPUT,
        f"{output_path} is missing",
        record,
    )
    rerun = _run_task(job, TASK_X, {}, body)
    assert calls == [False, True]
    assert [run.status for run in rerun.runs] == ["done", "done"]
    assert rerun.metadata == {"n": 2}

    running = TaskRecord(TASK_X, {}, (_run("running"),))
    running.write(job.task_record_path(TASK_X), root_dir=job.root_dir)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert _task(job, TASK_X) == Task(
        TASK_X, job.task_dir(TASK_X), TaskStatus.NOT_DONE, record=running
    )
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
        job.require_done(TASK_X)
    record = _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    assert job.require_done(TASK_X) == record
    (job.root_dir / "x-fake" / "out.txt").unlink()
    with pytest.raises(ValueError, match=not_done):
        job.require_done(TASK_X)


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
    assert _task(job, TASK_X) == Task(
        TASK_X, job.task_dir(TASK_X), TaskStatus.CHANGED, detail, record
    )
    refused = re.escape(f"{detail}; run omphjc x with --force to regenerate the file")
    with pytest.raises(ValueError, match=refused):
        job.require_done(TASK_X)
    with pytest.raises(ValueError, match=refused):
        _run_task(job, TASK_X, {}, body)
    assert calls == [False]
    assert _run_task(job, TASK_X, {}, body, force=True).is_done
    assert calls == [False, True]
    assert job.require_done(TASK_X).result.outputs["out"].n_bytes == 4


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
    assert _task(job, TASK_X) == Task(
        TASK_X,
        job.task_dir(TASK_X),
        TaskStatus.CHANGED,
        f"{second_path} holds 16 bytes, not the 4 the x-fake task recorded",
        record,
    )
    with pytest.raises(ValueError, match="with --force to regenerate the file"):
        _run_task(job, TASK_X, {}, body)


def test_require_events_returns_the_events_a_done_stage_made(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="has not run to completion"):
        job.require_events(TASK_X)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    with pytest.raises(ValueError, match="The x-fake task of .* made no event file"):
        job.require_events(TASK_X)

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
    assert Job(specs["HToBB"], tmp_path, 1).require_events(TASK_X) == events


def test_a_failed_stage_is_recorded_raised_and_replaced_on_retry(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool, log_path: Path) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_X, {"events": 10}, failing)
    record = job.task_record(TASK_X)
    assert record is not None
    assert (
        record.latest_run.status == "failed" and record.latest_run.finished is not None
    )
    assert record.parameters == {"events": 10} and record.result is None
    assert record.latest_run.error == "boom"

    calls: list[bool] = []

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    rerun = _run_task(job, TASK_X, {"events": 10}, body)
    assert [run.status for run in rerun.runs] == ["failed", "done"]
    assert rerun.runs[0].usage == {}
    assert rerun.runs[1].usage["wall_seconds"] >= 0
    assert calls == [True]

    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_Y, {"events": 10}, failing)
    other = _run_task(job, TASK_Y, {"events": 20}, body)
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


def test_a_task_is_loaded_from_its_record_file(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    record = _run_task(job, TASK_X, {}, _write_log(job))
    task = Task.read(job.task_record_path(TASK_X))
    assert task == _task(job, TASK_X)
    assert (task.identity, task.name) == (TASK_X, "x-fake")
    assert task.directory == job.task_dir(TASK_X)
    assert (task.status, task.record) == (TaskStatus.DONE, record)
    assert task.latest_log.read_text() == "finished"
    with pytest.raises(FileNotFoundError):
        Task.read(job.task_dir(TASK_Y) / "task.json")


def test_a_task_without_a_record_has_no_latest_log(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    task = _task(Job(specs["HToBB"], tmp_path, 1), TASK_X)
    assert task.record is None
    with pytest.raises(ValueError, match="has no run"):
        _ = task.latest_log


@pytest.mark.parametrize(("parameters", "force"), [({"events": 20}, False), ({}, True)])
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
        (
            TaskRun(
                run_id="../../../../outside", status="failed", started="t", host="h"
            ),
        ),
    )
    job.task_dir(TASK_X).mkdir(parents=True)
    record.write(job.task_record_path(TASK_X), root_dir=job.root_dir)
    with pytest.raises(ValueError, match="Path component"):
        _run_task(job, TASK_X, {"events": 20}, _write_log(job))
    assert outside_path.read_text() == "not a log of the task"
    assert job.task_record(TASK_X) == record


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
    record = job.task_record(TASK_X)
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
    record = job.task_record(TASK_X)
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
    record = job.task_record(TASK_X)
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
        newer_record = TaskRecord.running(TASK_X, {"events": 20})
        newer_record.write(job.task_record_path(TASK_X), root_dir=job.root_dir)
        newer_records.append(newer_record)
        if fails:
            raise RuntimeError("boom")
        return _make_output(job)

    with pytest.raises(ReplacedRunError) as refusal:
        _run_task(job, TASK_X, {"events": 10}, body)
    (replaced_run_id,) = replaced_run_ids
    (newer_record,) = newer_records
    assert job.task_record(TASK_X) == newer_record
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
        job.task_record_path(TASK_X).unlink()
        return _make_output(job)

    record = _run_task(job, TASK_X, {}, delete_record_then_finish)
    assert record.is_done
    assert job.task_record(TASK_X) == record


PARAMETERS = {"events": 10, "input_fingerprint": "v1:original"}
CHANGED_INPUT_PARAMETERS = {"events": 10, "input_fingerprint": "v1:changed"}


def _body(job: Job) -> Callable[[bool, Path], TaskOutcome]:
    """Return a body that makes the output of task ``x`` of `job`."""
    return lambda overwrite, log_path: _make_output(job)


def test_an_accepted_input_keeps_a_done_task_without_a_run(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_task(job, TASK_X, PARAMETERS, _body(job))
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job))
    accepted_record = _run_task(
        job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True
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
    assert job.task_record(TASK_X) == accepted_record
    assert (
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job)) == accepted_record
    )
    assert _run_task(job, TASK_X, PARAMETERS, _body(job)) == accepted_record
    assert (
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
        == accepted_record
    )
    assert (
        _run_task(job, TASK_X, PARAMETERS, _body(job), accept_input=True)
        == accepted_record
    )


def test_a_later_acceptance_replaces_the_earlier_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, PARAMETERS, _body(job))
    _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
    later_parameters = {**PARAMETERS, "input_fingerprint": "v1:later"}
    later_record = _run_task(
        job, TASK_X, later_parameters, _body(job), accept_input=True
    )
    assert later_record.accepted_input is not None
    assert later_record.accepted_input.fingerprint == "v1:later"
    assert _run_task(job, TASK_X, later_parameters, _body(job)) == later_record
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job))


def test_an_input_is_accepted_only_when_nothing_else_differs(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done_record = _run_task(job, TASK_X, PARAMETERS, _body(job))
    other_parameters = {**CHANGED_INPUT_PARAMETERS, "events": 20}
    with pytest.raises(ValueError, match="events: expected 10") as refusal:
        _run_task(job, TASK_X, other_parameters, _body(job), accept_input=True)
    assert "input_fingerprint" not in str(refusal.value)
    with pytest.raises(ValueError, match="events: expected 10"):
        _run_task(job, TASK_X, {"events": 20}, _body(job), accept_input=True)
    with pytest.raises(ValueError, match="cannot both be set"):
        _run_task(
            job,
            TASK_X,
            CHANGED_INPUT_PARAMETERS,
            _body(job),
            accept_input=True,
            force=True,
        )
    assert job.task_record(TASK_X) == done_record


def test_accept_input_changes_nothing_for_a_task_that_is_not_done(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        _run_task(job, TASK_X, PARAMETERS, _fail, accept_input=True)
    failed_record = job.task_record(TASK_X)
    assert failed_record is not None
    assert failed_record.latest_run.status == "failed"
    record = _run_task(
        job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True
    )
    assert record.is_done and len(record.runs) == 1
    assert record.parameters == CHANGED_INPUT_PARAMETERS
    assert record.accepted_input is None


def test_a_record_holds_an_accepted_input_only_when_its_latest_run_is_done() -> None:
    with pytest.raises(ValueError, match="has an accepted input"):
        TaskRecord(
            TASK_X, {}, (_run("failed"),), accepted_input=AcceptedInput("f", "t")
        )


def test_a_task_run_again_after_an_acceptance_compares_the_input_it_ran_on(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, PARAMETERS, _body(job))
    _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), accept_input=True)
    (job.task_dir(TASK_X) / "out.txt").unlink()
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job))
    rerun = _run_task(job, TASK_X, PARAMETERS, _body(job))
    assert len(rerun.runs) == 2
    assert rerun.accepted_input is None
    with pytest.raises(ValueError, match="input_fingerprint: expected v1:original"):
        _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job))
    forced = _run_task(job, TASK_X, CHANGED_INPUT_PARAMETERS, _body(job), force=True)
    assert (
        forced.parameters == CHANGED_INPUT_PARAMETERS and forced.accepted_input is None
    )


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
    assert job.task_record(TASK_X) == x_record
    assert job.task_record(TASK_Y) == y_record
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
    y_record = job.task_record(TASK_Y)
    assert y_record is not None
    manifest = Manifest(
        job.identity,
        {
            "x-fake": TaskSummary(
                "done", x_record.latest_run.run_id, 1, job.task_record_path(TASK_X)
            ),
            "y-fake": TaskSummary(
                "failed", y_record.latest_run.run_id, 1, job.task_record_path(TASK_Y)
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
        "done", z_record.latest_run.run_id, 1, job.task_record_path(TASK_Z)
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
    with pytest.raises(ValueError, match="is the record of"):
        _task(job, same_name)
    with pytest.raises(ValueError, match="is the record of"):
        _run_task(job, same_name, {}, lambda overwrite, log_path: _make_output(job))
    assert job.task_record(tagged) == record


def test_a_record_in_a_directory_of_another_name_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    job.task_dir(TASK_X).rename(job.root_dir / "renamed")
    with pytest.raises(ValueError, match="its directory is named renamed"):
        job.tasks()


def test_a_record_without_an_identity_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    record_path = job.task_record_path(TASK_X)
    written = json.loads(record_path.read_text())
    del written["identity"]
    record_path.write_text(json.dumps(written))
    with pytest.raises(ValueError, match="invalid content"):
        _task(job, TASK_X)


def test_a_task_is_found_by_the_record_in_its_own_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))
    record_path = job.task_record_path(TASK_X)
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
    record_path = job.task_record_path(TASK_X)
    record_path.write_text("{")
    unreadable = re.escape(f"{record_path} is not valid JSON")
    with pytest.raises(ValueError, match=unreadable):
        _task(job, TASK_X)
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
    with pytest.raises(ValueError, match="job.json has invalid content"):
        Job(specs["HToBB"], tmp_path, 1)
    job.identity_path.write_text("not json")
    with pytest.raises(ValueError, match="job.json is not valid JSON"):
        _run_task(job, TASK_X, {}, lambda overwrite, log_path: _make_output(job))


def test_generate_records_what_madgraph_made(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["TTBar"], tmp_path, 3)
    record = generate(job, n_events=10, mg5_path=mg5_path)
    assert job.task_record(GENERATE_TASK) == record
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
    assert _task(job, GENERATE_TASK).log_path(record.latest_run.run_id).is_file()
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
    record = generate(job, n_events=10, n_cores=n_cores, mg5_path=mg5_path)
    expected = available_cores() if n_cores is None else n_cores
    assert record.result.metadata["n_cores"] == expected
    rerun = generate(job, n_events=10, n_cores=expected + 1, mg5_path=mg5_path)
    assert rerun == record


def test_generate_keeps_a_finished_run_unless_forced(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    first = generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    logs_dir = tmp_path / "HToBB" / "job_1" / "generate-madgraph" / "logs"
    first_log = f"{first.latest_run.run_id}.log"
    assert [path.name for path in logs_dir.iterdir()] == [first_log]
    assert (
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
        == first
    )
    assert [path.name for path in logs_dir.iterdir()] == [first_log]
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
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    record = Job(specs["HToBB"], tmp_path, 1).task_record(GENERATE_TASK)
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
    logs_dir = tmp_path / "HToBB" / "job_1" / "generate-madgraph" / "logs"
    for run in done.runs:
        assert (logs_dir / f"{run.run_id}.log").is_file()


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
    assert job.task_record(SHOWER_TASK) == record
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
    assert _task(job, SHOWER_TASK).log_path(record.latest_run.run_id).is_file()
    cmnd = (job.root_dir / "shower-pythia" / "pythia.cmnd").read_text()
    assert "Random:seed = 10000001" in cmnd and "Main:numberOfEvents = 10000" in cmnd
    card = (job.root_dir / "shower-pythia" / "particles_card.tcl").read_text()
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
        in (job.root_dir / "shower-pythia" / "pythia.cmnd").read_text()
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

    record = _run_task(job, TASK_X, {"events": 10}, body)
    assert record.latest_run.set_aside == "x-fake/omphjc-set-aside/20260101T000000Z-abc"
    assert job.task_record(TASK_X) == record


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
    assert record.latest_run.set_aside.startswith("generate-madgraph/omphjc-set-aside/")
    folders = job.set_aside_folders()
    assert [job.relative_path(folder.path) for folder in folders] == [
        record.latest_run.set_aside
    ]
    assert folders[0].size() > 0
    assert job.clear_set_aside_folders() == folders
    assert job.set_aside_folders() == []
    assert not (job.task_dir(GENERATE_TASK) / "omphjc-set-aside").exists()
    assert _task(job, GENERATE_TASK).status is TaskStatus.DONE


@dataclass(frozen=True)
class FakeSimulator:
    """A simulator for tests: it writes one small file and no events."""

    name: ClassVar[str] = "fake-simulator"
    card_classes: ClassVar[tuple[type[Card], ...]] = ()

    input_formats: frozenset[EventFormat] = frozenset({EventFormat.DELPHES_ROOT})
    extra_parameters: tuple[tuple[str, Any], ...] = ()

    def parameters(self, *, seed: int) -> dict[str, Any]:
        return {"seed": seed, **dict(self.extra_parameters)}

    def simulate(
        self,
        source: EventSource,
        *,
        workdir: Path,
        seed: int,
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        workdir.mkdir(parents=True, exist_ok=True)
        output_path = workdir / "simulated.txt"
        output_path.write_text(f"{source.path.name} {seed}")
        log_path.write_text("simulated")
        output = FileRecord(output_path, output_path.stat().st_size, None)
        return TaskOutcome(
            RunResult(
                outputs={"out": output},
                metadata={"input_format": source.format.value},
            )
        )


def _record_showered_events(job: Job, event_format: EventFormat) -> EventFileRecord:
    """Record a done shower task of `job` whose events have `event_format`."""
    events_path = job.task_dir(SHOWER_TASK) / "events.dat"

    def body(overwrite: bool, log_path: Path) -> TaskOutcome:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("events")
        events = EventFileRecord(events_path, 6, "fake-v1:abc", event_format, 1)
        return TaskOutcome(RunResult(outputs={EVENTS_OUTPUT: events}))

    record = _run_task(job, SHOWER_TASK, {}, body)
    assert record.events is not None
    return record.events


def test_simulate_runs_a_simulator_on_the_showered_events(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    events = _record_showered_events(job, EventFormat.DELPHES_ROOT)
    record = simulate(job, FakeSimulator())
    assert record.is_done
    assert record.parameters == {
        "input_fingerprint": events.fingerprint,
        "seed": job.seed,
    }
    assert record.metadata == {"input_format": "delphes-root"}
    assert record.identity == TaskIdentity("simulate", "fake-simulator")
    task = _task(job, record.identity)
    assert task.directory == job.root_dir / "simulate-fake-simulator"
    assert (task.directory / "simulated.txt").read_text() == f"events.dat {job.seed}"
    assert task.latest_log.read_text() == "simulated"
    assert simulate(job, FakeSimulator()) == record


def test_simulate_refuses_events_the_simulator_cannot_read(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _record_showered_events(job, EventFormat.LHE)
    refusal = (
        "fake-simulator reads delphes-root files, but the shower-pythia task of "
        f"{job.root_dir} made a lhe file"
    )
    with pytest.raises(ValueError, match=re.escape(refusal)):
        simulate(job, FakeSimulator())
    assert job.tasks("simulate") == []


def test_simulate_refuses_a_simulator_that_uses_a_key_of_the_stage(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    _record_showered_events(job, EventFormat.DELPHES_ROOT)
    simulator = FakeSimulator(extra_parameters=(("input_fingerprint", "mine"),))
    refusal = "The parameters of fake-simulator use the keys of the stage"
    with pytest.raises(ValueError, match=f"{refusal}: input_fingerprint"):
        simulate(job, simulator)
    assert job.task_record(SIMULATE_TASK) is None


def test_task_parameters_join_the_parameters_of_a_stage_and_its_tool() -> None:
    joined = task_parameters({"events": 10}, {"seed": 7}, tool_name="tool")
    assert joined == {"events": 10, "seed": 7}
    with pytest.raises(ValueError, match="of tool use the keys of the stage: a, b"):
        task_parameters({"a": 1, "b": 2, "c": 3}, {"b": 0, "a": 0}, tool_name="tool")


def test_simulate_needs_a_finished_shower_stage(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc shower first"):
        job = Job(specs["HToBB"], tmp_path, 1)
        simulate(job, _delphes_simulator(job, delphes_root_path))
    assert not (tmp_path / "HToBB" / "job_1" / "simulate-delphes").exists()


def _run_all(
    job: Job, mg5_path: Path, delphes_pythia8_path: Path, delphes_root_path: Path
) -> tuple[TaskRecord, TaskRecord, TaskRecord]:
    return (
        generate(job, n_events=10, mg5_path=mg5_path),
        shower(job, delphes_pythia8_path=delphes_pythia8_path),
        simulate(job, _delphes_simulator(job, delphes_root_path)),
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
    assert simulate(job, _delphes_simulator(job, delphes_root_path)) == simulated


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
    lhe_fingerprint = job.require_events(GENERATE_TASK).fingerprint
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
        simulate(job, _delphes_simulator(job, delphes_root_path))
    forced = simulate(job, _delphes_simulator(job, delphes_root_path), force=True)
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
    lhe_fingerprint = job.require_events(GENERATE_TASK).fingerprint
    accepted_record = shower(
        job, delphes_pythia8_path=delphes_pythia8_path, accept_input=True
    )
    assert accepted_record.accepted_input is not None
    assert accepted_record.accepted_input.fingerprint == lhe_fingerprint
    assert accepted_record.parameters == showered.parameters
    assert accepted_record.runs == showered.runs
    assert shower(job, delphes_pythia8_path=delphes_pythia8_path) == accepted_record
    assert simulate(job, _delphes_simulator(job, delphes_root_path)) == simulated
    assert (
        simulate(job, _delphes_simulator(job, delphes_root_path), accept_input=True)
        == simulated
    )
    with pytest.raises(ValueError, match="cannot both be set"):
        shower(job, accept_input=True, force=True)
    with pytest.raises(ValueError, match="cannot both be set"):
        simulate(job, DelphesSimulator(job.spec), accept_input=True, force=True)


def test_a_kept_stage_reads_no_event_file(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done = _run_all(job, mg5_path, delphes_pythia8_path, delphes_root_path)
    for stage in (GENERATE_TASK, SHOWER_TASK, SIMULATE_TASK):
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
    root_path = job.require_events(SHOWER_TASK).path
    recorded = root_path.stat().st_size
    root_path.write_bytes(root_path.read_bytes()[: recorded // 2])
    refused = re.escape(
        f"{root_path} holds {recorded // 2} bytes, not the {recorded} the "
        "shower-pythia task recorded; run omphjc shower with --force to "
        "regenerate the file"
    )
    with pytest.raises(ValueError, match=refused):
        shower(job, delphes_pythia8_path=delphes_pythia8_path)
    with pytest.raises(ValueError, match=refused):
        simulate(job, _delphes_simulator(job, delphes_root_path))
    shower(job, delphes_pythia8_path=delphes_pythia8_path, force=True)
    assert simulate(job, _delphes_simulator(job, delphes_root_path)).is_done


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
    record = simulate(job, _delphes_simulator(job, delphes_root_path))
    assert record.is_done
    assert record.parameters["seed"] == job.seed
    assert (
        record.parameters["input_fingerprint"]
        == showered.result.outputs[EVENTS_OUTPUT].fingerprint
    )
    assert len(record.parameters["card"]) == 64
    card_path = job.root_dir / "simulate-delphes" / "delphes_card.tcl"
    assert record.cards == {"detector_card": DetectorCard.record_file(card_path)}
    card_names = {card_class.card_name for card_class in DelphesSimulator.card_classes}
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
    log = _task(job, SIMULATE_TASK).log_path(record.latest_run.run_id).read_text()
    assert f"** Reading {job.root_dir / 'shower-pythia' / 'particles.root'}" in log

    reopened_job = Job(specs["HToBB"], tmp_path, 1)
    assert (
        simulate(reopened_job, _delphes_simulator(reopened_job, delphes_root_path))
        == record
    )
    other = tmp_path / "other.tcl"
    other.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    with pytest.raises(ValueError, match="card: expected "):
        simulate(
            job, _delphes_simulator(job, delphes_root_path, detector_card_path=other)
        )
    forced = simulate(
        job,
        _delphes_simulator(job, delphes_root_path, detector_card_path=other),
        force=True,
    )
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
    generate(job, n_events=10, mg5_path=mg5_path)
    shower(job, delphes_pythia8_path=delphes_pythia8_path)
    showered = job.require_events(SHOWER_TASK)
    # The fake DelphesROOT copies its input, so the simulated file holds three
    # events while the shower stage recorded one.
    pids = ak.Array([[2212, 211], [2212], [211, 211, 22]])
    write_delphes_file(showered.path, {"PID": pids}, omit=omit)
    # The shower stage is recorded with the size of the file put in its place.
    record = job.task_record(SHOWER_TASK)
    assert record is not None
    record.result.outputs[EVENTS_OUTPUT] = replace(
        showered, n_bytes=showered.path.stat().st_size
    )
    record.write(job.task_record_path(SHOWER_TASK), root_dir=job.root_dir)
    simulate(job, _delphes_simulator(job, delphes_root_path))
    assert showered.n_events == 1
    assert job.require_events(SIMULATE_TASK).n_events == 3


def test_a_forced_rerun_of_each_program_leaves_the_record_of_its_task(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    runs = {
        GENERATE_TASK: lambda force: generate(
            job, n_events=10, force=force, mg5_path=mg5_path
        ),
        SHOWER_TASK: lambda force: shower(
            job, force=force, delphes_pythia8_path=delphes_pythia8_path
        ),
        SIMULATE_TASK: lambda force: simulate(
            job, _delphes_simulator(job, delphes_root_path), force=force
        ),
    }
    for stage, run in runs.items():
        run(False)
        record = run(True)
        assert record.latest_run.set_aside is None
        assert job.task_record(stage) == record
        stamp = read_stamp(job.task_dir(stage))
        assert stamp is not None and "task.json" not in stamp.artifacts
