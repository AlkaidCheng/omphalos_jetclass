"""The ``omphjc`` command line."""

from collections.abc import Mapping
from pathlib import Path

import click

from omphjc import __version__
from omphjc.cli.formatting import format_count, format_size, format_usage
from omphjc.config_paths import config_dir, export_config
from omphjc.delphes import DelphesCard, compare_cards, read_card, reference_card
from omphjc.jobs import (
    MADGRAPH,
    SHOWER,
    SIMULATE,
    Job,
    StageRecord,
    TerminationError,
    exception_on_termination,
    generate,
    shower,
    simulate,
)
from omphjc.madgraph import (
    compare_all,
    format_value,
    launch_commands,
    proc_card_commands,
)
from omphjc.processes import ProcessSpec, default_catalogue, read_catalogue
from omphjc.programs import ProgramError
from omphjc.pythia import format_cmnd, shower_settings
from omphjc.stamps import StampError

Catalogue = Mapping[str, ProcessSpec]


@click.group()
@click.version_option(__version__, prog_name="omphjc")
@click.option(
    "--catalogue",
    "catalogue_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    envvar="OMPHJC_CATALOGUE",
    help="Process catalogue to use instead of the default config/jetclass.yaml.",
)
@click.pass_context
def cli(context: click.Context, catalogue_path: Path | None) -> None:
    """Generate JetClass samples for Delphes and Parnassus."""
    context.obj = (
        default_catalogue()
        if catalogue_path is None
        else read_catalogue(catalogue_path)
    )


@cli.group(invoke_without_command=True)
@click.pass_context
def processes(context: click.Context) -> None:
    """List the processes of the catalogue, or inspect one with ``show``."""
    if context.invoked_subcommand is not None:
        return
    specs: Catalogue = context.obj
    click.echo(f"{'process':<12} {'class':<6} {'model':<22} {'matched':<8} madspin")
    for spec in specs.values():
        click.echo(
            f"{spec.name:<12} {spec.label:<6} {spec.model:<22} "
            f"{_yes_no(spec.matching):<8} {_yes_no(spec.uses_madspin)}"
        )


@processes.command("show")
@click.argument("name")
@click.pass_obj
def processes_show(specs: Catalogue, name: str) -> None:
    """Print the MadGraph inputs the package writes for one process."""
    spec = _lookup(specs, name)
    click.echo(f"{spec.name}: {spec.description}")
    click.echo(f"class label: {spec.label}")
    click.echo(f"seed offset: {spec.seed_offset}")
    click.echo("\nprocess script:")
    for line in proc_card_commands(spec, output_dir=Path(spec.name)):
        click.echo(f"  {line}")
    click.echo("\nlaunch script (1000 events, random seed):")
    for line in launch_commands(
        spec, process_dir=Path(spec.name), n_events=1000, seed=None
    ):
        click.echo(f"  {line}")
    click.echo("\nrun-card settings:")
    for key, value in spec.run_card.items():
        click.echo(f"  {key} = {format_value(value)}")


@cli.command("check-cards")
@click.pass_obj
def check_cards(specs: Catalogue) -> None:
    """Compare every process that names reference cards with those cards."""
    checked = [spec for spec in specs.values() if spec.reference_cards is not None]
    unchecked = [spec.name for spec in specs.values() if spec.reference_cards is None]
    if unchecked:
        click.echo(f"Without reference cards, not checked: {', '.join(unchecked)}")
    mismatches = compare_all(checked)
    if not mismatches:
        click.echo(f"{len(checked)} processes match their reference cards.")
        return
    for mismatch in mismatches:
        click.echo(str(mismatch), err=True)
    raise SystemExit(1)


@cli.command("generate")
@click.argument("name")
@click.option(
    "--job",
    "job_id",
    type=int,
    required=True,
    help="Job number; the seed of every program follows from it.",
)
@click.option(
    "--events", "n_events", type=int, required=True, help="Events to generate."
)
@click.option(
    "--outdir",
    "outdir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory holding the jobs of every process.",
)
@click.option(
    "--cores",
    "n_cores",
    type=int,
    default=None,
    help="Cores MadGraph may use (default: every usable CPU).",
)
@click.option("--timeout", type=float, default=None, help="Seconds MadGraph may take.")
@click.option(
    "--force", is_flag=True, help="Run the stage again, replacing its outputs."
)
@click.option(
    "--mg5",
    "mg5_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
    spec = _lookup(specs, name)
    try:
        job = Job(spec, outdir, job_id)
        earlier = job.manifest.stages.get(MADGRAPH)
        with exception_on_termination():
            record = generate(
                job,
                n_events=n_events,
                n_cores=n_cores,
                timeout=timeout,
                force=force,
                mg5_path=mg5_path,
            )
    except (
        ValueError,
        FileExistsError,
        FileNotFoundError,
        StampError,
        ProgramError,
        TerminationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    _report_generation(job, record, kept=record is earlier)


def _report_generation(job: Job, record: StageRecord, *, kept: bool) -> None:
    """Print what the MadGraph stage of `job` ran with and what it made."""
    metadata = record.metadata
    outcome = "done, kept from an earlier run" if kept else "done"
    click.echo(f"{job.spec.name} job {job.job_id}: {job.root_dir}")
    click.echo(f"MadGraph generation: {outcome}")
    click.echo(
        f"  MadGraph {metadata['madgraph_version']}, seed {record.parameters['seed']}"
    )
    click.echo(f"  events requested  {record.parameters['events']}")
    click.echo(f"  events generated  {metadata['events']}")
    click.echo(
        f"  cross section     {metadata['cross_section_pb']:g}"
        f" +- {metadata['cross_section_error_pb']:.3g} pb"
    )
    click.echo(f"  event file        {record.outputs[0]}")
    click.echo(f"  log               {record.log}")
    click.echo(
        f"  cards             {job.relative_path(job.stage_dir(MADGRAPH))}/cards/"
    )
    click.echo(f"  took              {format_usage(record.usage)}")
    _report_set_aside(job)


def _report_set_aside(job: Job) -> None:
    """Print what earlier runs of `job` set aside, when anything is."""
    folders = job.set_aside_folders()
    if not folders:
        return
    click.echo(
        f"  set aside         {format_count(len(folders), 'folder')} left by earlier runs; "
        "omphjc clean --set-aside deletes them"
    )


@cli.command("shower")
@click.argument("name")
@click.option(
    "--job",
    "job_id",
    type=int,
    required=True,
    help="Job number; the seed of every program follows from it.",
)
@click.option(
    "--outdir",
    "outdir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory holding the jobs of every process.",
)
@click.option(
    "--set",
    "assignments",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override one Pythia setting; may be repeated.",
)
@click.option(
    "--timeout", type=float, default=None, help="Seconds DelphesPythia8 may take."
)
@click.option(
    "--force", is_flag=True, help="Run the stage again, replacing its outputs."
)
@click.option(
    "--delphes-pythia8",
    "delphes_pythia8_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
    spec = _lookup(specs, name)
    overrides = dict(_assignment(item) for item in assignments)
    try:
        job = Job(spec, outdir, job_id)
        earlier = job.manifest.stages.get(SHOWER)
        with exception_on_termination():
            record = shower(
                job,
                overrides=overrides,
                timeout=timeout,
                force=force,
                delphes_pythia8_path=delphes_pythia8_path,
            )
    except (
        ValueError,
        FileExistsError,
        FileNotFoundError,
        StampError,
        ProgramError,
        TerminationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    _report_shower(job, record, kept=record is earlier)


def _report_shower(job: Job, record: StageRecord, *, kept: bool) -> None:
    """Print what the shower stage of `job` ran with and what it made."""
    metadata = record.metadata
    outcome = "done, kept from an earlier run" if kept else "done"
    click.echo(f"{job.spec.name} job {job.job_id}: {job.root_dir}")
    click.echo(f"Pythia shower: {outcome}")
    click.echo(
        f"  Pythia {metadata['pythia_version']}, seed {record.parameters['seed']}"
    )
    click.echo(f"  events read       {metadata['events_read']}")
    click.echo(f"  events kept       {metadata['events_accepted']}")
    if "matching_efficiency" in metadata:
        click.echo(f"  kept by matching  {metadata['matching_efficiency']:.1%}")
    click.echo(f"  output            {record.outputs[0]}")
    click.echo(f"  log               {record.log}")
    click.echo(f"  settings          {', '.join(metadata['settings'])}")
    click.echo(f"  took              {format_usage(record.usage)}")
    _report_set_aside(job)


@cli.command("simulate")
@click.argument("name")
@click.option(
    "--job",
    "job_id",
    type=int,
    required=True,
    help="Job number; the seed of every program follows from it.",
)
@click.option(
    "--outdir",
    "outdir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory holding the jobs of every process.",
)
@click.option(
    "--card",
    "card_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Detector card to run instead of the process's.",
)
@click.option(
    "--timeout", type=float, default=None, help="Seconds DelphesROOT may take."
)
@click.option(
    "--force", is_flag=True, help="Run the stage again, replacing its outputs."
)
@click.option(
    "--delphes-root",
    "delphes_root_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
    spec = _lookup(specs, name)
    try:
        job = Job(spec, outdir, job_id)
        earlier = job.manifest.stages.get(SIMULATE)
        with exception_on_termination():
            record = simulate(
                job,
                card_path=card_path,
                timeout=timeout,
                force=force,
                delphes_root_path=delphes_root_path,
            )
    except (
        ValueError,
        FileExistsError,
        FileNotFoundError,
        StampError,
        ProgramError,
        TerminationError,
    ) as error:
        raise click.ClickException(str(error)) from error
    _report_simulation(job, record, kept=record is earlier)


def _report_simulation(job: Job, record: StageRecord, *, kept: bool) -> None:
    """Print what the simulation stage of `job` ran with and what it made."""
    metadata = record.metadata
    outcome = "done, kept from an earlier run" if kept else "done"
    click.echo(f"{job.spec.name} job {job.job_id}: {job.root_dir}")
    click.echo(f"Delphes simulation: {outcome}")
    click.echo(f"  card              {', '.join(metadata['card'])}")
    click.echo(f"  seed              {record.parameters['seed']}")
    click.echo(f"  events            {metadata['events']}")
    click.echo(f"  output            {record.outputs[0]}")
    click.echo(f"  log               {record.log}")
    click.echo(f"  took              {format_usage(record.usage)}")
    _report_set_aside(job)


@cli.command("clean")
@click.argument("name")
@click.option("--job", "job_id", type=int, required=True, help="Job number.")
@click.option(
    "--outdir",
    "outdir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory holding the jobs of every process.",
)
@click.option(
    "--set-aside",
    "set_aside",
    is_flag=True,
    help="Delete what earlier runs set aside in <stage>/omphjc-set-aside/.",
)
@click.option(
    "--dry-run", is_flag=True, help="List what would be deleted; delete nothing."
)
@click.pass_obj
def clean_job(
    specs: Catalogue,
    name: str,
    job_id: int,
    outdir: Path,
    set_aside: bool,
    dry_run: bool,
) -> None:
    """Delete what one job of a process no longer needs; an option names what."""
    if not set_aside:
        raise click.UsageError("Name what to delete: --set-aside.")
    spec = _lookup(specs, name)
    try:
        job = Job(spec, outdir, job_id)
        folders = job.set_aside_folders()
        sizes = [folder.size() for folder in folders]
        if not dry_run:
            job.clear_set_aside_folders()
    except (ValueError, StampError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"{job.spec.name} job {job.job_id}: {job.root_dir}")
    if not folders:
        click.echo("set aside: nothing")
        return
    verb = "would delete" if dry_run else "deleted"
    click.echo(
        f"set aside: {verb} {format_count(len(folders), 'folder')}, {format_size(sum(sizes))}"
    )
    for folder, folder_size in zip(folders, sizes, strict=True):
        click.echo(
            f"  {job.relative_path(folder.path):<56} "
            f"{folder.created:%Y-%m-%d %H:%M} UTC  {format_size(folder_size):>9}"
        )


@cli.group()
def config() -> None:
    """Locate or copy the configuration included with the package."""


@config.command("path")
def config_path() -> None:
    """Print the directory of the package's configuration."""
    click.echo(str(config_dir()))


@config.command("export")
@click.argument(
    "destination_dir", metavar="DESTINATION", type=click.Path(path_type=Path)
)
def config_export(destination_dir: Path) -> None:
    """Copy the package's configuration to DESTINATION for editing."""
    try:
        export_config(destination_dir)
    except FileExistsError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Configuration copied to {destination_dir}")


@cli.group()
def pythia() -> None:
    """Pythia 8 settings for DelphesPythia8."""


@pythia.command("show")
@click.argument("name")
@click.option(
    "--events",
    "n_events",
    type=int,
    default=1000,
    show_default=True,
    help="Upper bound on the showered events (Main:numberOfEvents).",
)
@click.option(
    "--seed", type=int, default=None, help="Random:seed (default: from the clock)."
)
@click.option(
    "--lhe",
    "lhe_path",
    type=click.Path(path_type=Path),
    default=Path("events.lhe"),
    show_default=True,
    help="Uncompressed LHE file Pythia reads.",
)
@click.option(
    "--set",
    "assignments",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override one Pythia setting; may be repeated.",
)
@click.pass_obj
def pythia_show(
    specs: Catalogue,
    name: str,
    n_events: int,
    seed: int | None,
    lhe_path: Path,
    assignments: tuple[str, ...],
) -> None:
    """Print the Pythia command file written for one process."""
    spec = _lookup(specs, name)
    overrides = dict(_assignment(item) for item in assignments)
    settings = shower_settings(
        spec, lhe_path=lhe_path, n_events=n_events, seed=seed, overrides=overrides
    )
    click.echo(format_cmnd(settings, title=spec.name), nl=False)


@cli.group()
def delphes() -> None:
    """Inspect Delphes cards as configuration keys and values."""


@delphes.command("show")
@click.argument(
    "card_path",
    metavar="CARD",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
def delphes_show(card_path: Path | None) -> None:
    """Print the evaluated configuration of a card (default: the official one)."""
    configuration = reference_card() if card_path is None else read_card(card_path)
    click.echo("ExecutionPath:")
    for name in configuration.execution_path:
        click.echo(f"  {name}")
    for key, value in configuration.settings.items():
        click.echo(f"{key} = {' '.join(value)}")
    for name, module in configuration.modules.items():
        click.echo(f"\nmodule {module.type} {name}")
        for key, value in module.parameters.items():
            click.echo(f"  {key} = {_abbreviate(value)}")


@delphes.command("compare")
@click.argument(
    "card_path",
    metavar="CARD",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--reference",
    "reference_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Card to compare against (default: the official JetClass card).",
)
def delphes_compare(card_path: Path, reference_path: Path | None) -> None:
    """Report configuration differences between a card and a reference."""
    reference_configuration: DelphesCard = (
        reference_card() if reference_path is None else read_card(reference_path)
    )
    differences = compare_cards(read_card(card_path), reference_configuration)
    if not differences:
        click.echo("The cards configure Delphes identically.")
        return
    for difference in differences:
        click.echo(str(difference), err=True)
    raise SystemExit(1)


def _lookup(specs: Catalogue, name: str) -> ProcessSpec:
    try:
        return specs[name]
    except KeyError:
        known = ", ".join(specs)
        raise click.BadParameter(
            f"unknown process {name!r}; choose from {known}"
        ) from None


def _assignment(text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    if not separator or not key.strip() or not value.strip():
        raise click.BadParameter(
            f"expected KEY=VALUE, got {text!r}", param_hint="--set"
        )
    return key.strip(), value.strip()


def _abbreviate(value: tuple[str, ...], limit: int = 8) -> str:
    if len(value) <= limit:
        return " ".join(value)
    head = " ".join(value[: limit // 2])
    tail = " ".join(value[-(limit // 2) :])
    return f"{head} … {tail}  ({len(value)} elements)"


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"
