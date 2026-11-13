"""Reading ROOT trees with uproot.

The module has these functions:

- :func:`open_tree` opens a tree after checking that it has the branches that
  a read takes.
- :func:`count_entries` counts the entries of a tree.
- :func:`read_branches` reads the entries of a tree.
- :func:`iterate_branches` iterates over the entries of a tree.

Every uproot read in omphjc passes an entry count as its step size, never a
memory size. uproot 5.7 turns a memory size into an entry count by inflating
every basket of the selected branches. It then inflates the baskets again to
read them (``basket_uncompressed_bytes``,
https://github.com/scikit-hep/uproot5/blob/v5.7.4/src/uproot/behaviors/TBranch.py#L2697-L2709).

:func:`entries_per_step` makes the same conversion without reading a basket.
It reads the uncompressed size that each branch records.
"""

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import awkward as ak
import uproot

from omphjc.numeric import require_number

# Memory sizes such as "100 MB" or "1 GiB", in the form uproot accepts
# (uproot._util.memory_size,
# https://github.com/scikit-hep/uproot5/blob/v5.7.4/src/uproot/_util.py) without
# its exponents and its units above tera, matched without regard to case. A sign
# is matched so that a negative size is refused as such.
_MEMORY_SIZE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*((?:[kmgt]i?)?b)\s*$", re.I
)
_UNIT_BYTES = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


@contextmanager
def open_tree(
    path: Path, tree_name: str, branch_names: Sequence[str] = ()
) -> Iterator[Any]:
    """Open tree `tree_name` of the ROOT file `path` until the context exits.

    Parameters
    ----------
    path : Path
        The ROOT file.
    tree_name : str
        The tree to open.
    branch_names : Sequence[str], optional
        Branches the tree must have.

    Yields
    ------
    uproot.TTree
        The tree.

    Raises
    ------
    TypeError
        If `branch_names` is a single string.
    ValueError
        If the file has no TTree `tree_name`, or the tree lacks one of
        `branch_names`.
    """
    if isinstance(branch_names, str):
        raise TypeError(
            f"branch_names must be a sequence of names, not the string {branch_names!r}"
        )
    with uproot.open(path) as file:
        if tree_name not in file:
            raise ValueError(f"{path} has no tree {tree_name!r}")
        tree = file[tree_name]
        if not isinstance(tree, uproot.TTree):
            raise ValueError(
                f"{path} holds {tree_name!r} as a {file.classname_of(tree_name)},"
                " not a TTree"
            )
        missing = [name for name in branch_names if name not in tree]
        if missing:
            raise ValueError(f"tree {tree_name!r} of {path} lacks {', '.join(missing)}")
        yield tree


def count_entries(path: Path, tree_name: str, branch_names: Sequence[str] = ()) -> int:
    """Return the entry count of tree `tree_name` in `path`, reading no basket.

    Parameters
    ----------
    path : Path
        The ROOT file.
    tree_name : str
        The tree to count.
    branch_names : Sequence[str], optional
        Branches the tree must have.

    Raises
    ------
    ValueError
        For the reasons that :func:`open_tree` gives.
    """
    with open_tree(path, tree_name, branch_names) as tree:
        return int(tree.num_entries)


def read_branches(
    path: Path,
    tree_name: str,
    branch_names: Sequence[str],
    *,
    entry_start: int = 0,
    entry_stop: int | None = None,
) -> ak.Array:
    """Return branches of tree `tree_name` at entries [entry_start, entry_stop).

    Parameters
    ----------
    path : Path
        The ROOT file.
    tree_name : str
        The tree to read.
    branch_names : Sequence[str]
        The branches to read.
    entry_start, entry_stop : int, int or None, optional
        The entries to read. ``None`` reads to the end of the tree.

    Returns
    -------
    ak.Array
        One record per entry, with a field per branch.

    Raises
    ------
    ValueError
        If `branch_names` is empty, if the range lies outside the entries of
        the tree, or for the reasons that :func:`open_tree` gives.
    """
    if not branch_names:
        raise ValueError("no branches to read")
    with open_tree(path, tree_name, branch_names) as tree:
        n_entries = int(tree.num_entries)
        stop = n_entries if entry_stop is None else entry_stop
        if not 0 <= entry_start <= stop <= n_entries:
            raise ValueError(
                f"entries [{entry_start}, {stop}) lie outside the {n_entries}"
                f" entries of tree {tree_name!r} in {path}"
            )
        return tree.arrays(list(branch_names), entry_start=entry_start, entry_stop=stop)


def iterate_branches(
    path: Path,
    tree_name: str,
    branch_names: Sequence[str],
    *,
    step_size: int | str,
) -> Iterator[tuple[int, ak.Array]]:
    """Yield branches of tree `tree_name` in steps of `step_size`.

    Parameters
    ----------
    path : Path
        The ROOT file.
    tree_name : str
        The tree to read.
    branch_names : Sequence[str]
        The branches to read.
    step_size : int or str
        Entries per step, or a memory size such as ``"100 MB"``.
        :func:`entries_per_step` takes the same values.

    Yields
    ------
    tuple[int, ak.Array]
        The first entry of a step and the arrays of the step. The arrays have
        the form that :func:`read_branches` returns.

    Raises
    ------
    ValueError
        If `branch_names` is empty, or for the reasons that :func:`open_tree`
        and :func:`entries_per_step` give. The error is raised once the
        iteration starts.
    """
    if not branch_names:
        raise ValueError("no branches to read")
    with open_tree(path, tree_name, branch_names) as tree:
        step = entries_per_step(tree, branch_names, step_size)
        for arrays, report in tree.iterate(
            list(branch_names), step_size=step, report=True
        ):
            yield report.tree_entry_start, arrays


def entries_per_step(
    tree: Any, branch_names: Sequence[str], step_size: int | str
) -> int:
    """Return `step_size` as a number of entries of `tree`.

    Parameters
    ----------
    tree : uproot.TTree
        The tree to read.
    branch_names : Sequence[str]
        The branches the read takes.
    step_size : int or str
        Entries per step, or a memory size such as ``"100 MB"``. A number of
        entries is returned unchanged. A memory size is converted with the
        uncompressed bytes that the branches record (``fTotBytes``), and no
        basket is read.

    Returns
    -------
    int
        Entries per step, at least 1.

    Raises
    ------
    TypeError
        If `step_size` is neither an integer nor a string.
    ValueError
        If `step_size` is not positive or is a string that is not a memory
        size.
    """
    if not isinstance(step_size, str):
        return require_number(step_size, what="step_size", kind=int, positive=True)
    step_bytes = parse_memory_size(step_size)
    n_entries = int(tree.num_entries)
    total_bytes = sum(int(tree[name].member("fTotBytes")) for name in branch_names)
    if n_entries == 0 or total_bytes == 0:
        return max(n_entries, 1)
    return max(1, step_bytes * n_entries // total_bytes)


def parse_memory_size(text: str) -> int:
    """Return the bytes of a memory size such as ``"100 MB"`` or ``"1 GiB"``.

    The size is rounded to whole bytes, and a positive size is at least 1 byte.

    Raises
    ------
    ValueError
        If `text` is not a memory size, or its number is not positive.
    """
    match = _MEMORY_SIZE.match(text)
    if match is None:
        raise ValueError(f"not a memory size such as '100 MB': {text!r}")
    number, unit = match.groups()
    if float(number) <= 0:
        raise ValueError(f"a memory size must be positive, got {text!r}")
    return max(1, round(float(number) * _UNIT_BYTES[unit.upper()]))
