# Runbook: reproducing the second-engine benchmark

## Purpose

BinderScout's three-engine refold (Boltz-2 + AlphaFold 3 + ESMFold2) cannot be used by anyone who
may not obtain or run the AF3 weights. The benchmark asks whether a commercially usable engine can
take AF3's slot without losing skill at separating measured binders from measured non-binders. It
reuses the existing Boltz-2, AF3 and ESMFold2 scores for 563 curated Adaptyv/ProteinBase designs on
4 targets, refolds those same designs with one candidate (OpenFold3, Protenix v1.x, Chai-1, RF3), and
compares per-target ROC AUC of the panel mean ipTM with a paired bootstrap and a fixed pass rule. The
reasoning, the pass rule and the non-goals are in
`docs/superpowers/specs/2026-11-04-af3-replacement-engine-design.md`; the licence reading for each
candidate is in `Evaluator/docs/second_engine_licences.md` (read that first: IntelliFold-2 is not
benchmarked because its clearance is "unclear"). This runbook is the how-to; every number in it is
either a measurement from the 2026-11-05 live smokes (two real PD-L1 designs per engine, plus a few
larger-target designs) or a step-0 figure, and anything not observed is marked "not recorded".

## Inputs

Everything below lives on the lab's private share, never in this repository. **Label rows never enter
the repo**; the repo holds only `Evaluator/benchmarks/adaptyv/MANIFEST.json`, which names the label
file's SHA-256 and the row counts.

| Input | What it contains |
|---|---|
| Merged CSV (`adaptyv_merged.csv`) | 563 rows, one per design. Column `id`, and the already-computed `boltz_pae_iptm`, `af3_pae_iptm`, `esmfold2_pae_iptm` (plus `consensus_iptm_mean` and the per-engine metrics). It has **no `target` column** (header checked 2026-11-05). |
| Labels | Either the private registry (`$BINDERSCOUT_BENCHMARK_STORE`, pool `adaptyv`, 2,018 rows: 325 `bound`, 1,693 `not_bound`) or a CSV with columns `id`, `target` and a 0/1 label column. The registry pool has **2,018 rows**; the benchmark uses only the **563-design curated subset** (egfr 190, il7r 96, nipah 211, pd-l1 66) that has all three baseline scores. Step 0 was run from a labels CSV; 0 designs were dropped. |
| `raw_refold/` | Per-engine, per-target refold CSVs that carry `sequence` and `target_sequence`, the source of the binder and target sequences a candidate needs. |
| `<target>.fasta` | The binder sequences of one target, one record per design, header = design id (first token), in the merged CSV's id space. Counts: pd-l1 66, il7r 96, egfr 190, nipah 211. |
| `<target>.target.txt` | The target sequence, one line. Lengths: pd-l1 220, il7r 219, egfr 621, nipah 602 aa. |

Recipe used for the smoke inputs (from the project notes, not re-run here): take the 563 ids of the merged CSV,
join them to `source/master_designs.csv` on the share for the binder sequences, and take each target's
sequence from the engines' `raw_refold/` CSVs (`target_sequence`), so that the candidate folds exactly what the
three baseline engines folded. Warning: the `target` column of `master_designs.csv` differs from the label file's
for some designs; the labels file is the authority for which target a design belongs to.
Check the files before a run: record count per file as above, every FASTA id present in the merged CSV, and
the target length as above.

The target MSA is fetched **once per target** from ColabFold and cached (see "Target MSA" in the
repository's `CLAUDE.md`); every adapter reads that cache and none contacts an MSA server by itself.
On a host with no outbound access, copy the cached `target_<hash>.a3m` for each target (found with
`target_msa_cache_path(seq)`) into the same cache directory on that host, and run with the cache
present. Pre-warm it before running anything in parallel.

## Per-engine environment recipe

All four adapters are `Evaluator/scripts/refold_<engine>.py`, run **inside the engine's own
environment** with `PYTHONPATH=<repo>/Evaluator` (they import `binder_comparison`, which needs only
numpy and pandas there; Chai-1 needs pandas below 3). Common flags (all four, `--help` verified):
`--sequences --target-seq --output --output-dir --resume --no-msa --allow-no-msa --msa-cache-dir
--num-seeds --num-samples`. Defaults are `--num-samples 5`; **the benchmark runs use
`--num-samples 1`** (see the sample-count caveat). Give every run a fresh `--output` path: an existing
CSV is appended to unless `--resume` is passed. Exit code 3 means some designs got a blank row
(never a zero); exit 2 means the run was refused before any design (for example a missing target MSA
or a non-standard residue letter in the target). Binders containing a letter outside the 20 standard
amino acids get a blank row before any engine call (driver commit `8e08be1`).

On the aarch64 GB10 host (unified memory) every GPU job goes through `tools/gpurun --cap <GiB>`
(the smokes used a cap of 30 GiB); an uncapped job can reboot the
machine. Do not copy the cap into a script as a constant: query it.

### OpenFold3 (x86_64 24 GB box)

Pins observed: `openfold3==0.5.1` (Python 3.12.13, torch 2.15.0+cu132), no kernel extras. Not recorded in the smoke report:
the exact `uv venv` command, the JSON config given to `setup_openfold`, and the path of the gcc used for `CC`.

```
uv venv --python 3.12 $ENV            # exact venv command not recorded for this engine
uv pip install --python $ENV/bin/python "openfold3==0.5.1"
export OPENFOLD_CACHE=$WEIGHTS/ofcache
# one-time weight fetch: setup_openfold with a JSON config whose selected_parameters is "default",
# and --skip-biotite-ccd-update (the config file's full text is not recorded in the smoke report)
export CC=<path to a gcc>             # only on a host with no system C compiler (Triton JIT)
python Evaluator/scripts/refold_openfold3.py --sequences $IN/pd-l1.fasta \
   --target-seq "$(cat $IN/pd-l1.target.txt)" --output $OUT/openfold3_pd-l1.csv \
   --output-dir $OUT/openfold3_pd-l1 --num-samples 1
```

Weights: `of3-ob-2025-06-30-174k.pt`, 2,287,872,989 bytes (one file only). The adapter passes the
checkpoint name `openbind-2025-06-30-174k`; `--model-dir`/`--ckpt-name` override the default.

### Protenix v1.x (aarch64 GB10 host in the smoke)

Pins observed: `protenix==1.1.0`, Python 3.12.3, torch 2.7.1+cu128, triton 3.3.1. Model
`protenix_base_default_v1.0.0` (the only other accepted name is `protenix_base_20250630_v1.0.0`;
`protenix-v2`, unknown names and a name with a trailing space are refused with exit 1 before anything is
downloaded). Installing it pulls in NVIDIA's proprietary cuEquivariance wheels (see the licence record).

```
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
pip install protenix==1.1.0
tools/gpurun --cap <GiB> -- $ENV/bin/python Evaluator/scripts/refold_protenix_v1.py \
   --sequences $IN/pd-l1.fasta --target-seq "$(cat $IN/pd-l1.target.txt)" \
   --output $OUT/protenix_pd-l1.csv --output-dir $OUT/protenix_pd-l1 --model-dir $PROTENIX_ROOT \
   --trimul-kernel torch --triatt-kernel torch --layernorm-type torch --num-samples 1
```

The three non-default settings were all needed on the GB10 host: the default cuEquivariance kernels
abort the process (an LLVM sm_121a error) and `LAYERNORM_TYPE=torch` avoids an import-time CUDA
extension build that needs `nvcc` and `ninja`. The smoke set `LAYERNORM_TYPE` as an environment variable;
the `--layernorm-type` flag (commit `9a1fbc3`) is unit-tested but **not yet run live**. If a cuEquivariance
kernel is chosen, `libnvrtc` and `libcublas` from the venv's `nvidia/` directory must be on
`LD_LIBRARY_PATH`. The first run downloads about 2.1 GB (checkpoint 1,475,950,125 bytes plus CCD files)
into `--model-dir` from the host named in the licence record. Behaviour with the default kernels on an
x86_64 box with `nvcc` is **not recorded**.

#### x86_64 environment build observed (24 GB RTX 3090 host)

Python 3.12 (venv or conda), `torch==2.7.1` from the `cu128` wheel index, `protenix==1.1.0`, then
`pip install -e 'Evaluator[report]'` so `binder-compare` exists in the env (the installer's `binder-eval-protenix` is built the
same way). **A C compiler is required**, because `scikit-learn-extra` builds from source. `LAYERNORM_TYPE=torch` must be set in
the environment before `runner.inference` is imported (the import otherwise attempts the CUDA layer-norm extension build);
`binder-compare refold-protenix` sets it itself and always uses the torch kernels.

### Chai-1 (aarch64 GB10 host in the smoke)

Pins observed (an existing environment, used unmodified): `chai_lab==0.6.1`, Python 3.12.14,
torch 2.10.0+cu130, pandas 2.3.3, pyarrow 25.0.1, numpy 1.26.4, gemmi 0.6.7. How that environment was
built is not recorded (no install command, and no record of how torch 2.10.0 came to sit beside a `chai_lab` whose
PyPI metadata asks for `torch<2.7`). The directory passed as `--model-dir` must already exist.

```
tools/gpurun --cap <GiB> -- python Evaluator/scripts/refold_chai1.py \
   --sequences $IN/pd-l1.fasta --target-seq "$(cat $IN/pd-l1.target.txt)" \
   --output $OUT/chai1_pd-l1.csv --output-dir $OUT/chai1_pd-l1 --model-dir $CHAI_WEIGHTS --num-samples 1
```

First use downloads about 6.6 GB from `chaiassets.com` (the ESM2-3B file 5.3 GB, six model components
1.1 GB, `conformers_v1.apkl` 124,726,115 bytes). Since commit `1b5f264` the adapter wraps chai-lab's own MSA loader, fails a design before any model
work when a supplied target MSA was not loaded (depth 1), requires the depth to be identical across designs
and records it as `settings.target_msa_depth` in `refold_run_info.json`. The smoke saw a loaded target depth of 4045 on
PD-L1 (by reading the saved MSA file, before this change); the live check of the recorded value is still owed.

### RF3 (x86_64 24 GB box)

Pins observed (the plain `pip install "rc-foundry[rf3]==0.2.0"` does not give a working environment):

```
uv venv --python 3.12 $ENV
uv pip install --python $ENV/bin/python "rc-foundry[rf3]==0.2.0" numpy pandas
uv pip install --python $ENV/bin/python "atomworks[ml]==2.2.0"
uv pip install --python $ENV/bin/python cuequivariance==0.7.0 cuequivariance-torch==0.7.0 \
   cuequivariance-ops-cu12==0.7.0 cuequivariance-ops-torch-cu12==0.7.0
python Evaluator/scripts/refold_rf3.py --sequences $IN/pd-l1.fasta \
   --target-seq "$(cat $IN/pd-l1.target.txt)" --output $OUT/rf3_pd-l1.csv \
   --output-dir $OUT/rf3_pd-l1 --model-dir $WEIGHTS/rf3 --num-samples 1
```

Result set: rc-foundry 0.2.0, atomworks 2.2.0, torch 2.7.1+cu126, triton 3.3.1, hydra-core 1.3.8,
rdkit 2025.3.6, numpy 2.5.4, pandas 2.3.3. Weights: `rf3_foundry_01_24_latest_remapped.ckpt`,
3,038,876,446 bytes, sha256 `364ef592fd8042a9cf4176d045015190f8322f961ccca38d891b20ca578d3bb0`; the
adapter refuses any other file name. `--model-dir` is the directory holding it; nothing is downloaded.
Defaults: 200 diffusion steps (`--num-steps`; RF3's own shipped default is 50), 10 recycles, early
stopping off. Since commit `9117c35` the fold runs with `DISABLE_CUEQUIVARIANCE=1` unless
`--use-cuequivariance` is given; the smokes ran before that change with the ops enabled, apart from one
design run with the variable set by hand. With the ops enabled the host needs a C compiler (`CC`).

## Hardware sizing

**Measurements from the live smokes, on the stated GPU classes only.** They are single runs on one or two
designs; they are not benchmarks of the engines. Hosts differ, so times are not comparable across rows.
Peak memory is `nvidia-smi` sampling (0.5 s for OpenFold3 and RF3, 2 s for Chai-1, which includes the
CUDA context and allocator cache) except Protenix, whose figures are PyTorch's own allocated/reserved
counters. Token count is target plus binder length.

| Engine, host | Complex | Samples | Wall per design | Peak GPU memory |
|---|---|---|---|---|
| OpenFold3, 24 GB RTX 3090 | pd-l1, about 305 tokens | 5 | 35.3 s warm (34.9-36.1 s); the first cold run was 89 s for 2 designs | 5,336 MiB (about 5.2 GiB) |
| OpenFold3, 24 GB RTX 3090 | il7r, 326 tokens | 5 | not recorded | reported as "5.7 GiB" in the smoke report, whose GiB figures for this engine were really MiB/1000 (the MiB value was not recorded; read it as about 5,700 MiB, roughly 5.6 GiB) |
| OpenFold3, 24 GB RTX 3090 | egfr 621 aa + 63 aa binder, 684 tokens | 5 | 92 s including process start | 19,294 MiB (about 18.8 GiB) |
| RF3, 24 GB RTX 3090, ops enabled | pd-l1, 308 tokens | 5 | 49.7 s warm, 51.7 s cold | 5,008 MiB |
| RF3, 24 GB RTX 3090, ops enabled | il7r, 326 tokens | 5 | 50 s | 4,950 MiB |
| RF3, 24 GB RTX 3090, ops enabled | egfr, 684 tokens | 5 | 123 s | 9,458 MiB |
| RF3, 24 GB RTX 3090, ops enabled | nipah 602 aa + 144 aa binder, 746 tokens | 5 | 141 s plus a first-use target MSA fetch | 9,192 MiB |
| RF3, 24 GB RTX 3090, ops disabled (now the default) | pd-l1 design 1, 308 tokens | 5 | 62 s | 6,308 MiB |
| RF3, 24 GB RTX 3090, ops enabled | pd-l1 design 1 | 1 | 41 s | 4,964 MiB |
| Chai-1, aarch64 GB10, cap 30 GiB, shared | pd-l1, 308 tokens | 5 | 7.4-8.4 min warm, up to 10.5 min under contention | 11.9 GiB as reported (`nvidia-smi` sampling; the MiB value was not recorded, so the unit may be MiB/1000) peak during load and trunk (about 2.5 GiB in the diffusion loop); host RSS 10.8-11.3 GiB (`/usr/bin/time`) |
| Protenix, aarch64 GB10, cap 30 GiB, **contended GPU** (another tenant at about 96% utilisation for the whole session) | pd-l1, 308 tokens | 5 | 8.3-8.7 min | 3.29 GiB allocated / 3.44 GiB reserved |
| Protenix, same contended host | pd-l1, 308 tokens | 1 | about 173-175 s | not separately measured (at most 3.3 GiB) |
| Protenix, same contended host | egfr, 684 tokens | 1 | about 450 s | 14.07 GiB allocated / 15.00 GiB reserved |
| Protenix, torch kernels, 24 GB RTX 3090 (headless) | nipah 602 aa + 177 aa binder, 779 tokens (the longest design in the pool) | 1 | not recorded (the run included the weight download) | 21,282 MiB (20.8 GiB of the 24,576 MiB card) card-wide `nvidia-smi`; ipTM 0.895, rc 0; n = 1 design |
| Protenix, torch kernels, 46 GiB L40S | egfr, about 772 tokens | 1 | not recorded | 20,939 MiB (20.4 GiB) card-wide `nvidia-smi` |

The two last Protenix rows are card-wide `nvidia-smi` peaks (including the CUDA context and allocator cache), unlike the
PyTorch allocated/reserved counters of the GB10 rows above; compare them with the other `nvidia-smi` rows, not with those.
They are the evidence for the 24 GB claim: a 24 GB card fits the longest design with about 3 GiB to spare, less if it also
drives a display. Protenix fits the 24 GB card class that ESMFold2 already requires (ESMFold2 holds about 18.9 GiB on a 24 GB card), so no larger GPU is needed; its own peak (20.4-20.8 GiB) is several times AF3's (about 4.4 GiB at 260-390 tokens; AF3 was not measured at about 780 tokens), so the owner's constraint was read as "no new GPU class", not as "no more memory than AF3". `evaluate.sh --gpu-cap-protenix` defaults to 24G, a PyTorch ceiling of about 1.2 times the 20.4 GiB
measured on the L40S, not a reservation.

Not measured: Chai-1 on a 24 GB card or on any target above 308 tokens; OpenFold3 on nipah (long
binders up to 144 aa, about 746 tokens, were predicted to be near the 24 GB limit and need one
measurement before a 24 GB host is committed to that pool); Protenix with the fast kernels on x86_64;
anything on aarch64 for OpenFold3 and RF3.

**Extrapolations, not measurements** (the smoke authors' arithmetic for 66 / 96 / 190 / 211 designs; the
design counts are exact, the per-design times are one or two points scaled, and the Protenix figures
carry about +/-40% because the GPU was contended):

| Engine | pd-l1 (66) | il7r (96) | egfr (190) | nipah (211) |
|---|---|---|---|---|
| OpenFold3, 5 samples | about 39 min | about 1.1 h | about 4.8 h | 5.3-6.5 h, memory is the risk |
| RF3, 5 samples, ops enabled | about 55 min | about 80 min | about 6.5 h | about 8.3 h |
| Protenix, 1 sample, GB10 | about 3.2 h | about 4.7 h | about 24 h | about 25 h |
| Chai-1, 5 samples, GB10 | 9-11 h | 13-16 h | not measured; about 100-140 h was a guess | not measured |

The RF3 smoke put a full 563-design run at about 17 h on one 3090 with 5 samples (about 13 h with 1 sample).
Protenix at 5 samples, and Chai-1 on the two large targets, are impractical on the GB10 host.

## Merging a candidate and running the benchmark

Each adapter writes the same unprefixed CSV as `refold_af3.py` (header `run_id,idx,sequence,
target_sequence,binder_length,iptm,ptm,ranking_score,plddt_binder_mean,plddt_binder_min,
plddt_target_mean,pae_bt_mean,pae_tb_mean,pae_bb_mean,pae_overall_mean,pae_max,cif,pdb,pae_file`) plus
`<id>_<engine>_pae.npy` files saved binder-first. The CSV has no design-id column and records
**absolute** `pae_file` paths, so merge on the box that ran the engine (or pass `base_dir=`). The rows
are in FASTA order, one per record; a failed design keeps its row with blank scores. The engine's own
`iptm` is not used for ranking: the column that enters a panel is `<engine>_pae_iptm`, derived from the
saved PAE by the shared kernel.

```python
import pandas as pd
from binder_comparison.comparison.scoring import add_iptm_from_pae_files

ENGINE = "openfold3"  # openfold3 | protenix | chai1 | rf3
runs = {"pd-l1": (f"{ENGINE}_pd-l1.csv", "pd-l1.fasta"), ...}  # one CSV per target, and the FASTA fed to it
parts = []
for target, (csv_path, fasta_path) in runs.items():
    d = pd.read_csv(csv_path)
    ids = [ln[1:].split()[0] for ln in open(fasta_path) if ln.startswith(">")]
    assert len(ids) == len(d)          # one row per FASTA record, in FASTA order
    d["id"] = ids
    parts.append(d)
cand = add_iptm_from_pae_files(pd.concat(parts, ignore_index=True), "pae_file", prefix=ENGINE)
merged = pd.read_csv("adaptyv_merged.csv")
merged = merged.merge(cand[["id", f"{ENGINE}_pae_iptm"]], on="id", how="left", validate="one_to_one")
merged.to_csv(f"merged_{ENGINE}.csv", index=False)
```

`ordering` is left at its default, `binder_target`, which is how the files are saved. The prefix is the
engine's own name: a candidate's scores must never be written into an `af3_*` column. The snippet above
was run against the two-design OpenFold3 smoke output and reproduced the smoke report's kernel values
(0.8351 and 0.8410); it has not been run on a full pool. A blank `pae_file` gives a blank iptm, which
clause d (below) then reports. The `id` column must be unique in the merged CSV (`validate="one_to_one"`
refuses otherwise).

Run the comparison (`Evaluator/scripts/panel_benchmark.py`, inside the `binder-eval` environment, with
`PYTHONPATH=<repo>/Evaluator` if the package is not installed):

```
python Evaluator/scripts/panel_benchmark.py --merged merged_openfold3.csv \
   --labels-csv labels.csv --label-column binds \
   --panel boltz_pae_iptm,af3_pae_iptm,esmfold2_pae_iptm \
   --panel boltz_pae_iptm,esmfold2_pae_iptm \
   --panel boltz_pae_iptm,openfold3_pae_iptm,esmfold2_pae_iptm \
   --out panels_openfold3.json
```

All flags: `--merged` (required; needs `id` and the panel columns), `--pool` (default `adaptyv`; the
registry, located by `$BINDERSCOUT_BENCHMARK_STORE`, used when `--labels-csv` is not given),
`--labels-csv` (columns `id`, `target` and the label column), `--label-column` (default `binds`),
`--panel` (repeat; comma-separated columns; **the first is the baseline** and every later panel is
compared with it), `--n-boot` (default 2000), `--seed` (default 0), `--out` (required). The panel value
is the row mean of its columns; a blank engine blanks the design rather than shrinking the mean.
Exit 0 is written output; exit 2 is a refusal that names the counts: a merged id with no label row, a
requested column not in the merged CSV, a blank in a **baseline** column on a measured design, a label
that is not 0/1, a label source with two rows for one design (give the merged CSV a `target` column, or
a labels CSV with one row per id; the merged CSV on the share has none). Designs that were not
measured (registry outcome not `bound`/`not_bound`) or have a null label in `--labels-csv` are
dropped and counted, never read as negatives. Blanks in a **candidate** panel are not refused; they
flow to the pass rule.

## Reading the output JSON

Top level: `pool`, `baseline`, `n_designs`, `n_dropped_unmeasured`, `n_dropped_null_label`, `panels`.
Each panel (keyed by its comma-joined columns) has `columns`, `n_per_target`, `per_target_auc`,
`macro_auc` and `median_auc` (over targets with a finite AUC). Every panel after the baseline also has
`paired_bootstrap_diff` and `passes`:

- `paired_bootstrap_diff.macro_diff`, `ci_low`, `ci_high`: macro AUC of the panel minus the baseline,
  with a 95% interval from a bootstrap that resamples designs within each target, the same indices for
  both panels. `per_target_diff` is the per-target difference.
- `paired_bootstrap_diff.coverage`: per target, `n_total` labelled designs, `n_scored` scored under both
  panels, and `n_dropped_unscored`. Read this before anything else: a panel that is blank for part of a
  target looks like one that agrees with the baseline on the rest.
- `passes.ok` and `passes.failed_clauses`. The rule was fixed before any candidate was run:
  - **a**: the 95% interval is not wholly below zero (fails when `ci_high < 0`).
  - **b**: the macro difference is not worse than -0.02.
  - **c**: no single target is worse than -0.05.
  - **d**: no labelled design was dropped for lacking a score, in any target.
  A missing macro difference fails a and b. A one-class target is a property of the labels, not a failure.

The floor panel `{Boltz-2, ESMFold2}` is run beside every candidate. The design document asks that a
candidate which passes but is indistinguishable from the floor be reported in those words: the slot
exists to keep the three-engine gate satisfied without AF3, not to raise AUC.

**Step-0 numbers (the baseline reproduced from the merged CSV and labels; 563 designs, 0 dropped).**
Baseline macro AUC 0.7231 (egfr 0.6611, il7r 0.7282, nipah 0.7365, pd-l1 0.7665; n 190 / 96 / 211 / 66).
Floor `{Boltz-2, ESMFold2}` macro AUC 0.7279. Floor minus baseline: macro +0.0048, 95% interval
[-0.0217, +0.0295]; per target egfr +0.0711, il7r -0.0051, nipah +0.0250, pd-l1 -0.0717. Both figures
match the previously recorded ones exactly.

**Why clause c is noisy on the small targets.** The floor, which only drops one of three engines, fails
clause c on PD-L1 (-0.0717 against the -0.05 limit, n = 66 designs) while gaining +0.0711 on EGFR (n = 190), so
its overall verdict is `ok: false` with `c: a target worse than -0.05` even though its macro difference
is +0.0048. An AUC from 66 designs moves by several hundredths from one resample to the next, and
a single-target limit of -0.05 sits inside that noise; clause c should be read as a flag on the
smallest targets, not as a finding about the engine. The report must say which of these it is.

## The sample-count caveat

`refold_af3.py` defaults `--num-samples` to 5 and AF3 returns its top-ranked sample, so the AF3 baseline is assumed to be
best-of-5 by ranking score; the setting the baseline pool was actually run with is not recorded. The candidates are run with `--num-samples 1`. That is a deliberate deviation, made because
the measured spread across samples was small and the cost of 5 samples is not practical for two engines:

| Engine | Measured spread across the samples of one design |
|---|---|
| RF3 | iptm of the five samples differs by under 0.001; repeats of the same design vary in the 4th decimal (0.84298-0.84338) |
| Protenix | five samples on one design: iptm 0.8093-0.8134 (range 0.004); a 1-sample run on the same design gave 0.7997 (a different random stream and sample count) |
| Chai-1 | five samples: design 1 0.8262-0.8277, design 2 0.3409-0.3534; repeated runs of the same design differ by about +/-0.007 |
| OpenFold3 | spread across samples not recorded; fixed-seed runs gave an identical iptm (0.849554) across four runs |

These are one or two designs per engine on PD-L1. Best-of-five can only raise a design's score, and
the 1-sample runs have not been compared with the 5-sample runs on the 563 designs. The smoke plan also
called for a cheap 5-sample sensitivity on PD-L1 for OpenFold3 and RF3; it is not recorded as done.
The adapter default stays at 5 samples; only the benchmark runs set 1.

## Known limits

- **Four targets, one dataset.** "Adaptyv" and "ProteinBase" are one dataset, not two corroborating ones.
  Only 563 of the pool's 2,018 designs were scored by all three baseline engines, and that coverage was not
  random (`n_engines_scored` records it); a figure recomputed on all 2,018 is not comparable.
- **Resolution.** The step-0 interval for a difference of this kind has a half-width of about 0.026, so
  differences under roughly 0.03 in macro AUC cannot be told apart from zero, and the floor beating the
  full panel by 0.0048 is not significant. A pass can mean "the third engine hardly matters" as much as
  "the candidate is as good as AF3".
- **`<engine>_pae_iptm` is not the engine's own ipTM.** It is a point-PAE re-derivation with one shared
  kernel. In the smokes it sat below the engine's own value on most designs (OpenFold3 on PD-L1 by 0.007-0.014 and
  on a 621-aa EGFR design by 0.128, but 0.007 above on the IL7R design; RF3 by 0.03-0.14; Protenix by
  0.006-0.08 on strong binders and 0.25 on a weak one) but **above** it for Chai-1 (+0.06 to +0.10), because Chai-1 takes its d0 from the other chain's
  length while the kernel uses the whole complex. The numbers are n = 2 to 5 per engine. Do not quote a
  single correction and do not compare the columns across engines as if they shared a scale; the benchmark
  compares orderings within a target.
- **Native PAE order was checked per engine** and the saved binder-first order is correct for all four.
  How decisively differs: RF3 was settled exactly from the raw PAE bins (the ipTM recomputed from them
  equalled the engine's, 0.8427609 to seven digits, in the target-first reading); Protenix and Chai-1 by a
  wrong reading that scored a weak design far above the engine (Chai-1 design 2: engine 0.353, correct
  reading 0.412, wrong reading 0.889); OpenFold3 only on a 621-aa EGFR design, because the PD-L1 ipTM
  comparison could not discriminate (engine 0.504, correct reading 0.376, wrong reading 0.841). The order is
  also pinned by a test with an asymmetric fixture per adapter.
- **Training overlap is not audited.** The Adaptyv targets may appear in a candidate's training data, as
  they may for AF3. Record each candidate's training cutoff in the report.
- **Hosts differ.** Timings come from different GPU classes (two 24 GB RTX 3090 runs, two aarch64 GB10 runs,
  one of them on a contended GPU) and are not an engine ranking by speed.
- **Open checks.** Three live checks were left owed after the adapters were fixed: Chai-1's recorded target
  MSA depth (about 4045 on PD-L1), a Protenix run with `--layernorm-type torch`, and the RF3 fold log
  printing "cuEquivariance usage disabled via DISABLE_CUEQUIVARIANCE".
- **Failure messages.** When every failure is a deterministic invalid-letter failure, the all-failed and
  partial-failure messages still advise "environment fault" and "--resume"; re-running will not help there.

## Live validation of the opt-in installer and refold (2026-11-07)

Run on 2026-11-07 against a clean extract of the Part 2 code (`git archive` of commit 3c26910, before the later
C++-compiler fix in the installer's early gate) in an isolated scratch checkout, on an x86_64 host with a 24 GB
RTX 3090 and no system C or C++ compiler. Everything below was observed, not inferred.

| Step | Result |
|---|---|
| Licence decline | The licence block printed before any network access. Declining at a TTY prompt exited 1 with "Nothing was created or downloaded", and no `conda/`, `weights/` or `.install_state/protenix` existed afterwards. Without a TTY and without `--yes` the installer printed the block and refused (exit 1). `--second-engine af3` and `--second-engine bogus` each refused (exit 1) with their own message. |
| Install | `bash install/install.sh --second-engine protenix --yes --standalone --skip-examples` took 279 s including a 2.0 GB weights download (about 9.5 min from the first attempt). Result: Python 3.12.16, torch 2.7.1+cu128, protenix 1.1.0; checkpoint 1,475,950,125 bytes with the pinned sha256; Protenix's own downloader fetched all five files (`protenix_base_default_v1.0.0`, `ccd_components_file`, `ccd_components_rdkit_mol_file`, `pdb_cluster_file`, `obsolete_release_data_csv`). |
| Install needed | `--skip-preflight` (the toolchain preflight demands make, gcc and g++; the box has none), plus `CC` and `CXX` pointing at a conda-forge gcc/g++ and `cc`, `gcc`, `g++`, `c++` on `PATH`. |
| Defect found and fixed | The first attempt passed the installer's early gate with a C compiler only, was shown and accepted the licence, then `pip install protenix` died building `scikit-learn-extra` with `No such file or directory: 'g++'`. The early gate now also requires a C++ compiler (commit 15630b4). The fix was not re-run live: it is covered by tests only. |
| `binder-compare refold-protenix --help` | Ran inside the new env and printed the options. |
| Refold, 2 PD-L1 designs (220 aa target, 88 and 84 aa binders), 24 GB RTX 3090 | Exit 0, 148.9 s in total, about 74 s per design: each design is a separate `protenix pred` process with about 41 s of fixed start-up and about 28 s of inference. Peak GPU memory 5,854 MiB against an 18 MiB baseline. ipTM 0.8078 and 0.8998. PAE arrays (308, 308) and (304, 304), i.e. binder plus target tokens. Structure stems `<binder_id>_protenix`. |
| Hostile ambient environment | With `LAYERNORM_TYPE=fast_layernorm` and a hostile Triton cache variable in the caller's environment, the engine log read "Triangle_multiplicative kernel: torch, Triangle_attention kernel: torch" and `refold_run_info.json` recorded torch for all three settings: the adapter overrides the layernorm variable and passes the kernel flags itself. `PROTENIX_ROOT_DIR` was not made hostile (it would have triggered a download); the adapter overwrites it unconditionally. `FUSED_DROPOUT_RESIDUAL` is the only kernel-selecting variable the adapter does not pin; it is inert at inference. |
| Reproducibility | Three runs of the first design with the same seed gave ipTM 0.8078, 0.8071 and 0.8025: Protenix is **not bit-reproducible** here. Treat differences of a few thousandths in ipTM as noise. |
| Report | `binder-compare report --second-engine protenix --second-results ...` with the one engine exited 0 with the usual gate warning. `metrics.csv` had `protenix_pae_iptm`, `panel` = `boltz+protenix+esmfold2` and `second_engine` = `protenix`; the HTML contained "Boltz-2 + Protenix + ESMFold2; AF3 not used" and the sentence that scores from different panels are not on one scale. |
| Uninstall | `--uninstall --tool protenix --yes` removed the env, `weights/protenix` and the marker; the real checkout's `conda/`, `weights/` and `.install_state/` were not touched. |

**Not validated:** aarch64 (the cu128 wheels there are unverified); a full three-engine gate in one report; a re-run
with partial weights; `--resume`; an install with a full toolchain and no `--skip-preflight`; the 15630b4 gate fix.
The peak-memory figures in the memory table above and the 5,854 MiB here come from different complexes (779 tokens
and about 308 tokens).
