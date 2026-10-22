import hashlib
import json

from omphjc.config_paths import config_root

VENDORED_DIRECTORIES = ("delphes", "madspin", "models", "references")


def test_every_vendored_file_matches_its_recorded_hash() -> None:
    root = config_root()
    document = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    assert document["algorithm"] == "sha256"
    hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in VENDORED_DIRECTORIES
        for path in (root / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert hashes == document["files"]
