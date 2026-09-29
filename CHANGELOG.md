# Changelog

## Unreleased

### Added

- Process catalogue of the ten JetClass classes with the official gridpack
  cards as references, MadGraph process and launch script writers, the JetClass
  Delphes card, and the `omphjc processes` and `omphjc check-cards` commands.
- Delphes and MadSpin cards are compared as configuration, by keys and values
  (`omphjc delphes show`, `omphjc delphes compare`).
- The catalogue, cards and models ship in the top-level `config/` directory;
  `omphjc config path` and `omphjc config export DIR` locate and copy it, and
  `--catalogue PATH` (or `OMPHJC_CATALOGUE`) runs every command on another
  catalogue.
- Pythia command files for `DelphesPythia8` mirrored from MadGraph's interface,
  with the MLM matching block for matched processes (`omphjc pythia show`). (#2)
- `Banner.read` returns the MadGraph version, event count, cross section with
  its error and the run card of an event or banner file. (#2)
- `derive_seeds` gives a job one seed for MadGraph, Pythia and Delphes from the
  process offsets of the official production; unseeded runs stay the default. (#2)
- A process is one catalogue entry: `reference_cards`, `madspin_card` and the
  models directory are paths relative to the catalogue, and `check-cards` lists
  processes without reference cards instead of failing on them. (#3)
- The shared Pythia settings live in the catalogue (`common.pythia`,
  `common.pythia_matching`) with their provenance, and a process or a run may
  override them (`pythia:` block, `omphjc pythia show --set KEY=VALUE`). (#3)
