# Changelog

## Unreleased

### Added

- Process catalogue of the ten JetClass classes (`omphjc processes`), with a
  value-by-value comparison against the official JetClass cards
  (`omphjc check-cards`).
- Delphes cards are read and compared by their evaluated settings
  (`omphjc delphes show`, `omphjc delphes compare`).
- The configuration is a top-level `config/` directory that
  `omphjc config export DIR` copies for editing and `--catalogue PATH` (or
  `OMPHJC_CATALOGUE`) selects.
- `omphjc pythia show` prints the Pythia command file `DelphesPythia8` reads,
  including the MLM matching block for matched processes. (#2)
- `Banner.read` returns the version, event count, cross section and run card
  recorded in a MadGraph event or banner file. (#2)
- A job's seed, shared by MadGraph, Pythia and Delphes, is its process's offset
  plus its job number (`omphjc.jobs.job_seed`). (#2)
- A process is one catalogue entry needing only `label`, `description`, `model`
  and `processes`; `check-cards` lists entries without `reference_cards` as not
  checked. (#3)
- `config/` keeps the files a run reads (`models/`, `madspin/`, `delphes/`)
  apart from the official JetClass cards in `references/`, and the catalogue
  names the Delphes card in `common.delphes_card`. (#3)
- Pythia settings shared by every process live in the catalogue's
  `common.pythia` and `common.pythia_matching` blocks and can be overridden per
  process (`pythia:`) or per run (`omphjc pythia show --set KEY=VALUE`). (#3)
- The five-flavour `p` and `j` definitions written for every process live in
  the catalogue's `common.definitions`. (#3)
- `docs/guide.md` introduces MadGraph, Pythia and Delphes to newcomers: what
  each program does and the syntax of the files it reads. (#4)
- The CMS card distributed with Delphes, from which the JetClass card is
  adapted, is included in `config/references/delphes/` for
  `omphjc delphes compare --reference`. (#5)
- `config/checksums.json` records the SHA-256 hash of every file the
  configuration takes from the JetClass production, MadGraph and Delphes. (#6)
- A catalogue entry whose process or model name is not a plain name (letters,
  digits, `_`, `.` and `-`) is rejected when the catalogue loads. (#8)
- `omphjc.madgraph.generate_events` runs MadGraph for one process in a working
  directory of its own and returns the event file with its banner. (#9)
- `omphjc generate` runs the MadGraph stage of one job in
  `<outdir>/<process>/job_<N>/` and records the run in its `manifest.json`. (#10)
- `omphjc shower` runs Pythia 8 on a job's generated events through
  `DelphesPythia8` and keeps the generator record of every showered event. (#12)
- Each stage records its wall time, CPU time and peak memory in the job's
  `manifest.json`. (#13)
- `omphjc clean --set-aside` deletes the folders a rerun set aside, which the
  stage reports now count. (#14)
