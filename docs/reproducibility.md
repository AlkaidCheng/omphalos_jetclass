# What a rerun reproduces

Every program a job runs is seeded from the job's seed, `seed_offset + job`
(see [Seeds](../README.md#seeds)): MadGraph's `iseed` and `python_seed`,
Pythia's `Random:seed` and Delphes's `RandomSeed`. Running a stage again with
the same seed gives the same events as long as the conditions in the table
also hold. The conditions were read from the source code of MadGraph 3.8.1,
Pythia 8.312 and Delphes 3.5.1.

| Stage | Program | The events also depend on |
|---|---|---|
| `generate` | MadGraph and MadSpin | the core count, for a process with MadSpin; the open-file limit, for a run with many channels |
| `shower` | Pythia 8, inside `DelphesPythia8` | nothing else found |
| `simulate` | Delphes, as `DelphesROOT` | nothing else found |

Every stage also depends on the version and the build of its program (see
[Versions and builds](#versions-and-builds)). Two runs with the same events are
still different files (see [Same events, different files](#same-events-different-files)).

## generate: MadGraph and MadSpin

MadGraph has two random generators. Its Fortran code, which integrates the
matrix element and generates weighted events, starts from `iseed`; its Python
generator, which unweights those events, starts from `python_seed`. A job sets
both to its seed. MadSpin draws its own seed from the Python generator and
records it in the banner's MadSpin block, so it follows the job's seed too.

A `set seed` line in a MadSpin card has no effect in the spin modes `madspin`
(MadSpin's default), `onshell` and `PA`, which take the seed from MadGraph's
Python generator. The TTBar and TTBarLep cards keep MadSpin's commented-out
`# set seed 1`; removing the `#` changes nothing.

MadGraph resets `iseed` to 0 in `Cards/run_card.dat` before it runs, so the
copy the job keeps, `generate/cards/run_card.dat`, shows `iseed = 0`. The seed
the run used is the stage's `seed` parameter in `manifest.json` and the `iseed`
of the run card in the event file's banner.

### The core count

MadSpin decays the events in one separately seeded shard per core, so a process
with MadSpin (TTBar and TTBarLep in the default catalogue) gives the same events
only on the same number of cores. A rerun with another `--cores` keeps a
finished stage, and the manifest records the count MadGraph ran on as the
stage's `n_cores`. Without `--cores`, MadGraph runs on every CPU the job may
use, which a batch system sets per allocation, so give `--cores` explicitly for
a process with MadSpin. For a process without MadSpin the core count does not
change the events.

### Runs with many channels

MadGraph integrates each channel of the matrix element in a directory of its
own. It unweights the events of a run with at least `max(80, ulimit -n − 40)`
such directories, or 2500 when the soft open-file limit `ulimit -n` is
unlimited, in separate Python processes whose random numbers come from the
operating system, so such a run gives other events every time. omphjc raises
`ulimit -n` to the hard limit, `ulimit -Hn`, while MadGraph runs, or to 10240
where the hard limit is unlimited, as on macOS. Only a run with at least that
limit minus 40 channel directories is then affected.

To check a process before a production, generate one small job, count its
channel directories (an upper bound on the count MadGraph checks) and compare
the count with the hard limit of the machine that will run the production:

```
awk '$2 > 0' runs/dev/HToBB/job_1/generate/HToBB/SubProcesses/P*/symfact.dat | wc -l
ulimit -Hn
```

## shower: Pythia

Pythia draws every random number from one generator seeded with `Random:seed`,
and it reads the generated events in order. Pythia accepts seeds from 1 to
900 000 000, the narrowest range of the three programs, so omphjc refuses a job
whose seed is larger.

## simulate: Delphes

omphjc adds `set RandomSeed <seed>` as the last line of the detector card.
Delphes seeds ROOT's random generator, `gRandom`, with it, and every module
draws from that generator. Delphes evaluates the card from top to bottom and
uses the last value of `RandomSeed`, so a `set RandomSeed` line in the card
itself has no effect.

## Versions and builds

Another version of a program can give other events; the manifest records the
MadGraph and Pythia versions. A program built with another compiler, other
compiler options or for another CPU can give other floating-point results and
so other events. None of the three programs documents how far this goes, and
omphjc has not tested it.

## Same events, different files

Two runs with the same events still differ as files. The banner of an LHE file
holds the path of the job directory, a ROOT file holds its creation time and a
unique identifier, and Delphes writes the wall-clock times `Event.ReadTime` and
`Event.ProcTime` into every event. Compare the events, not checksums of the
files.

omphjc records a fingerprint of each stage's event file in `manifest.json`, and
the fingerprint leaves those differences out. The shower and the simulation
record the fingerprint of the events they read as the parameter
`input_fingerprint`. A stage run again with the same events therefore keeps the
stages after it, and a stage whose input events changed is refused unless
forced.

The fingerprint of an LHE file covers the cards as MadGraph recorded them in
the header, without their comments and layout, and every byte from the
`<init>` line to the end of the file. The fingerprint of a ROOT file covers the
number of events, the name and type of every leaf, and the values of a sample
of the events. A leaf with the same number of values in every event, such as
the number of particles, is hashed in every event. A leaf with a list in every
event, such as the particle momenta, is hashed in four ranges of 1% of the
events each: the first events, the last events and two ranges between them. A
change that lies in the lists and reaches no sampled event is missed.

A fingerprint is taken when the stage writes its file. A change made to the
file afterwards is seen only when it changes the size of the file: the stage
is then refused, as is the stage that reads the file, until it is run again
with `--force`.
