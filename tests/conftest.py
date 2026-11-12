import hashlib
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest

from omphjc.processes import ProcessSpec, default_catalogue


@pytest.fixture(scope="session")
def specs() -> Mapping[str, ProcessSpec]:
    return default_catalogue()


LOW_OPEN_FILE_LIMIT = 256


@pytest.fixture
def low_open_file_limit() -> Iterator[int]:
    """Lower the soft limit on open files to LOW_OPEN_FILE_LIMIT for the test."""
    resource = pytest.importorskip("resource")
    limits = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (LOW_OPEN_FILE_LIMIT, limits[1]))
    yield LOW_OPEN_FILE_LIMIT
    resource.setrlimit(resource.RLIMIT_NOFILE, limits)


@pytest.fixture(scope="session")
def fake_program_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("fake_programs")


@pytest.fixture
def link_fake_program(
    fake_program_store: Path, tmp_path: Path
) -> Callable[[str, str], Path]:
    """Return a function that puts the program `text` at ``tmp_path/bin/<name>``.

    Each program is written once per session and hard-linked into the test's
    directory, since on macOS the first run of a newly written executable takes
    about 0.15 s longer.
    """

    def link(name: str, text: str) -> Path:
        source = fake_program_store / hashlib.sha256(text.encode()).hexdigest() / name
        if not source.exists():
            source.parent.mkdir()
            source.write_text(text)
            source.chmod(0o755)
        program = tmp_path / "bin" / name
        program.parent.mkdir(exist_ok=True)
        os.link(source, program)
        return program

    return link


TESTS_DIR = Path(__file__).parent
BANNER = TESTS_DIR / "data" / "madgraph" / "TTBar_banner.txt"

# Stands in for MadGraph's bin/mg5_aMC: it follows the script it is given,
# writes the files MadGraph would write, and, like MadGraph, exits with status
# 0 when a command fails (FAKE_MG5_FAIL names the command to fail). With
# FAKE_MG5_FAIL=hang it never finishes. A launch prints the soft limit on open
# files it runs with.
FAKE_MG5 = """\
#!{python}
import gzip
import os
import re
import sys
import time
from pathlib import Path

lines = Path(sys.argv[1]).read_text().splitlines()
fail = os.environ.get("FAKE_MG5_FAIL", "")
if fail == "exit":
    sys.exit(3)
if fail == "hang":
    time.sleep(60)
for line in lines:
    word, _, argument = line.partition(" ")
    if word == "import":
        model = argument.split()[-1].rsplit("-", 1)[0]
        if Path(model).is_dir():
            Path(model, "py3_model.pkl").write_text("cache")
    elif word in ("output", "launch") and fail == word:
        print(f"Command {{word}} interrupted with error")
        sys.exit(0)
    elif word == "output":
        Path(argument, "Cards").mkdir(parents=True)
        Path(argument, "Cards", "me5_configuration.txt").write_text("# nb_core = None\\n")
        Path(argument, "Cards", "proc_card_mg5.dat").write_text("\\n".join(lines))
        Path(argument, "Events").mkdir()
    elif word == "launch":
        import resource
        print("open files", resource.getrlimit(resource.RLIMIT_NOFILE)[0])
        process = Path(argument)
        seed = next(int(l.split()[2]) for l in lines if l.startswith("set iseed"))
        banner = re.sub(r" 42 = iseed", f" {{seed}} = iseed", Path("{banner}").read_text())
        runs = ["run_01"]
        if "madspin=ON" in lines:
            if not (process / "Cards" / "madspin_card.dat").is_file():
                sys.exit("MadSpin card missing")
            runs.append("run_01_decayed_1")
        for run in runs:
            (process / "Events" / run).mkdir()
            with gzip.open(process / "Events" / run / "unweighted_events.lhe.gz", "wt") as out:
                out.write(banner + "<event>\\n</event>\\n</LesHouchesEvents>\\n")
print("MadGraph done")
"""


@pytest.fixture
def mg5_path(link_fake_program: Callable[[str, str], Path]) -> Path:
    return link_fake_program(
        "mg5_aMC", FAKE_MG5.format(python=sys.executable, banner=BANNER)
    )


# Stands in for Delphes's DelphesPythia8: it takes the card, the Pythia command
# file and the output file, reads the LHE file the command file names as text,
# prints Pythia's banner and event statistics, and writes a file with the
# layout of a Delphes ROOT file (tests/delphes_records.py) that holds one entry
# for each event it accepts. It writes that file with uproot once for each
# number of events in a test session and copies it afterwards, since loading
# uproot takes about 0.3 s. Like DelphesPythia8 it refuses an existing output
# file and, with FAKE_DP8_FAIL=abort, gives up with exit status 0.
# FAKE_DP8_FAIL=exit fails with status 1; FAKE_DP8_FAIL=hang never finishes.
FAKE_DELPHES_PYTHIA8 = """\
#!{python}
import os
import shutil
import sys
import time
from pathlib import Path

if len(sys.argv) != 4:
    print("Usage: DelphesPythia8 config_file pythia_card output_file")
    sys.exit(1)
card, cmnd, output = sys.argv[1:]
fail = os.environ.get("FAKE_DP8_FAIL", "")
if fail == "hang":
    time.sleep(60)
if fail == "exit":
    print("** ERROR: can't read Pythia8 configuration file", file=sys.stderr)
    sys.exit(1)
if Path(output).exists():
    print(f"** ERROR: can't create output file {{output}}", file=sys.stderr)
    sys.exit(1)
settings = {{}}
for line in Path(cmnd).read_text().splitlines():
    line = line.split("!")[0].strip()
    if "=" in line:
        key, _, value = line.partition("=")
        settings[key.strip().lower()] = value.strip()
Path(card).read_text()
print(" |  |    This is PYTHIA version 8.318      |  | ")
lhe = Path(settings["beams:lhef"])
if not lhe.is_file():
    sys.exit("Abort from Pythia::init: Les Houches Event File not found")
events = lhe.read_text().count("<event>")
tried = min(events, int(settings["main:numberofevents"]))
if fail == "abort":
    print("Event generation aborted prematurely, owing to error!")
    sys.exit(0)
matched = settings.get("jetmatching:merge", "off") == "on"
accepted = tried - tried // 2 if matched else tried
record = Path({records_dir!r}) / f"delphes_{{accepted}}_events.root"
if not record.exists():
    sys.path.insert(0, {tests_dir!r})
    import awkward as ak
    import numpy as np
    from delphes_records import write_delphes_file

    pids = np.tile([2212, 2212, 211], accepted)
    written = record.with_name(f"{{record.name}}.{{os.getpid()}}")
    write_delphes_file(written, {{"PID": ak.unflatten(pids, np.full(accepted, 3))}})
    os.replace(written, record)
shutil.copyfile(record, output)
print(" *-------  PYTHIA Event and Cross Section Statistics  -----*")
print(f" | Les Houches User Process(es)                  9999 | {{tried:11d}} {{tried:10d}} {{accepted:10d}} |   1.000e-09  0.000e+00 |")
print(f" | {{'sum':<50}} | {{tried:11d}} {{tried:10d}} {{accepted:10d}} |   1.000e-09  0.000e+00 |")
print(" *-------  End PYTHIA Event and Cross Section Statistics -----*")
print("** Exiting...")
"""


@pytest.fixture
def delphes_pythia8_path(
    link_fake_program: Callable[[str, str], Path], fake_program_store: Path
) -> Path:
    return link_fake_program(
        "DelphesPythia8",
        FAKE_DELPHES_PYTHIA8.format(
            python=sys.executable,
            tests_dir=str(TESTS_DIR),
            records_dir=str(fake_program_store),
        ),
    )


# Stands in for Delphes's DelphesROOT: it takes the card, the output file and
# the input files, reads the card, requires every input to exist, and copies
# the first input to the output, so the output holds as many events as that
# input. Like DelphesROOT it refuses an existing output file and exits with
# status 1 when it cannot open a file. FAKE_DROOT_FAIL=exit fails with status
# 1; FAKE_DROOT_FAIL=hang never finishes.
FAKE_DELPHES_ROOT = """\
#!{python}
import os
import shutil
import sys
import time
from pathlib import Path

if len(sys.argv) < 4:
    print("Usage: DelphesROOT config_file output_file input_file(s)")
    sys.exit(1)
card, output, *inputs = sys.argv[1:]
fail = os.environ.get("FAKE_DROOT_FAIL", "")
if fail == "hang":
    time.sleep(60)
if fail == "exit":
    print(f"** ERROR: can't open {{card}}", file=sys.stderr)
    sys.exit(1)
if Path(output).exists():
    print(f"** ERROR: can't open {{output}}", file=sys.stderr)
    sys.exit(1)
Path(card).read_text()
for name in inputs:
    print(f"** Reading {{name}}")
    if not Path(name).is_file():
        print(f"** ERROR: can't open {{name}}", file=sys.stderr)
        sys.exit(1)
shutil.copyfile(inputs[0], output)
print("** Exiting...")
"""


@pytest.fixture
def delphes_root_path(link_fake_program: Callable[[str, str], Path]) -> Path:
    return link_fake_program(
        "DelphesROOT", FAKE_DELPHES_ROOT.format(python=sys.executable)
    )
