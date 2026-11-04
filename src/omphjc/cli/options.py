"""The click options and argument helpers that several commands share.

A command applies an option in its own decorator stack, which sets the option's
place in the command's ``--help``.
"""

from collections.abc import Mapping
from pathlib import Path

import click

from omphjc.processes import ProcessSpec

Catalogue = Mapping[str, ProcessSpec]

EXISTING_FILE = click.Path(exists=True, dir_okay=False, path_type=Path)

JOB_ID_OPTION = click.option(
    "--job-id",
    "job_id",
    type=int,
    required=True,
    help="Job number; the seed of every program follows from it.",
)
OUTDIR_OPTION = click.option(
    "--outdir",
    "outdir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory holding the jobs of every process.",
)
FORCE_OPTION = click.option(
    "--force", is_flag=True, help="Run the stage again, replacing its outputs."
)
SET_OPTION = click.option(
    "--set",
    "assignments",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override one Pythia setting; may be repeated.",
)


def lookup_process(specs: Catalogue, name: str) -> ProcessSpec:
    """Return the process `name` of the catalogue `specs`.

    Raises
    ------
    click.BadParameter
        If the catalogue has no process `name`; the message lists the ones it has.
    """
    try:
        return specs[name]
    except KeyError:
        known = ", ".join(specs)
        raise click.BadParameter(
            f"unknown process {name!r}; choose from {known}"
        ) from None


def parse_assignment(text: str) -> tuple[str, str]:
    """Return the key and the value of a ``--set KEY=VALUE`` argument, stripped.

    Raises
    ------
    click.BadParameter
        If `text` has no ``=``, or its key or value is empty.
    """
    key, separator, value = text.partition("=")
    if not separator or not key.strip() or not value.strip():
        raise click.BadParameter(
            f"expected KEY=VALUE, got {text!r}", param_hint="--set"
        )
    return key.strip(), value.strip()
