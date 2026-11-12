from collections.abc import Callable
from pathlib import Path
from typing import Any

import awkward as ak
import numpy as np
import pytest
import uproot
from delphes_records import EVENT_DTYPES, PARTICLE_DTYPES, write_delphes_file

from omphjc.events import EventFile, EventFormat
from omphjc.events.delphes_root import (
    SPEED_OF_LIGHT_MM_PER_S,
    DelphesROOTFile,
    DelphesRootReader,
)
from omphjc.events.particles import FIELDS, build_record
from omphjc.events.readers import reader_for
from omphjc.events.stable_particles import StableParticleDefinition

# Three events: K0S -> pi+ pi-, an empty event, and a photon with an electron.
PARTICLES = {
    "PID": ak.Array([[310, 211, -211], [], [22, 11]]),
    "Status": ak.Array([[2, 1, 1], [], [1, 1]]),
    "M1": ak.Array([[-1, 0, 0], [], [-1, -1]]),
    "D1": ak.Array([[1, -1, -1], [], [-1, -1]]),
    "D2": ak.Array([[2, -1, -1], [], [-1, -1]]),
    "Charge": ak.Array([[0, 1, -1], [], [0, -1]]),
    "Px": ak.Array([[1.0, 0.6, 0.4], [], [5.0, -5.0]]),
    "E": ak.Array([[2.0, 1.1, 0.9], [], [5.0, 5.0]]),
    "T": ak.Array([[1e-12, 2e-12, 3e-12], [], [0.0, 0.0]]),
}
EVENTS = {
    "Number": np.array([0, 2, 3]),
    "Weight": np.array([1.0, 0.5, 2.0]),
    "Scale": np.array([91.2, 100.0, 50.0]),
    "ProcessID": np.full(3, 9999),
    "ID1": np.array([21, 1, -2]),
}
# The GenParticle or HepMCEvent member each record field is read from.
MEMBER_OF_FIELD = {
    "event_number": "Number",
    "weight": "Weight",
    "scale": "Scale",
    "alpha_qcd": "AlphaQCD",
    "alpha_qed": "AlphaQED",
    "id1": "ID1",
    "id2": "ID2",
    "x1": "X1",
    "x2": "X2",
    "part_pid": "PID",
    "part_status": "Status",
    "part_m1": "M1",
    "part_m2": "M2",
    "part_d1": "D1",
    "part_d2": "D2",
    "part_charge": "Charge",
    "part_mass": "Mass",
    "part_px": "Px",
    "part_py": "Py",
    "part_pz": "Pz",
    "part_e": "E",
    "part_x": "X",
    "part_y": "Y",
    "part_z": "Z",
    "part_t": "T",
}


@pytest.fixture
def record_file(tmp_path: Path) -> EventFile:
    path = tmp_path / "particles.root"
    write_delphes_file(path, PARTICLES, EVENTS)
    return EventFile(path, EventFormat.DELPHES_ROOT)


@pytest.fixture
def write_file(tmp_path: Path) -> Callable[..., EventFile]:
    """Return a function that writes a Delphes file with the given changes."""

    def write(**changes: Any) -> EventFile:
        path = tmp_path / "changed.root"
        particles = {**PARTICLES, **changes.pop("particles", {})}
        write_delphes_file(path, particles, EVENTS, **changes)
        return EventFile(path, EventFormat.DELPHES_ROOT)

    return write


def _random_file(path: Path, *, n_events: int, events_per_basket: int) -> EventFile:
    rng = np.random.default_rng(7)
    counts = rng.integers(0, 40, n_events)
    n = int(counts.sum())
    particles = {
        "PID": ak.unflatten(rng.integers(-300, 300, n), counts),
        "Status": ak.unflatten(np.ones(n, dtype=np.int64), counts),
        "Px": ak.unflatten(rng.normal(size=n), counts),
        "T": ak.unflatten(rng.normal(size=n) * 1e-12, counts),
    }
    write_delphes_file(path, particles, events_per_basket=events_per_basket)
    return EventFile(path, EventFormat.DELPHES_ROOT)


def test_formats_and_event_files_round_trip_through_their_values(
    tmp_path: Path,
) -> None:
    for event_format in EventFormat:
        assert EventFormat(event_format.value) is event_format
    event_file = EventFile(tmp_path / "particles.root", EventFormat.DELPHES_ROOT)
    assert EventFile(event_file.path, EventFormat("delphes-root")) == event_file
    name: str = EventFormat.DELPHES_ROOT
    assert name == "delphes-root"


def test_the_record_has_the_schema_fields_in_order_and_dtypes(
    record_file: EventFile,
) -> None:
    record = reader_for(record_file).read_particles()
    assert record.fields == [field.name for field in FIELDS]
    for field in FIELDS:
        assert (
            ak.to_numpy(ak.flatten(record[field.name], axis=None)).dtype == field.dtype
        )
    assert ak.num(record["part_pid"], axis=1).tolist() == [3, 0, 2]
    assert record["part_pid"].tolist() == PARTICLES["PID"].tolist()
    assert record["event_number"].tolist() == [0, 2, 3]
    assert record["id1"].tolist() == [21, 1, -2]
    assert record["part_m2"].tolist() == [[-1, -1, -1], [], [-1, -1]]


def test_each_field_is_read_from_its_own_member(tmp_path: Path) -> None:
    counts = [3, 0, 2]
    n_particles = sum(counts)
    # Every member gets values of its own, so a field read from another differs.
    particles = {
        name: ak.unflatten(np.arange(n_particles) * 100 + k, counts)
        for k, name in enumerate(PARTICLE_DTYPES)
    }
    events = {
        name: np.arange(len(counts)) * 100 + k for k, name in enumerate(EVENT_DTYPES)
    }
    path = tmp_path / "distinct.root"
    write_delphes_file(path, particles, events)
    record = reader_for(EventFile(path, EventFormat.DELPHES_ROOT)).read_particles()
    for field, member in MEMBER_OF_FIELD.items():
        if field.startswith("part_"):
            expected = ak.to_numpy(ak.flatten(particles[member])).astype(np.float64)
            read = ak.to_numpy(ak.flatten(record[field])).astype(np.float64)
        else:
            expected = events[member].astype(np.float64)
            read = ak.to_numpy(record[field]).astype(np.float64)
        if field == "part_t":
            expected = expected * SPEED_OF_LIGHT_MM_PER_S
        np.testing.assert_allclose(read, expected, rtol=1e-5, err_msg=field)


def test_each_field_has_a_known_unit_and_a_description() -> None:
    assert {field.unit for field in FIELDS} <= {"", "GeV", "mm", "e"}
    assert all(field.description.endswith(".") for field in FIELDS)


def test_the_production_time_is_read_as_c_t_in_mm(record_file: EventFile) -> None:
    times = ak.to_numpy(ak.flatten(reader_for(record_file).read_particles()["part_t"]))
    stored = np.array([1e-12, 2e-12, 3e-12, 0.0, 0.0], dtype=np.float32)
    np.testing.assert_allclose(times, stored * SPEED_OF_LIGHT_MM_PER_S, rtol=1e-6)
    assert times[0] == pytest.approx(0.299792458, rel=1e-6)


def test_without_downcasting_the_stored_dtypes_are_kept(record_file: EventFile) -> None:
    kept = reader_for(record_file).read_particles(downcast=False)
    cast = reader_for(record_file).read_particles()
    step = next(iter(reader_for(record_file).iterate_particles(downcast=False)))
    for name in ("part_status", "part_charge"):
        assert ak.to_numpy(ak.flatten(kept[name])).dtype == np.int32
        assert ak.to_numpy(ak.flatten(step[name])).dtype == np.int32
        assert ak.to_numpy(ak.flatten(cast[name])).dtype == np.int16
        assert kept[name].tolist() == cast[name].tolist()
    np.testing.assert_array_equal(
        ak.to_numpy(ak.flatten(kept["part_t"])), ak.to_numpy(ak.flatten(cast["part_t"]))
    )


@pytest.mark.parametrize("value", [40000, -40000])
def test_a_value_outside_int16_is_refused_when_downcasting(
    write_file: Callable[..., EventFile], value: int
) -> None:
    event_file = write_file(particles={"Status": ak.Array([[2, value, 1], [], [1, 1]])})
    with pytest.raises(
        ValueError,
        match=rf"part_status holds values from {min(value, 1)} to {max(value, 2)}",
    ):
        reader_for(event_file).read_particles()
    assert (
        reader_for(event_file).read_particles(downcast=False)["part_status"][0, 1]
        == value
    )


@pytest.mark.parametrize("value", [np.iinfo(np.int16).max, np.iinfo(np.int16).min])
def test_a_value_at_the_int16_limit_is_kept_when_downcasting(
    write_file: Callable[..., EventFile], value: int
) -> None:
    event_file = write_file(particles={"Status": ak.Array([[2, value, 1], [], [1, 1]])})
    status = reader_for(event_file).read_particles()["part_status"]
    assert ak.to_numpy(ak.flatten(status)).dtype == np.int16
    assert status[0, 1] == value


def test_a_charge_unknown_to_root_fits_the_downcast(
    write_file: Callable[..., EventFile],
) -> None:
    event_file = write_file(
        particles={"Charge": ak.Array([[0, -999, -1], [], [0, -1]])}
    )
    assert reader_for(event_file).read_particles()["part_charge"][0, 1] == -999


def test_the_event_index_counts_entries_from_the_file_start(
    record_file: EventFile,
) -> None:
    assert reader_for(record_file).read_particles()["event_index"].tolist() == [0, 1, 2]
    assert reader_for(record_file).read_particles(entry_start=1)[
        "event_index"
    ].tolist() == [1, 2]
    part = reader_for(record_file).read_particles(entry_start=1, entry_stop=2)
    assert part["event_index"].tolist() == [1]
    assert part["event_number"].tolist() == [2]
    kept = reader_for(record_file).read_particles(downcast=False)
    assert ak.to_numpy(kept["event_index"]).dtype == np.int64


@pytest.mark.parametrize(("start", "stop"), [(-1, None), (0, 4)])
def test_a_range_outside_the_file_is_refused(
    record_file: EventFile, start: int, stop: int | None
) -> None:
    with pytest.raises(ValueError, match="lie outside the 3 entries"):
        reader_for(record_file).read_particles(entry_start=start, entry_stop=stop)


@pytest.mark.parametrize("step_size", [1, 2, 7, "1 kB", "1 GB"])
def test_the_steps_of_an_iteration_join_into_the_whole_record(
    tmp_path: Path, step_size: int | str
) -> None:
    event_file = _random_file(
        tmp_path / "random.root", n_events=50, events_per_basket=8
    )
    whole = reader_for(event_file).read_particles()
    steps = list(reader_for(event_file).iterate_particles(step_size=step_size))
    assert ak.concatenate(steps).tolist() == whole.tolist()
    if isinstance(step_size, int):
        assert [len(step) for step in steps] == [
            min(step_size, 50 - start) for start in range(0, 50, step_size)
        ]


def test_the_reader_of_a_file_follows_its_format(record_file: EventFile) -> None:
    reader = reader_for(record_file)
    assert isinstance(reader, DelphesRootReader) and reader.path == record_file.path


def test_the_event_count_is_the_tree_entry_count(record_file: EventFile) -> None:
    assert reader_for(record_file).count_events() == 3


def test_the_definition_applies_to_the_record_a_reader_gives(
    record_file: EventFile,
) -> None:
    definition = StableParticleDefinition(ctau_min_mm=10.0, ctau_mm={310: 26.844})
    for downcast in (True, False):
        record = reader_for(record_file).read_particles(downcast=downcast)
        marked = definition.apply(record)
        assert marked["part_final"].tolist() == [[True, False, False], [], [True, True]]
        assert marked["part_promoted"].tolist() == [
            [True, False, False],
            [],
            [False] * 2,
        ]


def test_a_delphes_file_has_the_same_fingerprint_whatever_time_its_events_took(
    tmp_path: Path, record_file: EventFile
) -> None:
    n_events = len(EVENTS["Number"])
    times = {"ReadTime": np.full(n_events, 7.25), "ProcTime": np.full(n_events, 0.5)}
    write_delphes_file(tmp_path / "slower.root", PARTICLES, {**EVENTS, **times})
    content = DelphesROOTFile.read(record_file.path)
    slower = DelphesROOTFile.read(tmp_path / "slower.root")
    assert content.fingerprint() == slower.fingerprint()
    assert content.fingerprint().startswith("delphes_root-v1:")
    assert "Event.Number" in content.leaves
    assert not {"Event.ReadTime", "Event.ProcTime"} & set(content.leaves)


def test_a_missing_branch_is_named(write_file: Callable[..., EventFile]) -> None:
    reader = reader_for(write_file(omit=("Particle.Charge", "Event.Scale")))
    for read in (reader.read_particles, reader.count_events):
        with pytest.raises(ValueError, match="lacks Event.Scale, Particle.Charge"):
            read()


def test_a_file_without_tree_delphes_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.root"
    with uproot.recreate(path) as file:
        file.mktree("Other", {"x": np.int32}).extend({"x": np.array([1])})
    with pytest.raises(ValueError, match="has no tree 'Delphes'"):
        reader_for(EventFile(path, EventFormat.DELPHES_ROOT)).count_events()


def test_an_event_branch_without_one_entry_per_event_is_refused(
    write_file: Callable[..., EventFile],
) -> None:
    event_file = write_file(event_entries=np.array([1, 2, 1]))
    with pytest.raises(
        ValueError, match="holds 2 entries at entry 1 of .*changed.root"
    ):
        reader_for(event_file).read_particles()


def test_an_unreadable_format_is_refused(tmp_path: Path) -> None:
    event_file = EventFile(tmp_path / "events.lhe.gz", EventFormat.LHE)
    with pytest.raises(ValueError, match="readable formats: delphes-root"):
        reader_for(event_file)


def test_a_record_holds_the_fields_it_is_given_in_the_schemas_order() -> None:
    record = build_record(
        {"part_pid": ak.Array([[211, 22]]), "event_index": ak.Array([0])},
        downcast=True,
    )
    assert record.fields == ["event_index", "part_pid"]
    assert record["part_pid"].tolist() == [[211, 22]]


def test_a_field_the_schema_does_not_know_is_refused() -> None:
    columns = {field.name: ak.Array([0]) for field in FIELDS[:2]}
    columns["extra"] = ak.Array([0])
    with pytest.raises(ValueError, match=r"no fields \['extra'\]"):
        build_record(columns, downcast=True)


def test_floats_are_downcast_as_they_are_and_integers_widened() -> None:
    record = build_record(
        {
            "part_px": ak.Array([[0.1, -2.5]]),
            "event_number": ak.values_astype(ak.Array([7]), np.int32),
        },
        downcast=True,
    )
    px = ak.to_numpy(ak.flatten(record["part_px"]))
    assert px.dtype == np.float32 and px.tolist() == [np.float32(0.1), -2.5]
    assert ak.to_numpy(record["event_number"]).dtype == np.int64


def test_a_cast_that_can_change_a_value_is_refused() -> None:
    with pytest.raises(ValueError, match="part_pid holds float64 values"):
        build_record({"part_pid": ak.Array([[211.5]])}, downcast=True)


def test_a_column_with_no_values_takes_the_schemas_dtype() -> None:
    record = build_record({"part_pid": ak.Array([[]])}, downcast=True)
    assert str(ak.type(record["part_pid"]).content) == "var * int32"
