"""The import rules between omphjc's layers, checked module by module.

Every module is parsed and its ``omphjc`` imports, at any depth of its code,
are compared with the rules below; the tables of accepted imports are exact, so
an accepted import that no longer occurs fails too and is removed.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import omphjc

PACKAGE_DIR = Path(omphjc.__file__).parent

# Modules any layer may import: they run programs, guard paths, stamp outputs,
# compare values and read ROOT files, and know no catalogue, tool, stage or
# command.
SHARED_MODULES = (
    "omphjc.comparison",
    "omphjc.config_paths",
    "omphjc.filetree",
    "omphjc.programs",
    "omphjc.root_io",
    "omphjc.safe_paths",
    "omphjc.stamps",
    "omphjc.workspace",
)

# The modules omphjc.events may import besides its own: the event-file
# contracts know no tool, stage or command.
EVENTS_IMPORTS = ("omphjc.root_io",)

ARRAY_LIBRARIES = ("awkward", "numpy", "uproot")

# The one import from one tool into another: the shower runs inside a Delphes
# program, which reads the card that keeps the generator record.
CROSS_TOOL_IMPORTS = {
    ("omphjc.tools.pythia.driver", "omphjc.tools.delphes.card"),
}

# The tool modules the jobs layer imports: each stage function calls its tool's
# driver, and a job's seed is checked against Pythia's limit.
JOBS_TOOL_IMPORTS = {
    ("omphjc.jobs.job", "omphjc.tools.pythia.cmnd"),
    ("omphjc.jobs.stages.generate", "omphjc.tools.madgraph.driver"),
    ("omphjc.jobs.stages.shower", "omphjc.tools.pythia.driver"),
    ("omphjc.jobs.stages.simulate", "omphjc.tools.delphes.driver"),
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _parsed_modules() -> dict[str, ast.Module]:
    modules = {}
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if path.relative_to(PACKAGE_DIR).parts[0] == "config":
            continue
        modules[_module_name(path)] = ast.parse(path.read_text(encoding="utf-8"))
    return modules


def _omphjc_imports(tree: ast.Module) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return {name for name in imported if _within(name, "omphjc")}


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


MODULES = _parsed_modules()
IMPORTS = {name: _omphjc_imports(tree) for name, tree in MODULES.items()}
TOOL_PACKAGES = sorted(
    name for name in MODULES if _within(name, "omphjc.tools") and name.count(".") <= 2
)


def _tool_of(module: str) -> str:
    return ".".join(module.split(".")[:3])


def test_modules_use_absolute_imports() -> None:
    relative = sorted(
        name
        for name, tree in MODULES.items()
        if any(
            isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(tree)
        )
    )
    assert relative == []


@pytest.mark.parametrize("package", TOOL_PACKAGES)
def test_tool_packages_import_nothing(package: str) -> None:
    assert IMPORTS[package] == set()


def test_tools_import_no_stage_and_no_command() -> None:
    reaches = {
        (name, target)
        for name, targets in IMPORTS.items()
        if _within(name, "omphjc.tools")
        for target in targets
        if _within(target, "omphjc.jobs") or _within(target, "omphjc.cli")
    }
    assert reaches == set()


def test_a_tool_imports_another_only_where_accepted() -> None:
    crossings = {
        (name, target)
        for name, targets in IMPORTS.items()
        if _within(name, "omphjc.tools")
        for target in targets
        if _within(target, "omphjc.tools") and _tool_of(target) != _tool_of(name)
    }
    assert crossings == CROSS_TOOL_IMPORTS


def test_shared_modules_and_the_catalogue_import_no_tool_stage_or_command() -> None:
    importers = [
        name
        for name in IMPORTS
        if name in SHARED_MODULES or _within(name, "omphjc.processes")
    ]
    reaches = {
        (name, target)
        for name in importers
        for target in IMPORTS[name]
        if any(
            _within(target, layer)
            for layer in ("omphjc.tools", "omphjc.jobs", "omphjc.cli")
        )
    }
    assert reaches == set()


def test_shared_modules_import_no_catalogue() -> None:
    reaches = {
        (name, target)
        for name in SHARED_MODULES
        for target in IMPORTS[name]
        if _within(target, "omphjc.processes")
    }
    assert reaches == set()


def test_the_event_files_import_nothing_but_their_own_and_root_io() -> None:
    reaches = {
        (name, target)
        for name, targets in IMPORTS.items()
        if _within(name, "omphjc.events")
        for target in targets
        if not _within(target, "omphjc.events") and target not in EVENTS_IMPORTS
    }
    assert reaches == set()


def test_the_jobs_layer_imports_no_command() -> None:
    reaches = {
        (name, target)
        for name, targets in IMPORTS.items()
        if _within(name, "omphjc.jobs")
        for target in targets
        if _within(target, "omphjc.cli")
    }
    assert reaches == set()


def test_the_jobs_layer_imports_tools_only_where_accepted() -> None:
    reaches = {
        (name, target)
        for name, targets in IMPORTS.items()
        if _within(name, "omphjc.jobs")
        for target in targets
        if _within(target, "omphjc.tools")
    }
    assert reaches == JOBS_TOOL_IMPORTS


def _loaded_after(statement: str) -> set[str]:
    """Return the modules a fresh interpreter holds after running `statement`."""
    code = f"import sys\n{statement}\nprint('\\n'.join(sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    )
    return set(result.stdout.split())


def test_importing_the_tools_package_loads_no_tool() -> None:
    loaded = _loaded_after("import omphjc.tools")
    assert {name for name in loaded if _within(name, "omphjc.tools")} == {
        "omphjc.tools"
    }


@pytest.mark.parametrize("module", ["omphjc.events", "omphjc.events.formats"])
def test_the_event_file_contracts_load_no_array_library(module: str) -> None:
    loaded = _loaded_after(f"import {module}")
    assert {name for name in loaded if name.split(".")[0] in ARRAY_LIBRARIES} == set()


def test_a_tool_module_loads_no_driver_and_no_other_tool() -> None:
    loaded = _loaded_after("import omphjc.tools.madgraph.run_card")
    tools = {name for name in loaded if _within(name, "omphjc.tools")}
    assert tools == {
        "omphjc.tools",
        "omphjc.tools.madgraph",
        "omphjc.tools.madgraph.run_card",
    }
