"""Checks of the numbers that callers and configuration files pass."""

import math
from numbers import Integral, Real
from typing import Any, overload


@overload
def require_number(
    value: object, *, what: str, kind: type[int], positive: bool = False
) -> int: ...


@overload
def require_number(
    value: object, *, what: str, kind: type[float] = float, positive: bool = False
) -> float: ...


def require_number(
    value: object,
    *,
    what: str,
    kind: type[int] | type[float] = float,
    positive: bool = False,
) -> Any:
    """Return `value` as a finite number of type `kind`, refusing any other value.

    With `kind` int only an integer is accepted; with float an integer is
    accepted too and returned as a float. A bool is refused either way, though
    Python counts it as an int, so a YAML ``true`` is not read as 1. NumPy
    scalars are accepted and returned as Python numbers.

    Parameters
    ----------
    value : object
        The value to check.
    what : str
        What the value is, for the error message, such as ``"ctau_min_mm"``.
    kind : {int, float}, optional
        The type of number to return.
    positive : bool, optional
        Whether the number must be greater than zero.

    Returns
    -------
    int or float
        `value` as a `kind`.

    Raises
    ------
    TypeError
        If `value` is a bool or not a number of type `kind`.
    ValueError
        If `value` is not finite, or not positive when `positive` is set.
    """
    number = _as_number(value, kind)
    if number is None:
        noun = "an integer" if kind is int else "a number"
        raise TypeError(f"{what} must be {noun}, got {value!r}")
    if not math.isfinite(number):
        raise ValueError(f"{what} must be finite, got {value!r}")
    if positive and number <= 0:
        raise ValueError(f"{what} must be positive, got {value!r}")
    return number


def _as_number(value: object, kind: type[int] | type[float]) -> int | float | None:
    """Return `value` as a `kind`; None for a bool or a value of another type."""
    if isinstance(value, bool):
        return None
    if kind is int:
        return int(value) if isinstance(value, Integral) else None
    return float(value) if isinstance(value, Real) else None
