"""The process card of MadGraph.

A process card is a list of MadGraph commands, one on each line, with comments
after ``#``. The commands load the model, define the particles and the
processes, and name the directory that MadGraph writes the process to.

MadGraph writes a command longer than 70 characters on several lines. Every
line of such a command except the last ends in a backslash, and MadGraph joins
the lines into one command when it reads the card.

A ``define`` command names the members of a multiparticle, and a member may be
a multiparticle that an earlier command defined.
:meth:`ProcCard.multiparticles` returns the members that every multiparticle
has after the last command.
"""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec
from omphjc.processes.input_card import InputCard
from omphjc.tools.madgraph.cards import proc_card_commands
from omphjc.tools.madgraph.multiparticles import Multiparticles

# The commands that take a path, as
# omphjc.tools.madgraph.cards.proc_card_commands writes them.
_PATH_COMMANDS = ("import model", "output")

# The commands that MadGraph writes at the top of every process card, before
# those of the user: the Standard Model, and the multiparticles of
# input/multiparticles_default.txt,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/input/multiparticles_default.txt#L16-L21.
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

# A backslash that ends a line, with the spaces and the line break after it.
# MadGraph removes them to join the line with the next one (ProcCard.write
# and ProcCard.read,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/various/banner.py#L960-L970
# and #L813-L829).
_LINE_CONTINUATION_PATTERN = re.compile(r"\\[^\S\n]*\n")


@dataclass(frozen=True)
class ProcCard(InputCard):
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
    reference_file_name: ClassVar[str] = "proc_card_mg5.dat"
    card_name: ClassVar[str] = "proc_card"
    file_name: ClassVar[str] = "proc_card_mg5.dat"
    description: ClassVar[str] = "The process card that MadGraph writes on output."

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
    def reference(cls, reference_dir: Path) -> "ProcCard | None":
        """Return the commands of the official card that define the process.

        The ``set`` and ``output`` commands are left out, and each model has
        the name the catalogue gives it. The commands that MadGraph writes at
        the top of every process card stay, since the definitions after them
        add to the multiparticles that they define. The result is ``None``
        when `reference_dir` holds no process card.
        """
        card = super().reference(reference_dir)
        if card is None:
            return None
        return cls(
            commands=tuple(
                _canonical_import(command)
                for command in card.commands
                if not command.startswith(("set ", "output"))
            )
        )

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

    def multiparticles(self) -> Multiparticles:
        """Return the multiparticles that the ``define`` commands of the card leave.

        The commands are read in their order, as MadGraph reads them
        (:meth:`Multiparticles.from_definitions`), so a multiparticle that
        the card defines twice has the members of its last definition. The
        other commands of the card are not read: a change that MadGraph makes
        to a multiparticle when it loads a model depends on the model and on
        the version of MadGraph.

        Raises
        ------
        ValueError
            If MadGraph refuses a definition whatever the model.
        """
        return Multiparticles.from_definitions(
            command.removeprefix("define")
            for command in self.commands
            if self._is_definition(command)
        )

    def differences(self, reference: "ProcCard") -> list[Difference]:
        """Return one difference when the content records are not equal.

        The order of the commands counts, so the difference holds every
        command of each record, joined with `` | ``.
        """
        record, expected = self.content_record(), reference.content_record()
        if record == expected:
            return []
        return [Difference("commands", " | ".join(expected), " | ".join(record))]

    def checked_differences(self, reference: "ProcCard") -> list[Difference]:
        """Return the differences from `reference` that a check reports.

        The ``define`` commands are compared by the multiparticles they leave
        (:meth:`multiparticles`), one difference for each multiparticle with
        other members. A multiparticle counts with the members it has after
        the last command, wherever its definitions stand among the other
        commands. The other commands are compared in their order
        (:meth:`differences`).

        An official card starts with the commands that MadGraph writes at the
        top of every process card, and this card, which the catalogue states,
        has none of them. Its definitions are therefore read after those
        commands. ``define p = p b b~`` then adds to the same ``p`` in both
        cards, and a multiparticle that neither card defines, such as ``l+``,
        has the same members in both. The other commands are compared from
        the first one after them.

        A reference that loads no model after those commands uses the
        Standard Model, so it gets the command ``import model sm``. A
        reference without those commands is compared from its first command.

        Raises
        ------
        ValueError
            If a card holds a definition that MadGraph refuses whatever the
            model.
        """
        count = len(_PREAMBLE_COMMANDS)
        preamble, stated = reference.commands[:count], reference.commands[count:]
        if preamble != _PREAMBLE_COMMANDS:
            preamble, stated = (), reference.commands
        others = ProcCard(commands=stated)._without_definitions().commands
        if not others or not others[0].startswith("import model"):
            others = ("import model sm", *others)
        after_preamble = ProcCard(commands=(*preamble, *self.commands))
        return [
            *self._without_definitions().differences(ProcCard(commands=others)),
            *after_preamble.multiparticles().differences(reference.multiparticles()),
        ]

    def _without_definitions(self) -> "ProcCard":
        """Return the card without its ``define`` commands."""
        return ProcCard(
            commands=tuple(
                command for command in self.commands if not self._is_definition(command)
            )
        )

    @staticmethod
    def _is_definition(command: str) -> bool:
        """Return whether `command` is a ``define`` command."""
        return command.split(maxsplit=1)[:1] == ["define"]


def _canonical_import(line: str) -> str:
    """Reduce an ``import model`` line to the bare catalogue model name."""
    if not line.startswith("import model "):
        return line
    target = line[len("import model ") :].strip()
    name = Path(target).name if "/" in target else target
    return f"import model {_OFFICIAL_MODEL_ALIASES.get(name, name)}"
