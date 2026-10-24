import gzip
from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.delphes import parse_card, particles_card_text
from omphjc.processes import ProcessSpec
from omphjc.pythia import (
    ShowerError,
    ShowerWorkspace,
    read_statistics,
    shower_events,
)
from omphjc.stamps import read_stamp

BANNER_TEXT = (
    Path(__file__).parent / "data" / "madgraph" / "TTBar_banner.txt"
).read_text()

ARTIFACTS = {
    "events.lhe",
    "pythia.cmnd",
    "particles_card.tcl",
    "particles.root",
    "shower.log",
}


def _write_lhe(path: Path, n_events: int) -> Path:
    text = BANNER_TEXT + "<event>\n</event>\n" * n_events + "</LesHouchesEvents>\n"
    if path.suffix == ".gz":
        with gzip.open(path, "wt") as stream:
            stream.write(text)
    else:
        path.write_text(text)
    return path


def test_a_shower_runs_in_its_own_working_directory(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 3)
    workdir = tmp_path / "shower"
    run = shower_events(
        specs["HToBB"],
        lhe_path=lhe_path,
        workdir=workdir,
        n_events=3,
        seed=7,
        delphes_pythia8_path=delphes_pythia8_path,
    )
    assert run.output_path == workdir / "particles.root" and run.output_path.is_file()
    events = (workdir / "events.lhe").read_text()
    assert events.count("<event>") == 3
    cmnd = run.cmnd_path.read_text()
    assert "Beams:LHEF = events.lhe" in cmnd
    assert "Main:numberOfEvents = 3" in cmnd
    assert "Random:seed = 7" in cmnd
    assert run.card_path.read_text() == particles_card_text()
    assert run.statistics.pythia_version == "8.318"
    assert (run.statistics.events_read, run.statistics.events_accepted) == (3, 3)
    assert run.log_path == workdir / "shower.log"
    assert run.log_path.read_text().count("$ ") == 1
    assert run.set_aside is None
    stamp = read_stamp(workdir)
    assert stamp is not None and stamp.purpose == "pythia-shower"
    assert stamp.details == {"process": "HToBB"}
    assert set(stamp.artifacts) == ARTIFACTS


def test_a_plain_lhe_file_is_copied_and_no_seed_leaves_pythia_to_the_clock(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe", 2)
    run = shower_events(
        specs["HToBB"],
        lhe_path=lhe_path,
        workdir=tmp_path / "shower",
        n_events=10,
        seed=None,
        delphes_pythia8_path=delphes_pythia8_path,
    )
    assert (tmp_path / "shower" / "events.lhe").read_text() == lhe_path.read_text()
    assert "Random:seed = 0" in run.cmnd_path.read_text()
    assert run.statistics.events_read == 2


def test_the_particles_card_runs_only_the_tree_writer() -> None:
    card = parse_card(particles_card_text())
    assert card.execution_path == ("TreeWriter",)
    assert list(card.modules) == ["TreeWriter"]
    assert "RandomSeed" not in particles_card_text()


def test_a_matched_process_showers_with_matching_and_loses_events_to_it(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 4)
    run = shower_events(
        specs["ZJetsToNuNu"],
        lhe_path=lhe_path,
        workdir=tmp_path / "shower",
        n_events=4,
        seed=1,
        overrides={"Main:timesAllowErrors": 5},
        delphes_pythia8_path=delphes_pythia8_path,
    )
    cmnd = run.cmnd_path.read_text()
    assert "JetMatching:merge = on" in cmnd
    assert "Main:timesAllowErrors = 5" in cmnd
    assert (run.statistics.events_read, run.statistics.events_accepted) == (4, 2)


def test_an_existing_output_is_kept_by_default_and_replaced_on_request(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 1)
    arguments = dict(lhe_path=lhe_path, workdir=tmp_path / "shower", n_events=1, seed=1)
    first = shower_events(
        specs["HToBB"], delphes_pythia8_path=delphes_pythia8_path, **arguments
    )
    with pytest.raises(FileExistsError, match="already exists"):
        shower_events(
            specs["HToBB"], delphes_pythia8_path=delphes_pythia8_path, **arguments
        )
    assert first.output_path.is_file()
    again = shower_events(
        specs["HToBB"],
        delphes_pythia8_path=delphes_pythia8_path,
        overwrite=True,
        **arguments,
    )
    assert again.output_path.is_file()
    assert again.log_path.read_text().count("$ ") == 1
    assert again.set_aside is None


def test_a_failing_exit_status_raises_and_seals_the_log(
    specs: Mapping[str, ProcessSpec],
    delphes_pythia8_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 1)
    monkeypatch.setenv("FAKE_DP8_FAIL", "exit")
    with pytest.raises(ShowerError, match="DelphesPythia8 failed: .* status 1"):
        shower_events(
            specs["HToBB"],
            lhe_path=lhe_path,
            workdir=tmp_path / "shower",
            n_events=1,
            seed=1,
            delphes_pythia8_path=delphes_pythia8_path,
        )
    stamp = read_stamp(tmp_path / "shower")
    assert stamp is not None and "shower.log" in stamp.artifacts


def test_a_run_that_gave_up_raises(
    specs: Mapping[str, ProcessSpec],
    delphes_pythia8_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 1)
    monkeypatch.setenv("FAKE_DP8_FAIL", "abort")
    with pytest.raises(ShowerError, match="gave up"):
        shower_events(
            specs["HToBB"],
            lhe_path=lhe_path,
            workdir=tmp_path / "shower",
            n_events=1,
            seed=1,
            delphes_pythia8_path=delphes_pythia8_path,
        )


def test_a_run_past_its_time_limit_is_stopped(
    specs: Mapping[str, ProcessSpec],
    delphes_pythia8_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 1)
    monkeypatch.setenv("FAKE_DP8_FAIL", "hang")
    with pytest.raises(ShowerError, match="time limit"):
        shower_events(
            specs["HToBB"],
            lhe_path=lhe_path,
            workdir=tmp_path / "shower",
            n_events=1,
            seed=1,
            timeout=0.5,
            delphes_pythia8_path=delphes_pythia8_path,
        )


def test_invalid_requests_fail_before_anything_runs(
    specs: Mapping[str, ProcessSpec], delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "shower"
    with pytest.raises(FileNotFoundError, match="Event file"):
        shower_events(
            specs["HToBB"],
            lhe_path=tmp_path / "missing.lhe.gz",
            workdir=workdir,
            n_events=1,
            seed=1,
            delphes_pythia8_path=delphes_pythia8_path,
        )
    assert not workdir.exists()
    lhe_path = _write_lhe(tmp_path / "events.lhe.gz", 1)
    first = shower_events(
        specs["HToBB"],
        lhe_path=lhe_path,
        workdir=workdir,
        n_events=1,
        seed=1,
        delphes_pythia8_path=delphes_pythia8_path,
    )
    log_before = first.log_path.read_text()
    with pytest.raises(ValueError, match="n_events"):
        shower_events(
            specs["HToBB"],
            lhe_path=lhe_path,
            workdir=workdir,
            n_events=0,
            seed=1,
            overwrite=True,
            delphes_pythia8_path=delphes_pythia8_path,
        )
    assert first.output_path.is_file() and first.log_path.read_text() == log_before


def test_read_statistics_parses_pythias_banner_and_table() -> None:
    log = (
        " |  |    This is PYTHIA version 8.318      |  | \n"
        " | Les Houches User Process(es)                  9999 |"
        "        1000       1000        800 |   1.000e-09  0.000e+00 |\n"
        " | sum                                                |"
        "        1000       1000        800 |   1.000e-09  0.000e+00 |\n"
    )
    statistics = read_statistics(log)
    assert statistics.pythia_version == "8.318"
    assert (statistics.events_read, statistics.events_selected) == (1000, 1000)
    assert statistics.events_accepted == 800
    with pytest.raises(ValueError, match="banner"):
        read_statistics("no banner")
    with pytest.raises(ValueError, match="statistics"):
        read_statistics("This is PYTHIA version 8.318 and nothing else")


def test_a_workspace_finds_delphes_pythia8_on_path_or_takes_the_given_one(
    specs: Mapping[str, ProcessSpec],
    delphes_pythia8_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = specs["HToBB"]
    workspace = ShowerWorkspace(
        spec, tmp_path, delphes_pythia8_path=delphes_pythia8_path
    )
    assert workspace.program_path == delphes_pythia8_path
    assert workspace.output_path == tmp_path.resolve() / "particles.root"
    monkeypatch.setenv("PATH", str(delphes_pythia8_path.parent))
    assert ShowerWorkspace(spec, tmp_path).program_path == delphes_pythia8_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="not on PATH"):
        ShowerWorkspace(spec, tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        ShowerWorkspace(spec, tmp_path, delphes_pythia8_path=tmp_path / "missing")
