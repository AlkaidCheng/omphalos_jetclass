import hashlib
from pathlib import Path

from omphjc.formats.binary_file import BinaryFile


def test_a_binary_file_is_the_hash_of_its_bytes(tmp_path: Path) -> None:
    path = tmp_path / "table.parquet"
    path.write_bytes(bytes(range(256)) * 5000)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert BinaryFile.read(path) == BinaryFile(expected)
    record = BinaryFile.record_file(path)
    assert (record.n_bytes, record.file_format) == (256 * 5000, "binary")
