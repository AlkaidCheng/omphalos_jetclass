"""The content of the files that the tools read and write.

Each file format has one class, and every such class is a :class:`DataFile`.
An object of the class holds the content of one file after parsing. It does
not hold the location of the file, so the same class also holds content that
is stored inside another file, such as a card in the header of an event file.

A class states how its format is read (:meth:`DataFile.read`) and how the
content is written down as plain values (:meth:`DataFile.content_record`). The
content record holds what the program that reads the file gets from it. The
layout of the file and its comments are left out. Two files with equal content
records have the same fingerprint (:meth:`DataFile.fingerprint`).

A :class:`Card` is a data file made of text, with settings or commands.
"""

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, TypeVar

_DataFileT = TypeVar("_DataFileT", bound="DataFile")
_CardT = TypeVar("_CardT", bound="Card")


class DataFile(ABC):
    """The parsed content of a file in one format.

    Attributes
    ----------
    record_scheme : str
        A label for the way :meth:`content_record` writes the content down,
        such as ``"lhe-v1"``. A class gets a new label whenever that way
        changes, so that fingerprints made in two ways never match.
    """

    record_scheme: ClassVar[str]

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
            The label :attr:`record_scheme`, a colon, and the SHA-256 hash of
            the content record in hexadecimal.
        """
        canonical = json.dumps(
            self.content_record(), sort_keys=True, separators=(",", ":")
        )
        return f"{self.record_scheme}:{hashlib.sha256(canonical.encode()).hexdigest()}"


class Card(DataFile):
    """The parsed content of a text file that holds settings or commands."""

    @classmethod
    @abstractmethod
    def from_text(cls: type[_CardT], text: str) -> _CardT:
        """Return the content of a card given as text."""

    @classmethod
    def read(cls: type[_CardT], path: Path) -> _CardT:
        """Return the content of the card at `path`, read as UTF-8 text."""
        return cls.from_text(path.read_text(encoding="utf-8"))
