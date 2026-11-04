import sys
from pathlib import Path
from types import ModuleType

import awkward as ak
import numpy as np
import pytest

from omphjc.events.stable_particles import StableParticleDefinition
from omphjc.tools.parnassus.hepmc_input import (
    EVENT_COLUMN,
    hepevt_arrays,
    write_hepmc_input,
)

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
K0S_DEFINITION = StableParticleDefinition(ctau_min_mm=10.0, ctau_mm={310: 26.844})


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
    at: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> dict[str, float]:
    """Return one row of an event; a particle is final when its status is 1."""
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
DECAY_VERTEX = (0.25, -0.5, 1.75, 2.0)


def record(*events: list[dict[str, float]], first_index: int = 0) -> ak.Array:
    """Return the particle records of `events`, each a list of rows."""
    counts = np.array([len(event) for event in events], dtype=np.int64)
    columns = {EVENT_COLUMN: np.arange(first_index, first_index + len(events))}
    for name in (*INT_FIELDS, "part_final", *FLOAT_FIELDS):
        dtype = (
            np.int32
            if name in INT_FIELDS
            else np.bool_ if name == "part_final" else np.float32
        )
        values = np.array([row[name] for event in events for row in event], dtype)
        columns[name] = ak.unflatten(values, counts)
    return ak.zip(columns, depth_limit=1)


def pi0_to_two_photons() -> list[dict[str, float]]:
    """A pi0 decayed at a tiny distance from the origin, as its tau0 makes Pythia do."""
    photon_at = (1.5e-5, -2.5e-5, 3.5e-5, 4.5e-5)
    return [
        *BEAMS,
        particle(22, 1, p=(1 / 3, 2 / 3, 3.0, 4.0)),
        particle(111, 2, d1=4, d2=5, mass=0.135),
        particle(22, 1, m1=3, at=photon_at),
        particle(22, 1, m1=3, at=photon_at),
    ]


def b_to_partons_to_string() -> list[dict[str, float]]:
    """A B+ decayed into partons whose string hadrons start at the B's decay vertex."""
    return [
        *BEAMS,
        particle(521, 2, d1=3, d2=4, mass=5.279),
        particle(2, 71, m1=2, d1=5, d2=6),
        particle(-2, 71, m1=2, d1=5, d2=6),
        particle(211, 1, m1=3, at=DECAY_VERTEX),
        particle(-211, 1, m1=3, at=DECAY_VERTEX),
    ]


def test_a_displaced_photon_hangs_from_its_mothers_decay_vertex() -> None:
    arrays = hepevt_arrays(record(pi0_to_two_photons())[0])
    assert arrays.pid.tolist() == [2212, 2212, 22, 111, 22, 22]
    assert arrays.status.tolist() == [4, 4, 1, 2, 1, 1]
    assert arrays.parents.tolist() == [
        [-1, -1],
        [-1, -1],
        [0, 1],
        [0, 1],
        [3, 3],
        [3, 3],
    ]
    vertices = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
    assert vertices[:4].tolist() == [[0.0] * 4] * 4
    np.testing.assert_array_equal(
        vertices[4:], np.float32([(1.5e-5, -2.5e-5, 3.5e-5, 4.5e-5)] * 2)
    )


def test_string_hadrons_hang_from_their_first_parton_and_the_b_is_left_out() -> None:
    arrays = hepevt_arrays(record(b_to_partons_to_string())[0])
    assert arrays.pid.tolist() == [2212, 2212, 2, 211, -211]
    assert arrays.status.tolist() == [4, 4, 71, 1, 1]
    assert arrays.parents.tolist() == [[-1, -1], [-1, -1], [0, 1], [2, 2], [2, 2]]
    assert [arrays.vx[3], arrays.vy[3], arrays.vz[3], arrays.vt[3]] == list(
        DECAY_VERTEX
    )
    assert arrays.vx[2] == arrays.vz[2] == 0.0


def test_the_event_number_momenta_and_masses_are_the_records() -> None:
    event = record(pi0_to_two_photons(), first_index=41)[0]
    arrays = hepevt_arrays(event)
    assert arrays.event_number == 41
    assert arrays.px.dtype == np.float64 and arrays.pid.dtype == np.int32
    assert arrays.m[3] == np.float32(0.135)
    assert arrays.e.tolist() == [6500.0, 6500.0, 4.0, 4.0, 4.0, 4.0]


def test_the_beams_come_first_wherever_the_record_holds_them() -> None:
    arrays = hepevt_arrays(record([particle(22, 1), *BEAMS])[0])
    assert arrays.pid.tolist() == [2212, 2212, 22]
    assert arrays.status.tolist() == [4, 4, 1]
    assert arrays.parents.tolist() == [[-1, -1], [-1, -1], [0, 1]]


def test_a_promoted_hadron_is_written_as_final_and_its_decay_left_out() -> None:
    k0s_decay = [
        *BEAMS,
        particle(310, 2, d1=3, d2=4, mass=0.4976),
        particle(211, 1, m1=2, at=DECAY_VERTEX),
        particle(-211, 1, m1=2, at=DECAY_VERTEX),
    ]
    marked = K0S_DEFINITION.apply(record(k0s_decay))
    arrays = hepevt_arrays(marked[0])
    assert arrays.pid.tolist() == [2212, 2212, 310]
    assert arrays.status.tolist() == [4, 4, 1]
    assert arrays.parents.tolist() == [[-1, -1], [-1, -1], [0, 1]]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [*BEAMS, particle(22, 1, at=DECAY_VERTEX)],
            "particle 2 of event 0 lies away from the origin, and its mother"
            " part_m1 = -1",
        ),
        (
            [*BEAMS, particle(22, 1, m1=0, at=DECAY_VERTEX)],
            "part_m1 = 0 is none, outside the event or a beam",
        ),
        (
            [BEAMS[0], particle(22, 1)],
            "event 0 has 1 beam particles",
        ),
        (
            [
                *BEAMS,
                particle(111, 2),
                particle(22, 1, m1=2, at=DECAY_VERTEX),
                particle(22, 1, m1=2, at=(0.25, -0.5, 1.75, 2.5)),
            ],
            "daughters of particle 2 in event 0 lie at different positions",
        ),
    ],
)
def test_an_event_parnassus_cannot_read_is_refused_without_pyhepmc(
    rows: list[dict[str, float]], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pyhepmc", None)
    with pytest.raises(ValueError, match=message):
        hepevt_arrays(record(rows)[0])


def test_a_record_not_yet_marked_is_refused() -> None:
    unmarked = ak.without_field(record(pi0_to_two_photons()), "part_final")
    with pytest.raises(
        ValueError, match="lacks .*part_final; mark it with StableParticleDefinition"
    ):
        hepevt_arrays(unmarked[0])


def test_parnassus_reads_hepmc_only_from_a_plain_hepmc_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pyhepmc", None)
    path = tmp_path / "input.hepmc.gz"
    with pytest.raises(ValueError, match="ending in .hepmc, not input.hepmc.gz"):
        write_hepmc_input([record(pi0_to_two_photons())], path)
    assert not path.exists()


def _positions_as_parnassus_reads_them(text: str) -> list[list[list[float]]]:
    """Return each event's particle positions by the rule of Parnassus's reader.

    A particle's position is that of the vertex line its parent field names,
    when the line carries one after ``@``; otherwise it is the origin
    (``data/hepmc.py``, ``_assign_vertices_and_events``, at c9f8bd9e4c).
    """
    events: list[list[list[float]]] = []
    vertices: dict[int, list[float]] = {}
    parents: list[int] = []

    def close() -> None:
        if events:
            events[-1] = [vertices.get(parent, [0.0] * 4) for parent in parents]

    for line in text.splitlines():
        fields = line.split()
        if line.startswith("E "):
            close()
            events.append([])
            vertices, parents = {}, []
        elif line.startswith("V ") and "@" in fields:
            at = fields.index("@")
            vertices[int(fields[1])] = [float(value) for value in fields[at + 1 :]]
        elif line.startswith("P "):
            parents.append(int(fields[2]))
    close()
    return events


@pytest.fixture
def hepmc() -> ModuleType:
    return pytest.importorskip("pyhepmc")


@pytest.mark.usefixtures("hepmc")
def test_parnassus_finds_every_particles_recorded_position(tmp_path: Path) -> None:
    events = record(pi0_to_two_photons(), b_to_partons_to_string())
    path = tmp_path / "input.hepmc"
    assert write_hepmc_input([events], path) == 2
    positions = _positions_as_parnassus_reads_them(path.read_text())
    for event, read in zip(events, positions, strict=True):
        arrays = hepevt_arrays(event)
        expected = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
        np.testing.assert_array_equal(np.float32(read), np.float32(expected))
    assert np.float32(positions[1][3]).tolist() == list(DECAY_VERTEX)


@pytest.mark.usefixtures("hepmc")
def test_chunks_give_the_file_one_array_gives(tmp_path: Path) -> None:
    events = record(
        pi0_to_two_photons(), b_to_partons_to_string(), pi0_to_two_photons()
    )
    whole, chunked = tmp_path / "whole.hepmc", tmp_path / "chunked.hepmc"
    assert write_hepmc_input([events], whole) == 3
    assert write_hepmc_input([events[:1], events[1:1], events[1:]], chunked) == 3
    assert chunked.read_text() == whole.read_text()


def test_hepmc3_reads_back_the_record_in_gev_and_mm(
    tmp_path: Path, hepmc: ModuleType
) -> None:
    events = record(pi0_to_two_photons(), b_to_partons_to_string(), first_index=7)
    path = tmp_path / "input.hepmc"
    write_hepmc_input([events], path)
    assert "\nU GEV MM\n" in path.read_text()
    with hepmc.open(path) as stream:
        read = list(stream)
    assert [event.event_number for event in read] == [7, 8]
    for event, written in zip(read, events, strict=True):
        arrays = hepevt_arrays(written)
        assert event.momentum_unit == hepmc.Units.GEV
        assert event.length_unit == hepmc.Units.MM
        assert [p.pid for p in event.particles] == arrays.pid.tolist()
        assert [p.status for p in event.particles] == arrays.status.tolist()
        momenta = np.float32([list(p.momentum) for p in event.particles])
        expected = np.float32(
            np.column_stack([arrays.px, arrays.py, arrays.pz, arrays.e])
        )
        np.testing.assert_array_equal(momenta, expected)
        displaced = [
            list(p.production_vertex.position)
            for p in event.particles
            if p.status == 1 and any(p.production_vertex.position)
        ]
        assert len(displaced) == 2
