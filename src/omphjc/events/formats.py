"""The file conventions that carry events from one stage to the next.

A format names how a file is opened and where its particle-level events are.
It does not name the reconstructed collections that the file carries. For
example, DelphesPythia8's record of the shower and DelphesROOT's output are
both ``delphes-root`` files.

The content of a file in a format is an :class:`EventDataFile`, whose record
(:meth:`EventDataFile.record_file`) is an :class:`EventFileRecord`: the
record of a file with its format and its event count.

:class:`EventReader` is the interface for reading the particle record of a
file. It is defined here, with the formats it serves. Each readable format has
a module with a subclass of :class:`EventReader`.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from omphjc.data_files import DataFile, FileRecord

if TYPE_CHECKING:
    import awkward as ak


class EventFormat(str, Enum):
    """A file convention that carries events from one stage to the next."""

    LHE = "lhe"
    """Les Houches events, plain or compressed with gzip."""

    DELPHES_ROOT = "delphes-root"
    """ROOT tree ``Delphes`` with the branches ``Particle`` and ``Event``."""


@dataclass(frozen=True)
class EventFile:
    """An event file and its format.

    Attributes
    ----------
    path : Path
        The file.
    format : EventFormat
        How the file is opened and where its events are.
    """

    path: Path
    format: EventFormat


@dataclass(frozen=True)
class EventFileRecord(FileRecord):
    """The record of an event file.

    Parameters
    ----------
    path : Path
        The file.
    n_bytes : int
        The size of the file in bytes when it was recorded.
    fingerprint : str
        The fingerprint of the events (:meth:`EventDataFile.fingerprint`).
        Two files with the same events have the same fingerprint, which the
        next stage compares to tell whether its input has changed.
    format : EventFormat
        The format of the file.
    n_events : int
        The number of events the file holds.
    """

    fingerprint: str
    format: EventFormat
    n_events: int

    @classmethod
    def from_record(
        cls, record: Mapping[str, Any], root_dir: Path
    ) -> "EventFileRecord":
        """Return the event file record that `record` holds, as the base class does.

        The format is recorded by its value, such as ``"lhe"``.
        """
        return super().from_record(
            {**record, "format": EventFormat(record["format"])}, root_dir
        )


class EventDataFile(DataFile):
    """The parsed content of a file that holds events.

    A subclass is one event format. It states :attr:`event_format` and gives
    the number of events, :attr:`n_events`.

    Attributes
    ----------
    event_format : EventFormat
        The format of the file.
    """

    event_format: ClassVar[EventFormat]

    @property
    @abstractmethod
    def n_events(self) -> int:
        """The number of events the file holds."""

    @classmethod
    def record_file(cls, path: Path) -> EventFileRecord:
        """Return the record of the event file at `path`.

        The file is read once, by :meth:`read`.
        """
        content = cls.read(path)
        return EventFileRecord(
            path,
            path.stat().st_size,
            content.fingerprint(),
            cls.event_format,
            content.n_events,
        )


class EventReader(ABC):
    """Reads the particle record of an event file of one format.

    Parameters
    ----------
    path : Path
        The file to read.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    @abstractmethod
    def count_events(self) -> int:
        """Return the number of events in the file, without reading them."""

    @abstractmethod
    def read_particles(
        self,
        *,
        entry_start: int = 0,
        entry_stop: int | None = None,
        downcast: bool = True,
    ) -> "ak.Array":
        """Return the particle record of the events in [entry_start, entry_stop).

        Parameters
        ----------
        entry_start, entry_stop : int, int or None, optional
            The events to read. ``None`` reads to the end of the file.
        downcast : bool, optional
            Whether to cast every field to the dtype of the schema. Without
            the cast, each field keeps the dtype that the file stores. The
            values are in the units of the schema in both cases.

        Returns
        -------
        ak.Array
            One record per event (:mod:`omphjc.events.particles`).

        Raises
        ------
        ValueError
            If the range lies outside the file, the file is not one the reader
            accepts, or a value does not fit the schema's dtype when
            downcasting.
        """

    @abstractmethod
    def iterate_particles(
        self, *, step_size: int | str = "100 MB", downcast: bool = True
    ) -> Iterator["ak.Array"]:
        """Yield the particle record of the file in steps of `step_size`.

        Parameters
        ----------
        step_size : int or str, optional
            Events per step, or a memory size such as ``"100 MB"``.
        downcast : bool, optional
            The same as for :meth:`read_particles`.

        Yields
        ------
        ak.Array
            The records of consecutive events.

        Raises
        ------
        ValueError
            For the reasons that :meth:`read_particles` gives. The error is
            raised once the iteration starts.
        """
