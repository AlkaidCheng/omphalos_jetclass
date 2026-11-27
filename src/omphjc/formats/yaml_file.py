"""YAMLFile, the format of a YAML file that no tool's class reads."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml

from omphjc.formats.file_content import FileContent


class _CanonicalDumper(yaml.SafeDumper):
    """Writes a YAML value without anchors, so a repeated value is written out."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


@dataclass(frozen=True)
class YAMLFile(FileContent):
    """The parsed value of a YAML file.

    The content record is the value written back as YAML in one form, with
    the keys of each mapping sorted. Two files that hold the same value have
    the same record, whatever their layout and comments. YAML's tags keep the
    types apart, so the key ``25`` and the key ``"25"``, or a date and a quoted
    date, give two records.

    Parameters
    ----------
    value : Any
        The value that the file holds, as :func:`yaml.safe_load` returns it.
    """

    format_name: ClassVar[str] = "yaml"
    record_version: ClassVar[int] = 1

    value: Any

    @classmethod
    def read(cls, path: Path) -> "YAMLFile":
        """Return the value of the YAML file at `path`, read as UTF-8 text.

        Raises
        ------
        yaml.YAMLError
            If the file is not YAML.
        """
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def content_record(self) -> str:
        """Return the value written as YAML, with the keys of each mapping sorted."""
        return yaml.dump(self.value, Dumper=_CanonicalDumper, sort_keys=True)
