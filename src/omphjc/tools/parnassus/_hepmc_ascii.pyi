"""Parnassus's input in HepMC3's ASCII format, built and written in C++."""

from typing import Any

import numpy as np
import numpy.typing as npt

_Reals = npt.NDArray[np.float32] | npt.NDArray[np.float64]

def format_events(
    particle_counts: npt.NDArray[np.int64],
    event_numbers: npt.NDArray[np.int64],
    pid: npt.NDArray[np.int32],
    status: npt.NDArray[np.int32],
    mother: npt.NDArray[np.int32],
    is_final: npt.NDArray[np.bool_],
    px: _Reals,
    py: _Reals,
    pz: _Reals,
    e: _Reals,
    mass: _Reals,
    x: _Reals,
    y: _Reals,
    z: _Reals,
    t: _Reals,
    precision: int,
    threads: int = 1,
) -> tuple[bytes, int, str]: ...
def to_hepevt(
    particle_counts: npt.NDArray[np.int64],
    event_numbers: npt.NDArray[np.int64],
    pid: npt.NDArray[np.int32],
    status: npt.NDArray[np.int32],
    mother: npt.NDArray[np.int32],
    is_final: npt.NDArray[np.bool_],
    px: _Reals,
    py: _Reals,
    pz: _Reals,
    e: _Reals,
    mass: _Reals,
    x: _Reals,
    y: _Reals,
    z: _Reals,
    t: _Reals,
) -> dict[str, Any]: ...
