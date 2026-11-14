import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from omphjc.data_files import Card
from omphjc.programs import ProgramError
from omphjc.stamps import SET_ASIDE_DIR, StampError, read_stamp, write_stamp
from omphjc.workspace import ProgramWorkspace, Workspace

PURPOSE = "testing"
ARTIFACTS = ["first.txt", "second.txt"]


class PlainWorkspace(Workspace):
    """A workspace whose runs write their files from Python."""

    purpose = PURPOSE

    @property
    def artifacts(self) -> list[str]:
        return ARTIFACTS


class NoteCard(Card):
    """A card for the tests, which is never parsed."""

    card_name = "note_card"
    file_name = "note.dat"
    description = "A note that steers nothing."


class CardWorkspace(Workspace):
    """A workspace whose run keeps one card in the working directory."""

    purpose = PURPOSE
    card_classes = (NoteCard,)


class NestedCardWorkspace(CardWorkspace):
    """A workspace whose run keeps its card in a directory of its own."""

    @property
    def cards_dir(self) -> Path:
        return self.workdir / "cards"

    @property
    def artifacts(self) -> list[str]:
        return ["cards", *super().artifacts]


def test_the_cards_in_the_working_directory_are_artifacts(tmp_path: Path) -> None:
    workspace = CardWorkspace("HToBB", tmp_path / "run")
    assert workspace.artifacts == ["note.dat"]
    card_path = workspace.workdir / "note.dat"
    with workspace.sealed_run():
        card_path.write_text("a note")
    stamp = read_stamp(workspace.workdir)
    assert stamp is not None and list(stamp.artifacts) == ["note.dat"]
    assert workspace.card_paths == {"note_card": card_path}
    with workspace.sealed_run():
        assert not card_path.exists()


def test_cards_in_another_directory_are_not_listed_again(tmp_path: Path) -> None:
    workspace = NestedCardWorkspace("HToBB", tmp_path / "run")
    assert workspace.artifacts == ["cards"]
    with workspace.sealed_run():
        workspace.cards_dir.mkdir()
        (workspace.cards_dir / "note.dat").write_text("a note")
    assert workspace.card_paths == {"note_card": workspace.cards_dir / "note.dat"}
    stamp = read_stamp(workspace.workdir)
    assert stamp is not None and list(stamp.artifacts) == ["cards"]


def test_entering_sealed_run_creates_and_stamps_the_directory(tmp_path: Path) -> None:
    workdir = tmp_path / "run"
    workspace = PlainWorkspace("HToBB", workdir)
    assert workspace.workdir == workdir.resolve()
    assert workspace.artifacts == ARTIFACTS
    assert workspace.card_paths == {}
    with workspace.sealed_run() as set_aside:
        stamp = read_stamp(workdir)
        assert stamp is not None and stamp.purpose == PURPOSE
        assert stamp.details == {"process": "HToBB"}
        assert set_aside is None
        (workdir / "first.txt").write_text("made")
    sealed = read_stamp(workdir)
    assert sealed is not None and "first.txt" in sealed.artifacts


def test_a_run_is_sealed_when_its_block_raises(tmp_path: Path) -> None:
    workspace = PlainWorkspace("HToBB", tmp_path)
    with pytest.raises(RuntimeError, match="cut short"), workspace.sealed_run():
        (tmp_path / "first.txt").write_text("partial")
        raise RuntimeError("cut short")
    stamp = read_stamp(tmp_path)
    assert stamp is not None and "first.txt" in stamp.artifacts


def test_a_sealed_artifact_is_deleted_and_an_unsealed_one_set_aside(
    tmp_path: Path,
) -> None:
    workspace = PlainWorkspace("HToBB", tmp_path)
    with workspace.sealed_run():
        (tmp_path / "first.txt").write_text("sealed")
    (tmp_path / "second.txt").write_text("left by a killed run")
    (tmp_path / "notes.txt").write_text("mine")
    with workspace.sealed_run() as set_aside:
        assert not (tmp_path / "first.txt").exists()
        assert not (tmp_path / "second.txt").exists()
        assert set_aside is not None and set_aside.parent == tmp_path / SET_ASIDE_DIR
        assert (set_aside / "second.txt").read_text() == "left by a killed run"
        assert (tmp_path / "notes.txt").read_text() == "mine"


def test_a_directory_of_another_purpose_or_process_is_refused_untouched(
    tmp_path: Path,
) -> None:
    other_purpose = tmp_path / "other-purpose"
    other_purpose.mkdir()
    write_stamp(other_purpose, "other-purpose", {"process": "HToBB"})
    refused = PlainWorkspace("HToBB", other_purpose)
    with (
        pytest.raises(StampError, match="other-purpose, not testing"),
        refused.sealed_run(),
    ):
        raise AssertionError("the block must not run")
    other_process = tmp_path / "other-process"
    other_process.mkdir()
    write_stamp(other_process, PURPOSE, {"process": "HToBB"})
    refused = PlainWorkspace("TTBar", other_process)
    with pytest.raises(StampError, match="'HToBB', not 'TTBar'"), refused.sealed_run():
        raise AssertionError("the block must not run")
    for directory in (other_purpose, other_process):
        stamp = read_stamp(directory)
        assert stamp is not None and stamp.artifacts == {}


def test_a_filesystem_root_is_refused() -> None:
    with pytest.raises(ValueError, match="filesystem root"):
        PlainWorkspace("HToBB", Path("/"))


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


class ToolError(ProgramError):
    pass


class ToolWorkspace(ProgramWorkspace):
    purpose = PURPOSE
    program = "fake-tool"
    description = "the fake tool"
    log_name = "tool.log"
    error_type = ToolError

    def __init__(
        self,
        process_name: str,
        workdir: Path,
        *,
        tool_path: Path | None = None,
        timeout: float | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(
            process_name,
            workdir,
            program_path=tool_path,
            timeout=timeout,
            log_dir=log_dir,
        )


@pytest.fixture
def tool_path(link_fake_program: Callable[[str, str], Path]) -> Path:
    return link_fake_program("fake-tool", FAKE_TOOL.format(python=sys.executable))


def test_a_program_workspace_takes_the_given_program_or_finds_it_on_path(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path)
    assert workspace.program_path == tool_path
    assert workspace.log_path == tmp_path.resolve() / "tool.log"
    assert workspace.deadline is None
    monkeypatch.setenv("PATH", str(tool_path.parent))
    assert ToolWorkspace("HToBB", tmp_path).program_path == tool_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="fake-tool is not on PATH"):
        ToolWorkspace("HToBB", tmp_path)
    with pytest.raises(FileNotFoundError, match="the fake tool .* not found"):
        ToolWorkspace("HToBB", tmp_path, tool_path=tmp_path / "missing")


def test_a_log_in_another_directory_is_not_an_artifact(
    tool_path: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "work"
    workspace = ToolWorkspace("HToBB", workdir, tool_path=tool_path)
    assert workspace.artifacts == ["tool.log"]
    log_dir = tmp_path / "logs"
    workspace = ToolWorkspace("HToBB", workdir, tool_path=tool_path, log_dir=log_dir)
    assert workspace.artifacts == []
    assert workspace.log_path == log_dir / "tool.log"


@pytest.mark.parametrize("timeout", [0, -1.0])
def test_a_time_limit_must_be_positive(
    tool_path: Path, tmp_path: Path, timeout: float
) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        ToolWorkspace("HToBB", tmp_path, tool_path=tool_path, timeout=timeout)


def test_runs_append_to_one_log_and_their_usage_adds_up(
    tool_path: Path, tmp_path: Path
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path)
    with workspace.sealed_run():
        first = workspace.run([tool_path, "one"], failure_message="tool failed")
        second = workspace.run([tool_path, "two"], failure_message="tool failed")
    log = workspace.log_path.read_text()
    assert "tool ran with one" in log and "tool ran with two" in log
    assert workspace.usage.wall_seconds == pytest.approx(
        first.wall_seconds + second.wall_seconds
    )
    stamp = read_stamp(tmp_path)
    assert stamp is not None and "tool.log" in stamp.artifacts


def test_a_failing_program_raises_the_workspaces_error(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path)
    monkeypatch.setenv("FAKE_TOOL_FAIL", "exit")
    with pytest.raises(ToolError, match="tool failed: "), workspace.sealed_run():
        workspace.run([tool_path], failure_message="tool failed")
    error = workspace.make_error("tool wrote nothing")
    assert isinstance(error, ToolError)
    assert str(error).startswith("tool wrote nothing\n")
    assert "tool ran with" in str(error)


def test_a_program_still_running_at_the_deadline_is_stopped(
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace("HToBB", tmp_path, tool_path=tool_path, timeout=0.1)
    monkeypatch.setenv("FAKE_TOOL_FAIL", "hang")
    started = time.monotonic()
    with pytest.raises(ToolError, match="tool failed: "), workspace.sealed_run():
        workspace.run([tool_path], failure_message="tool failed")
    assert time.monotonic() - started < 30
