"""The identity of a job and the identity of a task.

**A job** is identified by its process, its job number and its seed
(:class:`JobIdentity`), which are kept in ``job.json``. The first task that
runs in a job directory writes the file, and no later task changes it::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "seed": 10000001,
      "omphjc_version": "0.1.0"
    }

``omphjc_version`` is the version of omphjc that wrote the file.
:mod:`omphjc.jobs.record_file` describes ``schema``.

**A task** is identified in its job by its stage, its tool and its tag
(:class:`TaskIdentity`). A stage can have several tasks, which differ in
the tool or in the tag. The record of a task holds its identity
(:mod:`omphjc.jobs.task`), and the directory of the task is named after it.
"""

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar

from omphjc import __version__
from omphjc.comparison import Difference
from omphjc.jobs.record_file import RecordFile
from omphjc.safe_paths import require_plain_name


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


@dataclass(frozen=True)
class TaskIdentity:
    """The stage, the tool and the tag of one task of a job.

    Parameters
    ----------
    stage : str
        The name of the task's stage, such as ``"shower"``.
    tool : str
        The name of the tool that the task is named after, such as
        ``"pythia"``.
    tag : str or None, optional
        A label that tells the task apart from another task of the same
        stage and tool. Most tasks have none.

    Raises
    ------
    ValueError
        If the stage, the tool or the tag is not a plain name
        (:func:`omphjc.safe_paths.require_plain_name`).
    """

    stage: str
    tool: str
    tag: str | None = None

    def __post_init__(self) -> None:
        require_plain_name(self.stage, what="Stage name")
        require_plain_name(self.tool, what="Tool name")
        if self.tag is not None:
            require_plain_name(self.tag, what="Tag")

    def __str__(self) -> str:
        """Return the stage, the tool and the tag in words, as a message writes them."""
        tag = "no tag" if self.tag is None else f"tag {self.tag!r}"
        return f"stage {self.stage!r}, tool {self.tool!r} and {tag}"

    @property
    def name(self) -> str:
        """The name of the task in its job, such as ``"shower-pythia"``.

        It is the stage and the tool, followed by the tag when the task has
        one. The directory of the task has this name.
        """
        parts = [self.stage, self.tool, *([] if self.tag is None else [self.tag])]
        return "-".join(parts)

    @property
    def command(self) -> str:
        """The command that runs the task, as a message names it."""
        return f"omphjc {self.stage}"
