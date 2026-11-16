"""The multiparticles of MadGraph.

A multiparticle is a label for several particles, such as ``p`` for the
partons of the proton. A ``define`` command gives a label its members, and a
member may be a label that an earlier command defined.
:class:`Multiparticles` reads a list of such commands as MadGraph does and
holds the members that each label has after the last of them.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeGuard, cast

from omphjc.comparison import Difference

Members = list[str] | list[list[str]]
"""The members of a multiparticle, in the form in which MadGraph keeps them.

They are the names of its particles. A multiparticle that is defined with
``|`` has alternatives, and its members are one list of names for each
alternative.
"""


@dataclass(frozen=True)
class Multiparticles:
    """The multiparticles that MadGraph holds after a list of ``define`` commands.

    Parameters
    ----------
    members : dict[str, Members]
        The members of each multiparticle by its label. The labels come in
        the order in which they were first defined.
    """

    members: dict[str, Members]

    @classmethod
    def from_definitions(
        cls, definitions: Iterable[str], *, case_sensitive: bool = False
    ) -> "Multiparticles":
        """Return the multiparticles after the ``define`` commands `definitions`.

        The commands are read in their order, each as MadGraph 3.8.1 reads
        it (``do_define``, ``check_define`` and ``extract_particle_ids``,
        https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/madgraph_interface.py#L3612-L3645,
        #L942-L967 and #L6022-L6072, and ``expand_list_list``,
        https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/core/diagram_generation.py#L2178-L2216):

        - The label comes first, and the ``=`` after it may be left out.
        - A member that is the label of a multiparticle stands for the
          members which that multiparticle has at this command. Any other
          member is the name of a particle.
        - A particle that is named twice counts once, at its first place.
        - The particles named after ``/`` are taken out.
        - ``|`` separates alternatives. A multiparticle with alternatives
          that is named beside other members gives one alternative for each
          of its own. Among alternatives, ``/`` takes out a whole
          alternative, and only when the names after it are alternatives
          too.
        - A later definition of a label replaces the earlier one.

        MadGraph does three more things, which need its model and are left
        out. It refuses a member that the model does not hold and a label
        that names a particle of the model. It sorts the members by kind,
        keeping the written order within a kind (``optimize_order``,
        #L6074-L6090), where this class keeps the written order throughout.
        And when it loads a model, it changes ``p`` and ``j`` to the quarks
        that are massless there.

        Parameters
        ----------
        definitions : Iterable[str]
            The text of each ``define`` command after the word ``define``,
            such as ``"p = p b b~"``.
        case_sensitive : bool, optional
            Whether the names of the model depend on the case of their
            letters. MadGraph writes every name in lower case unless two
            particles of the model differ only in case
            (https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/models/import_ufo.py#L572-L578),
            which is the default here.

        Raises
        ------
        ValueError
            If MadGraph refuses a definition whatever the model: one without
            a member, one with ``=`` anywhere but after the label, or one
            that puts a multiparticle without members before other members.

        Examples
        --------
        A definition that adds to an earlier one, and two that take
        particles out. ``u`` counts once in ``gb``:

        >>> multiparticles = Multiparticles.from_definitions(
        ...     ["p = g u d", "p = p b b~", "q = p / g b~", "gb = p u / q"]
        ... )
        >>> multiparticles.members["p"]
        ['g', 'u', 'd', 'b', 'b~']
        >>> for definition in multiparticles.definitions():
        ...     print(definition)
        p = g u d b b~
        q = u d b
        gb = g b~

        Alternatives. ``h`` goes into each alternative of ``v``. The last
        definition takes out the alternative ``a``, which MadGraph does
        because ``a | h`` are alternatives; after ``/ a`` alone, ``a`` would
        stay:

        >>> multiparticles = Multiparticles.from_definitions(
        ...     ["v = z | a", "vh = v h", "boson = w+ w- | v", "rest = boson / a | h"]
        ... )
        >>> multiparticles.members["vh"]
        [['z', 'h'], ['a', 'h']]
        >>> for definition in multiparticles.definitions():
        ...     print(definition)
        v = z | a
        vh = z h | a h
        boson = w+ w- | z | a
        rest = w+ w- | z

        A label without a definition is taken for a particle:

        >>> Multiparticles.from_definitions(["lep = l+ l-"]).definitions()
        ['lep = l+ l-']
        >>> Multiparticles.from_definitions(
        ...     ["l+ = e+ mu+", "l- = e- mu-", "lep = l+ l-"]
        ... ).definitions()[-1]
        'lep = e+ mu+ e- mu-'
        """
        multiparticles = cls(members={})
        for definition in definitions:
            multiparticles._define(definition if case_sensitive else definition.lower())
        return multiparticles

    def definitions(self) -> list[str]:
        """Return one definition for each multiparticle, with its particles named.

        A definition has the form ``label = members``, and `` | `` stands
        between the alternatives of a multiparticle.
        """
        return [
            f"{label} = {self._written(members)}".rstrip()
            for label, members in self.members.items()
        ]

    def differences(self, reference: "Multiparticles") -> list[Difference]:
        """Return one difference for each multiparticle with other members.

        The item of a difference is ``define`` and the label. The order of
        the members counts. A multiparticle that one side lacks has the value
        ``None`` there.
        """
        return Difference.between_mappings(
            self.members,
            reference.members,
            text=self._written,
            name="define {}".format,
        )

    def _define(self, definition: str) -> None:
        """Give a label its members, as ``do_define`` and ``check_define`` do."""
        line = definition
        for separator in ("=", "|", "/"):
            line = line.replace(separator, f" {separator} ")
        # MadGraph also joins words in quotes or after a backslash, which the
        # names of particles do not hold.
        args = line.split()
        command = " ".join(["define", *definition.split()])
        problem = f'MadGraph cannot read "{command}"'
        if len(args) < 2:
            raise ValueError(f"{problem}: it needs a label and at least one member")
        if args[1] == "=":
            del args[1]
            if len(args) < 2:
                raise ValueError(f'{problem}: it needs a member after "="')
        if "=" in args:
            raise ValueError(f'{problem}: "=" may only follow the label')
        label = args[0]
        removed_names: list[str] = []
        if "/" in args:
            remove_index = args.index("/")
            removed_names = args[remove_index + 1 :]
            args = args[:remove_index]
        try:
            kept = self._extract(args[1:])
            removed = self._extract(removed_names)
        except IndexError:
            raise ValueError(
                f"{problem}: a multiparticle without members stands before "
                "other members"
            ) from None
        # A name is compared with names and an alternative with alternatives,
        # so the result has the form of `kept`.
        self.members[label] = cast(
            Members, [member for member in kept if member not in removed]
        )

    def _extract(self, names: list[str]) -> Members:
        """Return the members that `names` stand for, as ``extract_particle_ids``.

        MadGraph looks a name up among the particles of the model first. This
        class has no model, so a name that is no label is taken for a
        particle.
        """
        alternatives: list[list[Members]] = []
        parts: list[Members] = []
        for name in names:
            if name in self.members:
                parts.append(self.members[name])
            elif name == "|":
                if parts:
                    alternatives.append(parts)
                parts = []
            else:
                parts.append([name])
        alternatives.append(parts)
        expanded = [
            list(dict.fromkeys(members))
            for parts in alternatives
            for members in self._expand(parts)
        ]
        return expanded[0] if len(expanded) == 1 else expanded

    @classmethod
    def _expand(cls, parts: list[Members]) -> list[list[str]]:
        """Return every list of names that `parts` give, as ``expand_list_list``.

        A part with alternatives gives one list for each of them, each
        followed by what the later parts give.

        Raises
        ------
        IndexError
            If a part without members stands before other parts, where
            MadGraph fails in the same way.
        """
        if not parts or len(parts) == 1 and not parts[0]:
            return [[]]
        first = parts[0]
        starts = first if isinstance(first[0], list) else [first]
        if len(parts) == 1:
            return starts
        return [start + rest for start in starts for rest in cls._expand(parts[1:])]

    @staticmethod
    def _has_alternatives(members: Members) -> TypeGuard[list[list[str]]]:
        """Return whether `members` are alternatives, as ``multiparticle_string``."""
        return bool(members) and isinstance(members[0], list)

    @classmethod
    def _written(cls, members: Members) -> str:
        """Return `members` as a definition names them."""
        if cls._has_alternatives(members):
            return " | ".join(" ".join(alternative) for alternative in members)
        return " ".join(cast(list[str], members))
