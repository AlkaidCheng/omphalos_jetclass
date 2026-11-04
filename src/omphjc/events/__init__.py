"""Event files: the formats that carry events between stages, and their readers.

The package exports the file contracts only and imports no array library. The
readers are in :mod:`omphjc.events.readers` and the particle record's schema in
:mod:`omphjc.events.particles`.
"""

from omphjc.events.formats import EventFile, EventFormat

__all__ = ["EventFile", "EventFormat"]
