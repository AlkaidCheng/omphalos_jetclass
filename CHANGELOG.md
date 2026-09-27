# Changelog

## Unreleased

### Added

- Process catalogue of the ten JetClass classes with the official gridpack
  cards as references, MadGraph process and launch script writers, the
  JetClass Delphes card, and the `omphjc processes` and `omphjc check-cards`
  commands; the catalogue, cards and models ship in the top-level `config/`
  directory.
- Delphes cards are read as configuration and compared by keys and values
  (`omphjc delphes show`, `omphjc delphes compare`); MadSpin cards are compared
  the same way.
- `omphjc config path` and `omphjc config export DIR` locate and copy the
  shipped configuration; `--catalogue PATH` (or `OMPHJC_CATALOGUE`) runs every
  command on another catalogue.
- Pythia settings for `DelphesPythia8` mirrored from MadGraph's interface, with
  the MLM matching block for matched processes (`omphjc pythia show`).
- MadGraph banner reader: version, event count, cross section and error, and
  the run card as used.
- Job seeds derived from the process offsets of the official production
  (`derive_seeds`), with unseeded runs as the default.
- A process is described entirely by its catalogue entry: `reference_cards`,
  `madspin_card` and the models directory are paths relative to the catalogue,
  and `check-cards` lists processes without reference cards instead of
  failing on them.
