"""Reporting of configuration differences."""

from dataclasses import dataclass


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

    def __str__(self) -> str:
        return f"{self.item}: expected {self.expected}, got {self.actual}"
