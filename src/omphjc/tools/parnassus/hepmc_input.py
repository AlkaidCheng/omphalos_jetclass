"""Parnassus's input: the final state of the shower's events as a HepMC3 file.

Parnassus's generate pipeline picks its dataset by the input file's suffix,
lower-cased, and reads HepMC3 ASCII only from a ``.hepmc`` file, which it opens
uncompressed (``build_dataset`` in ``src/parnassus/data/__init__.py`` at
c9f8bd9e4c, https://github.com/parnassus-hep/parnassus). Of each particle it
reads the PDG id, status, momentum, generated mass and production position, and
of each event its number; it never follows mother or daughter links. The file
therefore holds the smallest valid record of each event: the two beams; every
final particle, with status 1, promoted long-lived particles among them; and,
once, the mother of each final particle produced away from the origin, with
its own status.

Parnassus finds a particle's production position only as the position of the
vertex line the particle names as its parent; a particle whose parent is
another particle's number is read at the origin without a warning
(``_assign_vertices_and_events`` in ``src/parnassus/data/hepmc.py`` at
c9f8bd9e4c). A displaced final particle therefore takes its mother as its
parent, which makes the mother's end a vertex at the daughters' common
position, and every other particle takes the beams, whose vertex is the origin.

The text is what HepMC3's own ``WriterAscii`` of HepMC3 3.3.1 writes for these
events (``src/WriterAscii.cc`` at 3.3.1, https://gitlab.cern.ch/hepmc/HepMC3),
in GeV and mm, with the vertices numbered in the order they appear.
"""

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

import awkward as ak
import numpy as np
import numpy.typing as npt

from omphjc.numeric import require_number
from omphjc.tools.parnassus import _hepmc_ascii

# Parnassus's generate pipeline reads HepMC3 ASCII only from a file with this
# suffix, compared lower-cased (build_dataset in src/parnassus/data/__init__.py
# at c9f8bd9e4c, https://github.com/parnassus-hep/parnassus).
HEPMC_SUFFIX = ".hepmc"

# The HepMC3 release whose WriterAscii the file follows, and the lines that
# writer puts before the first event and after the last (include/HepMC3/Version.h
# and src/WriterAscii.cc at 3.3.1, https://gitlab.cern.ch/hepmc/HepMC3).
HEPMC3_VERSION = "3.03.01"
_HEADER = f"HepMC::Version {HEPMC3_VERSION}\nHepMC::Asciiv3-START_EVENT_LISTING\n"
_FOOTER = "HepMC::Asciiv3-END_EVENT_LISTING\n\n"

# Digits after the decimal point of each number, which HepMC3 writes in exponent
# form: 8 give 9 significant digits, from which any float32 is read back
# unchanged (FLT_DECIMAL_DIG of IEEE binary32, 1 + ceil(24 log10 2); ISO C11
# 5.2.4.2.2). WriterAscii::set_precision takes 2 to 24 digits and ignores any
# other number (src/WriterAscii.cc at 3.3.1).
DEFAULT_PRECISION = 8
PRECISION_RANGE = (2, 24)

# HepMC3 keeps an event's number as an int (GenEvent::event_number,
# include/HepMC3/GenEvent.h at 3.3.1).
_EVENT_NUMBER_RANGE = (np.iinfo(np.int32).min, np.iinfo(np.int32).max)

# The fields of the particle record the input is made of, by the type the
# extension takes them as.
EVENT_COLUMN = "event_index"
_INTEGER_COLUMNS = ("part_pid", "part_status", "part_m1")
_REAL_COLUMNS = (
    "part_px",
    "part_py",
    "part_pz",
    "part_e",
    "part_mass",
    "part_x",
    "part_y",
    "part_z",
    "part_t",
)
PARTICLE_COLUMNS = (*_INTEGER_COLUMNS, "part_final", *_REAL_COLUMNS)


class HepevtArrays(NamedTuple):
    """One event's record as HEPEVT arrays.

    The two beams come first. Indices count from 0, and ``parents`` holds the
    first and last parent of each particle, ``(-1, -1)`` for none. Momenta and
    masses are in GeV, positions in mm, the time as c t.
    """

    event_number: int
    pid: npt.NDArray[np.int32]
    status: npt.NDArray[np.int32]
    px: npt.NDArray[np.float64]
    py: npt.NDArray[np.float64]
    pz: npt.NDArray[np.float64]
    e: npt.NDArray[np.float64]
    m: npt.NDArray[np.float64]
    parents: npt.NDArray[np.int64]
    vx: npt.NDArray[np.float64]
    vy: npt.NDArray[np.float64]
    vz: npt.NDArray[np.float64]
    vt: npt.NDArray[np.float64]


_Reals = npt.NDArray[np.float32] | npt.NDArray[np.float64]


class _Columns(NamedTuple):
    """A chunk's event counts and numbers and its particle columns, flat, as the
    extension takes them."""

    counts: npt.NDArray[np.int64]
    numbers: npt.NDArray[np.int64]
    pid: npt.NDArray[np.int32]
    status: npt.NDArray[np.int32]
    m1: npt.NDArray[np.int32]
    final: npt.NDArray[np.bool_]
    px: _Reals
    py: _Reals
    pz: _Reals
    e: _Reals
    mass: _Reals
    x: _Reals
    y: _Reals
    z: _Reals
    t: _Reals


def write_hepmc_input(
    chunks: Iterable[ak.Array], path: Path, *, precision: int = DEFAULT_PRECISION
) -> int:
    """Write the final state of every event in `chunks` to `path`.

    Parameters
    ----------
    chunks : iterable of ak.Array
        Particle records (:mod:`omphjc.events.particles`) with the field
        ``part_final`` that
        :meth:`omphjc.events.stable_particles.StableParticleDefinition.apply`
        adds. The chunks are written in turn, so a record can be streamed.
    path : Path
        The file to write; it must end in ``.hepmc``, and an existing file is
        replaced.
    precision : int, optional
        Digits after the decimal point of each number, from 2 to 24.

    Returns
    -------
    int
        The number of events written.

    Raises
    ------
    TypeError
        If `precision` is not an integer.
    ValueError
        If `path` does not end in ``.hepmc``, in any case, `precision` lies
        outside 2 to 24, or as :func:`iterate_hepevt_arrays` does for an event;
        the events before that one are then in the file, which ends as a HepMC3
        file does.
    """
    if path.suffix.lower() != HEPMC_SUFFIX:
        raise ValueError(
            f"Parnassus reads HepMC3 only from a file ending in {HEPMC_SUFFIX},"
            f" not {path.name}"
        )
    digits = require_number(precision, what="precision", kind=int)
    low, high = PRECISION_RANGE
    if not low <= digits <= high:
        raise ValueError(
            f"HepMC3 writes {low} to {high} digits after the point, not {digits}"
        )
    written = 0
    with path.open("wb") as output:
        output.write(_HEADER.encode())
        try:
            for chunk in chunks:
                text, n_events, error = _hepmc_ascii.format_events(
                    *_columns(chunk), digits
                )
                output.write(text)
                written += n_events
                if error:
                    raise ValueError(error)
        finally:
            output.write(_FOOTER.encode())
    return written


def iterate_hepevt_arrays(particles: ak.Array) -> Iterator[HepevtArrays]:
    """Yield the record Parnassus reads of each event, as HEPEVT arrays.

    The event number is the event's ``event_index``. A final particle takes
    status 1. A final particle at the origin takes the beams as its parents; one
    produced elsewhere takes its mother ``part_m1``, which joins the record
    with its own status, the beams as its parents and its decay at the
    daughters' position. Every other particle is left out.

    Parameters
    ----------
    particles : ak.Array
        Particle records marked with
        :meth:`omphjc.events.stable_particles.StableParticleDefinition.apply`.

    Yields
    ------
    HepevtArrays
        The arrays of each event in turn, beams first.

    Raises
    ------
    ValueError
        If the record lacks a field, an event's ``event_index`` does not fit an
        int, or an event has other than two beams (status 4) or holds a final
        particle away from the origin whose mother is missing, outside the
        event or a beam, or whose displaced siblings lie at another position.
    """
    columns = _columns(particles)
    arrays = _hepmc_ascii.hepevt_events(*columns)
    counts = arrays["counts"]
    stops = np.cumsum(counts)
    numbers = columns.numbers[: counts.size]
    for number, start, stop in zip(numbers, stops - counts, stops, strict=True):
        part = slice(start, stop)
        yield HepevtArrays(
            event_number=int(number),
            pid=arrays["pid"][part],
            status=arrays["status"][part],
            px=arrays["px"][part],
            py=arrays["py"][part],
            pz=arrays["pz"][part],
            e=arrays["e"][part],
            m=arrays["m"][part],
            parents=arrays["parents"][part],
            vx=arrays["vx"][part],
            vy=arrays["vy"][part],
            vz=arrays["vz"][part],
            vt=arrays["vt"][part],
        )
    if arrays["error"]:
        raise ValueError(arrays["error"])


def _columns(particles: ak.Array) -> _Columns:
    """Return the event counts and numbers and the particle columns, flat.

    The integers are passed as int32 and the flags as bool; the real numbers
    stay float32 when every one of them is, and are float64 otherwise.
    """
    _check_fields(particles.fields)
    counts = ak.to_numpy(ak.num(particles["part_pid"], axis=1)).astype(np.int64)
    numbers = np.asarray(ak.to_numpy(particles[EVENT_COLUMN]), dtype=np.int64)
    low, high = _EVENT_NUMBER_RANGE
    outside = (numbers < low) | (numbers > high)
    if outside.any():
        raise ValueError(
            f"event_index {int(numbers[np.argmax(outside)])} does not fit HepMC3's"
            f" event number, an int from {low} to {high}"
        )
    flat = {
        name: ak.to_numpy(ak.flatten(particles[name], axis=1))
        for name in PARTICLE_COLUMNS
    }
    pid, status, m1 = (
        np.ascontiguousarray(flat[name], dtype=np.int32) for name in _INTEGER_COLUMNS
    )
    reals: list[_Reals]
    if all(flat[name].dtype == np.float32 for name in _REAL_COLUMNS):
        reals = [np.ascontiguousarray(flat[name], np.float32) for name in _REAL_COLUMNS]
    else:
        reals = [np.ascontiguousarray(flat[name], np.float64) for name in _REAL_COLUMNS]
    px, py, pz, e, mass, x, y, z, t = reals
    final = np.ascontiguousarray(flat["part_final"], dtype=np.bool_)
    return _Columns(
        counts, numbers, pid, status, m1, final, px, py, pz, e, mass, x, y, z, t
    )


def _check_fields(fields: Sequence[str]) -> None:
    """Refuse a record that lacks a field the input is made of."""
    missing = [name for name in (EVENT_COLUMN, *PARTICLE_COLUMNS) if name not in fields]
    if missing:
        hint = (
            "; mark it with StableParticleDefinition.apply first"
            if "part_final" in missing
            else ""
        )
        raise ValueError(f"the particle record lacks {', '.join(missing)}{hint}")
