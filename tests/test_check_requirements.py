import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from packaging.utils import canonicalize_name

SCRIPT_PATH = Path(__file__).parents[1] / "environment" / "check_requirements.py"


@pytest.fixture(scope="module")
def check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_requirements", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEnvironment:
    """Installed distributions by project name; records every name it is asked for."""

    def __init__(
        self,
        check: ModuleType,
        distributions: Mapping[str, tuple[str, tuple[str, ...]]],
    ) -> None:
        self._installed = {
            canonicalize_name(name): check.Distribution(version, requires)
            for name, (version, requires) in distributions.items()
        }
        self.read: list[str] = []

    def __call__(self, name: str) -> Any:
        self.read.append(canonicalize_name(name))
        return self._installed.get(canonicalize_name(name))


def test_requirements_that_hold_give_no_problem(check: ModuleType) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("click>=8.1", "PyYAML>=6.0")),
            "click": ("8.2.1", ()),
            "pyyaml": ("6.0.3", ()),
        },
    )
    assert check.find_problems(lookup) == []


def test_an_unmet_requirement_and_a_missing_distribution_are_reported(
    check: ModuleType,
) -> None:
    lookup = FakeEnvironment(
        check, {"omphjc": ("0.1", ("click>=9", "uproot>=5.7")), "click": ("8.2.1", ())}
    )
    assert check.find_problems(lookup) == [
        "omphjc 0.1 requires click>=9, but click 8.2.1 is installed",
        "omphjc 0.1 requires uproot>=5.7, but uproot is not installed",
    ]


def test_a_requirement_reached_through_another_distribution_is_checked(
    check: ModuleType,
) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("awkward>=2.8.2",)),
            "awkward": ("2.9.1", ("awkward_cpp==51",)),
            "awkward-cpp": ("50", ()),
        },
    )
    assert check.find_problems(lookup) == [
        "awkward 2.9.1 requires awkward_cpp==51, but awkward_cpp 50 is installed"
    ]


def test_requirements_excluded_by_a_marker_or_behind_an_extra_are_not_checked(
    check: ModuleType,
) -> None:
    requires = ('tomli>=2; python_version < "3.0"', 'pytest>=99; extra == "dev"')
    lookup = FakeEnvironment(check, {"omphjc": ("0.1", requires)})
    assert check.find_problems(lookup) == []
    assert "tomli" not in lookup.read and "pytest" not in lookup.read


def test_a_missing_omphjc_is_reported_and_a_missing_parnassus_is_not(
    check: ModuleType,
) -> None:
    assert check.find_problems(FakeEnvironment(check, {})) == [
        "omphjc is not installed"
    ]


def test_parnassus_is_checked_when_it_is_installed(check: ModuleType) -> None:
    lookup = FakeEnvironment(
        check, {"omphjc": ("0.1", ()), "parnassus": ("0.0.1", ("torch",))}
    )
    assert check.find_problems(lookup) == [
        "parnassus 0.0.1 requires torch, but torch is not installed"
    ]


def test_an_accepted_conflict_passes(check: ModuleType) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("uproot>=5.7",)),
            "parnassus": ("0.0.1", ("uproot<5.6.7,>=5.5.2", "pythia8mc==8.316.0")),
            "uproot": ("5.7.4", ()),
        },
    )
    accepted = [("parnassus", "uproot"), ("Parnassus", "pythia8mc")]
    assert check.find_problems(lookup, accepted=accepted) == []


def test_an_accepted_conflict_that_no_longer_occurs_fails(check: ModuleType) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("uproot>=5.7",)),
            "parnassus": ("0.0.2", ("uproot>=5.7",)),
            "uproot": ("5.7.4", ()),
        },
    )
    assert check.find_problems(lookup, accepted=[("parnassus", "uproot")]) == [
        "the accepted conflict of parnassus with uproot no longer occurs; "
        "remove it from ACCEPTED_CONFLICTS"
    ]


def test_an_accepted_conflict_whose_holder_is_not_installed_does_not_apply(
    check: ModuleType,
) -> None:
    lookup = FakeEnvironment(check, {"omphjc": ("0.1", ())})
    assert check.find_problems(lookup, accepted=[("parnassus", "uproot")]) == []


def test_a_distribution_not_reachable_from_omphjc_is_not_read(
    check: ModuleType,
) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("click>=8.1",)),
            "click": ("8.2.1", ()),
            "unrelated": ("1.0", ("missing-project",)),
        },
    )
    assert check.find_problems(lookup) == []
    assert "unrelated" not in lookup.read


def test_main_prints_each_problem_and_fails_unless_it_is_accepted(
    check: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lookup = FakeEnvironment(
        check, {"omphjc": ("0.1", ("click>=9",)), "click": ("8.2.1", ())}
    )
    monkeypatch.setattr(check, "read_installed_distribution", lookup)
    assert check.main([]) == 1
    assert capsys.readouterr().out == (
        "omphjc 0.1 requires click>=9, but click 8.2.1 is installed\n"
    )
    assert check.main(["--accept", "omphjc:click"]) == 0
    with pytest.raises(SystemExit):
        check.main(["--accept", "omphjc"])


def test_naming_a_root_replaces_the_default_roots(
    check: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lookup = FakeEnvironment(
        check,
        {
            "omphjc": ("0.1", ("click>=9",)),
            "click": ("8.2.1", ()),
            "parnassus": ("0.1.0", ("uproot<5",)),
            "other-tool": ("2.0", ("click>=8",)),
        },
    )
    monkeypatch.setattr(check, "read_installed_distribution", lookup)
    assert check.main(["--root", "other-tool"]) == 0
    assert capsys.readouterr().out == "Every checked requirement holds.\n"
    assert "omphjc" not in lookup.read and "parnassus" not in lookup.read
    assert check.main(["--optional-root", "absent"]) == 0
