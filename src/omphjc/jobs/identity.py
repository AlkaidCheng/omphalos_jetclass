"""The identity of a job, ``job.json``: its process, job number and seed.

The first task that runs in a job directory writes the file, and no later
task changes it::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "seed": 10000001,
      "omphjc_version": "0.1.0"
    }

``omphjc_version`` is the version of omphjc that wrote the file.
:mod:`omphjc.jobs.record_file` describes ``schema``.
"""

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

from omphjc import __version__
from omphjc.comparison import Difference
from omphjc.jobs.record_file import RecordFile


@dataclass(frozen=True)
class JobIdentity(RecordFile):
    """The process, the job number and the seed of one job.

    Two identities are equal when these three values are equal. The omphjc
    version does not count.

    Parameters
    ----------
    process : str
        The name of the process that the job generates.
    job_id : int
        The job number within the process.
    seed : int
        The seed of every program that the job runs.
    omphjc_version : str, optional
        The version of omphjc that created the job.
    """

    file_name: ClassVar[str] = "job.json"

    process: str
    job_id: int
    seed: int
    omphjc_version: str = field(default=__version__, compare=False)

    def as_record(self) -> dict[str, Any]:
        """Return the four fields by name."""
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any], root_dir: Path) -> "JobIdentity":
        """Return the identity that `record` describes."""
        return cls(**record)

    def differences(self, reference: "JobIdentity") -> list[Difference]:
        """Return one difference for each value that `reference` gives differently.

        A difference has the name of its field, and its expected value is
        the value of `reference`. The fields are the ones that count when two
        identities are compared, so two equal identities give no difference.
        """
        names = [field.name for field in fields(self) if field.compare]
        return Difference.between_mappings(
            {name: getattr(self, name) for name in names},
            {name: getattr(reference, name) for name in names},
        )
