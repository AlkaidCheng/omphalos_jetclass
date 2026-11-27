from pathlib import Path

from omphjc.formats.text_file import TextFile


def test_a_text_file_is_its_text(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("caf\u00e9\n", encoding="utf-8")
    assert TextFile.read(path) == TextFile("caf\u00e9\n")
    assert TextFile.record_file(path).file_format == "text"
