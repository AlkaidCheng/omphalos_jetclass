"""FileRecord, what a run notes about each file that it made or read."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

_FileRecordT = TypeVar("_FileRecordT", bound="FileRecord")


@dataclass(frozen=True)
class FileRecord:
    """The record of a file: where it is, its size and what it holds.

    Parameters
    ----------
    path : Path
        The file.
    n_bytes : int
        The size of the file in bytes when it was recorded. A job compares it
        with the file to tell whether the file has changed since.
    fingerprint : str or None
        The fingerprint of the file's content in its format
        (:meth:`FileContent.fingerprint`), or ``None`` for a file recorded
        without being read.
    """

    path: Path
    n_bytes: int
    fingerprint: str | None

    @classmethod
    def from_record(
        cls: type[_FileRecordT], record: Mapping[str, Any], root_dir: Path
    ) -> _FileRecordT:
        """Return the file record that `record` holds, with its path under `root_dir`.

        `record` maps each field of the class to its value, as
        :func:`dataclasses.asdict` writes it, with the path relative to
        `root_dir`. A subclass whose field is not a JSON value converts it.
        """
        values = {field.name: record[field.name] for field in fields(cls)}
        return cls(**{**values, "path": root_dir / values["path"]})

    @property
    def file_format(self) -> str | None:
        """The format of the file: the name that the fingerprint of its content holds.

        It is the :attr:`FileContent.format_name` of the class that read the
        file, as :meth:`FileContent.fingerprint` writes it, such as ``"lhe"``. It
        is ``None`` for a file recorded without being read.
        """
        if self.fingerprint is None:
            return None
        head, _, _ = self.fingerprint.partition(":")
        format_name, separator, version = head.rpartition("-v")
        return format_name if separator and version.isdigit() else None
