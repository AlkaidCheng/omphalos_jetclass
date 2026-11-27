from dataclasses import asdict
from pathlib import Path

import pytest
from settings_card import SettingsCard

from omphjc.formats.file_record import FileRecord


def test_a_file_record_names_the_format_of_the_class_that_read_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "card.dat"
    path.write_text("ptj = 20\n")
    assert SettingsCard.record_file(path).file_format == SettingsCard.format_name


@pytest.mark.parametrize("fingerprint", [None, "", "abc", "lhe:abc", "lhe-v1:"])
def test_a_file_record_without_a_fingerprint_is_refused(
    fingerprint: str | None, tmp_path: Path
) -> None:
    path = tmp_path / "card.dat"
    refusal = (
        f"^the record of {path} must hold a fingerprint such as "
        f'"lhe-v1:<hash>", got {fingerprint!r}$'
    )
    with pytest.raises(ValueError, match=refusal):
        FileRecord(path, 9, fingerprint)  # type: ignore[arg-type]


def test_a_file_record_reads_back_what_asdict_writes(tmp_path: Path) -> None:
    record = FileRecord(tmp_path / "cards" / "card.dat", 16, "settings-v1:abc")
    written = {**asdict(record), "path": "cards/card.dat"}
    assert FileRecord.from_record(written, tmp_path) == record
