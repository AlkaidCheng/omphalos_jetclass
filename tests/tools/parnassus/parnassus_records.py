"""Particle records for the tests of Parnassus's input."""

from typing import Any

import awkward as ak
import numpy as np

from omphjc.tools.parnassus.hepmc_input import EVENT_COLUMN

INT_FIELDS = (
    "part_pid",
    "part_status",
    "part_m1",
    "part_m2",
    "part_d1",
    "part_d2",
)
FLOAT_FIELDS = (
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
ORIGIN = (0.0, 0.0, 0.0, 0.0)
DECAY_VERTEX = (0.25, -0.5, 1.75, 2.0)
OTHER_DECAY_VERTEX = (-0.75, 1.25, -2.5, 3.0)
# A float32 that needs all 9 significant digits: 1.0352942e+01 is another float32.
NINE_DIGITS = float(np.float32(176 / 17))


def particle(
    pid: int,
    status: int,
    *,
    m1: int = -1,
    d1: int = -1,
    d2: int = -1,
    final: bool | None = None,
    p: tuple[float, float, float, float] = (1.0, 2.0, 3.0, 4.0),
    mass: float = 0.0,
    at: tuple[float, float, float, float] = ORIGIN,
) -> dict[str, Any]:
    """Return one row of an event; a particle is final when its status is 1,
    unless `final` says otherwise."""
    px, py, pz, e = p
    x, y, z, t = at
    return {
        "part_pid": pid,
        "part_status": status,
        "part_m1": m1,
        "part_m2": -1,
        "part_d1": d1,
        "part_d2": d2,
        "part_final": status == 1 if final is None else final,
        "part_px": px,
        "part_py": py,
        "part_pz": pz,
        "part_e": e,
        "part_mass": mass,
        "part_x": x,
        "part_y": y,
        "part_z": z,
        "part_t": t,
    }


BEAMS = [
    particle(2212, 4, p=(0.0, 0.0, 6500.0, 6500.0), mass=0.938),
    particle(2212, 4, p=(0.0, 0.0, -6500.0, 6500.0), mass=0.938),
]


def record(
    *events: list[dict[str, Any]], first_index: int = 0, real: type = np.float32
) -> ak.Array:
    """Return the particle records of `events`, each a list of rows, with the
    record's dtypes and real numbers of dtype `real`."""
    counts = np.array([len(event) for event in events], dtype=np.int64)
    columns = {EVENT_COLUMN: np.arange(first_index, first_index + len(events))}
    for name in (*INT_FIELDS, "part_final", *FLOAT_FIELDS):
        dtype = (
            np.int16
            if name == "part_status"
            else (
                np.int32
                if name in INT_FIELDS
                else np.bool_ if name == "part_final" else real
            )
        )
        values = np.array([row[name] for event in events for row in event], dtype)
        columns[name] = ak.unflatten(values, counts)
    return ak.zip(columns, depth_limit=1)


def pi0_to_two_photons() -> list[dict[str, Any]]:
    """A pi0 decayed at a tiny distance from the origin, as its tau0 makes Pythia do."""
    photon_at = (1.5e-5, -2.5e-5, 3.5e-5, 4.5e-5)
    return [
        *BEAMS,
        particle(22, 1, p=(1 / 3, 2 / 3, 3.0, 4.0)),
        particle(111, 2, d1=4, d2=5, mass=0.135),
        particle(22, 1, m1=3, at=photon_at),
        particle(22, 1, m1=3, at=photon_at),
    ]


def b_to_psi2s_to_gluons() -> list[dict[str, Any]]:
    """A B+ -> psi(2S) K+ decay whose psi(2S) -> ggg string starts at the B's vertex.

    Pythia hadronizes the gluons of an onium decay in a string (``meMode`` 92),
    so the string's pions take its first gluon as their mother.
    """
    return [
        *BEAMS,
        particle(521, 2, d1=3, d2=4, mass=5.279),
        particle(100443, 2, m1=2, d1=5, d2=7, mass=3.686, at=DECAY_VERTEX),
        particle(321, 1, m1=2, at=DECAY_VERTEX),
        *(particle(21, 71, m1=3, d1=8, d2=9) for _ in range(3)),
        particle(211, 1, m1=5, at=DECAY_VERTEX),
        particle(-211, 1, m1=5, at=DECAY_VERTEX),
    ]


def two_pi0s_at_two_vertices() -> list[dict[str, Any]]:
    """Two pi0s decayed at different points, their photons listed alternately."""
    return [
        *BEAMS,
        particle(111, 2, d1=6, d2=4, mass=0.135),
        particle(111, 2, d1=7, d2=5, mass=0.135),
        particle(22, 1, m1=2, at=DECAY_VERTEX),
        particle(22, 1, m1=3, at=OTHER_DECAY_VERTEX),
        particle(22, 1, m1=2, at=DECAY_VERTEX),
        particle(22, 1, m1=3, at=OTHER_DECAY_VERTEX),
    ]


def _real(rng: np.random.Generator) -> float:
    """Return a float32 value of random sign and magnitude, sometimes a signed zero."""
    if rng.random() < 0.1:
        return float(np.float32(-0.0 if rng.random() < 0.5 else 0.0))
    magnitude = rng.random() * 10.0 ** rng.integers(-9, 6)
    return float(np.float32(magnitude if rng.random() < 0.5 else -magnitude))


def _position(rng: np.random.Generator) -> tuple[float, float, float, float]:
    """Return a production position away from the origin, at times in time alone."""
    if rng.random() < 0.1:
        return (0.0, 0.0, 0.0, abs(_real(rng)) or 1e-3)
    while True:
        position = (_real(rng), _real(rng), _real(rng), abs(_real(rng)))
        if any(position):
            return position


_RANDOM_PIDS = (22, 211, -211, 321, 2212, 11, 13, 130, 310, 3122, 111, 21)


def _add(
    nodes: list[dict[str, Any]],
    rng: np.random.Generator,
    status: int,
    final: bool,
    at: tuple[float, float, float, float],
    mother: int | None,
) -> int:
    """Append a particle of random species to `nodes` and return its number."""
    nodes.append(
        {
            "pid": int(rng.choice(_RANDOM_PIDS)),
            "status": status,
            "final": final,
            "at": at,
            "mother": mother,
        }
    )
    return len(nodes) - 1


def random_events(
    rng: np.random.Generator, n_events: int
) -> list[list[dict[str, Any]]]:
    """Return events of random shape that the writer accepts.

    Each holds the beams, prompt particles, and decay chains whose daughters
    share their mother's decay position, some decaying further, some promoted
    with their own daughters dropped, listed in random order.
    """
    events = []
    for _ in range(n_events):
        nodes: list[dict[str, Any]] = [
            {"pid": 2212, "status": 4, "final": False, "at": ORIGIN, "mother": None}
            for _ in range(2)
        ]
        for _ in range(int(rng.integers(0, 6))):
            _add(nodes, rng, 1, True, ORIGIN, None)
        for _ in range(int(rng.integers(0, 4))):
            root = _add(nodes, rng, int(rng.choice((2, 71, 51))), False, ORIGIN, None)
            pending = [(root, 0)]
            while pending:
                mother, depth = pending.pop()
                at = _position(rng)
                for _ in range(int(rng.integers(1, 4))):
                    kind = rng.random()
                    if kind < 0.2 and depth < 2:
                        pending.append(
                            (_add(nodes, rng, 2, False, at, mother), depth + 1)
                        )
                    elif kind < 0.3:
                        promoted = _add(nodes, rng, 2, True, at, mother)
                        _add(nodes, rng, 1, False, _position(rng), promoted)
                    else:
                        _add(nodes, rng, 1, True, at, mother)
        order = rng.permutation(len(nodes))
        place = {int(node): k for k, node in enumerate(order)}
        rows = []
        for node in order:
            info = nodes[int(node)]
            mother = info["mother"]
            rows.append(
                particle(
                    info["pid"],
                    info["status"],
                    m1=-1 if mother is None else place[mother],
                    final=info["final"],
                    p=(_real(rng), _real(rng), _real(rng), abs(_real(rng))),
                    mass=abs(_real(rng)),
                    at=info["at"],
                )
            )
        events.append(rows)
    return events
