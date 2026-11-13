"""Stamp the directories omphjc works in, so that later runs can recognise them.

A stamp is a small JSON file, ``omphjc-stamp.json``. It certifies that omphjc
works in a directory, and it states what for: a purpose, such as MadGraph
event generation, and details, such as the process.

A stamp also seals the artifacts that a procedure leaves in the directory. An
artifact is a file or folder that the procedure made. The seal of an artifact
is the latest status-change time (``ctime``) found in it when the procedure
finished.

Adding, removing or renaming anything in a folder moves the ``ctime`` of that
folder forward, and no ordinary tool can set it back. A later run therefore
reads the ``ctime`` of an artifact and of the folders in it. This tells the
run whether anything was added, removed or renamed since the seal, and no list
of files has to be kept.

Editing a file in place inside a folder changes the file alone, so the edit is
not detected. On Windows ``st_ctime`` is the creation time, so no change can
be seen there and no artifact counts as unchanged.

A later run clears the artifacts in this way:

- An artifact that was sealed and shows no such change is deleted.
- An artifact that the run cannot confirm as its own is moved into
  ``omphjc-set-aside/`` instead, with its contents. An example is an artifact
  left by a run that was killed before it could seal the directory.
- Nothing else in the directory is ever touched.

What was set aside stays until someone deletes it. :func:`set_aside_folders`
shows the folders with their sizes, and :func:`clear_set_aside_folders`
deletes them.

Stamps guard against mistakes, such as a mistyped path or a file that a user
left in the folder of a run. Anyone who can write to a directory can also edit
its stamp.
"""

import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omphjc import __version__
from omphjc.filetree import CHANGES_MOVE_CTIME, latest_change_ns, tree_size
from omphjc.safe_paths import inside, is_occupied, remove_inside

STAMP_FILE = "omphjc-stamp.json"
SET_ASIDE_DIR = "omphjc-set-aside"
_PRODUCER = "omphjc"
COMPACT_UTC_FORMAT = "%Y%m%dT%H%M%SZ"
"""A UTC time as it is written in a name, such as ``20261027T153012Z``."""
# A folder _set_aside makes: the creation time, then the suffix tempfile.mkdtemp adds.
_SET_ASIDE_FOLDER = re.compile(r"([0-9]{8}T[0-9]{6}Z)-[A-Za-z0-9_]+")


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
        The sealed artifacts. A key is the POSIX path of an artifact relative
        to the directory. A value is the latest ``ctime`` found in the
        artifact at sealing, in nanoseconds.
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
    """Seal the `artifacts` that exist in the stamped `directory`.

    The stamp then records these artifacts only. Any other artifact that the
    stamp recorded is dropped from it.

    Each artifact is a POSIX path relative to `directory` whose components
    are plain names (:func:`omphjc.safe_paths.require_plain_name`).

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
            name: latest_change_ns(path)
            for name in artifacts
            if is_occupied(path := _artifact_path(directory, name))
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
    unconfirmed: Iterable[str] = (),
) -> Path | None:
    """Clear the `artifacts` an earlier run left in `directory`, and nothing else.

    `directory` must carry the stamp for `purpose` and `details`. An artifact
    that was sealed and shows no change since the seal is deleted.

    Any other artifact that is present is moved, with its contents, into a new
    folder under ``omphjc-set-aside/`` in `directory`. This applies to an
    artifact that:

    - is unsealed, for example because the earlier run was killed before it
      could seal the directory;
    - changed since it was sealed;
    - is a symbolic link;
    - is named in `unconfirmed`.

    On Windows a change cannot be seen, so every artifact that is present is
    moved into this folder.

    Every check is made before anything is moved or deleted. The stamp drops
    the cleared artifacts from its record.

    Parameters
    ----------
    directory : Path
        The stamped directory.
    artifacts : iterable of str
        What a run makes in `directory`. Each artifact is a POSIX path
        relative to `directory` whose components are plain names
        (:func:`omphjc.safe_paths.require_plain_name`).
    purpose : str
        The purpose the stamp must record.
    details : Mapping[str, str] or None, optional
        Details the stamp must record.
    unconfirmed : iterable of str, optional
        Artifacts to set aside even when they are sealed and unchanged, for
        example because they lack a sign that the caller expects.

    Returns
    -------
    Path or None
        The folder that holds the artifacts set aside, or ``None`` when no
        artifact was set aside.

    Raises
    ------
    StampError
        If `directory` is in one of these states:

        - it holds an artifact but carries no stamp;
        - its stamp records another purpose or other details;
        - it holds something other than a stamp where the stamp belongs.

        Nothing is changed in that case.
    ValueError
        If an artifact is not a relative path of plain names.
    """
    present = {
        name: path
        for name in artifacts
        if is_occupied(path := _artifact_path(directory, name))
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
    unconfirmed_names = set(unconfirmed)
    confirmed = {
        name: path
        for name, path in present.items()
        if CHANGES_MOVE_CTIME
        and name not in unconfirmed_names
        and not path.is_symlink()
        and name in stamp.artifacts
        and latest_change_ns(path) <= stamp.artifacts[name]
    }
    to_set_aside = {
        name: path for name, path in present.items() if name not in confirmed
    }
    remove_inside(directory, confirmed.values())
    set_aside = _set_aside(directory, to_set_aside) if to_set_aside else None
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


@dataclass(frozen=True)
class SetAsideFolder:
    """A folder of artifacts a clearing moved aside.

    Parameters
    ----------
    path : Path
        The folder, under ``omphjc-set-aside/``.
    created : datetime
        When the artifacts were set aside, in UTC, read from the folder's name.
    """

    path: Path
    created: datetime

    def size(self) -> int:
        """Return the bytes held by the files in the folder, walking it once.

        Symbolic links are not followed. The walk reads every file's metadata,
        so callers that only need to know the folders exist skip it.
        """
        return tree_size(self.path)


def set_aside_folders(directory: Path) -> list[SetAsideFolder]:
    """Return the folders set aside in `directory`, oldest first.

    A folder counts only when its name has the form that
    :func:`clear_artifacts` gives. Anything else under ``omphjc-set-aside/``
    is left out.
    """
    set_aside_dir = directory / SET_ASIDE_DIR
    if set_aside_dir.is_symlink() or not set_aside_dir.is_dir():
        return []
    found = []
    with os.scandir(set_aside_dir) as entries:
        for entry in entries:
            match = _SET_ASIDE_FOLDER.fullmatch(entry.name)
            if match is None or not entry.is_dir(follow_symlinks=False):
                continue
            created = datetime.strptime(match.group(1), COMPACT_UTC_FORMAT)
            found.append(
                SetAsideFolder(
                    path=Path(entry.path), created=created.replace(tzinfo=timezone.utc)
                )
            )
    return sorted(found, key=lambda folder: folder.path.name)


def clear_set_aside_folders(directory: Path) -> list[SetAsideFolder]:
    """Delete the folders set aside in `directory` and return them.

    Only the folders that :func:`set_aside_folders` lists are deleted.
    ``omphjc-set-aside/`` itself is deleted once it is empty.

    Raises
    ------
    StampError
        If folders are set aside in `directory` while it has no stamp.
        Nothing is changed in that case.
    """
    folders = set_aside_folders(directory)
    if not folders:
        return []
    if read_stamp(directory) is None:
        raise StampError(
            f"{directory} holds {SET_ASIDE_DIR}/ but has no omphjc stamp; "
            "nothing is changed"
        )
    remove_inside(directory, [folder.path for folder in folders])
    set_aside_dir = directory / SET_ASIDE_DIR
    if not any(set_aside_dir.iterdir()):
        set_aside_dir.rmdir()
    return folders


def _set_aside(directory: Path, artifacts: Mapping[str, Path]) -> Path:
    """Move `artifacts` into a new folder under ``omphjc-set-aside/``; return it."""
    set_aside_dir = inside(directory, SET_ASIDE_DIR)
    set_aside_dir.mkdir(exist_ok=True)
    created = datetime.now(timezone.utc).strftime(COMPACT_UTC_FORMAT)
    folder = Path(tempfile.mkdtemp(dir=set_aside_dir, prefix=f"{created}-"))
    for name, path in artifacts.items():
        target_path = folder / name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.rename(path, target_path)
    return folder


def _artifact_path(directory: Path, name: str) -> Path:
    return inside(directory, *name.split("/"))


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
