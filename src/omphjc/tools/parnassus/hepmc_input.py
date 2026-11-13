"""Write the final state of the shower's events as a HepMC3 file for Parnassus.

Parnassus's generate pipeline picks its dataset by the suffix of the input
file, compared in lower case. It reads HepMC3 ASCII only from a ``.hepmc``
file, and it opens that file uncompressed (``build_dataset`` in
``src/parnassus/data/__init__.py`` at c9f8bd9e4c,
https://github.com/parnassus-hep/parnassus).

Parnassus reads the following values:

- of each particle, the PDG id, status, momentum, generated mass and
  production position;
- of each event, its number.

It never follows mother or daughter links. The file therefore holds the
smallest valid record of each event:

- the two beams;
- every final particle, with status 1. The final particles include the
  promoted ones, which are long-lived particles that the shower decayed and
  that the stable-particle definition marks as final;
- the mother of each final particle produced away from the origin, written
  once, with its own status.

In a HepMC3 file each particle names a parent. The parent is either a vertex
line or the number of another particle. Parnassus takes the production
position of a particle only from the vertex line that the particle names as
its parent. It reads a particle whose parent is another particle's number at
the origin, without a warning (``_assign_vertices_and_events`` in
``src/parnassus/data/hepmc.py`` at c9f8bd9e4c).

For this reason a displaced final particle, which is a final particle
produced away from the origin, takes its mother as its parent. The end of the
mother then becomes a vertex at the common position of the daughters. Every
other particle takes the beams as its parents, and the vertex of the beams
is the origin.

The text is identical to what ``WriterAscii`` of HepMC3 3.3.1 writes for
these events (``src/WriterAscii.cc`` at 3.3.1,
https://gitlab.cern.ch/hepmc/HepMC3). The units are GeV and mm. The vertices
are numbered in the order they appear.
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

    The two beams come first. Indices count from 0. ``parents`` holds the
    first and last parent of each particle, or ``(-1, -1)`` when the particle
    has no parent. Momenta and masses are in GeV. Positions are in mm, and
    the time is given as c t.
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
    """The columns of one chunk in the form the extension takes.

    The fields are the particle count and the event number of each event,
    followed by the particle columns as flat arrays.
    """

    particle_counts: npt.NDArray[np.int64]
    event_numbers: npt.NDArray[np.int64]
    pid: npt.NDArray[np.int32]
    status: npt.NDArray[np.int32]
    mother: npt.NDArray[np.int32]
    is_final: npt.NDArray[np.bool_]
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
    chunks: Iterable[ak.Array],
    path: Path,
    *,
    precision: int = DEFAULT_PRECISION,
    threads: int = 1,
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
        The file to write. Its name must end in ``.hepmc``. An existing file
        is replaced.
    precision : int, optional
        Digits after the decimal point of each number, from 2 to 24.
    threads : int, optional
        Number of threads that build and write the events of each chunk. The
        content of the file does not depend on this number.

    Returns
    -------
    int
        The number of events written.

    Raises
    ------
    TypeError
        If `precision` or `threads` is not an integer.
    ValueError
        In any of these cases:

        - `path` does not end in ``.hepmc``, compared without regard to case;
        - `precision` lies outside 2 to 24;
        - `threads` is below 1;
        - an event is invalid, under the conditions listed for
          :func:`iterate_hepevt_arrays`.

        When an event is invalid, the events before it are already in the
        file, and the file still ends with the closing lines of a HepMC3
        file.
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
    workers = require_number(threads, what="threads", kind=int, positive=True)
    written = 0
    with path.open("wb") as output:
        output.write(_HEADER.encode())
        try:
            for chunk in chunks:
                text, n_events, error = _hepmc_ascii.format_events(
                    *_columns(chunk), digits, workers
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
    status 1.

    A final particle at the origin takes the beams as its parents. A final
    particle produced elsewhere takes its mother ``part_m1`` as its parent.
    The mother then joins the record with its own status, with the beams as
    its parents, and with its decay at the position of the daughters.

    Every other particle is left out.

    Parameters
    ----------
    particles : ak.Array
        Particle records with the field ``part_final`` that
        :meth:`omphjc.events.stable_particles.StableParticleDefinition.apply`
        adds.

    Yields
    ------
    HepevtArrays
        The arrays of each event in turn, beams first.

    Raises
    ------
    ValueError
        In any of these cases:

        - the record lacks a field;
        - the ``event_index`` of an event does not fit an int;
        - an event does not have exactly two beams (status 4);
        - an event holds a final particle away from the origin, and the
          position of that particle is not finite;
        - the mother of such a particle is missing, lies outside the event
          or is a beam;
        - the displaced siblings of such a particle lie at another position.

        The events before the invalid event are yielded first.
    """
    columns = _columns(particles)
    arrays = _hepmc_ascii.to_hepevt(*columns)
    particle_counts = arrays["particle_counts"]
    stops = np.cumsum(particle_counts)
    event_numbers = columns.event_numbers[: particle_counts.size]
    for event_number, start, stop in zip(
        event_numbers, stops - particle_counts, stops, strict=True
    ):
        part = slice(start, stop)
        yield HepevtArrays(
            event_number=int(event_number),
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
    """Return the columns of `particles` in the form the extension takes.

    The result holds the particle count and the event number of each event,
    followed by the particle columns as flat arrays.

    The particle counts and the event numbers are passed as int64. The integer
    particle columns are passed as int32, and the flags as bool. The real
    numbers stay float32 when every one of them is float32, and are passed as
    float64 otherwise.
    """
    _check_fields(particles.fields)
    particle_counts = ak.to_numpy(ak.num(particles["part_pid"], axis=1)).astype(
        np.int64
    )
    event_numbers = np.asarray(ak.to_numpy(particles[EVENT_COLUMN]), dtype=np.int64)
    flat = {
        name: ak.to_numpy(ak.flatten(particles[name], axis=1))
        for name in PARTICLE_COLUMNS
    }
    pid, status, mother = (
        np.ascontiguousarray(flat[name], dtype=np.int32) for name in _INTEGER_COLUMNS
    )
    reals: list[_Reals]
    if all(flat[name].dtype == np.float32 for name in _REAL_COLUMNS):
        reals = [np.ascontiguousarray(flat[name], np.float32) for name in _REAL_COLUMNS]
    else:
        reals = [np.ascontiguousarray(flat[name], np.float64) for name in _REAL_COLUMNS]
    px, py, pz, e, mass, x, y, z, t = reals
    is_final = np.ascontiguousarray(flat["part_final"], dtype=np.bool_)
    return _Columns(
        particle_counts,
        event_numbers,
        pid,
        status,
        mother,
        is_final,
        px,
        py,
        pz,
        e,
        mass,
        x,
        y,
        z,
        t,
    )


def _check_fields(fields: Sequence[str]) -> None:
    """Refuse a record that lacks a field the input is made of."""
    missing = [name for name in (EVENT_COLUMN, *PARTICLE_COLUMNS) if name not in fields]
    if missing:
        hint = (
            "; apply a StableParticleDefinition to it first"
            if "part_final" in missing
            else ""
        )
        raise ValueError(f"the particle record lacks {', '.join(missing)}{hint}")
