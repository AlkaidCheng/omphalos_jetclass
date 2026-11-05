"""Event files: the formats that carry events between stages, and their readers.

The package exports the file contracts only and imports no array library.
:func:`omphjc.events.readers.reader_for` returns the reader of a file's format;
the particle record's schema is in :mod:`omphjc.events.particles` and the
restoration of long-lived particles in :mod:`omphjc.events.long_lived`.
"""

from omphjc.events.formats import EventFile, EventFormat, EventReader

__all__ = ["EventFile", "EventFormat", "EventReader"]
