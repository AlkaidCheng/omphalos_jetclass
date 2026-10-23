"""The manifest of a job, ``manifest.json``: what ran, with what, and what came out.

The manifest names the process and job number, the omphjc version that
created the job, and one record per stage::

    {
      "schema": 1,
      "process": "HToBB",
      "job": 1,
      "omphjc_version": "0.1.0",
      "stages": {
        "madgraph": {
          "status": "done",
          "started": "2026-10-23T01:00:00+00:00",
          "finished": "2026-10-23T01:20:00+00:00",
          "parameters": {"events": 1000, "seed": 10000001},
          "metadata": {
            "madgraph_version": "3.8.0",
            "events": 1000,
            "cross_section_pb": 1.23,
            "cross_section_error_pb": 0.01,
            "cards": {"madgraph/cards/run_card.dat": "<sha256>"}
          },
          "outputs": ["madgraph/HToBB/Events/run_01/unweighted_events.lhe.gz"],
          "log": "madgraph/madgraph.log",
          "error": null
        }
      }
    }

``schema`` numbers this layout; a manifest of another schema is refused.
``status`` is ``"running"``, ``"done"`` or ``"failed"``. ``parameters`` is
what the stage was asked for, the seed included where the stage uses one, and
decides whether a later run may keep its result. ``metadata`` is what is known
about the stage and the sample it made; its keys are the stage's own.
``outputs`` and ``log`` are paths relative to the job directory. The file is
replaced in one step whenever it changes, so a crash never leaves a
half-written manifest.
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
    error: str | None = None


@dataclass
class Manifest:
    """The manifest of one job; the module docstring describes the fields."""

    process: str
    job: int
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
                job=record["job"],
                omphjc_version=record["omphjc_version"],
                stages={
                    name: StageRecord(**stage)
                    for name, stage in record["stages"].items()
                },
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"{path} is not a manifest: {error}") from None


def now() -> str:
    """The current time in the manifest's format, ISO 8601 UTC to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
