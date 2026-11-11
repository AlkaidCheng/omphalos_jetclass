"""The process card of MadGraph.

A process card is a list of MadGraph commands, one on each line, with comments
after ``#``. The commands load the model, define the particles and the
processes, and name the directory that MadGraph writes the process to.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from omphjc.data_files import Card

# The commands that take a path, as
# omphjc.tools.madgraph.cards.proc_card_commands writes them.
_PATH_COMMANDS = ("import model", "output")


@dataclass(frozen=True)
class ProcCard(Card):
    """The commands of a MadGraph process card.

    Parameters
    ----------
    commands : tuple[str, ...]
        The commands in the order of the card. Each command is written
        without its comment and with one space between its words.
    """

    record_scheme: ClassVar[str] = "proc-card-v1"

    commands: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "ProcCard":
        """Return the commands of a process card given as text."""
        lines = (" ".join(line.split("#", 1)[0].split()) for line in text.splitlines())
        return cls(commands=tuple(line for line in lines if line))

    def content_record(self) -> list[str]:
        """Return the commands, with every path cut down to its last part.

        The commands ``import model`` and ``output`` take a path. The
        directories of that path differ from job to job, and the last part
        names the model or the process.
        """
        record = []
        for line in self.commands:
            for command in _PATH_COMMANDS:
                if line.startswith(f"{command} "):
                    target, *options = line.removeprefix(f"{command} ").split()
                    line = " ".join([command, PurePosixPath(target).name, *options])
            record.append(line)
        return record
