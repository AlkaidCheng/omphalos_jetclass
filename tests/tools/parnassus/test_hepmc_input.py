import math
import sys
from pathlib import Path

import awkward as ak
import numpy as np
import pytest
from parnassus_records import (
    BEAMS,
    DECAY_VERTEX,
    FLOAT_FIELDS,
    NINE_DIGITS,
    OTHER_DECAY_VERTEX,
    b_to_psi2s_to_gluons,
    particle,
    pi0_to_two_photons,
    random_events,
    record,
    reference_record,
    two_pi0s_at_two_vertices,
    with_a_fault,
)

from omphjc.events.stable_particles import StableParticleDefinition
from omphjc.tools.parnassus.hepmc_input import (
    EVENT_COLUMN,
    HepevtArrays,
    iterate_hepevt_arrays,
    write_hepmc_input,
)

K0S_DEFINITION = StableParticleDefinition(ctau_min_mm=10.0, ctau_mm={310: 26.844})


def arrays_of(rows: list[dict[str, float]]) -> HepevtArrays:
    """Return the HEPEVT arrays of the one event `rows`."""
    (arrays,) = iterate_hepevt_arrays(record(rows))
    return arrays


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
    assert arrays.e.tolist() == [6500.0, 6500.0, 4.0, 4.0, 4.0, 4.0]


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
def test_an_event_parnassus_cannot_read_is_refused(
    rows: list[dict[str, float]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        arrays_of(rows)


def test_a_record_not_yet_marked_is_refused() -> None:
    unmarked = ak.without_field(record(pi0_to_two_photons()), "part_final")
    with pytest.raises(
        ValueError, match="lacks .*part_final; mark it with StableParticleDefinition"
    ):
        list(iterate_hepevt_arrays(unmarked))


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


def test_parnassus_reads_hepmc_only_from_a_plain_hepmc_file(tmp_path: Path) -> None:
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


def test_parnassus_reads_the_suffix_in_any_case(tmp_path: Path) -> None:
    path = tmp_path / "input.HEPMC"
    assert write_hepmc_input([record(pi0_to_two_photons())], path) == 1


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


def test_chunks_give_the_file_one_array_gives(tmp_path: Path) -> None:
    events = record(pi0_to_two_photons(), b_to_psi2s_to_gluons(), pi0_to_two_photons())
    whole, chunked = tmp_path / "whole.hepmc", tmp_path / "chunked.hepmc"
    assert write_hepmc_input([events], whole) == 3
    assert write_hepmc_input([events[:1], events[1:1], events[1:]], chunked) == 3
    assert chunked.read_text() == whole.read_text()


def test_the_events_before_a_refused_one_stay_in_the_file(tmp_path: Path) -> None:
    refused = [*BEAMS, particle(22, 1, at=DECAY_VERTEX)]
    path = tmp_path / "input.hepmc"
    with pytest.raises(ValueError, match="particle 2 of event 1 lies away"):
        write_hepmc_input([record(pi0_to_two_photons(), refused)], path)
    lines = path.read_text().splitlines()
    assert [line.split()[1] for line in lines if line.startswith("E ")] == ["0"]


def test_the_precision_sets_the_digits_after_the_point(tmp_path: Path) -> None:
    photon = particle(22, 1, p=(NINE_DIGITS, 0.0, 0.0, NINE_DIGITS))
    path = tmp_path / "input.hepmc"
    write_hepmc_input([record([*BEAMS, photon])], path, precision=3)
    assert " 1.035e+01 " in path.read_text()


@pytest.mark.parametrize("precision", [1, 25])
def test_a_precision_hepmc3_does_not_write_is_refused(
    precision: int, tmp_path: Path
) -> None:
    with pytest.raises(
        ValueError, match=f"2 to 24 digits after the point, not {precision}"
    ):
        write_hepmc_input(
            [record(pi0_to_two_photons())],
            tmp_path / "input.hepmc",
            precision=precision,
        )


@pytest.mark.parametrize("precision", [8.0, True])
def test_a_precision_that_is_not_an_integer_is_refused(
    precision: object, tmp_path: Path
) -> None:
    with pytest.raises(TypeError, match="precision"):
        write_hepmc_input(
            [record(pi0_to_two_photons())],
            tmp_path / "input.hepmc",
            precision=precision,  # type: ignore[arg-type]
        )


def test_an_event_index_beyond_an_int_is_refused() -> None:
    events = record(pi0_to_two_photons(), first_index=2**31)
    with pytest.raises(ValueError, match="event_index 2147483648 does not fit"):
        list(iterate_hepevt_arrays(events))


def test_a_float64_record_gives_the_file_a_float32_one_gives(tmp_path: Path) -> None:
    single = record(*random_events(np.random.default_rng(5), 20))
    double = ak.zip(
        {
            name: (
                ak.values_astype(single[name], np.float64)
                if name in FLOAT_FIELDS
                else single[name]
            )
            for name in single.fields
        },
        depth_limit=1,
    )
    paths = tmp_path / "single.hepmc", tmp_path / "double.hepmc"
    write_hepmc_input([single], paths[0])
    write_hepmc_input([double], paths[1])
    assert paths[1].read_bytes() == paths[0].read_bytes()


def test_writing_needs_no_pyhepmc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pyhepmc", None)
    assert (
        write_hepmc_input([record(pi0_to_two_photons())], tmp_path / "input.hepmc") == 1
    )


@pytest.mark.parametrize("threads", [2, 3, 7, 64])
def test_the_file_does_not_depend_on_the_number_of_threads(
    threads: int, tmp_path: Path
) -> None:
    events = record(*random_events(np.random.default_rng(13), 120))
    one, many = tmp_path / "one.hepmc", tmp_path / "many.hepmc"
    assert write_hepmc_input([events[:50], events[50:]], one) == 120
    chunks = [events[:50], events[50:]]
    assert write_hepmc_input(chunks, many, threads=threads) == 120
    assert many.read_bytes() == one.read_bytes()


@pytest.mark.parametrize("threads", [1, 4])
def test_the_first_refusal_ends_the_file_whatever_the_threads(
    threads: int, tmp_path: Path
) -> None:
    events = [pi0_to_two_photons()] * 40
    events[11] = [*BEAMS, particle(22, 1, at=DECAY_VERTEX)]
    events[33] = [BEAMS[0], particle(22, 1)]
    path = tmp_path / "input.hepmc"
    with pytest.raises(ValueError, match="particle 2 of event 11 lies away"):
        write_hepmc_input([record(*events)], path, threads=threads)
    lines = path.read_text().splitlines()
    numbers = [int(line.split()[1]) for line in lines if line.startswith("E ")]
    assert numbers == list(range(11))


@pytest.mark.parametrize(
    ("threads", "error"),
    [(0, ValueError), (-2, ValueError), (2.0, TypeError), (True, TypeError)],
)
def test_a_thread_count_that_is_not_a_positive_integer_is_refused(
    threads: object, error: type[Exception], tmp_path: Path
) -> None:
    with pytest.raises(error, match="threads"):
        write_hepmc_input(
            [record(pi0_to_two_photons())],
            tmp_path / "input.hepmc",
            threads=threads,  # type: ignore[arg-type]
        )


def _yielded_until_refused(
    particles: ak.Array,
) -> tuple[list[HepevtArrays], str | None]:
    """Return the events iterate_hepevt_arrays yields, and its refusal if any."""
    yielded: list[HepevtArrays] = []
    try:
        for arrays in iterate_hepevt_arrays(particles):
            yielded.append(arrays)
    except ValueError as error:
        return yielded, str(error)
    return yielded, None


def _same_record(arrays: HepevtArrays, expected: dict[str, object]) -> None:
    assert arrays.pid.tolist() == expected["pid"]
    assert arrays.status.tolist() == expected["status"]
    assert arrays.parents.tolist() == expected["parents"]
    positions = np.column_stack([arrays.vx, arrays.vy, arrays.vz, arrays.vt])
    assert np.float32(positions).tolist() == expected["positions"]


@pytest.mark.parametrize("seed", [21, 22, 23])
def test_the_records_follow_the_rules_written_out_particle_by_particle(
    seed: int,
) -> None:
    events = random_events(np.random.default_rng(seed), 100)
    yielded, refusal = _yielded_until_refused(record(*events, first_index=5))
    assert refusal is None
    for number, (arrays, rows) in enumerate(zip(yielded, events, strict=True), 5):
        expected = reference_record(rows, number)
        assert isinstance(expected, dict)
        _same_record(arrays, expected)


@pytest.mark.parametrize("seed", range(30))
def test_an_event_that_breaks_a_rule_ends_the_records_as_written_out(
    seed: int,
) -> None:
    rng = np.random.default_rng(seed)
    events = with_a_fault(rng, random_events(rng, 12))
    expected = [reference_record(rows, number) for number, rows in enumerate(events)]
    first_refused = next(k for k, item in enumerate(expected) if isinstance(item, str))
    yielded, refusal = _yielded_until_refused(record(*events))
    assert refusal is not None and refusal.startswith(str(expected[first_refused]))
    assert len(yielded) == first_refused
    for arrays, item in zip(yielded, expected, strict=False):
        assert isinstance(item, dict)
        _same_record(arrays, item)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("daughters", [1, 2])
def test_a_position_that_is_not_finite_is_refused(value: float, daughters: int) -> None:
    at = (value, 1.0, 1.0, 1.0)
    rows = [
        *BEAMS,
        particle(111, 2),
        *(particle(22, 1, m1=2, at=at) for _ in range(daughters)),
    ]
    with pytest.raises(
        ValueError, match="particle 3 of event 0 lies at a position that is not finite"
    ):
        arrays_of(rows)


def test_an_event_index_beyond_an_int_ends_the_file_at_that_event(
    tmp_path: Path,
) -> None:
    events = record(*[pi0_to_two_photons()] * 3, first_index=2**31 - 2)
    path = tmp_path / "input.hepmc"
    with pytest.raises(ValueError, match="event_index 2147483648 does not fit"):
        write_hepmc_input([events], path)
    lines = path.read_text().splitlines()
    assert [line.split()[1] for line in lines if line.startswith("E ")] == [
        "2147483646",
        "2147483647",
    ]


def test_the_events_after_a_refused_one_are_neither_written_nor_yielded(
    tmp_path: Path,
) -> None:
    refused = [*BEAMS, particle(22, 1, at=DECAY_VERTEX)]
    events = record(
        pi0_to_two_photons(), pi0_to_two_photons(), refused, pi0_to_two_photons()
    )
    yielded, refusal = _yielded_until_refused(events)
    assert [arrays.event_number for arrays in yielded] == [0, 1]
    assert refusal is not None and "event 2" in refusal
    path = tmp_path / "input.hepmc"
    with pytest.raises(ValueError, match="event 2"):
        write_hepmc_input([events], path)
    lines = path.read_text().splitlines()
    assert [line.split()[1] for line in lines if line.startswith("E ")] == ["0", "1"]


def test_a_float64_record_keeps_its_digits(tmp_path: Path) -> None:
    photon = particle(22, 1, p=(0.1, 0.0, 0.0, 0.1))
    double = record([*BEAMS, photon], real=np.float64)
    single = record([*BEAMS, photon])
    mixed = ak.with_field(single, double["part_px"], "part_px")
    for particles in (double, mixed):
        path = tmp_path / "input.hepmc"
        write_hepmc_input([particles], path, precision=16)
        assert " 1.0000000000000001e-01 " in path.read_text()


def test_an_existing_file_is_replaced(tmp_path: Path) -> None:
    path, once = tmp_path / "input.hepmc", tmp_path / "once.hepmc"
    write_hepmc_input([record(*[pi0_to_two_photons()] * 5)], path)
    write_hepmc_input([record(pi0_to_two_photons())], path)
    write_hepmc_input([record(pi0_to_two_photons())], once)
    assert path.read_bytes() == once.read_bytes()


def test_fields_of_different_lengths_are_refused() -> None:
    particles = record(pi0_to_two_photons())
    shorter = ak.Array([[1.0, 2.0]])
    broken = ak.zip(
        {
            name: shorter if name == "part_px" else particles[name]
            for name in particles.fields
        },
        depth_limit=1,
    )
    with pytest.raises(ValueError, match="every particle column"):
        list(iterate_hepevt_arrays(broken))
