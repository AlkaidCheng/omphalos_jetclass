from collections.abc import Mapping
from pathlib import Path

from omphjc.config_paths import config_dir
from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.cards import proc_card_commands
from omphjc.tools.madgraph.proc_card import ProcCard

REFERENCES_DIR = config_dir() / "references" / "jetclass"

CARD = """\
# the model
import model  /models/heft_c_mass --modelname   # with its own particle names
define p = g u c d s b u~ c~ d~ s~ b~

generate p p > h, h > b b~
output /jobs/1/generate/HToBB -f
"""


def test_a_process_card_holds_its_commands_without_comments_or_extra_spaces() -> None:
    assert ProcCard.from_text(CARD).commands == (
        "import model /models/heft_c_mass --modelname",
        "define p = g u c d s b u~ c~ d~ s~ b~",
        "generate p p > h, h > b b~",
        "output /jobs/1/generate/HToBB -f",
    )


def test_a_command_on_several_lines_is_one_command() -> None:
    wrapped = CARD.replace("heft_c_mass", "heft_\\\nc_mass").replace(
        "HToBB -f", "HToBB \\  \n-f"
    )
    assert "\\\n" in wrapped
    assert ProcCard.from_text(wrapped) == ProcCard.from_text(CARD)


def test_the_content_record_keeps_the_last_part_of_each_path() -> None:
    assert ProcCard.from_text(CARD).content_record() == [
        "import model heft_c_mass --modelname",
        "define p = g u c d s b u~ c~ d~ s~ b~",
        "generate p p > h, h > b b~",
        "output HToBB -f",
    ]


def test_cards_written_for_two_job_directories_have_one_fingerprint(
    specs: Mapping[str, ProcessSpec], tmp_path: Path
) -> None:
    first, second = (
        ProcCard.from_text(
            "\n".join(
                proc_card_commands(specs["HToBB"], output_dir=tmp_path / job / "HToBB")
            )
        )
        for job in ("1", "2")
    )
    assert first.commands != second.commands
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint().startswith("proc_card-v1:")


def test_another_process_changes_the_fingerprint() -> None:
    card = ProcCard.from_text(CARD)
    other = ProcCard.from_text(CARD.replace("h > b b~", "h > c c~"))
    assert other.fingerprint() != card.fingerprint()


def test_cards_that_differ_only_in_directories_have_no_differences() -> None:
    card = ProcCard.from_text(CARD)
    moved = ProcCard.from_text(CARD.replace("/jobs/1/", "/jobs/2/"))
    assert moved.differences(card) == []


def test_another_process_is_reported_with_every_command() -> None:
    reference = ProcCard.from_text("import model sm\ngenerate p p > t t~\n")
    card = ProcCard.from_text("import model sm\ngenerate p p > z j\n")
    assert [str(difference) for difference in card.differences(reference)] == [
        "commands: expected import model sm | generate p p > t t~, "
        "got import model sm | generate p p > z j"
    ]


def test_a_process_card_is_read_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "proc_card_mg5.dat"
    path.write_text(CARD, encoding="utf-8")
    assert ProcCard.read(path) == ProcCard.from_text(CARD)


def test_the_official_card_holds_the_definition_of_the_process() -> None:
    assert ProcCard.reference(REFERENCES_DIR / "HToBB").commands == (
        "import model heft",
        "define p = p b b~",
        "define j = j b b~",
        "generate p p > ve ve~ h, h > b b~",
    )


def test_an_official_card_without_a_model_loads_the_standard_model() -> None:
    card = ProcCard.reference(REFERENCES_DIR / "ZJetsToNuNu")
    assert card.commands[0] == "import model sm"


def test_the_model_of_an_official_card_has_its_catalogue_name() -> None:
    card = ProcCard.reference(REFERENCES_DIR / "HToCC")
    assert card.commands[0] == "import model heft_c_mass_jetclass"


def test_the_card_of_a_process_holds_its_definition_without_the_output(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert ProcCard.from_process(specs["HToBB"]).commands == (
        "import model heft",
        "define p = p b b~",
        "define j = j b b~",
        "generate p p > ve ve~ h, h > b b~",
    )
