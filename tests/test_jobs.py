import hashlib
import json
import os
import re
import shutil
import signal
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import awkward as ak
import pytest
from delphes_records import write_delphes_file

from omphjc import __version__
from omphjc.comparison import Difference
from omphjc.events import EventFormat
from omphjc.events.delphes_root import DelphesROOTFile
from omphjc.jobs import (
    EVENTS_OUTPUT,
    EventOutput,
    Job,
    JobIdentity,
    Manifest,
    Task,
    TaskOutcome,
    TaskOutput,
    TaskRecord,
    TaskResult,
    TaskStatus,
    TaskSummary,
    TerminationError,
    exception_on_termination,
    generate,
    job_seed,
    shower,
    simulate,
)
from omphjc.processes import ProcessSpec, get_process
from omphjc.programs import available_cores
from omphjc.stamps import read_stamp
from omphjc.tools.madgraph.driver import MadGraphError
from omphjc.tools.madgraph.lhe_file import LHEFile
from omphjc.tools.pythia.cmnd import PYTHIA_SEED_LIMIT


def test_job_seed_is_the_process_offset_plus_the_job_number() -> None:
    assert job_seed(get_process("HToBB"), 7) == 10000007
    assert job_seed(get_process("HToCC"), 7) == 20000007
    assert job_seed(get_process("TTBar"), 1) == 1
    with pytest.raises(ValueError, match="job_id"):
        job_seed(get_process("HToBB"), 0)
    with pytest.raises(ValueError, match="limit"):
        job_seed(get_process("HToBB"), PYTHIA_SEED_LIMIT)


def test_a_job_has_a_directory_per_process_and_number(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path / "runs", 7)
    assert job.root_dir == (tmp_path / "runs").resolve() / "HToBB" / "job_7"
    assert job.manifest_path == job.root_dir / "manifest.json"
    assert job.task_dir("generate") == job.root_dir / "generate"
    assert job.relative_path(job.root_dir / "generate" / "x.log") == "generate/x.log"
    assert job.seed == 10000007
    assert job.identity_path == job.root_dir / "job.json"
    assert job.identity == JobIdentity(process="HToBB", job_id=7, seed=10000007)
    assert job.task_record_path("generate") == job.root_dir / "generate" / "task.json"
    assert job.task_record("generate") is None
    assert job.task_names() == []
    assert not job.root_dir.exists()
    with pytest.raises(ValueError, match="job_id"):
        Job(specs["HToBB"], tmp_path, 0)
    with pytest.raises(ValueError, match="filesystem root"):
        Job(specs["HToBB"], Path("/"), 1)


def test_a_task_record_round_trips_through_json(tmp_path: Path) -> None:
    output_path = tmp_path / "x" / "out"
    record = TaskRecord(
        status="done",
        started="t",
        parameters={"events": 10},
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
            metadata={"cards": {"x/c.dat": "abc"}},
        ),
    )
    path = tmp_path / "x" / "task.json"
    path.parent.mkdir()
    record.write(path, root_dir=tmp_path)
    written = json.loads(path.read_text())
    assert written["schema"] == 1
    assert written["status"] == "done" and written["parameters"] == {"events": 10}
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
        "metadata": {"cards": {"x/c.dat": "abc"}},
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


def test_a_task_record_refuses_a_path_outside_its_root_directory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "job" / "x" / "task.json"
    path.parent.mkdir(parents=True)
    record = TaskRecord(
        status="done",
        started="t",
        result=TaskResult(
            outputs={"out": TaskOutput(tmp_path / "elsewhere" / "out", n_bytes=0)}
        ),
    )
    with pytest.raises(ValueError, match="elsewhere"):
        record.write(path, root_dir=tmp_path / "job")
    assert list(path.parent.iterdir()) == []


def test_a_manifest_round_trips_through_json(tmp_path: Path) -> None:
    manifest = Manifest(
        JobIdentity(process="HToBB", job_id=1, seed=10000001),
        {
            "x": TaskSummary("done", "t", tmp_path / "x" / "task.json"),
            "y": TaskSummary("running", "u", tmp_path / "y" / "task.json"),
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
            "x": {"status": "done", "started": "t", "record_path": "x/task.json"},
            "y": {"status": "running", "started": "u", "record_path": "y/task.json"},
        },
    }
    assert Manifest.read(path) == manifest


def _make_output(job: Job) -> TaskOutcome:
    directory = job.task_dir("x")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "out.txt"
    output.write_text("made")
    return TaskOutcome(
        TaskResult(
            outputs={"out": TaskOutput(output, n_bytes=len("made"))},
            metadata={"n": 1},
        )
    )


def test_a_stage_runs_once_and_its_result_is_kept(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_task("x", {"events": 10}, body)
    assert calls == [False]
    assert record.status == "done" and record.finished is not None
    assert record.parameters == {"events": 10}
    assert record.result == TaskResult(
        outputs={"out": TaskOutput(job.root_dir / "x" / "out.txt", n_bytes=4)},
        metadata={"n": 1},
    )
    assert record.log is None
    assert job.task_record("x") == record

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task("x") == Task("x", TaskStatus.DONE, record=record)
    assert job.run_task("x", {"events": 10}, body) == record
    assert calls == [False]


def test_other_parameters_need_force_and_force_replaces(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task("x", {"events": 10}, body)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="ran with {'events': 10}"):
        job.run_task("x", {"events": 20}, body)
    forced = job.run_task("x", {"events": 20}, body, force=True)
    assert forced.parameters == {"events": 20}
    assert calls == [False, True]


def test_a_stage_with_missing_outputs_or_left_running_runs_again(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task("x") == Task("x", TaskStatus.NOT_DONE)
    record = job.run_task("x", {}, body)
    output_path = job.root_dir / "x" / "out.txt"
    output_path.unlink()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task("x") == Task(
        "x", TaskStatus.MISSING_OUTPUT, f"{output_path} is missing", record
    )
    job.run_task("x", {}, body)
    assert calls == [False, True]

    running = TaskRecord(status="running", started="t")
    running.write(job.task_record_path("x"), root_dir=job.root_dir)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task("x") == Task("x", TaskStatus.NOT_DONE, record=running)
    assert job.run_task("x", {}, body).status == "done"
    assert calls == [False, True, True]


def test_require_done_returns_the_record_or_says_which_stage_to_run(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    not_done = "The x stage of .* has not run to completion; run omphjc x first"
    with pytest.raises(ValueError, match=not_done):
        job.require_done("x")
    record = job.run_task("x", {}, lambda overwrite: _make_output(job))
    assert job.require_done("x") == record
    (job.root_dir / "x" / "out.txt").unlink()
    with pytest.raises(ValueError, match=not_done):
        job.require_done("x")


def test_a_stage_whose_output_has_another_size_is_refused_unless_forced(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_task("x", {}, body)
    output_path = job.root_dir / "x" / "out.txt"
    output_path.write_text("made and changed")
    job = Job(specs["HToBB"], tmp_path, 1)
    detail = f"{output_path} holds 16 bytes, not the 4 the x stage recorded"
    assert job.task("x") == Task("x", TaskStatus.CHANGED, detail, record)
    refused = re.escape(f"{detail}; run omphjc x with --force to regenerate the file")
    with pytest.raises(ValueError, match=refused):
        job.require_done("x")
    with pytest.raises(ValueError, match=refused):
        job.run_task("x", {}, body)
    assert calls == [False]
    assert job.run_task("x", {}, body, force=True).status == "done"
    assert calls == [False, True]
    assert job.require_done("x").result.outputs["out"].n_bytes == 4


def test_an_output_of_another_size_is_reported_before_a_missing_one(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    first_path = job.task_dir("x") / "first.txt"
    second_path = job.task_dir("x") / "second.txt"

    def body(overwrite: bool) -> TaskOutcome:
        job.task_dir("x").mkdir(parents=True, exist_ok=True)
        outputs = {}
        for name, path in (("first", first_path), ("second", second_path)):
            path.write_text("made")
            outputs[name] = TaskOutput(path, n_bytes=len("made"))
        return TaskOutcome(TaskResult(outputs=outputs))

    record = job.run_task("x", {}, body)
    first_path.unlink()
    second_path.write_text("made and changed")
    assert job.task("x") == Task(
        "x",
        TaskStatus.CHANGED,
        f"{second_path} holds 16 bytes, not the 4 the x stage recorded",
        record,
    )
    with pytest.raises(ValueError, match="with --force to regenerate the file"):
        job.run_task("x", {}, body)


def test_require_events_returns_the_events_a_done_stage_made(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="has not run to completion"):
        job.require_events("x")
    job.run_task("x", {}, lambda overwrite: _make_output(job))
    with pytest.raises(ValueError, match="The x stage of .* made no event file"):
        job.require_events("x")

    events = EventOutput(
        job.task_dir("x") / "out.txt",
        n_bytes=len("made"),
        format=EventFormat.LHE,
        n_events=3,
        fingerprint="lhe-v1:abc",
    )
    job.run_task(
        "x",
        {},
        lambda overwrite: TaskOutcome(TaskResult(outputs={EVENTS_OUTPUT: events})),
        force=True,
    )
    assert Job(specs["HToBB"], tmp_path, 1).require_events("x") == events


def test_a_failed_stage_is_recorded_raised_and_replaced_on_retry(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task("x", {"events": 10}, failing)
    record = job.task_record("x")
    assert record is not None
    assert record.status == "failed" and record.finished is not None
    assert record.parameters == {"events": 10} and record.error == "boom"

    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.run_task("x", {"events": 10}, body).status == "done"
    assert calls == [True]


def test_two_jobs_opened_on_one_directory_keep_the_records_of_both_tasks(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    first = Job(specs["HToBB"], tmp_path, 1)
    second = Job(specs["HToBB"], tmp_path, 1)
    x_record = first.run_task("x", {}, lambda overwrite: _make_output(first))
    y_record = second.run_task("y", {}, lambda overwrite: TaskOutcome(TaskResult()))
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.task_names() == ["x", "y"]
    assert job.task_record("x") == x_record
    assert job.task_record("y") == y_record
    assert set(Manifest.read(job.manifest_path).tasks) == {"x", "y"}


def test_the_manifest_lists_every_task_and_is_written_again_when_deleted(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool) -> TaskOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    x_record = job.run_task("x", {}, lambda overwrite: _make_output(job))
    with pytest.raises(RuntimeError, match="boom"):
        job.run_task("y", {}, failing)
    y_record = job.task_record("y")
    assert y_record is not None
    manifest = Manifest(
        job.identity,
        {
            "x": TaskSummary("done", x_record.started, job.task_record_path("x")),
            "y": TaskSummary("failed", y_record.started, job.task_record_path("y")),
        },
    )
    assert Manifest.read(job.manifest_path) == manifest

    job.manifest_path.unlink()
    assert job.run_task("x", {}, lambda overwrite: _make_output(job)) == x_record
    assert not job.manifest_path.exists()
    z_record = job.run_task("z", {}, lambda overwrite: TaskOutcome(TaskResult()))
    entry = TaskSummary("done", z_record.started, job.task_record_path("z"))
    assert Manifest.read(job.manifest_path) == Manifest(
        job.identity, {**manifest.tasks, "z": entry}
    )


def test_a_task_is_found_by_the_record_in_its_own_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task("x", {}, lambda overwrite: _make_output(job))
    record_path = job.task_record_path("x")
    deeper_dir = job.task_dir("x") / "deeper"
    deeper_dir.mkdir()
    shutil.copy(record_path, deeper_dir / "task.json")
    shutil.copy(record_path, job.root_dir / "task.json")
    (job.root_dir / "empty").mkdir()
    assert job.task_names() == ["x"]


def test_a_task_record_that_cannot_be_read_stops_every_task_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> TaskOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task("x", {}, body)
    record_path = job.task_record_path("x")
    record_path.write_text("{")
    unreadable = re.escape(f"{record_path} is not valid JSON")
    with pytest.raises(ValueError, match=unreadable):
        job.task("x")
    with pytest.raises(ValueError, match=unreadable):
        job.run_task("x", {}, body, force=True)
    with pytest.raises(ValueError, match=unreadable):
        job.run_task("y", {}, body)
    assert calls == [False]
    assert job.set_aside_folders() == []


def test_the_first_task_writes_the_identity_of_the_job(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_task("x", {}, lambda overwrite: _make_output(job))
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
    record = later.run_task("x", {}, lambda overwrite: _make_output(later))
    assert record.status == "done"
    assert JobIdentity.read(job.identity_path).omphjc_version == "0.0.1"


def test_a_directory_of_another_job_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    shifted = Job(replace(specs["HToBB"], seed_offset=20_000_000), tmp_path, 1)
    job.run_task("x", {}, lambda overwrite: _make_output(job))
    refusal = (
        "The current configuration is inconsistent with that of the existing"
        " job in .*job_1 \\(job.json\\):"
        "\n  seed: expected 10000001, got 20000001"
        "\nRerun with the configuration the job was created with, or choose"
        " another output directory.$"
    )
    calls = []
    with pytest.raises(ValueError, match=refusal):
        shifted.run_task("y", {}, calls.append, force=True)
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

    def remove_then_finish(overwrite: bool) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        return _make_output(job)

    with pytest.raises(
        FileNotFoundError, match="job.json was removed while the x task ran"
    ):
        job.run_task("x", {}, remove_then_finish)
    assert not job.identity_path.exists()
    assert not job.manifest_path.exists()

    def remove_then_fail(overwrite: bool) -> TaskOutcome:
        shutil.rmtree(job.root_dir)
        raise RuntimeError("the program stopped")

    with pytest.raises(FileNotFoundError, match="is not recorded") as failure:
        Job(specs["HToBB"], tmp_path, 1).run_task("x", {}, remove_then_fail)
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
        job.run_task("x", {}, lambda overwrite: _make_output(job))


def test_generate_records_what_madgraph_made(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["TTBar"], tmp_path, 3)
    record = generate(job, n_events=10, mg5_path=mg5_path)
    assert job.task_record("generate") == record
    assert record.status == "done"
    assert record.parameters == {"events": 10, "seed": 3}
    metadata = record.result.metadata
    assert metadata["madgraph_version"] == "3.5.7"
    assert metadata["cross_section_pb"] == pytest.approx(1.052824254921272)
    assert metadata["cross_section_error_pb"] == pytest.approx(2.3983749989e-3)
    assert record.usage["wall_seconds"] > 0
    assert record.usage["cpu_seconds"] >= 0 and record.usage["peak_memory_mib"] > 0
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
    assert record.log == "generate/madgraph.log"
    card = job.root_dir / "generate" / "cards" / "proc_card_mg5.dat"
    assert card.is_file()
    assert metadata["cards"]["generate/cards/proc_card_mg5.dat"] == (
        hashlib.sha256(card.read_bytes()).hexdigest()
    )
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
    log = tmp_path / "HToBB" / "job_1" / "generate" / "madgraph.log"
    runs = log.read_text().count("$ ")
    assert (
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
        == first
    )
    assert log.read_text().count("$ ") == runs
    with pytest.raises(ValueError, match="ran with"):
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=20, mg5_path=mg5_path)
    shifted = replace(specs["HToBB"], seed_offset=20_000_000)
    with pytest.raises(ValueError, match="seed: expected 10000001, got 20000001"):
        generate(Job(shifted, tmp_path, 1), n_events=10, mg5_path=mg5_path)
    again = generate(
        Job(specs["HToBB"], tmp_path, 1), n_events=20, mg5_path=mg5_path, force=True
    )
    assert again.status == "done"
    assert again.parameters == {"events": 20, "seed": 10000001}
    assert log.read_text().count("$ ") == runs


def test_a_failed_madgraph_run_is_recorded_and_retried(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", "launch")
    with pytest.raises(MadGraphError):
        generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    record = Job(specs["HToBB"], tmp_path, 1).task_record("generate")
    assert record is not None
    assert record.status == "failed" and record.finished is not None
    assert record.error is not None and "launch.mg5" in record.error
    monkeypatch.delenv("FAKE_MG5_FAIL")
    done = generate(Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path)
    assert done.status == "done"


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
    assert job.task_record("shower") == record
    assert record.status == "done"
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
    assert set(metadata["settings"]) == {
        "shower/pythia.cmnd",
        "shower/particles_card.tcl",
    }
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
    assert record.log == "shower/shower.log"
    cmnd = (job.root_dir / "shower" / "pythia.cmnd").read_text()
    assert "Random:seed = 10000001" in cmnd and "Main:numberOfEvents = 10000" in cmnd
    card = (job.root_dir / "shower" / "particles_card.tcl").read_text()
    assert "TreeWriter" in card and "RandomSeed" not in card

    kept = shower(
        Job(specs["HToBB"], tmp_path, 1), delphes_pythia8_path=delphes_pythia8_path
    )
    assert kept == record
    overrides = {"Main:timesAllowErrors": 5}
    with pytest.raises(ValueError, match="ran with"):
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

    def body(overwrite: bool) -> TaskOutcome:
        aside = job.task_dir("x") / "omphjc-set-aside" / "20260101T000000Z-abc"
        aside.mkdir(parents=True)
        return replace(_make_output(job), set_aside_dir=aside)

    record = job.run_task("x", {"events": 10}, body)
    assert record.set_aside == "x/omphjc-set-aside/20260101T000000Z-abc"
    assert job.task_record("x") == record


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
    assert record.set_aside is not None
    assert record.set_aside.startswith("generate/omphjc-set-aside/")
    folders = job.set_aside_folders()
    assert [job.relative_path(folder.path) for folder in folders] == [record.set_aside]
    assert folders[0].size() > 0
    assert job.clear_set_aside_folders() == folders
    assert job.set_aside_folders() == []
    assert not (job.task_dir("generate") / "omphjc-set-aside").exists()
    assert job.task("generate").status is TaskStatus.DONE


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
    lhe_fingerprint = job.require_events("generate").fingerprint
    assert lhe_fingerprint != generated.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(ValueError, match="ran with .*'input_fingerprint': 'lhe-v1:"):
        shower(job, delphes_pythia8_path=delphes_pythia8_path)
    forced = shower(job, delphes_pythia8_path=delphes_pythia8_path, force=True)
    assert forced.parameters["input_fingerprint"] == lhe_fingerprint
    root_fingerprint = forced.result.outputs[EVENTS_OUTPUT].fingerprint
    assert root_fingerprint != showered.result.outputs[EVENTS_OUTPUT].fingerprint
    with pytest.raises(
        ValueError, match="ran with .*'input_fingerprint': 'delphes_root-v1:"
    ):
        simulate(job, delphes_root_path=delphes_root_path)
    forced = simulate(job, delphes_root_path=delphes_root_path, force=True)
    assert forced.parameters["input_fingerprint"] == root_fingerprint


def test_a_kept_stage_reads_no_event_file(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    done = _run_all(job, mg5_path, delphes_pythia8_path, delphes_root_path)
    for stage in ("generate", "shower", "simulate"):
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
    root_path = job.require_events("shower").path
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
    assert simulate(job, delphes_root_path=delphes_root_path).status == "done"


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
    assert record.status == "done"
    assert record.parameters["seed"] == job.seed
    assert (
        record.parameters["input_fingerprint"]
        == showered.result.outputs[EVENTS_OUTPUT].fingerprint
    )
    assert len(record.parameters["card"]) == 64
    assert list(record.result.metadata["card"]) == ["simulate/delphes_card.tcl"]
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
    assert record.log == "simulate/simulate.log"
    card = (job.root_dir / "simulate" / "delphes_card.tcl").read_text()
    assert card.endswith("\nset RandomSeed 10000001\n")
    log = (job.root_dir / "simulate" / "simulate.log").read_text()
    assert f"** Reading {job.root_dir / 'shower' / 'particles.root'}" in log

    kept = simulate(
        Job(specs["HToBB"], tmp_path, 1), delphes_root_path=delphes_root_path
    )
    assert kept == record
    other = tmp_path / "other.tcl"
    other.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    with pytest.raises(ValueError, match="ran with"):
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
    assert (
        forced.status == "done"
        and forced.parameters["card"] != record.parameters["card"]
    )
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
    showered = job.require_events("shower")
    # The fake DelphesROOT copies its input, so the simulated file holds three
    # events while the shower stage recorded one.
    pids = ak.Array([[2212, 211], [2212], [211, 211, 22]])
    write_delphes_file(showered.path, {"PID": pids}, omit=omit)
    # The shower stage is recorded with the size of the file put in its place.
    record = job.task_record("shower")
    assert record is not None
    record.result.outputs[EVENTS_OUTPUT] = replace(
        showered, n_bytes=showered.path.stat().st_size
    )
    record.write(job.task_record_path("shower"), root_dir=job.root_dir)
    simulate(job, delphes_root_path=delphes_root_path)
    assert showered.n_events == 1
    assert job.require_events("simulate").n_events == 3


def test_a_forced_rerun_of_each_program_leaves_the_record_of_its_task(
    specs: Mapping[str, ProcessSpec],
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    runs = {
        "generate": lambda force: generate(
            job, n_events=10, force=force, mg5_path=mg5_path
        ),
        "shower": lambda force: shower(
            job, force=force, delphes_pythia8_path=delphes_pythia8_path
        ),
        "simulate": lambda force: simulate(
            job, force=force, delphes_root_path=delphes_root_path
        ),
    }
    for stage, run in runs.items():
        run(False)
        record = run(True)
        assert record.set_aside is None
        assert job.task_record(stage) == record
        stamp = read_stamp(job.task_dir(stage))
        assert stamp is not None and "task.json" not in stamp.artifacts
