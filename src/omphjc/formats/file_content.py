"""FileContent, the base class of the file formats, and their fingerprints."""

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from omphjc.formats.file_record import FileRecord

_FileContentT = TypeVar("_FileContentT", bound="FileContent")


class FileContent(ABC):
    """The parsed content of a file in one format.

    Attributes
    ----------
    format_name : str
        The name of the file format, such as ``"lhe"`` or ``"run_card"``.
    record_version : int
        The version of the way :meth:`content_record` writes the content
        down. A class gets the next number whenever that way changes, so that
        fingerprints made in two ways never match.
    """

    format_name: ClassVar[str]
    record_version: ClassVar[int]

    @classmethod
    @abstractmethod
    def read(cls: type[_FileContentT], path: Path) -> _FileContentT:
        """Return the content of the file at `path`."""

    @abstractmethod
    def content_record(self) -> Any:
        """Return the content as values that :func:`json.dumps` accepts.

        Two files that differ only in layout or in comments have equal
        records.
        """

    def fingerprint(self) -> str:
        """Return a short string that stands for the content.

        Two objects have the same fingerprint when their content records are
        equal. The order of the keys in a mapping of the record does not
        count.

        Returns
        -------
        str
            The name :attr:`format_name`, the letters ``-v``, the number
            :attr:`record_version`, a colon, and the SHA-256 hash of the
            content record in hexadecimal, as in ``lhe-v1:<hash>``.
        """
        canonical = json.dumps(
            self.content_record(), sort_keys=True, separators=(",", ":")
        )
        content_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
        return f"{self.format_name}-v{self.record_version}:{content_sha256}"

    @classmethod
    def record_file(cls, path: Path) -> FileRecord:
        """Return the record of the file at `path`, with the fingerprint of its content.

        The file is read once, by :meth:`read`.
        """
        return FileRecord(path, path.stat().st_size, cls.read(path).fingerprint())
