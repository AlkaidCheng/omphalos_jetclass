"""The JetClass Delphes card.

The card is the official one from the JetClass production, shipped verbatim:
the stock CMS card with track impact-parameter smearing, anti-kT R = 0.8 jets
above 500 GeV with soft drop and N-subjettiness, and a tree writer that keeps
the full generator record. The only run-time change is an optional random seed.
"""

from omphjc.processes.resources_access import delphes_card_path

JETCLASS_CARD_SHA256 = (
    "bf205dd95fe9fe0031847d76edf70a6a8e125ed65141ea9c479aef453588ed1c"
)
"""SHA-256 of ``delphes_card.tcl`` in jet-universe/jetclass_generation @ ae722ea."""


def jetclass_card_text(*, random_seed: int | None = None) -> str:
    """Return the Delphes card, optionally with a fixed random seed.

    Parameters
    ----------
    random_seed : int or None, optional
        When given, a ``set RandomSeed`` line is prepended so that the
        detector smearing is reproducible. Without it Delphes seeds from the
        clock, as the official production did.
    """
    text = delphes_card_path().read_text(encoding="utf-8")
    if random_seed is None:
        return text
    return f"set RandomSeed {random_seed}\n\n{text}"
