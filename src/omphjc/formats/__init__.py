"""The formats of the files that the tools read and write.

Each file format has one class, and every such class is a
:class:`~omphjc.formats.file_content.FileContent`. An object of the class holds
the content of one file after parsing. It does not hold the location of the
file, so the same class also holds content that is stored inside another file,
such as a card in the header of an event file.

The class of a file that is too large to keep in memory, such as an event
file, holds a hash of the large part in its place.

A class states how its format is read and how the content is written down as
plain values, its content record. The content record holds what the program
that reads the file gets from it. The layout of the file and its comments are
left out. Two files with equal content records have the same fingerprint.

The package has one module per class:

- :mod:`omphjc.formats.file_content`: :class:`FileContent`, the base class of
  the formats.
- :mod:`omphjc.formats.file_record`: :class:`FileRecord`, the record of a file
  on disk by its path, its size and the fingerprint of its content.
- :mod:`omphjc.formats.card`: :class:`Card`, the base class of a text file with
  settings or commands.

The package exports these classes. The format of a tool's file lives with the
tool, such as :class:`omphjc.tools.madgraph.lhe_file.LHEFile`.
"""

from omphjc.formats.card import Card
from omphjc.formats.file_content import FileContent
from omphjc.formats.file_record import FileRecord

__all__ = [
    "Card",
    "FileContent",
    "FileRecord",
]
