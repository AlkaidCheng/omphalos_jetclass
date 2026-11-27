"""FileRecord, what a run notes about each file that it made or read."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

# A fingerprint, as FileContent.fingerprint writes it: lhe-v1:<hash>.
_FINGERPRINT_PATTERN = re.compile(r"[^:]+-v\d+:.+")

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
    fingerprint : str
        The fingerprint of the file's content in its format
        (:meth:`FileContent.fingerprint`).

    Raises
    ------
    ValueError
        If `fingerprint` is not a fingerprint, such as ``None`` in a record
        that was edited by hand.
    """

    path: Path
    n_bytes: int
    fingerprint: str

    def __post_init__(self) -> None:
        if not (
            isinstance(self.fingerprint, str)
            and _FINGERPRINT_PATTERN.fullmatch(self.fingerprint)
        ):
            raise ValueError(
                f"the record of {self.path} must hold a fingerprint such as "
                f'"lhe-v1:<hash>", got {self.fingerprint!r}'
            )

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
    def file_format(self) -> str:
        """The format of the file: the name that the fingerprint of its content holds.

        It is the :attr:`FileContent.format_name` of the class that read the
        file, as :meth:`FileContent.fingerprint` writes it, such as ``"lhe"``.
        """
        head, _, _ = self.fingerprint.partition(":")
        format_name, _, _ = head.rpartition("-v")
        return format_name
