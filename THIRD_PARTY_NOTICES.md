# Third-party notices

`LICENSE` (MIT) covers **BindMaster's own source** — the CLI, the configurator,
the TUI, the installers and the `binder-comparison` package. It does **not**
cover the third-party assets listed below, which are redistributed inside this
repository and carry their own terms.

This file exists because the repository ships several binaries and data files
that are not ours, under a top-level MIT licence that says nothing about them.
Anyone cloning, forking, packaging or redistributing this repository inherits
those terms whether or not they read this file.

**Where a licence is marked "confirm with upstream" below, it has not been
verified from a licence file in-tree** — the vendored copy carries none. The
identification is from the artifact itself (version strings, copyright banners)
plus the upstream project it came from. Confirm before redistribution, and
especially before any commercial use.

---

## 1. Vendored — redistributed with every `git clone`

| Path | What it is | Version (verified in-tree) | Upstream | Licence |
|---|---|---|---|---|
| `Evaluator/tools/ngl/ngl-2.3.1.min.js` (1.3 MB) | NGL Viewer — the WebGL molecular viewer inlined into `report.html` and `epitope_map.html` | 2.3.1 (filename) | [nglviewer/ngl](https://github.com/nglviewer/ngl) | MIT (per upstream repository) |
| `Evaluator/tools/soluprot/` (≈51 MB, excluding the USEARCH binaries) | SoluProt 1.0 — sequence-only *E. coli* solubility predictor. Includes `soluprot.py`, `feature_scripts/`, the trained classifiers (`data/grad_clf_v1_tc.pkl`, `grad_clf_v1_tc_notmhmm.pkl`, `grad_best_clf_v1.pkl`) and the reference FASTA databases | 1.0 | Hon, Borko, Stourac et al., *SoluProt: prediction of soluble protein expression in Escherichia coli*, **Bioinformatics** 37(1), 2021. [doi:10.1093/bioinformatics/btaa1102](https://doi.org/10.1093/bioinformatics/btaa1102) · Loschmidt Laboratories, Masaryk University · <https://loschmidt.chemi.muni.cz/soluprot/> | **Not stated in the vendored copy — confirm with upstream** |
| `tools/aarch64/DAlphaBall.gcc` (325 KB) | Alpha-ball surface/SASA scoring binary that BindCraft calls; ARM64 build, installed to `BindCraft/functions/DAlphaBall.gcc` | ARM64 Fortran build (`libgfortran.so.5`) | Rosetta / RosettaCommons `DAlphaBall` component, as required by [martinpacesa/BindCraft](https://github.com/martinpacesa/BindCraft) | **Rosetta terms — confirm with upstream.** Rosetta is free for academic and non-commercial use; commercial use requires a separate licence from UW TechTransfer / Rosetta Commons |
| `tools/aarch64/dssp` (9.4 MB) | `mkdssp` — secondary-structure assignment, called by BindCraft; ARM64 build, installed to `BindCraft/functions/dssp` | `mkdssp 3.1.4`, `DSSP, CMBI version 3.1.4` (binary strings) | [cmbi/dssp](https://github.com/cmbi/dssp) | Boost Software License 1.0 (per upstream, DSSP 3.x) — **confirm with upstream** |

The two `tools/aarch64/` binaries exist because BindCraft ships x86_64 builds
only; they are the same components BindCraft expects, rebuilt for ARM64, and
are copied into `BindCraft/functions/` by `install/install_aarch.sh`.

## 2. USEARCH — removed from the tree, built at install time

USEARCH v12 is **GPLv3**. It used to be committed here as `usearch.x86_64` and
`usearch.aarch64`, which put a copyleft redistribution obligation on every clone
of this MIT-licensed repository. Both binaries have been **removed**. Both
installers now build USEARCH v12 from source
([rcedgar/usearch12](https://github.com/rcedgar/usearch12)) as part of
`--tool soluprot`, so the binary is produced on the user's machine and is never
redistributed by us.

Two notes for anyone auditing this:

- **The binaries remain in git history** (they entered in `b8d2b87`). Removing
  them from `HEAD` stops future release tarballs and source archives from
  carrying them, but a full `git clone` still fetches them from history. Ending
  the obligation completely would need a history rewrite, which breaks every
  existing clone — that trade-off has not been taken.
- **Do not substitute the drive5 build.** `https://drive5.com/usearch/` serves
  the older proprietary 32-bit USEARCH under an academic-use-only licence. That
  is *stricter* than the GPLv3 v12 it would replace, and it is not the version
  SoluProt is patched for (`usearch_global` vs `search_global`). Both installers
  now say so where they used to recommend it.

Verified equivalent before removal: the source build and the previously
committed binary, given SoluProt's exact `-usearch_global` command against
SoluProt's own *E. coli* reference database, produce **byte-identical** output.

## 3. Not vendored — fetched at install time

The seven design tools and the refolding engines are **cloned or pip-installed
by the installer at install time**, not redistributed here. Their licences are
their own and travel with them; consult each project directly. They are listed
so the full dependency surface is visible in one place:

| Component | Upstream |
|---|---|
| BindCraft | [martinpacesa/BindCraft](https://github.com/martinpacesa/BindCraft) |
| BoltzGen | [HannesStark/boltzgen](https://github.com/HannesStark/boltzgen) |
| Mosaic | [escalante-bio/mosaic](https://github.com/escalante-bio/mosaic) |
| PXDesign / Protenix | [bytedance/PXDesign](https://github.com/bytedance/PXDesign) |
| Proteina-Complexa | [NVIDIA-Digital-Bio/proteina-complexa](https://github.com/NVIDIA-Digital-Bio/proteina-complexa) |
| Protein-Hunter (vendored Boltz-2 / Chai-1) | Cho et al. 2025 |
| RFD3 / `rc-foundry` | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) — BSD-3 |
| AlphaFold 3 v3.0.2 | [google-deepmind/alphafold3](https://github.com/google-deepmind/alphafold3) — weights are **gated**; obtain them from DeepMind under their terms |
| ESMFold2 | Biohub `esm` |
| PyRosetta (BindCraft, Protein-Hunter) | Academic/non-commercial free; commercial use requires a licence |

Model weights — AF2 parameters, Boltz-1/Boltz-2 checkpoints, RFD3 and
ProteinMPNN checkpoints, ESMFold2 weights — are downloaded at install or first
run and are **not** in this repository. Each carries its own terms.

---

*Corrections welcome. If you own one of the components above and this entry is
wrong or incomplete, please open an issue.*
