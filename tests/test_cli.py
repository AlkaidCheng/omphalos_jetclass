import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from omphjc.cli import cli
from omphjc.config_paths import export_config

RUN_ROW = re.compile(r"  run ID            (\d{8}T\d{6}Z-[0-9a-f]{8})")


def _run_id(line: str) -> str:
    """Return the run ID in the report row `line`, which must be the run row."""
    match = RUN_ROW.fullmatch(line)
    assert match is not None, line
    return match.group(1)


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


def test_check_cards_passes_for_the_default_catalogue() -> None:
    result = CliRunner().invoke(cli, ["check-cards"])
    assert result.exit_code == 0, result.output
    assert "10 processes match" in result.output


def test_a_custom_catalogue_is_used_by_every_command(tmp_path: Path) -> None:
    custom = export_config(tmp_path / "config") / "jetclass.yaml"
    text = custom.read_text(encoding="utf-8")
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


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("processes: [unclosed\n", "expected ',' or ']', but got '<stream end>'"),
        (
            "common:\n  definitions: p = g u d\nprocesses: {}\n",
            "common: definitions must be a list of strings, got 'p = g u d'",
        ),
    ],
)
def test_a_malformed_catalogue_is_reported_as_an_error(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text(text, encoding="utf-8")
    result = CliRunner().invoke(cli, ["--catalogue", str(path), "processes"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert result.output.startswith(f"Error: Catalogue {path}: ")
    assert message in result.output


def test_config_path_and_export(tmp_path: Path) -> None:
    shown = CliRunner().invoke(cli, ["config", "path"])
    assert shown.exit_code == 0
    assert Path(shown.output.strip()).is_dir()

    destination_dir = tmp_path / "config"
    exported = CliRunner().invoke(cli, ["config", "export", str(destination_dir)])
    assert exported.exit_code == 0, exported.output
    assert (destination_dir / "jetclass.yaml").is_file()
    assert (
        destination_dir / "references" / "jetclass" / "HToBB" / "run_card.dat"
    ).is_file()
    assert (destination_dir / "madspin" / "TTBar.dat").is_file()
    assert (destination_dir / "models" / "heft" / "restrict_ckm.dat").is_file()
    assert not list(destination_dir.rglob("__pycache__"))

    again = CliRunner().invoke(cli, ["config", "export", str(destination_dir)])
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
    overridden = CliRunner().invoke(
        cli, ["pythia", "show", "HToBB", "--set", "Check:epTolErr=0.1"]
    )
    assert overridden.exit_code == 0, overridden.output
    assert "Check:epTolErr = 0.1" in overridden.output
    assert (
        CliRunner().invoke(cli, ["pythia", "show", "HToBB", "--set", "x"]).exit_code
        != 0
    )


def test_generate_runs_a_job_and_keeps_a_finished_one(
    mg5_path: Path, tmp_path: Path
) -> None:
    arguments = ["generate", "HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    result = CliRunner().invoke(
        cli, [*arguments, "--events", "10", "--mg5", str(mg5_path)]
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("HToBB job 1: ") and lines[0].endswith("HToBB/job_1")
    assert lines[1] == "MadGraph generation: done"
    run_id = _run_id(lines[2])
    assert lines[3] == "  MadGraph 3.5.7, seed 10000001"
    assert lines[4] == "  events requested  10"
    assert lines[5] == "  events generated  10000"
    assert lines[6] == "  cross section     1.05282 +- 0.0024 pb"
    assert lines[7].startswith("  event file        generate/HToBB/Events/")
    assert lines[8] == f"  log               generate/runs/{run_id}/madgraph.log"
    assert lines[9] == "  cards             generate/cards/"
    assert lines[10].startswith("  took              ") and "s wall" in lines[10]
    assert "s CPU" in lines[10] and "MiB peak" in lines[10]
    job_dir = tmp_path / "HToBB" / "job_1"
    record_paths = [job_dir / "generate" / "task.json", job_dir / "manifest.json"]
    written = [path.read_text() for path in record_paths]
    again = CliRunner().invoke(
        cli, [*arguments, "--events", "10", "--mg5", str(mg5_path)]
    )
    assert again.exit_code == 0, again.output
    assert "MadGraph generation: done, kept from an earlier run" in again.output
    assert [path.read_text() for path in record_paths] == written

    other_count = CliRunner().invoke(cli, [*arguments, "--events", "20"])
    assert other_count.exit_code != 0
    assert "  events: expected 10, got 20\n" in other_count.output
    assert (
        CliRunner()
        .invoke(cli, [*arguments, "--events", "10", "--job-id", "0"])
        .exit_code
        != 0
    )


def test_a_report_counts_the_runs_of_a_rerun_task(
    mg5_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = ["generate", "HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    arguments += ["--events", "10", "--mg5", str(mg5_path)]
    monkeypatch.setenv("FAKE_MG5_FAIL", "launch")
    assert CliRunner().invoke(cli, arguments).exit_code != 0
    monkeypatch.delenv("FAKE_MG5_FAIL")
    rerun = CliRunner().invoke(cli, arguments)
    assert rerun.exit_code == 0, rerun.output
    lines = rerun.output.splitlines()
    assert lines[10] == "  runs              2 (failed, done)"
    assert lines[11].startswith("  took              ")


def test_shower_runs_after_generate_and_reports(
    mg5_path: Path, delphes_pythia8_path: Path, tmp_path: Path
) -> None:
    job = ["HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    shower = ["shower", *job, "--delphes-pythia8", str(delphes_pythia8_path)]
    missing = CliRunner().invoke(cli, shower)
    assert missing.exit_code != 0
    assert "run omphjc generate first" in missing.output
    generated = CliRunner().invoke(
        cli, ["generate", *job, "--events", "10", "--mg5", str(mg5_path)]
    )
    assert generated.exit_code == 0, generated.output
    result = CliRunner().invoke(cli, shower)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("HToBB job 1: ")
    assert lines[1] == "Pythia shower: done"
    run_id = _run_id(lines[2])
    assert lines[3] == "  Pythia 8.318, seed 10000001"
    assert lines[4] == "  events read       1"
    assert lines[5] == "  events kept       1"
    assert lines[6] == "  output            shower/particles.root"
    assert lines[7] == f"  log               shower/runs/{run_id}/shower.log"
    assert (
        lines[8] == "  settings          shower/pythia.cmnd, shower/particles_card.tcl"
    )
    assert lines[9].startswith("  took              ") and "s wall" in lines[9]
    again = CliRunner().invoke(cli, shower)
    assert again.exit_code == 0, again.output
    assert "Pythia shower: done, kept from an earlier run" in again.output


def test_clean_deletes_what_earlier_runs_set_aside(
    mg5_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import omphjc.workspace as workspace

    job = ["HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    generate = ["generate", *job, "--events", "10", "--mg5", str(mg5_path)]
    with monkeypatch.context() as killed_before_sealing:
        killed_before_sealing.setattr(workspace, "seal", lambda *_: None)
        assert CliRunner().invoke(cli, generate).exit_code == 0
    rerun = CliRunner().invoke(cli, [*generate, "--force"])
    assert rerun.exit_code == 0, rerun.output
    assert "  set aside         1 folder left by earlier runs" in rerun.output
    assert "omphjc clean --set-aside deletes them" in rerun.output

    unnamed = CliRunner().invoke(cli, ["clean", *job])
    assert unnamed.exit_code != 0 and "Name what to delete" in unnamed.output
    listed = CliRunner().invoke(cli, ["clean", *job, "--set-aside", "--dry-run"])
    assert listed.exit_code == 0, listed.output
    assert "set aside: would delete 1 folder, " in listed.output
    assert "generate/omphjc-set-aside/" in listed.output
    cleaned = CliRunner().invoke(cli, ["clean", *job, "--set-aside"])
    assert cleaned.exit_code == 0, cleaned.output
    assert "set aside: deleted 1 folder, " in cleaned.output
    set_aside = tmp_path / "HToBB" / "job_1" / "generate" / "omphjc-set-aside"
    assert not set_aside.exists()
    again = CliRunner().invoke(cli, ["clean", *job, "--set-aside"])
    assert again.exit_code == 0 and again.output.endswith("set aside: nothing\n")


def test_simulate_runs_after_shower_and_reports(
    mg5_path: Path, delphes_pythia8_path: Path, delphes_root_path: Path, tmp_path: Path
) -> None:
    job = ["HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    simulate = ["simulate", *job, "--delphes-root", str(delphes_root_path)]
    missing = CliRunner().invoke(cli, simulate)
    assert missing.exit_code != 0
    assert "run omphjc shower first" in missing.output
    assert (
        CliRunner()
        .invoke(cli, ["generate", *job, "--events", "10", "--mg5", str(mg5_path)])
        .exit_code
        == 0
    )
    assert (
        CliRunner()
        .invoke(cli, ["shower", *job, "--delphes-pythia8", str(delphes_pythia8_path)])
        .exit_code
        == 0
    )
    result = CliRunner().invoke(cli, simulate)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("HToBB job 1: ")
    assert lines[1] == "Delphes simulation: done"
    run_id = _run_id(lines[2])
    assert lines[3] == "  card              simulate/delphes_card.tcl"
    assert lines[4] == "  seed              10000001"
    assert lines[5] == "  events            1"
    assert lines[6] == "  output            simulate/delphes.root"
    assert lines[7] == f"  log               simulate/runs/{run_id}/simulate.log"
    assert lines[8].startswith("  took              ") and "s wall" in lines[8]
    again = CliRunner().invoke(cli, simulate)
    assert again.exit_code == 0, again.output
    assert "Delphes simulation: done, kept from an earlier run" in again.output


def test_accept_input_keeps_a_shower_whose_events_changed(
    mg5_path: Path,
    delphes_pythia8_path: Path,
    delphes_root_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = ["HToBB", "--job-id", "1", "--outdir", str(tmp_path)]
    generate = ["generate", *job, "--events", "10", "--mg5", str(mg5_path)]
    shower = ["shower", *job, "--delphes-pythia8", str(delphes_pythia8_path)]
    simulate = ["simulate", *job, "--delphes-root", str(delphes_root_path)]
    assert CliRunner().invoke(cli, generate).exit_code == 0
    first = CliRunner().invoke(cli, [*shower, "--accept-input"])
    assert first.exit_code == 0, first.output
    assert first.output.splitlines()[1] == "Pythia shower: done"
    assert "  input  " not in first.output
    assert CliRunner().invoke(cli, simulate).exit_code == 0
    monkeypatch.setenv("FAKE_MG5_EVENTS", "2")
    assert CliRunner().invoke(cli, [*generate, "--force"]).exit_code == 0

    refused = CliRunner().invoke(cli, shower)
    assert refused.exit_code != 0
    assert "input_fingerprint: expected lhe-v1:" in refused.output
    conflicting = CliRunner().invoke(cli, [*shower, "--accept-input", "--force"])
    assert conflicting.exit_code == 2
    assert "--accept-input and --force cannot be used together." in conflicting.output

    accepted = CliRunner().invoke(cli, [*shower, "--accept-input"])
    assert accepted.exit_code == 0, accepted.output
    assert "Pythia shower: done, kept from an earlier run" in accepted.output
    input_row = re.compile(
        r"  input             accepted \(ran on lhe-v1:[0-9a-f]{8}\.\.\., "
        r"accepted for lhe-v1:[0-9a-f]{8}\.\.\.\)"
    )
    assert any(input_row.fullmatch(line) for line in accepted.output.splitlines())
    again = CliRunner().invoke(cli, shower)
    assert again.exit_code == 0, again.output
    assert "  input             accepted (ran on" in again.output
    kept = CliRunner().invoke(cli, simulate)
    assert kept.exit_code == 0, kept.output
    assert "Delphes simulation: done, kept from an earlier run" in kept.output
    assert "  input  " not in kept.output

    monkeypatch.delenv("FAKE_MG5_EVENTS")
    assert CliRunner().invoke(cli, [*generate, "--force"]).exit_code == 0
    original = CliRunner().invoke(cli, shower)
    assert original.exit_code == 0, original.output
    assert "Pythia shower: done, kept from an earlier run" in original.output
    assert "  input  " not in original.output
