"""Reporting of configuration differences."""

import operator
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import TypeVar

_ValueT = TypeVar("_ValueT")
_MemberT = TypeVar("_MemberT")

# The values of an item that only one side holds.
_PRESENT = "present"
_ABSENT = "absent"


@dataclass(frozen=True)
class Difference:
    """One difference between a configuration and its reference.

    Parameters
    ----------
    item : str
        What differs, for example a module parameter or a decay chain.
    expected : str
        The reference value.
    actual : str
        The value found.
    """

    item: str
    expected: str
    actual: str

    @classmethod
    def between_mappings(
        cls,
        actual: Mapping[str, _ValueT],
        reference: Mapping[str, _ValueT],
        *,
        equal: Callable[[_ValueT, _ValueT], bool] = operator.eq,
        text: Callable[[_ValueT], str] = str,
        name: Callable[[str], str] = str,
    ) -> list["Difference"]:
        """Return one difference for each key with two different values.

        The differences come in the sorted order of the keys. A key that one
        mapping lacks has the value ``absent`` there.

        Parameters
        ----------
        actual : Mapping[str, _ValueT]
            The values found, by key.
        reference : Mapping[str, _ValueT]
            The reference values, by key.
        equal : callable, optional
            Returns whether two values are equal. Defaults to ``==``.
        text : callable, optional
            Returns a value as a difference writes it. Defaults to
            :class:`str`.
        name : callable, optional
            Returns the item name of a key. Defaults to the key.
        """
        differences = []
        for key in sorted(actual.keys() | reference.keys()):
            in_both = key in actual and key in reference
            if in_both and equal(actual[key], reference[key]):
                continue
            expected, found = (
                text(values[key]) if key in values else _ABSENT
                for values in (reference, actual)
            )
            differences.append(cls(name(key), expected, found))
        return differences

    @classmethod
    def between_collections(
        cls,
        actual: Collection[_MemberT],
        reference: Collection[_MemberT],
        *,
        name: Callable[[_MemberT], str] = str,
    ) -> list["Difference"]:
        """Return one difference for each member that only one collection holds.

        The members of `reference` alone come first, then the members of
        `actual` alone, each group in the order of its collection. A member
        has the value ``present`` in the collection that holds it and
        ``absent`` in the other.

        Parameters
        ----------
        actual : Collection[_MemberT]
            The members found.
        reference : Collection[_MemberT]
            The reference members.
        name : callable, optional
            Returns the item name of a member. Defaults to :class:`str`.
        """
        return [
            cls(name(member), expected, found)
            for members, others, expected, found in (
                (reference, actual, _PRESENT, _ABSENT),
                (actual, reference, _ABSENT, _PRESENT),
            )
            for member in members
            if member not in others
        ]

    def __str__(self) -> str:
        return f"{self.item}: expected {self.expected}, got {self.actual}"
