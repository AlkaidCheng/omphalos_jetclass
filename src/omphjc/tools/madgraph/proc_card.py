"""The process card of MadGraph.

A process card is a list of MadGraph commands, one on each line, with comments
after ``#``. The commands load the model, define the particles and the
processes, and name the directory that MadGraph writes the process to.

MadGraph writes a command longer than 70 characters on several lines. Every
line of such a command except the last ends in a backslash, and MadGraph joins
the lines into one command when it reads the card.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.data_files import Card

# The commands that take a path, as
# omphjc.tools.madgraph.cards.proc_card_commands writes them.
_PATH_COMMANDS = ("import model", "output")

# A backslash that ends a line, with the spaces and the line break after it.
# MadGraph removes them to join the line with the next one (ProcCard.write
# and ProcCard.read,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/various/banner.py#L960-L970
# and #L813-L829).
_LINE_CONTINUATION_PATTERN = re.compile(r"\\[^\S\n]*\n")


@dataclass(frozen=True)
class ProcCard(Card):
    """The commands of a MadGraph process card.

    Parameters
    ----------
    commands : tuple[str, ...]
        The commands in the order of the card. Each command is written
        without its comment and with one space between its words. A command
        that the card holds on several lines is one command here.
    """

    record_scheme: ClassVar[str] = "proc-card-v1"

    commands: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "ProcCard":
        """Return the commands of a process card given as text."""
        joined = _LINE_CONTINUATION_PATTERN.sub("", text)
        lines = (
            " ".join(line.split("#", 1)[0].split()) for line in joined.splitlines()
        )
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

    def differences(self, reference: "ProcCard") -> list[Difference]:
        """Return one difference when the content records are not equal.

        The order of the commands counts, so the difference holds every
        command of each record, joined with `` | ``.
        """
        record, expected = self.content_record(), reference.content_record()
        if record == expected:
            return []
        return [Difference("commands", " | ".join(expected), " | ".join(record))]
