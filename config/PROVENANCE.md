# Provenance of the shipped configuration

`checksums.json` records the SHA-256 hash of every file listed here. Files
under `references/` are kept unchanged as the official reference; the files a
run reads (`madspin/`, `delphes/`) start as byte-identical copies of them and
may be edited in an exported configuration.

## references/jetclass/

Taken from jet-universe/jetclass_generation at commit ae722ea (MIT, see
`references/jetclass/LICENSE`):

- repository at that commit:
  https://github.com/jet-universe/jetclass_generation/tree/ae722ea560efa01c6ed814c72d15b7cdafdf3449
- gridpacks:
  https://github.com/jet-universe/jetclass_generation/tree/ae722ea560efa01c6ed814c72d15b7cdafdf3449/gridpacks

Each `<process>/` holds `proc_card_mg5.dat`, `run_card.dat`, `param_card.dat`,
`pythia8_card.dat` and `run_<process>.mg5` from `gridpacks/<process>.tar.gz`,
plus `madspin_card.dat` for the two top processes. The gridpacks were produced
with MadGraph5_aMC@NLO 3.1.1.

`delphes_card.tcl` is the repository's Delphes card:
https://github.com/jet-universe/jetclass_generation/blob/ae722ea560efa01c6ed814c72d15b7cdafdf3449/delphes_card.tcl

## references/delphes/

The CMS card distributed with Delphes, from which the JetClass card is adapted
(section 2 of https://arxiv.org/abs/2202.03772):

- `delphes_card_CMS.tcl` is `cards/delphes_card_CMS.tcl` of Delphes 3.5.0,
  https://github.com/delphes/delphes/blob/3.5.0/cards/delphes_card_CMS.tcl;
  the file is byte-identical in Delphes 3.4.2 and 3.5.1.
- `LICENSE` and `COPYING` are Delphes's license files at the same tag. Delphes
  is distributed under the GNU General Public License version 3 or later, and
  the card keeps that license.

## madspin/

`TTBar.dat` and `TTBarLep.dat` are copies of
`references/jetclass/TTBar/madspin_card.dat` and
`references/jetclass/TTBarLep/madspin_card.dat`.

## delphes/

`delphes_card_JetClass.tcl` is a copy of `references/jetclass/delphes_card.tcl`.

## models/heft/

The MadGraph5_aMC@NLO `heft` model as distributed by the MadGraph model
database, http://madgraph.phys.ucl.ac.be/Downloads/models/heft.tgz, without
its log and cached pickle. Its `restrict_default.dat` and `restrict_ckm.dat`
are byte-identical to the restriction cards recorded inside the HToBB, HToGG,
HToWW4Q and HToWW2Q1L gridpacks (`bin/internal/ufomodel/restrict_default.dat`).

## models/heft_c_mass_jetclass/

The `bin/internal/ufomodel` directory of the HToCC gridpack
(`gridpacks/HToCC.tar.gz` at the commit above): the heft model with a massive
charm quark and a charm Yukawa coupling (MC = ymc = 1.55 GeV), already
restricted, as MadGraph wrote it when the gridpack was produced.
