"""Event files: the formats that carry events between stages, and their readers.

The package exports the file contracts only and imports no array library. The
rest is in these modules:

- :func:`omphjc.events.readers.reader_for` returns the reader of a file's
  format.
- :mod:`omphjc.events.particles` holds the schema of the particle record.
- :mod:`omphjc.events.stable_particles` holds the stable-particle definition.
"""

from omphjc.events.formats import EventFile, EventFormat, EventReader

__all__ = ["EventFile", "EventFormat", "EventReader"]
