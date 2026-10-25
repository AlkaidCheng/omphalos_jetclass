import sys
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.processes.catalogue import ProcessSpec
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


def test_entering_sealed_run_creates_and_stamps_the_directory(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    workdir = tmp_path / "run"
    workspace = PlainWorkspace(specs["HToBB"], workdir)
    assert workspace.workdir == workdir.resolve()
    assert workspace.artifacts == ARTIFACTS
    with workspace.sealed_run() as set_aside:
        stamp = read_stamp(workdir)
        assert stamp is not None and stamp.purpose == PURPOSE
        assert stamp.details == {"process": "HToBB"}
        assert set_aside is None
        (workdir / "first.txt").write_text("made")
    sealed = read_stamp(workdir)
    assert sealed is not None and "first.txt" in sealed.artifacts


def test_a_run_is_sealed_when_its_block_raises(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    workspace = PlainWorkspace(specs["HToBB"], tmp_path)
    with pytest.raises(RuntimeError, match="cut short"), workspace.sealed_run():
        (tmp_path / "first.txt").write_text("partial")
        raise RuntimeError("cut short")
    stamp = read_stamp(tmp_path)
    assert stamp is not None and "first.txt" in stamp.artifacts


def test_a_sealed_artifact_is_deleted_and_an_unsealed_one_set_aside(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    workspace = PlainWorkspace(specs["HToBB"], tmp_path)
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
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    other_purpose = tmp_path / "other-purpose"
    other_purpose.mkdir()
    write_stamp(other_purpose, "other-purpose", {"process": "HToBB"})
    refused = PlainWorkspace(specs["HToBB"], other_purpose)
    with (
        pytest.raises(StampError, match="other-purpose, not testing"),
        refused.sealed_run(),
    ):
        raise AssertionError("the block must not run")
    other_process = tmp_path / "other-process"
    other_process.mkdir()
    write_stamp(other_process, PURPOSE, {"process": "HToBB"})
    refused = PlainWorkspace(specs["TTBar"], other_process)
    with pytest.raises(StampError, match="'HToBB', not 'TTBar'"), refused.sealed_run():
        raise AssertionError("the block must not run")
    for directory in (other_purpose, other_process):
        stamp = read_stamp(directory)
        assert stamp is not None and stamp.artifacts == {}


def test_a_filesystem_root_is_refused(specs: Mapping[str, ProcessSpec]) -> None:
    with pytest.raises(ValueError, match="filesystem root"):
        PlainWorkspace(specs["HToBB"], Path("/"))


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
        spec: ProcessSpec,
        workdir: Path,
        *,
        tool_path: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(spec, workdir, program_path=tool_path, timeout=timeout)

    @property
    def artifacts(self) -> list[str]:
        return [self.log_name]


@pytest.fixture
def tool_path(tmp_path: Path) -> Path:
    program = tmp_path / "bin" / "fake-tool"
    program.parent.mkdir()
    program.write_text(FAKE_TOOL.format(python=sys.executable))
    program.chmod(0o755)
    return program


def test_a_program_workspace_takes_the_given_program_or_finds_it_on_path(
    specs: Mapping[str, ProcessSpec],
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = specs["HToBB"]
    workspace = ToolWorkspace(spec, tmp_path, tool_path=tool_path)
    assert workspace.program_path == tool_path
    assert workspace.log_path == tmp_path.resolve() / "tool.log"
    assert workspace.deadline is None
    monkeypatch.setenv("PATH", str(tool_path.parent))
    assert ToolWorkspace(spec, tmp_path).program_path == tool_path
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError, match="fake-tool is not on PATH"):
        ToolWorkspace(spec, tmp_path)
    with pytest.raises(FileNotFoundError, match="the fake tool .* not found"):
        ToolWorkspace(spec, tmp_path, tool_path=tmp_path / "missing")


@pytest.mark.parametrize("timeout", [0, -1.0])
def test_a_time_limit_must_be_positive(
    specs: Mapping[str, ProcessSpec], tool_path: Path, tmp_path: Path, timeout: float
) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        ToolWorkspace(specs["HToBB"], tmp_path, tool_path=tool_path, timeout=timeout)


def test_runs_append_to_one_log_and_their_usage_adds_up(
    specs: Mapping[str, ProcessSpec], tool_path: Path, tmp_path: Path
) -> None:
    workspace = ToolWorkspace(specs["HToBB"], tmp_path, tool_path=tool_path)
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
    specs: Mapping[str, ProcessSpec],
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace(specs["HToBB"], tmp_path, tool_path=tool_path)
    monkeypatch.setenv("FAKE_TOOL_FAIL", "exit")
    with pytest.raises(ToolError, match="tool failed: "), workspace.sealed_run():
        workspace.run([tool_path], failure_message="tool failed")
    error = workspace.make_error("tool wrote nothing")
    assert isinstance(error, ToolError)
    assert str(error).startswith("tool wrote nothing\n")
    assert "tool ran with" in str(error)


def test_a_program_still_running_at_the_deadline_is_stopped(
    specs: Mapping[str, ProcessSpec],
    tool_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = ToolWorkspace(
        specs["HToBB"], tmp_path, tool_path=tool_path, timeout=0.5
    )
    monkeypatch.setenv("FAKE_TOOL_FAIL", "hang")
    started = time.monotonic()
    with pytest.raises(ToolError, match="tool failed: "), workspace.sealed_run():
        workspace.run([tool_path], failure_message="tool failed")
    assert time.monotonic() - started < 30
