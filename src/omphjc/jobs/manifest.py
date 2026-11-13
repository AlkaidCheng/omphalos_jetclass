"""The manifest of a job, ``manifest.json``: an index of the job's tasks.

The manifest names the job and lists each task that has a record, under the
name of the task::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "seed": 10000001,
      "omphjc_version": "0.1.0",
      "tasks": {
        "generate": {
          "status": "done",
          "latest_run_id": "20261023T020000Z-b81d07c3",
          "n_runs": 2,
          "record_path": "generate/task.json"
        }
      }
    }

``process``, ``job_id`` and ``seed`` identify the job as ``job.json`` does
(:mod:`omphjc.jobs.identity`), and ``omphjc_version`` is the version of omphjc
that wrote the manifest. A task has the ``status`` and the ID of the latest
run in its record (:mod:`omphjc.jobs.task`) and the number of runs in the
record, ``n_runs``. ``record_path`` is the path of the
record, relative to the job directory. :mod:`omphjc.jobs.record_file`
describes ``schema``.

The manifest is a summary of the records for a reader. A job writes it again
from the records whenever it writes the record of a task, and reads the
records themselves to decide what to run.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from omphjc.jobs.identity import JobIdentity
from omphjc.jobs.record_file import RecordFile


@dataclass(frozen=True)
class TaskSummary:
    """The summary of a task's record that the manifest lists.

    Parameters
    ----------
    status : str
        The status of the task, that of the latest run in its record.
    latest_run_id : str
        The ID of that run, which begins with its start time.
    n_runs : int
        The number of runs in the record.
    record_path : Path
        The file that holds the record of the task.
    """

    status: str
    latest_run_id: str
    n_runs: int
    record_path: Path


@dataclass(frozen=True)
class Manifest(RecordFile):
    """The manifest of one job.

    Parameters
    ----------
    identity : JobIdentity
        The process, the job number and the seed of the job.
    tasks : dict[str, TaskSummary]
        The tasks that have a record, by name.
    """

    file_name: ClassVar[str] = "manifest.json"

    identity: JobIdentity
    tasks: dict[str, TaskSummary] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        """Return the fields of the identity, then the tasks by name."""
        tasks = {name: asdict(entry) for name, entry in self.tasks.items()}
        return {**self.identity.as_record(), "tasks": tasks}

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "Manifest":
        """Return the manifest that `record` describes.

        The path of a task's record becomes an absolute path under `root_dir`.
        """
        tasks = {
            name: TaskSummary(
                status=entry["status"],
                latest_run_id=entry["latest_run_id"],
                n_runs=entry["n_runs"],
                record_path=root_dir / entry["record_path"],
            )
            for name, entry in record.pop("tasks").items()
        }
        return cls(identity=JobIdentity.from_record(record, root_dir), tasks=tasks)
