"""Write the MadGraph inputs for one process.

Two scripts drive MadGraph: the process script (``import model``, the
multiparticle definitions, ``generate`` and ``output``) and the launch script
(``launch`` with the run switches and the ``set`` lines that pin the run-card
values). The MadSpin card is shipped verbatim from the official production.
"""

from pathlib import Path

from omphjc.config_paths import VENDORED_MODELS, reference_dir
from omphjc.madgraph.runcard import format_value
from omphjc.processes.catalogue import ProcessSpec

STANDARD_DEFINITIONS: tuple[str, ...] = ("p = p b b~", "j = j b b~")
"""Five-flavour proton and jet definitions shared by every JetClass process."""


def model_import_target(spec: ProcessSpec, *, models_dir: Path) -> str:
    """Return the argument of ``import model`` for `spec`.

    Vendored models are imported by path so that MadGraph never downloads
    them; the restriction suffix, if any, is kept.
    """
    if spec.model_base not in VENDORED_MODELS:
        return spec.model
    target = str(models_dir / spec.model_base)
    if spec.model_restriction:
        target = f"{target}-{spec.model_restriction}"
    return target


def proc_card_commands(
    spec: ProcessSpec, *, output_dir: Path, models_dir: Path
) -> list[str]:
    """Return the MadGraph commands that define and output the process.

    Parameters
    ----------
    spec : ProcessSpec
        The process to define.
    output_dir : Path
        Directory MadGraph writes the process into (``output`` argument).
    models_dir : Path
        Directory holding the vendored UFO models.
    """
    commands = [f"import model {model_import_target(spec, models_dir=models_dir)}"]
    commands.extend(f"define {item}" for item in STANDARD_DEFINITIONS)
    commands.extend(f"define {item}" for item in spec.definitions)
    first, *rest = spec.processes
    commands.append(f"generate {first}")
    commands.extend(f"add process {process}" for process in rest)
    commands.append(f"output {output_dir}")
    return commands


def launch_commands(
    spec: ProcessSpec, *, process_dir: Path, n_events: int, seed: int | None
) -> list[str]:
    """Return the MadGraph commands that generate events for `spec`.

    Parameters
    ----------
    spec : ProcessSpec
        The process to run.
    process_dir : Path
        Directory produced by the process script's ``output``.
    n_events : int
        Number of events to generate.
    seed : int or None
        MadGraph ``iseed``; ``None`` lets MadGraph pick one at random.

    Returns
    -------
    list[str]
        The shower and detector switches are off because Pythia and Delphes
        run afterwards through ``DelphesPythia8``; MadSpin is on only for the
        processes that ship a MadSpin card.
    """
    if n_events <= 0:
        raise ValueError(f"n_events must be positive, got {n_events}")
    commands = [
        f"launch {process_dir}",
        "shower=OFF",
        "detector=OFF",
        "madspin=ON" if spec.madspin else "madspin=OFF",
        "done",
        f"set nevents {n_events}",
        f"set iseed {0 if seed is None else seed}",
    ]
    commands.extend(
        f"set {name} {format_value(value)}" for name, value in spec.run_card.items()
    )
    commands.append("done")
    return commands


def madspin_card_text(spec: ProcessSpec) -> str:
    """Return the official MadSpin card for `spec`.

    Raises
    ------
    ValueError
        If the process does not use MadSpin.
    """
    if not spec.madspin:
        raise ValueError(f"Process {spec.name!r} does not use MadSpin")
    return (reference_dir(spec.name) / "madspin_card.dat").read_text(encoding="utf-8")
