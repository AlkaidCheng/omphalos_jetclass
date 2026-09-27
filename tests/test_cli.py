from pathlib import Path

from click.testing import CliRunner

from omphjc.cli import cli
from omphjc.config_paths import catalogue_path


def test_processes_lists_every_class() -> None:
    result = CliRunner().invoke(cli, ["processes"])
    assert result.exit_code == 0, result.output
    assert "HToBB" in result.output
    assert "ZJetsToNuNu" in result.output
    assert result.output.count("\n") == 11  # header + 10 processes


def test_processes_show_prints_the_scripts() -> None:
    result = CliRunner().invoke(cli, ["processes", "show", "HToWW2Q1L"])
    assert result.exit_code == 0, result.output
    assert "generate p p > ve ve~ h, h > w+ w- > j j lep nu" in result.output
    assert "set ptl 0.1" in result.output
    assert "seed offset: 50000000" in result.output
    assert "models/heft-ckm" in result.output


def test_processes_show_rejects_unknown_names() -> None:
    result = CliRunner().invoke(cli, ["processes", "show", "HToTauTau"])
    assert result.exit_code != 0
    assert "unknown process 'HToTauTau'" in result.output


def test_check_cards_passes_for_the_shipped_catalogue() -> None:
    result = CliRunner().invoke(cli, ["check-cards"])
    assert result.exit_code == 0, result.output
    assert "10 processes match" in result.output


def test_a_custom_catalogue_is_used_by_every_command(tmp_path: Path) -> None:
    shipped = catalogue_path().parent
    text = catalogue_path().read_text(encoding="utf-8")
    text = text.replace("common:\n", f"common:\n  models_dir: {shipped / 'models'}\n")
    text = text.replace("_cards: cards/", f"_cards: {shipped}/cards/")
    text = text.replace("_card: cards/", f"_card: {shipped}/cards/")
    custom = tmp_path / "study.yaml"
    custom.write_text(text.replace("misset: 450.0", "misset: 400.0"), encoding="utf-8")

    listing = CliRunner().invoke(cli, ["--catalogue", str(custom), "processes"])
    assert listing.exit_code == 0, listing.output
    assert listing.output.count("\n") == 11

    check = CliRunner().invoke(cli, ["--catalogue", str(custom), "check-cards"])
    assert check.exit_code == 1
    assert "HToBB: run_card.misset: expected 450.0, got 400.0" in check.output


def test_the_catalogue_can_come_from_the_environment(tmp_path: Path) -> None:
    custom = tmp_path / "one.yaml"
    custom.write_text(
        "processes:\n  Only:\n    label: X\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n    run_card: {}\n    seed_offset: 0\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli, ["processes"], env={"OMPHJC_CATALOGUE": str(custom)}
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("\n") == 2
    assert "Only" in result.output


def test_config_path_and_export(tmp_path: Path) -> None:
    shown = CliRunner().invoke(cli, ["config", "path"])
    assert shown.exit_code == 0
    assert Path(shown.output.strip()).is_dir()

    destination = tmp_path / "config"
    exported = CliRunner().invoke(cli, ["config", "export", str(destination)])
    assert exported.exit_code == 0, exported.output
    assert (destination / "jetclass.yaml").is_file()
    assert (destination / "cards" / "jetclass" / "HToBB" / "run_card.dat").is_file()
    assert (destination / "models" / "heft" / "restrict_ckm.dat").is_file()
    assert not list(destination.rglob("__pycache__"))

    again = CliRunner().invoke(cli, ["config", "export", str(destination)])
    assert again.exit_code != 0
    assert "already exists" in again.output


def test_pythia_show_prints_a_command_file() -> None:
    result = CliRunner().invoke(
        cli, ["pythia", "show", "ZJetsToNuNu", "--events", "50", "--seed", "3"]
    )
    assert result.exit_code == 0, result.output
    assert "Beams:LHEF = events.lhe" in result.output
    assert "Main:numberOfEvents = 50" in result.output
    assert "JetMatching:qCut = 45" in result.output
    assert "Random:seed = 3" in result.output
