import hashlib
from pathlib import Path

from settings_card import SettingsCard

from omphjc.formats.file_record import FileRecord


def test_a_fingerprint_is_the_format_the_version_and_the_content_hash() -> None:
    card = SettingsCard.from_text("ptj = 20\niseed = 42\n")
    canonical = b'{"iseed":"42","ptj":"20"}'
    assert card.fingerprint() == f"settings-v1:{hashlib.sha256(canonical).hexdigest()}"


def test_files_with_equal_content_records_have_one_fingerprint() -> None:
    card = SettingsCard.from_text("ptj = 20\niseed = 42\n")
    reordered = SettingsCard.from_text("# cuts\niseed=42   # seed\n\nptj   =   20\n")
    assert reordered.fingerprint() == card.fingerprint()


def test_a_changed_value_changes_the_fingerprint() -> None:
    card = SettingsCard.from_text("ptj = 20\n")
    assert SettingsCard.from_text("ptj = 30\n").fingerprint() != card.fingerprint()


def test_the_record_of_a_file_holds_its_size_and_its_fingerprint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "card.dat"
    path.write_text("ptj = 20  # cut\n")
    fingerprint = SettingsCard.from_text("ptj = 20\n").fingerprint()
    assert SettingsCard.record_file(path) == FileRecord(path, 16, fingerprint)
