from pathlib import Path

from omphjc.events import EventFileRecord, EventFormat
from omphjc.file_content import FileRecord
from omphjc.runs import EVENTS_OUTPUT, RunResult


def test_the_events_of_a_result_are_its_output_named_events(tmp_path: Path) -> None:
    events = EventFileRecord(tmp_path / "events.lhe", 7, "lhe-v1:a", EventFormat.LHE, 1)
    summary = FileRecord(tmp_path / "summary.txt", 3, None)
    result = RunResult(outputs={EVENTS_OUTPUT: events, "summary": summary})
    assert result.events == events
    assert RunResult(outputs={"summary": summary}).events is None
    assert RunResult(outputs={EVENTS_OUTPUT: summary}).events is None
