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

:mod:`omphjc.jobs.record_file` describes ``schema`` and
:mod:`omphjc.jobs.task` the record of a task. The file is replaced in one
step whenever it changes, so a crash never leaves a half-written manifest.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from omphjc import __version__
from omphjc.jobs.record_file import RecordFile
from omphjc.jobs.task import TaskRecord, TaskResult


@dataclass
class Manifest(RecordFile):
    """The manifest of one job; the module docstring describes the fields."""

    file_name: ClassVar[str] = "manifest.json"

    process: str
    job_id: int
    omphjc_version: str = __version__
    stages: dict[str, TaskRecord] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        """Return the fields, with the record of each task by its stage."""
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "Manifest":
        """Return the manifest that `record` describes.

        A path in a result becomes an absolute path under `root_dir`.
        """
        stages = {}
        for name, stage in record["stages"].items():
            result = TaskResult.from_record(stage.pop("result"), root_dir)
            stages[name] = TaskRecord(**stage, result=result)
        return cls(
            process=record["process"],
            job_id=record["job_id"],
            omphjc_version=record["omphjc_version"],
            stages=stages,
        )
