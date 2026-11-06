"""Walks over directory trees that never follow symbolic links."""

import os
import sys
from pathlib import Path

# Whether adding, removing or renaming an entry moves its folder's st_ctime. On
# Windows st_ctime holds the creation time
# (https://docs.python.org/3/library/os.html#os.stat_result.st_ctime), and
# sys.platform is "win32" on every Windows build, 64-bit x86 and ARM included
# (https://github.com/python/cpython/blob/v3.12.0/PC/pyconfig.h#L321-L325).
CHANGES_MOVE_CTIME = sys.platform != "win32"


def latest_change_ns(path: Path) -> int:
    """Return the latest ``ctime`` of `path` and of every folder in it, in ns.

    Adding, removing or renaming an entry changes the folder holding it, so
    the folders alone show such changes; editing a file in place changes only
    the file, which is not read. Symbolic links are not followed.
    """
    latest = path.lstat().st_ctime_ns
    if path.is_symlink() or not path.is_dir():
        return latest
    folders = [os.fspath(path)]
    while folders:
        with os.scandir(folders.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    latest = max(latest, entry.stat(follow_symlinks=False).st_ctime_ns)
                    folders.append(entry.path)
    return latest


def tree_size(path: str | os.PathLike[str]) -> int:
    """Return the bytes held by the files under `path`; links are not followed."""
    total = 0
    folders = [os.fspath(path)]
    while folders:
        with os.scandir(folders.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry.path)
                else:
                    total += entry.stat(follow_symlinks=False).st_size
    return total
