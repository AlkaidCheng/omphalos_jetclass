"""The ``omphjc`` command line: its root group and the commands other than the stages.

The stage commands are defined in :mod:`omphjc.cli.stages`.
"""

from pathlib import Path

import click

from omphjc import __version__
from omphjc.cli.formatting import format_count, format_job_line, format_size
from omphjc.cli.options import (
    EXISTING_FILE,
    OUTDIR_OPTION,
    SET_OPTION,
    Catalogue,
    lookup_process,
    parse_assignment,
)
from omphjc.cli.stages import generate_job, shower_job, simulate_job
from omphjc.config_paths import config_dir, export_config
from omphjc.jobs import Job
from omphjc.processes import default_catalogue, read_catalogue
from omphjc.stamps import StampError
from omphjc.tools.delphes.card import DelphesCard, reference_card
from omphjc.tools.madgraph.cards import launch_commands, proc_card_commands
from omphjc.tools.madgraph.run_card import format_value
from omphjc.tools.pythia.cmnd import PythiaCmnd
from omphjc.validation.cards import compare_all


@click.group()
@click.version_option(__version__, prog_name="omphjc")
@click.option(
    "--catalogue",
    "catalogue_path",
    type=EXISTING_FILE,
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


cli.add_command(generate_job)
cli.add_command(shower_job)
cli.add_command(simulate_job)


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
    spec = lookup_process(specs, name)
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
    differences = compare_all(checked)
    if not differences:
        click.echo(f"{len(checked)} processes match their reference cards.")
        return
    for name, process_differences in differences.items():
        for difference in process_differences:
            click.echo(f"{name}: {difference}", err=True)
    raise SystemExit(1)


@cli.command("clean")
@click.argument("name")
@click.option("--job-id", "job_id", type=int, required=True, help="Job number.")
@OUTDIR_OPTION
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
    spec = lookup_process(specs, name)
    try:
        job = Job(spec, outdir, job_id)
        folders = job.set_aside_folders()
        sizes = [folder.size() for folder in folders]
        if not dry_run:
            job.clear_set_aside_folders()
    except (ValueError, StampError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(format_job_line(job.spec.name, job.job_id, job.root_dir))
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
@SET_OPTION
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
    spec = lookup_process(specs, name)
    overrides = dict(parse_assignment(item) for item in assignments)
    cmnd = PythiaCmnd.from_process(
        spec, lhe_path=lhe_path, n_events=n_events, seed=seed, overrides=overrides
    )
    click.echo(cmnd.to_text(title=spec.name), nl=False)


@cli.group()
def delphes() -> None:
    """Inspect Delphes cards as configuration keys and values."""


@delphes.command("show")
@click.argument(
    "card_path",
    metavar="CARD",
    type=EXISTING_FILE,
    required=False,
)
def delphes_show(card_path: Path | None) -> None:
    """Print the evaluated configuration of a card (default: the official one)."""
    configuration = (
        reference_card() if card_path is None else DelphesCard.read(card_path)
    )
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
    type=EXISTING_FILE,
)
@click.option(
    "--reference",
    "reference_path",
    type=EXISTING_FILE,
    help="Card to compare against (default: the official JetClass card).",
)
def delphes_compare(card_path: Path, reference_path: Path | None) -> None:
    """Report configuration differences between a card and a reference."""
    reference_configuration = (
        reference_card() if reference_path is None else DelphesCard.read(reference_path)
    )
    differences = DelphesCard.read(card_path).differences(reference_configuration)
    if not differences:
        click.echo("The cards configure Delphes identically.")
        return
    for difference in differences:
        click.echo(str(difference), err=True)
    raise SystemExit(1)


def _abbreviate(value: tuple[str, ...], limit: int = 8) -> str:
    if len(value) <= limit:
        return " ".join(value)
    head = " ".join(value[: limit // 2])
    tail = " ".join(value[-(limit // 2) :])
    return f"{head} … {tail}  ({len(value)} elements)"


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"
