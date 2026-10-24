"""Run ``DelphesPythia8`` as Pythia's event loop: the shower of one event file, no detector.

Each run has a working directory of its own::

    <workdir>/
      omphjc-stamp.json    stamp: the process and the sealed artifacts of its run
      events.lhe           the input events, uncompressed
      pythia.cmnd          Pythia settings: the catalogue's, the matching block, the seed
      particles_card.tcl   the Delphes card that writes the generator record and simulates nothing
      particles.root       the showered events: the Particle, Event and Weight branches
      shower.log           DelphesPythia8's output, Pythia's banner and statistics included

``DelphesPythia8`` combines Pythia 8 and Delphes in one program: Pythia reads
the LHE file and showers each event, the program copies the event record into
Delphes's ``allParticles`` array, and the modules of the card run on it
(``readers/DelphesPythia8.cpp`` in Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/readers/DelphesPythia8.cpp).
Run with the card of :func:`omphjc.delphes.card.particles_card_text`, whose
only module is the TreeWriter, it showers, writes the generator record and
simulates nothing; a detector card is run on that file afterwards with
``DelphesROOT``. The MLM matching veto is Pythia's own user hook
(``Pythia8Plugins/CombineMatchingInput.h``), installed by the program and
active when the command file turns ``JetMatching:merge`` on.

The program takes the card, the command file and the output file, in that
order, and opens the output with ROOT's ``CREATE`` mode, so an existing
output file is an error.
Its event loop runs up to ``Main:numberOfEvents`` events and stops early at
the end of the LHE file, with exit status 0; after ``Main:timesAllowErrors``
failed events it gives up, prints that the generation was aborted prematurely
and also exits with status 0, so a run is judged by its log, not by its exit
status. The LHE file is opened as text for the ``EventLHEF`` branch, which is
why the input is decompressed into the directory. At the end the program
prints Pythia's event statistics (``ProcessLevel::statistics`` in Pythia's
``src/ProcessLevel.cc``), whose ``sum`` line gives the events read, selected
and accepted; the events the matching veto rejects are read but not accepted.
Pythia's banner names its version (``Pythia::banner`` in ``src/Pythia.cc``).

A working directory carries a stamp (:mod:`omphjc.stamps`) naming the process,
and a run seals its artifacts when it ends; :class:`omphjc.workspace.Workspace`
describes what a later run may delete.
"""

import gzip
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.delphes.card import particles_card_text
from omphjc.processes.catalogue import ProcessSpec, SettingValue
from omphjc.programs import ProgramError
from omphjc.pythia.cmnd import format_cmnd, shower_settings
from omphjc.safe_paths import require_file, require_unoccupied
from omphjc.workspace import ProgramRun, Workspace

# Delphes's program combining Pythia 8 and the detector simulation.
_DELPHES_PYTHIA8 = "DelphesPythia8"

_EVENTS_FILE = "events.lhe"
_CMND_FILE = "pythia.cmnd"
_CARD_FILE = "particles_card.tcl"
_OUTPUT_FILE = "particles.root"
_LOG_FILE = "shower.log"

# The purpose written in the stamp of a working directory.
_RUN_PURPOSE = "pythia-shower"

# What DelphesPythia8 prints when Main:timesAllowErrors failed events end the run.
_ABORTED = "Event generation aborted prematurely"
_PYTHIA_VERSION = re.compile(r"This is PYTHIA version\s+(\d+\.\d+)")
# The "sum" line of Pythia's event statistics: tried, selected, accepted.
_STATISTICS_SUM = re.compile(
    r"^\s*\|\s*sum\s*\|\s*(\d+)\s+(\d+)\s+(\d+)\s*\|", re.MULTILINE
)


class ShowerError(ProgramError):
    """``DelphesPythia8`` failed, gave up, ran past its time limit or wrote nothing."""


@dataclass(frozen=True)
class ShowerStatistics:
    """What Pythia reports at the end of a run.

    Parameters
    ----------
    pythia_version : str
        Pythia's version, from its banner.
    events_read : int
        Events read from the LHE file (Pythia's "tried").
    events_selected : int
        Events that passed Pythia's own selection.
    events_accepted : int
        Events that also passed the user hooks, the matching veto among them;
        the events written to the output.
    """

    pythia_version: str
    events_read: int
    events_selected: int
    events_accepted: int


@dataclass(frozen=True, kw_only=True)
class ShowerRun(ProgramRun):
    """The output of one ``DelphesPythia8`` run.

    The log, the usage and the folder set aside are
    :class:`omphjc.workspace.ProgramRun`'s.

    Parameters
    ----------
    output_path : Path
        The showered events: a Delphes ROOT file holding the generator record
        of every event in its ``Particle`` branch.
    cmnd_path : Path
        The Pythia command file as run.
    card_path : Path
        The Delphes card as run, the one that writes the generator record.
    statistics : ShowerStatistics
        Pythia's version and event counts, read from the log.
    """

    cmnd_path: Path
    card_path: Path
    statistics: ShowerStatistics


def parse_statistics(log_text: str) -> ShowerStatistics:
    """Return Pythia's version and event counts from the text of a run's log.

    Raises
    ------
    ValueError
        If the log holds no Pythia banner or no event statistics, as after a
        run that did not finish.
    """
    version = _PYTHIA_VERSION.search(log_text)
    if version is None:
        raise ValueError("The log holds no Pythia banner")
    counts = _STATISTICS_SUM.search(log_text)
    if counts is None:
        raise ValueError("The log holds no Pythia event statistics")
    return ShowerStatistics(
        pythia_version=version.group(1),
        events_read=int(counts.group(1)),
        events_selected=int(counts.group(2)),
        events_accepted=int(counts.group(3)),
    )


def shower_events(
    spec: ProcessSpec,
    *,
    lhe_path: Path,
    workdir: Path,
    n_events: int,
    seed: int | None,
    overrides: Mapping[str, SettingValue] | None = None,
    timeout: float | None = None,
    overwrite: bool = False,
    delphes_pythia8_path: Path | None = None,
) -> ShowerRun:
    """Shower the events in `lhe_path` with Pythia 8 through ``DelphesPythia8``, simulating nothing.

    Parameters
    ----------
    spec : ProcessSpec
        The process the events belong to; its Pythia settings and matching
        block come from the catalogue.
    lhe_path : Path
        The LHE file, gzipped or plain; it is decompressed into `workdir`.
    workdir : Path
        Directory of the run, created when missing; it must not hold a run of
        another process. Every call writes the inputs and the log in it anew.
    n_events : int
        Upper bound on the events showered; the run also stops at the end of
        the LHE file.
    seed : int or None
        Pythia's seed; ``None`` leaves Pythia to seed itself from the clock.
    overrides : Mapping[str, SettingValue] or None, optional
        Pythia settings applied over the catalogue's.
    timeout : float or None, optional
        Seconds the run may take; ``None`` sets no limit. At the limit,
        ``DelphesPythia8`` and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the output of an earlier run in `workdir`. By
        default an existing output is an error, so that a run never deletes
        results by accident. It is replaced only after every other check has
        passed: deleted when the earlier run sealed it and nothing in it
        changed since, otherwise moved aside (see `ShowerRun.set_aside`).
    delphes_pythia8_path : Path or None, optional
        Delphes's ``DelphesPythia8``; by default the one on PATH.

    Returns
    -------
    ShowerRun
        The showered events, the inputs as run, the log and Pythia's statistics.

    Raises
    ------
    ValueError
        If `n_events` or `timeout` is not positive, `seed` is outside Pythia's
        range, `workdir` is a filesystem root, or a file of an earlier run is a
        symbolic link.
    FileNotFoundError
        If `lhe_path` is not a file or ``DelphesPythia8`` cannot be found.
    FileExistsError
        If `workdir` already holds an output file and `overwrite` is false.
    StampError
        If `workdir` is stamped for another purpose or process, holds what a
        run makes without carrying a stamp, or holds something other than a
        stamp in the stamp's place. Nothing is changed in that case.
    ShowerError
        If ``DelphesPythia8`` exits with an error, gives up after too many
        failed events, is still running at the time limit, or writes no
        output; the message ends with the last lines of its log.
    """
    require_file(lhe_path, what="Event file")
    workspace = ShowerWorkspace(
        spec, workdir, delphes_pythia8_path=delphes_pythia8_path, timeout=timeout
    )
    if not overwrite:
        require_unoccupied(workspace.output_path, what="Output file")
    # Built before anything is removed, so that an invalid request fails at
    # once and leaves earlier results in place.
    settings = shower_settings(
        spec,
        lhe_path=Path(_EVENTS_FILE),
        n_events=n_events,
        seed=seed,
        overrides=overrides,
    )

    set_aside = workspace.prepare()
    try:
        workspace.write_inputs(lhe_path, settings)
        workspace.run_shower()
    finally:
        # Whatever the outcome, the stamp seals what this run made, so that a
        # later run can tell whether anyone changed it since.
        workspace.seal_artifacts()

    log_text = workspace.log_path.read_text(encoding="utf-8", errors="replace")
    if _ABORTED in log_text:
        raise workspace.make_error(
            "DelphesPythia8 gave up after too many failed events (Main:timesAllowErrors)"
        )
    if not workspace.output_path.is_file():
        raise workspace.make_error(
            f"DelphesPythia8 wrote no output file {workspace.output_path}"
        )
    try:
        statistics = parse_statistics(log_text)
    except ValueError as error:
        raise workspace.make_error(f"DelphesPythia8 did not finish: {error}") from None
    return ShowerRun(
        output_path=workspace.output_path,
        cmnd_path=workspace.cmnd_path,
        card_path=workspace.card_path,
        log_path=workspace.log_path,
        statistics=statistics,
        usage=workspace.usage,
        set_aside=set_aside,
    )


class ShowerWorkspace(Workspace):
    """The working directory of one process's shower runs, and the steps of a run.

    :func:`shower_events` drives a workspace from start to finish; a caller
    that needs the steps one at a time constructs one and calls
    :meth:`prepare`, :meth:`write_inputs`, :meth:`run_shower`, then
    :meth:`seal_artifacts` in a ``finally``.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    workdir : Path
        The working directory, created when missing; not a filesystem root.
    delphes_pythia8_path : Path or None, optional
        Delphes's ``DelphesPythia8``; by default the one on PATH.
    timeout : float or None, optional
        Seconds the run may take from now; ``None`` sets no limit.

    Raises
    ------
    ValueError
        If `timeout` is not positive or `workdir` is a filesystem root.
    FileNotFoundError
        If `delphes_pythia8_path` is not a file, or none is given and PATH has no
        ``DelphesPythia8``.
    """

    error_type: ClassVar[type[ProgramError]] = ShowerError

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        delphes_pythia8_path: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            workdir,
            program=_DELPHES_PYTHIA8,
            program_path=delphes_pythia8_path,
            description=f"Delphes's {_DELPHES_PYTHIA8}",
            purpose=_RUN_PURPOSE,
            details={"process": spec.name},
            log_name=_LOG_FILE,
            timeout=timeout,
        )
        self.spec = spec

    @property
    def events_path(self) -> Path:
        """The uncompressed event file the run reads."""
        return self.workdir / _EVENTS_FILE

    @property
    def cmnd_path(self) -> Path:
        """The Pythia command file of the run."""
        return self.workdir / _CMND_FILE

    @property
    def card_path(self) -> Path:
        """The Delphes card of the run, the one that writes the generator record."""
        return self.workdir / _CARD_FILE

    @property
    def output_path(self) -> Path:
        """The ROOT file of showered events the run writes."""
        return self.workdir / _OUTPUT_FILE

    @property
    def artifacts(self) -> list[str]:
        return [_EVENTS_FILE, _CMND_FILE, _CARD_FILE, _OUTPUT_FILE, _LOG_FILE]

    def write_inputs(self, lhe_path: Path, settings: Mapping[str, str]) -> None:
        """Decompress `lhe_path` into the directory and write the command file and the card."""
        _copy_events(lhe_path, self.events_path)
        self.cmnd_path.write_text(
            format_cmnd(settings, title=self.spec.name), encoding="utf-8"
        )
        self.card_path.write_text(particles_card_text(), encoding="utf-8")

    def run_shower(self) -> None:
        """Run ``DelphesPythia8`` on the card and command file in the directory.

        Raises
        ------
        ShowerError
            If ``DelphesPythia8`` exits with a failing status or is still
            running at the deadline.
        """
        self.run(
            [self.program_path, _CARD_FILE, _CMND_FILE, _OUTPUT_FILE],
            failure_message="DelphesPythia8 failed",
        )


def _copy_events(source: Path, target: Path) -> None:
    """Copy `source` to `target`, decompressing it when its name ends in ``.gz``."""
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as reader, target.open("wb") as writer:
            shutil.copyfileobj(reader, writer)
    else:
        shutil.copyfile(source, target)
