import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.processes import ProcessSpec, default_catalogue


@pytest.fixture(scope="session")
def specs() -> Mapping[str, ProcessSpec]:
    return default_catalogue()


BANNER = Path(__file__).parent / "data" / "madgraph" / "TTBar_banner.txt"

# Stands in for MadGraph's bin/mg5_aMC: it follows the script it is given,
# writes the files MadGraph would write, and, like MadGraph, exits with status
# 0 when a command fails (FAKE_MG5_FAIL names the command to fail). With
# FAKE_MG5_FAIL=hang it never finishes.
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
def mg5_path(tmp_path: Path) -> Path:
    program = tmp_path / "bin" / "mg5_aMC"
    program.parent.mkdir(exist_ok=True)
    program.write_text(FAKE_MG5.format(python=sys.executable, banner=BANNER))
    program.chmod(0o755)
    return program


# Stands in for Delphes's DelphesPythia8: it takes the card, the Pythia command
# file and the output file, reads the LHE file the command file names as text,
# prints Pythia's banner and event statistics, and writes the output. Like
# DelphesPythia8 it refuses an existing output file and, with
# FAKE_DP8_FAIL=abort, gives up with exit status 0. FAKE_DP8_FAIL=exit fails
# with status 1; FAKE_DP8_FAIL=hang never finishes.
FAKE_DELPHES_PYTHIA8 = """\
#!{python}
import os
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
Path(output).write_bytes(b"ROOT fake")
print(" *-------  PYTHIA Event and Cross Section Statistics  -----*")
print(f" | Les Houches User Process(es)                  9999 | {{tried:11d}} {{tried:10d}} {{accepted:10d}} |   1.000e-09  0.000e+00 |")
print(f" | {{'sum':<50}} | {{tried:11d}} {{tried:10d}} {{accepted:10d}} |   1.000e-09  0.000e+00 |")
print(" *-------  End PYTHIA Event and Cross Section Statistics -----*")
print("** Exiting...")
"""


@pytest.fixture
def delphes_pythia8_path(tmp_path: Path) -> Path:
    program = tmp_path / "bin" / "DelphesPythia8"
    program.parent.mkdir(exist_ok=True)
    program.write_text(FAKE_DELPHES_PYTHIA8.format(python=sys.executable))
    program.chmod(0o755)
    return program


# Stands in for Delphes's DelphesROOT: it takes the card, the output file and
# the input files, reads the card, requires every input to exist, and writes
# the output. Like DelphesROOT it refuses an existing output file and exits
# with status 1 when it cannot open a file. FAKE_DROOT_FAIL=exit fails with
# status 1; FAKE_DROOT_FAIL=hang never finishes.
FAKE_DELPHES_ROOT = """\
#!{python}
import os
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
Path(output).write_bytes(b"ROOT fake")
print("** Exiting...")
"""


@pytest.fixture
def delphes_root_path(tmp_path: Path) -> Path:
    program = tmp_path / "bin" / "DelphesROOT"
    program.parent.mkdir(exist_ok=True)
    program.write_text(FAKE_DELPHES_ROOT.format(python=sys.executable))
    program.chmod(0o755)
    return program
