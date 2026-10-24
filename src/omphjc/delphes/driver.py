"""Run ``DelphesROOT``: the Delphes simulation of showered events kept in a ROOT file.

Each run has a working directory of its own::

    <workdir>/
      omphjc-stamp.json   stamp: the process and the sealed artifacts of its run
      delphes_card.tcl    the detector card, with the run's seed prepended
      delphes.root        DelphesROOT's output
      simulate.log        DelphesROOT's output

``DelphesROOT`` takes the card, the output file and the input file, in that
order (``readers/DelphesROOT.cpp`` in Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/readers/DelphesROOT.cpp). It
reads the ``Particle`` and ``Event`` branches of the input, a Delphes ROOT
file such as the shower stage writes (:mod:`omphjc.pythia.driver`), fills
Delphes's ``allParticles``, ``stableParticles`` and ``partons`` arrays from
them exactly as ``DelphesPythia8`` does from a Pythia event, and runs the
card's modules on every event. It opens the output with ROOT's ``CREATE``
mode, so an existing output file is an error, and exits with status 1 when it
cannot open a file and 0 otherwise, so a run is judged by its exit status and
by the output it leaves. The ``Event`` branch is copied into the output; the
``Weight`` branch is not, which the program's source marks as still to be
done. The input is read where it is, not copied.

A working directory carries a stamp (:mod:`omphjc.stamps`) naming the process,
and a run seals its artifacts when it ends; :class:`omphjc.workspace.Workspace`
describes what a later run may delete.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.delphes.card import reference_card_text, with_random_seed
from omphjc.processes.catalogue import ProcessSpec
from omphjc.programs import ProgramError, ProgramUsage
from omphjc.safe_paths import normalize_path, occupied
from omphjc.workspace import Workspace

# Delphes's program running a card on the generator record of a Delphes ROOT file.
_DELPHES_ROOT = "DelphesROOT"

_CARD_FILE = "delphes_card.tcl"
_OUTPUT_FILE = "delphes.root"
_LOG_FILE = "simulate.log"

# The purpose written in the stamp of a working directory.
_RUN_PURPOSE = "delphes-simulation"


class SimulationError(ProgramError):
    """``DelphesROOT`` failed, ran past its time limit or wrote nothing."""


@dataclass(frozen=True)
class SimulationRun:
    """The output of one ``DelphesROOT`` run.

    Parameters
    ----------
    output : Path
        The Delphes ROOT file.
    card : Path
        The detector card as run.
    log_file : Path
        ``DelphesROOT``'s output for the run.
    usage : ProgramUsage
        Wall time, CPU time and peak memory of the ``DelphesROOT`` run.
    set_aside : Path or None
        Folder in the working directory holding what an earlier run left and
        this run could not confirm as its own, moved there rather than deleted;
        ``None`` when nothing was set aside.
    """

    output: Path
    card: Path
    log_file: Path
    usage: ProgramUsage
    set_aside: Path | None = None


def detector_card_text(spec: ProcessSpec, card: Path | None = None) -> str:
    """Return the text of the detector card a simulation of `spec` runs.

    Parameters
    ----------
    spec : ProcessSpec
        The process; its catalogue names the card to use by default.
    card : Path or None, optional
        A card to run instead of the process's.

    Raises
    ------
    FileNotFoundError
        If `card` is given and is not a file.
    """
    if card is not None:
        if not card.is_file():
            raise FileNotFoundError(f"Delphes card {card} not found")
        return card.read_text(encoding="utf-8")
    if spec.delphes_card is None:
        return reference_card_text()
    return spec.delphes_card.read_text(encoding="utf-8")


def simulate_events(
    spec: ProcessSpec,
    *,
    events_file: Path,
    workdir: Path,
    seed: int | None,
    card: Path | None = None,
    timeout: float | None = None,
    overwrite: bool = False,
    delphes_root: Path | None = None,
) -> SimulationRun:
    """Simulate the detector on the events in `events_file` with ``DelphesROOT``.

    Parameters
    ----------
    spec : ProcessSpec
        The process the events belong to; its catalogue names the detector
        card used by default.
    events_file : Path
        The showered events: a Delphes ROOT file holding the generator record
        of every event in its ``Particle`` branch, as the shower writes it.
    workdir : Path
        Directory of the run, created when missing; it must not hold a run of
        another process. Every call writes the card and the log in it anew.
    seed : int or None
        Delphes's seed, prepended to the card; ``None`` leaves Delphes to seed
        itself from the clock.
    card : Path or None, optional
        The detector card to run instead of the process's.
    timeout : float or None, optional
        Seconds the run may take; ``None`` sets no limit. At the limit,
        ``DelphesROOT`` and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the output of an earlier run in `workdir`. By
        default an existing output is an error, so that a run never deletes
        results by accident. It is replaced only after every other check has
        passed: deleted when the earlier run sealed it and nothing in it
        changed since, otherwise moved aside (see `SimulationRun.set_aside`).
    delphes_root : Path or None, optional
        Delphes's ``DelphesROOT``; by default the one on PATH.

    Returns
    -------
    SimulationRun
        The output file, the card as run and the log.

    Raises
    ------
    ValueError
        If `timeout` is not positive, `workdir` is a filesystem root, or a
        file of an earlier run is a symbolic link.
    FileNotFoundError
        If `events_file` or `card` is not a file, or ``DelphesROOT`` cannot be
        found.
    FileExistsError
        If `workdir` already holds an output file and `overwrite` is false.
    StampError
        If `workdir` is stamped for another purpose or process, holds what a
        run makes without carrying a stamp, or holds something other than a
        stamp in the stamp's place. Nothing is changed in that case.
    SimulationError
        If ``DelphesROOT`` exits with an error, is still running at the time
        limit, or writes no output; the message ends with the last lines of
        its log.
    """
    if not events_file.is_file():
        raise FileNotFoundError(f"Showered events {events_file} not found")
    workspace = SimulationWorkspace(
        spec, workdir, delphes_root=delphes_root, timeout=timeout
    )
    if occupied(workspace.output) and not overwrite:
        raise FileExistsError(
            f"Output file {workspace.output} already exists; pass overwrite=True "
            "to replace it"
        )
    # Read before anything is removed, so that a missing card fails at once
    # and leaves earlier results in place.
    card_text = detector_card_text(spec, card)
    if seed is not None:
        card_text = with_random_seed(card_text, seed)

    set_aside = workspace.prepare()
    try:
        workspace.write_card(card_text)
        workspace.run_simulation(events_file)
    finally:
        # Whatever the outcome, the stamp seals what this run made, so that a
        # later run can tell whether anyone changed it since.
        workspace.seal_artifacts()

    if not workspace.output.is_file():
        raise workspace.error(f"DelphesROOT wrote no output file {workspace.output}")
    return SimulationRun(
        output=workspace.output,
        card=workspace.card,
        log_file=workspace.log_file,
        usage=workspace.usage,
        set_aside=set_aside,
    )


class SimulationWorkspace(Workspace):
    """The working directory of one process's ``DelphesROOT`` runs, and the steps of a run.

    :func:`simulate_events` drives a workspace from start to finish; a caller
    that needs the steps one at a time constructs one and calls
    :meth:`prepare`, :meth:`write_card`, :meth:`run_simulation`, then
    :meth:`seal_artifacts` in a ``finally``.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    directory : Path
        The working directory, created when missing; not a filesystem root.
    delphes_root : Path or None, optional
        Delphes's ``DelphesROOT``; by default the one on PATH.
    timeout : float or None, optional
        Seconds the run may take from now; ``None`` sets no limit.

    Raises
    ------
    ValueError
        If `timeout` is not positive or `directory` is a filesystem root.
    FileNotFoundError
        If `delphes_root` is not a file, or none is given and PATH has no
        ``DelphesROOT``.
    """

    error_type: ClassVar[type[ProgramError]] = SimulationError

    def __init__(
        self,
        spec: ProcessSpec,
        directory: Path,
        *,
        delphes_root: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            directory,
            program=_DELPHES_ROOT,
            program_path=delphes_root,
            description=f"Delphes's {_DELPHES_ROOT}",
            purpose=_RUN_PURPOSE,
            details={"process": spec.name},
            log_name=_LOG_FILE,
            timeout=timeout,
        )
        self.spec = spec

    @property
    def card(self) -> Path:
        """The detector card of the run."""
        return self.directory / _CARD_FILE

    @property
    def output(self) -> Path:
        """The Delphes ROOT file the run writes."""
        return self.directory / _OUTPUT_FILE

    @property
    def artifacts(self) -> list[str]:
        return [_CARD_FILE, _OUTPUT_FILE, _LOG_FILE]

    def write_card(self, card_text: str) -> None:
        """Write the detector card the run uses."""
        self.card.write_text(card_text, encoding="utf-8")

    def run_simulation(self, events_file: Path) -> None:
        """Run ``DelphesROOT`` with the card in the directory on `events_file`.

        Raises
        ------
        SimulationError
            If ``DelphesROOT`` exits with a failing status or is still running
            at the deadline.
        """
        self.run(
            [self.program_path, _CARD_FILE, _OUTPUT_FILE, normalize_path(events_file)],
            failure="DelphesROOT failed",
        )
