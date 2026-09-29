# Test fixtures

## pythia/

`HToBB_mg311_effective.cmd` and `ZJetsToNuNu_mg311_effective.cmd` are the
Pythia command files (`tag_1_pythia8.cmd`) that MadGraph5_aMC@NLO 3.1.1 writes
when it showers the official JetClass gridpacks: the official `pythia8_card.dat`
after `setup_Pythia8RunAndCard` has filled in the values it derives from the
run card. The production did not publish these files; they were reconstructed
by replaying that routine of MadGraph 3.1.1 on the official cards, and the
result was checked against the file sizes printed in the production logs.
HToBB stands for the nine unmatched processes, whose cards are identical
except for the input file name; ZJetsToNuNu is the MLM-matched one.

## madgraph/

`TTBar_banner.txt` is the banner of one MadGraph5_aMC@NLO 3.5.7 run of the
official TTBar cards (10 000 events, `iseed = 42`) after MadSpin, reduced to
the blocks the banner reader consumes: the version, the run card as used, the
generation summary, the MadSpin commands and the `<init>` block that MadGraph
copies into the event file. The process and parameter cards are omitted.
