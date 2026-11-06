import sys
from pathlib import Path
from types import ModuleType

import awkward as ak
import numpy as np
import pytest

from omphjc.events.stable_particles import StableParticleDefinition
from omphjc.tools.parnassus.hepmc_input import (
    EVENT_COLUMN,
    HepevtArrays,
    iterate_hepevt_arrays,
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
        "part_final": status == 1,
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
OTHER_DECAY_VERTEX = (-0.75, 1.25, -2.5, 3.0)
# A float32 that needs all 9 significant digits: 1.0352942e+01 is another float32.
NINE_DIGITS = float(np.float32(176 / 17))


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


def arrays_of(rows: list[dict[str, float]]) -> HepevtArrays:
    """Return the HEPEVT arrays of the one event `rows`."""
    (arrays,) = iterate_hepevt_arrays(record(rows))
    return arrays


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


def b_to_psi2s_to_gluons() -> list[dict[str, float]]:
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


def two_pi0s_at_two_vertices() -> list[dict[str, float]]:
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


def test_a_displaced_photon_hangs_from_its_mothers_decay_vertex() -> None:
    arrays = arrays_of(pi0_to_two_photons())
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


def test_string_hadrons_hang_from_the_first_gluon_and_the_onium_is_left_out() -> None:
    arrays = arrays_of(b_to_psi2s_to_gluons())
    assert arrays.pid.tolist() == [2212, 2212, 521, 321, 21, 211, -211]
    assert arrays.status.tolist() == [4, 4, 2, 1, 71, 1, 1]
    assert arrays.parents.tolist() == [
        [-1, -1],
        [-1, -1],
        [0, 1],
        [2, 2],
        [0, 1],
        [4, 4],
        [4, 4],
    ]
    vertices = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
    np.testing.assert_array_equal(vertices[[3, 5, 6]], np.float32([DECAY_VERTEX] * 3))
    assert not vertices[[0, 1, 2, 4]].any()


def test_the_photons_of_two_decays_hang_from_their_own_mothers_vertex() -> None:
    arrays = arrays_of(two_pi0s_at_two_vertices())
    assert arrays.parents.tolist() == [
        [-1, -1],
        [-1, -1],
        [0, 1],
        [0, 1],
        [2, 2],
        [3, 3],
        [2, 2],
        [3, 3],
    ]
    vertices = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
    np.testing.assert_array_equal(
        vertices[4:], np.float32([DECAY_VERTEX, OTHER_DECAY_VERTEX] * 2)
    )


def test_the_event_number_momenta_and_masses_are_the_records() -> None:
    (arrays,) = iterate_hepevt_arrays(record(pi0_to_two_photons(), first_index=41))
    assert arrays.event_number == 41
    assert arrays.px.dtype == np.float64 and arrays.pid.dtype == np.int32
    assert arrays.m[3] == np.float32(0.135)
    assert arrays.en.tolist() == [6500.0, 6500.0, 4.0, 4.0, 4.0, 4.0]


def test_the_beams_come_first_wherever_the_record_holds_them() -> None:
    arrays = arrays_of([particle(22, 1), *BEAMS])
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
    (arrays,) = iterate_hepevt_arrays(K0S_DEFINITION.apply(record(k0s_decay)))
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
            [*BEAMS, particle(22, 1, m1=1, at=DECAY_VERTEX)],
            "part_m1 = 1 is none, outside the event or a beam",
        ),
        (
            [*BEAMS, particle(22, 1, m1=3, at=DECAY_VERTEX)],
            "part_m1 = 3 is none, outside the event or a beam",
        ),
        (
            [
                *BEAMS,
                particle(111, 2),
                particle(22, 1, m1=2, at=DECAY_VERTEX),
                particle(22, 1, at=OTHER_DECAY_VERTEX),
            ],
            "final particle 4 of event 0 lies away from the origin, and its mother"
            " part_m1 = -1",
        ),
        (
            [BEAMS[0], particle(22, 1)],
            "event 0 has 1 beam particles",
        ),
        (
            [*BEAMS, BEAMS[0], particle(22, 1)],
            "event 0 has 3 beam particles",
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
        (
            [
                *BEAMS,
                particle(111, 2),
                particle(111, 2),
                particle(22, 1, m1=2, at=DECAY_VERTEX),
                particle(22, 1, m1=3, at=OTHER_DECAY_VERTEX),
                particle(22, 1, m1=2, at=DECAY_VERTEX),
                particle(22, 1, m1=3, at=DECAY_VERTEX),
            ],
            "daughters of particle 3 in event 0 lie at different positions",
        ),
    ],
)
def test_an_event_parnassus_cannot_read_is_refused_without_pyhepmc(
    rows: list[dict[str, float]], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pyhepmc", None)
    with pytest.raises(ValueError, match=message):
        arrays_of(rows)


def test_a_record_not_yet_marked_is_refused() -> None:
    unmarked = ak.without_field(record(pi0_to_two_photons()), "part_final")
    with pytest.raises(
        ValueError, match="lacks .*part_final; mark it with StableParticleDefinition"
    ):
        list(iterate_hepevt_arrays(unmarked))


@pytest.mark.usefixtures("hepmc")
@pytest.mark.parametrize(
    ("missing", "message"),
    [
        (
            "part_final",
            r"lacks part_final; mark it with StableParticleDefinition\.apply first$",
        ),
        (EVENT_COLUMN, "lacks event_index$"),
        ("part_mass", "lacks part_mass$"),
    ],
)
def test_writing_a_record_that_lacks_a_field_is_refused(
    missing: str, message: str, tmp_path: Path
) -> None:
    particles = ak.without_field(record(pi0_to_two_photons()), missing)
    with pytest.raises(ValueError, match=message):
        write_hepmc_input([particles], tmp_path / "input.hepmc")


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
    (``_assign_vertices_and_events`` in ``src/parnassus/data/hepmc.py`` at
    c9f8bd9e4c).
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
def test_parnassus_reads_the_suffix_in_any_case(tmp_path: Path) -> None:
    path = tmp_path / "input.HEPMC"
    assert write_hepmc_input([record(pi0_to_two_photons())], path) == 1


@pytest.mark.usefixtures("hepmc")
def test_parnassus_finds_every_particles_recorded_position(tmp_path: Path) -> None:
    events = record(
        pi0_to_two_photons(), b_to_psi2s_to_gluons(), two_pi0s_at_two_vertices()
    )
    path = tmp_path / "input.hepmc"
    assert write_hepmc_input([events], path) == 3
    positions = _positions_as_parnassus_reads_them(path.read_text())
    for arrays, read in zip(iterate_hepevt_arrays(events), positions, strict=True):
        expected = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
        np.testing.assert_array_equal(np.float32(read), np.float32(expected))
    assert np.float32(positions[1][3]).tolist() == list(DECAY_VERTEX)


@pytest.mark.usefixtures("hepmc")
def test_chunks_give_the_file_one_array_gives(tmp_path: Path) -> None:
    events = record(pi0_to_two_photons(), b_to_psi2s_to_gluons(), pi0_to_two_photons())
    whole, chunked = tmp_path / "whole.hepmc", tmp_path / "chunked.hepmc"
    assert write_hepmc_input([events], whole) == 3
    assert write_hepmc_input([events[:1], events[1:1], events[1:]], chunked) == 3
    assert chunked.read_text() == whole.read_text()


def test_hepmc3_reads_back_the_record_in_gev_and_mm(
    tmp_path: Path, hepmc: ModuleType
) -> None:
    events = record(pi0_to_two_photons(), b_to_psi2s_to_gluons(), first_index=7)
    path = tmp_path / "input.hepmc"
    write_hepmc_input([events], path)
    assert "\nU GEV MM\n" in path.read_text()
    with hepmc.open(path) as stream:
        read = list(stream)
    assert [event.event_number for event in read] == [7, 8]
    for event, arrays in zip(read, iterate_hepevt_arrays(events), strict=True):
        assert event.momentum_unit == hepmc.Units.GEV
        assert event.length_unit == hepmc.Units.MM
        assert [p.pid for p in event.particles] == arrays.pid.tolist()
        assert [p.status for p in event.particles] == arrays.status.tolist()
        momenta = np.float32([list(p.momentum) for p in event.particles])
        expected = np.float32(
            np.column_stack([arrays.px, arrays.py, arrays.pz, arrays.en])
        )
        np.testing.assert_array_equal(momenta, expected)
        vertices = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
        displaced = (arrays.status == 1) & vertices.any(axis=1)
        positions = [
            list(p.production_vertex.position)
            for p in event.particles
            if p.status == 1 and any(p.production_vertex.position)
        ]
        np.testing.assert_array_equal(
            np.float32(positions), np.float32(vertices[displaced])
        )


@pytest.mark.usefixtures("hepmc")
def test_the_events_before_a_refused_one_stay_in_the_file(tmp_path: Path) -> None:
    refused = [*BEAMS, particle(22, 1, at=DECAY_VERTEX)]
    path = tmp_path / "input.hepmc"
    with pytest.raises(ValueError, match="particle 2 of event 1 lies away"):
        write_hepmc_input([record(pi0_to_two_photons(), refused)], path)
    lines = path.read_text().splitlines()
    assert [line.split()[1] for line in lines if line.startswith("E ")] == ["0"]


def test_every_float32_is_read_back_unchanged(
    tmp_path: Path, hepmc: ModuleType
) -> None:
    photon = particle(22, 1, p=(NINE_DIGITS, 0.0, 0.0, NINE_DIGITS))
    path = tmp_path / "input.hepmc"
    write_hepmc_input([record([*BEAMS, photon])], path)
    with hepmc.open(path) as stream:
        (event,) = list(stream)
    assert np.float32(event.particles[2].momentum.px) == np.float32(NINE_DIGITS)


@pytest.mark.usefixtures("hepmc")
def test_the_precision_sets_the_digits_after_the_point(tmp_path: Path) -> None:
    photon = particle(22, 1, p=(NINE_DIGITS, 0.0, 0.0, NINE_DIGITS))
    path = tmp_path / "input.hepmc"
    write_hepmc_input([record([*BEAMS, photon])], path, precision=3)
    assert " 1.035e+01 " in path.read_text()
