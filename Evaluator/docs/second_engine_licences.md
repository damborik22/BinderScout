# Licence record: candidate engines for the AF3 slot

Purpose: a dated record of what the primary sources said about commercial use of each
candidate to replace AlphaFold 3 (AF3) as the second refold engine. It is meant for a
company's legal reviewer and for the text the installer shows before it fetches an engine.

**This is not legal advice.** Each row is a snapshot of what the primary sources said on the
date read (2026-11-05). Quotes are copied from the raw files or pages named in the Source
column; where a page was only summarised by a tool, that is stated in the engine section.
Anything not confirmed from a primary source is marked "unverified". Licences and README text
change: re-read before relying on a row after a release.

Pins read (so a reviewer can fetch the same text): OpenFold3 tag `0.5.1` (`795e45b`), default
branch `main` (`37be44e`); Protenix tag `v1.1.0` (`4f1eedf`), tag `v2.0.0` (`a758b89`), `main`
(`85767b8`); Chai-1 tag `v0.6.1` (`8d5ac0f`); Foundry (RF3) tag `v0.2.0` (`3967144`),
default branch `production` (`0d0b0ba`), licence commit `69d5f73`; IntelliFold `main`
(`bc84487`) and tag `v2.0.4` (`4e420db`); AlphaFold 3 tag `v3.0.3` (`7b197fe`).

## Table

| Engine and version read | Code licence | Weights licence | Source URL(s) | Verbatim operative quote(s) | Date read | Verdict (commercial use) |
|---|---|---|---|---|---|---|
| OpenFold3, release 0.5.1 (default weights OpenBind-0, file `of3-ob-2025-06-30-174k.pt`) | Apache-2.0 | Apache-2.0 per the OpenBind announcement and the OpenBind tools page only; no licence file beside the weights; bucket-root file is CC BY 4.0 | https://github.com/aqlaboratory/openfold-3/blob/0.5.1/LICENSE ; https://github.com/aqlaboratory/openfold-3/blob/0.5.1/README.md ; https://openbind.uk/news/blog-openbind-0-advancing-open-molecular-structure-prediction/ ; https://openbind.uk/documents-and-tools/ ; https://openfold3-data.s3.amazonaws.com/LICENSE ; https://huggingface.co/OpenFold/OpenFold3 | README: "our repository is freely available for academic and commercial use under the Apache 2.0 license." Blog (2026-08-21): "OB0 is fully open source under the Apache 2.0 licence: the training data, code, model weights, and training recipes are publicly available." Tools page: "Contains the training code, model weights, and training recipes, released under Apache 2.0." | 2026-11-05 | yes (weights licence rests on the announcement; see caveats) |
| Protenix, tag v1.1.0 with model `protenix_base_default_v1.0.0` (v1.x only) | Apache-2.0 | Apache-2.0 for v1.x per the README; v2 weights are explicitly proprietary and are excluded | https://github.com/bytedance/Protenix/blob/v1.1.0/README.md ; https://github.com/bytedance/Protenix/blob/v2.0.0/README.md ; https://github.com/bytedance/Protenix/blob/v1.1.0/LICENSE ; https://github.com/bytedance/Protenix/blob/main/README.md | v1.1.0 README: "The Protenix project including both code and model parameters is released under the [Apache 2.0 License](./LICENSE). It is free for both academic research and commercial use." `main` README, 2026-04-08 entry: "The model weights of Protenix-v2 are proprietary and confidential information of the rights holder, are not released under any open-source license, and may not be reproduced, distributed, sublicensed, disclosed, or otherwise transferred to any third party in any form without the express prior written consent of the rights holder." | 2026-11-05 | yes for v1.x; no for v2. Caveat: `pip install protenix` hard-requires NVIDIA proprietary cuEquivariance wheels (see "Corrections from the live smokes") |
| Chai-1, tag v0.6.1 | Apache-2.0 | Apache-2.0 per README and Hugging Face metadata | https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/README.md ; https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/LICENSE ; https://huggingface.co/chaidiscovery/chai-1 | README: "Chai-1 is released under an Apache 2.0 License (both code and model weights), which means it can be used for both academic and commerical purposes, including for drug discovery." (spelling as in source). Hugging Face card metadata: `license: apache-2.0` | 2026-11-05 | yes |
| RF3 (RoseTTAFold3) in RosettaCommons Foundry (`rc-foundry`), default branch `production` at `0d0b0ba`; v0.2.0 tag and PyPI 0.2.0 checked separately | BSD-3-Clause | BSD-3-Clause, stated only on the `production` branch (commit `69d5f73`, 2026-10-13); the sentence is absent from tag v0.2.0 and from the PyPI 0.2.0 sdist | https://github.com/RosettaCommons/foundry/blob/production/LICENSE.md ; https://github.com/RosettaCommons/foundry/blob/v0.2.0/LICENSE.md ; https://github.com/RosettaCommons/foundry/commit/69d5f735f272b78b6b23c230abba849f18315234 ; https://pypi.org/project/rc-foundry/0.2.0/ ; https://pypi.org/project/cuequivariance-ops-cu12/ | `production` LICENSE.md: "This copyright and license covers both the source code and model weights referenced for download in the README file." Commit message of `69d5f73`: "Added clarification about the copyright and license coverage." | 2026-11-05 | yes for `production` text; unstated for the v0.2.0 / PyPI artifact we install (see caveats). Caveat: the `rf3` extra depends on proprietary NVIDIA cuEquivariance ops, disabled at runtime by the adapter (see "Corrections from the live smokes") |
| IntelliFold-2 (IntelliGen-AI), `main` at `bc84487` / tag v2.0.4; weights `intellifold_v2` | Apache-2.0 for the wrapper; vendors AF3 v3.0.3 code (Apache-2.0) | Apache-2.0 per README and Hugging Face metadata; AF3 weights not included | https://github.com/IntelliGen-AI/IntelliFold/blob/main/LICENSE ; https://github.com/IntelliGen-AI/IntelliFold/blob/main/NOTICE ; https://github.com/IntelliGen-AI/IntelliFold/blob/main/README.md ; https://huggingface.co/intelligenAI/intellifold ; https://github.com/google-deepmind/alphafold3/releases/tag/v3.0.3 ; https://github.com/google-deepmind/alphafold3/blob/main/OUTPUT_TERMS_OF_USE.md | README: "The IntelliFold project, including code and model parameters, is made available under the [Apache 2.0 License](./LICENSE), it is free for both academic research and commercial use." NOTICE: "This repository vendors and targets the Apache-2.0 release of AlphaFold 3 (v3.0.3)." AF3 Output Terms: "'AlphaFold 3 Code' means ... (iii) other code or machine learning model which incorporates, in full or in part, that code." | 2026-11-05 | unclear (see the clearance section) |

## Per-engine caveats

### OpenFold3

- Code: Apache-2.0 confirmed from the LICENSE file at `0.5.1` and the README sentence above.
- The OpenBind-0 weights are fetched by `setup_openfold` from the public S3 bucket `openfold3-data`
  (key `openfold3-parameters/of3-ob-2025-06-30-174k.pt`; registry in
  `openfold3/entry_points/parameters.py` at `0.5.1`). The bucket object was last modified
  2026-07-24.
- The weights licence rests on two vendor-run pages (the OpenBind blog of 2026-08-21 and the
  OpenBind documents-and-tools page). Neither the OpenFold3 README nor the OpenFold3 docs page
  `parameters_reference.html` says anything about a weights licence. Written confirmation from
  the OpenFold or OpenBind team would close this.
- No licence file sits beside the weights: `openfold3-parameters/LICENSE` returns 404. The bucket-root
  `LICENSE` is CC BY 4.0 (Attribution 4.0 International) and was last modified 2026-03-20, before
  OpenBind-0 was released, so it was not written for these weights. CC BY 4.0 and Apache-2.0 both
  permit commercial use, so the verdict is unaffected, but the two statements differ and attribution
  is required under CC BY 4.0.
- The 0.5.0 release note names the parameter set `openbind-2025-06-03-174k`; the registry and file
  name say `06-30`. Treat the file name and S3 key above as authoritative and re-check before pinning.
- The older preview weights on Hugging Face (`OpenFold/OpenFold3`) carry `license: apache-2.0`
  metadata and a gate prompt that says "The OpenFold3-preview model is released under Apache 2.0
  license." The gate is automatic on answering a form (company and role are asked). Those weights
  are deprecated and do not work with 0.5 or later.
- The blog says the OpenBind-0 training set is PDB structures to June 2025 ("OB0 is trained on data
  from the Protein Data Bank (PDB) through June 2025"); distillation sets were not checked here.

### Protenix

- Use v1.x model names explicitly in any installer text (`protenix_base_default_v1.0.0` or
  `protenix_base_20250630_v1.0.0`). Never rely on a default model name, because the `main` README
  now also lists `protenix-v2`.
- The "proprietary" sentence for v2 is on `main` (`85767b8`) in the 2026-04-08 entry. It is absent
  from the README at the `v2.0.0` tag (`a758b89`), whose only licence text is the general section.
- The `main` README still has a general License section that says "both code and model parameters"
  are Apache-2.0 and "free for both academic research and commercial use", which conflicts with the v2
  sentence in the same file. The v2 sentence is the specific one; the v1.x grant is read here as
  unaffected. A vendor confirmation that the general section covers v1.x only would remove the
  conflict.
- History: the initial commit (`d092a0d`, 2024-11-07) was CC BY-NC 4.0 ("This project, including code
  and model parameters are made available under the terms of the Creative Commons
  Attribution-NonCommercial 4.0 International License", with a commercial-licence contact). The
  relicense commit is `d779625` "Change License to Apache 2.0 License", 2024-12-13. All v1.x models
  (released 2026-02-05) postdate it.
- The model-weight download host was not checked for separate terms (unverified); the host is now named,
  and still unread, in "Corrections from the live smokes" below.

### Chai-1

- The licence rests on the README sentence and the Hugging Face card metadata only; no separate
  weights licence file exists. The package downloads weights from `chaiassets.com`, not from
  Hugging Face (`chai_lab/utils/paths.py` at v0.6.1), and that host's terms were not checked. The package
  also fetches one data file that is not a model weight; see "Corrections from the live smokes".
- At v0.6.1 the repository tree contains only a `LICENSE` file (Apache-2.0); no acceptable-use
  policy, NOTICE or terms file survived the relicense.
- History: at the 2024-11-26 snapshot (`44375d5`) `LICENSE.md` was the "Chai Discovery Community
  License Agreement" and the README said "To discuss commercial use of our models, reach us via
  email". Commit `0c7cfd5` "update LICENSE.md (#186)" on 2024-11-27 moved the project to Apache-2.0;
  `6c267f9` the same day moved the file to `LICENSE`. This matches the earlier-pass date.
- v0.6.1 (2025-03-18) is the latest GitHub release; `main` was at `c691da7`.

### RF3 (RoseTTAFold3 in Foundry)

- The weights sentence is in `production` LICENSE.md since commit `69d5f73` (2026-10-13). No tag or
  PyPI release contains it: the latest tag is `v0.2.0` (`3967144`, commit date 2026-06-03, PyPI
  upload 2026-06-05) and `production` is 31 commits ahead of it; `69d5f73` is 23 commits ahead of the tag. The `LICENSE.md` in the `v0.2.0` tag and in the
  `rc_foundry-0.2.0.tar.gz` sdist is plain BSD-3-Clause with no mention of model weights (the phrase
  "model weights" does not appear in the sdist file).
- `production` is the repository's default branch, so the sentence is the vendor's current public
  position. A pin to `v0.2.0` or PyPI 0.2.0 therefore has no written statement that BSD-3-Clause
  covers the weights; the weights are "referenced for download in the README" and a written
  confirmation from the Institute for Protein Design would close this for released artifacts.
- Our installer takes `rc-foundry` from PyPI, not from the `production` branch: `install/install.sh`
  pins `FOUNDRY_VERSION="0.1.9"` for RFD3 (extras `rfd3` and `mpnn`). The 0.2.0 sdist was read and has
  no weights sentence; the 0.1.9 sdist was not read, but it predates 0.2.0 and so predates commit
  `69d5f73`. For the artifact this repo installs today, the weights coverage is therefore unstated,
  not granted.
- Separate terms at the weight download location were not checked (unverified). The RF3 README does
  not mention a licence.
- GPU-kernel dependency: the `rf3` extra of `rc-foundry` requires `cuequivariance_ops_cu12`,
  `cuequivariance_ops_torch_cu12` and `cuequivariance_torch` on Linux (pyproject at `production` and
  at `v0.2.0`). `cuequivariance-torch` 0.13.0 is Apache-2.0 on PyPI. `cuequivariance-ops-cu12`
  0.13.0 ships under a proprietary NVIDIA licence, not an open-source one: its licence text begins
  "LICENSE AGREEMENT FOR NVIDIA MATH LIBRARIES SOFTWARE DEVELOPMENT KITS", and the grant (section 1.1)
  reads "NVIDIA hereby grants you a non-exclusive, non-transferable license, without the right to
  sublicense (except as expressly provided in this Agreement) to: Install and use the SDK, and
  Distribute the binary files, files identified as samples, and headers as incorporated into a
  software application that meets the distribution requirements indicated in this Agreement."
  Redistribution of that package inside our own distribution would need the distribution
  requirements checked; installing it from PyPI on the user's machine is a use of the SDK by that
  user. The Foundry README says the `rf3` extra (cuEquivariance) is Linux-only and skipped on macOS
  while RF3 still runs there, which suggests RF3 can run without it; whether it runs without it on
  Linux was not tested when this was first written (unverified). The live smoke has since observed it running
  with the ops disabled but installed; see "Corrections from the live smokes".
  Scope of what was read: only the preamble and the opening of section 1 (the section 1.1 grant and the start of
  1.2) of the NVIDIA agreement were read, not the whole agreement; its field-of-use and commercial-use terms beyond the grant are
  unstated here. If RF3 cannot run without that SDK on Linux (unverified), the effective licence of the
  engine on our platform is BSD-3-Clause plus a proprietary NVIDIA SDK licence, not BSD-3-Clause alone.
  (The installer does not install the `rf3` extra today; this applies once RF3 is added as a refold engine.)
- The weights were not re-checked against any licence of the training data.

### Relationship to AF3 for the other four candidates

OpenFold3 describes itself as "aiming to be a bitwise reproduction of DeepMind's AlphaFold3"; this
record read no OpenFold3, Protenix, Chai-1 or Foundry file that vendors AF3 source, and their licence
and README text does not refer to the AF3 weights or output terms. That is a statement about the
files read, not an audit of their code or training data (distillation sets were not checked).

## Corrections from the live smokes (read 2026-11-05)

Each candidate's refold adapter was run live on two real PD-L1 designs on 2026-11-05. The smokes
turned up facts the record above did not have. Where a statement is about something the smoke
observed, it says so; where it is about a primary-source page or file, the URL, the quote and the
date read (2026-11-05) are given. The verdicts in the table stand for each engine's own code and weights. Protenix and RF3
each also depend on proprietary NVIDIA cuEquivariance packages (RF3's was already recorded above; Protenix's is new),
and that third-party dependency needs its own review before a commercial deployment.

### Chai-1: a data file the weight list did not name

- The package also downloads `conformers_v1.apkl`. `chai_lab/utils/paths.py` at v0.6.1 defines it as
  `cached_conformers = Downloadable(url="https://chaiassets.com/chai1-inference-depencencies/conformers_v1.apkl", path=downloads_path.joinpath("conformers_v1.apkl"))`
  (the misspelling "depencencies" is in the source). It is the same host, `chaiassets.com`, as the weights, whose
  terms were not checked.
- What it is: `chai_lab/data/sources/rdkit.py` at v0.6.1 loads it as the reference-conformer cache
  (`antipickle.load(path, ...)`), and the class docstring says: "Caches idealized 3D coordinates and list
  of atoms for residues that exist in the PDB. This is needed to create empty atom coordinates and mask
  for missing residues and ensure the number of tokens and atoms is the same for chains with the same
  entity_id". It is a data file, not a model checkpoint, and no licence statement for it was found.
- Size: an HTTP HEAD on that URL on 2026-11-05 returned `Content-Length: 124726115` (about 119 MiB; the
  smoke report's "119 MB" is the MiB figure).
- Observed in the smoke (not a primary-source reading): the whole download for a fresh Chai-1 install was
  about 6.6 GB, of which the ESM2-3B traced fp16 file was 5.3 GB and the six `models_v2/*.pt` components 1.1 GB.
- The licence verdict is unchanged (Apache-2.0 per README and Hugging Face metadata); the conformer file
  falls under whatever the host's terms say, which is unverified.

### Protenix: proprietary NVIDIA wheels are a hard dependency, and the weight host was not in the record

- `pip install protenix==1.1.0` cannot avoid NVIDIA's proprietary cuEquivariance packages. The PyPI
  metadata of `protenix` 1.1.0 (JSON API, read 2026-11-05) lists, with no environment marker or extra,
  `cuequivariance-ops-torch-cu12==0.8.0` and `cuequivariance-torch==0.8.0`. `cuequivariance-ops-torch-cu12`
  0.8.0 in turn requires `cuequivariance-ops-cu12==0.8.0`. The `license` field of
  `cuequivariance-ops-torch-cu12` 0.8.0 reads "Other/Proprietary License (NVIDIA Proprietary Software)";
  the `license` field of `cuequivariance-ops-cu12` 0.8.0 (and 0.7.0) begins "# Software License Agreement /
  LICENSE AGREEMENT FOR NVIDIA MATH LIBRARIES SOFTWARE DEVELOPMENT KITS", the same agreement already quoted in the RF3
  section (only its opening was read there and here). `cuequivariance-torch` 0.8.0 carries the Apache
  License 2.0 text.
- Observed in the smoke: with `--trimul-kernel torch --triatt-kernel torch` and `LAYERNORM_TYPE=torch` the
  proprietary packages were installed but unused at runtime. This was observed on an aarch64 GB10 host where
  the default cuEquivariance kernels abort (an LLVM error on sm_121a) so the torch kernels were the only way
  to run; it was NOT tested with the packages uninstalled, and could not be: the install requires them. The
  effective licence of the engine on our platform is therefore, as far as the opening of that agreement was read, Apache-2.0 plus the NVIDIA SDK agreement for
  files that are installed whether or not they are used. The adapter's `--layernorm-type torch` flag, which sets
  `LAYERNORM_TYPE`, was added after the smoke and has not been run live yet.
- The weight and CCD download host is `protenix.tos-cn-beijing.volces.com`. `protenix/web_service/dependency_url.py`
  at v1.1.0 maps `"protenix_base_default_v1.0.0"` to
  `https://protenix.tos-cn-beijing.volces.com/checkpoint/protenix_base_default_v1.0.0.pt` and the CCD and
  cluster files to `https://protenix.tos-cn-beijing.volces.com/common/components.cif`,
  `.../common/components.cif.rdkit_mol.pkl`, `.../common/clusters-by-entity-40.txt` and
  `.../common/obsolete_release_date.csv`. An HTTP HEAD on the checkpoint on 2026-11-05 returned
  `Content-Length: 1475950125` and `Last-Modified: Tue, 03 Feb 2026 04:14:06 GMT`; a request for
  `https://protenix.tos-cn-beijing.volces.com/LICENSE` returned 404. **The terms of that host, and of the
  CCD and cluster files fetched from it, were not read** (they were not found at the host root and the
  v1.1.0 README does not mention the host). The verdict for the weights still rests on the README sentence quoted in the table.
- Observed in the smoke: the first-use download from that host was about 2.1 GB (checkpoint 1.48 GB, `components.cif` 491 MB,
  `components.cif.rdkit_mol.pkl` 142 MB, `clusters-by-entity-40.txt` 22 MB, `obsolete_release_date.csv` 0.13 MB).

### RF3: the extra as published does not install into a working environment; the adapter avoids the proprietary ops at runtime

- Primary-source facts (PyPI JSON for `rc-foundry` 0.2.0, read 2026-11-05): the package requires
  `atomworks[ml]>=2.1.1` (a base requirement with no upper bound) and the `rf3` extra requires, on Linux,
  `cuequivariance-ops-cu12>=0.6.1`, `cuequivariance-ops-torch-cu12>=0.6.1` and `cuequivariance-torch>=0.6.1`.
  PyPI carries `atomworks` 2.2.0 and 3.0.4 (latest 3.0.4) and `cuequivariance` 0.7.0 and 0.13.0.
- Observed in the smoke (these are behaviours of the installed packages, not primary-source quotes):
  `pip install "rc-foundry[rf3]==0.2.0"` resolves `atomworks` 3.0.4, on which
  `from atomworks.io.utils.selection import AtomSelectionStack` fails, so `rf3.utils.inference` cannot be
  imported; and it resolves cuEquivariance 0.13.0, which is incompatible with torch 2.7.1 (the first
  triangle-multiplication call fails). The working set was `atomworks[ml]==2.2.0` plus `cuequivariance`,
  `cuequivariance-torch`, `cuequivariance-ops-cu12` and `cuequivariance-ops-torch-cu12` all `==0.7.0`, with torch
  2.7.1+cu126. With cuEquivariance active, Triton also compiles C on first use, so a host with no C compiler fails
  without `CC`. A plain install is therefore broken, and every fix is a pin the vendor does not publish.
- Per the source and one observed run, the proprietary ops are not needed at runtime. `src/foundry/__init__.py` at tag v0.2.0 reads
  `_env.bool("DISABLE_CUEQUIVARIANCE", default=False)`: when it is set the module logs "cuEquivariance usage
  disabled via DISABLE_CUEQUIVARIANCE" and does not import `cuequivariance_torch`, and the import is wrapped in
  `except ImportError`. The adapter sets `DISABLE_CUEQUIVARIANCE=1` by default (`--use-cuequivariance` opts
  in).
- **What was observed, and what was not.** On one PD-L1 design, with the variable set by hand, with no C compiler and `CC`
  unset, the fold ran to exit 0 (iptm 0.8439 against 0.8432 with the ops enabled; 62 s against 50 s; peak 6,308 MiB against
  5,008 MiB). The four `cuequivariance*` packages were **installed but disabled** in that run. A run with them
  **uninstalled** was NOT done; the `except ImportError` fallback in the source is a reading of the source, not
  a test. The adapter's new default (commit `9117c35`) is unit-tested, and its live check, that the fold log
  prints the "disabled" line, is still owed.
- The weights file, `rf3_foundry_01_24_latest_remapped.ckpt`, was fetched from
  `https://files.ipd.uw.edu/pub/rf3/rf3_foundry_01_24_latest_remapped.ckpt` (observed in the smoke: 3,038,876,446 bytes, the
  `Content-Length`, sha256 `364ef592fd8042a9cf4176d045015190f8322f961ccca38d891b20ca578d3bb0`). The terms of that host were not
  read (unverified), as before.
- The licence verdict is unchanged: BSD-3-Clause code, with the weights statement on the `production` branch only.

### OpenFold3: operational notes, licence unchanged

- Weights: `of3-ob-2025-06-30-174k.pt`, 2,287,872,989 bytes (about 2.29 GB), from the public bucket
  `openfold3-data` (HTTP HEAD on 2026-11-05: `Content-Length: 2287872989`, `Last-Modified: Fri, 24 Jul 2026 03:15:05 GMT`,
  the same modification date as recorded above). The smoke fetched exactly this one file with `setup_openfold`.
- Observed in the smoke: a host with no system C compiler fails per design with "Failed to find C compiler. Please specify via CC
  environment variable" (Triton JIT) unless `CC` names a gcc; Python headers were present. The release requires
  Python 3.12 or newer (PyPI metadata for `openfold3` 0.5.1, `Requires-Python >=3.12`).
- Observed in the smoke: the engine ran with its default kernels, and no cuEquivariance or DeepSpeed was used or
  installed. The base dependencies in the PyPI metadata of `openfold3` 0.5.1 (read 2026-11-05) name no cuEquivariance
  package; `cuequivariance`, `cuequivariance-ops-torch-cu12` and `cuequivariance-torch` appear only under the optional extra
  `cuequivariance`, and `deepspeed` only under the extra `deepspeed`. The NVIDIA CUDA runtime wheels that torch pulls in were
  not assessed.
- The licence caveats above (weights licence resting on two OpenBind pages, no licence file beside the weights,
  bucket-root file CC BY 4.0) are unchanged by the smoke.

## Install-time licence notice (Protenix)

`install/install.sh` and `install/install_aarch.sh` (`--second-engine protenix`, `--tool protenix`) read the text
between the two marker comments below at run time and print it verbatim before anything is downloaded; they refuse
to install if the markers are missing or the block is empty. The text is the only copy: edit it here, and keep it in
step with the Protenix sections above. The markers are exact, whole-line strings.

<!-- install-licence:protenix:start -->
PROTENIX v1.x (ByteDance), the opt-in replacement for AF3 as the second refold engine. Licence read 2026-11-05.

Licence: Apache-2.0 for the code and for the v1.x model parameters, v1.x only (protenix==1.1.0, model
protenix_base_default_v1.0.0). The v1.1.0 README says the code and model parameters are "free for both academic
research and commercial use". Protenix-v2 weights are proprietary and confidential, are not released under any
open-source licence, and are never installed or used here; the adapter refuses any model name outside v1.x.
Sources:
  https://github.com/bytedance/Protenix/blob/v1.1.0/README.md
  https://github.com/bytedance/Protenix/blob/v1.1.0/LICENSE
  https://github.com/bytedance/Protenix/blob/main/README.md (the v2 weights statement)

Download host: the checkpoint (1.48 GB) and the CCD and cluster files (about 0.65 GB) come from
protenix.tos-cn-beijing.volces.com. The terms of that host, and of the CCD and cluster files fetched from it, were
not read.

NVIDIA wheels: pip install protenix also installs NVIDIA's proprietary cuEquivariance packages
(cuequivariance-ops-torch-cu12 and cuequivariance-ops-cu12, under the NVIDIA Software License Agreement). They are
installed but unused at runtime, because the refold adapter always runs the plain torch kernels. A commercial
deployment needs its own review of that NVIDIA agreement.

Full record, with quotes and pins: Evaluator/docs/second_engine_licences.md. This is not legal advice.
<!-- install-licence:protenix:end -->

## Environments used in the benchmark

What each engine ran with in the 2026-11-05 live smokes. "Not recorded" means the smoke report did not state it.
Peak memory and timings are in the runbook (`second_engine_benchmark_runbook.md`).

| Engine | Version / commit | Weights file(s) and size | Python / torch | Host class it ran on |
|---|---|---|---|---|
| OpenFold3 | `openfold3==0.5.1` from PyPI (git `795e45b` is the tag read for the record); no kernel extras | `of3-ob-2025-06-30-174k.pt`, 2,287,872,989 B | Python 3.12.13; torch 2.15.0+cu132 | x86_64 24 GB box (RTX 3090) |
| Protenix | `protenix==1.1.0` (tag `v1.1.0`, `4f1eedf`), model `protenix_base_default_v1.0.0` | `protenix_base_default_v1.0.0.pt` 1,475,950,125 B; first-use total about 2.1 GB with the CCD files | Python 3.12.3; torch 2.7.1+cu128 (triton 3.3.1) | aarch64 GB10 host (unified memory, GPU also used by another tenant during the run) |
| Chai-1 | `chai_lab==0.6.1` (tag `v0.6.1`, `8d5ac0f`), existing env used unmodified | `esm/traced_sdpa_esm2_t36_3B_UR50D_fp16.pt` 5.3 GB; `models_v2/{bond_loss_input_proj,confidence_head,diffusion_module,feature_embedding,token_embedder,trunk}.pt` 1.1 GB together; `conformers_v1.apkl` 124,726,115 B; about 6.6 GB in all | Python 3.12.14; torch 2.10.0+cu130. The PyPI metadata of `chai_lab` 0.6.1 says `torch<2.7,>=2.3.1`; the env that worked was outside that range | aarch64 GB10 host (unified memory, shared with another smoke) |
| RF3 | `rc-foundry==0.2.0` (tag `v0.2.0`, `3967144`) with `atomworks[ml]==2.2.0` and the four `cuequivariance*` packages `==0.7.0` | `rf3_foundry_01_24_latest_remapped.ckpt`, 3,038,876,446 B | Python 3.12.13; torch 2.7.1+cu126 (triton 3.3.1) | x86_64 24 GB box (RTX 3090) |

## IntelliFold-2 clearance

**Verdict: unclear.**

What the primary sources establish:

1. **AF3 code is included, not merely targeted.** `third_party/alphafold3/` in the IntelliFold repo
   was compared file by file (git blob hashes) against `google-deepmind/alphafold3` at tag `v3.0.3`:
   171 files are vendored; 168 are byte-identical to `v3.0.3`; 3 differ
   (`src/alphafold3/model/model.py`, `.../network/atom_cross_attention.py`,
   `.../network/diffusion_head.py`); none exists only in IntelliFold. The only files missing are
   17 `test_data` fixtures, which the NOTICE says were omitted. `intellifold/run_jax_inference.py`
   is a modified copy of AF3's `run_alphafold.py` (its header says so and carries a modification
   notice). The vendoring commit is `0caa7d2` (2026-06-15).
2. **An Apache-2.0 release of AF3 exists.** AF3 release `v3.0.3` (2026-06-09): "Version 3.0.3 changes
   the AlphaFold 3 code license from CC BY-NC-SA 4.0 to Apache 2.0." The `LICENSE` at tag `v3.0.3`
   (and on `main`) is the Apache License 2.0; at tag `v3.0.2` it is "Attribution-NonCommercial-ShareAlike
   4.0 International". The relicense commit is `7b197fe` "Change the code license from CC BY-NC-SA
   4.0 to Apache 2.0." (2026-06-09). The AF3 README states: "AlphaFold 3 source code is licensed under
   the Apache License, Version 2.0". So the NOTICE's claim about the code is accurate, and the vendored
   code is not the CC BY-NC-SA code. The code is in the Apache-2.0 state IntelliFold says it is.
3. **AF3 weights are not included.** NOTICE: "The AlphaFold 3 model parameters ("weights") and outputs
   generated with them are NOT included here and are governed by separate non-commercial terms ...
   This repository ships only IntelliGen-AI's own IntelliFold-v2 weights." The weights were converted
   from an IntelliFold-v2 PyTorch checkpoint (`convert_ifv2_to_jax.py`, README section "How the
   IntelliFold JAX weights were produced").
4. **Licence grant of the weights.** README: "The IntelliFold project, including code and model
   parameters, is made available under the Apache 2.0 License, it is free for both academic research
   and commercial use." The Hugging Face repository `intelligenAI/intellifold` has `license: apache-2.0`
   metadata and is not gated. The repository `LICENSE` at `main` is the Apache License 2.0 (its history has three
   commits, the first on 2025-07-03; the earlier versions were not read).

What keeps the verdict at "unclear":

- **The AF3 Output Terms were not updated by the relicense and their definitions are broad.**
  `OUTPUT_TERMS_OF_USE.md` has one commit in its history (2024-11-11, initial release; it says
  "Last Modified: 2024-11-09"). It defines: "'AlphaFold 3' means the AlphaFold 3 Code and Model
  Parameters." and "'AlphaFold 3 Code' means the AlphaFold 3 source code: (a) identified at [public
  GitHub repo], or such other location in which we may make it available from time to time,
  regardless of the source that it was obtained from; and (b) made available by Google to
  organizations for their use in accordance with the [AlphaFold 3 Model Parameters Terms of Use] (not
  these Terms) together with (i) modifications to that code, (ii) works based on that code, or (iii)
  other code or machine learning model which incorporates, in full or in part, that code." and
  "'Output' means the structure predictions and all related information provided by AlphaFold 3,
  together with any visual representations, computational predictions, descriptions, modifications,
  copies, or adaptations that are substantially derived from Output." The use restrictions then say
  Output is "made available free of charge, for non-commercial use only" and must not be used "On
  behalf of a commercial organization or in connection with any commercial activities".
  IntelliFold-2 is code that "incorporates, in full or in part," the AF3 source code, and it runs on
  AF3's own JAX engine. Read literally, structure predictions it produces could be "Output" under
  these Terms even though the code licence is Apache-2.0. The other reading, which the NOTICE adopts
  ("outputs generated with them" refers to AF3 weights), is that "AlphaFold 3" needs the Model
  Parameters and IntelliFold-2 uses none. Whether Google's Output Terms reach a model that uses
  separately trained weights on the Apache-2.0 code was not resolved from the primary sources, and
  the sources are in tension (the code is relicensed, the Output Terms definition is unchanged).
  This is a question of contract interpretation that a lawyer, or written confirmation from
  Google DeepMind and IntelliGen-AI, has to answer. It does not apply to the other four candidates,
  none of which uses AF3 source.
- **Training provenance of IntelliFold-v2 is not documented.** The AF3 weights terms ("Key things to know",
  item 2.2) forbid using "AlphaFold 3 output to train machine learning models or
  related technology for biomolecular structure prediction similar to AlphaFold 3" (emphasis in the
  original omitted). The IntelliFold-2 release note (bioRxiv 2026.02.09.704787, also in the repo's
  assets) says: "we scaled up the self-distillation dataset and optimised its distribution" and
  credits the authors who built "the distillation datasets", without naming which model produced the
  distilled structures. The 2025 IntelliFold technical report (arXiv 2507.02025, the v1 model, not
  v2) lists the distillation sources as AlphaFold DB structures (AF2) filtered at pLDDT over 85,
  AlphaFold-Multimer v2.3 predictions on PDB proteins with unresolved regions, and antibody-antigen
  pairs predicted "using IntFold" (IntelliGen's own model), and says: "Due to license limitations,
  performance metrics for AlphaFold 3 are cited directly from the original benchmark." Nothing in
  these sources says AF3 weights or AF3 output were used for training, but the v2 distillation source
  is not stated either. The same open question exists for every candidate whose distillation set was
  not audited here, so by itself it would not justify "unclear"; it is recorded because the
  IntelliFold-2 evidence chain also depends on AF3.
- **NOTICE is incomplete as to modified files.** The NOTICE names two modified AF3 files
  (`atom_cross_attention.py`, `diffusion_head.py`) and `run_jax_inference.py`, but the tree diff shows
  a third modified file, `model.py` (adds an optional `steering` argument), whose header carries no
  IntelliGen modification notice. That is a gap against Apache-2.0 section 4(b) on IntelliGen's side.
  It does not make the vendored code non-commercial, so it is a caveat, not a blocker.
- Other attributions in the shipped `LICENSE` and `NOTICE` (all permissive): OpenFold, Protenix,
  OneFlow and FastFold (Apache-2.0) and Boltz-1 (MIT; steering code from Boltz under MIT).

What would close it: a written statement from IntelliGen-AI, ideally also from Google DeepMind,
that structure predictions made with IntelliFold-v2 weights on the Apache-2.0 AF3 v3.0.3 engine are
not "Output" under the AF3 Output Terms of Use, plus a statement of what generated the IntelliFold-v2
self-distillation set. Until then IntelliFold-2 does not proceed to benchmarking (Task 9).
