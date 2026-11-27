from dataclasses import asdict
from pathlib import Path

from settings_card import SettingsCard

from omphjc.formats.file_record import FileRecord


def test_a_file_record_names_the_format_of_the_class_that_read_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "card.dat"
    path.write_text("ptj = 20\n")
    assert SettingsCard.record_file(path).file_format == SettingsCard.format_name
    assert FileRecord(path, 9, None).file_format is None


def test_a_file_record_reads_back_what_asdict_writes(tmp_path: Path) -> None:
    record = FileRecord(tmp_path / "cards" / "card.dat", 16, "settings-v1:abc")
    written = {**asdict(record), "path": "cards/card.dat"}
    assert FileRecord.from_record(written, tmp_path) == record
    unread = FileRecord(tmp_path / "notes.txt", 3, None)
    written = {**asdict(unread), "path": "notes.txt"}
    assert FileRecord.from_record(written, tmp_path) == unread
