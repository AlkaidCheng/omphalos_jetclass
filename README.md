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

## Processes

The ten JetClass classes are defined as data, with the official gridpack cards
of the JetClass production packaged as the reference:

```
omphjc processes              # list the catalogue
omphjc processes show HToBB   # MadGraph inputs written for one process
omphjc check-cards            # compare the catalogue with the official cards
```

`check-cards` verifies, value by value, that every physics setting the package
applies equals the one in the official cards and that no tracked official
setting is missing.

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
[jetclass_generation at commit ae722ea](https://github.com/jet-universe/jetclass_generation/tree/ae722ea560efa01c6ed814c72d15b7cdafdf3449).
The vendored `heft` model is the MadGraph5_aMC@NLO Higgs effective-field-theory
model. Developed with the assistance of Claude Code.

## License

MIT. See `LICENSE`.
