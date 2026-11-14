"""Run ``DelphesPythia8`` to shower one event file, without detector simulation.

Each run has a working directory of its own::

    <workdir>/
      omphjc-stamp.json    stamp: the process and the sealed artifacts of its run
      events.lhe           the input events, uncompressed
      pythia.cmnd          Pythia settings: the catalogue's, the matching block, the seed
      particles_card.tcl   the Delphes card that writes the generator record and simulates nothing
      particles.root       the showered events: the Particle, Event and Weight branches,
                           and EventLHEF and WeightLHEF from the LHE file
      shower.log           DelphesPythia8's output, Pythia's banner and statistics included

``DelphesPythia8`` combines Pythia 8 and Delphes in one program
(``readers/DelphesPythia8.cpp`` in Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/readers/DelphesPythia8.cpp).
It handles each event in three steps:

- Pythia reads the event from the LHE file and showers it;
- the program copies the event record into Delphes's ``allParticles`` array;
- the modules of the card process that array.

This module gives the program the card of
:func:`omphjc.tools.delphes.card.particles_card_text`. The only module of
that card is the TreeWriter. The program therefore showers the events, writes
the generator record and simulates nothing. The generator record is the
complete list of the generator particles of each event. ``DelphesROOT``
applies a detector card to that file afterwards.

The MLM matching veto is Pythia's own user hook
(``Pythia8Plugins/CombineMatchingInput.h``). The program installs the hook.
The hook is active when the command file turns ``JetMatching:merge`` on.

The program takes three arguments in this order: the card, the command file
and the output file. It opens the output with ROOT's ``CREATE`` mode, so an
existing output file is an error.

The event loop processes up to ``Main:numberOfEvents`` events. It stops early
at the end of the LHE file and exits with status 0. After
``Main:timesAllowErrors`` failed events it gives up, prints that the
generation was aborted prematurely, and also exits with status 0. A run is
therefore judged by its log, not by its exit status.

The program opens the LHE file as text to fill the ``EventLHEF`` branch. For
this reason the input is copied into the working directory uncompressed.

At the end the program prints Pythia's event statistics
(``ProcessLevel::statistics`` in Pythia's ``src/ProcessLevel.cc``). The
``sum`` line of the statistics gives the number of events read, selected and
accepted. An event that the matching veto rejects is read but not accepted.
Pythia's banner names the Pythia version (``Pythia::banner`` in
``src/Pythia.cc``).

A working directory carries a stamp (:mod:`omphjc.stamps`) that names the
process. A run seals its artifacts when it ends, which records them in the
stamp. :class:`omphjc.workspace.Workspace` describes what a later run may
delete.
"""

import gzip
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from omphjc.processes.catalogue import ProcessSpec, SettingValue
from omphjc.programs import ProgramError
from omphjc.safe_paths import require_file, require_unoccupied
from omphjc.tools.delphes.card import ParticlesCard, particles_card_text
from omphjc.tools.pythia.cmnd import PythiaCmnd
from omphjc.workspace import ProgramRun, ProgramWorkspace

# Delphes's program combining Pythia 8 and the detector simulation.
_DELPHES_PYTHIA8 = "DelphesPythia8"

_EVENTS_FILE = "events.lhe"
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
        Events that also passed the user hooks, which include the matching
        veto. These are the events written to the output.
    """

    pythia_version: str
    events_read: int
    events_selected: int
    events_accepted: int


@dataclass(frozen=True, kw_only=True)
class ShowerRun(ProgramRun):
    """The output of one ``DelphesPythia8`` run.

    The log, the usage and the folder that holds what was set aside are
    fields of :class:`omphjc.workspace.ProgramRun`.

    Parameters
    ----------
    output_path : Path
        The showered events. This is a Delphes ROOT file that holds the
        generator record of every event in its ``Particle`` branch.
    cmnd_path : Path
        The Pythia command file that the run used.
    card_path : Path
        The Delphes card that the run used. It is the card that writes the
        generator record.
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
        If the log holds no Pythia banner or no event statistics. This
        happens, for example, when the run did not finish.
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
    log_dir: Path | None = None,
    delphes_pythia8_path: Path | None = None,
) -> ShowerRun:
    """Shower the events in `lhe_path` with Pythia 8 through ``DelphesPythia8``.

    No detector is simulated.

    Parameters
    ----------
    spec : ProcessSpec
        The process the events belong to. Its Pythia settings and matching
        block come from the catalogue.
    lhe_path : Path
        The LHE file, gzipped or plain. It is copied into `workdir`, and
        decompressed when it is gzipped.
    workdir : Path
        Directory of the run. It is created when missing, and it must not
        hold a run of another process. Every call writes the inputs and the
        log in it anew.
    n_events : int
        Upper bound on the number of events showered. The run also stops at
        the end of the LHE file.
    seed : int or None
        Pythia's seed. With ``None``, Pythia seeds itself from the clock.
    overrides : Mapping[str, SettingValue] or None, optional
        Pythia settings applied over the settings from the catalogue.
    timeout : float or None, optional
        Seconds the run may take. ``None`` sets no limit. At the limit,
        ``DelphesPythia8`` and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the output that an earlier run left in `workdir`.
        By default an existing output is an error, so a run never deletes
        results by accident.

        The output is replaced only after every other check has passed. It is
        deleted when the earlier run sealed it and nothing in it has changed
        since. Otherwise it is moved aside (see `ShowerRun.set_aside`).
    log_dir : Path or None, optional
        An existing directory to write the log in. By default the log is
        written in `workdir`, and a later run replaces it. A log written in
        another directory is not replaced.
    delphes_pythia8_path : Path or None, optional
        Path of Delphes's ``DelphesPythia8``. By default the program is
        looked up on PATH.

    Returns
    -------
    ShowerRun
        The showered events, the inputs that the run used, the log and
        Pythia's statistics.

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
        If `workdir` is in one of these states:

        - it is stamped for another purpose or process;
        - it holds artifacts of a run but carries no stamp;
        - it holds something other than a stamp where the stamp belongs.

        Nothing is changed in that case.
    ShowerError
        If ``DelphesPythia8`` exits with an error, gives up after too many
        failed events, is still running at the time limit, or writes no
        output. The message ends with the last lines of the log.
    """
    require_file(lhe_path, what="Event file")
    workspace = ShowerWorkspace(
        spec,
        workdir,
        delphes_pythia8_path=delphes_pythia8_path,
        timeout=timeout,
        log_dir=log_dir,
    )
    if not overwrite:
        require_unoccupied(workspace.output_path, what="Output file")
    # Built before anything is removed, so that an invalid request fails at
    # once and leaves earlier results in place.
    cmnd = PythiaCmnd.from_process(
        spec,
        lhe_path=Path(_EVENTS_FILE),
        n_events=n_events,
        seed=seed,
        overrides=overrides,
    )

    with workspace.sealed_run() as set_aside:
        workspace.write_inputs(lhe_path, cmnd)
        workspace.run_shower()

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


class ShowerWorkspace(ProgramWorkspace):
    """The working directory of one process's shower runs, and the steps of a run.

    :func:`shower_events` drives a workspace from start to finish. A caller
    that needs the steps one at a time constructs a workspace and opens a
    ``with workspace.sealed_run():`` block. Inside the block it calls
    :meth:`write_inputs` and then :meth:`run_shower`.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    workdir : Path
        The working directory. It is created when missing, and it must not
        be a filesystem root.
    delphes_pythia8_path : Path or None, optional
        Path of Delphes's ``DelphesPythia8``. By default the program is
        looked up on PATH.
    timeout : float or None, optional
        Seconds the run may take, counted from the creation of the workspace.
        ``None`` sets no limit.
    log_dir : Path or None, optional
        See the `log_dir` parameter of
        :class:`~omphjc.workspace.ProgramWorkspace`.

    Raises
    ------
    ValueError
        If `timeout` is not positive or `workdir` is a filesystem root.
    FileNotFoundError
        If `delphes_pythia8_path` is not a file, or none is given and PATH has no
        ``DelphesPythia8``.
    """

    purpose = _RUN_PURPOSE
    program = _DELPHES_PYTHIA8
    description = f"Delphes's {_DELPHES_PYTHIA8}"
    log_name = _LOG_FILE
    error_type = ShowerError

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        delphes_pythia8_path: Path | None = None,
        timeout: float | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(
            spec.name,
            workdir,
            program_path=delphes_pythia8_path,
            timeout=timeout,
            log_dir=log_dir,
        )

    @property
    def events_path(self) -> Path:
        """The uncompressed event file the run reads."""
        return self.workdir / _EVENTS_FILE

    @property
    def cmnd_path(self) -> Path:
        """The Pythia command file of the run."""
        return self.workdir / PythiaCmnd.file_name

    @property
    def card_path(self) -> Path:
        """The Delphes card of the run, the one that writes the generator record."""
        return self.workdir / ParticlesCard.file_name

    @property
    def output_path(self) -> Path:
        """The ROOT file of showered events the run writes."""
        return self.workdir / _OUTPUT_FILE

    @property
    def artifacts(self) -> list[str]:
        return [
            _EVENTS_FILE,
            PythiaCmnd.file_name,
            ParticlesCard.file_name,
            _OUTPUT_FILE,
            *super().artifacts,
        ]

    def write_inputs(self, lhe_path: Path, cmnd: PythiaCmnd) -> None:
        """Decompress `lhe_path` into the directory and write the command file and the card."""
        _copy_events(lhe_path, self.events_path)
        self.cmnd_path.write_text(
            cmnd.to_text(title=self.process_name), encoding="utf-8"
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
            [
                self.program_path,
                ParticlesCard.file_name,
                PythiaCmnd.file_name,
                _OUTPUT_FILE,
            ],
            failure_message="DelphesPythia8 failed",
        )


def _copy_events(source: Path, target: Path) -> None:
    """Copy `source` to `target`, decompressing it when its name ends in ``.gz``."""
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as reader, target.open("wb") as writer:
            shutil.copyfileobj(reader, writer)
    else:
        shutil.copyfile(source, target)
