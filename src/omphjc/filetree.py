"""Walks over directory trees that never follow symbolic links."""

import os
from pathlib import Path


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
