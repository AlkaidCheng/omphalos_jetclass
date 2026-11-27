from pathlib import Path

from omphjc.formats.json_file import JSONFile


def test_a_json_file_is_its_value_whatever_its_layout(tmp_path: Path) -> None:
    compact = tmp_path / "compact.json"
    compact.write_text('{"b": [1, 2], "a": "x"}')
    spread = tmp_path / "spread.json"
    spread.write_text('{\n  "a": "x",\n  "b": [\n    1,\n    2\n  ]\n}\n')
    assert JSONFile.read(compact) == JSONFile({"a": "x", "b": [1, 2]})
    assert JSONFile.read(compact).fingerprint() == JSONFile.read(spread).fingerprint()
    assert JSONFile.record_file(compact).file_format == "json"
