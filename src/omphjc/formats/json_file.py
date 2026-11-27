"""JSONFile, the format of a JSON file that no tool's class reads."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from omphjc.formats.file_content import FileContent


@dataclass(frozen=True)
class JSONFile(FileContent):
    """The parsed value of a JSON file.

    Parameters
    ----------
    value : Any
        The value that the file holds, as :func:`json.loads` returns it.
    """

    format_name: ClassVar[str] = "json"
    record_version: ClassVar[int] = 1

    value: Any

    @classmethod
    def read(cls, path: Path) -> "JSONFile":
        """Return the value of the JSON file at `path`, read as UTF-8 text.

        Raises
        ------
        ValueError
            If the file is not JSON.
        """
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def content_record(self) -> Any:
        """Return the value."""
        return self.value
