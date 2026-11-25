from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.config_paths import config_dir
from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.cards import proc_card_commands
from omphjc.tools.madgraph.proc_card import ProcCard

REFERENCES_DIR = config_dir() / "references" / "jetclass"

FIVE_FLAVOURS = "g u c d s u~ c~ d~ s~ b b~"

# The commands at the top of every official card.
LEADING_COMMANDS = (
    "import model sm",
    "define p = g u c d s u~ c~ d~ s~",
    "define j = g u c d s u~ c~ d~ s~",
    "define l+ = e+ mu+",
    "define l- = e- mu-",
    "define vl = ve vm vt",
    "define vl~ = ve~ vm~ vt~",
)

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
        *LEADING_COMMANDS,
        "import model heft",
        "define p = p b b~",
        "define j = j b b~",
        "generate p p > ve ve~ h, h > b b~",
    )


def test_the_model_of_an_official_card_has_its_catalogue_name() -> None:
    card = ProcCard.reference(REFERENCES_DIR / "HToCC")
    assert card.commands[len(LEADING_COMMANDS)] == ("import model heft_c_mass_jetclass")


def test_the_card_of_a_process_holds_its_definition_without_the_output(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert ProcCard.from_process(specs["HToBB"]).commands == (
        "import model heft",
        f"define p = {FIVE_FLAVOURS}",
        f"define j = {FIVE_FLAVOURS}",
        "generate p p > ve ve~ h, h > b b~",
    )


def test_the_multiparticles_of_a_card_are_those_after_its_last_command() -> None:
    card = ProcCard.from_text(
        "import model sm\ndefine p = g u d\ndefine p = p b b~  # with b\n"
        "generate p p > t t~\ndefine j=p\n"
    )
    assert card.multiparticles().definitions() == [
        "p = g u d b b~",
        "j = g u d b b~",
    ]


def test_a_card_without_definitions_has_no_multiparticles() -> None:
    card = ProcCard.from_text("import model sm\ngenerate g g > t t~\n")
    assert card.multiparticles().members == {}


def test_an_official_definition_adds_to_the_one_at_the_top_of_its_card() -> None:
    card = ProcCard.reference(REFERENCES_DIR / "HToBB")
    assert card.multiparticles().definitions() == [
        f"p = {FIVE_FLAVOURS}",
        f"j = {FIVE_FLAVOURS}",
        "l+ = e+ mu+",
        "l- = e- mu-",
        "vl = ve vm vt",
        "vl~ = ve~ vm~ vt~",
    ]


def test_a_definition_that_madgraph_refuses_is_an_error() -> None:
    card = ProcCard.from_text("import model sm\ndefine p =\n")
    with pytest.raises(ValueError, match='cannot read "define p ="'):
        card.multiparticles()


def test_every_process_defines_the_multiparticles_of_its_official_card(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for name, spec in specs.items():
        reference = ProcCard.reference(REFERENCES_DIR / name)
        card = ProcCard.from_process(spec)
        assert card.differences_from_official(reference) == [], name


def test_an_official_card_without_a_model_loads_the_standard_model(
    specs: Mapping[str, ProcessSpec],
) -> None:
    reference = ProcCard.reference(REFERENCES_DIR / "ZJetsToNuNu")
    imports = [c for c in reference.commands if c.startswith("import model")]
    assert imports == ["import model sm"]
    card = ProcCard.from_process(specs["ZJetsToNuNu"])
    assert card.commands[0] == "import model sm"
    assert card.differences_from_official(reference) == []


@pytest.mark.parametrize(
    ("proton", "members"),
    [
        (FIVE_FLAVOURS, FIVE_FLAVOURS),
        ("p b b~", FIVE_FLAVOURS),
        ("g u c d s u~ c~ d~ s~ b b~ b", FIVE_FLAVOURS),
        ("g u d s u~ d~ s~ b b~", "g u d s u~ d~ s~ b b~"),
        ("g u d c s u~ c~ d~ s~ b b~", "g u d c s u~ c~ d~ s~ b b~"),
        ("p", "g u c d s u~ c~ d~ s~"),
    ],
)
def test_a_proton_is_compared_by_its_members(proton: str, members: str) -> None:
    reference = ProcCard.reference(REFERENCES_DIR / "TTBar")
    card = ProcCard.from_text(
        f"import model sm-ckm\ndefine p = {proton}\ndefine j = {FIVE_FLAVOURS}\n"
        "generate p p > t t~\n"
    )
    differences = card.differences_from_official(reference)
    assert [str(difference) for difference in differences] == (
        []
        if members == FIVE_FLAVOURS
        else [f"define p: expected {FIVE_FLAVOURS}, got {members}"]
    )


def test_a_multiparticle_of_one_card_alone_is_reported(
    specs: Mapping[str, ProcessSpec],
) -> None:
    reference = ProcCard.reference(REFERENCES_DIR / "WToQQ")
    card = ProcCard.from_process(specs["WToQQ"])
    without = ProcCard(commands=tuple(c for c in card.commands if "wpm =" not in c))
    assert [str(d) for d in without.differences_from_official(reference)] == [
        "missing define wpm: w+ w-"
    ]
    extra = ProcCard(commands=(*card.commands[:-1], "define tops = t t~"))
    assert [str(d) for d in extra.differences_from_official(reference)] == [
        "commands: expected import model sm-ckm | generate p p > ve ve~ wpm, "
        "wpm > j j, got import model sm-ckm",
        "unexpected define tops: t t~",
    ]


def test_the_other_commands_are_compared_in_their_order() -> None:
    reference = ProcCard.reference(REFERENCES_DIR / "ZJetsToNuNu")
    card = ProcCard.from_text(
        f"import model sm\ndefine p = {FIVE_FLAVOURS}\ndefine j = p\n"
        "generate p p > ve ve~ j j @1\nadd process p p > ve ve~ j @0\n"
    )
    differences = card.differences_from_official(reference)
    assert [str(difference) for difference in differences] == [
        "commands: expected import model sm | generate p p > ve ve~ j @0 | "
        "add process p p > ve ve~ j j @1, got import model sm | "
        "generate p p > ve ve~ j j @1 | add process p p > ve ve~ j @0"
    ]


def test_a_reference_without_the_leading_commands_is_compared_as_written() -> None:
    reference = ProcCard.from_text(
        "import model sm\ndefine p = p b b~\ngenerate p p > t t~\n"
    )
    assert reference.differences_from_official(reference) == []
    named = ProcCard.from_text(
        f"import model sm\ndefine p = {FIVE_FLAVOURS}\ngenerate p p > t t~\n"
    )
    assert [
        str(difference) for difference in named.differences_from_official(reference)
    ] == [f"define p: expected p b b~, got {FIVE_FLAVOURS}"]
