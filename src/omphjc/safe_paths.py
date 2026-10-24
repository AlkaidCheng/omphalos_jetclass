"""Keep the files a run writes and deletes inside the directory they belong to.

Names that come from data, such as a catalogue's process and model names, are
screened before they become part of a path, paths are normalized before they
are compared, and a deletion names the directory it must stay inside. A
malformed name such as ``""``, ``".."`` or ``"/etc"`` is refused rather than
allowed to point a write or a deletion somewhere else.
"""

import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

# One path component that cannot be empty, "." or "..", hold a separator or
# whitespace, or start with "-" (read as an option) or "." (a hidden file).
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def require_plain_name(name: str, *, what: str = "Name") -> str:
    """Return `name` if it is safe as a single path component.

    A plain name consists of letters, digits, ``_``, ``.`` and ``-`` and starts
    with a letter, a digit or ``_``.

    Parameters
    ----------
    name : str
        The name to screen.
    what : str, optional
        What the name is, for the error message, for example
        ``"Process name"``.

    Raises
    ------
    ValueError
        If `name` is not a plain name.
    """
    if not _PLAIN_NAME.fullmatch(name):
        raise ValueError(
            f"{what} {name!r} must consist of letters, digits, '_', '.' and '-', "
            "and start with a letter, a digit or '_'"
        )
    return name


def normalize_path(path: str | os.PathLike[str]) -> Path:
    """Return `path` absolute, with ``~`` expanded and ``..`` and links resolved."""
    return Path(path).expanduser().resolve()


def working_directory(path: str | os.PathLike[str]) -> Path:
    """Return `path` normalized for use as the directory of a run.

    Raises
    ------
    ValueError
        If `path` is a filesystem root.
    """
    directory = normalize_path(path)
    if directory == Path(directory.anchor):
        raise ValueError(f"A run cannot use a filesystem root as its directory: {path}")
    return directory


def is_occupied(path: Path) -> bool:
    """Return whether something, a broken symbolic link included, is at `path`."""
    return path.exists() or path.is_symlink()


def inside(root_dir: Path, *names: str) -> Path:
    """Return `root_dir` joined with `names`, each a plain name.

    Raises
    ------
    ValueError
        If a name is not a plain name.
    """
    path = root_dir
    for name in names:
        path = path / require_plain_name(name, what="Path component")
    return path


def remove_inside(root_dir: Path, paths: Iterable[Path]) -> None:
    """Delete each of `paths`, a file or a directory tree, all inside `root_dir`.

    Every path is checked before any is removed, so a refused path leaves all
    of them in place. A path that does not exist is skipped. Directory trees
    are removed with :func:`shutil.rmtree`, which deletes the symbolic links
    inside a tree rather than following them.

    Parameters
    ----------
    root_dir : Path
        Directory the removals must stay inside; it is never removed itself.
    paths : iterable of Path
        Files or directories to delete.

    Raises
    ------
    ValueError
        If a path is a symbolic link, is `root_dir` itself or lies outside it.
    """
    resolved_root = normalize_path(root_dir)
    targets = []
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"Refusing to remove {path}: it is a symbolic link")
        if not path.exists():
            continue
        target = normalize_path(path)
        if target == resolved_root or not target.is_relative_to(resolved_root):
            raise ValueError(f"Refusing to remove {path}: it is not inside {root_dir}")
        targets.append(target)
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
