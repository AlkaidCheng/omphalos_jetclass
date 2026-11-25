"""The content of the files that the tools read and write.

Each file format has one class, and every such class is a :class:`DataFile`.
An object of the class holds the content of one file after parsing. It does
not hold the location of the file, so the same class also holds content that
is stored inside another file, such as a card in the header of an event file.

The class of a file that is too large to keep in memory, such as an event
file, holds a hash of the large part in its place.

A class states how its format is read (:meth:`DataFile.read`) and how the
content is written down as plain values (:meth:`DataFile.content_record`). The
content record holds what the program that reads the file gets from it. The
layout of the file and its comments are left out. Two files with equal content
records have the same fingerprint (:meth:`DataFile.fingerprint`).

A :class:`FileRecord` identifies a file on disk by its path, its size and the
fingerprint of its content; :meth:`DataFile.record_file` makes the record of a
file in a format.

A :class:`Card` is a data file made of text, with settings or commands. Two
cards of one class are compared part by part (:meth:`Card.differences`).
"""

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from omphjc.comparison import Difference

_DataFileT = TypeVar("_DataFileT", bound="DataFile")
_CardT = TypeVar("_CardT", bound="Card")
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
        (:meth:`DataFile.fingerprint`), or ``None`` for a file recorded
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

        It is the :attr:`DataFile.format_name` of the class that read the
        file, as :meth:`DataFile.fingerprint` writes it, such as ``"lhe"``. It
        is ``None`` for a file recorded without being read.
        """
        if self.fingerprint is None:
            return None
        head, _, _ = self.fingerprint.partition(":")
        format_name, separator, version = head.rpartition("-v")
        return format_name if separator and version.isdigit() else None


class DataFile(ABC):
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
    def read(cls: type[_DataFileT], path: Path) -> _DataFileT:
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


class Card(DataFile):
    """The parsed content of a text file that holds settings or commands.

    A class may also name one card of a tool: the card that the tool's
    program reads in a run. Such a class states the three attributes below.
    A class that describes a format alone leaves them out, and a card of a
    tool that has this format derives from it.

    Attributes
    ----------
    card_name : str
        The name of the card among the cards of its tool, such as
        ``"run_card"``. The record of a task lists the card under this name.
    file_name : str
        The name of the file of the card in the directory where a run keeps
        its cards.
    description : str
        One sentence that says what the card is.
    """

    card_name: ClassVar[str]
    file_name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_text(cls: type[_CardT], text: str) -> _CardT:
        """Return the content of a card given as text."""

    @classmethod
    def read(cls: type[_CardT], path: Path) -> _CardT:
        """Return the content of the card at `path`, read as UTF-8 text."""
        return cls.from_text(path.read_text(encoding="utf-8"))

    @abstractmethod
    def differences(self: _CardT, reference: _CardT) -> list[Difference]:
        """Return the differences between this card and `reference`.

        Each difference names one part of the content. Its expected value is
        the one of `reference`, and its actual value is the one of this card.
        The layout of a card and its comments give no differences.
        """
