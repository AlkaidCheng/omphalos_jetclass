# Provenance of the packaged resources

All hashes are SHA-256.

## jetclass/<process>/

Cards extracted from the gridpack tarballs of jet-universe/jetclass_generation
at commit ae722ea (MIT, see `jetclass/LICENSE`):

- repository at that commit:
  https://github.com/jet-universe/jetclass_generation/tree/ae722ea560efa01c6ed814c72d15b7cdafdf3449
- gridpacks:
  https://github.com/jet-universe/jetclass_generation/tree/ae722ea560efa01c6ed814c72d15b7cdafdf3449/gridpacks

Each `<process>/` holds `proc_card_mg5.dat`, `run_card.dat`, `param_card.dat`,
`pythia8_card.dat` and `run_<process>.mg5` from `gridpacks/<process>.tar.gz`,
plus `madspin_card.dat` for the two top processes. The gridpacks were produced
with MadGraph5_aMC@NLO 3.1.1.

## delphes/delphes_card_JetClass.tcl

`delphes_card.tcl` from the same commit:
https://github.com/jet-universe/jetclass_generation/blob/ae722ea560efa01c6ed814c72d15b7cdafdf3449/delphes_card.tcl

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

## Hashes

```
bf205dd95fe9fe0031847d76edf70a6a8e125ed65141ea9c479aef453588ed1c  delphes/delphes_card_JetClass.tcl
121806cb4d171d7a8f8974001a3eb4025ecc6ff11b792a625b734e30a0baaa47  models/heft/__init__.py
f252a54cf4f7605dea8dcdf1013169438ece67185acb11df78a94b569eb997ad  models/heft/coupling_orders.py
9bb282906d42693cd3072cbc2f36a98e508d511b868cc6ac66fe84fdfc4c5431  models/heft/couplings.py
b4cbc7f905b5b539e37e4c4ed0942b3a70dc4c8ada71ba4205e8dcf914be3523  models/heft/function_library.py
a40e7da2e3a812852a3b82e544489bdcbb44891634f2fac321f33c1e1061de19  models/heft/lorentz.py
1867d8a94bb6106ddd314a5108ed7ceaf2fa2d9abecff6fbbfde8b064fe8aabe  models/heft/object_library.py
3bb1c0e4bf8999942696be42b91d95d96595881c4de8068f21b9e0c93b8a392d  models/heft/parameters.py
061b7dee642f8027742445f5778c8564ced81745955bbc5b8674ad201cb5abb1  models/heft/particles.py
9b8ca6e8d680e57988c164bce88b14db8ef56167117d81f9f6198925f65d4f9a  models/heft/vertices.py
b1fefa31387db6d35631469c59ffbf87539093c34989f123dc63a98b46742462  models/heft/write_param_card.py
9393706620b2b64672424e31042525b1fd42bcd0047d335813083f211c88487e  models/heft/restrict_ckm.dat
ab813ab6cc6c2762aafee36f332a0a0db69871bf935924b37a019067938a2d0e  models/heft/restrict_default.dat
141ff37e8397559d64c818676424539188a738601a2abeab5034bd9b3bb02dab  models/heft/restrict_no_b_mass.dat
5b16389c32fe6d25761f6b7172945fc8f393fad7a44126d0072f9a0b42403a46  models/heft/restrict_no_masses.dat
eb11ec324e77bc78b330e610c1a198557548f45c28f3ff802b3665b6ad6259a1  models/heft/restrict_no_tau_mass.dat
934782a84ea7301e85680e24b83f8ee5f36bdb181fbc90483842bc789f61bfc9  models/heft/restrict_zeromass_ckm.dat
121806cb4d171d7a8f8974001a3eb4025ecc6ff11b792a625b734e30a0baaa47  models/heft_c_mass_jetclass/__init__.py
f252a54cf4f7605dea8dcdf1013169438ece67185acb11df78a94b569eb997ad  models/heft_c_mass_jetclass/coupling_orders.py
8b1621d1ded6fc57bc7ccfa1177cd71995f0078f4dbf056823071ec4e1e9e9c5  models/heft_c_mass_jetclass/couplings.py
b4cbc7f905b5b539e37e4c4ed0942b3a70dc4c8ada71ba4205e8dcf914be3523  models/heft_c_mass_jetclass/function_library.py
a40e7da2e3a812852a3b82e544489bdcbb44891634f2fac321f33c1e1061de19  models/heft_c_mass_jetclass/lorentz.py
1867d8a94bb6106ddd314a5108ed7ceaf2fa2d9abecff6fbbfde8b064fe8aabe  models/heft_c_mass_jetclass/object_library.py
b4bb7449da9f568495d6b1746113c0322edd5edb6f89fef2b6cd3f53fecb4f30  models/heft_c_mass_jetclass/parameters.py
041c4c89bbd9ba7f064cd76eaeebc73922483c6c59020da80b065bfe8c6fe7ad  models/heft_c_mass_jetclass/particles.py
d60312d438c8682893f6b4fac3f7b865f38fb44fdbc6d36fc93b7163c4a0f2fe  models/heft_c_mass_jetclass/restrict_default.dat
e3dc4daa959d2eed94af82d123994f95661cd26f773f8e2c25a3e36e99f792a3  models/heft_c_mass_jetclass/vertices.py
b1fefa31387db6d35631469c59ffbf87539093c34989f123dc63a98b46742462  models/heft_c_mass_jetclass/write_param_card.py
```
