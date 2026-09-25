# Decisions waiting on you

Written 2026-09-25 overnight. Everything below is blocked on a judgement call,
not on implementation. Each has my recommendation, but they are yours.

The work that needed no decision is done and pushed — see
[REPO_DIARY.md](REPO_DIARY.md)'s Part 2.0 chapter for the night's entries.

---

## 1. Does the discovery-rank metric accept a pre-filtered pool? **(the big one)**

**Blocks:** finishing Stage 1 (item AD). Everything else in it is built.

Most extractor inputs are *already downstream of a quality filter*, so a
"discovery rank" computed over them is conditioned on survival — the denominator
has been deleted:

| tool | what the extractor sees |
|---|---|
| Protein-Hunter | iPTM > 0.8 **and** pLDDT > 0.8 **and** Ala ≤ 20% |
| Mosaic | `is_top=1` — the top ~5% by quality rank |
| BoltzGen | budget + diversity selection, ~700 rows of ~10,000 |
| Proteina-Complexa | `top_samples`, then only survivors reach `evaluation_results/` |
| BindCraft | accepted designs only |

"How early did a good design appear", measured over a pool pre-filtered for being
good, is a biased estimator. Three options:

- **(a) Refuse.** Emit no discovery rank for a pre-filtered pool. Honest,
  and makes the metric near-useless for five of eight tools.
- **(b) Carry the caveat.** Emit it with `pool_pre_filtered=True` alongside, which
  `tool_classification.py` already tracks. Useful, and relies on every reader
  noticing a flag.
- **(c) Require the complete pool.** Mosaic and Protein-Hunter both *have* one
  (`--all-mosaic-designs`, `--all-protein-hunter-designs`); BoltzGen's
  `aggregate_metrics_*.csv` is near-complete and unread. Most correct, most work.

**My recommendation: (b) now, (c) where it is cheap.** The flag exists, and for
Mosaic and Protein-Hunter (c) is one CLI flag each. BoltzGen and PC can stay at
(b) until someone wants the number badly enough.

---

## 2. Is Proteina-Complexa's aarch64 deprecation worth re-testing?

**Blocks:** nothing. Reopening a closed decision.

Last night's finding: PC's AF2 reward **is ColabDesign**, the same library
BindCraft runs on the GPU on Spark. PC is simply pinned to `jax 0.4.29`, which
predates sm_121 — the identical mechanism that made BindCraft CPU-bound, with
the identical fix. CLAUDE.md's stated reason for the deprecation ("a different
problem") does not hold, and its "1.7 years" figure rests on it.

What is **not** established: whether upgrading actually works. PC uses uv with a
different ColabDesign version and its own resolver constraints, and testing it
needs Spark.

**My recommendation: worth one afternoon on Spark, not more.** The upside is a
deprecated tool coming back on a whole platform; the downside is a bounded
experiment. If the resolver fights, stop.

---

## 3. Which pools go into the label registry first?

**Blocks:** promoting any shadow-mode column out of shadow mode.

Part Y shipped last night, so a labelled pool can now be named and audited
without its labels entering the repo. Nothing is registered yet, and I did not
guess — the manifest records provenance, and a wrong one is worse than none.

Candidates mentioned across the plans: Cao 2022 (4,442 designs, 12 targets),
Adaptyv rounds, the CBG wet-lab results, ApoE4. I need to know **which of these
you actually have label rows for, and where**, before writing manifests.

Relevant caveat already recorded in `SCHEMA.json`: 73.4% of Cao's binder labels
are one-sided-Kd and experimentally indistinguishable from non-binders on Cao's
own binary assay. Macro-AUC rises 0.56 → 0.73 once they are excluded, so which
subset gets registered changes every number computed from it.

---

## 4. P5: which model, ESM-2 or ESM Cambrian?

**Blocks:** starting P5.

The source plan says "ESM Cambrian"; `NEXT_STAGES.md` says "ESM-2 650M fits this
box". They are different models. I did not start it because the choice changes
the runner, the env and the download, and because it is a new screen — worth
five minutes of your input rather than an overnight guess.

Neither is installed. `binder-eval` has no torch; `binder-eval-esmfold2` does.

**My recommendation: ESM-2 650M**, unless you specifically want Cambrian.
Pseudo-perplexity from ESM-2 is the well-trodden plausibility signal, it fits
this box, and it can move later.

---

## 5. The aarch64 `dssp` binary has a build path baked in

**Blocks:** nothing. Cosmetic-but-public.

`tools/aarch64/dssp` carries a `/home/<account>` naming one of our own boxes,
baked in by whatever compiled it. Removing it needs an aarch64 rebuild. It is now
recorded in CLAUDE.md and pinned by a test, so it cannot spread and cannot be
quietly forgotten.

**My recommendation: rebuild it next time someone is on Spark anyway.** Not worth
a special trip.

---

## Blocked on DATA, not on you

Noting these so they are not mistaken for decisions.

- **Stage 4 (Z, staged cheap-filter) cannot be validated on this box.** Its gate
  needs two archived pools carrying all three engine CSVs, to measure recall at
  the chosen keep-fraction. This machine has none — only the 6-design golden
  fixture, which is far too small. The code could be written blind; the number
  that says whether it is safe could not be computed.
- **Stage 1's remaining gate needs a real campaign.** Its stated criterion is
  "holdout passes a KS test vs the pool", which needs a pool with a real
  generation order. Same missing ingredient.

---

## Also worth knowing

- **CLAUDE.md said "Scrubbed from tree and history 2026-09-22" and that was
  false** — six tracked files still carried a username three days later. Fixed,
  and now enforced tree-wide by a test. The history is still published; a tree
  scrub unpublishes nothing.
- **I shipped a crash on 09-24 and fixed it on 09-25.** Wiring
  `--collect-structures` into the pipeline turned an unguarded `import gemmi`
  into a `ModuleNotFoundError` that killed every run *after* extracting the
  sequences. The class is now guarded by a static test, mutation-verified.
- **Three shadow-mode columns now ship and none can be promoted without §3.**
