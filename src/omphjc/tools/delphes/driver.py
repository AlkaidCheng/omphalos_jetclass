"""Run ``DelphesROOT`` to simulate the detector on showered events in a ROOT file.

Each run has a working directory of its own::

    <workdir>/
      omphjc-stamp.json   stamp: the process and the sealed artifacts of its run
      delphes_card.tcl    the detector card, with the run's seed appended
      delphes.root        DelphesROOT's output
      simulate.log        DelphesROOT's output

``DelphesROOT`` takes three arguments in this order: the card, the output
file and the input file (``readers/DelphesROOT.cpp`` in Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/readers/DelphesROOT.cpp).

The input is a Delphes ROOT file such as the shower stage writes
(:mod:`omphjc.tools.pythia.driver`). The program reads the ``Particle`` and
``Event`` branches of the input. From them it fills Delphes's
``allParticles``, ``stableParticles`` and ``partons`` arrays, exactly as
``DelphesPythia8`` does from a Pythia event. It then applies the card's
modules to every event. The input is read where it is and is not copied.

The program opens the output with ROOT's ``CREATE`` mode, so an existing
output file is an error. It exits with status 1 when it cannot open a file
and with status 0 otherwise. A run is therefore judged by its exit status and
by the output it leaves.

The program copies the ``Event`` branch into the output. It does not copy the
``Weight`` branch; the program's source marks this as still to be done.

A working directory carries a stamp (:mod:`omphjc.stamps`) that names the
process. A run seals its artifacts when it ends, which records them in the
stamp. :class:`omphjc.workspace.Workspace` describes what a later run may
delete.
"""

from dataclasses import dataclass
from pathlib import Path

from omphjc.processes.catalogue import ProcessSpec
from omphjc.programs import ProgramError
from omphjc.safe_paths import normalize_path, require_file, require_unoccupied
from omphjc.tools.delphes.card import reference_card_text, with_random_seed
from omphjc.workspace import ProgramRun, ProgramWorkspace

# Delphes's program running a card on the generator record of a Delphes ROOT file.
_DELPHES_ROOT = "DelphesROOT"

_CARD_FILE = "delphes_card.tcl"
_OUTPUT_FILE = "delphes.root"
_LOG_FILE = "simulate.log"

# The purpose written in the stamp of a working directory.
_RUN_PURPOSE = "delphes-simulation"


class SimulationError(ProgramError):
    """``DelphesROOT`` failed, ran past its time limit or wrote nothing."""


@dataclass(frozen=True, kw_only=True)
class SimulationRun(ProgramRun):
    """The output of one ``DelphesROOT`` run.

    The log, the usage and the folder that holds what was set aside are
    fields of :class:`omphjc.workspace.ProgramRun`.

    Parameters
    ----------
    output_path : Path
        The Delphes ROOT file.
    card_path : Path
        The detector card that the run used.
    """

    card_path: Path


def detector_card_text(spec: ProcessSpec, card_path: Path | None = None) -> str:
    """Return the text of the detector card a simulation of `spec` runs.

    Parameters
    ----------
    spec : ProcessSpec
        The process. Its catalogue names the card to use by default. When it
        names none, the official JetClass card is used.
    card_path : Path or None, optional
        A card to use instead of the card of the process.

    Raises
    ------
    FileNotFoundError
        If `card_path` is given and is not a file.
    """
    if card_path is not None:
        require_file(card_path, what="Delphes card")
        return card_path.read_text(encoding="utf-8")
    if spec.delphes_card is None:
        return reference_card_text()
    return spec.delphes_card.read_text(encoding="utf-8")


def simulate_events(
    spec: ProcessSpec,
    *,
    events_path: Path,
    workdir: Path,
    seed: int | None,
    card_path: Path | None = None,
    timeout: float | None = None,
    overwrite: bool = False,
    log_dir: Path | None = None,
    delphes_root_path: Path | None = None,
) -> SimulationRun:
    """Simulate the detector on the events in `events_path` with ``DelphesROOT``.

    Parameters
    ----------
    spec : ProcessSpec
        The process the events belong to. Its catalogue names the detector
        card used by default.
    events_path : Path
        The showered events. This is a Delphes ROOT file that holds the
        generator record of every event in its ``Particle`` branch, as the
        shower writes it.
    workdir : Path
        Directory of the run. It is created when missing, and it must not
        hold a run of another process. Every call writes the card and the log
        in it anew.
    seed : int or None
        Delphes's seed, appended to the card. With ``None``, Delphes seeds
        itself from the clock.
    card_path : Path or None, optional
        The detector card to use instead of the card of the process.
    timeout : float or None, optional
        Seconds the run may take. ``None`` sets no limit. At the limit,
        ``DelphesROOT`` and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the output that an earlier run left in `workdir`.
        By default an existing output is an error, so a run never deletes
        results by accident.

        The output is replaced only after every other check has passed. It is
        deleted when the earlier run sealed it and nothing in it has changed
        since. Otherwise it is moved aside (see `SimulationRun.set_aside`).
    log_dir : Path or None, optional
        An existing directory to write the log in. By default the log is
        written in `workdir`, and a later run replaces it. A log written in
        another directory is not replaced.
    delphes_root_path : Path or None, optional
        Path of Delphes's ``DelphesROOT``. By default the program is looked
        up on PATH.

    Returns
    -------
    SimulationRun
        The output file, the card that the run used and the log.

    Raises
    ------
    ValueError
        If `timeout` is not positive, `workdir` is a filesystem root, or a
        file of an earlier run is a symbolic link.
    FileNotFoundError
        If `events_path` or `card_path` is not a file, or ``DelphesROOT`` cannot be
        found.
    FileExistsError
        If `workdir` already holds an output file and `overwrite` is false.
    StampError
        If `workdir` is in one of these states:

        - it is stamped for another purpose or process;
        - it holds artifacts of a run but carries no stamp;
        - it holds something other than a stamp where the stamp belongs.

        Nothing is changed in that case.
    SimulationError
        If ``DelphesROOT`` exits with an error, is still running at the time
        limit, or writes no output. The message ends with the last lines of
        the log.
    """
    require_file(events_path, what="Showered events")
    workspace = SimulationWorkspace(
        spec,
        workdir,
        delphes_root_path=delphes_root_path,
        timeout=timeout,
        log_dir=log_dir,
    )
    if not overwrite:
        require_unoccupied(workspace.output_path, what="Output file")
    # Read before anything is removed, so that a missing card fails at once
    # and leaves earlier results in place.
    card_text = detector_card_text(spec, card_path)
    if seed is not None:
        card_text = with_random_seed(card_text, seed)

    with workspace.sealed_run() as set_aside:
        workspace.write_card(card_text)
        workspace.run_simulation(events_path)

    if not workspace.output_path.is_file():
        raise workspace.make_error(
            f"DelphesROOT wrote no output file {workspace.output_path}"
        )
    return SimulationRun(
        output_path=workspace.output_path,
        card_path=workspace.card_path,
        log_path=workspace.log_path,
        usage=workspace.usage,
        set_aside=set_aside,
    )


class SimulationWorkspace(ProgramWorkspace):
    """The working directory of one process's ``DelphesROOT`` runs, and the steps of a run.

    :func:`simulate_events` drives a workspace from start to finish. A caller
    that needs the steps one at a time constructs a workspace and opens a
    ``with workspace.sealed_run():`` block. Inside the block it calls
    :meth:`write_card` and then :meth:`run_simulation`.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    workdir : Path
        The working directory. It is created when missing, and it must not
        be a filesystem root.
    delphes_root_path : Path or None, optional
        Path of Delphes's ``DelphesROOT``. By default the program is looked
        up on PATH.
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
        If `delphes_root_path` is not a file, or none is given and PATH has no
        ``DelphesROOT``.
    """

    purpose = _RUN_PURPOSE
    program = _DELPHES_ROOT
    description = f"Delphes's {_DELPHES_ROOT}"
    log_name = _LOG_FILE
    error_type = SimulationError

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        delphes_root_path: Path | None = None,
        timeout: float | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(
            spec.name,
            workdir,
            program_path=delphes_root_path,
            timeout=timeout,
            log_dir=log_dir,
        )

    @property
    def card_path(self) -> Path:
        """The detector card of the run."""
        return self.workdir / _CARD_FILE

    @property
    def output_path(self) -> Path:
        """The Delphes ROOT file the run writes."""
        return self.workdir / _OUTPUT_FILE

    @property
    def artifacts(self) -> list[str]:
        return [_CARD_FILE, _OUTPUT_FILE, *super().artifacts]

    def write_card(self, card_text: str) -> None:
        """Write the detector card the run uses."""
        self.card_path.write_text(card_text, encoding="utf-8")

    def run_simulation(self, events_path: Path) -> None:
        """Run ``DelphesROOT`` with the card in the directory on `events_path`.

        Raises
        ------
        SimulationError
            If ``DelphesROOT`` exits with a failing status or is still running
            at the deadline.
        """
        self.run(
            [self.program_path, _CARD_FILE, _OUTPUT_FILE, normalize_path(events_path)],
            failure_message="DelphesROOT failed",
        )
