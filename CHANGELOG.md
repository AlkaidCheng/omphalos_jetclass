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
- `omphjc simulate` runs Delphes on a job's showered events through
  `DelphesROOT`, with the process's detector card or one given by `--card`. (#15)
- `omphjc generate` records the cores MadGraph ran on as `n_cores` in the
  stage's metadata. (#30)
- `omphjc.events.readers.reader_for` returns the `EventReader` of an event file,
  whose `read_particles`, `iterate_particles` and `count_events` read the
  generator record of a Delphes ROOT file, such as the shower's
  `particles.root`, as one awkward record per event with `part_t` in mm. (#39)
- `omphjc.events.stable_particles.StableParticleDefinition` marks as final the
  long-lived particles the shower decayed, and their decay products as not
  final, as Parnassus expects. (#39)
- `omphjc.tools.parnassus.hepmc_input.write_hepmc_input` writes the final state
  of a particle record as the HepMC3 file Parnassus reads, on as many threads as
  `threads` asks. (#41)
- `environment/check_requirements.py` checks that an installed environment
  meets every requirement that omphjc, Parnassus and the packages they reach
  declare. (#43)
- `environment/environment.yml` describes a conda environment for omphjc, and
  `environment/Dockerfile` builds an image of it with MadGraph 3.8.1, which
  each release publishes as `ghcr.io/alkaidcheng/omphjc:<version>`. (#44, #46)
- `omphjc.tools.madgraph.lhe_file.LHEFile.fingerprint` returns a fingerprint of
  an LHE file, the same for two files with the same events and cards. (#50,
  #51)
- `omphjc.data_files.DataFile` is the base class of the classes that hold the
  content of one file format each, the first three being `ProcCard`,
  `SLHACard` and `LHEFile` for MadGraph's process card, parameter card and
  event file. (#51)
- `Card.differences` lists the differences between two cards of one class,
  built with the `Difference.between_mappings` and
  `Difference.between_collections` constructors. (#53)
- `omphjc.events.delphes_root.DelphesROOTFile.fingerprint` returns a
  fingerprint of a Delphes ROOT file from the structure of its tree and a
  sample of its entries, the same for two files with the same events. (#55)
- A job directory holds `job.json` with the job's process, number and seed
  (`omphjc.jobs.JobIdentity`), and no stage runs in the directory of another
  job. (#61)

### Changed

- Every argument and attribute of the drivers, run records, stages and CLI that
  holds a file path ends in `_path` and every one that holds a directory in
  `_dir`. (#16)
- Python names follow one verb per idea and say what they return, for example
  `read_card`, `parse_statistics`, `format_duration`, `uses_madspin`,
  `is_occupied` and `make_error`; `madgraph.verify` is `madgraph.reference` and
  `madgraph.runcard` is `madgraph.run_card`. (#17)
- The first stage's directory and manifest record are named `generate` after
  its command, the job number is `--job-id` on the command line and `job_id` in
  the manifest, and the peak memory is `peak_memory_mib`. (#18)
- `compare_process` and `compare_all` report `omphjc.comparison.Difference`
  records like the Pythia and Delphes comparisons, `compare_all` keyed by
  process name; `Mismatch` is gone. (#19)
- Run records derive from `omphjc.workspace.Run` and `ProgramRun`, which carry
  the fields every run shares, and MadGraph's event file is `output_path` like
  the other runs' outputs. (#21)
- A workspace's `sealed_run` context manager readies the directory on entry and
  seals the run's artifacts on exit, in place of `prepare` and
  `seal_artifacts`. (#22)
- `omphjc.workspace.Workspace` is the stamped directory alone, whose subclass
  names its purpose and artifacts, and `ProgramWorkspace` adds the external
  program, which `MadGraphWorkspace`, `ShowerWorkspace` and
  `SimulationWorkspace` now name in class attributes. (#23)
- `StageOutcome` lives in `omphjc.jobs.manifest` beside `StageRecord`, whose
  `running`, `failed` and `done` constructors build the record of each state.
  (#24)
- `omphjc.jobs.Job.require_done` returns the record of a finished stage or
  says which command to run first. (#24)
- Installing omphjc also installs numpy, awkward and uproot. (#39)
- Installing omphjc from source compiles its C++ extension, which needs a C++17
  standard library that formats floating-point numbers. (#41)
- Reading a Delphes card in a Python without `tkinter` says that Tcl support is
  needed and points to the README. (#42)
- `omphjc.jobs` names its types after tasks: `TaskRecord`, `TaskOutcome`,
  `Job.run_task` and `Job.task_dir` replace `StageRecord`, `StageOutcome`,
  `Job.run_stage` and `Job.stage_dir`. (#48)
- A stage's record in `manifest.json` holds what the stage made under
  `result`: its outputs by name, an event file with its format and event
  count, and its metadata (`omphjc.jobs.TaskResult`). (#49)
- `omphjc check-cards` and `omphjc delphes compare` report an item that only
  one side holds as `missing <item>: <value>` or `unexpected <item>: <value>`,
  and `Difference` holds `None` as the value of the side that lacks it. (#53)
- `Banner` holds its cards as `RunCard`, `ProcCard`, `SLHACard` and
  `MadSpinCard` objects, whose `from_text` and `differences` methods replace
  the `parse_*` and `compare_*` functions of the MadGraph cards. (#54)
- `omphjc check-cards` names each difference by its card, as in
  `madspin_card.decay`, and reports a MadSpin card that only one side has as
  a missing or an unexpected card. (#54)
- A `DataFile` class states `format_name` and `record_version` in place of
  `record_scheme`, and a fingerprint starts with both, as in `run_card-v1:`.
  (#54)
- `compare_process` and `compare_all` are in `omphjc.validation.cards`,
  which replaces `omphjc.tools.madgraph.reference`. (#54)
- `omphjc simulate` records the number of events counted in `delphes.root`
  in place of the shower's count. (#56)
- `omphjc shower` and `omphjc simulate` compare the fingerprint of the events
  they read, recorded in `manifest.json` with each stage's event file, in
  place of the cards and settings of the stage before. (#57)
- `PythiaCmnd` and `DelphesCard` hold the Pythia command file and the
  Delphes card, and their methods replace the functions of
  `omphjc.tools.pythia.cmnd` and `omphjc.tools.delphes.card` that parsed,
  wrote and compared them. (#58)
- `omphjc generate`, `omphjc shower` and `omphjc simulate` refuse a stage
  with an output that no longer has the size recorded in `manifest.json`,
  until the stage is run again with `--force`. (#59)
- The record of a task and the types of its result live in
  `omphjc.jobs.records`. (#60)
- `Job.check_stage`, `StageCheck` and `StageStatus` are renamed `Job.task`,
  `Task` and `TaskStatus`, in `omphjc.jobs.task`, the former
  `omphjc.jobs.records`. (#64)
- Each stage keeps its record in `<stage>/task.json`, read through
  `Job.task_record`, and `manifest.json` is an index of the stages;
  `Job.manifest` is removed and a job of an earlier version is run again
  from `omphjc generate --force`. (#65)
- `omphjc generate`, `omphjc shower` and `omphjc simulate` refuse a task that
  ran with other parameters by naming each parameter that differs, a nested
  one by its dotted path, with the value it ran with and the current one.
  (#66)
- `task.json` keeps every run of a task, with its status, times, log and
  usage, and the reports of `omphjc generate`, `omphjc shower` and
  `omphjc simulate` count the runs of a task run more than once. (#67)
- Each run of a task writes its log in `<stage>/runs/<run_id>/`, named by
  the run ID that `task.json` records and the stage reports print first, and
  later runs leave it in place. (#68)

### Fixed

- A model copy cut short in `generate_events` is sealed with the run's other
  artifacts, so the next run deletes it instead of setting it aside. (#20)
- `omphjc generate` derives the seeds of MadGraph's unweighting and MadSpin's
  decays from the job seed instead of one fixed seed shared by every job. A
  seed therefore no longer reproduces events generated before this change.
  (#30)
- `omphjc generate` raises the open-file limit while MadGraph runs, so that a
  run with many channels also unweights its events from the job seed. (#30)
- `omphjc simulate` seeds Delphes with the job seed also when the detector card
  sets `RandomSeed` itself. (#37)
- On Windows, rerunning a stage sets aside what the earlier run left instead of
  deleting it, since a folder's `ctime` there does not show changes. (#40)
- `ProcCard` joins the lines of a command that MadGraph writes on several
  lines, so the fingerprint of an event file does not depend on the directory
  of its job. (#52)
- `read_catalogue` raises a `CatalogueError` that names the file for a
  malformed catalogue, including `definitions` or `processes` that are not
  lists of strings, and `omphjc --catalogue` reports it without a traceback.
  (#62)
- `read_catalogue` refuses a top-level key other than `common` and
  `processes`, and a `matching` that is not a boolean, so a quoted `"no"` no
  longer turns matching on. (#63)
