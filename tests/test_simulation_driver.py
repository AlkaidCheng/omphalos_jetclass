from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.delphes import (
    SimulationError,
    SimulationWorkspace,
    detector_card_text,
    reference_card_text,
    simulate_events,
)
from omphjc.processes import ProcessSpec
from omphjc.stamps import read_stamp

ARTIFACTS = {"delphes_card.tcl", "delphes.root", "simulate.log"}


def _write_events_file(path: Path) -> Path:
    path.write_bytes(b"ROOT fake")
    return path


def test_a_simulation_runs_in_its_own_working_directory(
    specs: Mapping[str, ProcessSpec], delphes_root: Path, tmp_path: Path
) -> None:
    events_file = _write_events_file(tmp_path / "particles.root")
    workdir = tmp_path / "simulate"
    run = simulate_events(
        specs["HToBB"],
        events_file=events_file,
        workdir=workdir,
        seed=7,
        delphes_root=delphes_root,
    )
    assert run.output == workdir / "delphes.root" and run.output.is_file()
    card = run.card.read_text()
    assert card.startswith("set RandomSeed 7\n")
    assert card.endswith(reference_card_text())
    assert run.log_file == workdir / "simulate.log"
    log = run.log_file.read_text()
    assert log.count("$ ") == 1 and f"** Reading {events_file}" in log
    assert run.set_aside is None
    stamp = read_stamp(workdir)
    assert stamp is not None and stamp.purpose == "delphes-simulation"
    assert stamp.details == {"process": "HToBB"}
    assert set(stamp.artifacts) == ARTIFACTS


def test_another_card_can_be_run_and_no_seed_leaves_it_alone(
    specs: Mapping[str, ProcessSpec], delphes_root: Path, tmp_path: Path
) -> None:
    events_file = _write_events_file(tmp_path / "particles.root")
    card = tmp_path / "mine.tcl"
    card.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    run = simulate_events(
        specs["HToBB"],
        events_file=events_file,
        workdir=tmp_path / "simulate",
        seed=None,
        card=card,
        delphes_root=delphes_root,
    )
    assert run.card.read_text() == card.read_text()
    assert detector_card_text(specs["HToBB"], card) == card.read_text()
    assert detector_card_text(specs["HToBB"]) == reference_card_text()
    with pytest.raises(FileNotFoundError, match="Delphes card"):
        detector_card_text(specs["HToBB"], tmp_path / "missing.tcl")


def test_an_existing_output_is_kept_by_default_and_replaced_on_request(
    specs: Mapping[str, ProcessSpec], delphes_root: Path, tmp_path: Path
) -> None:
    events_file = _write_events_file(tmp_path / "particles.root")
    arguments = dict(events_file=events_file, workdir=tmp_path / "simulate", seed=1)
    first = simulate_events(specs["HToBB"], delphes_root=delphes_root, **arguments)
    with pytest.raises(FileExistsError, match="already exists"):
        simulate_events(specs["HToBB"], delphes_root=delphes_root, **arguments)
    assert first.output.is_file()
    again = simulate_events(
        specs["HToBB"], delphes_root=delphes_root, overwrite=True, **arguments
    )
    assert again.output.is_file()
    assert again.log_file.read_text().count("$ ") == 1
    assert again.set_aside is None


def test_a_failing_exit_status_raises_and_seals_the_log(
    specs: Mapping[str, ProcessSpec],
    delphes_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_file = _write_events_file(tmp_path / "particles.root")
    monkeypatch.setenv("FAKE_DROOT_FAIL", "exit")
    with pytest.raises(SimulationError, match="DelphesROOT failed: .* status 1"):
        simulate_events(
            specs["HToBB"],
            events_file=events_file,
            workdir=tmp_path / "simulate",
            seed=1,
            delphes_root=delphes_root,
        )
    stamp = read_stamp(tmp_path / "simulate")
    assert stamp is not None and "simulate.log" in stamp.artifacts


def test_a_run_past_its_time_limit_is_stopped(
    specs: Mapping[str, ProcessSpec],
    delphes_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_file = _write_events_file(tmp_path / "particles.root")
    monkeypatch.setenv("FAKE_DROOT_FAIL", "hang")
    with pytest.raises(SimulationError, match="time limit"):
        simulate_events(
            specs["HToBB"],
            events_file=events_file,
            workdir=tmp_path / "simulate",
            seed=1,
            timeout=0.5,
            delphes_root=delphes_root,
        )


def test_invalid_requests_fail_before_anything_runs(
    specs: Mapping[str, ProcessSpec], delphes_root: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "simulate"
    with pytest.raises(FileNotFoundError, match="Showered events"):
        simulate_events(
            specs["HToBB"],
            events_file=tmp_path / "missing.root",
            workdir=workdir,
            seed=1,
            delphes_root=delphes_root,
        )
    assert not workdir.exists()
    events_file = _write_events_file(tmp_path / "particles.root")
    first = simulate_events(
        specs["HToBB"],
        events_file=events_file,
        workdir=workdir,
        seed=1,
        delphes_root=delphes_root,
    )
    log_before = first.log_file.read_text()
    with pytest.raises(FileNotFoundError, match="Delphes card"):
        simulate_events(
            specs["HToBB"],
            events_file=events_file,
            workdir=workdir,
            seed=1,
            card=tmp_path / "missing.tcl",
            overwrite=True,
            delphes_root=delphes_root,
        )
    assert first.output.is_file() and first.log_file.read_text() == log_before


def test_a_workspace_finds_delphes_root_on_path_or_takes_the_given_one(
    specs: Mapping[str, ProcessSpec],
    delphes_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = specs["HToBB"]
    workspace = SimulationWorkspace(spec, tmp_path, delphes_root=delphes_root)
    assert workspace.program_path == delphes_root
    assert workspace.output == tmp_path.resolve() / "delphes.root"
    monkeypatch.setenv("PATH", str(delphes_root.parent))
    assert SimulationWorkspace(spec, tmp_path).program_path == delphes_root
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="not on PATH"):
        SimulationWorkspace(spec, tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        SimulationWorkspace(spec, tmp_path, delphes_root=tmp_path / "missing")
