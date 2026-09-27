"""The ``omphjc`` command line."""

from pathlib import Path

import click

from omphjc import __version__
from omphjc.madgraph import (
    compare_all,
    format_value,
    launch_commands,
    proc_card_commands,
)
from omphjc.processes import catalogue, get_process, models_dir, process_names


@click.group()
@click.version_option(__version__, prog_name="omphjc")
def cli() -> None:
    """Generate JetClass samples for Delphes and Parnassus."""


@cli.group(invoke_without_command=True)
@click.pass_context
def processes(context: click.Context) -> None:
    """List the JetClass processes, or inspect one with ``show``."""
    if context.invoked_subcommand is not None:
        return
    header = f"{'process':<12} {'class':<6} {'model':<22} {'matched':<8} madspin"
    click.echo(header)
    for spec in catalogue().values():
        click.echo(
            f"{spec.name:<12} {spec.label:<6} {spec.model:<22} "
            f"{_yes_no(spec.matching):<8} {_yes_no(spec.madspin)}"
        )


@processes.command("show")
@click.argument("name", type=click.Choice(process_names()))
def processes_show(name: str) -> None:
    """Print the MadGraph inputs the package writes for one process."""
    spec = get_process(name)
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
def check_cards() -> None:
    """Compare the catalogue with the official JetClass gridpack cards."""
    mismatches = compare_all()
    if not mismatches:
        click.echo(f"{len(process_names())} processes match the official cards.")
        return
    for mismatch in mismatches:
        click.echo(str(mismatch), err=True)
    raise SystemExit(1)


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"
