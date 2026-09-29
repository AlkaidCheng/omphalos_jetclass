# omphjc

Sample generation for JetClass-style jet datasets with two detector
simulations: Delphes, as in the original JetClass production, and Parnassus.
One set of generated events feeds both, so the two detector responses can be
compared on identical physics.

The pipeline is MadGraph5_aMC@NLO → Pythia 8 → Delphes, run as
`DelphesPythia8` with the official JetClass Delphes card. The full simulated
event (hard process, decays, parton shower and hadronisation) is extracted from
the Delphes output into a columnar file, from which the Parnassus input is
derived in Parnassus's own stable-particle convention.

## Installation

```
pip install -e .
```

The package itself needs Python 3.10 or later. Generating events additionally
needs MadGraph5_aMC@NLO, Pythia 8 and Delphes built with Pythia support; the
`environment/` directory documents a pinned installation.

## Configuration

Everything a user may want to read, cite or adapt lives in `config/`:

- `jetclass.yaml`: the ten JetClass classes as data (model, process lines,
  run-card settings, MadSpin, matching, seed offsets);
- `cards/jetclass/<process>/`: the official gridpack cards of the JetClass
  production, the reference the catalogue is checked against;
- `cards/delphes/delphes_card_JetClass.tcl`: the official Delphes card;
- `models/`: the vendored MadGraph UFO models;
- `PROVENANCE.md`: where each file comes from, with hashes.

An installed package carries a copy of this directory. To work from a modified
catalogue, export the configuration and point the command line at it:

```
omphjc config path                        # where the shipped copy lives
omphjc config export ./my_config          # copy it for editing
omphjc --catalogue ./my_config/jetclass.yaml processes
export OMPHJC_CATALOGUE=./my_config/jetclass.yaml   # same, for every command
```

## Processes

The catalogue is checked against the official cards:

```
omphjc processes              # list the catalogue
omphjc processes show HToBB   # MadGraph inputs written for one process
omphjc check-cards            # compare the catalogue with the official cards
```

`check-cards` verifies, value by value, that every physics setting the package
applies equals the one in the official cards and that no tracked official
setting is missing.

## Adding a process

A process is one catalogue entry; no code changes are involved. Export the
shipped configuration (`omphjc config export ./my_config`) or write a catalogue
of your own, then point the command line at it with `--catalogue`:

```yaml
processes:
  ZPrimeToTT:
    label: Zptt                        # class name, unique within the catalogue
    description: "Z' → tt̄ with up to one extra jet"
    model: zprime-restricted           # models/zprime/ next to the catalogue, or a MadGraph model
    definitions: ["tops = t t~"]       # optional multiparticle definitions
    processes:
      - "p p > zp > tops tops @0"
      - "p p > zp > tops tops j @1"
    run_card: {ickkw: 1, xqcut: 40.0, pt_min_pdg: {6: 450.0}}
    matching: true                     # MLM matching; adds the Pythia matching block
    madspin_card: decays/zprime.dat    # optional; MadSpin runs when present
    reference_cards: cards/zprime      # optional; check-cards compares against these
    seed_offset: 60000000              # keeps its seeds apart from every other process
```

Paths are relative to the catalogue file. A model whose directory exists under
`models/` is imported by path; any other model name is left to MadGraph.
`omphjc check-cards` compares every process that names `reference_cards` and
lists the others as not checked.

## Pythia settings

Events are showered inside `DelphesPythia8`, which takes a Pythia command file
rather than MadGraph's run card. `omphjc pythia show` prints the file the
package writes for a process:

```
$ omphjc pythia show ZJetsToNuNu --events 1000 --seed 1
! Pythia 8 settings for DelphesPythia8: ZJetsToNuNu
!
Beams:frameType = 4
Check:epTolErr = 0.01
JetMatching:setMad = off
JetMatching:etaJetMax = 1000
Beams:LHEF = events.lhe
Main:numberOfEvents = 1000
Beams:setProductionScalesFromLHEF = on
JetMatching:merge = on
JetMatching:scheme = 1
JetMatching:coneRadius = 1
JetMatching:doShowerKt = off
JetMatching:qCut = 45
JetMatching:nJetMax = 2
JetMatching:nQmatch = 5
Random:setSeed = on
Random:seed = 1
```

- `Beams:frameType`, `Check:epTolErr`, `JetMatching:setMad` and
  `JetMatching:etaJetMax` are the settings MadGraph's own Pythia interface adds
  to every run; they are written for every process.
- `Beams:LHEF`, `Main:numberOfEvents` and `Random:*` describe the run:
  `--lhe`, `--events` and `--seed`. Without `--seed` the shower is seeded from
  the clock (`Random:seed = 0`).
- The `JetMatching:*` block and `Beams:setProductionScalesFromLHEF` implement
  MLM matching and appear only for a process with `matching: true` in the
  catalogue (ZJetsToNuNu). `JetMatching:qCut` is 1.5 × the run card's `xqcut`,
  `JetMatching:nQmatch` its `maxjetflavor`, `JetMatching:nJetMax` the largest
  number of jets in the process lines; the remaining values are MadGraph's
  fixed choices.

### Changing the settings

The fixed values live in `config/jetclass.yaml`: `common.pythia` holds the
settings written for every run, `common.pythia_matching` the fixed part of the
matching block, each value with a comment naming the MadGraph source it comes
from. Three places change them, later ones winning:

1. The catalogue blocks themselves, in your own copy
   (`omphjc config export ./my_config`, then `--catalogue ./my_config/jetclass.yaml`).
2. A `pythia:` block in one process entry, for that process only:

   ```yaml
     HToBB:
       model: heft
       processes:
         - "p p > ve ve~ h, h > b b~"
       pythia:
         Main:timesAllowErrors: 100
   ```

3. The command line, for one run: `omphjc pythia show HToBB --set Main:timesAllowErrors=100`.

The derived matching values (`qCut`, `nQmatch`, `nJetMax`) follow the run card
and the process lines; they can be overridden the same way.

## Delphes cards

The official JetClass Delphes card is packaged and used by default; any card
can be used instead. Cards are compared as configuration, the way Delphes reads
them, so layout, comments and definition order never count as differences:

```
omphjc delphes show                    # execution path, modules and parameters
omphjc delphes compare my_card.tcl     # differences from the official card
```

Reading a card uses the Tcl interpreter that ships with Python (`tkinter`).

## Layout of a job

Each job produces, in its own directory, the MadGraph event file, the Delphes
output, the simulation-only record and the Parnassus input, together with a
manifest recording versions, seeds and cross sections.

## Acknowledgements

The process definitions, cards and Delphes configuration follow the JetClass
production by the jet-universe project (MIT),
[jet-universe/jetclass_generation](https://github.com/jet-universe/jetclass_generation);
`config/PROVENANCE.md` records the exact files taken from it.
The vendored `heft` model is the MadGraph5_aMC@NLO Higgs effective-field-theory
model. Developed with the assistance of Claude Code.

## License

MIT. See `LICENSE`.
