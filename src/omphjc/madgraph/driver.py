"""Run MadGraph5_aMC@NLO for one process.

Each run has a working directory of its own::

    <workdir>/
      omphjc-stamp.json       stamp: the process and the sealed artifacts of its run
      models/<model>/         copy of the model, when the catalogue includes it
      process.mg5             process script: import model, definitions, generate, output
      launch.mg5              launch script: switches and run-card values
      madgraph.log            MadGraph's output for both scripts
      <process>/              MadGraph's process directory
        Cards/madspin_card.dat                            when MadSpin runs
        Cards/me5_configuration.txt                       core count appended
        Events/run_01/unweighted_events.lhe.gz
        Events/run_01_decayed_1/unweighted_events.lhe.gz  after MadSpin

MadGraph caches an imported model as ``py3_model.pkl`` inside the model's
folder (``import_full_model`` in ``models/import_ufo.py``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/models/import_ufo.py#L454-L456),
so a run imports a copy and leaves the catalogue's folder untouched.

A command that fails inside a script stops MadGraph without a failing exit
status (``nice_error_handling`` in ``madgraph/interface/extended_cmd.py``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/madgraph/interface/extended_cmd.py#L1375-L1385),
so a run is judged by the files MadGraph writes.

MadGraph runs the jobs of a launch in parallel, by default on every CPU of the
machine (``configure_run_mode`` in ``madgraph/interface/common_run_interface.py``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/madgraph/interface/common_run_interface.py#L3993-L4002).
A run writes its core count into the process's ``Cards/me5_configuration.txt``,
the configuration file MadGraph reads last (``set_configuration``, same file,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/madgraph/interface/common_run_interface.py#L4345-L4382),
so a value in the user's or the installation's configuration does not
override it.

A working directory holds the runs of one process and carries a stamp
(:mod:`omphjc.stamps`) naming the process. When a run ends, short of a hard
kill, it seals its artifacts: the process directory, the model copy, the
scripts and the log. A later run of the process deletes an artifact only when
it was sealed and nothing in it changed since, and a process directory also
needs MadGraph's process card; any other artifact, such as one left by a run
killed before sealing, is moved into ``omphjc-set-aside/`` with its contents.
Nothing else in the directory is ever touched.
"""

import dataclasses
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.madgraph.banner import Banner
from omphjc.madgraph.cards import (
    launch_commands,
    madspin_card_text,
    proc_card_commands,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.programs import ProgramError, ProgramUsage, available_cores
from omphjc.safe_paths import inside, is_occupied
from omphjc.workspace import Workspace

# MadGraph's command-line program, bin/mg5_aMC of an installation.
_MG5_EXECUTABLE = "mg5_aMC"

_PROCESS_SCRIPT = "process.mg5"
_LAUNCH_SCRIPT = "launch.mg5"
_LOG_FILE = "madgraph.log"

# MadGraph's names for the event file of the first run and, after MadSpin, of
# its decayed copy ("%s_decayed_%i" in do_decay_events,
# madgraph/interface/common_run_interface.py, 3.8.0), and for the MadSpin card
# it reads from the process's Cards directory.
_EVENT_FILE = "unweighted_events.lhe.gz"
_FIRST_RUN = "run_01"
_DECAYED_RUN = "run_01_decayed_1"
_MADSPIN_CARD = "madspin_card.dat"
_ME5_CONFIGURATION = "me5_configuration.txt"

# The process card MadGraph writes into Cards/ on output: the evidence that a
# directory is a MadGraph process directory, which a rerun may replace.
_PROC_CARD = "proc_card_mg5.dat"

# Folder of the model copies in a working directory.
_MODELS_DIR = "models"

# Purpose of the stamp on a working directory (omphjc.stamps).
_RUN_PURPOSE = "madgraph-event-generation"

# MadGraph's run_mode for parallel jobs on the current machine (0 runs them one
# after another, 1 submits them to a batch system; set2_run_mode in
# madgraph/interface/madgraph_interface.py, 3.8.0).
_MULTICORE_RUN_MODE = 2


class MadGraphError(ProgramError):
    """MadGraph failed, ran past its time limit or did not write its output."""


@dataclass(frozen=True)
class MadGraphRun:
    """The output of one MadGraph run.

    Parameters
    ----------
    process_dir : Path
        MadGraph's process directory.
    events_path : Path
        The gzipped LHE file of the sample; after MadSpin, the decayed one.
    banner : Banner
        The banner of `events_path`: version, event count, cross section, run card.
    log_path : Path
        MadGraph's output for the run.
    usage : ProgramUsage
        Wall time, CPU time and peak memory of MadGraph's two scripts together.
    set_aside : Path or None
        Folder in the working directory holding what an earlier run left and
        this run could not confirm as its own, moved there rather than deleted;
        ``None`` when nothing was set aside.
    """

    process_dir: Path
    events_path: Path
    banner: Banner
    log_path: Path
    usage: ProgramUsage
    set_aside: Path | None = None


def generate_events(
    spec: ProcessSpec,
    *,
    workdir: Path,
    n_events: int,
    seed: int | None,
    n_cores: int | None = None,
    timeout: float | None = None,
    overwrite: bool = False,
    mg5_path: Path | None = None,
) -> MadGraphRun:
    """Generate parton-level events for `spec` with MadGraph.

    MadGraph writes the process directory from the process script, then
    generates the events from the launch script, with MadSpin when the
    process names a MadSpin card.

    Parameters
    ----------
    spec : ProcessSpec
        The process to generate.
    workdir : Path
        Directory of the runs of `spec`, created when missing. Its path must
        not contain whitespace, which MadGraph does not support, and it must
        not hold a run of another process. Every call writes the scripts, the
        log and the model copy in it anew.
    n_events : int
        Number of events to generate.
    seed : int or None
        MadGraph ``iseed``; ``None`` lets MadGraph choose one.
    n_cores : int or None, optional
        Number of cores MadGraph runs its jobs on; by default every CPU this
        process may use (:func:`omphjc.programs.available_cores`).
    timeout : float or None, optional
        Seconds the call may take; ``None`` sets no limit. At the limit,
        MadGraph and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the process directory of an earlier run in
        `workdir`. By default an existing one is an error, so that a run never
        deletes results by accident. It is replaced only after every other
        check has passed: deleted when the earlier run sealed it and nothing
        in it changed since, otherwise, as after a run killed before sealing,
        moved aside (see `MadGraphRun.set_aside`).
    mg5_path : Path or None, optional
        MadGraph's ``bin/mg5_aMC``; by default the one on PATH.

    Returns
    -------
    MadGraphRun
        The process directory, the event file, its banner and the log.

    Raises
    ------
    ValueError
        If `n_events`, `n_cores` or `timeout` is not positive, `workdir` is a
        filesystem root or its path contains whitespace, the model copy would
        overlap the catalogue's model folder, or a file of an earlier run is a
        symbolic link.
    FileExistsError
        If `workdir` already holds a process directory for `spec` and
        `overwrite` is false.
    StampError
        If `workdir` is stamped for another purpose or process, holds what a
        run makes without carrying a stamp, or holds something other than a
        stamp in the stamp's place. Nothing is changed in that case.
    FileNotFoundError
        If MadGraph cannot be found.
    MadGraphError
        If MadGraph exits with an error, is still running at the time limit,
        or does not write the process directory or the event file; the
        message ends with the last lines of its log.
    """
    if n_cores is None:
        n_cores = available_cores()
    if n_cores < 1:
        raise ValueError(f"n_cores must be positive, got {n_cores}")
    workspace = MadGraphWorkspace(spec, workdir, mg5_path=mg5_path, timeout=timeout)
    if is_occupied(workspace.process_dir) and not overwrite:
        raise FileExistsError(
            f"Process directory {workspace.process_dir} already exists; "
            "pass overwrite=True to replace it"
        )
    # Built before MadGraph starts or anything is removed, so that an invalid
    # request fails at once and leaves earlier results in place.
    launch = launch_commands(
        spec, process_dir=workspace.process_dir, n_events=n_events, seed=seed
    )

    set_aside = workspace.prepare()
    try:
        local_spec = workspace.copy_model()
        workspace.run_script(
            _PROCESS_SCRIPT,
            proc_card_commands(local_spec, output_dir=workspace.process_dir),
        )
        workspace.write_cards(n_cores)
        workspace.run_script(_LAUNCH_SCRIPT, launch)
    finally:
        # Whatever the outcome, the stamp seals what this run made, so that a
        # later run can tell whether anyone changed it since.
        workspace.seal_artifacts()

    events_path = workspace.events_path
    if not events_path.is_file():
        raise workspace.make_error(f"MadGraph wrote no event file {events_path}")
    return MadGraphRun(
        process_dir=workspace.process_dir,
        events_path=events_path,
        banner=Banner.read(events_path),
        log_path=workspace.log_path,
        usage=workspace.usage,
        set_aside=set_aside,
    )


class MadGraphWorkspace(Workspace):
    """The working directory of one process's runs, and the steps a run takes in it.

    :func:`generate_events` drives a workspace from start to finish; a caller
    that needs the steps one at a time constructs one and calls them in the
    same order: :meth:`prepare`, :meth:`copy_model`,
    :meth:`run_script` for the process script, :meth:`write_cards`,
    :meth:`run_script` for the launch script, then :meth:`seal_artifacts` in
    a ``finally``.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    workdir : Path
        The working directory, created when missing. Its path must not contain
        whitespace, which MadGraph does not support, and must not be a
        filesystem root.
    mg5_path : Path or None, optional
        MadGraph's ``bin/mg5_aMC``; by default the one on PATH.
    timeout : float or None, optional
        Seconds the run may take from now; ``None`` sets no limit.

    Attributes
    ----------
    spec : ProcessSpec
    workdir : Path
        The working directory, normalized.
    program_path : Path
        The ``mg5_aMC`` program file the run uses.
    deadline : float or None
        ``time.monotonic`` value at which a running script is stopped.

    Raises
    ------
    ValueError
        If `timeout` is not positive, `workdir` is a filesystem root or its
        path contains whitespace.
    FileNotFoundError
        If `mg5_path` is not a file, or none is given and PATH has no ``mg5_aMC``.
    """

    error_type: ClassVar[type[ProgramError]] = MadGraphError

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        mg5_path: Path | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            workdir,
            program=_MG5_EXECUTABLE,
            program_path=mg5_path,
            description=f"MadGraph's bin/{_MG5_EXECUTABLE}",
            purpose=_RUN_PURPOSE,
            details={"process": spec.name},
            log_name=_LOG_FILE,
            timeout=timeout,
        )
        if any(character.isspace() for character in str(self.workdir)):
            raise ValueError(
                f"MadGraph cannot run in a path with whitespace: {self.workdir}"
            )
        self.spec = spec

    @property
    def process_dir(self) -> Path:
        return inside(self.workdir, self.spec.name)

    @property
    def model_copy_dir(self) -> Path | None:
        """Where the catalogue's model is copied for the run; ``None`` without one."""
        if self.spec.model_dir is None:
            return None
        return inside(self.workdir, _MODELS_DIR, self.spec.model_base)

    @property
    def artifacts(self) -> list[str]:
        """What a run makes in the directory, as paths relative to it."""
        names = [self.spec.name, _PROCESS_SCRIPT, _LAUNCH_SCRIPT, _LOG_FILE]
        if self.spec.model_dir is not None:
            names.append(f"{_MODELS_DIR}/{self.spec.model_base}")
        return names

    @property
    def events_path(self) -> Path:
        """The event file MadGraph writes: the decayed sample after MadSpin."""
        run = _DECAYED_RUN if self.spec.uses_madspin else _FIRST_RUN
        return self.process_dir / "Events" / run / _EVENT_FILE

    def clear_earlier_run(self, *, unconfirmed: Iterable[str] = ()) -> Path | None:
        """Clear what an earlier run left in the directory, and nothing else.

        A process directory without MadGraph's process card is not what a run
        leaves, so it is moved aside however it was sealed, as is anything
        named in `unconfirmed`. Returns the folder holding what was moved aside,
        ``None`` when nothing was.

        Raises
        ------
        ValueError
            If the model copy would overlap the catalogue's model folder.
        """
        copy_dir = self.model_copy_dir
        if self.spec.model_dir is not None and copy_dir is not None:
            source_dir, target_dir = (
                self.spec.model_dir.resolve(),
                copy_dir.resolve(),
            )
            if target_dir.is_relative_to(source_dir) or source_dir.is_relative_to(
                target_dir
            ):
                raise ValueError(
                    f"The model copy {copy_dir} would overlap the model folder "
                    f"{self.spec.model_dir}"
                )
        unconfirmed = list(unconfirmed)
        process_dir = self.process_dir
        if process_dir.is_dir() and not (process_dir / "Cards" / _PROC_CARD).is_file():
            unconfirmed.append(self.spec.name)
        return super().clear_earlier_run(unconfirmed=unconfirmed)

    def copy_model(self) -> ProcessSpec:
        """Return the spec importing a copy of its model made in the directory."""
        copy_dir = self.model_copy_dir
        if self.spec.model_dir is None or copy_dir is None:
            return self.spec
        shutil.copytree(
            self.spec.model_dir,
            copy_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pkl"),
        )
        return dataclasses.replace(self.spec, model_dir=copy_dir)

    def run_script(self, name: str, commands: list[str]) -> None:
        """Write `commands` to the script `name` and run MadGraph on it.

        Raises
        ------
        MadGraphError
            If MadGraph exits with a failing status or is still running at the
            deadline.
        """
        script_path = self.workdir / name
        script_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
        self.run(
            [self.program_path, script_path],
            failure_message=f"MadGraph failed running {name}",
        )

    def write_cards(self, n_cores: int) -> None:
        """Append the core count to MadGraph's configuration; write the MadSpin card.

        Raises
        ------
        MadGraphError
            If MadGraph wrote no process directory.
        """
        cards_dir = self.process_dir / "Cards"
        if not cards_dir.is_dir():
            raise self.make_error(
                f"MadGraph wrote no process directory {self.process_dir}"
            )
        with (cards_dir / _ME5_CONFIGURATION).open("a", encoding="utf-8") as stream:
            stream.write(f"\nrun_mode = {_MULTICORE_RUN_MODE}\nnb_core = {n_cores}\n")
        if self.spec.uses_madspin:
            (cards_dir / _MADSPIN_CARD).write_text(
                madspin_card_text(self.spec), encoding="utf-8"
            )
