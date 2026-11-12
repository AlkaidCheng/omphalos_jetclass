from pathlib import Path
from typing import ClassVar

import awkward as ak
import numpy as np
import pytest
import uproot
from delphes_records import write_delphes_file

from omphjc.root_files import ROOTFile, sampled_ranges

N_EVENTS = 1000

# An event in the second half of the tree that no sampled range holds.
UNSAMPLED_EVENT = next(
    event
    for event in range(N_EVENTS // 2, N_EVENTS)
    if not any(start <= event < stop for start, stop in sampled_ranges(N_EVENTS))
)


class EventTree(ROOTFile):
    """A file with its events in tree ``Delphes``, and every field counted."""

    format_name: ClassVar[str] = "event_tree"
    tree_name: ClassVar[str] = "Delphes"


class TimedEventTree(EventTree):
    """The same file without the time each event took."""

    excluded_fields: ClassVar[frozenset[str]] = frozenset({"ReadTime", "ProcTime"})


def _events(seed: int = 1, n_events: int = N_EVENTS) -> tuple[np.ndarray, np.ndarray]:
    """Return each event's particle count and the momenta, drawn from one stream."""
    rng = np.random.default_rng(seed)
    counts = rng.poisson(40, n_events)
    return counts, rng.normal(size=int(counts.sum()))


def _write(
    path: Path,
    counts: np.ndarray,
    momenta: np.ndarray,
    *,
    weights: np.ndarray | float = 1.0,
    stopwatch: float = 0.0,
    events_per_basket: int = 50,
) -> Path:
    """Write the events to `path` as a tree ``Delphes`` and return `path`."""
    times = np.full(len(counts), stopwatch)
    write_delphes_file(
        path,
        {"Px": ak.unflatten(momenta, counts)},
        {
            "ReadTime": times,
            "ProcTime": times,
            "Weight": np.full(len(counts), weights),
        },
        events_per_basket=events_per_basket,
    )
    return path


@pytest.fixture
def reference(tmp_path: Path) -> str:
    path = _write(tmp_path / "reference.root", *_events())
    return TimedEventTree.read(path).fingerprint()


def test_the_sampled_ranges_are_the_first_the_last_and_two_drawn() -> None:
    assert sampled_ranges(N_EVENTS) == [(0, 10), (135, 145), (350, 360), (990, 1000)]
    assert sampled_ranges(3) == [(0, 3)]
    assert sampled_ranges(0) == [(0, 0)]


def test_a_file_holds_the_entry_count_and_the_type_of_each_leaf(
    tmp_path: Path,
) -> None:
    content = EventTree.read(_write(tmp_path / "events.root", *_events()))
    assert content.n_entries == N_EVENTS
    assert content.leaves["Particle.Px"].type_name == "float[]"
    assert content.leaves["Event.Weight"].type_name == "float[]"
    assert content.content_record()["entries"] == N_EVENTS


def test_a_count_is_hashed_in_every_entry_and_a_list_in_the_sampled_ranges(
    tmp_path: Path,
) -> None:
    content = EventTree.read(_write(tmp_path / "events.root", *_events()))
    hashed_ranges = {
        name: {key.split(":")[0] for key in content.leaves[name].sha256_by_buffer}
        for name in ("Particle_size", "Particle.Px", "Event.Weight")
    }
    ranges = {f"{start}-{stop}" for start, stop in sampled_ranges(N_EVENTS)}
    assert hashed_ranges == {
        "Particle_size": {f"0-{N_EVENTS}"},
        "Particle.Px": ranges,
        "Event.Weight": ranges,
    }


def test_files_with_the_same_events_have_one_fingerprint(
    tmp_path: Path, reference: str
) -> None:
    rewritten = _write(
        tmp_path / "rewritten.root", *_events(), stopwatch=7.25, events_per_basket=30
    )
    assert TimedEventTree.read(rewritten).fingerprint() == reference
    assert reference.startswith("event_tree-v1:")


def test_a_field_counts_unless_it_is_excluded(tmp_path: Path) -> None:
    first = _write(tmp_path / "first.root", *_events())
    second = _write(tmp_path / "second.root", *_events(), stopwatch=7.25)
    assert EventTree.read(first).fingerprint() != EventTree.read(second).fingerprint()
    assert not any("Time" in name for name in TimedEventTree.read(first).leaves)


def test_the_status_bits_of_root_are_left_out_of_every_format(tmp_path: Path) -> None:
    path = tmp_path / "objects.root"
    with uproot.recreate(path) as file:
        tree = file.mktree("Delphes", {"fBits": np.int64, "PT": np.float64})
        tree.extend({"fBits": np.arange(3), "PT": np.arange(3.0)})
    assert set(EventTree.read(path).leaves) == {"PT"}


def test_another_seed_changes_the_fingerprint(tmp_path: Path, reference: str) -> None:
    other = _write(tmp_path / "other.root", *_events(seed=2))
    assert TimedEventTree.read(other).fingerprint() != reference


def test_a_stream_diverging_from_an_unsampled_event_changes_the_fingerprint(
    tmp_path: Path, reference: str
) -> None:
    counts, momenta = _events()
    first = counts[:UNSAMPLED_EVENT].sum()
    momenta[first:] = np.random.default_rng(2).normal(size=len(momenta) - first)
    diverging = _write(tmp_path / "diverging.root", counts, momenta)
    assert TimedEventTree.read(diverging).fingerprint() != reference


def test_a_particle_dropped_from_an_unsampled_event_changes_the_fingerprint(
    tmp_path: Path, reference: str
) -> None:
    counts, momenta = _events()
    momenta = np.delete(momenta, counts[:UNSAMPLED_EVENT].sum())
    counts[UNSAMPLED_EVENT] -= 1
    fewer = _write(tmp_path / "fewer.root", counts, momenta)
    assert TimedEventTree.read(fewer).fingerprint() != reference


def test_a_weight_changed_in_a_sampled_event_changes_the_fingerprint(
    tmp_path: Path, reference: str
) -> None:
    weights = np.ones(N_EVENTS)
    weights[-1] = 2.0
    weighted = _write(tmp_path / "weighted.root", *_events(), weights=weights)
    assert TimedEventTree.read(weighted).fingerprint() != reference


def test_values_changed_in_one_unsampled_event_are_missed(
    tmp_path: Path, reference: str
) -> None:
    counts, momenta = _events()
    momenta[counts[:UNSAMPLED_EVENT].sum()] += 1.0
    weights = np.ones(N_EVENTS)
    weights[UNSAMPLED_EVENT] = 2.0
    changed = _write(tmp_path / "changed.root", counts, momenta, weights=weights)
    assert TimedEventTree.read(changed).fingerprint() == reference


def test_a_tree_too_short_for_separate_ranges_is_read_whole(tmp_path: Path) -> None:
    counts, momenta = _events(n_events=3)
    short = TimedEventTree.read(_write(tmp_path / "short.root", counts, momenta))
    momenta[counts[0]] += 1.0
    changed = TimedEventTree.read(_write(tmp_path / "changed.root", counts, momenta))
    assert changed.fingerprint() != short.fingerprint()


def test_a_file_without_the_tree_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.root"
    with uproot.recreate(path) as file:
        file.mktree("Events", {"PT": np.float64}).extend({"PT": np.arange(3.0)})
    with pytest.raises(ValueError, match="Delphes"):
        EventTree.read(path)
