# PLAN — audit fixes

> **✅ Implemented — all 10 batches are complete.** This plan is left as written, so the reasoning
> behind each fix stays readable next to the code that landed. The work is on
> `claude/audit-fixes-nb3kbk` (15 commits after the three docs commits); the four decisions below were
> taken by the repository owner and implemented as recorded. The test suite went from **213 to 338**
> passing, with each regression test verified to fail against the pre-fix code before its fix landed.
> The one thing deliberately not built is the **GUI** — that is a project, not a fix, and still needs a
> decision on which architecture to pursue.

Proposed fixes for the 43 findings in [`repo_analysis_2026-07-26.html`](repo_analysis_2026-07-26.html).
Finding IDs (F1, F2, …) refer to that document.

Grouped into **10 independently-shippable batches**, ordered by value. Each batch is one PR
(`CONTRIBUTING.md`: one logical change per PR). Every diff below was written against the code as it
stood at `a600090` and the surrounding lines were read; the code that shipped follows these proposals
but is not always identical to them — the commits are the record.

---

## Batch order at a glance

| # | Batch | Findings | Files | Risk | Why now |
|---|---|---|---|---|---|
| 1 | Wrong-target bugs | F1, F2 | `configurator.py` | low | Silently designs against the wrong protein |
| 2 | Ranking integrity | F5, F6, F23, F33 | `scoring.py`, `merger.py`, `report.py` | **changes rankings** | Decides what the wet lab orders |
| 3 | Report truthfulness | F32, F20, F34, F35 | `visualization/report.py` | low | The report currently misdescribes its own method |
| 4 | Unbreak the click path | F8, F9, F3, F15 | `configurator.py` | low | Documented commands fail as typed |
| 5 | Ingestion coverage | F38, F40, F39, F42 | `cli/run.py`, `cli/extract.py`, `extractors/rfd3.py` | low | Tools silently absent from the report |
| 6 | Installer safety | F11, F26, F18, F24 | `install.sh` | medium | `--yes` deletes 4 GB of weights |
| 7 | aarch64 parity | F12, F13, F14, F16 | `install_aarch.sh`, `bindmaster.py` | medium | Needs Spark hardware to verify |
| 8 | Headless configurator | non-agentic blocker | `configurator.py` | low | The one true no-LLM blocker |
| 9 | Docs + notices | F4, F41, F17, F19, F30, F31 | docs, `.claude/skills` | none | Follows from decisions |
| 10 | Tests | F29, F37 + regressions | `tests/` | none | Locks batches 1–5 in |

Batches 1–5 are pure Python, independently reviewable, and together close every finding that changes
a result. Batch 2 is the only one that alters existing outputs.

---

## Batch 1 — wrong-target bugs

**F1 · `extract_sequence_from_cif` ignores `chain_id` in both branches**

`chain_id` is accepted and never used. Branch 1 returns the longest `_entity_poly` entity; branch 2
concatenates every chain's CA records. `extract_sequence_from_pdb:364` already filters correctly, so
only mmCIF input is affected.

```diff
@@ configurator/configurator.py:497
-def _cif_atom_site_seq(text: str) -> str | None:
-    """Fallback: extract sequence from _atom_site CA records."""
+def _cif_atom_site_seq(text: str, chain_id: str | None = None) -> str | None:
+    """Extract sequence from _atom_site CA records, optionally for one chain only."""
@@ configurator/configurator.py:524
             if row[col["label_atom_id"]].strip("'\"") == "CA":
                 chain = row[col["label_asym_id"]].strip("'\"")
+                if chain_id is not None and chain.upper() != chain_id.upper():
+                    i += n_cols
+                    continue
                 try:

@@ configurator/configurator.py:551  (extract_sequence_from_cif)
-    # Try canonical _entity_poly first (chain-agnostic, longest entity)
-    seq = _cif_entity_poly_seq(text)
-    if seq:
-        return seq
-
-    # Fallback: _atom_site CA records for requested chain
-    ...inline loop...
+    # Chain-specific coordinates first — this is the only branch that can honour chain_id.
+    seq = _cif_atom_site_seq(text, chain_id)
+    if seq:
+        return seq
+
+    # No coordinates for that chain. _entity_poly is chain-agnostic (longest entity),
+    # so using it means silently targeting a different chain — say so out loud.
+    seq = _cif_entity_poly_seq(text)
+    if seq:
+        print_warn(
+            f"Chain {chain_id} has no CA records in {Path(cif_path).name}; "
+            f"falling back to the longest _entity_poly entity ({len(seq)} aa). "
+            f"Verify this is the chain you meant."
+        )
+        return seq
+    return None
```

The inline `_atom_site` loop currently duplicated inside `extract_sequence_from_cif` (`:557–575`) is
deleted — `_cif_atom_site_seq` already does the same thing.

**F2 · Mosaic epitope indices always resolve against chain A**

```diff
@@ configurator/configurator.py:913  (hotspots_to_epitope_idx)
-    chain = cfg.get("target_chain") or cfg.get("chain") or "A"
+    # The wizard stores the (possibly comma-separated) selection in cfg["chains"] (:2851).
+    # Neither "target_chain" nor "chain" is ever set, so those lookups always fell back to "A".
+    chain = (cfg.get("chains") or "A").split(",")[0].strip() or "A"
```

**Tests** (`tests/configurator/test_configurator_writers.py`)

- two-chain mmCIF fixture with `_entity_poly`, request the *shorter* chain → returns the short one
- same fixture with `_entity_poly` stripped → returns one chain, not the concatenation
- `_entity_poly`-only fixture (no `_atom_site`) → returns a sequence *and* warns
- `hotspots_to_epitope_idx({"chains": "B,C", ...})` resolves against B

---

## Batch 2 — ranking integrity

> **Changes the ordering of existing reports.** Re-run `report` on an archived campaign and diff
> `top30_candidates.csv` before merging, so the movement is understood rather than discovered later.

**F5 · Single-engine designs outrank multi-engine ones**

`DataFrame.mean(axis=1)` skips NaN, so a design only Boltz-2 refolded gets
`consensus_iptm_mean` = its single Boltz value. Since Mosaic *is* Boltz-2 hallucination, that is the
one engine biased in its favour — the exact failure the two-stage design exists to prevent.
`consensus_iptm_n` is already computed (`:713`) and simply unused.

```diff
@@ Evaluator/binder_comparison/comparison/scoring.py:790
-def rank_by_two_stage(df: pd.DataFrame, screen_frac: float = 0.5, screen_metric: str = "max") -> pd.DataFrame:
+def rank_by_two_stage(
+    df: pd.DataFrame, screen_frac: float = 0.5, screen_metric: str = "max", min_engines: int = 2
+) -> pd.DataFrame:
@@ :828
     screen_col = "consensus_iptm_mean" if screen_metric == "mean" else "consensus_iptm"
     cons = pd.to_numeric(result[screen_col], errors="coerce")
-    eligible = cons.notna()
+    # A design scored by one engine has mean == that engine's value, so it would compete with
+    # 3-engine means on an incomparable scale. Require cross-engine support to pass the screen.
+    n_eng = pd.to_numeric(result.get("consensus_iptm_n", 0), errors="coerce").fillna(0)
+    eligible = cons.notna() & (n_eng >= min_engines)
     n_eligible = int(eligible.sum())
-    n_keep = round(n_eligible * screen_frac)
+    n_keep = math.ceil(n_eligible * screen_frac)          # F23
     thr = cons[eligible].nlargest(n_keep).min() if n_keep else float("inf")
     result["passes_max_screen"] = eligible & (cons >= thr)

-    sort_keys = ["passes_max_screen", "consensus_iptm_mean", "consensus_iptm"]
-    ascending = [False, False, False]
+    sort_keys = ["passes_max_screen", "consensus_iptm_mean", "consensus_iptm_n", "consensus_iptm"]
+    ascending = [False, False, False, False]
```

Add `import math` at `scoring.py:21`.

`min_engines=2` degrades gracefully: on a single-engine install *nothing* passes the screen, which
is honest — the two-stage method needs cross-engine evidence it does not have. Batch 3's F34 fix
handles the reporting side of that case. Expose it as `--min-engines` in `cli/report.py` so a
single-engine user can opt into `--min-engines 1` knowingly.

**F23 · banker's rounding** — folded into the diff above. Measured today: N=1→0 kept, N=3→2, N=5→2,
N=7→4. `math.ceil` gives 1/2/3/4.

**F6 · Duplicate sequences fan out report rows**

`cli/autosize.py:160` already guards the analogous merge with `.drop_duplicates("sequence")`. Same
guard, plus a `validate=` so a regression raises instead of silently inflating row counts.

```diff
@@ Evaluator/binder_comparison/comparison/merger.py:126
     meta_df = pd.DataFrame(meta_rows)
-    return pd.merge(df, meta_df, on="sequence", how="left")
+    # One metadata row per sequence. With --keep-duplicates the FASTA can carry the same
+    # sequence under several binder_ids; without this the left join multiplies metrics rows.
+    n_before = len(meta_df)
+    meta_df = meta_df.drop_duplicates("sequence", keep="first")
+    if len(meta_df) < n_before:
+        warnings.warn(
+            f"[merger] {n_before - len(meta_df)} duplicate sequence(s) in {fasta_path} — "
+            f"keeping the first binder_id for each."
+        )
+    return pd.merge(df, meta_df, on="sequence", how="left", validate="m:1")
```

**F33 · AF3 and Protenix ipSAE never reach the shortlist**

Two naming conventions exist and `scoring.py:395–400` already documents them and maps each engine to
the right column in `_ENGINE_IPSAE_COLS` — Boltz uses `boltz_pae_ipsae_min` (written at `:239`),
everything else uses `<engine>_ipsae_min` (written at `:315`). Five call sites hardcode the wrong
`*_pae_ipsae_min` form for the non-Boltz engines. **Fix by using the existing map, not by renaming**:

```diff
@@ Evaluator/binder_comparison/cli/report.py:412
         "boltz_pae_ipsae_min",
-        "protenix_pae_ipsae_min",
-        "af3_pae_ipsae_min",
-        "esmfold2_ipsae_min",
+        "protenix_ipsae_min",
+        "af3_ipsae_min",
+        "esmfold2_ipsae_min",
```

```diff
@@ Evaluator/binder_comparison/visualization/report.py:2639
-        ("boltz", "boltz_pae_ipsae_min", "Boltz-2 ≥ 0.61"),
-        ("protenix", "protenix_pae_ipsae_min", "Protenix ≥ 0.61"),
-        ("af3", "af3_pae_ipsae_min", "AF3 ≥ 0.61"),
-        ("af2", "af2_pae_ipsae_min", "AF2 ≥ 0.30 …"),
+        ("boltz", _ENGINE_IPSAE_COLS["boltz"], "Boltz-2 ≥ 0.61"),
+        ("protenix", _ENGINE_IPSAE_COLS["protenix"], "Protenix ≥ 0.61"),
+        ("af3", _ENGINE_IPSAE_COLS["af3"], "AF3 ≥ 0.61"),
+        ("esmfold2", _ENGINE_IPSAE_COLS["esmfold2"], "ESMFold2 ≥ 0.61"),
```

Same substitution at `visualization/report.py:2608–2610`. Drop the `af2` row — Part I removed AF2
refolding, so it can never populate. Import `_ENGINE_IPSAE_COLS` from `..comparison.scoring`.

The root cause is that `_top_cols` filters silently: `_available = [c for c in _top_cols if c in
df.columns]` (`cli/report.py:438`). A missing column is indistinguishable from an absent engine. Worth
one line:

```diff
+    _expected = {_ENGINE_IPSAE_COLS[e] for e in ("boltz", "af3", "esmfold2") if f"{e}_pae_iptm" in df.columns}
+    for col in _expected - set(df.columns):
+        warnings.warn(f"[report] engine present but {col} missing — shortlist will omit it")
     _available = [c for c in _top_cols if c in df.columns]
```

**Tests** (`tests/binder_comparison/test_scoring.py`, `test_merger.py` — new)

- 3 designs: engines {3, 1, 3}. The 1-engine design must not pass the screen even with the highest value
- `n_eligible` 1..8 → `n_keep` == `ceil(n/2)`
- FASTA with one sequence twice → merged row count unchanged; warning emitted
- a frame with `af3_pae_iptm` but no `af3_ipsae_min` → warns
- `min_engines=1` reproduces today's behaviour exactly (regression guard for the opt-out)

---

## Batch 3 — report truthfulness

**F32 · Every report describes the reverted mean-screen default**

`generate_report()` takes `rank_method` but not `screen_metric`, so the `two_stage` blurb at
`:1837–1846` is a static string still describing the pre-`5769064` default. The neighbouring
`_top_table_legend_html` docstring states the intent — "so a reader can never get a description that
[mismatches]" — this just completes it.

```diff
@@ Evaluator/binder_comparison/visualization/report.py:1305  (generate_report signature)
     rank_method: str = "adaptyv",
+    screen_metric: str = "max",

@@ :1836
-        "two_stage": (
-            f"Ranking is <b>two-stage mean iPTM</b> … <b>Stage 1 — screen:</b> "
-            f"<code>consensus_iptm_mean</code> = mean(boltz2, af3, esmfold2 iPTM); … "
-            f"Mean was selected as default over max because … "
-            f"The legacy max-screen (<code>--screen-metric max</code>) is the precision-leaning "
-            f"alternative … so Stage 1 + Stage 2 collapse to a single mean-iPTM gate-then-rank."
-        ),
+        "two_stage": _two_stage_methodology_html(screen_metric),
```

with a small helper that renders the screen half from the argument:

```python
def _two_stage_methodology_html(screen_metric: str) -> str:
    """Methodology text for --rank-by two_stage, derived from the ACTIVE screen metric.

    Must never be a fixed string: the default flipped mean→max in 5769064 and the
    hardcoded copy silently kept describing the old behaviour.
    """
    if screen_metric == "mean":
        stage1 = (
            "<b>Stage 1 — screen:</b> <code>consensus_iptm_mean</code> = mean of the per-engine "
            "PAE-recomputed iPTMs; the top 50% form the binder-likely pool. The stricter screen "
            "(Adaptyv macro AUC <b>0.710 vs 0.689</b> for max)."
        )
    else:
        stage1 = (
            "<b>Stage 1 — screen:</b> <code>consensus_iptm</code> = <b>max</b> of the per-engine "
            "PAE-recomputed iPTMs; the top 50% form the binder-likely pool. The lenient recall step "
            "— keep a design if <i>any</i> engine rates it highly (ProteinBase macro AUC <b>~0.755</b>). "
            "Use <code>--screen-metric mean</code> for the stricter screen."
        )
    return (
        f"Ranking is <b>two-stage cross-engine iPTM</b>, validated on two <em>internal</em> 4-target "
        f"benchmarks (Adaptyv n = 662; ProteinBase n = 175). {stage1} <b>Stage 2 — rank:</b> survivors "
        f"are ordered by <code>consensus_iptm_mean</code> — demanding multi-engine consensus at the "
        f"sharp end lifts <b>precision@top-10% to 0.92 vs 0.79</b> for max alone. All designs are "
        f"ranked; the screen is a flag, nothing is dropped. …"
    )
```

Pass it through from `cli/report.py` (which already has `screen_metric` at `:346`) at the
`generate_report(...)` call. Also state the engine list from the columns actually present rather than
the hardcoded "(boltz2, af3, esmfold2)", and — after Batch 2 — mention the `min_engines` gate.

**F20 · The 3D viewer loads NGL from a CDN**

`cli/epitope_map.py:40` already solves this with `_VENDORED_NGL = "tools/ngl/ngl-2.3.1.min.js"`.
Back-port it; the vendored 1.3 MB file is otherwise dead weight.

```diff
@@ Evaluator/binder_comparison/visualization/report.py:400
-<script src="https://unpkg.com/ngl@2.3.1/dist/ngl.js"></script>
+<script>{ngl_js}</script>
```

where `ngl_js` is the vendored file read at render time, falling back to the CDN tag with a printed
warning if it is missing. Cost: +1.3 MB per `report.html`, which is already multi-MB from base64
plots. Benefit: the viewer works on an air-gapped node — the environment this repo otherwise
engineers around carefully.

**F34 · `wetlab_recommended` is always False on a single-engine install**

```diff
@@ Evaluator/binder_comparison/comparison/scoring.py:996
     if "agreement_count" in out.columns:
         agreement = pd.to_numeric(out["agreement_count"], errors="coerce")
+        # agreement_count cannot exceed the number of engines present, and a single-engine
+        # run is a supported configuration (evaluate.sh:146-163 auto-skips absent envs).
+        # Requiring >= 2 there fails every design for a reason the user cannot act on.
+        n_engines = int(pd.to_numeric(out.get("consensus_iptm_n", 0), errors="coerce").max() or 0)
+        if n_engines < agreement_min:
+            agreement = pd.Series([float("nan")] * len(out), index=out.index)
         for i, val in enumerate(agreement):
```

and add `"single-engine run — cross-engine agreement not assessed"` to `wetlab_reason` so the column
explains itself instead of going quietly blank.

**F35 · ipSAE thresholds hardcoded 18× in the HTML layer**

`scoring.py:28–30` holds the canonical constants; `visualization/report.py` retypes `0.61` eighteen
times and `top30_slim.py` once. So `--threshold-boltz 0.50` changes the computation while the labels
keep saying 0.61. Mechanical fix: import the constants, and thread the resolved threshold into
`_tier()` and the legend builders as a parameter. No behaviour change when the flag is unused —
which makes it safe to land alongside the rest.

**Tests**

- `generate_report(..., screen_metric="max")` → HTML contains "max of the per-engine", not "Mean was selected"
- `screen_metric="mean"` → the converse
- report.html contains no `unpkg.com` when the vendored NGL is present
- single-engine frame → `wetlab_recommended` not uniformly False; reason mentions single-engine
- `--threshold-boltz 0.50` → rendered legend says 0.50

---

## Batch 4 — unbreak the click path

**F8 · `run_all.sh` exits 1 before any tool runs when Mosaic is enabled**

The Mosaic block is emitted *first* and hard-exits unless `mosaic/designs.csv` exists. Move it last
and warn instead of exiting, so the other six tools run.

```diff
@@ configurator/configurator.py:1556  (write_run_all — move this block to the END of the tool sequence)
     '    echo "  Mosaic requires interactive input. Run run_mosaic.sh first, then re-run run_all.sh." >&2',
-    "    exit 1",
+    '    echo "  Skipping Mosaic — the other tools have already run." >&2',
```

**F9 · RFD3 and Protein-Hunter are invisible in three UI surfaces**

`run_pipeline()` (`:2662`) dispatches five design tools; `print_tree()` (`:743`) shows four; the
"To run later" list (`:3423`) shows five. All three are hand-maintained if-chains. Replace with one
ordered table used by all of them:

```python
# Single source of truth: (tools_enabled key, run-script name, display label, output subdir).
# Every UI surface iterates this — adding a tool must not require touching four if-chains.
TOOL_SEQUENCE = [
    ("mosaic", "run_mosaic.sh", "Mosaic", "mosaic"),
    ("boltzgen", "run_boltzgen.sh", "BoltzGen", "boltzgen"),
    ("bindcraft", "run_bindcraft.sh", "BindCraft", "bindcraft"),
    ("pxdesign_local", "run_pxdesign.sh", "PXDesign", "pxdesign"),
    ("proteina_complexa", "run_proteina_complexa.sh", "Proteina-Complexa", "proteina_complexa"),
    ("protein_hunter", "run_protein_hunter.sh", "Protein-Hunter", "protein_hunter"),
    ("rfd3", "run_rfd3.sh", "RFD3", "rfd3"),
]
```

`tui/app.py:72, 325, 473` hardcode the same four-tool tuple (F27) — import the output-subdir column
from here rather than keeping a fifth copy.

**F3 · RFD3 designs never reach the Evaluator**

```diff
@@ configurator/configurator.py:2459
-        design_dirs.append(("--rfd3", str(run_dir / "rfd3" / "outputs")))
+        # run_rfd3.sh writes rfd3/sequences.csv (:1963); run_all.sh already checks that path (:1610).
+        design_dirs.append(("--rfd3", str(run_dir / "rfd3")))
```

and drop the `(run_dir / "rfd3" / "outputs").mkdir(...)` at `:2623` that creates the empty decoy.

**F15 · The provenance block kills every run script without `nvidia-smi`**

Reproduced: under `set -euo pipefail` a failing command substitution in an assignment exits 127. The
three neighbouring lines are already guarded; these two were missed.

```diff
@@ configurator/configurator.py:1157
-GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i {gpu_id_var} 2>/dev/null | head -1)
-GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i {gpu_id_var} 2>/dev/null | head -1)
+GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader -i {gpu_id_var} 2>/dev/null | head -1 || echo "unknown")
+GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i {gpu_id_var} 2>/dev/null | head -1 || echo "0")
```

Land this **before** F28 (adding the provenance block to BindCraft/BoltzGen/Mosaic), or those three
tools inherit the crash.

**Tests**

- generate a run dir with all seven tools; assert every `run_<tool>.sh` appears in `run_all.sh`, in
  the preview tree, and in the next-steps list
- `bash -n` every generated script (catches quoting regressions cheaply)
- run the generated settings block with `PATH` stripped of `nvidia-smi` → exit 0

---

## Batch 5 — ingestion coverage

**F38 · `binder-compare run` cannot ingest RFD3, Protein-Hunter or Proteina-Complexa**

`cli/run.py:184–187` offers four tool flags; `cli/extract.py:177–181` offers all seven. Share one
argparse group so they cannot diverge again:

```python
# Evaluator/binder_comparison/cli/_tool_args.py  (new, ~20 lines)
TOOL_FLAGS = [
    ("--bindcraft", "BindCraft output directory"),
    ("--boltzgen", "BoltzGen output directory"),
    ("--mosaic", "Mosaic output directory (containing designs.csv)"),
    ("--pxdesign", "PXDesign output directory (containing summary.csv)"),
    ("--proteina-complexa", "Proteina-Complexa output directory"),
    ("--protein-hunter", "Protein-Hunter output directory"),
    ("--rfd3", "RFD3 / foundry output directory"),
]


def add_tool_args(p):
    for flag, help_text in TOOL_FLAGS:
        p.add_argument(flag, metavar="DIR", help=help_text)
```

Called from both `extract.add_parser` and `run.add_parser`. `run` must then forward the three new
directories into its extract step.

**F40 · A requested tool yielding zero sequences is not an error**

The existing guard only fires when *every* tool yields nothing, so one typo'd path silently shrinks
the pool and hours of GPU time are spent on it.

```diff
@@ Evaluator/binder_comparison/cli/extract.py:81
+    empty = [t for t, n in per_tool_counts.items() if n == 0]
+    if empty and not args.allow_empty:
+        print(
+            f"[extract] ERROR: {', '.join(empty)} produced 0 sequences. "
+            f"Check the directory path and that the run completed. "
+            f"Pass --allow-empty to proceed anyway.",
+            file=sys.stderr,
+        )
+        sys.exit(1)
     if not all_binders:
         print("[extract] ERROR: no binders found. Check input directories.", file=sys.stderr)
         sys.exit(1)
```

Requires accumulating `per_tool_counts` in the existing per-tool blocks (each already prints
`→ N sequences`), plus `--allow-empty`.

**F39 · RFD3 FASTA fallback can ingest target+binder concatenations**

CLAUDE.md's own gotcha list says the MPNN output needs "strip the target prefix (first
`len(target_seq)` chars)". `_extract_from_fasta` (`extractors/rfd3.py:182`) is the path that runs
when a manual foundry workflow left no aggregated CSV.

```diff
@@ Evaluator/binder_comparison/extractors/rfd3.py:182  (_extract_from_fasta)
+        # mpnn writes the FULL chain (target prefix + designed binder). Strip the prefix when we
+        # know the target; otherwise refuse rather than refold a chimera as if it were a binder.
+        if target_sequence and seq.startswith(target_sequence):
+            seq = seq[len(target_sequence):]
+        elif target_sequence and len(seq) > len(target_sequence):
+            warnings.warn(f"RFD3 {name}: {len(seq)} aa exceeds target ({len(target_sequence)} aa) "
+                          f"but does not start with it — skipping, pass an aggregated sequences.csv")
+            continue
```

This needs `target_sequence` threaded into the extractor, which it does not currently receive —
the largest change in this batch, and the reason it is listed last. If that plumbing is unwanted,
the minimal alternative is to **fail loudly** when the FASTA fallback triggers and no target is
known, rather than silently emitting oversized "binders".

**F42 · ESMFold2 missing from `ZSCORE_METRICS`** — add the `esmfold2_*` entries alongside the
existing `af3_*` ones in `core/schema.py:308` so the default engine appears in `metrics_zscore.csv`
and `summary.json`.

---

## Batch 6 — installer safety

**F11 · `--yes` inverts the destructive prompts' own `[y/N]` default**

`confirm()` returns true unconditionally under `--yes`, so the documented
`--tool all --yes --skip-examples` deletes `BindCraft/params/*.npz` (~4 GB of AF2 weights) on a
re-run. Separate consent for destruction from consent for convenience:

```diff
@@ install/install.sh:280
 confirm() {
     local prompt="${1:-Are you sure?}"
     if [[ "${AUTO_YES}" == true ]]; then
         echo -e "${YELLOW}${prompt} [y/N]: ${RESET}y (auto-yes)"
         return 0
     fi
     ...
 }
+
+# Destructive prompts (reclone, env re-create). --yes must NOT answer these: the documented
+# non-interactive install is also the documented repair step, and answering yes there deletes
+# cloned repos and multi-GB weight caches. --force opts in explicitly.
+confirm_destructive() {
+    local prompt="${1:-Are you sure?}"
+    if [[ "${FORCE}" == true ]]; then
+        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}y (--force)"
+        return 0
+    fi
+    if [[ "${AUTO_YES}" == true ]]; then
+        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}n (auto-yes keeps existing; use --force to replace)"
+        return 1
+    fi
+    _confirm_interactive "$prompt"
+}
```

This needs the `while true; do read -rp … done` loop currently inline in `confirm()` (`:286–293`)
extracted into a shared `_confirm_interactive()` that both wrappers call — otherwise the loop is
duplicated. `FORCE` is a new variable; nothing in `install.sh` uses that name today.

Then switch the reclone / env-recreate call sites (`:706`, `:722`, and the BoltzGen, Mosaic,
Proteina-Complexa equivalents) from `confirm` to `confirm_destructive`, add `--force` to the arg
parser and `--help`. `--yes` keeps auto-confirming the *safe* prompts ("Proceed with installation?",
"Run the example?"), so CI is unaffected.

**F26 · No preflight before ~60 GB of downloads** — ~20 lines called from `main()` before the menu:
`df` on the install target vs a per-tool size table, `nvidia-smi` presence, one HTTPS reachability
probe. Abort with one clear message rather than an opaque tar/pip error an hour in. Make it
`--skip-preflight`-able.

**F18 · PXDesign install is not resumable** — wrap the `conda create` at `:1236` in the
`env_exists … skipping creation` pattern already used for `binder-eval-esmfold2` (`:2236`). The
later steps are all network-bound, so the operator's natural re-run should resume, not abort.

**F24 · `--uninstall --tool all` leaves multi-GB artefacts** — extend the removal list with the
`binder-eval-af3` env + `alphafold3/` clone, `binder-eval-soluprot`, `~/cutlass`, and the
`~/.bashrc` PATH line; print what was deliberately preserved (`runs/`) versus removed.

---

## Batch 7 — aarch64 parity

Needs a Spark/GH200 to verify, so it should land behind the others.

- **F14** is pure deletion: `install_aarch.sh:1740` pip-installs `esmfold`, which `install.sh:2245`
  explicitly comments does not exist on PyPI. The x86 `install_esmfold2()` is *already*
  architecture-aware (`:2249` selects the cu130 wheel index for aarch64). Delete the aarch64 copy and
  call the x86 function.
- **F12** add the `rfd3|foundry` and `proteina-complexa` cases to the `--tool` parser; give
  Protein-Hunter an explicit "no aarch64 PyRosetta wheels" message instead of "Invalid `--tool` value".
- **F13** add `DO_ESMFOLD2=true` to the aarch64 `all` case.
- **F16** architecture dispatch in `bindmaster.py:105`:

```diff
+    import platform
...
     if cmd == "install":
-        script = REPO / "install" / "install.sh"
+        name = "install_aarch.sh" if platform.machine() == "aarch64" else "install.sh"
+        script = REPO / "install" / name
```

and have `tui/app.py:259, 418` call `bindmaster.py install` rather than hardcoding `install.sh`, so
there is one dispatch point instead of three.

---

## Batch 8 — headless configurator

The single non-agentic blocker: the wizard is the only way to produce a run directory, and answering
its 80 questions is the only way to reproduce a campaign. The `cfg` dict is already the complete
description of a run — it is just never written down.

```diff
@@ configurator/configurator.py:3565  (main)
     parser.add_argument("--archive", metavar="RUN", help="Archive a run folder to tar.gz")
     parser.add_argument("--status", action="store_true", help="Show all runs and their completion state")
+    parser.add_argument(
+        "--config", metavar="JSON",
+        help="Run non-interactively from a saved config (see runs/<name>/config.json). "
+             "Skips all prompts; missing keys fall back to wizard defaults.",
+    )
+    parser.add_argument(
+        "--print-config", action="store_true",
+        help="With --config: validate, print the resolved config, and exit without writing.",
+    )
```

Two halves, each small:

1. **Dump** — in `generate()`, write `cfg` to `runs/<name>/config.json` next to the run scripts.
   Every wizard run then leaves a replayable artefact. ~10 lines, no behaviour change, useful alone.
2. **Load** — `if args.config: cfg = json.load(...)`, validate against the same validators the
   prompts use, then call `generate(cfg, tools_enabled)` directly. The 80 `ask()` calls are skipped
   wholesale rather than defaulted one by one.

This closes CLAUDE.md's deferred **F2** ("`--headless` mode for configurator"), and it is the
prerequisite for any GUI: a form that reads and writes `config.json` needs no wizard reimplementation.
Round-trip test: run the wizard with scripted stdin, dump the config, re-run with `--config`, assert
byte-identical run scripts.

---

## Batch 9 — docs and notices

Follows the decisions below.

- **F41** `Evaluator/README.md:77, 158, 207, 231, 241` and `docs/pipeline_reference.md:26, 41` still
  document the `refold-af2` subcommand and `binder-eval-af2` env removed in Part I, including a
  troubleshooting entry for an env that no installer builds. Generate the subcommand list from
  argparse instead of maintaining it by hand.
- **F17** three skill references prescribe `install/install.sh --pxdesign`, which does not exist →
  `--tool pxdesign`, plus a real `--reapply-patches` path for the documented recovery.
- **F19** "5-step wizard (~1700 lines)" → 7 steps + 6a–6h, 80 prompts, 3593 lines; renumber the
  duplicate `Step 6d` and the missing `6e`.
- **F30** add `THIRD_PARTY_NOTICES.md` for the vendored SoluProt, USEARCH (GPLv3 per CLAUDE.md),
  NGL, `DAlphaBall.gcc` (Rosetta-derived) and `dssp`. The MIT root LICENSE currently covers them all
  by omission, and the repo advertises RFD3's BSD-3 as "commercial-use OK" while shipping a
  Rosetta-derived binary.
- **F31** move `INVESTIGATION_RANKING_DISCREPANCY.md` and `PLAN_chai_and_designers.md` out of the
  repo root (the `docs/` copy of the former is byte-identical); fix `bindmaster.py:52`,
  `CLAUDE.md:424`, `CONTRIBUTING.md:16` clone URLs; move the `--help` side effect
  (`bindmaster.py:142`) after the `--help` branch.

---

## Batch 10 — tests

CI currently runs 5 tests pinning the **retired** `evaluator_legacy/evaluator.py` and 0 against the
seven live extractors, the five refold runners, `merger.py`, `ensemble.py` or `statistics.py`.

- **F29** port `tests/evaluator/test_evaluator_parsers.py` onto the real extractors, one fixture
  directory per tool built from the filenames and columns in
  [the data-flow map](walkthrough_and_dataflow.html). Then delete the legacy test — or keep it and
  un-retire the module, but not both.
- **F37** `compute_ipsae_from_pae` and `compute_iptm_from_pae` produce every ranked number and have
  no tests, while the docstring claims cross-validation against DunbrackLab ipsae v1.0.1. Pin 2–3 PAE
  matrices with expected outputs; if that comparison really was run, commit its fixtures. A transpose
  or `d0` regression here would currently pass CI silently.
- Plus every regression test listed in batches 1–5.

---

## Decisions

Four items are product calls, not defects I can settle from the code.

**1 · F4 — is Protenix opt-in or opt-out?**
`evaluate.sh:135–143` runs it whenever `bindmaster_pxdesign` exists; `CLAUDE.md` says three times it
"runs only when explicitly enabled"; README's engine table matches the *code*. Two operators with
identical designs get different rankings depending on whether they installed PXDesign, because
`protenix_pae_iptm` enters `consensus_iptm`.
→ *Recommend* making it opt-in (`SKIP_PROTENIX=1` default + `--with-protenix`): it matches the
documented intent, and a 4th GPU pass should be a deliberate choice. But if you have been running it
all along, your historical rankings are 4-engine and switching changes them — in which case fix the
docs instead and say so in CHANGELOG.

**2 · F5 — `min_engines` default of 2?**
Correct for the method, but on a single-engine install nothing passes the screen. Alternatives:
default 2 with `--min-engines 1` to opt out (recommended); or default 1 and only surface
`consensus_iptm_n` as a warning column. The first is safe-by-default, the second never changes an
existing report.

**3 · F12/F13 — wire aarch64 up, or correct the support matrix?**
RFD3 should port cleanly (no DGL), but I cannot verify without the hardware. Either add the cases and
test on Spark, or downgrade CLAUDE.md's "fully supported on aarch64" to "untested". Claiming support
that exits 1 is the one option to avoid.

**4 · F20 — inline 1.3 MB of NGL into every report?**
Makes the viewer work offline; adds 1.3 MB per `report.html`. Alternative: `--inline-viewer` flag
defaulting to on when the vendored file exists. Recommend plain inlining — the reports are already
multi-MB from base64 plots, and a silently blank viewer is worse than a larger file.

---

## Suggested sequencing

1. **Batch 1** — smallest, highest consequence, no output churn.
2. **Batch 4** — unbreaks the documented commands; independent of everything else.
3. **Batch 2 + 3 together** — both touch ranking and its description, and Batch 3's F34 covers the
   single-engine case Batch 2 creates. Re-run `report` on an archived campaign and attach the
   `top30_candidates.csv` diff to the PR.
4. **Batch 5**, then **Batch 10** for the areas just touched.
5. **Batch 6**, then **Batch 7** once hardware is available.
6. **Batch 8** — the non-agentic unlock; do it before any GUI work.
7. **Batch 9** last, so the docs describe the settled behaviour.
