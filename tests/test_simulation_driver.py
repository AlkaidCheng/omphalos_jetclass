from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.delphes import (
    SimulationWorkspace,
    detector_card_text,
    reference_card_text,
    simulate_events,
)
from omphjc.processes import ProcessSpec
from omphjc.stamps import read_stamp

ARTIFACTS = {"delphes_card.tcl", "delphes.root", "simulate.log"}


def _write_events_path(path: Path) -> Path:
    path.write_bytes(b"ROOT fake")
    return path


def test_a_simulation_runs_in_its_own_working_directory(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    events_path = _write_events_path(tmp_path / "particles.root")
    workdir = tmp_path / "simulate"
    run = simulate_events(
        specs["HToBB"],
        events_path=events_path,
        workdir=workdir,
        seed=7,
        delphes_root_path=delphes_root_path,
    )
    assert run.output_path == workdir / "delphes.root" and run.output_path.is_file()
    card = run.card_path.read_text()
    assert card.startswith("set RandomSeed 7\n")
    assert card.endswith(reference_card_text())
    assert run.log_path == workdir / "simulate.log"
    log = run.log_path.read_text()
    assert log.count("$ ") == 1 and f"** Reading {events_path}" in log
    assert run.set_aside is None
    stamp = read_stamp(workdir)
    assert stamp is not None and stamp.purpose == "delphes-simulation"
    assert stamp.details == {"process": "HToBB"}
    assert set(stamp.artifacts) == ARTIFACTS


def test_another_card_can_be_run_and_no_seed_leaves_it_alone(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    events_path = _write_events_path(tmp_path / "particles.root")
    card = tmp_path / "mine.tcl"
    card.write_text("set ExecutionPath {\n  TreeWriter\n}\n")
    run = simulate_events(
        specs["HToBB"],
        events_path=events_path,
        workdir=tmp_path / "simulate",
        seed=None,
        card_path=card,
        delphes_root_path=delphes_root_path,
    )
    assert run.card_path.read_text() == card.read_text()
    assert detector_card_text(specs["HToBB"], card) == card.read_text()
    assert detector_card_text(specs["HToBB"]) == reference_card_text()
    with pytest.raises(FileNotFoundError, match="Delphes card"):
        detector_card_text(specs["HToBB"], tmp_path / "missing.tcl")


def test_missing_showered_events_fail_before_anything_runs(
    specs: Mapping[str, ProcessSpec], delphes_root_path: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "simulate"
    with pytest.raises(FileNotFoundError, match="Showered events"):
        simulate_events(
            specs["HToBB"],
            events_path=tmp_path / "missing.root",
            workdir=workdir,
            seed=1,
            delphes_root_path=delphes_root_path,
        )
    assert not workdir.exists()


def test_a_workspace_finds_delphes_root_on_path_or_takes_the_given_one(
    specs: Mapping[str, ProcessSpec],
    delphes_root_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = specs["HToBB"]
    workspace = SimulationWorkspace(spec, tmp_path, delphes_root_path=delphes_root_path)
    assert workspace.program_path == delphes_root_path
    assert workspace.output_path == tmp_path.resolve() / "delphes.root"
    monkeypatch.setenv("PATH", str(delphes_root_path.parent))
    assert SimulationWorkspace(spec, tmp_path).program_path == delphes_root_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="not on PATH"):
        SimulationWorkspace(spec, tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        SimulationWorkspace(spec, tmp_path, delphes_root_path=tmp_path / "missing")
