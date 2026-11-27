"""TextFile, the format of a text file that no tool's class reads."""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.formats.file_content import FileContent


@dataclass(frozen=True)
class TextFile(FileContent):
    """The text of a file.

    Parameters
    ----------
    text : str
        The text of the file, read as UTF-8.
    """

    format_name: ClassVar[str] = "text"
    record_version: ClassVar[int] = 1

    text: str

    @classmethod
    def read(cls, path: Path) -> "TextFile":
        """Return the text of the file at `path`, read as UTF-8."""
        return cls(path.read_text(encoding="utf-8"))

    def content_record(self) -> str:
        """Return the text."""
        return self.text
