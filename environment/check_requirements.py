"""Check that every requirement reachable from the given distributions holds.

conda installs most of an environment and checks only what conda-forge's
packages declare, so this script checks the requirements as pip reads them. It
reads the declared requirements of each root distribution, of each optional root
when it is installed, and of every distribution they reach, evaluates their
markers for this interpreter and does not follow extras. Distributions they do
not reach are not read, so other packages in a shared environment cannot fail
the check. The roots are omphjc and, when installed, Parnassus, unless
``--root`` or ``--optional-root`` names others.

An accepted conflict is a requirement that may fail, named by its holder and
the project it requires. The accepted conflicts are kept in
``ACCEPTED_CONFLICTS``, each with the upstream source that declares it, and
``--accept HOLDER:NAME`` adds one for a single run. An accepted conflict whose
holder is checked and that no longer occurs fails the check, so its entry is
removed rather than hiding a later conflict.

Usage::

    python check_requirements.py [--root NAME ...] [--optional-root NAME ...]
                                 [--accept HOLDER:NAME ...]

The script prints each requirement that does not hold and exits with status 1,
or exits with status 0 when all hold.
"""

import argparse
import sys
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion

# The distributions whose requirements are checked, with every distribution
# they reach; the optional ones only when they are installed.
ROOTS = ("omphjc",)
OPTIONAL_ROOTS = ("parnassus",)

# Requirements that may fail, as (holder, required project) pairs, each citing
# the upstream file that declares it.
ACCEPTED_CONFLICTS: tuple[tuple[str, str], ...] = ()

# Markers are evaluated without an extra, so requirements behind one are skipped.
_MARKER_ENVIRONMENT = {"extra": ""}


@dataclass(frozen=True)
class Distribution:
    """An installed distribution: its version and declared requirements."""

    version: str
    requires: tuple[str, ...]


def read_installed_distribution(name: str) -> Distribution | None:
    """Return the distribution called `name` installed in this environment."""
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    return Distribution(distribution.version, tuple(distribution.requires or ()))


def find_problems(
    lookup: Callable[[str], Distribution | None],
    *,
    roots: Iterable[str] = ROOTS,
    optional_roots: Iterable[str] = OPTIONAL_ROOTS,
    accepted: Iterable[tuple[str, str]] = ACCEPTED_CONFLICTS,
) -> list[str]:
    """Return one line for each requirement that does not hold.

    Parameters
    ----------
    lookup : callable
        Returns the installed distribution of a project name, or ``None``.
    roots : iterable of str, optional
        Projects whose requirements are checked; each must be installed.
    optional_roots : iterable of str, optional
        Projects whose requirements are checked when they are installed.
    accepted : iterable of (str, str), optional
        Requirements that may fail, as (holder, required project) pairs.

    Returns
    -------
    list of str
        The requirements that do not hold, then the accepted conflicts of a
        checked holder that no longer occur.
    """
    accepted_pairs = {
        (canonicalize_name(holder), canonicalize_name(name))
        for holder, name in accepted
    }
    installed, problems = _installed_roots(lookup, roots, optional_roots)
    queue = deque(installed)
    checked = {canonicalize_name(name) for name, _ in queue}
    failing: set[tuple[str, str]] = set()
    while queue:
        holder, distribution = queue.popleft()
        requirements, invalid = _applicable_requirements(holder, distribution)
        problems.extend(invalid)
        for requirement in requirements:
            pair = (canonicalize_name(holder), canonicalize_name(requirement.name))
            dependency = lookup(requirement.name)
            problem = _unmet(holder, distribution, requirement, dependency)
            if problem is not None:
                failing.add(pair)
                if pair not in accepted_pairs:
                    problems.append(problem)
            if dependency is not None and pair[1] not in checked:
                checked.add(pair[1])
                queue.append((requirement.name, dependency))
    problems.extend(
        f"the accepted conflict of {holder} with {name} no longer occurs; "
        "remove it from ACCEPTED_CONFLICTS"
        for holder, name in sorted(accepted_pairs - failing)
        if holder in checked
    )
    return problems


def _installed_roots(
    lookup: Callable[[str], Distribution | None],
    roots: Iterable[str],
    optional_roots: Iterable[str],
) -> tuple[list[tuple[str, Distribution]], list[str]]:
    """Return the installed roots, and a line for each required one missing."""
    installed: list[tuple[str, Distribution]] = []
    missing: list[str] = []
    for name in roots:
        distribution = lookup(name)
        if distribution is None:
            missing.append(f"{name} is not installed")
        else:
            installed.append((name, distribution))
    for name in optional_roots:
        distribution = lookup(name)
        if distribution is not None:
            installed.append((name, distribution))
    return installed, missing


def _applicable_requirements(
    holder: str, distribution: Distribution
) -> tuple[list[Requirement], list[str]]:
    """Return the requirements of `holder` whose markers hold here, and the invalid ones."""
    requirements: list[Requirement] = []
    invalid: list[str] = []
    for line in distribution.requires:
        try:
            requirement = Requirement(line)
        except InvalidRequirement as error:
            invalid.append(f"{holder} declares an invalid requirement: {error}")
            continue
        if requirement.marker is None or requirement.marker.evaluate(
            _MARKER_ENVIRONMENT
        ):
            requirements.append(requirement)
    return requirements, invalid


def _unmet(
    holder: str,
    distribution: Distribution,
    requirement: Requirement,
    required: Distribution | None,
) -> str | None:
    """Return why `requirement` of `holder` does not hold, or ``None``."""
    stated = f"{holder} {distribution.version} requires {requirement}"
    if required is None:
        return f"{stated}, but {requirement.name} is not installed"
    if requirement.url:
        return None
    try:
        holds = requirement.specifier.contains(required.version, prereleases=True)
    except InvalidVersion:
        holds = False
    if holds:
        return None
    return f"{stated}, but {requirement.name} {required.version} is installed"


def _accepted_pair(text: str) -> tuple[str, str]:
    holder, separator, name = text.partition(":")
    if not separator or not holder or not name:
        raise argparse.ArgumentTypeError(f"expected HOLDER:NAME, got {text!r}")
    return holder, name


def main(argv: Sequence[str] | None = None) -> int:
    """Check the environment, print each problem and return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="NAME",
        help="check NAME, which must be installed; naming a root or an optional "
        f"root replaces the defaults ({', '.join(ROOTS)}, and "
        f"{', '.join(OPTIONAL_ROOTS)} when installed)",
    )
    parser.add_argument(
        "--optional-root",
        action="append",
        default=[],
        metavar="NAME",
        help="check NAME when it is installed",
    )
    parser.add_argument(
        "--accept",
        action="append",
        default=[],
        type=_accepted_pair,
        metavar="HOLDER:NAME",
        help="also accept a failing requirement of HOLDER on NAME for this run",
    )
    arguments = parser.parse_args(argv)
    if arguments.root or arguments.optional_root:
        roots, optional_roots = arguments.root, arguments.optional_root
    else:
        roots, optional_roots = list(ROOTS), list(OPTIONAL_ROOTS)
    problems = find_problems(
        read_installed_distribution,
        roots=roots,
        optional_roots=optional_roots,
        accepted=(*ACCEPTED_CONFLICTS, *arguments.accept),
    )
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("Every checked requirement holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
