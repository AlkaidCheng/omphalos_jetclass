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
def mg5(tmp_path: Path) -> Path:
    program = tmp_path / "bin" / "mg5_aMC"
    program.parent.mkdir()
    program.write_text(FAKE_MG5.format(python=sys.executable, banner=BANNER))
    program.chmod(0o755)
    return program
