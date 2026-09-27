"""The ``omphjc`` command line."""

from collections.abc import Mapping
from pathlib import Path

import click

from omphjc import __version__
from omphjc.config_paths import config_root, export_config, models_dir
from omphjc.delphes import DelphesCard, compare_cards, load_card, reference_card
from omphjc.madgraph import (
    compare_all,
    format_value,
    launch_commands,
    proc_card_commands,
)
from omphjc.processes import ProcessSpec, catalogue, load_catalogue

Catalogue = Mapping[str, ProcessSpec]


@click.group()
@click.version_option(__version__, prog_name="omphjc")
@click.option(
    "--catalogue",
    "catalogue_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    envvar="OMPHJC_CATALOGUE",
    help="Process catalogue to use instead of the shipped config/jetclass.yaml.",
)
@click.pass_context
def cli(context: click.Context, catalogue_file: Path | None) -> None:
    """Generate JetClass samples for Delphes and Parnassus."""
    context.obj = (
        catalogue() if catalogue_file is None else load_catalogue(catalogue_file)
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
            f"{_yes_no(spec.matching):<8} {_yes_no(spec.madspin)}"
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
    for line in proc_card_commands(
        spec, output_dir=Path(spec.name), models_dir=models_dir()
    ):
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
    """Compare the catalogue with the official JetClass gridpack cards."""
    mismatches = compare_all(specs.values())
    if not mismatches:
        click.echo(f"{len(specs)} processes match the official cards.")
        return
    for mismatch in mismatches:
        click.echo(str(mismatch), err=True)
    raise SystemExit(1)


@cli.group()
def config() -> None:
    """Locate or copy the configuration shipped with the package."""


@config.command("path")
def config_path() -> None:
    """Print the directory of the shipped configuration."""
    click.echo(str(config_root()))


@config.command("export")
@click.argument("destination", type=click.Path(path_type=Path))
def config_export(destination: Path) -> None:
    """Copy the shipped configuration to DESTINATION for editing."""
    try:
        export_config(destination)
    except FileExistsError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Configuration copied to {destination}")


@cli.group()
def delphes() -> None:
    """Inspect Delphes cards as configuration keys and values."""


@delphes.command("show")
@click.argument(
    "card", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=False
)
def delphes_show(card: Path | None) -> None:
    """Print the evaluated configuration of a card (default: the official one)."""
    configuration = reference_card() if card is None else load_card(card)
    click.echo("ExecutionPath:")
    for name in configuration.execution_path:
        click.echo(f"  {name}")
    for key, value in configuration.settings.items():
        click.echo(f"{key} = {' '.join(value)}")
    for name, module in configuration.modules.items():
        click.echo(f"\nmodule {module.type} {name}")
        for key, value in module.parameters.items():
            click.echo(f"  {key} = {_render(value)}")


@delphes.command("compare")
@click.argument("card", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--reference",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Card to compare against (default: the official JetClass card).",
)
def delphes_compare(card: Path, reference: Path | None) -> None:
    """Report configuration differences between a card and a reference."""
    reference_configuration: DelphesCard = (
        reference_card() if reference is None else load_card(reference)
    )
    differences = compare_cards(load_card(card), reference_configuration)
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


def _render(value: tuple[str, ...], limit: int = 8) -> str:
    if len(value) <= limit:
        return " ".join(value)
    head = " ".join(value[: limit // 2])
    tail = " ".join(value[-(limit // 2) :])
    return f"{head} … {tail}  ({len(value)} elements)"


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"
