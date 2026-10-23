import os
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.config_paths import export_config
from omphjc.madgraph import (
    MadGraphError,
    MadGraphWorkspace,
    generate_events,
    launch_commands,
    madspin_card_text,
)
from omphjc.processes import ProcessSpec, load_catalogue
from omphjc.programs import available_cores
from omphjc.stamps import StampError, read_stamp


def test_a_process_runs_in_its_own_working_directory(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "work"
    run = generate_events(specs["HToBB"], workdir=workdir, n_events=10, seed=7, mg5=mg5)
    assert run.process_dir == workdir / "HToBB"
    assert run.events == workdir / "HToBB/Events/run_01/unweighted_events.lhe.gz"
    assert run.banner.seed == 7
    launch = (workdir / "launch.mg5").read_text().splitlines()
    assert launch == launch_commands(
        specs["HToBB"], process_dir=run.process_dir, n_events=10, seed=7
    )
    log = run.log_file.read_text()
    assert "process.mg5" in log and "launch.mg5" in log and "MadGraph done" in log


def test_madspin_events_are_the_decayed_sample(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    spec = specs["TTBar"]
    run = generate_events(spec, workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    assert run.events.parent.name == "run_01_decayed_1"
    card = run.process_dir / "Cards" / "madspin_card.dat"
    assert card.read_text() == madspin_card_text(spec)


def test_a_vendored_model_is_imported_from_a_copy(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    spec = specs["HToWW4Q"]
    assert spec.model_path is not None
    original = sorted(path.name for path in spec.model_path.iterdir())
    generate_events(spec, workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    copy = tmp_path / "models" / "heft"
    assert f"import model {copy}-ckm" in (tmp_path / "process.mg5").read_text()
    assert (copy / "py3_model.pkl").is_file()
    assert sorted(path.name for path in spec.model_path.iterdir()) == original


@pytest.mark.parametrize("failing", ["output", "launch"])
def test_a_failed_command_raises_with_the_end_of_the_log(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", failing)
    with pytest.raises(MadGraphError, match=f"Command {failing} interrupted"):
        generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)


def test_a_failing_exit_status_raises(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", "exit")
    with pytest.raises(
        MadGraphError, match="running process.mg5: mg5_aMC exited with status 3"
    ):
        generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)


@pytest.mark.parametrize("n_cores", [3, None])
def test_madgraph_runs_on_the_requested_cores(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path, n_cores: int | None
) -> None:
    run = generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, n_cores=n_cores, mg5=mg5
    )
    configuration = (run.process_dir / "Cards" / "me5_configuration.txt").read_text()
    expected = available_cores() if n_cores is None else n_cores
    assert configuration.splitlines()[-2:] == ["run_mode = 2", f"nb_core = {expected}"]


def test_a_run_past_its_time_limit_is_stopped(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", "hang")
    with pytest.raises(
        MadGraphError, match="running process.mg5: mg5_aMC was stopped at the time"
    ):
        generate_events(
            specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, timeout=1, mg5=mg5
        )


def test_an_existing_process_directory_is_kept_by_default(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    (tmp_path / "HToBB").mkdir()
    with pytest.raises(FileExistsError, match="overwrite=True"):
        generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    assert not (tmp_path / "madgraph.log").exists()


def test_overwrite_replaces_an_earlier_run(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    spec = specs["HToWW4Q"]
    generate_events(spec, workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    second = generate_events(
        spec, workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert second.banner.seed == 2
    commands = [
        line for line in second.log_file.read_text().splitlines() if line[:2] == "$ "
    ]
    assert len(commands) == 2


def test_a_run_stamps_its_directory_and_seals_its_artifacts(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    run = generate_events(
        specs["HToWW4Q"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5
    )
    stamp = read_stamp(tmp_path)
    assert stamp is not None
    assert stamp.purpose == "madgraph-event-generation"
    assert stamp.details == {"process": "HToWW4Q"}
    assert set(stamp.artifacts) == {
        "HToWW4Q",
        "process.mg5",
        "launch.mg5",
        "madgraph.log",
        "models/heft",
    }
    assert read_stamp(run.process_dir) is None


def test_a_run_killed_before_sealing_is_set_aside(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omphjc.madgraph.driver as driver

    with monkeypatch.context() as killed_before_sealing:
        killed_before_sealing.setattr(driver, "seal", lambda *_: None)
        generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    run = generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert run.banner.seed == 2
    assert run.set_aside is not None
    earlier = run.set_aside / "HToBB" / "Events" / "run_01" / "unweighted_events.lhe.gz"
    assert earlier.is_file()


def test_a_process_directory_without_the_process_card_is_set_aside(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omphjc.madgraph.driver as driver

    generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    monkeypatch.setattr(driver, "_PROC_CARD", "a_card_madgraph_did_not_write.dat")
    run = generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert run.set_aside is not None and (run.set_aside / "HToBB").is_dir()


def test_files_of_yours_inside_a_run_are_set_aside_with_it(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    spec = specs["HToWW4Q"]
    first = generate_events(spec, workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    (first.process_dir / "Cards" / "notes.txt").write_text("mine")
    (tmp_path / "models" / "heft" / "notes.txt").write_text("mine too")
    second = generate_events(
        spec, workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert second.set_aside is not None
    assert (second.set_aside / "HToWW4Q" / "Cards" / "notes.txt").read_text() == "mine"
    copy_notes = second.set_aside / "models" / "heft" / "notes.txt"
    assert copy_notes.read_text() == "mine too"
    assert not (second.process_dir / "Cards" / "notes.txt").exists()


@pytest.mark.parametrize(
    ("failure", "timeout"), [("exit", None), ("launch", None), ("hang", 1.0)]
)
def test_a_failed_run_is_sealed_and_replaced(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    timeout: float | None,
) -> None:
    monkeypatch.setenv("FAKE_MG5_FAIL", failure)
    with pytest.raises(MadGraphError):
        generate_events(
            specs["HToWW4Q"],
            workdir=tmp_path,
            n_events=10,
            seed=1,
            timeout=timeout,
            mg5=mg5,
        )
    monkeypatch.delenv("FAKE_MG5_FAIL")
    run = generate_events(
        specs["HToWW4Q"], workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert run.banner.seed == 2
    assert run.set_aside is None


def test_an_invalid_request_leaves_an_earlier_run_in_place(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    run = generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5
    )
    with pytest.raises(ValueError, match="positive"):
        generate_events(
            specs["HToBB"],
            workdir=tmp_path,
            n_events=0,
            seed=1,
            overwrite=True,
            mg5=mg5,
        )
    assert run.events.is_file()
    assert run.log_file.is_file()


def test_a_directory_no_run_made_is_left_in_place(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    (tmp_path / "HToBB").mkdir()
    (tmp_path / "models" / "heft").mkdir(parents=True)
    (tmp_path / "madgraph.log").write_text("mine\n")
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(StampError, match="has no omphjc stamp"):
        generate_events(
            specs["HToWW4Q"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5
        )
    with pytest.raises(StampError, match="has no omphjc stamp"):
        generate_events(
            specs["HToBB"],
            workdir=tmp_path,
            n_events=10,
            seed=1,
            overwrite=True,
            mg5=mg5,
        )
    assert sorted(tmp_path.rglob("*")) == before


def test_other_files_in_a_working_directory_are_kept(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    (tmp_path / "notes.txt").write_text("mine")
    generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert (tmp_path / "notes.txt").read_text() == "mine"


def test_a_directory_of_another_process_is_refused(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    run = generate_events(
        specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5
    )
    log = run.log_file.read_text()
    with pytest.raises(StampError, match="process 'HToBB', not 'HToGG'"):
        generate_events(specs["HToGG"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    assert run.log_file.read_text() == log
    assert run.events.is_file()


@pytest.mark.parametrize(
    "replaced", ["HToWW4Q", "models/heft", "process.mg5", "madgraph.log"]
)
def test_an_artifact_replaced_by_yours_is_set_aside(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path, replaced: str
) -> None:
    spec = specs["HToWW4Q"]
    generate_events(spec, workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    mine = tmp_path / replaced
    if mine.is_dir():
        shutil.rmtree(mine)
        mine.mkdir()
        (mine / "notes.txt").write_text("mine")
    else:
        mine.write_text("mine\n")
    run = generate_events(
        spec, workdir=tmp_path, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert run.set_aside is not None
    kept = run.set_aside / replaced
    assert (
        (kept / "notes.txt" if kept.is_dir() else kept).read_text().startswith("mine")
    )


def test_something_else_in_the_stamps_place_is_left_alone(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    generate_events(specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, mg5=mg5)
    (tmp_path / "omphjc-stamp.json").write_text("mine\n")
    with pytest.raises(StampError, match="not an omphjc stamp"):
        generate_events(
            specs["HToBB"],
            workdir=tmp_path,
            n_events=10,
            seed=2,
            overwrite=True,
            mg5=mg5,
        )
    assert (tmp_path / "omphjc-stamp.json").read_text() == "mine\n"


def test_a_run_in_the_catalogue_folder_leaves_its_model_alone(
    mg5: Path, tmp_path: Path
) -> None:
    config = export_config(tmp_path / "config")
    spec = load_catalogue(config / "jetclass.yaml")["HToWW4Q"]
    original = sorted(path.name for path in (config / "models" / "heft").iterdir())
    with pytest.raises(ValueError, match="would overlap the model folder"):
        generate_events(spec, workdir=config, n_events=10, seed=1, mg5=mg5)
    assert (
        sorted(path.name for path in (config / "models" / "heft").iterdir()) == original
    )


def test_a_symbolic_link_in_place_of_a_run_file_is_set_aside_unfollowed(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("import model mine\n")
    workdir = tmp_path / "work"
    generate_events(specs["HToBB"], workdir=workdir, n_events=10, seed=1, mg5=mg5)
    (workdir / "process.mg5").unlink()
    (workdir / "process.mg5").symlink_to(elsewhere)
    run = generate_events(
        specs["HToBB"], workdir=workdir, n_events=10, seed=2, overwrite=True, mg5=mg5
    )
    assert run.set_aside is not None and (run.set_aside / "process.mg5").is_symlink()
    assert elsewhere.read_text() == "import model mine\n"


def test_a_filesystem_root_is_refused(
    specs: Mapping[str, ProcessSpec], mg5: Path
) -> None:
    with pytest.raises(ValueError, match="filesystem root"):
        generate_events(
            specs["HToBB"],
            workdir=Path("/"),
            n_events=10,
            seed=1,
            overwrite=True,
            mg5=mg5,
        )


def test_invalid_requests_fail_before_madgraph_starts(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="positive"):
        generate_events(specs["HToBB"], workdir=tmp_path, n_events=0, seed=1, mg5=mg5)
    with pytest.raises(ValueError, match="whitespace"):
        generate_events(
            specs["HToBB"], workdir=tmp_path / "my run", n_events=10, seed=1, mg5=mg5
        )
    with pytest.raises(ValueError, match="n_cores"):
        generate_events(
            specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, n_cores=0, mg5=mg5
        )
    with pytest.raises(ValueError, match="timeout"):
        generate_events(
            specs["HToBB"], workdir=tmp_path, n_events=10, seed=1, timeout=0, mg5=mg5
        )
    assert not (tmp_path / "madgraph.log").exists()


def test_a_workspace_finds_mg5_on_path_or_takes_the_given_one(
    specs: Mapping[str, ProcessSpec],
    mg5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = specs["HToBB"]
    assert MadGraphWorkspace(spec, tmp_path, mg5=mg5).executable == mg5
    monkeypatch.setenv("PATH", str(mg5.parent))
    assert MadGraphWorkspace(spec, tmp_path).executable == mg5
    monkeypatch.setenv("PATH", "")
    with pytest.raises(FileNotFoundError, match="not on PATH"):
        MadGraphWorkspace(spec, tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        MadGraphWorkspace(spec, tmp_path, mg5=mg5.parent / "missing")


def test_a_workspace_derives_every_path_a_run_writes(
    specs: Mapping[str, ProcessSpec], mg5: Path, tmp_path: Path
) -> None:
    workspace = MadGraphWorkspace(specs["HToWW4Q"], tmp_path, mg5=mg5)
    assert workspace.directory == tmp_path.resolve()
    assert workspace.process_dir == workspace.directory / "HToWW4Q"
    assert workspace.model_copy == workspace.directory / "models" / "heft"
    assert workspace.artifacts == [
        "HToWW4Q",
        "process.mg5",
        "launch.mg5",
        "madgraph.log",
        "models/heft",
    ]
    assert workspace.events.parent.name == "run_01"
    decayed = MadGraphWorkspace(specs["TTBar"], tmp_path, mg5=mg5)
    assert decayed.events.parent.name == "run_01_decayed_1"


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("mg5_aMC") is None, reason="MadGraph's mg5_aMC is not on PATH"
)
def test_madgraph_generates_a_small_sample(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    run = generate_events(specs["HToBB"], workdir=tmp_path, n_events=20, seed=1)
    assert run.banner.n_events == 20
    assert run.banner.seed == 1
    assert os.path.getsize(run.events) > 0
