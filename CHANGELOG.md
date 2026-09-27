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
