"""Reading the particle record of an event file, whatever its format.

The record and its fields are described in :mod:`omphjc.events.particles`.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import awkward as ak

from omphjc.events import delphes_root
from omphjc.events.formats import EventFile, EventFormat


class _FormatReader(Protocol):
    """The functions a module reading one event format provides."""

    def read_particles(
        self,
        path: Path,
        *,
        entry_start: int = ...,
        entry_stop: int | None = ...,
        downcast: bool = ...,
    ) -> ak.Array: ...

    def iterate_particles(
        self, path: Path, *, step_size: int | str = ..., downcast: bool = ...
    ) -> Iterator[ak.Array]: ...

    def count_events(self, path: Path) -> int: ...


_READERS: dict[EventFormat, _FormatReader] = {
    EventFormat.DELPHES_ROOT: delphes_root,
}


def read_particles(
    event_file: EventFile,
    *,
    entry_start: int = 0,
    entry_stop: int | None = None,
    downcast: bool = True,
) -> ak.Array:
    """Return the particle record of `event_file`'s events in [entry_start, entry_stop).

    Parameters
    ----------
    event_file : EventFile
        The file to read.
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
        If the format cannot be read, or the file or the range is not one the
        format's reader accepts.
    """
    return _reader(event_file).read_particles(
        event_file.path,
        entry_start=entry_start,
        entry_stop=entry_stop,
        downcast=downcast,
    )


def iterate_particles(
    event_file: EventFile, *, step_size: int | str = "100 MB", downcast: bool = True
) -> Iterator[ak.Array]:
    """Yield the particle record of `event_file` in steps of `step_size`.

    Parameters
    ----------
    event_file : EventFile
        The file to read.
    step_size : int or str, optional
        Events per step, or a memory size such as ``"100 MB"``.
    downcast : bool, optional
        As for :func:`read_particles`.

    Returns
    -------
    Iterator[ak.Array]
        The records of consecutive events. A file the format's reader does not
        accept raises ``ValueError`` once the iteration starts.

    Raises
    ------
    ValueError
        If the format cannot be read.
    """
    return _reader(event_file).iterate_particles(
        event_file.path, step_size=step_size, downcast=downcast
    )


def count_events(event_file: EventFile) -> int:
    """Return the number of events in `event_file`, without reading them.

    Raises
    ------
    ValueError
        If the format cannot be read.
    """
    return _reader(event_file).count_events(event_file.path)


def _reader(event_file: EventFile) -> _FormatReader:
    """Return the reader of `event_file`'s format."""
    try:
        return _READERS[event_file.format]
    except KeyError:
        readable = ", ".join(sorted(fmt.value for fmt in _READERS))
        raise ValueError(
            f"cannot read particles from {event_file.format.value} files; readable"
            f" formats: {readable}"
        ) from None
