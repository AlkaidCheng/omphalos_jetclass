"""The stage commands: each runs one stage of a job and prints its report."""

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import click

from omphjc.cli.formatting import (
    format_count,
    format_job_line,
    format_row,
    format_usage,
)
from omphjc.cli.options import (
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
    GENERATE,
    SHOWER,
    SIMULATE,
    Job,
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
        stage=GENERATE,
        run=run,
        title="MadGraph generation",
        lines=_generation_lines,
    )


def _generation_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the generate stage of `job` ran with and what it made."""
    metadata = record.result.metadata
    events = job.require_events(GENERATE)
    yield f"  MadGraph {metadata['madgraph_version']}, seed {record.parameters['seed']}"
    yield format_row("events requested", record.parameters["events"])
    yield format_row("events generated", events.n_events)
    cross_section = (
        f"{metadata['cross_section_pb']:g}"
        f" +- {metadata['cross_section_error_pb']:.3g} pb"
    )
    yield format_row("cross section", cross_section)
    yield format_row("event file", job.relative_path(events.path))
    yield format_row("log", record.log)
    yield format_row("cards", f"{job.relative_path(job.task_dir(GENERATE))}/cards/")


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
) -> None:
    """Shower one job's generated events with Pythia 8; the detector comes later."""
    spec = lookup_process(specs, name)
    overrides = dict(parse_assignment(item) for item in assignments)

    def run(job: Job) -> TaskRecord:
        return shower(
            job,
            overrides=overrides,
            timeout=timeout,
            force=force,
            delphes_pythia8_path=delphes_pythia8_path,
        )

    _run_stage_command(
        spec,
        job_id,
        outdir,
        stage=SHOWER,
        run=run,
        title="Pythia shower",
        lines=_shower_lines,
    )


def _shower_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the shower stage of `job` ran with and what it made."""
    metadata = record.result.metadata
    events = job.require_events(SHOWER)
    yield f"  Pythia {metadata['pythia_version']}, seed {record.parameters['seed']}"
    yield format_row("events read", metadata["events_read"])
    yield format_row("events kept", events.n_events)
    if "matching_efficiency" in metadata:
        yield format_row("kept by matching", f"{metadata['matching_efficiency']:.1%}")
    yield format_row("output", job.relative_path(events.path))
    yield format_row("log", record.log)
    yield format_row("settings", ", ".join(metadata["settings"]))


@click.command("simulate")
@click.argument("name")
@JOB_ID_OPTION
@OUTDIR_OPTION
@click.option(
    "--card",
    "card_path",
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
@click.pass_obj
def simulate_job(
    specs: Catalogue,
    name: str,
    job_id: int,
    outdir: Path,
    card_path: Path | None,
    timeout: float | None,
    force: bool,
    delphes_root_path: Path | None,
) -> None:
    """Simulate the detector on one job's showered events with Delphes."""
    spec = lookup_process(specs, name)

    def run(job: Job) -> TaskRecord:
        return simulate(
            job,
            card_path=card_path,
            timeout=timeout,
            force=force,
            delphes_root_path=delphes_root_path,
        )

    _run_stage_command(
        spec,
        job_id,
        outdir,
        stage=SIMULATE,
        run=run,
        title="Delphes simulation",
        lines=_simulation_lines,
    )


def _simulation_lines(job: Job, record: TaskRecord) -> Iterator[str]:
    """Yield what the simulation stage of `job` ran with and what it made."""
    events = job.require_events(SIMULATE)
    yield format_row("card", ", ".join(record.result.metadata["card"]))
    yield format_row("seed", record.parameters["seed"])
    yield format_row("events", events.n_events)
    yield format_row("output", job.relative_path(events.path))
    yield format_row("log", record.log)


def _run_stage_command(
    spec: ProcessSpec,
    job_id: int,
    outdir: Path,
    *,
    stage: str,
    run: Callable[[Job], TaskRecord],
    title: str,
    lines: Callable[[Job, TaskRecord], Iterable[str]],
) -> None:
    """Run `stage` of one job of `spec` through `run` and print its report.

    `title` names the stage in the report and `lines` gives the rows between
    the title and what the stage took. An error in :data:`_STAGE_ERRORS`
    becomes a :class:`click.ClickException`.
    """
    try:
        job = Job(spec, outdir, job_id)
        earlier = job.manifest.stages.get(stage)
        with exception_on_termination():
            record = run(job)
    except _STAGE_ERRORS as error:
        raise click.ClickException(str(error)) from error
    outcome = "done, kept from an earlier run" if record is earlier else "done"
    click.echo(format_job_line(job.spec.name, job.job_id, job.root_dir))
    click.echo(f"{title}: {outcome}")
    for line in lines(job, record):
        click.echo(line)
    click.echo(format_row("took", format_usage(record.usage)))
    _report_set_aside(job)


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
