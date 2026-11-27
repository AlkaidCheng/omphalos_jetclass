from pathlib import Path

from settings_card import SettingsCard


def test_a_card_is_read_from_a_file_as_utf8_text(tmp_path: Path) -> None:
    path = tmp_path / "card.dat"
    path.write_text("label = caf\u00e9\n", encoding="utf-8")
    assert SettingsCard.read(path) == SettingsCard(settings={"label": "caf\u00e9"})
