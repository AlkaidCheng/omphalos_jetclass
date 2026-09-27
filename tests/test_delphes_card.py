import hashlib

from omphjc.delphes import JETCLASS_CARD_SHA256, jetclass_card_text


def test_card_is_the_official_jetclass_card() -> None:
    digest = hashlib.sha256(jetclass_card_text().encode("utf-8")).hexdigest()
    assert digest == JETCLASS_CARD_SHA256


def test_card_keeps_the_jetclass_modules() -> None:
    text = jetclass_card_text()
    assert "module TrackSmearing TrackSmearing" in text
    assert "set ParameterR 0.8" in text
    assert "add Branch Delphes/allParticles Particle GenParticle" in text


def test_random_seed_is_prepended_only_when_given() -> None:
    seeded = jetclass_card_text(random_seed=12345)
    assert seeded.startswith("set RandomSeed 12345\n\n")
    assert seeded.endswith(jetclass_card_text())
    assert "RandomSeed" not in jetclass_card_text()
