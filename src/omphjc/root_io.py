"""Reading ROOT files with uproot: the step size of a read, as entries.

Every uproot read in omphjc passes an entry count as its step size, never a
memory size. uproot 5.7 turns a memory size into entries by inflating every
basket of the selected branches, and then inflates them again to read them
(``basket_uncompressed_bytes``,
https://github.com/scikit-hep/uproot5/blob/v5.7.4/src/uproot/behaviors/TBranch.py#L2697-L2709).
:func:`entries_per_step` reads the uncompressed size each branch records
instead, which needs no basket.
"""

import re
from collections.abc import Sequence
from typing import Any

# Memory sizes as uproot writes them, such as "100 MB" or "1 GiB": decimal and
# binary units, matched without regard to case (uproot._util.memory_size,
# https://github.com/scikit-hep/uproot5/blob/v5.7.4/src/uproot/_util.py).
_MEMORY_SIZE = re.compile(r"^\s*(\d+(?:\.\d*)?|\.\d+)\s*([kmgt]?i?b)\s*$", re.I)
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
        Entries per step, returned unchanged, or a memory size such as
        ``"100 MB"``, converted with the uncompressed bytes the branches record
        (``fTotBytes``) and reading no basket.

    Returns
    -------
    int
        Entries per step, at least 1.

    Raises
    ------
    ValueError
        If `step_size` is not positive or is a string that is not a memory
        size.
    """
    if isinstance(step_size, int):
        if step_size < 1:
            raise ValueError(f"step_size must be positive, got {step_size}")
        return step_size
    step_bytes = memory_size(step_size)
    n_entries = int(tree.num_entries)
    total_bytes = sum(int(tree[name].member("fTotBytes")) for name in branch_names)
    if n_entries == 0 or total_bytes == 0:
        return max(n_entries, 1)
    return max(1, step_bytes * n_entries // total_bytes)


def memory_size(text: str) -> int:
    """Return the bytes of a memory size such as ``"100 MB"`` or ``"1 GiB"``.

    Raises
    ------
    ValueError
        If `text` is not a positive memory size.
    """
    match = _MEMORY_SIZE.match(text)
    if match is None:
        raise ValueError(f"not a memory size such as '100 MB': {text!r}")
    number, unit = match.groups()
    size = int(float(number) * _UNIT_BYTES[unit.upper()])
    if size < 1:
        raise ValueError(f"a memory size must be positive, got {text!r}")
    return size
