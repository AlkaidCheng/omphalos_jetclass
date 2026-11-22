"""The result of a run of a tool: the record of each file it made or read.

A :class:`RunResult` holds the record of each output and of each card of a run
(:class:`~omphjc.data_files.FileRecord`), by name, and the metadata of the
run. The record of a task keeps the result of its latest run
(:mod:`omphjc.jobs.task`).

The module knows the event formats and nothing of a tool, a job or a command,
so that both a tool and the jobs layer can use it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omphjc.data_files import FileRecord
from omphjc.events.formats import EventFileRecord

EVENTS_OUTPUT = "events"
"""The name of the output that holds the events of a run, which the next stage reads."""


@dataclass(frozen=True)
class RunResult:
    """The result of a run: the record of each file it made or read.

    Parameters
    ----------
    outputs : dict[str, FileRecord]
        The record of each file the run made, by the name of the output. The
        events of the run are the
        :class:`~omphjc.events.formats.EventFileRecord` named
        :data:`EVENTS_OUTPUT`. A run that makes no events has no such output.
    cards : dict[str, FileRecord]
        The record of each card the program of the run read, by the name of
        the card (:meth:`omphjc.workspace.ProgramWorkspace.card_records`).
    metadata : dict
        What is known about the run and the sample it made, as JSON values.
        The code that ran the tool chooses the keys.
    """

    outputs: dict[str, FileRecord] = field(default_factory=dict)
    cards: dict[str, FileRecord] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any], root_dir: Path) -> "RunResult":
        """Return the result that `record` holds, with its paths under `root_dir`.

        `record` is the result as :func:`dataclasses.asdict` writes it. Each
        file is read back by its record class
        (:meth:`~omphjc.data_files.FileRecord.from_record`). An output
        recorded with a format is an
        :class:`~omphjc.events.formats.EventFileRecord`.
        """
        outputs = {
            name: (EventFileRecord if "format" in output else FileRecord).from_record(
                output, root_dir
            )
            for name, output in record["outputs"].items()
        }
        cards = {
            name: FileRecord.from_record(card, root_dir)
            for name, card in record["cards"].items()
        }
        return cls(outputs=outputs, cards=cards, metadata=record["metadata"])

    @property
    def events(self) -> EventFileRecord | None:
        """The record of the event file the run made, or ``None`` when it made none."""
        events = self.outputs.get(EVENTS_OUTPUT)
        return events if isinstance(events, EventFileRecord) else None
