import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.data_files import Card


@dataclass(frozen=True)
class SettingsCard(Card):
    """A card of ``name = value`` lines, with comments after ``#``."""

    format_name: ClassVar[str] = "settings"
    record_version: ClassVar[int] = 1

    settings: dict[str, str]

    @classmethod
    def from_text(cls, text: str) -> "SettingsCard":
        settings = {}
        for line in text.splitlines():
            name, separator, value = line.split("#", 1)[0].partition("=")
            if separator:
                settings[name.strip()] = value.strip()
        return cls(settings=settings)

    def content_record(self) -> dict[str, str]:
        return self.settings

    def differences(self, reference: "SettingsCard") -> list[Difference]:
        return Difference.between_mappings(self.settings, reference.settings)


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


def test_a_card_is_read_from_a_file_as_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "card.dat"
    path.write_text("label = caf\u00e9\n", encoding="utf-8")
    assert SettingsCard.read(path) == SettingsCard(settings={"label": "caf\u00e9"})
