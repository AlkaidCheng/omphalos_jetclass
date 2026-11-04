from pathlib import Path

import awkward as ak
import numpy as np
import pytest
import uproot
from delphes_records import write_delphes_file

from omphjc.root_io import entries_per_step, memory_size

BRANCHES = ["Particle.PID", "Particle.Px", "Event.Number"]


@pytest.fixture
def tree_path(tmp_path: Path) -> Path:
    rng = np.random.default_rng(3)
    counts = rng.integers(0, 30, 100)
    particles = {
        "PID": ak.unflatten(rng.integers(-300, 300, int(counts.sum())), counts)
    }
    path = tmp_path / "tree.root"
    write_delphes_file(path, particles, events_per_basket=10)
    return path


def test_an_entry_count_is_returned_unchanged() -> None:
    assert entries_per_step(None, BRANCHES, 5) == 5


def test_a_memory_size_becomes_entries_from_the_branches_uncompressed_bytes(
    tree_path: Path,
) -> None:
    with uproot.open(tree_path) as file:
        tree = file["Delphes"]
        total = sum(tree[name].member("fTotBytes") for name in BRANCHES)
        per_entry = total / tree.num_entries
        assert entries_per_step(tree, BRANCHES, "10 kB") == int(10_000 // per_entry)
        assert entries_per_step(tree, BRANCHES, "1 B") == 1


def test_an_empty_tree_is_read_in_one_step(tmp_path: Path) -> None:
    path = tmp_path / "empty.root"
    write_delphes_file(path, {"PID": ak.Array([[0]])[:0]})
    with uproot.open(path) as file:
        assert entries_per_step(file["Delphes"], BRANCHES, "100 MB") == 1


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("100 MB", 100_000_000),
        ("1 kB", 1000),
        ("1KiB", 1024),
        ("1.5 GiB", 3 * 2**29),
        ("2 tb", 2 * 10**12),
        ("512 B", 512),
    ],
)
def test_memory_sizes_take_decimal_and_binary_units(text: str, size: int) -> None:
    assert memory_size(text) == size


@pytest.mark.parametrize("step_size", [0, -1, "0 MB", "100", "MB", "lots"])
def test_a_step_size_that_is_not_a_positive_size_is_refused(
    step_size: int | str,
) -> None:
    with pytest.raises(ValueError):
        entries_per_step(None, BRANCHES, step_size)
