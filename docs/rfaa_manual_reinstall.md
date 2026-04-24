# RFAA — legacy maintenance notes

**Status (2026-04):** RFAA (`baker-laboratory/rf_diffusion_all_atom`) is
**deprecated in BindMaster**. The Baker lab stopped commit activity in March
2024 and superseded the project with **RFdiffusion3 / foundry**
(`RosettaCommons/foundry`) in December 2025. BindMaster's default all-atom
tool is now **RFD3** — install it with `bindmaster install --tool rfd3`.

RFAA remains installable for backwards-compatibility with existing `runs/`
directories and for users who need the original RFAA weights. The interactive
menu no longer offers it; opt in explicitly:

```bash
bindmaster install --tool rfaa            # x86_64 only
bindmaster install --uninstall --tool rfaa   # when you're ready to remove it
```

---

## Why RFAA is deprecated

- **Upstream dormant.** HEAD of `baker-laboratory/rf_diffusion_all_atom`
  is still the 2024-03-13 "LICENSE" merge. 2 years of unresolved issues
  (#21 TRP side-chain bug, #26 run-outside-install-dir, #32 GPU parsing, …).
- **aarch64 blocker.** DGL has no CUDA-enabled aarch64 wheels, so the
  SE3-Transformer path doesn't work on DGX Spark / Grace-Hopper.
- **RFD3 supersedes it.** Atom-level diffusion replaces the graph-level
  stack, handles ligand + nucleic-acid binders natively, BSD-3-Clause
  license, no DGL.

## Manually reproducing an existing RFAA run

1. Check the repo state that installed your run:
   - `rf_diffusion_all_atom` HEAD: `f913a19e16f30858ce7a724fe028475b1871319c`
     (2024-03-13 — this IS upstream HEAD)
   - `LigandMPNN` HEAD: `26ec57ac976ade5379920dbd43c7f97a91cf82de`
     (2025-02-06)

2. Clone + pin:

   ```bash
   git clone https://github.com/baker-laboratory/rf_diffusion_all_atom.git
   cd rf_diffusion_all_atom && git submodule update --init --recursive
   git clone https://github.com/dauparas/LigandMPNN.git
   (cd LigandMPNN && git checkout 26ec57a)
   ```

3. Create the conda env (x86_64 only; aarch64 won't work — DGL blocker):

   ```bash
   conda create -n bindmaster_rfaa -y python=3.11 \
       "pytorch>=2.2" "pytorch-cuda=12.4" gcc_linux-64 gxx_linux-64 \
       -c pytorch -c nvidia -c conda-forge
   conda run -n bindmaster_rfaa pip install -q hydra-core omegaconf icecream \
       scipy "numpy<2" pandas tqdm fire assertpy deepdiff opt-einsum e3nn \
       ml_collections dm-tree "dgl==1.1.3+cu121" \
       -f https://data.dgl.ai/wheels/cu121/repo.html \
       "torchdata==0.7.1" prody openbabel-wheel
   ```

4. Post-install patches (required by the 2024-03 codebase on modern numpy /
   PyRosetta stacks — see `install/install.sh:install_rfaa()` for the
   current implementation):

   - `rf_diffusion_all_atom/idealize_backbone.py` — the upstream asserts
     exactly one ligand; patch to accept zero (protein-only) designs.
   - `LigandMPNN/openfold/np/residue_constants.py` — replace `np.int`
     (removed in numpy 2.x) with `np.int64`.

5. Download weights:

   ```bash
   wget -O rf_diffusion_all_atom/weights/RFDiffusionAA_paper_weights.pt \
       http://files.ipd.uw.edu/pub/RF-All-Atom/weights/RFDiffusionAA_paper_weights.pt
   (cd LigandMPNN && bash get_model_params.sh ./model_params)
   ```

6. Use via PYTHONPATH (RFAA is not pip-installable):

   ```bash
   export PYTHONPATH="$(pwd)/rf_diffusion_all_atom:$(pwd)/LigandMPNN${PYTHONPATH:+:$PYTHONPATH}"
   conda activate bindmaster_rfaa
   # Then follow the RFAA README for `rf_diffusion_all_atom/run_inference.py` flags
   ```

## Useful unmerged upstream PRs

These were known, small, and addressed real bugs — not merged by the Baker
lab. Consider cherry-picking them if you hit the symptoms:

- **#21** (2024-07, unmerged) — TRP side-chain N/C atom ordering fix in
  `chemical.py`. Affects motif-scaffolded ligand binders with tryptophan.
- **#26** (2024-09, unmerged) — allow running outside the install dir
  (checkpoint + output path search).
- **#37** (2025-05, merged post-our-pin) — `ContigMap.inpaint_seq` fix for
  motif-scaffolded designs.

## Migration to RFD3

Configs are **not compatible** — RFAA uses Hydra YAMLs with
`contigmap.contigs` / `potentials`; RFD3 uses an
`InputSpecification` schema with top-level `contig`, `ligand`,
`select_hotspots`, `select_fixed_atoms`, `partial_t`. BindMaster's
configurator regenerates the config when you switch tools.

Contig syntax is broadly compatible — the old `A40-60/0/70` idioms port
with minor edits, and RFD3 adds an `unindex` block for floating motifs.

AtomWorks (RFD3's framework) handles structure normalisation internally, so
the RFAA `idealize_backbone.py` / `residue_constants.py np.int → np.int64`
post-install patches are **no longer needed** for RFD3.

See `install/install.sh:install_rfd3()` and the
[foundry docs](https://rosettacommons.github.io/foundry/) for the
current RFD3 integration.
