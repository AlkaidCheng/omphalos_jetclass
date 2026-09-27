from click.testing import CliRunner

from omphjc.cli import cli


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


def test_processes_show_rejects_unknown_names() -> None:
    result = CliRunner().invoke(cli, ["processes", "show", "HToTauTau"])
    assert result.exit_code != 0


def test_check_cards_passes_for_the_packaged_catalogue() -> None:
    result = CliRunner().invoke(cli, ["check-cards"])
    assert result.exit_code == 0, result.output
    assert "10 processes match" in result.output
