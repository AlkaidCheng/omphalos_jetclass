"""The JSON files in which a job records what it is and what it ran.

Each kind of file has one class, and every such class is a
:class:`RecordFile`. An object of the class holds the content of one file.
The class states how the content is written down as JSON values
(:meth:`RecordFile.as_record`) and how it is built from them
(:meth:`RecordFile.from_record`). Writing and reading are the same for every
kind of file.

Every file holds the field ``schema``, which numbers the layout of the job
files. A file of another schema is refused.

A file that cannot be read is refused with a :class:`RecordFileError`, which
names the file and what is wrong with it. A class of file may refuse its files
with a subclass that also says how to go on.
"""

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, TypeVar

SCHEMA_VERSION = 1

_RecordFileT = TypeVar("_RecordFileT", bound="RecordFile")


class RecordFileError(ValueError):
    """A file of a job that cannot be read as the content of its class.

    The message names the file and says what is wrong with it. When the error
    knows how to go on, the message ends with that.

    Parameters
    ----------
    path : Path
        The file.
    problem : str
        What is wrong with the file, said of it, such as ``"has no schema field"``.
    remedy : str, optional
        The likely cause and the ways to go on.
    """

    def __init__(self, path: Path, problem: str, remedy: str | None = None) -> None:
        super().__init__(path, problem, remedy)
        self.path = path
        self.problem = problem
        self.remedy = remedy

    def __str__(self) -> str:
        message = f"{self.path} {self.problem}"
        return message if self.remedy is None else f"{message}.\n{self.remedy}"


class RecordFile(ABC):
    """The content of one JSON file of a job.

    Attributes
    ----------
    file_name : str
        The name of the file, such as ``"manifest.json"``.
    read_error : type
        The :class:`RecordFileError` class with which :meth:`read` refuses a file
        of this class.
    """

    file_name: ClassVar[str]
    read_error: ClassVar[type[RecordFileError]] = RecordFileError

    @abstractmethod
    def as_record(self) -> dict[str, Any]:
        """Return the content as a mapping of JSON values.

        A value may also be a :class:`~pathlib.Path`. :meth:`write` writes
        it as a relative path.
        """

    @classmethod
    @abstractmethod
    def from_record(
        cls: type[_RecordFileT], record: dict[str, Any], root_dir: Path
    ) -> _RecordFileT:
        """Return the content that `record` describes.

        Parameters
        ----------
        record : dict
            The mapping read from the file, without its ``schema`` field.
        root_dir : Path
            The directory that the paths in `record` are relative to.
        """

    def create(self, path: Path) -> None:
        """Write the content to `path`, which must not exist yet.

        Raises
        ------
        FileExistsError
            If something is already at `path`, a symbolic link included.
        ValueError
            If the content names a path outside the directory of `path`.
        """
        text = self._json_text(path.parent)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)

    def write(self, path: Path, *, root_dir: Path | None = None) -> None:
        """Write the content to `path`, replacing the file in one step.

        A crash during the write leaves the earlier file as it was.

        Parameters
        ----------
        path : Path
            The file to write.
        root_dir : Path, optional
            The directory that the paths in the file are relative to. It is
            the directory of `path` unless given.

        Raises
        ------
        ValueError
            If the content names a path outside `root_dir`.
        """
        text = self._json_text(path.parent if root_dir is None else root_dir)
        descriptor, temporary_path = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}-"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary_path, path)

    @classmethod
    def read(
        cls: type[_RecordFileT], path: Path, *, root_dir: Path | None = None
    ) -> _RecordFileT:
        """Return the content of the file at `path`.

        Parameters
        ----------
        path : Path
            The file to read.
        root_dir : Path, optional
            The directory that the paths in the file are relative to. It is
            the directory of `path` unless given.

        Raises
        ------
        RecordFileError
            If the file is not JSON, has no ``schema`` field, was written
            with another schema, or does not hold the fields of this class.
            The error is a :attr:`read_error`.
        """
        try:
            record: Any = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise cls.read_error(path, f"is not valid JSON: {error}") from None
        if not isinstance(record, dict) or "schema" not in record:
            raise cls.read_error(path, "has no schema field")
        schema = record.pop("schema")
        if schema != SCHEMA_VERSION:
            raise cls.read_error(
                path,
                f"was written with schema {schema}; this version of omphjc reads "
                f"schema {SCHEMA_VERSION}",
            )
        try:
            return cls.from_record(
                record, path.parent if root_dir is None else root_dir
            )
        except (KeyError, TypeError, ValueError) as error:
            raise cls.read_error(path, f"has invalid content: {error}") from None

    def _json_text(self, root_dir: Path) -> str:
        """Return the text of the file, with each path relative to `root_dir`."""

        def relative_path(value: object) -> str:
            if isinstance(value, Path):
                return value.relative_to(root_dir).as_posix()
            raise TypeError(f"{value!r} is not a JSON value")

        record = {"schema": SCHEMA_VERSION, **self.as_record()}
        return json.dumps(record, indent=2, default=relative_path) + "\n"
