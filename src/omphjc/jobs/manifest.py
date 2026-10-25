"""The manifest of a job, ``manifest.json``: what ran, with what, and what came out.

The manifest names the process and job number, the omphjc version that
created the job, and one record per stage::

    {
      "schema": 1,
      "process": "HToBB",
      "job_id": 1,
      "omphjc_version": "0.1.0",
      "stages": {
        "generate": {
          "status": "done",
          "started": "2026-10-23T01:00:00+00:00",
          "finished": "2026-10-23T01:20:00+00:00",
          "parameters": {"events": 1000, "seed": 10000001},
          "metadata": {
            "madgraph_version": "3.8.0",
            "events": 1000,
            "cross_section_pb": 1.23,
            "cross_section_error_pb": 0.01,
            "cards": {"generate/cards/run_card.dat": "<sha256>"}
          },
          "outputs": ["generate/HToBB/Events/run_01/unweighted_events.lhe.gz"],
          "log": "generate/madgraph.log",
          "usage": {"wall_seconds": 1203.4, "cpu_seconds": 9012.7, "peak_memory_mib": 812.5},
          "set_aside": null,
          "error": null
        }
      }
    }

``schema`` numbers this layout; a manifest of another schema is refused.
``status`` is ``"running"``, ``"done"`` or ``"failed"``. ``parameters`` is
what the stage was asked for, the seed included where the stage uses one, and
decides whether a later run may keep its result. ``metadata`` is what is known
about the stage and the sample it made; its keys are the stage's own.
``outputs``, ``log`` and ``set_aside`` are paths relative to the job
directory; ``set_aside`` names the folder into which the run moved what an
earlier run left and it could not confirm as that run's
(:mod:`omphjc.stamps`), ``null`` when it moved nothing. ``usage`` is what the
stage took: its wall time, and the CPU time and peak memory (MiB) of the
external program's processes where the platform reports them. The file is
replaced in one step whenever it changes, so a crash never leaves a
half-written manifest.

:class:`StageRecord` has one constructor per status. :meth:`StageRecord.running`
records a stage that has started, :meth:`StageRecord.failed` one that raised,
and :meth:`StageRecord.done` one that returned a :class:`StageOutcome`, whose
paths it makes relative to the job directory.
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omphjc import __version__

MANIFEST_FILE = "manifest.json"
SCHEMA_VERSION = 1

DONE = "done"
RUNNING = "running"
FAILED = "failed"


@dataclass(frozen=True)
class StageOutcome:
    """The result of a stage function, before the job records it.

    Parameters
    ----------
    metadata : dict
        What is known about the stage and the sample it made, as JSON values;
        the keys are the stage's own.
    outputs : list[Path]
        The files the stage made, inside the job directory.
    log_path : Path or None
        The log of the stage's program, inside the job directory.
    usage : dict[str, float]
        Resources the stage's program used, such as ``cpu_seconds`` and
        ``peak_memory_mib``; the job adds ``wall_seconds``.
    set_aside : Path or None
        The folder, inside the job directory, holding what an earlier run left
        and this run could not confirm as that run's (:mod:`omphjc.stamps`);
        ``None`` when nothing was moved.
    """

    metadata: dict[str, Any]
    outputs: list[Path]
    log_path: Path | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: Path | None = None


@dataclass
class StageRecord:
    """What one stage did; the module docstring describes the fields."""

    status: str
    started: str
    finished: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    log: str | None = None
    usage: dict[str, float] = field(default_factory=dict)
    set_aside: str | None = None
    error: str | None = None

    @classmethod
    def running(cls, *, started: str, parameters: dict[str, Any]) -> "StageRecord":
        """Return the record of a stage that has started."""
        return cls(status=RUNNING, started=started, parameters=parameters)

    @classmethod
    def failed(
        cls, *, started: str, parameters: dict[str, Any], error: str
    ) -> "StageRecord":
        """Return the record of a stage that has just raised `error`."""
        return cls(
            status=FAILED,
            started=started,
            finished=timestamp(),
            parameters=parameters,
            error=error,
        )

    @classmethod
    def done(
        cls,
        outcome: StageOutcome,
        *,
        started: str,
        parameters: dict[str, Any],
        wall_seconds: float,
        root_dir: Path,
    ) -> "StageRecord":
        """Return the record of a stage that has just returned `outcome`.

        The paths in `outcome` are made relative to `root_dir`, the job
        directory, and `wall_seconds` is added to its usage.
        """

        def relative(path: Path) -> str:
            return path.relative_to(root_dir).as_posix()

        return cls(
            status=DONE,
            started=started,
            finished=timestamp(),
            parameters=parameters,
            metadata=outcome.metadata,
            outputs=[relative(output) for output in outcome.outputs],
            log=None if outcome.log_path is None else relative(outcome.log_path),
            usage={"wall_seconds": round(wall_seconds, 3), **outcome.usage},
            set_aside=(
                None if outcome.set_aside is None else relative(outcome.set_aside)
            ),
        )


@dataclass
class Manifest:
    """The manifest of one job; the module docstring describes the fields."""

    process: str
    job_id: int
    omphjc_version: str = __version__
    stages: dict[str, StageRecord] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        """Write the manifest to `path`, replacing it in one step."""
        record = {"schema": SCHEMA_VERSION, **asdict(self)}
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manifest-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
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
            return cls(
                process=record["process"],
                job_id=record["job_id"],
                omphjc_version=record["omphjc_version"],
                stages={
                    name: StageRecord(**stage)
                    for name, stage in record["stages"].items()
                },
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None


def timestamp() -> str:
    """The current time in the manifest's format, ISO 8601 UTC to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
