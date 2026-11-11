from collections.abc import Mapping
from pathlib import Path

from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.cards import proc_card_commands
from omphjc.tools.madgraph.proc_card import ProcCard

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
    assert first.fingerprint().startswith("proc-card-v1:")


def test_another_process_changes_the_fingerprint() -> None:
    card = ProcCard.from_text(CARD)
    other = ProcCard.from_text(CARD.replace("h > b b~", "h > c c~"))
    assert other.fingerprint() != card.fingerprint()


def test_a_process_card_is_read_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "proc_card_mg5.dat"
    path.write_text(CARD, encoding="utf-8")
    assert ProcCard.read(path) == ProcCard.from_text(CARD)
