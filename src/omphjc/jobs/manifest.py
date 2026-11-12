"""The manifest of a job, ``manifest.json``: what ran, with what, and what came out.

The manifest names the process and job number, the omphjc version that
created the job, and one record per task, the work of one stage in the
job, under the stage's name::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "omphjc_version": "0.1.0",
      "stages": {
        "generate": {"status": "done", "started": "2026-10-23T01:00:00+00:00", ...}
      }
    }

``schema`` numbers this layout; a manifest of another schema is refused.
:mod:`omphjc.jobs.records` describes the record of a task. The file is
replaced in one step whenever it changes, so a crash never leaves a
half-written manifest.
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from omphjc import __version__
from omphjc.jobs.records import TaskRecord, TaskResult

MANIFEST_FILE = "manifest.json"
SCHEMA_VERSION = 1


@dataclass
class Manifest:
    """The manifest of one job; the module docstring describes the fields."""

    process: str
    job_id: int
    omphjc_version: str = __version__
    stages: dict[str, TaskRecord] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        """Write the manifest to `path`, replacing it in one step.

        A path in a result is written relative to the directory of `path`.

        Raises
        ------
        ValueError
            If a result names a path outside that directory.
        """

        def relative_path(value: object) -> str:
            if isinstance(value, Path):
                return value.relative_to(path.parent).as_posix()
            raise TypeError(f"{value!r} is not a JSON value")

        record = {"schema": SCHEMA_VERSION, **asdict(self)}
        text = json.dumps(record, indent=2, default=relative_path)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manifest-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
        os.replace(temporary, path)

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        """Read the manifest at `path`.

        Raises
        ------
        ValueError
            If the file is not a manifest of a known schema.
        """
        try:
            record: Any = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None
        if not isinstance(record, dict) or "schema" not in record:
            raise ValueError(f"{path} is not a manifest: no schema field")
        if record["schema"] != SCHEMA_VERSION:
            raise ValueError(
                f"{path} was written with manifest schema {record['schema']}; this "
                f"version of omphjc reads schema {SCHEMA_VERSION}"
            )
        try:
            stages = {}
            for name, stage in record["stages"].items():
                result = TaskResult.from_record(stage.pop("result"), path.parent)
                stages[name] = TaskRecord(**stage, result=result)
            return cls(
                process=record["process"],
                job_id=record["job_id"],
                omphjc_version=record["omphjc_version"],
                stages=stages,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None
