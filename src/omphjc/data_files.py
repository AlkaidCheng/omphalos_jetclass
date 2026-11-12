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

A :class:`Card` is a data file made of text, with settings or commands. Two
cards of one class are compared part by part (:meth:`Card.differences`).
"""

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from omphjc.comparison import Difference

_DataFileT = TypeVar("_DataFileT", bound="DataFile")
_CardT = TypeVar("_CardT", bound="Card")


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

    @abstractmethod
    def differences(self: _CardT, reference: _CardT) -> list[Difference]:
        """Return the differences between this card and `reference`.

        Each difference names one part of the content. Its expected value is
        the one of `reference`, and its actual value is the one of this card.
        The layout of a card and its comments give no differences.
        """
