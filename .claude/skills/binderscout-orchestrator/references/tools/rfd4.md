# RFD4-Proteina — engine reference

The ninth design tool (added to `v2.0.x` on 2026-10-27, after the `v2.0.2` tag). IPD x NVIDIA
latent-reasoning diffusion. **Generates backbone AND sequence in one pass — there is no MPNN
step**, so none of the RFD3 Pro/Gly-collapse reasoning applies to it.

**Env:** uv venv at `RFD4-Proteina/.venv` (the checkout IS the installation — moving or deleting
it breaks `rfd4-generate`). Weights under `weights/rfd4/`, used as `HF_HOME`.
**Opt-in:** `--tool rfd4`, deliberately NOT in `--tool all`.
**Licence:** code BSD-3; **the weights licence has NOT been verified** — read the terms on
`huggingface.co/nvidia/RFD4-Proteina` before any publication or commercial use.

## Platform

**x86_64 AND aarch64** as of 2026-10-29. Upstream's `scripts/setup_venv.sh` refuses any
non-x86_64 arch, but **we never call it** — our installer builds the venv with `uv` and selects
wheels with `--torch-backend cu130`. Every CUDA-13 dependency publishes a `linux_aarch64` wheel
(`tmol`, `cuequivariance-ops-cu13`, `cuequivariance-ops-torch-cu13`; `cuequivariance-torch` is
pure Python), and a resolve on GB10 returned the exact pinned set. Validated by install on one
GB10, **not** by a design campaign there — treat the first aarch64 run as a test.

On aarch64 `uv pip check` reports `nvidia-cusparselt-cu13 was built for a different platform`.
That is a **false positive**: PyTorch's cu130 index serves the ARM build tagged
`py3-none-manylinux2014_sbsa` (NVIDIA's ARM-server tag), which uv's matcher does not map to
aarch64. The binary is correct — `libcusparseLt.so.0` is `ELF64 / AArch64`, torch reports
`cuda_available True` on GB10, a GPU matmul returns. The installer tolerates exactly this one
complaint and nothing else.

## The three things that actually bite

1. **mmCIF only, and the contig resolves on `label_seq_id` — NOT `auth_seq_id`.** A `.pdb` has no
   label column, so the configurator refuses one at configure time rather than converting. The two
   numberings routinely differ: on a pMHC target, b2m is `auth 1-99` but `label 2-100` (an
   unmodelled N-terminal Met), so the contig must read `B2-100`. The configurator computes this
   from the label column itself and warns when they disagree; a hand-written YAML will not.

2. **The binder segment must come LAST in the contig.** RFD4's deferred binder sentinel re-derives
   molecule ids over the partially assembled array, and the build fails when a preserved chain
   placed after the first already carries the id the binder is handed. Measured 2026-10-29 on
   HLA(A)/b2m(B)/peptide(C):

   | contig | result |
   |---|---|
   | `60-150, /0, A1-276, /0, B2-100, /0, C1-10` | **FAILS** `index_group_molecule_must_be_connected` |
   | `A1-276, /0, B2-100, /0, C1-10, /0, 60-150` | **PASSES** |
   | `60-150, /0, A1-276, /0, C1-10` | PASSES |
   | `60-150, /0, C1-10, /0, A1-276` | FAILS |

   So it is **not** "binder-first always fails on a multi-chain target" — the condition is
   narrower. Binder-last avoids it for every ordering, which is what the configurator now emits.

3. **`'~metrics'` is required, and it is a Hydra removal, not a flag** — single-quote it or the
   shell eats the `~`. The native metrics block wants AF2/AF3 envs that are absent here.
   Consequence: RFD4 contributes **no** native metric column, so `evaluate.sh` folds back the
   Boltz-2 rank for it, as it already does for RFD3.

## Output and pooling

One uncompressed `.cif` per sample at
`<out_dir>/.../inference_samples/<name>_<i>/<name>_<i>_generated.cif`. Chain B is the designed
binder, chain A the preserved target. **Note RFD3 writes `.cif.gz` and this writes plain `.cif`.**

**A `timing/` and a `prod/` run side by side will silently pool.** The extractor refuses and names
both roots (`extractors/rfd4.py` raises on >1 root). Related live hazard: the shipped
`run_rfd4.sh` switches `INPUT_YAML` on `$SPEC` but leaves `GEN_DIR` fixed, so running the hotspot
arm after the default arm pools both into one `sequences.csv` with no arm column — even though the
script's own header advertises that second run.

## Cost and what is NOT established

~5 s per design, GPU peak ~3 GiB (measured on one L40S: 360 designs in 37 min). Generation is
cheap; **refolding the pool is what costs.** First results were in silico only — PD-L1 360 designs
median `consensus_iptm_mean` 0.598, TrkA 330 designs median 0.209. **No binding was measured and
no hit rate is claimed**; the paper's 84%-of-188-TrkA-binders figure is experimental and is not
replicated here.

**Install verification is not an import.** `import rfd4_proteina` and `rfd4-generate --help` both
pass on a GPU-less node with no weights at all. The installer asserts `uv pip check`, a non-null
`torch.version.cuda`, and the weights' exact byte count and sha256 — and it deliberately does not
assert `torch.cuda.is_available()`, which is correctly False on a GPU-less node.
