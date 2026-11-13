"""The reader of an event file of any readable format.

This module imports the module of every readable format, so that
:func:`reader_for` can name the reader of each format. No other module does:
the modules below this one import none of the format modules.

The record and its fields are described in :mod:`omphjc.events.particles`.
"""

from omphjc.events.delphes_root import DelphesRootReader
from omphjc.events.formats import EventFile, EventFormat, EventReader

READERS: dict[EventFormat, type[EventReader]] = {
    EventFormat.DELPHES_ROOT: DelphesRootReader,
}
"""The reader class of each readable format."""


def reader_for(event_file: EventFile) -> EventReader:
    """Return a reader of `event_file`, of the class that reads its format.

    Raises
    ------
    ValueError
        If no reader reads the file's format.
    """
    try:
        reader = READERS[event_file.format]
    except KeyError:
        readable = ", ".join(sorted(fmt.value for fmt in READERS))
        raise ValueError(
            f"cannot read particles from {event_file.format.value} files; readable"
            f" formats: {readable}"
        ) from None
    return reader(event_file.path)
