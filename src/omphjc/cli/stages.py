"""The stage commands: each runs one stage of a job and prints its report."""

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import click

from omphjc.cli.formatting import (
    format_count,
    format_fingerprint,
    format_job_line,
    format_row,
    format_usage,
)
from omphjc.cli.options import (
    ACCEPT_INPUT_OPTION,
    EXISTING_FILE,
    FORCE_OPTION,
    JOB_ID_OPTION,
    OUTDIR_OPTION,
    SET_OPTION,
    Catalogue,
    lookup_process,
    parse_assignment,
)
from omphjc.jobs import (
    INPUT_FINGERPRINT_PARAMETER,
    GenerateStage,
    Job,
    ReplacedRunError,
    ShowerStage,
    SimulateStage,
    Stage,
    TaskRecord,
    TerminationError,
    exception_on_termination,
    generate,
    shower,
    simulate,
)
from omphjc.processes import ProcessSpec
from omphjc.programs import ProgramError
from omphjc.stamps import StampError

# The errors of a stage command that are reported as a message, not a traceback.
_STAGE_ERRORS = (
    ValueError,
    FileExistsError,
    FileNotFoundError,
    StampError,
    ProgramError,
    TerminationError,
    ReplacedRunError,
)


@click.command("generate")
@click.argument("name")
@JOB_ID_OPTION
@click.option(
    "--events", "n_events", type=int, required=True, help="Events to generate."
)
@OUTDIR_OPTION
@click.option(
    "--cores",
    "n_cores",
    type=int,
    default=None,
    help="Cores MadGraph may use (default: every usable CPU).",
)
@click.option("--timeout", type=float, default=None, help="Seconds MadGraph may take.")
@FORCE_OPTION
@click.option(
    "--mg5",
    "mg5_path",
    type=EXISTING_FILE,
    default=None,
    help="MadGraph's bin/mg5_aMC (default: the one on PATH).",
)
@click.pass_obj
def generate_job(
    specs: Catalogue,
    name: str,
    job_id: int,
    n_events: int,
    outdir: Path,
    n_cores: int | None,
    timeout: float | None,
    force: bool,
    mg5_path: Path | None,
) -> None:
    """Generate the parton-level events of one job of a process with MadGraph."""
    spec = lookup_process(specs, name)

    def run(job: Job) -> TaskRecord:
        return generate(
            job,
            n_events=n_events,
            n_cores=n_cores,
            timeout=timeout,
            force=force,
            mg5_path=mg5_path,
        )

    _run_stage_command(
        spec,
        job_id,
        outdir,
        stage=GenerateStage(),
        run=run,
        title="MadGraph generation",
        lines=_generation_lines,
    )


def _generation_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the generate stage of `job` ran with and what it made."""
    metadata = record.metadata
    events = job.require_events(GenerateStage())
    yield f"  MadGraph {metadata['madgraph_version']}, seed {record.parameters['seed']}"
    yield format_row("events requested", record.parameters["events"])
    yield format_row("events generated", events.n_events)
    cross_section = (
        f"{metadata['cross_section_pb']:g}"
        f" +- {metadata['cross_section_error_pb']:.3g} pb"
    )
    yield format_row("cross section", cross_section)
    yield format_row("event file", job.relative_path(events.path))
    yield format_row("log", record.latest_run.log)
    yield format_row(
        "cards", f"{job.relative_path(job.task_dir(GenerateStage()))}/cards/"
    )


@click.command("shower")
@click.argument("name")
@JOB_ID_OPTION
@OUTDIR_OPTION
@SET_OPTION
@click.option(
    "--timeout", type=float, default=None, help="Seconds DelphesPythia8 may take."
)
@FORCE_OPTION
@click.option(
    "--delphes-pythia8",
    "delphes_pythia8_path",
    type=EXISTING_FILE,
    default=None,
    help="Delphes's DelphesPythia8 (default: the one on PATH).",
)
@ACCEPT_INPUT_OPTION
@click.pass_obj
def shower_job(
    specs: Catalogue,
    name: str,
    job_id: int,
    outdir: Path,
    assignments: tuple[str, ...],
    timeout: float | None,
    force: bool,
    delphes_pythia8_path: Path | None,
    accept_input: bool,
) -> None:
    """Shower one job's generated events with Pythia 8; the detector comes later."""
    _refuse_accept_input_with_force(accept_input, force)
    spec = lookup_process(specs, name)
    overrides = dict(parse_assignment(item) for item in assignments)

    def run(job: Job) -> TaskRecord:
        return shower(
            job,
            overrides=overrides,
            timeout=timeout,
            accept_input=accept_input,
            force=force,
            delphes_pythia8_path=delphes_pythia8_path,
        )

    _run_stage_command(
        spec,
        job_id,
        outdir,
        stage=ShowerStage(),
        run=run,
        title="Pythia shower",
        lines=_shower_lines,
    )


def _shower_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the shower stage of `job` ran with and what it made."""
    metadata = record.metadata
    events = job.require_events(ShowerStage())
    yield f"  Pythia {metadata['pythia_version']}, seed {record.parameters['seed']}"
    yield format_row("events read", metadata["events_read"])
    yield format_row("events kept", events.n_events)
    if "matching_efficiency" in metadata:
        yield format_row("kept by matching", f"{metadata['matching_efficiency']:.1%}")
    yield format_row("output", job.relative_path(events.path))
    yield format_row("log", record.latest_run.log)
    yield format_row("settings", _format_card_paths(job, record))


@click.command("simulate")
@click.argument("name")
@JOB_ID_OPTION
@OUTDIR_OPTION
@click.option(
    "--card",
    "detector_card_path",
    type=EXISTING_FILE,
    default=None,
    help="Detector card to run instead of the process's.",
)
@click.option(
    "--timeout", type=float, default=None, help="Seconds DelphesROOT may take."
)
@FORCE_OPTION
@click.option(
    "--delphes-root",
    "delphes_root_path",
    type=EXISTING_FILE,
    default=None,
    help="Delphes's DelphesROOT (default: the one on PATH).",
)
@ACCEPT_INPUT_OPTION
@click.pass_obj
def simulate_job(
    specs: Catalogue,
    name: str,
    job_id: int,
    outdir: Path,
    detector_card_path: Path | None,
    timeout: float | None,
    force: bool,
    delphes_root_path: Path | None,
    accept_input: bool,
) -> None:
    """Simulate the detector on one job's showered events with Delphes."""
    _refuse_accept_input_with_force(accept_input, force)
    spec = lookup_process(specs, name)

    def run(job: Job) -> TaskRecord:
        # The adapter loads the array libraries, so it is imported here and
        # not when a command starts.
        from omphjc.tools.delphes.adapter import DelphesSimulator

        simulator = DelphesSimulator(
            spec,
            detector_card_path=detector_card_path,
            timeout_seconds=timeout,
            delphes_root_path=delphes_root_path,
        )
        return simulate(job, simulator, accept_input=accept_input, force=force)

    _run_stage_command(
        spec,
        job_id,
        outdir,
        stage=SimulateStage(),
        run=run,
        title="Delphes simulation",
        lines=_simulation_lines,
    )


def _simulation_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the simulation stage of `job` ran with and what it made."""
    events = job.require_events(SimulateStage())
    yield format_row("card", _format_card_paths(job, record))
    yield format_row("seed", record.parameters["seed"])
    yield format_row("events", events.n_events)
    yield format_row("output", job.relative_path(events.path))
    yield format_row("log", record.latest_run.log)


def _format_card_paths(job: Job, record: TaskRecord) -> str:
    """Return the paths of the cards in `record` as one line of a report.

    The paths are relative to the job directory.
    """
    return ", ".join(job.relative_path(card.path) for card in record.cards.values())


def _run_stage_command(
    spec: ProcessSpec,
    job_id: int,
    outdir: Path,
    *,
    stage: Stage,
    run: Callable[[Job], TaskRecord],
    title: str,
    lines: Callable[[Job, TaskRecord], Iterable[str]],
) -> None:
    """Run `stage` of one job of `spec` through `run` and print its report.

    The report holds, in order:

    - the job and its directory;
    - `title`, which names the stage, and whether the result was kept;
    - the ID of the task's latest run;
    - the rows that `lines` gives;
    - an ``input`` row, when the stage was kept for other events than those
      it read;
    - the number of runs and the status of each, when the task has more than
      one run;
    - what the latest run took.

    An error in :data:`_STAGE_ERRORS` becomes a :class:`click.ClickException`.
    """
    try:
        job = Job(spec, outdir, job_id)
        previous_record = job.task_record(stage)
        with exception_on_termination():
            record = run(job)
    except _STAGE_ERRORS as error:
        raise click.ClickException(str(error)) from error
    kept = previous_record is not None and record.runs == previous_record.runs
    outcome = "done, kept from an earlier run" if kept else "done"
    click.echo(format_job_line(job.spec.name, job.job_id, job.root_dir))
    click.echo(f"{title}: {outcome}")
    click.echo(format_row("run ID", record.latest_run.run_id))
    for line in lines(job, record):
        click.echo(line)
    if stage.upstream_stage is not None:
        _report_accepted_input(job, record, stage.upstream_stage)
    if len(record.runs) > 1:
        statuses = ", ".join(run.status for run in record.runs)
        click.echo(format_row("runs", f"{len(record.runs)} ({statuses})"))
    click.echo(format_row("took", format_usage(record.latest_run.usage)))
    _report_set_aside(job)


def _report_accepted_input(job: Job, record: TaskRecord, upstream_stage: Stage) -> None:
    """Print the ``input`` row of a task that was kept for another input.

    The row is printed when the record holds an accepted input and the events
    of `upstream_stage` are not the ones the task read.
    """
    accepted_input = record.accepted_input
    input_fingerprint = record.parameters[INPUT_FINGERPRINT_PARAMETER]
    if accepted_input is None:
        return
    if job.require_events(upstream_stage).fingerprint == input_fingerprint:
        return
    acceptance = (
        f"accepted (ran on {format_fingerprint(input_fingerprint)}, "
        f"accepted for {format_fingerprint(accepted_input.fingerprint)})"
    )
    click.echo(format_row("input", acceptance))


def _refuse_accept_input_with_force(accept_input: bool, force: bool) -> None:
    """Refuse ``--accept-input`` together with ``--force``."""
    if accept_input and force:
        raise click.UsageError("--accept-input and --force cannot be used together.")


def _report_set_aside(job: Job) -> None:
    """Print what earlier runs of `job` set aside, when anything is."""
    folders = job.set_aside_folders()
    if not folders:
        return
    count = format_count(len(folders), "folder")
    click.echo(
        format_row(
            "set aside",
            f"{count} left by earlier runs; omphjc clean --set-aside deletes them",
        )
    )
