"""Reporting of configuration differences."""

import operator
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

_ValueT = TypeVar("_ValueT")
_MemberT = TypeVar("_MemberT")


@dataclass(frozen=True)
class Difference:
    """One difference between a configuration and its reference.

    An item that only the reference holds is missing from the configuration.
    An item that only the configuration holds is unexpected.

    Parameters
    ----------
    item : str
        What differs, for example a module parameter or a decay chain.
    expected : str or None
        The reference value. It is ``None`` when the reference lacks the item.
    actual : str or None
        The value found. It is ``None`` when the configuration lacks the item.
    """

    item: str
    expected: str | None
    actual: str | None

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
        mapping lacks has the value ``None`` there.

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
                text(values[key]) if key in values else None
                for values in (reference, actual)
            )
            differences.append(cls(name(key), expected, found))
        return differences

    @classmethod
    def between_nested_mappings(
        cls, actual: Mapping[str, Any], reference: Mapping[str, Any]
    ) -> list["Difference"]:
        """Return the differences between two nested mappings, value by value.

        Where both mappings hold a mapping under one key, the two are compared
        in turn, and a difference inside them is named by the dotted path of
        its keys, such as ``pythia.Main:timesAllowErrors``. Otherwise a key is
        compared as :meth:`between_mappings` compares it, values written with
        :class:`str`. The differences come in the sorted order of the keys at
        each level.

        Parameters
        ----------
        actual : Mapping[str, Any]
            The values found, by key.
        reference : Mapping[str, Any]
            The reference values, by key.
        """

        def compare(
            found: Mapping[str, Any], expected: Mapping[str, Any], prefix: str
        ) -> Iterator[Difference]:
            for key in sorted(found.keys() | expected.keys()):
                path = f"{prefix}{key}"
                if key not in found:
                    yield cls(path, str(expected[key]), None)
                elif key not in expected:
                    yield cls(path, None, str(found[key]))
                elif isinstance(found[key], Mapping) and isinstance(
                    expected[key], Mapping
                ):
                    yield from compare(found[key], expected[key], f"{path}.")
                elif found[key] != expected[key]:
                    yield cls(path, str(expected[key]), str(found[key]))

        return list(compare(actual, reference, ""))

    @classmethod
    def between_collections(
        cls,
        actual: Collection[_MemberT],
        reference: Collection[_MemberT],
        *,
        item: str,
        text: Callable[[_MemberT], str] = str,
    ) -> list["Difference"]:
        """Return one difference for each member that only one collection holds.

        The members of `reference` alone come first, then the members of
        `actual` alone, each group in the order of its collection. The value
        of a difference is the member, on the side of the collection that
        holds it.

        Parameters
        ----------
        actual : Collection[_MemberT]
            The members found.
        reference : Collection[_MemberT]
            The reference members.
        item : str
            The item name of every difference, which says what a member is,
            such as ``"decay"``.
        text : callable, optional
            Returns a member as a difference writes it. Defaults to
            :class:`str`.
        """
        return [
            *(
                cls(item, text(member), None)
                for member in reference
                if member not in actual
            ),
            *(
                cls(item, None, text(member))
                for member in actual
                if member not in reference
            ),
        ]

    def __str__(self) -> str:
        """Return the difference as one line of a report."""
        if self.actual is None:
            return f"missing {self.item}: {self.expected}"
        if self.expected is None:
            return f"unexpected {self.item}: {self.actual}"
        return f"{self.item}: expected {self.expected}, got {self.actual}"
