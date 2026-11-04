"""Readers of the particle record in an event file, one class per format.

The record and its fields are described in :mod:`omphjc.events.particles`.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import awkward as ak

from omphjc.events.formats import EventFile, EventFormat


class EventReader(ABC):
    """Reads the particle record of an event file of one format.

    Parameters
    ----------
    path : Path
        The file to read.
    """

    format: ClassVar[EventFormat]
    """The format the reader reads."""

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
    ) -> ak.Array:
        """Return the particle record of the events in [entry_start, entry_stop).

        Parameters
        ----------
        entry_start, entry_stop : int, int or None, optional
            The events to read; ``None`` reads to the end of the file.
        downcast : bool, optional
            Whether to cast every field to the schema's dtype; otherwise each
            keeps the dtype the file stores. Units are the schema's either way.

        Returns
        -------
        ak.Array
            One record per event.

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
    ) -> Iterator[ak.Array]:
        """Yield the particle record of the file in steps of `step_size`.

        Parameters
        ----------
        step_size : int or str, optional
            Events per step, or a memory size such as ``"100 MB"``.
        downcast : bool, optional
            As for :meth:`read_particles`.

        Yields
        ------
        ak.Array
            The records of consecutive events.

        Raises
        ------
        ValueError
            As :meth:`read_particles` does, once the iteration starts.
        """


def reader_for(event_file: EventFile) -> EventReader:
    """Return the reader of `event_file`'s format, reading `event_file`.

    Raises
    ------
    ValueError
        If no reader reads the file's format.
    """
    # Imported here, since each format's module imports EventReader from this one.
    from omphjc.events.delphes_root import DelphesRootReader

    readers: tuple[type[EventReader], ...] = (DelphesRootReader,)
    for reader in readers:
        if reader.format is event_file.format:
            return reader(event_file.path)
    readable = ", ".join(sorted(reader.format.value for reader in readers))
    raise ValueError(
        f"cannot read particles from {event_file.format.value} files; readable"
        f" formats: {readable}"
    )
