import zlib
from collections.abc import Callable
from pathlib import Path

import awkward as ak
import numpy as np
import pytest
import uproot
from delphes_records import write_delphes_file

from omphjc.events import EventFile, EventFormat
from omphjc.events.delphes_root import SPEED_OF_LIGHT_MM_PER_S, DelphesRootReader
from omphjc.events.particles import FIELDS, build_record
from omphjc.events.readers import reader_for

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


@pytest.fixture
def record_file(tmp_path: Path) -> EventFile:
    path = tmp_path / "particles.root"
    write_delphes_file(path, PARTICLES, EVENTS)
    return EventFile(path, EventFormat.DELPHES_ROOT)


@pytest.fixture
def write_file(tmp_path: Path) -> Callable[..., EventFile]:
    """Return a function that writes a Delphes file with the given changes."""

    def write(**changes: object) -> EventFile:
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
    assert EventFormat.DELPHES_ROOT == "delphes-root"


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


def test_the_production_time_is_read_as_c_t_in_mm(record_file: EventFile) -> None:
    times = ak.to_numpy(ak.flatten(reader_for(record_file).read_particles()["part_t"]))
    stored = np.array([1e-12, 2e-12, 3e-12, 0.0, 0.0], dtype=np.float32)
    np.testing.assert_allclose(times, stored * SPEED_OF_LIGHT_MM_PER_S, rtol=1e-6)
    assert times[0] == pytest.approx(0.299792458, rel=1e-6)


def test_without_downcasting_the_stored_dtypes_are_kept(record_file: EventFile) -> None:
    kept = reader_for(record_file).read_particles(downcast=False)
    cast = reader_for(record_file).read_particles()
    for name in ("part_status", "part_charge"):
        assert ak.to_numpy(ak.flatten(kept[name])).dtype == np.int32
        assert ak.to_numpy(ak.flatten(cast[name])).dtype == np.int16
        assert kept[name].tolist() == cast[name].tolist()
    np.testing.assert_array_equal(
        ak.to_numpy(ak.flatten(kept["part_t"])), ak.to_numpy(ak.flatten(cast["part_t"]))
    )


def test_a_value_outside_int16_is_refused_when_downcasting(
    write_file: Callable[..., EventFile],
) -> None:
    event_file = write_file(particles={"Status": ak.Array([[2, 40000, 1], [], [1, 1]])})
    with pytest.raises(ValueError, match=r"part_status holds values from 1 to 40000"):
        reader_for(event_file).read_particles()
    assert (
        reader_for(event_file).read_particles(downcast=False)["part_status"][0, 1]
        == 40000
    )


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


@pytest.mark.parametrize(("start", "stop"), [(-1, None), (2, 1), (0, 4)])
def test_a_range_outside_the_file_is_refused(
    record_file: EventFile, start: int, stop: int | None
) -> None:
    with pytest.raises(ValueError, match="lie outside the 3 events"):
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


def test_a_memory_step_size_inflates_each_basket_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_file = _random_file(
        tmp_path / "random.root", n_events=200, events_per_basket=20
    )
    calls = 0
    decompress = zlib.decompress

    def counting_decompress(*args: object, **kwargs: object) -> bytes:
        nonlocal calls
        calls += 1
        return decompress(*args, **kwargs)

    monkeypatch.setattr(zlib, "decompress", counting_decompress)
    reader_for(event_file).read_particles()
    whole_file_calls, calls = calls, 0
    list(reader_for(event_file).iterate_particles(step_size="1 GB"))
    # 25 branches of 10 baskets each, besides the tree's own metadata.
    assert whole_file_calls >= 250
    assert calls == whole_file_calls


def test_the_reader_of_a_file_follows_its_format(record_file: EventFile) -> None:
    reader = reader_for(record_file)
    assert isinstance(reader, DelphesRootReader) and reader.path == record_file.path


def test_the_event_count_is_the_tree_entry_count(record_file: EventFile) -> None:
    assert reader_for(record_file).count_events() == 3


def test_a_missing_branch_is_named(write_file: Callable[..., EventFile]) -> None:
    event_file = write_file(omit=("Particle.Charge", "Event.Scale"))
    with pytest.raises(ValueError, match="lacks Event.Scale, Particle.Charge"):
        reader_for(event_file).read_particles()


def test_a_file_without_tree_delphes_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.root"
    with uproot.recreate(path) as file:
        file.mktree("Other", {"x": np.int32}).extend({"x": np.array([1])})
    with pytest.raises(ValueError, match="has no tree 'Delphes'"):
        reader_for(EventFile(path, EventFormat.DELPHES_ROOT)).count_events()


@pytest.mark.parametrize(
    ("member", "values", "field"),
    [
        ("M1", [[-1, 0, 3], [], [-1, -1]], "part_m1"),
        ("D1", [[1, -2, -1], [], [-1, -1]], "part_d1"),
        ("D2", [[2, -1, -1], [], [-1, 2]], "part_d2"),
    ],
)
def test_an_index_outside_its_event_is_refused(
    write_file: Callable[..., EventFile],
    member: str,
    values: list[list[int]],
    field: str,
) -> None:
    event_file = write_file(particles={member: ak.Array(values)})
    with pytest.raises(ValueError, match=f"{field} holds an index outside"):
        reader_for(event_file).read_particles()


def test_an_event_branch_without_one_entry_per_event_is_refused(
    write_file: Callable[..., EventFile],
) -> None:
    event_file = write_file(event_entries=np.array([1, 2, 1]))
    with pytest.raises(ValueError, match="other than one entry per event"):
        reader_for(event_file).read_particles()


def test_an_unreadable_format_is_refused(tmp_path: Path) -> None:
    event_file = EventFile(tmp_path / "events.lhe.gz", EventFormat.LHE)
    with pytest.raises(ValueError, match="readable formats: delphes-root"):
        reader_for(event_file)


def test_a_record_with_other_fields_than_the_schema_is_refused() -> None:
    columns = {field.name: ak.Array([0]) for field in FIELDS if field.name != "weight"}
    columns["extra"] = ak.Array([0])
    with pytest.raises(ValueError, match=r"missing \['weight'\], unknown \['extra'\]"):
        build_record(columns, downcast=True)
