"""The file conventions that carry events from one stage to the next.

A format names how a file is opened and where its particle-level events are,
not which reconstructed collections it carries: DelphesPythia8's record of the
shower and DelphesROOT's output are both ``delphes-root`` files.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

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


class EventReader(ABC):
    """Reads the particle record of an event file of one format.

    A subclass that sets `format` registers itself as the reader of that format
    when it is defined; :meth:`for_format` returns it.

    Parameters
    ----------
    path : Path
        The file to read.
    """

    format: ClassVar[EventFormat]
    """The format the reader reads."""

    _registered: ClassVar[dict[EventFormat, type["EventReader"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "format" not in vars(cls):
            return
        registered = EventReader._registered.setdefault(cls.format, cls)
        if registered is not cls:
            raise TypeError(
                f"{cls.__qualname__} and {registered.__qualname__} both read"
                f" {cls.format.value} files"
            )

    @staticmethod
    def for_format(event_format: EventFormat) -> type["EventReader"]:
        """Return the reader class registered for `event_format`.

        A format's reader is registered when its module is imported, as
        importing :mod:`omphjc.events.readers` does for every format.

        Raises
        ------
        ValueError
            If no reader is registered for `event_format`.
        """
        try:
            return EventReader._registered[event_format]
        except KeyError:
            readable = ", ".join(sorted(fmt.value for fmt in EventReader._registered))
            raise ValueError(
                f"cannot read particles from {event_format.value} files; readable"
                f" formats: {readable or 'none until omphjc.events.readers is imported'}"
            ) from None

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
            The events to read; ``None`` reads to the end of the file.
        downcast : bool, optional
            Whether to cast every field to the schema's dtype; otherwise each
            keeps the dtype the file stores. Units are the schema's either way.

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
