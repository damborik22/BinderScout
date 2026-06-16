# PLAN — SoluProt as an evaluator solubility filter

## Why

Every refold engine we run (Boltz-2, Protenix, AF3, ESMFold2) tells us
whether a designed binder is *predicted to fold and bind*. None of them
tells us whether the binder will actually *express solubly* when we hand
the sequence to a wet lab. SoluProt closes that gap: a fast,
sequence-only solubility predictor that adds a `soluprot_score` to every
binder so designs that won't express get dropped before they consume
experimental time.

This sits naturally on the evaluator side of the architecture (alongside
Boltz-2 / Protenix / AF3 / ESMFold2) but is meaningfully different from
those: no GPU, no refold, no PAE — just a sequence in, a probability
out. That makes it the lightest engine we add.

## What SoluProt is

Hon et al. 2021, Bioinformatics 37(1):23-28 (Loschmidt Lab, Masaryk
University). One-line summary:

> Gradient Boosting Machine trained on 11,436 sequences from E. coli
> expression studies, using 96 hand-crafted features extracted from
> amino acid composition, physicochemistry, predicted secondary
> structure, disorder, transmembrane character, and sequence identity
> to known E. coli soluble proteins.

Performance is modest (AUC 0.62, MCC 0.17 on the balanced independent
test set) — SoluProt is best understood as a **screen, not a
ranker**: a 0.2 prediction is genuinely worse than a 0.7, but small
score differences in the 0.4–0.6 band are noise. The right use is to
drop the bottom of the distribution, not to re-rank the top.

## Acquisition

| Component | Source | License |
|---|---|---|
| `soluprot.zip` (script + GBM weights) | https://loschmidt.chemi.muni.cz/soluprot/?page=download | Free for academic; commercial via Enantis |
| `soluprot_data.zip` (train/test set) | same URL | informational only — not needed at runtime |
| TMHMM 2.0 | https://services.healthtech.dtu.dk/services/TMHMM-2.0/ (registration) | academic, no redistribution |
| USEARCH (32-bit free / 64-bit paid) | https://drive5.com/usearch/ | academic 32-bit free; **x86 only** |
| Python 3.7 | conda-forge | open |
| scikit-learn 0.20.1 | conda-forge | BSD |
| biopython 1.74 | conda-forge | BSD-like |

Citation we owe in our docs (and in CITATION.cff if/when we add one):

> Hon, J., Marusiak, M., Martinek, T., et al. (2021).
> "SoluProt: prediction of soluble protein expression in
> *Escherichia coli*." *Bioinformatics* 37(1), 23–28.

**Redistribution constraint:** we cannot mirror SoluProt's script /
weights in this repo. Same model as our AF3 weights: the installer
fetches them on first install, the user accepts the academic terms.
TMHMM is even more restrictive — the installer should fail closed and
print the registration URL.

## Where it fits in the pipeline

```
extract → sequences.fasta
   │
   ├──► refold-boltz2  ─┐
   ├──► refold-protenix ├──► report (current)
   ├──► refold-af3      │
   └──► refold-esmfold2 ┘
        + (NEW) filter-soluprot ──► soluprot_results.csv ──► report
```

Run order: SoluProt is sequence-only and stateless. It can run
*before* any refold (in parallel with them, even). The output is a CSV
keyed on sequence with two columns: `soluprot_score` (float 0–1) and
`passes_soluprot_filter` (bool, score ≥ threshold).

In `evaluate.sh`, the new step would slot between Step 0
(`parse-seqs`) and Step 1 (`refold-boltz2`). That way, if the user
opts in (`--use-soluprot`), the top of the pipeline already knows
which designs are likely to express and can either:

1. **Soft mode (default):** keep all sequences, add the score and
   pass-flag columns to the report.
2. **Hard mode (`--filter-soluprot`):** drop sequences below threshold
   from the FASTA *before* refolding. Saves GPU time on designs we
   wouldn't pursue anyway.

## Architecture

### Conda env

New `binder-eval-soluprot` conda env (mirrors the existing
`binder-eval` / `binder-eval-af3` / `binder-eval-esmfold2` family):

```yaml
# Evaluator/envs/binder-eval-soluprot.yml
name: binder-eval-soluprot
channels:
  - conda-forge
  - bioconda
dependencies:
  - python=3.7        # SoluProt's pinned version
  - scikit-learn=0.20.1
  - biopython=1.74
  - pandas
  - tqdm
  - perl              # TMHMM is Perl
  - pip
```

USEARCH and TMHMM are not on conda; the installer drops them into
`Evaluator/tools/soluprot/` after the env is created and prints
the registration URLs if download fails.

### Files to add

| File | Purpose |
|---|---|
| `Evaluator/envs/binder-eval-soluprot.yml` | conda env spec |
| `Evaluator/binder_comparison/cli/filter_soluprot.py` | argparse subcommand |
| `Evaluator/binder_comparison/refolding/soluprot_runner.py` | wrapper (despite the dir name; SoluProt isn't a refolder but lives next to the engines) |
| `Evaluator/scripts/filter_soluprot.py` | standalone CSV writer (mirrors `refold_boltz2.py` style) |
| `Evaluator/tools/soluprot/` (gitignored, runtime) | unpacked SoluProt script, weights, TMHMM, USEARCH |

The "refolding" directory rename is out of scope here; SoluProt rides
under that namespace for now because the call shape matches
(`sequences → CSV with one score per sequence`).

### CLI subcommand

```bash
binder-compare filter-soluprot \
    --sequences sequences.fasta \
    -o soluprot_results.csv \
    [--threshold 0.5] \
    [--scripts-path /path/to/soluprot/]
```

Schema extension in `core/schema.py:NativeMetrics`:

```python
# ---- SoluProt (sequence-only solubility predictor) ----
soluprot_score: float | None = None        # 0–1 probability of soluble expression
soluprot_passes: bool | None = None        # score >= threshold
```

These land as `native_soluprot_score` and `native_soluprot_passes` in
the merged CSV via the existing `MetricResult.to_flat_dict()`
machinery. No changes to merger needed — SoluProt joins via the
sidecar `native_metrics.csv` exactly like the per-tool design-time
metrics already do.

### Evaluator wiring

**`Evaluator/evaluate.sh`:**

- New flag `--skip-soluprot` (default: auto-detect
  `binder-eval-soluprot` env; if missing, set `SKIP_SOLUPROT=1`).
- New flag `--soluprot-threshold N` (default 0.5).
- New flag `--soluprot-filter` (default off): when set, drop sequences
  below threshold from the FASTA passed to the refold steps.
- New step between Step 0 (parse-seqs) and Step 1 (refold-boltz2):

  ```bash
  if [[ $SKIP_SOLUPROT -eq 0 ]]; then
      conda run -n binder-eval-soluprot binder-compare filter-soluprot \
          --sequences "$SEQUENCES" \
          -o "$OUTPUT/soluprot_results.csv" \
          --threshold "$SOLUPROT_THRESHOLD"
      if [[ $SOLUPROT_FILTER -eq 1 ]]; then
          # Rewrite $SEQUENCES to drop sequences with passes_soluprot_filter==0
          ...
      fi
  fi
  ```
- Report invocation gets a new `--soluprot-results "$SOLUPROT_CSV"`
  argument when SoluProt ran.

**`binder-compare report`:**

- New argparse `--soluprot-results CSV` argument.
- The merger joins it on sequence (analogous to how it joins the
  refold engine CSVs — but no `_prefix` widening, just the two
  columns).
- New `--soluprot-threshold` and `--soluprot-filter` flags so the
  report can re-filter on a different threshold than `evaluate.sh`
  used (cheap because SoluProt scores are already cached in the CSV).
- The Adaptyv ranking hierarchy (in
  `comparison/scoring.py:rank_by_adaptyv_method`) is augmented so
  `passes_soluprot_filter == 1` is the first sort key, ahead of
  `ipsae_valid`. Rationale: there's no point in surfacing a
  high-ipSAE binder we can't express. Off by default; opt in via
  `--soluprot-rank-priority`.

### Installer

Mirror the AF3 / ESMFold2 opt-in pattern. New `--tool soluprot`
(aliases: `solu`, `solubility`) on both `install/install.sh` and
`install/install_aarch.sh`. NOT in `--tool all` — keep it opt-in
because of the TMHMM/USEARCH download friction.

`install_soluprot()` steps:

1. Create `binder-eval-soluprot` conda env from yml.
2. Download `soluprot.zip` from
   `https://loschmidt.chemi.muni.cz/soluprot/?page=download` → unpack to
   `Evaluator/tools/soluprot/`.
3. Check for USEARCH binary at `Evaluator/tools/soluprot/usearch`; if
   missing, print the drive5.com URL with arch-aware instructions
   (x86 free 32-bit; aarch64 — see "Open questions" below).
4. Check for TMHMM at `Evaluator/tools/soluprot/tmhmm-2.0/bin/tmhmm`; if
   missing, print the DTU registration URL and exit 0 (don't fail
   install — user can drop the file in later).
5. `pip install -e Evaluator/` into the env so `binder-compare` is
   available.
6. Smoke test: `binder-compare filter-soluprot --help`.
7. Write `bin/soluprot` shortcut.

## Filter semantics

**Default threshold:** 0.5 (the paper's recommendation for the
balanced training distribution). De novo binders are short and may
sit lower on the score distribution than typical full proteins, so
0.5 may be too strict — we should publish the distribution from a
real run (e.g. 100 CALCA binders) before locking in the default.

**Pass/fail vs continuous:** Two columns in the output:

- `soluprot_score` (float, always present once the step has run)
- `passes_soluprot_filter` (bool, derived from score ≥ threshold;
  threshold stored alongside so the report can re-derive)

**What "dropping" means in `--filter-soluprot` hard mode:**
sequences below threshold are removed from `sequences.fasta` before
the refold steps. They never appear in the report. This is the GPU-
saver mode; the user explicitly opts in.

**What "soft" mode shows:** every sequence still gets refolded; the
report shows the SoluProt column next to the refold metrics. The
top-20 table flags `passes_soluprot_filter == 0` rows with a
distinct background so the user can decide per-design.

## Acceptance criteria

1. `bindmaster install --tool soluprot` creates the conda env,
   downloads `soluprot.zip`, prints a clear message if TMHMM /
   USEARCH need manual placement, smoke-tests
   `binder-compare filter-soluprot --help`.
2. `binder-compare filter-soluprot --sequences toy.fasta -o out.csv`
   on a 3-sequence FASTA writes a CSV with `sequence,
   soluprot_score, passes_soluprot_filter` columns and a sane
   score distribution (not all NaN, not all 0).
3. `bash evaluate.sh --sequences seqs.fasta --target-seq SEQ
   --output ./r` runs SoluProt before Boltz-2 if the env exists,
   passes `--soluprot-results` to the report, and produces a
   `report.html` with a SoluProt column visible in the top-20.
4. `--soluprot-filter` hard mode drops sub-threshold sequences from
   the FASTA before refolding (verified by row count in
   `boltz2_results.csv`).
5. Configurator wizard Step 5 sub-prompt for refolding engines
   includes SoluProt (under the engines list — labeled "screen"
   rather than "engine" to distinguish it from the refolders).

## Open questions for you to decide

1. **aarch64 support. — RESOLVED (2026-06-16), aarch64 is now enabled.**
   On inspection the blocker is not one thing but four, all handled in
   `install/install_aarch.sh:install_soluprot()` and validated end-to-end on
   DGX Spark (agreement r≈0.96 / 90% pass-fail vs the x86 reference output):
   - **USEARCH** (identity feature): x86 binary, and `vsearch` cannot
     substitute (it is nucleotide-only — silently strips amino acids).
     Fix: compile open-source **USEARCH v12** (`rcedgar/usearch12`, GPLv3,
     portable C++11, no x86 intrinsics) from source. The `bioconda::usearch
     12.0_beta` aarch64 build crashes at startup, so source build it is. The
     shipped `-search_global` spelling is patched to `usearch_global`.
   - **TMHMM** (3 of 96 features): also x86-only, no source. Fix: SoluProt's
     shipped `--no_tmhmm` model (`grad_clf_v1_tc_notmhmm.pkl`, ~-0.5%).
   - **scikit-learn 0.20.1**: no aarch64 build, and the model pickle won't
     `predict()` under aarch64's 0.21/0.22 (raises `get_init_raw_predictions`).
     Fix: pip-build **scikit-learn 0.20.4** from source (same minor series; still
     `<0.23` so `sklearn.externals.joblib` imports).
   - **biopython 1.74**: no aarch64 build; the oldest (1.78) removed
     `Bio.Alphabet`. Fix: patch `soluprot.py` + the 3 `feature_scripts/*.py`
     that import it. Also pin `numpy<1.24` / `pandas<1.4`.
   The earlier "Python reimplementation of USEARCH" / "drop the feature" ideas
   are unnecessary — the source-built USEARCH v12 reproduces the exact feature.

2. **Default threshold.** 0.5 is the paper default, but binders are
   short and atypical. After we run SoluProt on the existing CALCA /
   ApoE design pools we already have on master, we'll have an
   empirical distribution to set the default from. Until then, ship
   with 0.5 and document the override.

3. **Whether SoluProt should be in `--tool all`.** Recommendation: No.
   TMHMM is gated by registration and USEARCH is gated by arch — both
   are friction-y enough to keep it opt-in. Same logic as AF3 and
   ESMFold2.

4. **Whether `--soluprot-rank-priority` should be the default in the
   report.** Tradeoff: if on, the top-20 only contains designs we
   expect to express (good for experimental shortlists). If off,
   the top-20 may include high-ipSAE designs that won't express
   (good for understanding what the refold engines think).
   Recommendation: off by default; document the trade-off; add a
   `report.html` toggle button that re-sorts on click without
   re-running the pipeline.

5. **Where to surface the score in the report HTML.** Three options:
   (a) New column in the top-20 table only.
   (b) (a) + a SoluProt distribution histogram in the summary
   section.
   (c) (a) + (b) + a small SoluProt panel in each per-tool top-N
   section.
   Recommendation: start with (a); add (b) when we have real data
   to plot.

## Out of scope (for the first cut)

- SoluProtMPNN. We confirmed there is no SoluProtMPNN tool from
  Loschmidt Lab today (their software list has SoluProt 1.0 only;
  SoluProtMutDB is a database of solubility *mutations*, not a
  predictor). If the user was thinking of NetSolP / DeepSol /
  Proteoscape, those are separate projects worth a follow-up plan.
- Mutation suggestion. SoluProt only scores; it doesn't propose
  mutations to improve solubility. We could chain SoluProt with
  ProteinMPNN-based redesign of low-scoring positions later, but
  that's a separate scope.
- Per-residue solubility heatmap. SoluProt is a whole-sequence
  classifier; a residue-level heatmap would need a different
  predictor.

## Implementation slices (suggested commit boundaries)

1. **Schema + dry runner.** Add `soluprot_score` / `soluprot_passes`
   to `NativeMetrics`. Add a stub `filter_soluprot.py` CLI that
   reads a FASTA, writes a CSV with mock scores. Unit test the
   sidecar join. No conda env, no real SoluProt yet.
2. **Real runner + env.** Add `binder-eval-soluprot.yml`. Add
   `soluprot_runner.py` that invokes the unpacked
   SoluProt script. Add `Evaluator/scripts/filter_soluprot.py`. CLI
   produces real scores on a 3-sequence smoke test.
3. **Installer.** `install_soluprot()` in both installers. Downloads
   `soluprot.zip`. Handles TMHMM / USEARCH gracefully. Smoke test
   passes.
4. **Orchestration.** `evaluate.sh` gains `--skip-soluprot`,
   `--soluprot-threshold`, `--soluprot-filter`. Step inserted
   before `refold-boltz2`. Report gains `--soluprot-results`.
5. **Ranking.** `rank_by_adaptyv_method` gains the optional
   solubility-first hierarchy. Report HTML gains the SoluProt
   column + a sortable toggle.
6. **Configurator.** Step 5's refold-engine sub-prompt grows a
   SoluProt checkbox; if checked, write the right
   `--use-soluprot` flag into the generated `run_evaluate.sh`.
7. **Docs.** README mentions SoluProt as a refold-time screen.
   CLAUDE.md gets a SoluProt section under "Tools and what they do".

Each slice is independently shippable and reversible.
