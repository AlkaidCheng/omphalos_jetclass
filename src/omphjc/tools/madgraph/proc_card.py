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
from pathlib import Path, PurePosixPath
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec
from omphjc.tools.madgraph.cards import proc_card_commands
from omphjc.tools.madgraph.referenced_card import ReferencedCard

# The commands that take a path, as
# omphjc.tools.madgraph.cards.proc_card_commands writes them.
_PATH_COMMANDS = ("import model", "output")

# Commands MadGraph writes at the top of every process card before user input.
_PREAMBLE_COMMANDS: tuple[str, ...] = (
    "import model sm",
    "define p = g u c d s u~ c~ d~ s~",
    "define j = g u c d s u~ c~ d~ s~",
    "define l+ = e+ mu+",
    "define l- = e- mu-",
    "define vl = ve vm vt",
    "define vl~ = ve~ vm~ vt~",
)

# Official model names that the catalogue provides under a vendored name.
_OFFICIAL_MODEL_ALIASES: dict[str, str] = {"heft-c_mass": "heft_c_mass_jetclass"}

# The process card among the official cards of a process.
_REFERENCE_FILE_NAME = "proc_card_mg5.dat"

# A backslash that ends a line, with the spaces and the line break after it.
# MadGraph removes them to join the line with the next one (ProcCard.write
# and ProcCard.read,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/various/banner.py#L960-L970
# and #L813-L829).
_LINE_CONTINUATION_PATTERN = re.compile(r"\\[^\S\n]*\n")


@dataclass(frozen=True)
class ProcCard(ReferencedCard):
    """The commands of a MadGraph process card.

    Parameters
    ----------
    commands : tuple[str, ...]
        The commands in the order of the card. Each command is written
        without its comment and with one space between its words. A command
        that the card holds on several lines is one command here.
    """

    format_name: ClassVar[str] = "proc_card"
    record_version: ClassVar[int] = 1

    commands: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "ProcCard":
        """Return the commands of a process card given as text."""
        joined = _LINE_CONTINUATION_PATTERN.sub("", text)
        lines = (
            " ".join(line.split("#", 1)[0].split()) for line in joined.splitlines()
        )
        return cls(commands=tuple(line for line in lines if line))

    @classmethod
    def from_process(cls, spec: ProcessSpec) -> "ProcCard":
        """Return the commands that define the process of `spec`.

        The ``output`` command is left out, and each model has the name the
        catalogue gives it.
        """
        written = cls.from_text(
            "\n".join(proc_card_commands(spec, output_dir=Path(spec.name)))
        )
        return cls(
            commands=tuple(
                _canonical_import(command)
                for command in written.commands
                if not command.startswith("output ")
            )
        )

    @classmethod
    def reference(cls, reference_dir: Path) -> "ProcCard":
        """Return the commands of the official card that define the process.

        The ``set`` and ``output`` commands are left out, and so are the
        commands that MadGraph writes at the top of every process card. A
        card that loads no model after those commands uses the Standard
        Model, so it gets the command ``import model sm``. Each model has the
        name the catalogue gives it.
        """
        card = cls.read(reference_dir / _REFERENCE_FILE_NAME)
        commands = [
            command
            for command in card.commands
            if not command.startswith(("set ", "output"))
        ]
        if tuple(commands[: len(_PREAMBLE_COMMANDS)]) == _PREAMBLE_COMMANDS:
            commands = commands[len(_PREAMBLE_COMMANDS) :]
        if not commands[0].startswith("import model"):
            commands.insert(0, "import model sm")
        return cls(commands=tuple(_canonical_import(command) for command in commands))

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


def _canonical_import(line: str) -> str:
    """Reduce an ``import model`` line to the bare catalogue model name."""
    if not line.startswith("import model "):
        return line
    target = line[len("import model ") :].strip()
    name = Path(target).name if "/" in target else target
    return f"import model {_OFFICIAL_MODEL_ALIASES.get(name, name)}"
