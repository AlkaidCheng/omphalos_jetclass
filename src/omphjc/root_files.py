"""The content of a ROOT file that holds its events in one tree.

A tree is a table with one row for each event, and a row is called an entry.
A leaf is one column of the tree: a branch with no branch below it. An event
file is too large to keep in memory, so :class:`ROOTFile` holds the number of
entries, the name and the type of every leaf, and hashes of the values in a
sample of the entries.

A leaf holds either the same number of values in every entry or a list whose
length differs from entry to entry. A leaf of the first kind is hashed in
every entry. Such a leaf holds, for example, the number of objects in each
list of another leaf. A leaf of the second kind is hashed in the entry ranges
that :func:`sampled_ranges` gives.

Two files with the same entries have the same fingerprint. The time a file
was written, its compression and the sizes of the blocks that hold its values
do not count. A change is missed when it lies in the lists and reaches no
sampled entry.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, TypeVar

import awkward as ak
from uproot.interpretation.numerical import Numerical

from omphjc.data_files import DataFile
from omphjc.root_io import open_tree

_ROOTFileT = TypeVar("_ROOTFileT", bound="ROOTFile")

# The sampling of record version 1 (ROOTFile.record_version). omphjc chose
# these values. A fingerprint must be computed in the same way on every run,
# so a change to any of them needs the next record version.
RANGE_SHARE = 0.01
"""The share of the entries of the tree that each sampled range holds."""
N_RANDOM_RANGES = 2
"""The number of sampled ranges that are drawn between the first and the last."""
SAMPLE_SEED = 20261103
"""The number that the draw of the sampled ranges starts from."""

# The characters between the parts of the name of a leaf, as in
# Particle/Particle.PID.
_NAME_SEPARATOR_PATTERN = re.compile(r"[./]")

# The field with the status bits that ROOT keeps for every object
# (TObject::fBits,
# https://github.com/root-project/root/blob/v6-40-02/core/base/inc/TObject.h#L47).
# The bits say how ROOT handles the object in memory and whether a reference
# points to it (#L71-L92). After the bits of an object that a reference points
# to, ROOT writes two more bytes (TStreamerInfo::WriteBufferAux,
# https://github.com/root-project/root/blob/v6-40-02/io/io/src/TStreamerInfoWriteBuffer.cxx#L406-L421).
# uproot 5.7 reads the leaf as numbers of four bytes each and fails on it.
_STATUS_BITS_FIELD = "fBits"


@dataclass(frozen=True)
class SampledLeaf:
    """The type of one leaf and the hashes of its sampled entries.

    Parameters
    ----------
    type_name : str
        The type of the values of an entry, as uproot names it, such as
        ``float[]``.
    sha256_by_buffer : dict[str, str]
        The SHA-256 hashes, in hexadecimal, of the values in each hashed
        entry range.

        awkward keeps the values of a range in one or more arrays of numbers,
        called buffers. A leaf with a list in each entry has one buffer with
        the place where each list ends and one with the values.

        A key is the range and the name awkward gives the buffer, as in
        ``0-10:node1-data``. The bytes of a buffer are hashed in
        little-endian order.
    """

    type_name: str
    sha256_by_buffer: dict[str, str]


@dataclass(frozen=True)
class ROOTFile(DataFile):
    """The structure of the tree of a ROOT file and hashes of a sample of it.

    A subclass is one file format. It states :attr:`format_name` and
    :attr:`tree_name`, and it may state :attr:`excluded_fields`.

    Parameters
    ----------
    n_entries : int
        The number of entries of the tree.
    leaves : dict[str, SampledLeaf]
        Each leaf by its name. The name starts with the names of the branches
        above the leaf, as in ``Particle/Particle.PID``.

    Attributes
    ----------
    tree_name : str
        The name of the tree that holds the events.
    excluded_fields : frozenset[str]
        The fields that are left out of the content. A field is the last part
        of the name of a leaf, after the last ``.`` or ``/``, and it is left
        out on every branch.

        A format names the fields whose values differ between two runs that
        give the same events, such as the time a program took.

        The field ``fBits`` is left out in every format. It holds the status
        bits that ROOT keeps for each object, and they are no part of an
        event.
    """

    record_version: ClassVar[int] = 1
    tree_name: ClassVar[str]
    excluded_fields: ClassVar[frozenset[str]] = frozenset()

    n_entries: int
    leaves: dict[str, SampledLeaf]

    @classmethod
    def read(cls: type[_ROOTFileT], path: Path) -> _ROOTFileT:
        """Return the content of the ROOT file at `path`.

        Raises
        ------
        ValueError
            If the file has no tree :attr:`tree_name`.
        """
        excluded_fields = cls.excluded_fields | {_STATUS_BITS_FIELD}
        with open_tree(path, cls.tree_name) as tree:
            n_entries = int(tree.num_entries)
            branches = {
                name: branch
                for name, branch in tree.iteritems(
                    recursive=True, filter_branch=lambda branch: not branch.branches
                )
                if _NAME_SEPARATOR_PATTERN.split(name)[-1] not in excluded_fields
            }
            ranges = sampled_ranges(n_entries)
            leaves = {}
            for name, branch in branches.items():
                # uproot reads a leaf with the same number of values in every
                # entry through a subclass of Numerical (uproot 5.7.4,
                # https://github.com/scikit-hep/uproot5/blob/v5.7.4/src/uproot/interpretation/numerical.py#L35-L42).
                is_fixed_size = isinstance(branch.interpretation, Numerical)
                sha256_by_buffer = {}
                for start, stop in [(0, n_entries)] if is_fixed_size else ranges:
                    entries = ak.to_packed(
                        branch.array(entry_start=start, entry_stop=stop)
                    )
                    for key, buffer in ak.to_buffers(entries, byteorder="<")[2].items():
                        buffer_sha256 = hashlib.sha256(buffer.tobytes()).hexdigest()
                        sha256_by_buffer[f"{start}-{stop}:{key}"] = buffer_sha256
                leaves[name] = SampledLeaf(
                    type_name=branch.typename, sha256_by_buffer=sha256_by_buffer
                )
        return cls(n_entries=n_entries, leaves=leaves)

    def content_record(self) -> dict[str, Any]:
        """Return the number of entries, and the type and the hashes of each leaf."""
        return {
            "entries": self.n_entries,
            "leaves": {
                name: {"type": leaf.type_name, "sha256": leaf.sha256_by_buffer}
                for name, leaf in self.leaves.items()
            },
        }


def sampled_ranges(n_entries: int) -> list[tuple[int, int]]:
    """Return the entry ranges in which a leaf with a list in each entry is hashed.

    Each range holds :data:`RANGE_SHARE` of the `n_entries` entries of a tree,
    rounded up to a whole number of entries. One range starts at the first
    entry and one ends at the last entry. :data:`N_RANDOM_RANGES` more ranges
    lie between those two, and they may overlap each other.

    The start of each of these ranges comes from the SHA-256 hash of
    :data:`SAMPLE_SEED`, `n_entries` and the number of the range. Two trees
    with the same number of entries therefore have the same ranges.

    Returns
    -------
    list[tuple[int, int]]
        The first entry of each range and the entry after its last one, in
        rising order. A tree too short for four separate ranges gives one
        range with every entry.
    """
    width = max(1, math.ceil(n_entries * RANGE_SHARE))
    if n_entries < (2 + N_RANDOM_RANGES) * width:
        return [(0, n_entries)]
    starts = {0, n_entries - width}
    for number in range(N_RANDOM_RANGES):
        draw = hashlib.sha256(f"{SAMPLE_SEED}:{n_entries}:{number}".encode())
        starts.add(width + int(draw.hexdigest(), 16) % (n_entries - 3 * width + 1))
    return [(start, start + width) for start in sorted(starts)]
