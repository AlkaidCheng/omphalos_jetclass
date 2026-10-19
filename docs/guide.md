# A guide for newcomers to MadGraph, Pythia and Delphes

This guide explains the three programs `omphjc` drives, the files each one
reads, and the syntax of those files, using the JetClass processes as
examples. It assumes some particle physics, but no experience with event
generators. The [README](../README.md) shows how to run the package; this page
explains what happens inside a run and how to read or change its inputs.

## Contents

1. [From a collision to a detector event](#1-from-a-collision-to-a-detector-event)
2. [MadGraph: the hard process](#2-madgraph-the-hard-process)
3. [Pythia: shower and hadronisation](#3-pythia-shower-and-hadronisation)
4. [Delphes: the detector](#4-delphes-the-detector)
5. [Where each catalogue key ends up](#5-where-each-catalogue-key-ends-up)
6. [Glossary](#6-glossary)
7. [Further reading](#7-further-reading)

## 1. From a collision to a detector event

![The omphjc pipeline](pipeline.svg)

A simulated event is built in stages, each handled by a different program:

| Stage | Program | What it produces |
|---|---|---|
| Hard process | MadGraph5_aMC@NLO | The few energetic particles of the collision itself, for example a Higgs boson and a neutrino pair, drawn from the exact matrix element. Quarks and gluons at this stage are *partons*. |
| Decays of heavy particles | MadGraph (decay chains) or MadSpin | Top quarks, W, Z and Higgs bosons decayed to their final partons and leptons, keeping spin correlations. |
| Parton shower and hadronisation | Pythia 8 | Each parton radiates further gluons and quarks, the coloured partons bind into hadrons, and unstable hadrons decay. Around 100 particles per event. |
| Detector simulation | Delphes | What a CMS-like detector records: tracks, calorimeter deposits, particle-flow candidates and jets. |

MadGraph writes its events to a **Les Houches Event (LHE) file**, a plain-text
format with a header (the *banner*, holding every card used) and one `<event>`
block per event. In this package Pythia and Delphes then run together inside
the program `DelphesPythia8`, which reads the LHE file and writes a ROOT file.

## 2. MadGraph: the hard process

MadGraph is driven by short scripts of commands. The package writes two for
each process; `omphjc processes show HToBB` prints them:

```
process script:
  import model …/config/models/heft
  define p = p b b~
  define j = j b b~
  generate p p > ve ve~ h, h > b b~
  output HToBB

launch script (1000 events, random seed):
  launch HToBB
  shower=OFF
  detector=OFF
  madspin=OFF
  done
  set nevents 1000
  set iseed 0
  set lpp1 1
  …
  set misset 450.0
  set pt_min_pdg {25: 450.0}
  set eta_max_pdg {25: 2.5}
  done
```

The process script defines the physics and compiles code for it into a
directory (`output HToBB`). The launch script runs that directory: the lines up
to the first `done` answer MadGraph's questions about which programs to run
(the shower and detector are off because `DelphesPythia8` runs them
afterwards), and the `set` lines fix run-card values before generation starts.

### 2.1 Process syntax

| Syntax | Meaning | Example |
|---|---|---|
| `a b > c d` | Initial state, then final state | `p p > t t~` |
| `~` | Antiparticle | `t~`, `b~`, `ve~` |
| `p`, `j`, `l+`, `l-`, `vl`, `vl~` | Multiparticle labels. MadGraph starts with `p = j = g u c d s u~ c~ d~ s~`, `l+ = e+ mu+`, `l- = e- mu-`, `vl = ve vm vt` | `p p > ve ve~ j` |
| `define x = …` | A new label, or an extended one | `define p = p b b~` adds b quarks to the proton (five-flavour scheme); `define lep = l+ l-` |
| `, x > …` | Decay chain: produce `x` on its mass shell, then decay it. `bwcutoff` in the run card sets how far off-shell it may be | `p p > ve ve~ h, h > b b~` |
| `> x y >` | Required intermediate particles: the diagrams must contain `x` and `y` as propagators, which may be off-shell | `h > w+ w- > j j j j` (H → WW* → four quarks) |
| `@N` | A tag on a process line. With MLM matching, the line with the most jets is the highest multiplicity (§3.3) | `p p > ve ve~ j @0` |
| `generate`, `add process` | The first process line, then further lines summed into the same sample | ZJetsToNuNu has one `generate` and one `add process` |
| `/ x` and `$ x` | Exclude `x` from every diagram, or only as an on-shell intermediate. Not used by the JetClass processes | `p p > e+ e- / z` |

Particle names follow the model; the Standard Model names are `u d c s t b`,
`g a z w+ w- h`, `e- mu- ta-`, `ve vm vt` and their antiparticles.

### 2.2 Models and restriction cards

A **model** is a folder in the UFO format: Python files (`particles.py`,
`parameters.py`, `couplings.py`, `vertices.py`, …) that list the particles,
their parameters and their interactions. MadGraph ships the Standard Model
(`sm`); other models are downloaded or supplied as folders. The package keeps
the models it needs in `config/models/` and imports them by path, so a run
never downloads anything.

A model folder also holds **restriction cards**, `restrict_<name>.dat`. Each
gives a value to every parameter of the model, and MadGraph uses it to
simplify the model when importing it: parameters set exactly to 0 are removed,
together with every coupling and vertex that vanishes with them, and
parameters set exactly to 1 are fixed to 1. A smaller model generates faster.
What a card removes cannot be switched back on later.

The part of a model name after the last `-` chooses the card:

| `model:` | MadGraph imports |
|---|---|
| `heft` | `models/heft/` with `restrict_default.dat` if the folder has one |
| `heft-ckm` | `models/heft/` with `restrict_ckm.dat` |
| `heft-full` | `models/heft/` with no restriction at all |

The prefix `restrict_` and the extension `.dat` are fixed by MadGraph, which
builds the file name from the suffix; the suffix itself cannot contain a `-`,
and `full` is reserved. (`get_path_restrict` in MadGraph's
[`models/import_ufo.py`](https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/models/import_ufo.py#L201).)

The JetClass samples show why the choice matters. `restrict_default.dat` and
`restrict_ckm.dat` of `heft` differ only in the four CKM parameters: the
default sets them to 0, so quarks do not mix between generations, and the
HToWW processes use `heft-ckm` to keep the mixing. Both cards set the charm
mass and the charm Yukawa coupling to 0, which removes the H → cc̄ vertex, so
the HToCC sample uses its own model, `heft_c_mass_jetclass`, with both set to
1.55 GeV.

The `heft` model itself adds to the Standard Model the effective couplings of
the Higgs boson to gluons and photons (H → gg would otherwise not exist at the
level MadGraph computes).

### 2.3 The run card

The run card holds the settings of one generation run, one per line as
`value = name ! comment`. The package applies the catalogue's `run_card`
values as `set name value` lines at launch. The settings used by the JetClass
processes, with MadGraph's own description where it has one:

| Setting | Meaning |
|---|---|
| `nevents` | Number of events to generate |
| `iseed` | Random seed; 0 lets MadGraph choose |
| `lpp1`, `lpp2` | Beam types; 1 is a proton |
| `ebeam1`, `ebeam2` | Energy of each beam in GeV; 6500 + 6500 is the 13 TeV LHC |
| `pdlabel`, `lhaid` | Parton distribution functions. `nn23lo1` is NNPDF 2.3 at leading order, built into MadGraph; `lhaid` is read only when `pdlabel = lhapdf` |
| `dynamical_scale_choice`, `scalefact` | How the renormalisation and factorisation scales are chosen per event (−1 is MadGraph's default) and a factor applied to them |
| `bwcutoff` | How far off-shell a decay-chain particle may be, in units of its width: M ± bwcutoff·Γ |
| `maxjetflavor` | Heaviest quark counted as a jet; 5 includes b quarks |
| `cut_decays` | Whether the cuts below also apply to decay products |
| `ptj`, `etaj`, `drjj` | Minimum jet pT (GeV), maximum jet \|η\|, minimum ΔR between jets |
| `ptl`, `etal`, `drll`, `drjl` | The same for charged leptons |
| `misset` | Minimum missing transverse energy, the summed pT of the neutrinos. With `misset = 450`, the Z → νν̄ recoils against a Higgs boson of comparable pT, which makes the Higgs decay products land in one wide jet |
| `pt_min_pdg`, `eta_max_pdg` | Minimum pT and maximum \|η\| for given particles by PDG code: `{25: 450.0}` requires a Higgs boson (code 25) above 450 GeV |
| `use_syst` | Whether to store weights for systematic variations |
| `ickkw`, `xqcut` | MLM matching: `ickkw = 1` turns it on and `xqcut` is the minimum kT distance between partons, in GeV (§3.3) |
| `auto_ptj_mjj`, `alpsfact`, `asrwgtflavor` | Matching details: automatic jet cuts when `xqcut > 0`, the scale factor for QCD emission vertices, and the heaviest flavour in the αs reweighting |

The official JetClass run cards, with every setting MadGraph knows and its
comment, are in `config/references/jetclass/<process>/run_card.dat`.

### 2.4 The param card

The param card lists the model's parameters in blocks (`MASS`, `DECAY`,
`YUKAWA`, `CKMBLOCK`, …), one `code value # name` line each. MadGraph writes it
from the restriction card. A parameter the restriction kept, such as the top
mass, can be changed in the param card before a run; a parameter it removed
needs a different restriction card.

### 2.5 MadSpin

MadSpin decays heavy particles after the hard process has been generated,
keeping the correlations between the spins of the decaying particles and of
their products. Its card has `set` options, one `decay` line per decay, and
`launch`. The TTBar card, `config/madspin/TTBar.dat`:

```
 set max_weight_ps_point 400  # number of PS to estimate the maximum for each event
decay t > w+ b, w+ > j j
decay t~ > w- b~, w- > j j
decay w+ > j j
decay w- > j j
launch
```

Both tops decay to a b quark and a hadronically decaying W. TTBarLep's card
decays both W bosons to `l+ vl` and `l- vl~` instead. An entry runs MadSpin
when it names a `madspin_card`.

### 2.6 What MadGraph writes

The run directory holds `unweighted_events.lhe.gz` (gzipped LHE) and a banner
file. The banner records the MadGraph version, every card as used, the number
of events and the integrated cross section in pb; the `<init>` block of the
event file adds the statistical error. `omphjc.madgraph.Banner.read` reads
them.

## 3. Pythia: shower and hadronisation

### 3.1 What Pythia does

Pythia takes each event from the LHE file and turns its few partons into a
realistic final state: initial- and final-state radiation (the parton shower),
additional softer interactions between the remaining partons of the two
protons (multiparton interactions), hadronisation of the coloured partons into
hadrons (the Lund string model), and the decays of unstable hadrons.

### 3.2 Command-file syntax

Pythia reads settings from a command file, one `Group:name = value` per line.
`omphjc pythia show HToBB` prints the file the package writes:

```
! Pythia 8 settings for DelphesPythia8: HToBB
!
Beams:frameType = 4
Check:epTolErr = 0.01
JetMatching:setMad = off
JetMatching:etaJetMax = 1000
Beams:LHEF = events.lhe
Main:numberOfEvents = 1000
Random:setSeed = on
Random:seed = 0
```

The reading rules:

- A line is a setting only when its first non-blank character is a letter or
  a digit; any other line, such as one starting with `!` or `#`, is ignored.
- Names are not case-sensitive, and when a name appears twice the last value
  wins.
- Switches take `on` or `off`.

`Beams:frameType = 4` tells Pythia to read events from the LHE file named by
`Beams:LHEF`. `Random:seed = 0` takes the seed from the clock; Pythia's own
default is a fixed seed, which would give every run the same shower. The full
list of settings is in the [Pythia manual](https://pythia.org/latest-manual/Welcome.html).

The settings written for every process come from the catalogue's
`common.pythia` block, whose comment names the MadGraph source line the values
come from; the [README](../README.md#pythia-settings) explains how to override
them.

### 3.3 MLM matching

The QCD jet sample, ZJetsToNuNu, is generated with one and with two extra
partons (`p p > ve ve~ j @0` and `p p > ve ve~ j j @1`). Pythia's shower also
produces extra jets, so without care the same configuration would be counted
twice: once as a two-parton event, once as a one-parton event whose shower
made the second jet.

MLM matching removes the overlap:

1. MadGraph generates partons separated by at least `xqcut` in a kT distance
   (30 GeV here).
2. After the shower, Pythia clusters the event into jets with the kT algorithm
   down to the matching scale `JetMatching:qCut` (45 GeV, set by MadGraph to
   1.5 × `xqcut`).
3. Every MadGraph parton must match one of those jets, otherwise the event is
   vetoed. In the lower multiplicity the event is also vetoed when the shower
   made an extra jet above `qCut`; in the highest multiplicity
   (`JetMatching:nJetMax = 2`) extra jets are allowed as long as they are
   softer than the softest matched jet.

Vetoed events are dropped, so a matched job keeps fewer events than MadGraph
generated. The veto runs inside the shower, through a Pythia "user hook" that
`DelphesPythia8` installs; the package writes the matching block
(`JetMatching:merge`, `qCut`, `nJetMax`, …) only for an entry with
`matching: true`. The
[Pythia manual page](https://pythia.org/latest-manual/JetMatching.html) and the
[MadGraph wiki](https://cp3.irmp.ucl.ac.be/projects/madgraph/wiki/LOPY8Merging)
describe the settings.

## 4. Delphes: the detector

### 4.1 What Delphes does

Delphes is a fast detector simulation. Instead of tracing every particle
through detector material, it applies measured resolutions and efficiencies:
charged particles become tracks with smeared momenta, photons and hadrons
deposit energy in calorimeter cells, and the two are combined into
particle-flow candidates, from which jets are built.

### 4.2 Card syntax

A Delphes card is a Tcl script. `set ExecutionPath { … }` lists the modules in
the order they run, and each module is a block of `set` and `add` commands:

```tcl
module FastJetFinder FatJetFinder {
  set InputArray EFlowMerger/eflow
  set JetAlgorithm 6
  set ParameterR 0.8
  set JetPTMin 500.0
  …
}
```

`module Type Name` creates a module of class `Type`; `set` gives a parameter a
value; `add` appends elements to a list parameter (calorimeter binnings, the
output branches). A module reads another module's output by
`ModuleName/arrayName`.

The JetClass card runs 17 modules:

| Modules | Role |
|---|---|
| `ParticlePropagator` | Moves particles through the 3.8 T solenoid field to a cylinder of radius 1.29 m and half-length 3.00 m. Particles produced outside it, such as the decay products of long-lived hadrons, are dropped |
| `…TrackingEfficiency`, `…MomentumSmearing`, `TrackMerger`, `TrackSmearing` | Turn charged particles into tracks: efficiencies, momentum resolution, impact-parameter resolution |
| `ECal`, `HCal`, `Calorimeter`, `EFlowMerger` | Calorimeter deposits, then particle flow |
| `NeutrinoFilter`, `GenJetFinder` | Generator-level jets from all particles except neutrinos, with the same definition as `FatJetFinder` |
| `FatJetFinder` | Anti-kT jets (`JetAlgorithm 6`) with R = 0.8 and pT > 500 GeV, with N-subjettiness and soft-drop mass |
| `TreeWriter` | The output branches |

The output ROOT file has four branches: `Particle` (the full generator record
from Pythia), `ParticleFlowCandidate`, `GenFatJet` and `FatJet`.

`omphjc delphes show` prints a card as Delphes evaluates it, and
`omphjc delphes compare my_card.tcl` lists every setting that differs from the
official JetClass card.

## 5. Where each catalogue key ends up

| Catalogue key | Becomes | Read by |
|---|---|---|
| `model` | `import model …` in the process script (§2.2) | MadGraph |
| `common.definitions`, `definitions`, `processes` | `define`, `generate`, `add process` (§2.1) | MadGraph |
| `common.run_card`, `run_card` | `set` lines in the launch script (§2.3) | MadGraph |
| `madspin_card` | `madspin=ON` and the MadSpin card (§2.5) | MadSpin |
| `matching` | The MLM block of the Pythia command file, with `qCut`, `nJetMax` and `nQmatch` derived from the run card and process lines (§3.3) | Pythia |
| `common.pythia`, `common.pythia_matching`, `pythia` | Lines of the Pythia command file (§3.2) | Pythia |
| `common.delphes_card` | The Delphes card (§4.2) | Delphes |
| `seed_offset` | Added to the job number to form the MadGraph, Pythia and Delphes seeds | all three |
| `reference_cards` | Nothing in a run; `omphjc check-cards` compares the entry with these cards | — |

To see what a catalogue produces without running anything:

```
omphjc processes show HToBB     # MadGraph scripts and run-card settings
omphjc pythia show ZJetsToNuNu  # the Pythia command file, with the matching block
omphjc delphes show             # the official Delphes card, module by module
omphjc check-cards              # differences from the official JetClass cards
```

## 6. Glossary

| Term | Meaning |
|---|---|
| Banner | The header of an LHE file: every card used and the generation summary |
| Cross section | The rate of a process, in picobarn (pb) |
| ΔR | Angular distance √(Δη² + Δφ²) |
| η, φ | Pseudorapidity (the polar angle, as −ln tan(θ/2)) and azimuthal angle |
| Gridpack | A pre-compiled MadGraph process directory, used by the official JetClass production |
| kT distance | A measure of how close two partons are, combining their angle and transverse momenta; used by jet clustering and by MLM matching |
| LHE | Les Houches Event file, the standard text format for parton-level events |
| Missing transverse energy | The imbalance of transverse momentum in an event, here carried by neutrinos |
| Parton | A quark or gluon |
| PDG code | The Particle Data Group's number for a particle: 1–6 the quarks d u s c b t, 11 e⁻, 12 νe, 13 μ⁻, 21 g, 22 γ, 23 Z, 24 W⁺, 25 H; negative for antiparticles |
| pT | Transverse momentum, the momentum perpendicular to the beam |
| UFO | Universal FeynRules Output, the format of MadGraph models |

## 7. Further reading

- MadGraph5_aMC@NLO: J. Alwall et al., [arXiv:1405.0301](https://arxiv.org/abs/1405.0301);
  source and releases on [Launchpad](https://launchpad.net/mg5amcnlo).
- MadSpin: P. Artoisenet et al., [arXiv:1212.3460](https://arxiv.org/abs/1212.3460).
- UFO format: C. Degrande et al., [arXiv:1108.2040](https://arxiv.org/abs/1108.2040).
- Pythia 8.3: C. Bierlich et al., [arXiv:2203.11601](https://arxiv.org/abs/2203.11601);
  the [online manual](https://pythia.org/latest-manual/Welcome.html).
- Matching matrix elements and parton showers: J. Alwall et al.,
  [arXiv:0706.2569](https://arxiv.org/abs/0706.2569).
- Delphes 3: J. de Favereau et al., [arXiv:1307.6346](https://arxiv.org/abs/1307.6346);
  source on [GitHub](https://github.com/delphes/delphes).
- The Les Houches Event file format: J. Alwall et al.,
  [arXiv:hep-ph/0609017](https://arxiv.org/abs/hep-ph/0609017).
- The JetClass production this package reproduces:
  [jet-universe/jetclass_generation](https://github.com/jet-universe/jetclass_generation).
