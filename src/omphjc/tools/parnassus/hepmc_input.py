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

pyhepmc builds each event from the HEPEVT arrays that :func:`hepevt_arrays`
returns (``GenEvent.from_hepevt``), in its default units, GeV and mm, and
HepMC3's own writer writes the event, so the file is in the format HepMC3's
reader takes. pyhepmc is imported only by :func:`write_hepmc_input`.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import awkward as ak
import numpy as np
import numpy.typing as npt

# Parnassus's generate pipeline reads HepMC3 ASCII only from a file with this
# suffix, compared lower-cased (build_dataset in src/parnassus/data/__init__.py
# at c9f8bd9e4c, https://github.com/parnassus-hep/parnassus).
HEPMC_SUFFIX = ".hepmc"

# HepMC status codes as Pythia writes them, statusHepMC
# (https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
FINAL_STATUS = 1
BEAM_STATUS = 4

# Digits after the decimal point of each number, which HepMC3 writes in exponent
# form: 8 give 9 significant digits, from which any float32 is read back
# unchanged (FLT_DECIMAL_DIG of IEEE binary32, 1 + ceil(24 log10 2); ISO C11
# 5.2.4.2.2).
DEFAULT_PRECISION = 8

# The fields of the particle record the input is made of.
EVENT_COLUMN = "event_index"
PARTICLE_COLUMNS = (
    "part_pid",
    "part_status",
    "part_m1",
    "part_final",
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
_POSITION_COLUMNS = ("part_x", "part_y", "part_z", "part_t")


class HepevtArrays(NamedTuple):
    """One event's record as the HEPEVT arrays ``GenEvent.from_hepevt`` takes.

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
        Digits after the decimal point of each number.

    Returns
    -------
    int
        The number of events written.

    Raises
    ------
    ValueError
        If `path` does not end in ``.hepmc``, in any case, or as
        :func:`hepevt_arrays` does for an event; the events before that one are
        then in the file.
    """
    if path.suffix.lower() != HEPMC_SUFFIX:
        raise ValueError(
            f"Parnassus reads HepMC3 only from a file ending in {HEPMC_SUFFIX},"
            f" not {path.name}"
        )
    import pyhepmc

    written = 0
    with pyhepmc.open(path, "w", precision=precision) as output:
        for chunk in chunks:
            for arrays in _events_of(chunk):
                event = pyhepmc.GenEvent()
                event.from_hepevt(
                    arrays.event_number,
                    px=arrays.px,
                    py=arrays.py,
                    pz=arrays.pz,
                    en=arrays.e,
                    m=arrays.m,
                    pid=arrays.pid,
                    status=arrays.status,
                    parents=arrays.parents,
                    vx=arrays.vx,
                    vy=arrays.vy,
                    vz=arrays.vz,
                    vt=arrays.vt,
                    fortran=False,
                )
                output.write(event)
                written += 1
    return written


def hepevt_arrays(event: ak.Record) -> HepevtArrays:
    """Return the record Parnassus reads of one event, as HEPEVT arrays.

    The event number is the event's ``event_index``. A final particle takes
    status 1. A final particle at the origin takes the beams as its parents; one
    produced elsewhere takes its mother ``part_m1``, which joins the record
    with its own status, the beams as its parents and its decay at the
    daughters' position. Every other particle is left out.

    Parameters
    ----------
    event : ak.Record
        One event of a particle record marked with
        :meth:`omphjc.events.stable_particles.StableParticleDefinition.apply`.

    Returns
    -------
    HepevtArrays
        The arrays, beams first.

    Raises
    ------
    ValueError
        If the event lacks a field, has other than two beams (status 4), or
        holds a final particle away from the origin whose mother is missing,
        outside the event or a beam, or whose siblings in the file lie at
        another position.
    """
    _check_fields(event.fields)
    columns = {name: ak.to_numpy(event[name]) for name in PARTICLE_COLUMNS}
    return _event_arrays(int(event[EVENT_COLUMN]), columns)


def _events_of(chunk: ak.Array) -> Iterator[HepevtArrays]:
    """Yield the HEPEVT arrays of each event in `chunk`."""
    _check_fields(chunk.fields)
    counts = ak.to_numpy(ak.num(chunk["part_pid"], axis=1))
    stops = np.cumsum(counts)
    flat = {
        name: ak.to_numpy(ak.flatten(chunk[name], axis=1)) for name in PARTICLE_COLUMNS
    }
    numbers = ak.to_numpy(chunk[EVENT_COLUMN])
    for number, start, stop in zip(numbers, stops - counts, stops, strict=True):
        columns = {name: values[start:stop] for name, values in flat.items()}
        yield _event_arrays(int(number), columns)


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


def _event_arrays(number: int, columns: Mapping[str, npt.NDArray[Any]]) -> HepevtArrays:
    """Return the HEPEVT arrays of event `number`, given its particles' columns."""
    status = columns["part_status"]
    beams = np.flatnonzero(status == BEAM_STATUS)
    if beams.size != 2:
        raise ValueError(
            f"event {number} has {beams.size} beam particles (status"
            f" {BEAM_STATUS}), not 2"
        )
    final = columns["part_final"].astype(bool)
    position = np.column_stack(
        [columns[name].astype(np.float64) for name in _POSITION_COLUMNS]
    )
    finals = np.flatnonzero(final)
    displaced = finals[np.any(position[finals] != 0.0, axis=1)]
    mothers = columns["part_m1"][displaced].astype(np.int64)
    _check_mothers(number, displaced, mothers, beams, position, status.size)

    kept = np.concatenate([beams, np.union1d(finals, mothers)])
    row = np.full(status.size, -1, dtype=np.int64)
    row[kept] = np.arange(kept.size)
    out_status = status[kept].astype(np.int32)
    out_status[final[kept]] = FINAL_STATUS
    parents = np.tile(np.array([0, 1], dtype=np.int64), (kept.size, 1))
    parents[:2] = -1
    parents[row[displaced]] = row[mothers][:, None]
    out_position = np.zeros((kept.size, 4))
    out_position[row[displaced]] = position[displaced]

    def values(name: str) -> npt.NDArray[np.float64]:
        return np.asarray(columns[name][kept], dtype=np.float64)

    return HepevtArrays(
        event_number=number,
        pid=np.asarray(columns["part_pid"][kept], dtype=np.int32),
        status=out_status,
        px=values("part_px"),
        py=values("part_py"),
        pz=values("part_pz"),
        e=values("part_e"),
        m=values("part_mass"),
        parents=parents,
        vx=out_position[:, 0],
        vy=out_position[:, 1],
        vz=out_position[:, 2],
        vt=out_position[:, 3],
    )


def _check_mothers(
    number: int,
    displaced: npt.NDArray[np.int64],
    mothers: npt.NDArray[np.int64],
    beams: npt.NDArray[np.int64],
    position: npt.NDArray[np.float64],
    n_particles: int,
) -> None:
    """Refuse displaced final particles that cannot hang from their mother's vertex."""
    unusable = (mothers < 0) | (mothers >= n_particles) | np.isin(mothers, beams)
    if np.any(unusable):
        particle = int(displaced[np.argmax(unusable)])
        raise ValueError(
            f"final particle {particle} of event {number} lies away from the"
            f" origin, and its mother part_m1 = {int(mothers[np.argmax(unusable)])}"
            f" is none, outside the event or a beam, so no vertex can give its"
            f" position"
        )
    order = np.argsort(mothers, kind="stable")
    grouped = position[displaced[order]]
    first = np.r_[True, mothers[order][1:] != mothers[order][:-1]]
    group_start = np.maximum.accumulate(np.where(first, np.arange(order.size), 0))
    moved = np.any(grouped != grouped[group_start], axis=1)
    if np.any(moved):
        mother = int(mothers[order][np.argmax(moved)])
        raise ValueError(
            f"the daughters of particle {mother} in event {number} lie at"
            f" different positions, but share their mother's one decay vertex"
        )
