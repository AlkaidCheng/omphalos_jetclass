"""BinaryFile, the format of a file that omphjc does not parse."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.formats.file_content import FileContent

# Number of bytes read at a time while hashing a file.
_READ_BYTES = 1 << 20


@dataclass(frozen=True)
class BinaryFile(FileContent):
    """The SHA-256 hash of the bytes of a file that omphjc does not parse.

    Two files have the same content only when their bytes are equal. A format
    whose bytes also hold when and how the file was written, such as HDF5,
    gives two fingerprints to equal content; such a format needs a class of
    its own when that matters.

    Parameters
    ----------
    content_sha256 : str
        The SHA-256 hash of the bytes, in hexadecimal.
    """

    format_name: ClassVar[str] = "binary"
    record_version: ClassVar[int] = 1

    content_sha256: str

    @classmethod
    def read(cls, path: Path) -> "BinaryFile":
        """Return the hash of the file at `path`, read in blocks."""
        content = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(_READ_BYTES):
                content.update(block)
        return cls(content.hexdigest())

    def content_record(self) -> str:
        """Return the hash."""
        return self.content_sha256
