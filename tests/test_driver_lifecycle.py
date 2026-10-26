"""The run lifecycle every driver follows, checked on MadGraph, Pythia and Delphes.

A drive function refuses an occupied output unless asked to overwrite it,
replaces an earlier run it can confirm, seals what a failed run left, sets
aside what a run killed before sealing left, and checks a request before it
touches an earlier run.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import pytest

import omphjc.workspace as workspace
from omphjc.delphes import SimulationWorkspace, simulate_events
from omphjc.madgraph import MadGraphWorkspace, generate_events
from omphjc.processes import ProcessSpec
from omphjc.pythia import ShowerWorkspace, shower_events
from omphjc.stamps import read_stamp
from omphjc.workspace import ProgramRun, ProgramWorkspace


@dataclass(frozen=True)
class Driver:
    """A drive function with its fake program and inputs, and what it writes."""

    workspace_type: type[ProgramWorkspace]
    run: Callable[..., ProgramRun]
    fail_variable: str
    failure: str
    occupied: str
    seed_path: str
    seed_line: str
    invalid: Mapping[str, Any]
    invalid_error: type[Exception]
    invalid_match: str


def _madgraph(
    request: pytest.FixtureRequest, spec: ProcessSpec, tmp_path: Path
) -> Driver:
    return Driver(
        workspace_type=MadGraphWorkspace,
        run=partial(
            generate_events,
            spec,
            n_events=10,
            mg5_path=request.getfixturevalue("mg5_path"),
        ),
        fail_variable="FAKE_MG5_FAIL",
        failure="MadGraph failed running process.mg5: mg5_aMC",
        occupied="Process directory",
        seed_path="launch.mg5",
        seed_line="set iseed {}",
        invalid={"n_events": 0},
        invalid_error=ValueError,
        invalid_match="positive",
    )


def _shower(
    request: pytest.FixtureRequest, spec: ProcessSpec, tmp_path: Path
) -> Driver:
    lhe_path = tmp_path / "events.lhe"
    lhe_path.write_text("<LesHouchesEvents>\n<event>\n</event>\n</LesHouchesEvents>\n")
    return Driver(
        workspace_type=ShowerWorkspace,
        run=partial(
            shower_events,
            spec,
            lhe_path=lhe_path,
            n_events=1,
            delphes_pythia8_path=request.getfixturevalue("delphes_pythia8_path"),
        ),
        fail_variable="FAKE_DP8_FAIL",
        failure="DelphesPythia8 failed: DelphesPythia8",
        occupied="Output file",
        seed_path="pythia.cmnd",
        seed_line="Random:seed = {}",
        invalid={"n_events": 0},
        invalid_error=ValueError,
        invalid_match="n_events",
    )


def _simulation(
    request: pytest.FixtureRequest, spec: ProcessSpec, tmp_path: Path
) -> Driver:
    events_path = tmp_path / "particles.root"
    events_path.write_bytes(b"ROOT fake")
    return Driver(
        workspace_type=SimulationWorkspace,
        run=partial(
            simulate_events,
            spec,
            events_path=events_path,
            delphes_root_path=request.getfixturevalue("delphes_root_path"),
        ),
        fail_variable="FAKE_DROOT_FAIL",
        failure="DelphesROOT failed: DelphesROOT",
        occupied="Output file",
        seed_path="delphes_card.tcl",
        seed_line="set RandomSeed {}",
        invalid={"card_path": tmp_path / "missing.tcl"},
        invalid_error=FileNotFoundError,
        invalid_match="Delphes card",
    )


_DRIVERS = {"madgraph": _madgraph, "shower": _shower, "simulation": _simulation}


@pytest.fixture(params=list(_DRIVERS))
def driver(
    request: pytest.FixtureRequest, specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> Driver:
    return _DRIVERS[request.param](request, specs["HToBB"], tmp_path)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path / "work"


def _commands(log_path: Path) -> list[str]:
    return [line for line in log_path.read_text().splitlines() if line[:2] == "$ "]


def test_an_occupied_output_is_refused_and_left_as_it_was(
    driver: Driver, workdir: Path
) -> None:
    first = driver.run(workdir=workdir, seed=1)
    log = first.log_path.read_text()
    refused = f"{driver.occupied} .* already exists; pass overwrite=True to replace it"
    with pytest.raises(FileExistsError, match=refused):
        driver.run(workdir=workdir, seed=2)
    assert first.output_path.is_file()
    assert first.log_path.read_text() == log


def test_overwrite_replaces_an_earlier_run(driver: Driver, workdir: Path) -> None:
    first = driver.run(workdir=workdir, seed=1)
    commands = _commands(first.log_path)
    second = driver.run(workdir=workdir, seed=2, overwrite=True)
    seed_lines = (workdir / driver.seed_path).read_text().splitlines()
    assert driver.seed_line.format(2) in seed_lines
    assert second.output_path.is_file()
    assert _commands(second.log_path) == commands
    assert second.set_aside is None


def test_a_run_killed_before_sealing_is_set_aside(
    driver: Driver, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as killed_before_sealing:
        killed_before_sealing.setattr(workspace, "seal", lambda *_: None)
        first = driver.run(workdir=workdir, seed=1)
    second = driver.run(workdir=workdir, seed=2, overwrite=True)
    assert second.set_aside is not None
    assert (second.set_aside / first.output_path.relative_to(workdir)).is_file()
    assert second.output_path.is_file()


@pytest.mark.parametrize(
    ("failure", "timeout", "outcome"),
    [
        ("exit", None, "exited with status"),
        ("hang", 1.0, "was stopped at the time limit"),
    ],
    ids=["exit-status", "time-limit"],
)
def test_a_failed_run_is_sealed_and_replaced(
    driver: Driver,
    workdir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    timeout: float | None,
    outcome: str,
) -> None:
    workspace_type = driver.workspace_type
    monkeypatch.setenv(driver.fail_variable, failure)
    with pytest.raises(
        workspace_type.error_type, match=f"{re.escape(driver.failure)} {outcome}"
    ):
        driver.run(workdir=workdir, seed=1, timeout=timeout)
    stamp = read_stamp(workdir)
    assert stamp is not None and stamp.purpose == workspace_type.purpose
    assert workspace_type.log_name in stamp.artifacts
    monkeypatch.delenv(driver.fail_variable)
    run = driver.run(workdir=workdir, seed=2, overwrite=True)
    assert run.output_path.is_file()
    assert run.set_aside is None


def test_an_invalid_request_leaves_an_earlier_run_in_place(
    driver: Driver, workdir: Path
) -> None:
    first = driver.run(workdir=workdir, seed=1)
    log = first.log_path.read_text()
    with pytest.raises(driver.invalid_error, match=driver.invalid_match):
        driver.run(workdir=workdir, seed=2, overwrite=True, **driver.invalid)
    assert first.output_path.is_file()
    assert first.log_path.read_text() == log
