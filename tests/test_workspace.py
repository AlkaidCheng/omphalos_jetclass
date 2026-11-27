import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from omphjc.comparison import Difference
from omphjc.formats.card import Card
from omphjc.formats.file_record import FileRecord
from omphjc.programs import ProgramError
from omphjc.stamps import SET_ASIDE_DIR, StampError, read_stamp, write_stamp
from omphjc.workspace import LOG_NAME, ProgramWorkspace, Workspace

PURPOSE = "testing"
ARTIFACTS = ["first.txt", "second.txt"]

# Stands in for an external program: it prints its arguments, and with
# FAKE_TOOL_FAIL=exit fails with status 2, with FAKE_TOOL_FAIL=hang never
# finishes.
FAKE_TOOL = """\
#!{python}
import os
import sys
import time

print("tool ran with", *sys.argv[1:])
fail = os.environ.get("FAKE_TOOL_FAIL", "")
if fail == "hang":
    time.sleep(60)
if fail == "exit":
    print("tool error", file=sys.stderr)
    sys.exit(2)
"""


@pytest.fixture
def tool_path(link_fake_program: Callable[[str, str], Path]) -> Path:
    return link_fake_program("fake-tool", FAKE_TOOL.format(python=sys.executable))


def _workspace(workdir: Path, process_name: str = "HToBB") -> Workspace:
    return Workspace(workdir, process_name=process_name)


def test_making_a_workspace_changes_nothing_on_disk(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path / "run")
    assert workspace.workdir == (tmp_path / "run").resolve()
    assert workspace.log_path == workspace.workdir / LOG_NAME
    assert workspace.set_aside_dir is None
    assert not (tmp_path / "run").exists()


def test_entering_sealed_run_creates_and_stamps_the_directory(tmp_path: Path) -> None:
    workdir = tmp_path / "run"
    workspace = _workspace(workdir)
    with workspace.sealed_run(PURPOSE, ARTIFACTS):
        stamp = read_stamp(workdir)
        assert stamp is not None and stamp.purpose == PURPOSE
        assert stamp.details == {"process": "HToBB"}
        (workdir / "first.txt").write_text("made")
    assert workspace.set_aside_dir is None
    sealed = read_stamp(workdir)
    assert sealed is not None and "first.txt" in sealed.artifacts


def test_a_run_is_sealed_when_its_block_raises(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with (
        pytest.raises(RuntimeError, match="cut short"),
        workspace.sealed_run(PURPOSE, ARTIFACTS),
    ):
        (tmp_path / "first.txt").write_text("partial")
        raise RuntimeError("cut short")
    stamp = read_stamp(tmp_path)
    assert stamp is not None and "first.txt" in stamp.artifacts


def test_a_sealed_artifact_is_deleted_and_an_unsealed_one_set_aside(
    tmp_path: Path,
) -> None:
    with _workspace(tmp_path).sealed_run(PURPOSE, ARTIFACTS):
        (tmp_path / "first.txt").write_text("sealed")
    (tmp_path / "second.txt").write_text("left by a killed run")
    (tmp_path / "notes.txt").write_text("mine")
    rerun = _workspace(tmp_path)
    with rerun.sealed_run(PURPOSE, ARTIFACTS):
        assert not (tmp_path / "first.txt").exists()
        assert not (tmp_path / "second.txt").exists()
        assert (tmp_path / "notes.txt").read_text() == "mine"
    set_aside = rerun.set_aside_dir
    assert set_aside is not None and set_aside.parent == tmp_path / SET_ASIDE_DIR
    assert (set_aside / "second.txt").read_text() == "left by a killed run"


def test_an_unconfirmed_artifact_is_set_aside_although_it_was_sealed(
    tmp_path: Path,
) -> None:
    with _workspace(tmp_path).sealed_run(PURPOSE, ARTIFACTS):
        (tmp_path / "first.txt").write_text("sealed")
    rerun = _workspace(tmp_path)
    with rerun.sealed_run(PURPOSE, ARTIFACTS, unconfirmed=["first.txt"]):
        assert not (tmp_path / "first.txt").exists()
    assert rerun.set_aside_dir is not None
    assert (rerun.set_aside_dir / "first.txt").read_text() == "sealed"


def test_a_directory_of_another_purpose_or_process_is_refused_untouched(
    tmp_path: Path,
) -> None:
    other_purpose = tmp_path / "other-purpose"
    other_purpose.mkdir()
    write_stamp(other_purpose, "other-purpose", {"process": "HToBB"})
    refused = _workspace(other_purpose)
    with (
        pytest.raises(StampError, match="other-purpose, not testing"),
        refused.sealed_run(PURPOSE, ARTIFACTS),
    ):
        raise AssertionError("the block must not run")
    other_process = tmp_path / "other-process"
    other_process.mkdir()
    write_stamp(other_process, PURPOSE, {"process": "HToBB"})
    refused = _workspace(other_process, process_name="TTBar")
    with (
        pytest.raises(StampError, match="'HToBB', not 'TTBar'"),
        refused.sealed_run(PURPOSE, ARTIFACTS),
    ):
        raise AssertionError("the block must not run")
    for directory in (other_purpose, other_process):
        stamp = read_stamp(directory)
        assert stamp is not None and stamp.artifacts == {}


def test_a_filesystem_root_is_refused() -> None:
    with pytest.raises(ValueError, match="filesystem root"):
        _workspace(Path("/"))


def test_a_workspace_holds_one_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with workspace.sealed_run(PURPOSE, ARTIFACTS):
        pass
    with (
        pytest.raises(RuntimeError, match="holds one run"),
        workspace.sealed_run(PURPOSE, ARTIFACTS),
    ):
        raise AssertionError("the block must not run")


def test_the_programs_run_only_inside_sealed_run(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(RuntimeError, match="only inside an opened session"):
        workspace.programs.run([tool_path], failure_message="tool failed")
    with workspace.sealed_run(PURPOSE, ARTIFACTS):
        workspace.programs.run([tool_path], failure_message="tool failed")
    with pytest.raises(RuntimeError, match="only inside an opened session"):
        workspace.programs.run([tool_path], failure_message="tool failed")
    assert workspace.programs.cwd == workspace.workdir
    assert workspace.programs.log_path == workspace.log_path


@pytest.mark.parametrize("timeout", [0, -1.0])
def test_a_time_limit_must_be_positive(tmp_path: Path, timeout: float) -> None:
    workspace = _workspace(tmp_path / "run")
    with (
        pytest.raises(ValueError, match="timeout must be positive"),
        workspace.sealed_run(PURPOSE, ARTIFACTS, timeout=timeout),
    ):
        raise AssertionError("the block must not run")
    assert not (tmp_path / "run").exists()


def test_the_log_in_the_directory_is_an_artifact(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = _workspace(tmp_path)
    with workspace.sealed_run(PURPOSE, ARTIFACTS):
        workspace.programs.run([tool_path], failure_message="tool failed")
    stamp = read_stamp(tmp_path)
    assert stamp is not None and LOG_NAME in stamp.artifacts


def test_a_log_given_a_place_is_not_an_artifact(
    tool_path: Path, tmp_path: Path
) -> None:
    workdir, log_path = tmp_path / "work", tmp_path / "logs" / "first.log"
    log_path.parent.mkdir()
    workspace = Workspace(workdir, process_name="HToBB", log_path=log_path)
    assert workspace.log_path == log_path
    with workspace.sealed_run(PURPOSE, ARTIFACTS):
        workspace.programs.run([tool_path], failure_message="tool failed")
    assert workspace.log_path.is_file()
    stamp = read_stamp(workdir)
    assert stamp is not None and LOG_NAME not in stamp.artifacts


def test_the_time_limit_of_sealed_run_stops_a_program(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("FAKE_TOOL_FAIL", "hang")
    started = time.monotonic()
    with (
        pytest.raises(ProgramError, match="tool failed: "),
        workspace.sealed_run(PURPOSE, ARTIFACTS, timeout=0.1),
    ):
        workspace.programs.run([tool_path], failure_message="tool failed")
    assert time.monotonic() - started < 30


@dataclass(frozen=True)
class NoteCard(Card):
    """A card for the tests, read as its lines without the comments after ``#``."""

    format_name = "note"
    record_version = 1
    card_name = "note_card"
    file_name = "note.dat"
    description = "A note that steers nothing."

    lines: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "NoteCard":
        lines = (line.split("#", 1)[0].strip() for line in text.splitlines())
        return cls(tuple(line for line in lines if line))

    def content_record(self) -> list[str]:
        return list(self.lines)

    def differences(self, reference: "NoteCard") -> list[Difference]:
        return []


class ToolWorkspace(ProgramWorkspace):
    """A tool's workspace whose run keeps one card in the working directory."""

    purpose = PURPOSE
    program = "fake-tool"
    description = "the fake tool"
    card_classes = (NoteCard,)

    def __init__(
        self,
        process_name: str,
        workdir: Path,
        *,
        tool_path: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(process_name, workdir, program_path=tool_path, timeout=timeout)


class NestedCardWorkspace(ToolWorkspace):
    """A tool's workspace whose run keeps its card in a directory of its own."""

    @property
    def cards_dir(self) -> Path:
        return self.workdir / "cards"

    @property
    def artifacts(self) -> list[str]:
        return ["cards", *super().artifacts]


def test_a_tool_workspace_takes_the_given_program_or_finds_it_on_path(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path)
    assert workspace.program_path == tool_path
    assert workspace.log_path == tmp_path.resolve() / LOG_NAME
    monkeypatch.setenv("PATH", str(tool_path.parent))
    assert ToolWorkspace("HToBB", tmp_path).program_path == tool_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="fake-tool is not on PATH"):
        ToolWorkspace("HToBB", tmp_path)
    with pytest.raises(FileNotFoundError, match="the fake tool .* not found"):
        ToolWorkspace("HToBB", tmp_path, tool_path=tmp_path / "missing")


def test_the_cards_in_the_working_directory_are_artifacts(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path / "run", tool_path=tool_path)
    assert workspace.artifacts == ["note.dat"]
    card_path = workspace.workdir / "note.dat"
    with workspace.sealed_run() as set_aside:
        assert set_aside is None
        card_path.write_text("a note")
    stamp = read_stamp(workspace.workdir)
    assert stamp is not None and list(stamp.artifacts) == ["note.dat"]
    assert workspace.card_records() == {"note_card": NoteCard.record_file(card_path)}
    rerun = ToolWorkspace("HToBB", tmp_path / "run", tool_path=tool_path)
    with rerun.sealed_run():
        assert not card_path.exists()


def test_cards_in_another_directory_are_not_listed_again(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = NestedCardWorkspace("HToBB", tmp_path / "run", tool_path=tool_path)
    assert workspace.artifacts == ["cards"]
    with workspace.sealed_run():
        workspace.cards_dir.mkdir()
        (workspace.cards_dir / "note.dat").write_text("a note")
    card_path = workspace.cards_dir / "note.dat"
    assert workspace.card_records() == {"note_card": NoteCard.record_file(card_path)}
    stamp = read_stamp(workspace.workdir)
    assert stamp is not None and list(stamp.artifacts) == ["cards"]


def test_a_card_is_recorded_by_its_class_with_the_fingerprint_of_its_content(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path / "run", tool_path=tool_path)
    assert workspace.card_records() == {}
    with workspace.sealed_run():
        (workspace.workdir / "note.dat").write_text("a note  # for the reader\n")
        (workspace.workdir / "other.dat").write_text("not a card of the run")
    fingerprint = NoteCard.from_text("a note\n").fingerprint()
    assert fingerprint.startswith("note-v1:")
    record = FileRecord(workspace.workdir / "note.dat", 25, fingerprint)
    assert workspace.card_records() == {"note_card": record}


def test_a_tool_workspace_passes_its_time_limit_to_the_run(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path, timeout=0.1)
    monkeypatch.setenv("FAKE_TOOL_FAIL", "hang")
    with pytest.raises(ProgramError, match="tool failed: "), workspace.sealed_run():
        workspace.run([tool_path], failure_message="tool failed")
