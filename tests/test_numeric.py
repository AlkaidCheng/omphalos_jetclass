import math

import numpy as np
import pytest

from omphjc.numeric import require_number


def test_a_number_is_returned_as_the_kind_asked() -> None:
    assert require_number(3, what="n", kind=int) == 3
    assert type(require_number(3, what="x")) is float
    assert require_number(2.5, what="x", positive=True) == 2.5


def test_numpy_scalars_are_returned_as_python_numbers() -> None:
    assert type(require_number(np.int64(5), what="n", kind=int)) is int
    assert type(require_number(np.float32(1.5), what="x")) is float


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (True, int),
        (False, float),
        (np.bool_(True), int),
        ("3", int),
        ("3", float),
        (None, float),
        (1.0, int),
        (np.float64(1.0), int),
    ],
)
def test_a_value_that_is_not_a_number_of_the_kind_is_refused(
    value: object, kind: type[int] | type[float]
) -> None:
    noun = "an integer" if kind is int else "a number"
    with pytest.raises(TypeError, match=f"^n must be {noun}, got "):
        require_number(value, what="n", kind=kind)


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan, np.float32("inf")])
def test_a_number_that_is_not_finite_is_refused(value: float) -> None:
    with pytest.raises(ValueError, match="^x must be finite, got "):
        require_number(value, what="x")


@pytest.mark.parametrize(
    ("value", "kind"), [(0, int), (-1, int), (0.0, float), (-2.5, float)]
)
def test_a_number_that_is_not_positive_is_refused_when_asked(
    value: float, kind: type[int] | type[float]
) -> None:
    assert require_number(value, what="x", kind=kind) == value
    with pytest.raises(ValueError, match="^x must be positive, got "):
        require_number(value, what="x", kind=kind, positive=True)
