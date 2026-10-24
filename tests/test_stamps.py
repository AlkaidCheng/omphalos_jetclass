import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

import omphjc
from omphjc.stamps import (
    SET_ASIDE_DIR,
    STAMP_FILE,
    StampError,
    clear_artifacts,
    clear_set_aside_folders,
    read_stamp,
    require_stamp,
    seal,
    set_aside_folders,
    write_stamp,
)


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """A stamped directory with two sealed artifacts and a file of the user's."""
    run = tmp_path / "run"
    (run / "output" / "Events" / "run_01").mkdir(parents=True)
    (run / "output" / "Events" / "run_01" / "events.lhe.gz").write_text("events")
    (run / "run.log").write_text("log")
    (run / "notes.txt").write_text("mine")
    write_stamp(run, "testing", {"process": "HToBB"})
    seal(run, ["output", "run.log", "missing"])
    return run


def test_a_stamp_records_its_purpose_details_and_maker(tmp_path: Path) -> None:
    stamp = write_stamp(tmp_path, "testing", {"process": "HToBB"})
    assert read_stamp(tmp_path) == stamp
    assert stamp.details == {"process": "HToBB"}
    assert stamp.version == omphjc.__version__
    assert datetime.fromisoformat(stamp.created).tzinfo is not None
    assert json.loads((tmp_path / STAMP_FILE).read_text())["producer"] == "omphjc"


def test_a_stamp_is_never_written_over_anything(tmp_path: Path) -> None:
    write_stamp(tmp_path, "testing")
    with pytest.raises(FileExistsError):
        write_stamp(tmp_path, "other")
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("mine")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / STAMP_FILE).symlink_to(elsewhere)
    with pytest.raises(FileExistsError):
        write_stamp(linked, "testing")
    assert elsewhere.read_text() == "mine"


def test_a_directory_without_a_stamp_has_none(tmp_path: Path) -> None:
    assert read_stamp(tmp_path) is None
    assert read_stamp(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"producer": "someone else"}',
        '{"producer": "omphjc", "purpose": "testing", "details": {}, '
        '"omphjc_version": "1", "created": "now", "artifacts": {"x": "late"}}',
    ],
)
def test_anything_else_in_a_stamps_place_is_refused(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / STAMP_FILE).write_text(content)
    with pytest.raises(StampError, match="not an omphjc stamp"):
        read_stamp(tmp_path)


def test_require_stamp_checks_purpose_and_details(run: Path, tmp_path: Path) -> None:
    assert require_stamp(run, "testing", {"process": "HToBB"}).purpose == "testing"
    with pytest.raises(StampError, match="no omphjc stamp"):
        require_stamp(tmp_path / "missing", "testing")
    with pytest.raises(StampError, match="for testing, not other"):
        require_stamp(run, "other")
    with pytest.raises(StampError, match="process 'HToBB', not 'HToGG'"):
        require_stamp(run, "testing", {"process": "HToGG"})


def test_a_seal_is_one_number_per_artifact_however_many_files(run: Path) -> None:
    for number in range(500):
        (run / "output" / f"file_{number}.dat").write_text("")
    stamp = seal(run, ["output", "run.log", "missing"])
    assert set(stamp.artifacts) == {"output", "run.log"}
    assert all(isinstance(change, int) for change in stamp.artifacts.values())


def test_sealed_unchanged_artifacts_are_deleted_and_nothing_else(run: Path) -> None:
    assert clear_artifacts(run, ["output", "run.log", "missing"], "testing") is None
    assert sorted(path.name for path in run.iterdir()) == ["notes.txt", STAMP_FILE]
    stamp = read_stamp(run)
    assert stamp is not None and stamp.artifacts == {}


@pytest.mark.parametrize(
    "change",
    [
        lambda run: (run / "output" / "Events" / "run_01" / "notes.txt").write_text(
            "x"
        ),
        lambda run: (run / "output" / "Events" / "run_01" / "events.lhe.gz").unlink(),
        lambda run: (run / "output" / "Events" / "run_01").rename(
            run / "output" / "Events" / "renamed"
        ),
    ],
)
def test_an_artifact_changed_after_sealing_is_set_aside_whole(
    run: Path, change: Callable[[Path], object]
) -> None:
    change(run)
    before = sorted(path.relative_to(run) for path in (run / "output").rglob("*"))
    folder = clear_artifacts(
        run, ["output", "run.log"], "testing", details={"process": "HToBB"}
    )
    assert folder is not None and folder.parent == run / SET_ASIDE_DIR
    moved = sorted(path.relative_to(folder) for path in (folder / "output").rglob("*"))
    assert moved == before
    assert not (run / "output").exists() and not (run / "run.log").exists()


def test_unsealed_and_doubtful_artifacts_are_set_aside(run: Path) -> None:
    (run / "later").mkdir()
    (run / "later" / "partial.dat").write_text("partial")
    folder = clear_artifacts(
        run, ["output", "run.log", "later"], "testing", doubtful=["run.log"]
    )
    assert folder is not None
    assert (folder / "later" / "partial.dat").read_text() == "partial"
    assert (folder / "run.log").read_text() == "log"
    assert not (folder / "output").exists() and not (run / "output").exists()


def test_each_clearing_sets_aside_into_a_folder_of_its_own(run: Path) -> None:
    folders = set()
    for _ in range(2):
        (run / "later").mkdir()
        folders.add(clear_artifacts(run, ["later"], "testing"))
    assert len(folders) == 2 and None not in folders


def test_a_link_set_aside_is_moved_and_its_target_kept(
    run: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("mine")
    (run / "run.log").unlink()
    (run / "run.log").symlink_to(elsewhere)
    folder = clear_artifacts(run, ["run.log"], "testing")
    assert folder is not None and (folder / "run.log").is_symlink()
    assert elsewhere.read_text() == "mine"


def test_artifacts_in_a_directory_without_a_stamp_are_left_in_place(
    tmp_path: Path,
) -> None:
    (tmp_path / "output").mkdir()
    assert clear_artifacts(tmp_path, ["missing"], "testing") is None
    with pytest.raises(StampError, match="has no omphjc stamp"):
        clear_artifacts(tmp_path, ["output"], "testing")
    assert (tmp_path / "output").is_dir()


def test_artifacts_of_another_purpose_are_left_in_place(run: Path) -> None:
    with pytest.raises(StampError, match="process 'HToBB', not 'HToGG'"):
        clear_artifacts(run, ["output"], "testing", details={"process": "HToGG"})
    assert (run / "output").is_dir()
    assert not (run / SET_ASIDE_DIR).exists()


def test_an_artifact_name_must_stay_inside_the_directory(run: Path) -> None:
    for name in ("..", "../outside", "/etc", "output/../.."):
        with pytest.raises(ValueError):
            clear_artifacts(run, [name], "testing", details={"process": "HToBB"})


def test_links_in_an_artifact_are_neither_followed_nor_their_targets_removed(
    run: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "theirs.txt").write_text("theirs")
    (run / "output" / "linked").symlink_to(outside)
    seal(run, ["output", "run.log"])
    (outside / "added.txt").write_text("theirs too")
    assert (
        clear_artifacts(run, ["output"], "testing", details={"process": "HToBB"})
        is None
    )
    assert not (run / "output").exists()
    assert sorted(path.name for path in outside.iterdir()) == [
        "added.txt",
        "theirs.txt",
    ]


def test_an_edit_in_place_inside_a_sealed_folder_is_not_detected(run: Path) -> None:
    (run / "output" / "Events" / "run_01" / "events.lhe.gz").write_text("edited")
    folder = clear_artifacts(run, ["output"], "testing", details={"process": "HToBB"})
    assert folder is None
    assert not (run / "output").exists()


def test_a_link_sealed_in_an_artifacts_place_is_set_aside(
    run: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("mine")
    (run / "run.log").unlink()
    (run / "run.log").symlink_to(elsewhere)
    seal(run, ["output", "run.log"])
    folder = clear_artifacts(run, ["run.log"], "testing", details={"process": "HToBB"})
    assert folder is not None and (folder / "run.log").is_symlink()
    assert elsewhere.read_text() == "mine"


def test_set_aside_folders_are_listed_oldest_first_with_their_size(
    run: Path,
) -> None:
    assert set_aside_folders(run) == []
    for text in ("first", "second!"):
        (run / "later").mkdir()
        (run / "later" / "file.txt").write_text(text)
        clear_artifacts(run, ["later"], "testing")
    (run / SET_ASIDE_DIR / "notes.txt").write_text("mine")
    (run / SET_ASIDE_DIR / "20200101T000000Z-link").symlink_to(run / "notes.txt")
    folders = set_aside_folders(run)
    assert sorted(folder.size() for folder in folders) == [5, 7]
    assert folders[0].created <= folders[1].created
    assert folders[0].created.tzinfo is not None
    assert all(folder.path.parent == run / SET_ASIDE_DIR for folder in folders)


def test_clearing_deletes_the_listed_set_aside_folders_and_nothing_else(
    run: Path,
) -> None:
    assert clear_set_aside_folders(run) == []
    (run / "later").mkdir()
    (run / "later" / "file.txt").write_text("gone")
    clear_artifacts(run, ["later"], "testing")
    stray = run / SET_ASIDE_DIR / "notes.txt"
    stray.write_text("mine")
    removed = clear_set_aside_folders(run)
    assert len(removed) == 1 and not removed[0].path.exists()
    assert stray.read_text() == "mine" and set_aside_folders(run) == []
    stray.unlink()
    (run / "later").mkdir()
    clear_artifacts(run, ["later"], "testing")
    assert len(clear_set_aside_folders(run)) == 1
    assert not (run / SET_ASIDE_DIR).exists()
    assert (run / "notes.txt").read_text() == "mine"


def test_clearing_set_aside_folders_needs_a_stamp_when_there_is_something_to_delete(
    tmp_path: Path,
) -> None:
    folder = tmp_path / SET_ASIDE_DIR / "20260101T000000Z-abc"
    folder.mkdir(parents=True)
    with pytest.raises(StampError, match="no omphjc stamp"):
        clear_set_aside_folders(tmp_path)
    assert folder.is_dir()
