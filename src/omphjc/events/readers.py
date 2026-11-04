"""The reader of an event file, whatever its format.

This is the one module that imports the module of every readable format, each
of which registers its :class:`~omphjc.events.formats.EventReader` subclass
when imported, so :func:`reader_for` finds the reader of any of them. The
record and its fields are described in :mod:`omphjc.events.particles`.
"""

from omphjc.events import delphes_root
from omphjc.events.formats import EventFile, EventReader

# The modules of the readable formats.
FORMAT_MODULES = (delphes_root,)


def reader_for(event_file: EventFile) -> EventReader:
    """Return a reader of `event_file`, of the class registered for its format.

    Raises
    ------
    ValueError
        If no reader reads the file's format.
    """
    return EventReader.for_format(event_file.format)(event_file.path)
