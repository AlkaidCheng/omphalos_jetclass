import json
import math

import awkward as ak
import numpy as np
import pytest

from omphjc.events.long_lived import LongLivedRestorer

# Nominal c*tau in mm, PDG 2026 (https://pdg.lbl.gov/2026/tables/rpp2026-sum-mesons.pdf,
# rpp2026-sum-baryons.pdf and rpp2026-sum-leptons.pdf), with the CMS threshold of
# 10 mm that Parnassus asks for.
PDG_2026_CTAU_MM = {
    310: 26.844,
    3122: 78.45,
    3222: 24.04,
    3112: 44.34,
    3322: 87.1,
    3312: 49.1,
    3334: 24.61,
    211: 7804.5,
    321: 3711.0,
    130: 15340.0,
    13: 658638.4,
    2112: 2.633e14,
}
CMS_RESTORER = LongLivedRestorer(ctau_min_mm=10.0, ctau_mm=PDG_2026_CTAU_MM)

FIELDS = (
    "part_pid",
    "part_status",
    "part_m1",
    "part_m2",
    "part_d1",
    "part_d2",
    "part_charge",
    "part_px",
    "part_py",
    "part_pz",
    "part_e",
)
MOMENTUM_FIELDS = ("part_px", "part_py", "part_pz", "part_e")


def particle(
    pid: int,
    status: int,
    *,
    m1: int = -1,
    d1: int = -1,
    d2: int = -1,
    charge: int = 0,
    p: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> dict[str, float]:
    """Return one row of an event, with a single mother as decay products have."""
    px, py, pz, e = p
    return {
        "part_pid": pid,
        "part_status": status,
        "part_m1": m1,
        "part_m2": -1,
        "part_d1": d1,
        "part_d2": d2,
        "part_charge": charge,
        "part_px": px,
        "part_py": py,
        "part_pz": pz,
        "part_e": e,
    }


def record(*events: list[dict[str, float]]) -> ak.Array:
    """Return the particle records of `events`, each a list of rows."""
    counts = np.array([len(event) for event in events], dtype=np.int64)
    columns = {}
    for name in FIELDS:
        dtype = np.float32 if name in MOMENTUM_FIELDS else np.int32
        values = np.array([row[name] for event in events for row in event], dtype)
        columns[name] = ak.unflatten(values, counts)
    return ak.zip(columns, depth_limit=1)


def marks(
    particles: ak.Array, restorer: LongLivedRestorer = CMS_RESTORER
) -> tuple[list, list]:
    marked = restorer.restore(particles)
    return marked["part_final"].tolist(), marked["part_promoted"].tolist()


K0S_TO_PIONS = [
    particle(310, 2, d1=1, d2=2),
    particle(211, 1, m1=0, charge=1),
    particle(-211, 1, m1=0, charge=-1),
]


def test_a_decayed_k0s_is_final_and_its_pions_are_dropped() -> None:
    assert marks(record(K0S_TO_PIONS)) == (
        [[True, False, False]],
        [[True, False, False]],
    )


def test_of_a_cascade_only_the_first_long_lived_hadron_is_promoted() -> None:
    cascade = [
        particle(3312, 2, d1=1, d2=2),
        particle(3122, 2, m1=0, d1=3, d2=4),
        particle(-211, 1, m1=0),
        particle(2212, 1, m1=1),
        particle(-211, 1, m1=1),
    ]
    final, promoted = marks(record(cascade))
    assert final == [[True, False, False, False, False]]
    assert promoted == final


def test_every_generation_below_a_promoted_hadron_is_dropped() -> None:
    neutral_pions = [
        particle(310, 2, d1=1, d2=2),
        particle(111, 2, m1=0, d1=3, d2=4),
        particle(111, 2, m1=0, d1=5, d2=6),
        *(particle(22, 1, m1=mother) for mother in (1, 1, 2, 2)),
    ]
    final, promoted = marks(record(neutral_pions))
    assert final == [[True] + [False] * 6]
    assert promoted == final


def test_a_particle_whose_second_mother_is_dropped_is_dropped() -> None:
    rescattering = [
        particle(310, 2, d1=1, d2=2),
        particle(211, 2, m1=0, d1=4, d2=5),
        particle(-211, 1, m1=0),
        particle(2212, 2, d1=4, d2=5),
        {**particle(2212, 1, m1=3), "part_m2": 1},
        {**particle(211, 1, m1=3), "part_m2": 1},
    ]
    final, _ = marks(record(rescattering))
    assert final == [[True, False, False, False, False, False]]


def test_antiparticles_share_their_particles_entry() -> None:
    antibaryons = [
        particle(-3334, 2, d1=1, d2=2),
        particle(-3122, 2, m1=0, d1=3, d2=4),
        particle(321, 1, m1=0),
        particle(-2212, 1, m1=1),
        particle(211, 1, m1=1),
        particle(-3122, 2, d1=6, d2=7),
        particle(-2212, 1, m1=5),
        particle(211, 1, m1=5),
    ]
    final, promoted = marks(record(antibaryons))
    assert promoted == [[True, False, False, False, False, True, False, False]]
    assert final == promoted


def test_a_k0s_from_a_b_decay_is_promoted_and_its_siblings_are_kept() -> None:
    b_decay = [
        particle(521, 2, d1=1, d2=3),
        particle(310, 2, m1=0, d1=4, d2=5),
        particle(321, 1, m1=0),
        particle(22, 1, m1=0),
        particle(211, 1, m1=1),
        particle(-211, 1, m1=1),
    ]
    final, promoted = marks(record(b_decay))
    assert final == [[False, True, True, True, False, False]]
    assert promoted == [[False, True, False, False, False, False]]


def test_short_lived_species_are_left_decayed() -> None:
    short_lived = [
        particle(111, 2, d1=1, d2=2),
        particle(22, 1, m1=0),
        particle(22, 1, m1=0),
        particle(421, 2, d1=4, d2=5),
        particle(-321, 1, m1=3),
        particle(211, 1, m1=3),
        particle(511, 2, d1=7, d2=7),
        particle(-411, 1, m1=6),
    ]
    final, promoted = marks(record(short_lived))
    assert final == [[row["part_status"] == 1 for row in short_lived]]
    assert promoted == [[False] * len(short_lived)]


def test_beams_and_intermediate_particles_are_not_final() -> None:
    shower = [
        particle(2212, 4, d1=2, d2=2),
        particle(2212, 4, d1=3, d2=3),
        particle(21, 23, m1=0, d1=4, d2=4),
        particle(2, 62, m1=1, d1=5, d2=6),
        particle(21, 62, m1=2, d1=5, d2=6),
        particle(310, 2, m1=3, d1=7, d2=8),
        particle(211, 1, m1=3),
        particle(211, 1, m1=5, charge=1),
        particle(-211, 1, m1=5, charge=-1),
    ]
    final, promoted = marks(record(shower))
    assert final == [[False, False, False, False, False, True, True, False, False]]
    assert promoted == [[False, False, False, False, False, True, False, False, False]]


def test_marking_again_changes_nothing_and_an_undecayed_k0s_stays_final() -> None:
    particles = record(K0S_TO_PIONS, [particle(310, 1)])
    marked = CMS_RESTORER.restore(particles)
    again = CMS_RESTORER.restore(marked)
    assert again.tolist() == marked.tolist()
    assert marked["part_final"].tolist()[1] == [True]
    assert marked["part_promoted"].tolist()[1] == [False]


def test_the_final_four_momentum_and_charge_are_conserved() -> None:
    pi_plus, pi_minus = (0.3, 0.1, 1.0, 1.1), (0.2, -0.1, 0.5, 0.6)
    kaon, photon = (-0.4, 0.7, 2.0, 2.2), (0.1, 0.2, -0.3, 0.4)
    k0s = tuple(a + b for a, b in zip(pi_plus, pi_minus, strict=True))
    b_meson = tuple(sum(p) for p in zip(k0s, kaon, photon, strict=True))
    particles = record(
        [
            particle(521, 2, d1=1, d2=3, charge=1, p=b_meson),
            particle(310, 2, m1=0, d1=4, d2=5, p=k0s),
            particle(321, 1, m1=0, charge=1, p=kaon),
            particle(22, 1, m1=0, p=photon),
            particle(211, 1, m1=1, charge=1, p=pi_plus),
            particle(-211, 1, m1=1, charge=-1, p=pi_minus),
        ]
    )

    def totals(final: ak.Array) -> np.ndarray:
        names = ("part_px", "part_py", "part_pz", "part_e", "part_charge")
        return np.array([ak.sum(final[name]) for name in names], dtype=np.float64)

    restored = CMS_RESTORER.restore(particles)
    showered = particles[particles["part_status"] == 1]
    np.testing.assert_allclose(
        totals(restored[restored["part_final"]]), totals(showered), atol=1e-6
    )


def test_empty_events_and_an_empty_record_are_marked() -> None:
    assert marks(record([], K0S_TO_PIONS, [])) == (
        [[], [True, False, False], []],
        [[], [True, False, False], []],
    )
    assert marks(record()) == ([], [])


@pytest.mark.parametrize(
    "rows",
    [
        [particle(310, 2, d1=1, d2=3), particle(211, 1, m1=0)],
        [particle(310, 2, d1=-2, d2=-1)],
        [particle(310, 1), particle(211, 1, m1=2)],
    ],
)
def test_an_index_outside_its_event_is_refused(rows: list[dict[str, float]]) -> None:
    with pytest.raises(ValueError, match="outside the event's"):
        CMS_RESTORER.restore(record(rows))


def test_the_refusal_names_the_particle_and_its_event() -> None:
    events = record(K0S_TO_PIONS, [], [particle(310, 2, d1=2, d2=2), particle(22, 1)])
    with pytest.raises(
        ValueError,
        match="part_d1 of particle 0 in event 2 is 2, outside the event's 2 particles",
    ):
        CMS_RESTORER.restore(events)
    events = ak.with_field(events, np.array([7, 8, 9]), "event_index")
    with pytest.raises(ValueError, match="part_d1 of particle 0 in event 9 is 2"):
        CMS_RESTORER.restore(events)


def test_a_cyclic_record_is_marked_in_finite_passes() -> None:
    cycle = [particle(310, 2, m1=1, d1=1, d2=1), particle(22, 1, m1=0, d1=0, d2=0)]
    assert marks(record(cycle)) == ([[False, False]], [[False, False]])


# Species the random decay trees draw from: long-lived, short-lived and stable.
SPECIES = (310, 3122, -3122, 3312, 3334, 211, -211, 321, 13, 111, 421, 521, 22, 11)


def _random_event(rng: np.random.Generator) -> list[dict[str, float]]:
    """Return a random decay tree whose daughters follow Pythia's conventions.

    A decayed particle has as daughters a carbon copy of itself (d1 == d2), a
    single other particle (d2 = -1), a range d1..d2, or two particles stored
    apart with the later one first (d2 < d1).
    """
    rows: list[dict[str, float]] = []

    def add(pid: int, mother: int) -> int:
        rows.append(particle(pid, 1, m1=mother))
        if mother >= 0 and rng.random() < 0.5:
            rows[-1]["part_m2"] = mother
        return len(rows) - 1

    def species() -> int:
        return int(rng.choice(SPECIES))

    for _ in range(int(rng.integers(1, 4))):
        add(species(), -1)
    index = 0
    while index < len(rows) and len(rows) < 60:
        row = rows[index]
        if rng.random() < 0.6:
            # Most decay; some branch in the shower instead and keep its status.
            row["part_status"] = 2 if rng.random() < 0.8 else 51
            case = int(rng.integers(4))
            if case == 0:
                row["part_d1"] = row["part_d2"] = add(int(row["part_pid"]), index)
            elif case == 1:
                row["part_d1"] = add(species(), index)
            elif case == 2:
                daughters = [
                    add(species(), index) for _ in range(int(rng.integers(2, 4)))
                ]
                row["part_d1"], row["part_d2"] = daughters[0], daughters[-1]
            else:
                first = add(species(), index)
                add(species(), -1)
                row["part_d1"], row["part_d2"] = add(species(), index), first
        index += 1
    return rows


def _walk_down(
    rows: list[dict[str, float]], long_lived: frozenset[int]
) -> tuple[list[bool], list[bool]]:
    """Return the final and promoted marks found by walking down the daughters."""

    def daughters(row: dict[str, float]) -> list[int]:
        d1, d2 = int(row["part_d1"]), int(row["part_d2"])
        if d1 < 0:
            return []
        if d2 < 0 or d2 == d1:
            return [d1]
        return list(range(d1, d2 + 1)) if d1 < d2 else [d1, d2]

    candidate = [
        abs(int(row["part_pid"])) in long_lived
        and row["part_status"] == 2
        and row["part_d1"] >= 0
        and not (
            row["part_d1"] == row["part_d2"]
            and rows[int(row["part_d1"])]["part_pid"] == row["part_pid"]
        )
        for row in rows
    ]
    dropped = [False] * len(rows)
    pending = [
        d for row, c in zip(rows, candidate, strict=True) if c for d in daughters(row)
    ]
    while pending:
        index = pending.pop()
        if not dropped[index]:
            dropped[index] = True
            pending.extend(daughters(rows[index]))
    promoted = [c and not d for c, d in zip(candidate, dropped, strict=True)]
    final = [
        (row["part_status"] == 1 or p) and not d
        for row, p, d in zip(rows, promoted, dropped, strict=True)
    ]
    return final, promoted


def test_the_walk_up_the_mothers_agrees_with_one_down_the_daughters() -> None:
    rng = np.random.default_rng(2026)
    events = [_random_event(rng) for _ in range(300)]
    final, promoted = marks(record(*events))
    expected = [_walk_down(rows, CMS_RESTORER.long_lived) for rows in events]
    assert final == [marks_of_event[0] for marks_of_event in expected]
    assert promoted == [marks_of_event[1] for marks_of_event in expected]
    assert sum(map(sum, promoted)) > 50


def test_the_last_copy_of_a_carbon_copy_chain_is_promoted() -> None:
    copies = record(
        [
            particle(310, 2, d1=1, d2=1, p=(1.0, 0.0, 2.0, 2.3)),
            particle(310, 2, m1=0, d1=2, d2=3, p=(0.9, 0.1, 2.0, 2.3)),
            particle(211, 1, m1=1),
            particle(-211, 1, m1=1),
        ]
    )
    marked = CMS_RESTORER.restore(copies)
    assert marked["part_final"].tolist() == [[False, True, False, False]]
    assert marked["part_promoted"].tolist() == [[False, True, False, False]]
    kept = marked[marked["part_final"]]
    assert kept["part_px"].tolist() == [[pytest.approx(0.9)]]


def test_a_decayed_charged_pion_is_promoted_and_its_muon_dropped() -> None:
    pion = [particle(211, 2, d1=1, d2=2), particle(-13, 1, m1=0), particle(14, 1, m1=0)]
    assert marks(record(pion)) == ([[True, False, False]], [[True, False, False]])


def test_a_muon_that_radiated_a_photon_is_left_to_the_shower() -> None:
    radiating = [
        particle(13, 23, d1=1, d2=2),
        particle(13, 1, m1=0),
        particle(22, 1, m1=0),
    ]
    assert marks(record(radiating)) == ([[False, True, True]], [[False] * 3])


@pytest.mark.parametrize(
    "restorer",
    [
        LongLivedRestorer(ctau_min_mm=100.0, ctau_mm={3312: 49.1, 3122: 78.45}),
        LongLivedRestorer(ctau_min_mm=10.0, ctau_mm={}),
    ],
)
def test_with_no_species_above_the_threshold_the_final_state_is_status_1(
    restorer: LongLivedRestorer,
) -> None:
    cascade = record(
        [
            particle(3312, 2, d1=1, d2=2),
            particle(3122, 2, m1=0, d1=3, d2=4),
            particle(-211, 1, m1=0),
            particle(2212, 1, m1=1),
            particle(-211, 1, m1=1),
        ]
    )
    final, promoted = marks(cascade, restorer)
    assert final == [[False, False, True, True, True]]
    assert promoted == [[False] * 5]


def test_a_restorer_records_its_threshold_and_table() -> None:
    restorer = LongLivedRestorer(ctau_min_mm=10, ctau_mm={3122: 78.45, 310: 27})
    assert restorer.as_record() == {
        "ctau_min_mm": 10.0,
        "ctau_mm": {"310": 27.0, "3122": 78.45},
    }
    assert json.dumps(restorer.as_record(), sort_keys=True) == (
        '{"ctau_min_mm": 10.0, "ctau_mm": {"310": 27.0, "3122": 78.45}}'
    )


def test_the_long_lived_species_are_those_above_the_threshold() -> None:
    assert CMS_RESTORER.long_lived == frozenset(PDG_2026_CTAU_MM)
    raised = LongLivedRestorer(ctau_min_mm=25.0, ctau_mm=PDG_2026_CTAU_MM)
    assert raised.long_lived == frozenset(PDG_2026_CTAU_MM) - {3222, 3334}
    at_k0s = LongLivedRestorer(ctau_min_mm=26.844, ctau_mm=PDG_2026_CTAU_MM)
    assert at_k0s.long_lived == frozenset(PDG_2026_CTAU_MM) - {310, 3222, 3334}


def test_a_restorer_keeps_a_copy_of_its_table() -> None:
    table = {310: 26.844}
    restorer = LongLivedRestorer(ctau_min_mm=10.0, ctau_mm=table)
    table[3122] = 78.45
    assert restorer.long_lived == {310}
    assert restorer == LongLivedRestorer(ctau_min_mm=10.0, ctau_mm={310: 26.844})


@pytest.mark.parametrize(
    ("threshold", "table"),
    [
        (10.0, {-3122: 78.45}),
        (10.0, {0: 78.45}),
        (10.0, {"3122": 78.45}),
        (10.0, {True: 78.45}),
        (10.0, {3122: 0.0}),
        (10.0, {3122: -1.0}),
        (10.0, {3122: math.inf}),
        (10.0, {3122: math.nan}),
        (10.0, {3122: "78.45"}),
        (0.0, {3122: 78.45}),
        (-10.0, {3122: 78.45}),
        (math.inf, {3122: 78.45}),
        (True, {3122: 78.45}),
        ("10", {3122: 78.45}),
    ],
)
def test_an_invalid_restorer_is_refused(threshold: object, table: object) -> None:
    with pytest.raises(ValueError):
        LongLivedRestorer(ctau_min_mm=threshold, ctau_mm=table)
