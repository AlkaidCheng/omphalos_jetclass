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
