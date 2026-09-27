import pytest

from omphjc.madgraph import (
    format_value,
    parse_launch_overrides,
    parse_run_card,
    parse_value,
    values_equal,
)
from omphjc.processes import RunCardValue

RUN_CARD_SNIPPET = """
#*********************************************************************
  tag_1     = run_tag ! name of the run
  10000     = nevents ! Number of unweighted events requested
  6500.0    = ebeam1  ! beam 1 total energy in GeV
  nn23lo1   = pdlabel ! PDF set
  230000    = lhaid   ! if pdlabel=lhapdf, this is the lhapdf number
  False     = use_syst ! Enable systematics studies
  {'6': 450.0} = pt_min_pdg ! pt cut for other particles (use pdg code)
  {}        = eta_min_pdg
  0.01      = drll # hidden_parameter
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("True", True),
        ("False", False),
        ("450", 450),
        ("-1", -1),
        ("450.0", 450.0),
        ("nn23lo1", "nn23lo1"),
        ("{25: 450.0}", {25: 450.0}),
        ("{'6': 2.5}", {6: 2.5}),
        ("{}", {}),
    ],
)
def test_parse_value(text: str, expected: RunCardValue) -> None:
    assert parse_value(text) == expected
    assert type(parse_value(text)) is type(expected)


def test_parse_value_rejects_malformed_mapping() -> None:
    with pytest.raises(ValueError, match="Malformed PDG mapping"):
        parse_value("{25: }")


def test_parse_run_card_reads_active_lines_and_ignores_comments() -> None:
    settings = parse_run_card(RUN_CARD_SNIPPET)
    assert settings["nevents"] == 10000
    assert settings["ebeam1"] == 6500.0
    assert settings["pdlabel"] == "nn23lo1"
    assert settings["use_syst"] is False
    assert settings["pt_min_pdg"] == {6: 450.0}
    assert settings["eta_min_pdg"] == {}
    assert settings["drll"] == 0.01
    assert "run_tag" in settings


def test_parse_launch_overrides_keeps_the_last_value() -> None:
    overrides = parse_launch_overrides(
        "launch TTBar\n\nset use_syst False\nset pt_min_pdg {6: 450.0}\n"
        "set nevents _NEVENTS_\nset nevents 5000\n"
    )
    assert overrides == {
        "use_syst": False,
        "pt_min_pdg": {6: 450.0},
        "nevents": 5000,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "True"),
        (False, "False"),
        (450, "450"),
        (450.0, "450.0"),
        ("nn23lo1", "nn23lo1"),
        ({25: 450.0}, "{25: 450.0}"),
        ({6: 2.5, 5: 1.0}, "{5: 1.0, 6: 2.5}"),
    ],
)
def test_format_value_round_trips_through_parse_value(
    value: RunCardValue, expected: str
) -> None:
    assert format_value(value) == expected
    assert values_equal(parse_value(expected), value)


def test_values_equal_distinguishes_booleans_from_numbers() -> None:
    assert values_equal(450, 450.0)
    assert values_equal({25: 450.0}, {25: 450})
    assert not values_equal(True, 1)
    assert not values_equal(0, False)
    assert not values_equal("nn23lo1", "cteq6l1")
