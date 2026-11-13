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
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/models/import_ufo.py#L454-L456).
A run therefore imports a copy of the model and leaves the catalogue's folder
untouched.

A command that fails inside a script stops MadGraph without a failing exit
status (``nice_error_handling`` in ``madgraph/interface/extended_cmd.py``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/extended_cmd.py#L1375-L1385).
A run is therefore judged by the files MadGraph writes.

MadGraph runs the jobs of a launch in parallel, by default on every CPU of the
machine (``configure_run_mode`` in ``madgraph/interface/common_run_interface.py``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/common_run_interface.py#L3993-L4002).

A run writes its core count into the process's ``Cards/me5_configuration.txt``.
MadGraph reads this configuration file last (``set_configuration``, same file,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/common_run_interface.py#L4345-L4382).
A value in the user's or the installation's configuration therefore does not
override the core count.

A run sets two MadGraph settings to its seed: ``iseed`` and ``python_seed``,
the seed of MadGraph's Python generator. In its default spin mode, MadSpin
draws its own seed from that generator (``run_onshell``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/MadSpin/interface_madspin.py#L3283-L3297).

MadGraph resets ``iseed`` to 0 in the kept ``Cards/run_card.dat``
(``reset_iseed_in_run_card``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/common_run_interface.py#L5367-L5380).
The run card in the banner of the event file holds the seed MadGraph used.

MadSpin splits the events into one shard per core and seeds each shard
separately (``_split_production``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/MadSpin/interface_madspin.py#L6216-L6231).
A sample with MadSpin is therefore reproduced only on the same number of
cores.

MadGraph unweights the events in new Python processes when a run has many
channel directories (``do_combine_events``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/madevent_interface.py#L3908-L3990).
These processes take their random numbers from the operating system, not from
the seed. The threshold is ``max(80, ulimit -n - 40)`` directories, or 2500
when ``ulimit -n`` is unlimited.

A run with a seed raises ``ulimit -n`` to the hard limit while MadGraph is
active (:class:`omphjc.programs.RaisedOpenFileLimit`). Only a run with at
least the raised limit minus 40 channel directories is then not reproducible.

A working directory holds the runs of one process. It carries a stamp
(:mod:`omphjc.stamps`) that names the process.

A run seals its artifacts when it ends. The stamp then records them. Only a
hard kill ends a run before it seals them. The artifacts are:

- the process directory,
- the model copy,
- the scripts,
- the log.

A later run of the process deletes an artifact only when the artifact was
sealed and nothing in it has changed since. A process directory must also hold
MadGraph's process card to be deleted. Every other artifact is moved into
``omphjc-set-aside/`` with its contents. This happens, for example, to an
artifact left by a run that was killed before it could seal its artifacts.

A run touches nothing else in the directory.
"""

import dataclasses
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from omphjc.processes.catalogue import ProcessSpec
from omphjc.programs import ProgramError, RaisedOpenFileLimit, available_cores
from omphjc.safe_paths import inside, require_unoccupied
from omphjc.tools.madgraph.banner import Banner
from omphjc.tools.madgraph.cards import (
    launch_commands,
    madspin_card_text,
    proc_card_commands,
)
from omphjc.workspace import ProgramRun, ProgramWorkspace

# MadGraph's command-line program, bin/mg5_aMC of an installation.
_MG5_EXECUTABLE = "mg5_aMC"

_PROCESS_SCRIPT = "process.mg5"
_LAUNCH_SCRIPT = "launch.mg5"
_LOG_FILE = "madgraph.log"

# MadGraph's names for the event file of the first run and, after MadSpin, of
# its decayed copy ("%s_decayed_%i" in do_decay_events,
# madgraph/interface/common_run_interface.py, 3.8.1), and for the MadSpin card
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
# madgraph/interface/madgraph_interface.py, 3.8.1).
_MULTICORE_RUN_MODE = 2


class MadGraphError(ProgramError):
    """MadGraph failed, ran past its time limit or did not write its output."""


@dataclass(frozen=True, kw_only=True)
class MadGraphRun(ProgramRun):
    """The output of one MadGraph run.

    The log, the usage and the folder that holds what was set aside are
    fields of :class:`omphjc.workspace.ProgramRun`.

    Parameters
    ----------
    process_dir : Path
        MadGraph's process directory.
    output_path : Path
        The gzipped LHE file of the sample. After MadSpin, it is the file of
        the decayed events.
    banner : Banner
        The banner of `output_path`. It holds the version, the event count,
        the cross section and the run card.
    n_cores : int
        Number of cores MadGraph ran its jobs on.
    """

    process_dir: Path
    banner: Banner
    n_cores: int


def generate_events(
    spec: ProcessSpec,
    *,
    workdir: Path,
    n_events: int,
    seed: int | None,
    n_cores: int | None = None,
    timeout: float | None = None,
    overwrite: bool = False,
    log_dir: Path | None = None,
    mg5_path: Path | None = None,
) -> MadGraphRun:
    """Generate parton-level events for `spec` with MadGraph.

    MadGraph first writes the process directory from the process script. It
    then generates the events from the launch script. The launch uses MadSpin
    when the process names a MadSpin card.

    Parameters
    ----------
    spec : ProcessSpec
        The process to generate.
    workdir : Path
        Directory of the runs of `spec`, created when missing. Its path must
        not contain whitespace, because MadGraph does not support it. The
        directory must not hold a run of another process. Every call writes
        the scripts, the log and the model copy in it anew.
    n_events : int
        Number of events to generate.
    seed : int or None
        The value of MadGraph's ``iseed`` and ``python_seed``. With ``None``,
        MadGraph chooses ``iseed`` and the Python generator is seeded from the
        system.
    n_cores : int or None, optional
        Number of cores MadGraph runs its jobs on. The default is every CPU
        that the current Python process may use
        (:func:`omphjc.programs.available_cores`).
    timeout : float or None, optional
        Seconds the call may take. ``None`` sets no limit. At the limit,
        MadGraph and every process it started are stopped.
    overwrite : bool, optional
        Whether to replace the process directory that an earlier run left in
        `workdir`. By default an existing process directory is an error, so a
        run never deletes results by accident.

        The directory is replaced only after every other check has passed. It
        is deleted when the earlier run sealed it and nothing in it has changed
        since. Otherwise it is moved aside (see `MadGraphRun.set_aside`); this
        happens, for example, when the earlier run was killed before it could
        seal the directory.
    log_dir : Path or None, optional
        An existing directory to write the log in. By default the log is
        written in `workdir`, and a later run replaces it. A log written in
        another directory is not replaced.
    mg5_path : Path or None, optional
        Path of MadGraph's ``bin/mg5_aMC``. By default the program is looked
        up on PATH.

    Returns
    -------
    MadGraphRun
        The process directory, the event file, its banner, the core count and
        the log.

    Raises
    ------
    ValueError
        If one of these conditions holds:

        - `n_events`, `n_cores` or `timeout` is not positive.
        - `workdir` is a filesystem root, or its path contains whitespace.
        - The model copy would overlap the catalogue's model folder.
        - A file of an earlier run is a symbolic link.
    FileExistsError
        If `workdir` already holds a process directory for `spec` and
        `overwrite` is false.
    StampError
        If `workdir` is in one of these states:

        - it is stamped for another purpose or process;
        - it holds artifacts of a run but carries no stamp;
        - it holds something other than a stamp where the stamp belongs.

        Nothing is changed in that case.
    FileNotFoundError
        If MadGraph cannot be found.
    MadGraphError
        If MadGraph exits with an error, is still running at the time limit,
        or does not write the process directory or the event file. The
        message ends with the last lines of MadGraph's log.
    """
    if n_cores is None:
        n_cores = available_cores()
    if n_cores < 1:
        raise ValueError(f"n_cores must be positive, got {n_cores}")
    workspace = MadGraphWorkspace(
        spec,
        workdir,
        mg5_path=mg5_path,
        timeout=timeout,
        log_dir=log_dir,
    )
    if not overwrite:
        require_unoccupied(workspace.process_dir, what="Process directory")
    # Built before MadGraph starts or anything is removed, so that an invalid
    # request fails at once and leaves earlier results in place.
    launch = launch_commands(
        spec, process_dir=workspace.process_dir, n_events=n_events, seed=seed
    )

    with workspace.sealed_run() as set_aside:
        local_spec = workspace.copy_model()
        workspace.run_script(
            _PROCESS_SCRIPT,
            proc_card_commands(local_spec, output_dir=workspace.process_dir),
        )
        workspace.write_cards(n_cores)
        # Keeps MadGraph's unweighting in its seeded process (see the module docstring).
        with RaisedOpenFileLimit(enabled=seed is not None):
            workspace.run_script(_LAUNCH_SCRIPT, launch)

    output_path = workspace.output_path
    if not output_path.is_file():
        raise workspace.make_error(f"MadGraph wrote no event file {output_path}")
    return MadGraphRun(
        process_dir=workspace.process_dir,
        output_path=output_path,
        banner=Banner.read(output_path),
        n_cores=n_cores,
        log_path=workspace.log_path,
        usage=workspace.usage,
        set_aside=set_aside,
    )


class MadGraphWorkspace(ProgramWorkspace):
    """The working directory of one process's runs, and the steps a run takes in it.

    :func:`generate_events` drives a workspace from start to finish. A caller
    that needs the steps one at a time constructs a workspace and calls the
    steps inside ``with workspace.sealed_run():``, in this order:

    - :meth:`copy_model`,
    - :meth:`run_script` for the process script,
    - :meth:`write_cards`,
    - :meth:`run_script` for the launch script.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose runs the directory holds.
    workdir : Path
        The working directory, created when missing. Its path must not contain
        whitespace, because MadGraph does not support it. The directory must
        not be a filesystem root.
    mg5_path : Path or None, optional
        Path of MadGraph's ``bin/mg5_aMC``. By default the program is looked
        up on PATH.
    timeout : float or None, optional
        Seconds the run may take, counted from the creation of the workspace.
        ``None`` sets no limit.
    log_dir : Path or None, optional
        See the `log_dir` parameter of
        :class:`~omphjc.workspace.ProgramWorkspace`.

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
        If `mg5_path` is not a file, or if `mg5_path` is not given and PATH
        has no ``mg5_aMC``.
    """

    purpose = _RUN_PURPOSE
    program = _MG5_EXECUTABLE
    description = f"MadGraph's bin/{_MG5_EXECUTABLE}"
    log_name = _LOG_FILE
    error_type = MadGraphError

    def __init__(
        self,
        spec: ProcessSpec,
        workdir: Path,
        *,
        mg5_path: Path | None = None,
        timeout: float | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(
            spec.name, workdir, program_path=mg5_path, timeout=timeout, log_dir=log_dir
        )
        self.spec = spec
        if any(character.isspace() for character in str(self.workdir)):
            raise ValueError(
                f"MadGraph cannot run in a path with whitespace: {self.workdir}"
            )

    @property
    def process_dir(self) -> Path:
        return inside(self.workdir, self.spec.name)

    @property
    def model_copy_dir(self) -> Path | None:
        """The directory that the catalogue's model is copied to for the run.

        The value is ``None`` when the catalogue does not include the model.
        """
        if self.spec.model_dir is None:
            return None
        return inside(self.workdir, _MODELS_DIR, self.spec.model_base)

    @property
    def artifacts(self) -> list[str]:
        names = [self.spec.name, _PROCESS_SCRIPT, _LAUNCH_SCRIPT, *super().artifacts]
        if self.spec.model_dir is not None:
            names.append(f"{_MODELS_DIR}/{self.spec.model_base}")
        return names

    @property
    def output_path(self) -> Path:
        """The event file MadGraph writes.

        After MadSpin, it is the file of the decayed sample.
        """
        run = _DECAYED_RUN if self.spec.uses_madspin else _FIRST_RUN
        return self.process_dir / "Events" / run / _EVENT_FILE

    def clear_earlier_run(self, *, unconfirmed: Iterable[str] = ()) -> Path | None:
        """Clear what an earlier run left in the directory, and nothing else.

        A process directory without MadGraph's process card is not one that a
        run leaves. It is therefore moved aside, whether or not it was sealed.
        Everything named in `unconfirmed` is moved aside as well.

        Returns
        -------
        Path or None
            The folder that holds what was moved aside, or ``None`` when
            nothing was moved aside.

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
        """Copy the model into the directory.

        The returned spec imports the copy. When the catalogue does not
        include the model of the process, nothing is copied and the spec is
        returned unchanged.
        """
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
        """Write the core count and the MadSpin card.

        The core count is appended to MadGraph's configuration. The MadSpin
        card is written only for a process that uses MadSpin.

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
