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
- :mod:`omphjc.formats.json_file` and :mod:`omphjc.formats.yaml_file`:
  :class:`JSONFile` and :class:`YAMLFile`, the parsed value of a file, so the
  layout, the comments and the order of the keys are not part of the content.
- :mod:`omphjc.formats.text_file`: :class:`TextFile`, the text of a file.
- :mod:`omphjc.formats.binary_file`: :class:`BinaryFile`, the SHA-256 hash of
  the bytes of a file in a format that omphjc does not parse, such as Parquet
  or HDF5.

The generic formats, JSON, YAML, text and binary, read a file that no tool's
class reads, so every file that a run records has a fingerprint.

The package exports these classes. The format of a tool's file lives with the
tool, such as :class:`omphjc.tools.madgraph.lhe_file.LHEFile`.
"""

from omphjc.formats.binary_file import BinaryFile
from omphjc.formats.card import Card
from omphjc.formats.file_content import FileContent
from omphjc.formats.file_record import FileRecord
from omphjc.formats.json_file import JSONFile
from omphjc.formats.text_file import TextFile
from omphjc.formats.yaml_file import YAMLFile

__all__ = [
    "BinaryFile",
    "Card",
    "FileContent",
    "FileRecord",
    "JSONFile",
    "TextFile",
    "YAMLFile",
]
