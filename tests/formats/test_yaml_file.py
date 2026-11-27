from pathlib import Path

from omphjc.config_paths import catalogue_path
from omphjc.formats.yaml_file import YAMLFile


def test_a_yaml_file_is_its_value_whatever_its_layout(tmp_path: Path) -> None:
    commented = tmp_path / "commented.yaml"
    commented.write_text("# the order\nb: [1, 2]\na: x  # a letter\n")
    block = tmp_path / "block.yaml"
    block.write_text("a: x\nb:\n  - 1\n  - 2\n")
    assert YAMLFile.read(commented) == YAMLFile({"a": "x", "b": [1, 2]})
    assert YAMLFile.read(commented).fingerprint() == YAMLFile.read(block).fingerprint()
    assert YAMLFile.record_file(block).file_format == "yaml"


def test_a_yaml_file_keeps_the_types_that_json_lacks_apart(tmp_path: Path) -> None:
    def fingerprint(text: str) -> str:
        path = tmp_path / "settings.yaml"
        path.write_text(text)
        return YAMLFile.read(path).fingerprint()

    assert fingerprint("cut: {25: 450.0}\n") == fingerprint("cut:\n  25: 450.0\n")
    assert fingerprint("cut: {25: 450.0}\n") != fingerprint("cut: {'25': 450.0}\n")
    assert fingerprint("on: 2026-11-26\n") != fingerprint("on: '2026-11-26'\n")
    repeated = "a: &cut {pt: 20}\nb: *cut\n"
    assert fingerprint(repeated) == fingerprint("a: {pt: 20}\nb: {pt: 20}\n")


def test_the_shipped_catalogue_reads_as_a_yaml_file() -> None:
    catalogue = YAMLFile.read(catalogue_path())
    assert "HToBB" in catalogue.value["processes"]
