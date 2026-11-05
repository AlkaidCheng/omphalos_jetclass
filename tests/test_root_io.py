import re
import zlib
from pathlib import Path
from typing import Any

import awkward as ak
import numpy as np
import pytest
import uproot
from delphes_records import write_delphes_file

from omphjc.root_io import (
    count_entries,
    entries_per_step,
    iterate_branches,
    open_tree,
    parse_memory_size,
    read_branches,
)

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


def test_a_tree_opens_with_the_branches_it_must_have(tree_path: Path) -> None:
    with open_tree(tree_path, "Delphes", BRANCHES) as tree:
        assert tree.num_entries == 100
    assert count_entries(tree_path, "Delphes", BRANCHES) == 100


def test_a_file_without_the_tree_is_refused(tree_path: Path) -> None:
    with pytest.raises(ValueError, match="has no tree 'Other'"):
        count_entries(tree_path, "Other")


@pytest.mark.parametrize(
    ("name", "classname"),
    [("Hist", "TH1D"), ("Ntuple", "ROOT::RNTuple"), ("Dir", "TDirectory")],
)
def test_an_object_other_than_a_ttree_is_refused(
    tmp_path: Path, name: str, classname: str
) -> None:
    path = tmp_path / "objects.root"
    with uproot.recreate(path) as file:
        file["Hist"] = np.histogram([1.0, 2.0], bins=2)
        file.mkrntuple("Ntuple", {"x": np.int32}).extend({"x": np.array([1], np.int32)})
        file.mkdir("Dir")
    with pytest.raises(
        ValueError, match=re.escape(f"holds {name!r} as a {classname}, not a TTree")
    ):
        count_entries(path, name)


def test_a_single_branch_name_is_refused_as_a_string(tree_path: Path) -> None:
    with pytest.raises(TypeError, match="sequence of names, not the string"):
        count_entries(tree_path, "Delphes", "Particle.PID")


def test_a_read_of_no_branches_is_refused(tree_path: Path) -> None:
    with pytest.raises(ValueError, match="no branches to read"):
        read_branches(tree_path, "Delphes", [])
    with pytest.raises(ValueError, match="no branches to read"):
        next(iterate_branches(tree_path, "Delphes", [], step_size=10))


def test_the_branches_a_tree_lacks_are_named(tree_path: Path) -> None:
    with pytest.raises(
        ValueError, match="'Delphes' of .* lacks Particle.Spin, Event.Run$"
    ):
        count_entries(
            tree_path, "Delphes", ["Particle.PID", "Particle.Spin", "Event.Run"]
        )


def test_branches_are_read_at_a_range_of_entries(tree_path: Path) -> None:
    whole = read_branches(tree_path, "Delphes", BRANCHES)
    part = read_branches(tree_path, "Delphes", BRANCHES, entry_start=10, entry_stop=25)
    assert whole.fields == BRANCHES and len(whole) == 100
    assert part.tolist() == whole[10:25].tolist()
    assert len(read_branches(tree_path, "Delphes", BRANCHES, entry_start=100)) == 0


@pytest.mark.parametrize(("start", "stop"), [(-1, None), (20, 10), (0, 101)])
def test_a_range_outside_the_tree_is_refused(
    tree_path: Path, start: int, stop: int | None
) -> None:
    with pytest.raises(
        ValueError, match="lie outside the 100 entries of tree 'Delphes'"
    ):
        read_branches(
            tree_path, "Delphes", BRANCHES, entry_start=start, entry_stop=stop
        )


@pytest.mark.parametrize("step_size", [1, 7, "1 kB", "1 GB"])
def test_the_steps_hold_the_entries_asked_and_follow_each_other(
    tree_path: Path, step_size: int | str
) -> None:
    with open_tree(tree_path, "Delphes") as tree:
        step = entries_per_step(tree, BRANCHES, step_size)
    steps = list(iterate_branches(tree_path, "Delphes", BRANCHES, step_size=step_size))
    lengths = [len(arrays) for _, arrays in steps]
    assert lengths == [step] * (100 // step) + ([100 % step] if 100 % step else [])
    assert [start for start, _ in steps] == np.cumsum([0, *lengths[:-1]]).tolist()
    joined = ak.concatenate([arrays for _, arrays in steps])
    assert joined.tolist() == read_branches(tree_path, "Delphes", BRANCHES).tolist()


def test_an_iteration_refuses_a_missing_branch_once_it_starts(
    tree_path: Path,
) -> None:
    steps = iterate_branches(tree_path, "Delphes", ["Particle.Spin"], step_size=10)
    with pytest.raises(ValueError, match="lacks Particle.Spin"):
        next(steps)


def test_a_memory_step_size_inflates_each_basket_once(
    tree_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    decompress = zlib.decompress

    def counting_decompress(*args: Any, **kwargs: Any) -> bytes:
        nonlocal calls
        calls += 1
        return decompress(*args, **kwargs)

    monkeypatch.setattr(zlib, "decompress", counting_decompress)
    read_branches(tree_path, "Delphes", BRANCHES)
    whole_tree_calls, calls = calls, 0
    list(iterate_branches(tree_path, "Delphes", BRANCHES, step_size="1 GB"))
    # 3 branches of 10 baskets each, besides the tree's own metadata.
    assert whole_tree_calls >= 30
    assert calls == whole_tree_calls


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
        ("1 GB", 10**9),
        ("1 MiB", 2**20),
        ("1 TiB", 2**40),
        ("2 tb", 2 * 10**12),
        ("512 B", 512),
        ("0.5 B", 1),
        ("4.03 kB", 4030),
        ("2.01 kB", 2010),
    ],
)
def test_memory_sizes_take_decimal_and_binary_units(text: str, size: int) -> None:
    assert parse_memory_size(text) == size


@pytest.mark.parametrize("step_size", [2.0, True, None])
def test_a_step_size_that_is_neither_an_entry_count_nor_text_is_refused(
    step_size: Any,
) -> None:
    with pytest.raises(TypeError, match="step_size must be an integer"):
        entries_per_step(None, BRANCHES, step_size)


@pytest.mark.parametrize(
    ("step_size", "message"),
    [
        (0, "must be positive"),
        (-1, "must be positive"),
        ("0 MB", "must be positive"),
        ("-1 MB", "must be positive"),
        ("100", "not a memory size"),
        ("MB", "not a memory size"),
        ("1 iB", "not a memory size"),
        ("lots", "not a memory size"),
    ],
)
def test_a_step_size_that_is_not_a_positive_size_is_refused(
    step_size: int | str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        entries_per_step(None, BRANCHES, step_size)
