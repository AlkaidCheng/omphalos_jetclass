"""Stamp the directories omphjc works in, so that later runs can recognise them.

A stamp is a small JSON file, ``omphjc-stamp.json``, certifying that omphjc
works in a directory and for what: a purpose, such as MadGraph event
generation, and details such as the process. It also seals the artifacts a
procedure leaves there, the files and folders it made, each by the latest
status-change time (``ctime``) found in it when the procedure finished.

Adding, removing or renaming anything in a folder moves that folder's ``ctime``
forward, and no ordinary tool can set it back. A later run therefore reads the
``ctime`` of an artifact and of the folders in it, without keeping a list of
files, and learns whether anything was added, removed or renamed since the
seal. Editing a file in place inside a folder changes the file alone and is not
detected. An artifact that was sealed and shows no such change is deleted; one
the run cannot confirm as its own, such as one left by a run killed before sealing, is
moved into ``omphjc-set-aside/`` instead, with its contents. Nothing else in the
directory is ever touched. Stamps guard against mistakes, such as a mistyped
path or a user's file left in a run's folder; anyone who can write to a
directory can also edit its stamp.
"""

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omphjc import __version__
from omphjc.safe_paths import inside, occupied, remove_inside

STAMP_FILE = "omphjc-stamp.json"
SET_ASIDE_DIR = "omphjc-set-aside"
_PRODUCER = "omphjc"


class StampError(RuntimeError):
    """A directory lacks the stamp a procedure needs, or holds something else."""


@dataclass(frozen=True)
class Stamp:
    """What omphjc works on in a directory, and the artifacts it sealed there.

    Parameters
    ----------
    purpose : str
        What omphjc uses the directory for, for example
        ``"madgraph-event-generation"``.
    details : Mapping[str, str]
        Details of the purpose, for example ``{"process": "HToBB"}``.
    version : str
        Version of omphjc that stamped the directory.
    created : str
        When the directory was stamped, in ISO 8601 format (UTC).
    artifacts : Mapping[str, int]
        Each sealed artifact, by its POSIX path relative to the directory,
        with the latest ``ctime`` in it at sealing, in nanoseconds.
    """

    purpose: str
    details: Mapping[str, str]
    version: str
    created: str
    artifacts: Mapping[str, int]


def write_stamp(
    directory: Path, purpose: str, details: Mapping[str, str] | None = None
) -> Stamp:
    """Stamp `directory` as used by omphjc for `purpose`, with `details`.

    Raises
    ------
    FileExistsError
        If something is already at the stamp's place in `directory`.
    """
    stamp = Stamp(
        purpose=purpose,
        details=dict(details or {}),
        version=__version__,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        artifacts={},
    )
    # Exclusive creation fails on any existing path, a symbolic link included.
    with (directory / STAMP_FILE).open("x", encoding="utf-8") as stream:
        json.dump(_record(stamp), stream, indent=2)
        stream.write("\n")
    return stamp


def read_stamp(directory: Path) -> Stamp | None:
    """Return the stamp of `directory`, ``None`` when it has none.

    Raises
    ------
    StampError
        If the stamp's place holds something other than a stamp omphjc wrote.
    """
    path = directory / STAMP_FILE
    if path.is_symlink():
        raise StampError(f"{path} is not an omphjc stamp")
    if not path.exists():
        return None
    if not path.is_file():
        raise StampError(f"{path} is not an omphjc stamp")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StampError(f"{path} is not an omphjc stamp") from None
    if not _is_valid_record(record):
        raise StampError(f"{path} is not an omphjc stamp")
    return Stamp(
        purpose=record["purpose"],
        details=record["details"],
        version=record["omphjc_version"],
        created=record["created"],
        artifacts=record["artifacts"],
    )


def require_stamp(
    directory: Path, purpose: str, details: Mapping[str, str] | None = None
) -> Stamp:
    """Return the stamp of `directory`, which must record `purpose` and `details`.

    Raises
    ------
    StampError
        If `directory` has no stamp, its stamp records another purpose or
        other details, or something other than a stamp is in its place.
    """
    stamp = read_stamp(directory)
    if stamp is None:
        raise StampError(f"{directory} has no omphjc stamp")
    _check_stamp(stamp, directory, purpose, details or {})
    return stamp


def seal(directory: Path, artifacts: Iterable[str]) -> Stamp:
    """Seal the `artifacts` now in the stamped `directory`; forget the others.

    Each artifact is a POSIX path relative to `directory` whose components
    are plain names (:func:`omphjc.safe_paths.plain_name`).

    Raises
    ------
    StampError
        If `directory` has no stamp, or something else is in its place.
    """
    stamp = read_stamp(directory)
    if stamp is None:
        raise StampError(f"{directory} has no omphjc stamp")
    sealed = replace(
        stamp,
        artifacts={
            name: _latest_change(path)
            for name in artifacts
            if occupied(path := _artifact_path(directory, name))
        },
    )
    _replace_stamp(directory, sealed)
    return sealed


def clear_artifacts(
    directory: Path,
    artifacts: Iterable[str],
    purpose: str,
    *,
    details: Mapping[str, str] | None = None,
    doubtful: Iterable[str] = (),
) -> Path | None:
    """Clear the `artifacts` an earlier run left in `directory`, and nothing else.

    `directory` must carry the stamp for `purpose` and `details`. An artifact
    that was sealed and shows no change since is deleted. Any other artifact
    present, unsealed (as after a run killed before sealing), changed since
    sealing, a symbolic link, or named in `doubtful`, is moved with its
    contents into a new folder under ``omphjc-set-aside/`` in `directory`.
    Every check runs before anything is moved or deleted, and the stamp
    forgets the cleared artifacts.

    Parameters
    ----------
    directory : Path
        The stamped directory.
    artifacts : iterable of str
        What a run makes in `directory`: POSIX paths relative to it whose
        components are plain names (:func:`omphjc.safe_paths.plain_name`).
    purpose : str
        The purpose the stamp must record.
    details : Mapping[str, str] or None, optional
        Details the stamp must record.
    doubtful : iterable of str, optional
        Artifacts to set aside even when sealed and unchanged, for example
        because they lack a sign the caller expects.

    Returns
    -------
    Path or None
        The folder holding the artifacts set aside, ``None`` when none were.

    Raises
    ------
    StampError
        If an artifact is present while `directory` has no stamp, or the stamp
        records another purpose or other details; nothing is changed then.
    ValueError
        If an artifact is not a relative path of plain names.
    """
    present = {
        name: path
        for name in artifacts
        if occupied(path := _artifact_path(directory, name))
    }
    stamp = read_stamp(directory)
    if stamp is None:
        if present:
            raise StampError(
                f"{directory} holds {', '.join(present)} but has no omphjc stamp; "
                "nothing is changed"
            )
        return None
    _check_stamp(stamp, directory, purpose, details or {})
    doubts = set(doubtful)
    confirmed = {
        name: path
        for name, path in present.items()
        if name not in doubts
        and not path.is_symlink()
        and name in stamp.artifacts
        and _latest_change(path) <= stamp.artifacts[name]
    }
    unconfirmed = {
        name: path for name, path in present.items() if name not in confirmed
    }
    remove_inside(directory, confirmed.values())
    set_aside = _set_aside(directory, unconfirmed) if unconfirmed else None
    remaining = {
        name: change for name, change in stamp.artifacts.items() if name not in present
    }
    _replace_stamp(directory, replace(stamp, artifacts=remaining))
    return set_aside


def _check_stamp(
    stamp: Stamp, directory: Path, purpose: str, details: Mapping[str, str]
) -> None:
    if stamp.purpose != purpose:
        raise StampError(
            f"{directory} is used by omphjc for {stamp.purpose}, not {purpose}"
        )
    for key, value in details.items():
        if stamp.details.get(key) != value:
            raise StampError(
                f"{directory} is used by omphjc for {key} "
                f"{stamp.details.get(key)!r}, not {value!r}"
            )


def _set_aside(directory: Path, artifacts: Mapping[str, Path]) -> Path:
    """Move `artifacts` into a new folder under ``omphjc-set-aside/``; return it."""
    root = inside(directory, SET_ASIDE_DIR)
    root.mkdir(exist_ok=True)
    moment = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(dir=root, prefix=f"{moment}-"))
    for name, path in artifacts.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(path, target)
    return folder


def _artifact_path(directory: Path, name: str) -> Path:
    return inside(directory, *name.split("/"))


def _latest_change(path: Path) -> int:
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


def _replace_stamp(directory: Path, stamp: Stamp) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".stamp-")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(_record(stamp), stream, indent=2)
        stream.write("\n")
    os.replace(temporary, directory / STAMP_FILE)


def _record(stamp: Stamp) -> dict[str, Any]:
    return {
        "producer": _PRODUCER,
        "purpose": stamp.purpose,
        "details": dict(stamp.details),
        "omphjc_version": stamp.version,
        "created": stamp.created,
        "artifacts": dict(stamp.artifacts),
    }


def _is_valid_record(record: Any) -> bool:
    if not isinstance(record, dict) or record.get("producer") != _PRODUCER:
        return False
    if not all(
        isinstance(record.get(field), str)
        for field in ("purpose", "omphjc_version", "created")
    ):
        return False
    details, artifacts = record.get("details"), record.get("artifacts")
    if not isinstance(details, dict) or not isinstance(artifacts, dict):
        return False
    return all(isinstance(value, str) for value in details.values()) and all(
        isinstance(change, int) and not isinstance(change, bool)
        for change in artifacts.values()
    )
