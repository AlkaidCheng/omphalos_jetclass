"""Event files: the formats that carry events between stages, and their readers.

The package exports the file contracts only and imports no array library. The
readers are in :mod:`omphjc.events.readers`, the particle record's schema in
:mod:`omphjc.events.particles` and the final-state rule in
:mod:`omphjc.events.final_state`.
"""

from omphjc.events.formats import EventFile, EventFormat

__all__ = ["EventFile", "EventFormat"]
