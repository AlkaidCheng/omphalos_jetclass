import hashlib
import json
import os
import signal
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from omphjc.jobs import (
    Job,
    Manifest,
    StageOutcome,
    StageRecord,
    TerminationError,
    exception_on_termination,
    generate,
    job_seed,
    shower,
    simulate,
)
from omphjc.madgraph import MadGraphError
from omphjc.processes import ProcessSpec, get_process
from omphjc.pythia import PYTHIA_SEED_LIMIT


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
    assert job.stage_dir("generate") == job.root_dir / "generate"
    assert job.relative_path(job.root_dir / "generate" / "x.log") == "generate/x.log"
    assert job.seed == 10000007
    assert job.manifest == Manifest(process="HToBB", job_id=7)
    assert not job.root_dir.exists()
    with pytest.raises(ValueError, match="job_id"):
        Job(specs["HToBB"], tmp_path, 0)
    with pytest.raises(ValueError, match="filesystem root"):
        Job(specs["HToBB"], Path("/"), 1)


def test_a_manifest_round_trips_through_json(tmp_path: Path) -> None:
    record = StageRecord(
        status="done",
        started="t",
        parameters={"events": 10},
        metadata={"events": 10, "cards": {"x/c.dat": "abc"}},
        outputs=["x/out"],
    )
    manifest = Manifest(process="HToBB", job_id=1, stages={"x": record})
    path = tmp_path / "manifest.json"
    manifest.write(path)
    assert json.loads(path.read_text())["schema"] == 1
    assert Manifest.read(path) == manifest
    path.write_text('{"schema": 99}')
    with pytest.raises(ValueError, match="schema 99; .* reads schema 1"):
        Manifest.read(path)
    path.write_text('{"process": "HToBB"}')
    with pytest.raises(ValueError, match="no schema"):
        Manifest.read(path)
    path.write_text("not json")
    with pytest.raises(ValueError, match="not a manifest"):
        Manifest.read(path)


def _make_output(job: Job) -> StageOutcome:
    directory = job.stage_dir("x")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "out.txt"
    output.write_text("made")
    return StageOutcome(metadata={"n": 1}, outputs=[output])


def test_a_stage_runs_once_and_its_result_is_kept(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> StageOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    record = job.run_stage("x", {"events": 10}, body)
    assert calls == [False]
    assert record.status == "done" and record.finished is not None
    assert record.parameters == {"events": 10}
    assert record.metadata == {"n": 1}
    assert record.outputs == ["x/out.txt"] and record.log is None
    assert Manifest.read(job.manifest_path).stages["x"] == record

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.is_done("x")
    assert job.run_stage("x", {"events": 10}, body) == record
    assert calls == [False]


def test_other_parameters_need_force_and_force_replaces(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> StageOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_stage("x", {"events": 10}, body)
    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(ValueError, match="ran with {'events': 10}"):
        job.run_stage("x", {"events": 20}, body)
    forced = job.run_stage("x", {"events": 20}, body, force=True)
    assert forced.parameters == {"events": 20}
    assert calls == [False, True]


def test_a_stage_with_missing_outputs_or_left_running_runs_again(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    calls: list[bool] = []

    def body(overwrite: bool) -> StageOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    job.run_stage("x", {}, body)
    (job.root_dir / "x" / "out.txt").unlink()
    job = Job(specs["HToBB"], tmp_path, 1)
    assert not job.is_done("x")
    job.run_stage("x", {}, body)
    assert calls == [False, True]

    job.manifest.stages["x"] = StageRecord(status="running", started="t")
    job.manifest.write(job.manifest_path)
    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.run_stage("x", {}, body).status == "done"
    assert calls == [False, True, True]


def test_a_failed_stage_is_recorded_raised_and_replaced_on_retry(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    def failing(overwrite: bool) -> StageOutcome:
        raise RuntimeError("boom")

    job = Job(specs["HToBB"], tmp_path, 1)
    with pytest.raises(RuntimeError, match="boom"):
        job.run_stage("x", {"events": 10}, failing)
    record = Manifest.read(job.manifest_path).stages["x"]
    assert record.status == "failed" and record.finished is not None
    assert record.parameters == {"events": 10} and record.error == "boom"

    calls: list[bool] = []

    def body(overwrite: bool) -> StageOutcome:
        calls.append(overwrite)
        return _make_output(job)

    job = Job(specs["HToBB"], tmp_path, 1)
    assert job.run_stage("x", {"events": 10}, body).status == "done"
    assert calls == [True]


def test_a_manifest_of_another_job_is_refused(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    job = Job(specs["HToBB"], tmp_path, 1)
    job.root_dir.mkdir(parents=True)
    Manifest(process="HToGG", job_id=1).write(job.manifest_path)
    with pytest.raises(ValueError, match="belongs to HToGG job 1"):
        Job(specs["HToBB"], tmp_path, 1)


def test_generate_records_what_madgraph_made(
    specs: Mapping[str, ProcessSpec], mg5_path: Path, tmp_path: Path
) -> None:
    job = Job(specs["TTBar"], tmp_path, 3)
    record = generate(job, n_events=10, mg5_path=mg5_path)
    assert Manifest.read(job.manifest_path).stages["generate"] == record
    assert record.status == "done"
    assert record.parameters == {"events": 10, "seed": 3}
    assert record.metadata["madgraph_version"] == "3.5.7"
    assert record.metadata["events"] == 10000
    assert record.metadata["cross_section_pb"] == pytest.approx(1.052824254921272)
    assert record.metadata["cross_section_error_pb"] == pytest.approx(2.3983749989e-3)
    assert record.usage["wall_seconds"] > 0
    assert record.usage["cpu_seconds"] >= 0 and record.usage["peak_memory_mib"] > 0
    assert record.outputs == [
        "generate/TTBar/Events/run_01_decayed_1/unweighted_events.lhe.gz"
    ]
    assert (job.root_dir / record.outputs[0]).is_file()
    assert record.log == "generate/madgraph.log"
    card = job.root_dir / "generate" / "cards" / "proc_card_mg5.dat"
    assert card.is_file()
    assert record.metadata["cards"]["generate/cards/proc_card_mg5.dat"] == (
        hashlib.sha256(card.read_bytes()).hexdigest()
    )
    assert (card.parent / "madspin_card.dat").is_file()
    assert "set iseed 3" in (job.root_dir / "generate" / "launch.mg5").read_text()


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
    with pytest.raises(ValueError, match="'seed': 10000001.*'seed': 20000001"):
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
    manifest = Manifest.read(tmp_path / "HToBB" / "job_1" / "manifest.json")
    record = manifest.stages["generate"]
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
    assert Manifest.read(job.manifest_path).stages["shower"] == record
    assert record.status == "done"
    assert record.parameters == {
        "events": 10000,
        "seed": 10000001,
        "pythia": {},
        "generated_with": generated.metadata["cards"],
    }
    assert record.metadata["pythia_version"] == "8.318"
    assert record.metadata["events_read"] == 1
    assert record.metadata["events_accepted"] == 1
    assert "matching_efficiency" not in record.metadata
    assert set(record.metadata["settings"]) == {
        "shower/pythia.cmnd",
        "shower/particles_card.tcl",
    }
    assert record.outputs == ["shower/particles.root"]
    assert (job.root_dir / "shower" / "particles.root").is_file()
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

    generate(
        Job(specs["HToBB"], tmp_path, 1), n_events=10, mg5_path=mg5_path, force=True
    )
    regenerated = shower(
        Job(specs["HToBB"], tmp_path, 1),
        overrides=overrides,
        delphes_pythia8_path=delphes_pythia8_path,
    )
    assert regenerated == forced


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
    assert record.metadata["matching_efficiency"] == 1.0
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

    def body(overwrite: bool) -> StageOutcome:
        aside = job.stage_dir("x") / "omphjc-set-aside" / "20260101T000000Z-abc"
        aside.mkdir(parents=True)
        return replace(_make_output(job), set_aside=aside)

    record = job.run_stage("x", {"events": 10}, body)
    assert record.set_aside == "x/omphjc-set-aside/20260101T000000Z-abc"
    assert Manifest.read(job.manifest_path).stages["x"].set_aside == record.set_aside


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
    assert not (job.stage_dir("generate") / "omphjc-set-aside").exists()
    assert job.is_done("generate")


def test_simulate_needs_a_finished_shower_stage(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="run omphjc shower first"):
        simulate(Job(specs["HToBB"], tmp_path, 1), delphes_root_path=delphes_root_path)
    assert not (tmp_path / "HToBB" / "job_1" / "simulate").exists()


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
    assert record.parameters["showered_with"] == showered.metadata["settings"]
    assert len(record.parameters["card"]) == 64
    assert record.metadata["events"] == showered.metadata["events_accepted"]
    assert list(record.metadata["card"]) == ["simulate/delphes_card.tcl"]
    assert record.outputs == ["simulate/delphes.root"]
    assert (job.root_dir / "simulate" / "delphes.root").is_file()
    assert record.log == "simulate/simulate.log"
    card = (job.root_dir / "simulate" / "delphes_card.tcl").read_text()
    assert card.startswith("set RandomSeed 10000001\n")
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
        .endswith(other.read_text())
    )
