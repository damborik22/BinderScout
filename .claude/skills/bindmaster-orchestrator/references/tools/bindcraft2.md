# BindCraft 2

**Engine:** AlphaFold 2 sequence optimization → ProteinMPNN redesign → validation against held-out AlphaFold models plus structural filters. A **rewrite** of BindCraft, not a new version of it: JAX only, no PyRosetta, no conda, Python ≥3.12.
**Role:** design
**Status:** in `--tool all` on x86 when a source is supplied; **opt-in on aarch64** — validated on GB10/sm_121, kept out of `--tool all` for throughput. Added in BinderScout 1.1.0.
**Environment:** its own uv venv at `BindCraft2/.venv`, installed **editable** — the checkout *is* the installation. Not a `bindmaster_*` conda env, and it shares nothing with the `BindCraft` conda env.

## Principle

BindCraft 2 keeps the shape of BindCraft 1's method — hallucinate a binder through AF2, redesign the sequence with ProteinMPNN, validate what comes back — and replaces nearly everything around it. PyRosetta is gone, so the physics battery that BindCraft 1 filters on is gone with it; validation is instead done by AlphaFold models held out from the design step, plus structural filters. Conda is gone too: it installs from pip wheels into a venv we create for it, which makes it far lighter to stand up on a new machine — though not a platform unlock, since BindCraft 1 runs on aarch64 as well.

The other half of the rewrite is the interface. One layered campaign file replaces BindCraft 1's three JSONs: `core → modality → property → target → your campaign → --set`, each layer overriding the one above. That makes a campaign a single archivable artifact, and it makes the *modality* a first-class choice rather than a weight-tuning exercise — including scaffolded formats (VHH, ARP, scFv, Fab) and objectives (cyclic peptide, homo-oligomer, multidomain, induced-fit, fold-switch) that BindCraft 1 has no equivalent for. Outputs are mmCIF, not PDB, and land in a three-stage tree rather than one flat CSV.

**It ranks on `i_pDAE` — its own metric, a plain descending sort, and higher is better** despite the name reading like an error term. It is not i_pTM and it is not a composite. Two consequences for the orchestrator: never re-derive a BindCraft 2 rank from i_pTM (it reproduces nothing), and never assume the ranked table is strictly decreasing — the values are rounded, so tie blocks are large and rank *inside* a tie block is acceptance order, not quality order.

**BindCraft 2 does not replace BindCraft 1.** They coexist as separate tools with separate environments, separate run scripts and separate extractors, so every archived BindCraft 1 campaign stays reproducible and the two can be run head-to-head against one target inside a single report. Nothing about evaluation changes: BindCraft 2 optimizes AF2 confidence during hallucination and validates with AF2-family models, so **its confidence is design-time-biased exactly as BindCraft 1's is** — its metrics are a native block only, they never enter `consensus_iptm_mean`, and its designs pass the same ≥3-engine gate as everything else.

## Strengths

- **Modalities nothing else in the stack offers.** Scaffolded VHH / ARP / scFv / Fab, cyclic peptides, homo-oligomers, multidomain binders, induced-fit and fold-switch objectives — named, not hand-tuned. The wizard exposes the de novo formats — `binder`, `large_binder`, `peptide`; the other nine reach through `bindmaster configure --config`. **The scaffolded formats are held back on purpose.** `VHH`, `scFv` and `Fab` belong to the separate nano effort, where antibody-format design and its scoring are handled together. For VHH there is also a measured reason: our ranking cannot score nanobodies (a validated 6.8 nM VHH scores 0.21 through it, with no binder/non-binder separation), so a wizard-driven VHH campaign would produce a pool the report cannot rank — evidence specific to nanobodies, not assumed to carry to scFv or Fab.
- **A much lighter dependency stack.** No PyRosetta and no conda `jaxlib` — pip wheels into a venv. That is a maintenance and portability win rather than a platform one: BindCraft 1 runs on aarch64 too (measured on BM5, jaxlib 0.4.34 on the GPU, pyrosetta importing), so on Spark you have both, and they are complementary rather than substitutes.
- **One campaign file.** The whole run is a single JSON beside the run script; edit and rerun without regenerating anything.
- **A reproducible profile.** `core: benchmark` fixes the seed and disables autotuning and the desperation ladder — mandatory for any A/B against BindCraft 1 or against another preset, because the ladder silently loosens validation after a long fruitless stretch and stamps the designs it produced that way.
- **A second AF2 arm that is not a duplicate.** Running both BindCrafts on one target is a genuine method comparison (different filters, different ranking metric, different validation models) that costs nothing extra in the report.

## Weaknesses

- **No Rosetta interface battery.** Dropping PyRosetta drops ΔG, shape complementarity, packstat, ΔSASA and the H-bond accounting. BindCraft 1 remains the only native source of those, and `binder-compare affinity` / `qc-annotate` still shell into the `BindCraft` conda env for Rosetta — **do not repoint or upgrade that env on BindCraft 2's account**, it would silently break Part N.
- **No wall clock, anywhere in the package.** `number_of_final_designs` is a quota of *accepted* designs, not an attempt count, and `max_trajectories` is the only cap. Left unset, a campaign runs until the quota is filled, however long that takes. Every other tool in BindMaster is bounded by attempts — this one is the exception, and the wizard prompts for a budget every time for that reason.
- **Half throughput on aarch64 — because of our guard, not the card.** Measured head-to-head on the same 60 aa binder against a 115-residue target: **343 s per trajectory on a GB10, 328 s on a 24 GB RTX 3090** — equal. But the guard that avoids the `[N/A]` crash disables worker fan-out, so the GB10 runs one design worker while the 3090 packs two at 9.6 GB each, and finishes the same two trajectories in half the wall clock. Prefer x86 for production campaigns today. Either way the method is expensive: at ~5.5 min a trajectory, a hard target needing many attempts per accepted design is days of card time.
- **Length ceiling is a crash, not a refusal.** Roughly one worker per 24 GB card at ~256 residues. Past ~512 residues it does not refuse — it floors the plan at one worker, runs single-process, and OOMs at prediction time. Nothing upstream catches this.
- **Two output schemas exist in the wild.** v1.0.0 writes `3_Ranked/!_Ranked.csv` with lowercase `rank`/`design`/`Binder_Sequence`; the pre-1.0 build that produced our archived CBG and CALCA pools wrote a flat `<target>_ranked.csv` with TitleCase columns, and renamed/rescaled several metric columns besides. The extractor reads both; anything hand-written must not assume one.
- **The ranked table is rewritten as the campaign runs, and it can shrink** — it is rebuilt on every acceptance and reconciled at close against what is actually on disk. A `--tool-csv` snapshot taken mid-run can be superseded by a *smaller* one, which is the known stale-`tool_csvs` failure mode. Snapshot after the campaign closes.
- **Source is not public.** Pre-publication and source-available under its own licence, supplied per machine — there is no download to point a new node at, and `BindCraft2/` is gitignored and never committed.
- **Column set is campaign-dependent.** A metric column exists only if the campaign set a threshold for it, so two pools from the same tool legitimately differ in width. Every native read is optional.

## Pick when

- **You need a modality BindCraft 1 has no equivalent for** — a scaffolded antibody format (VHH / ARP / scFv / Fab), a cyclic peptide, a homo-oligomer, a multidomain binder, or an induced-fit / fold-switch objective. This is the main reason to reach for it over BindCraft 1.
- **A second AF2 arm on one target.** Running both BindCrafts is a genuine method comparison — different filters, different ranking metric, different validation models — not a duplicate. Both run on every platform we have, aarch64 included.
- **You want an AF2-hallucination arm that is not BindCraft 1** — same family, different filters and different ranking metric, so a head-to-head on one target is informative rather than redundant.
- The target is protein with a clear epitope; hotspots map 1:1 onto our existing prompts (`A54,A56,B12-16` syntax).

## Avoid when

- **You need the Rosetta interface metrics** (ΔG, shape complementarity, packstat, unsat-H-bond counts) → **BindCraft 1**, which is the only tool that produces them natively.
- **Throughput is the constraint on Spark** → run it on **BM1/BM2/BM4** instead, or use a tool that is not AF2-hallucination-bound. aarch64 is opt-in for throughput, not because anything fails there.
- **The complex is over ~512 residues on a 24 GB card** → it will not refuse, it will OOM at prediction time. Size the binder down or move to a bigger card.
- **You want backbone diversity** → hallucination converges, same as BindCraft 1; use **RFD3** or **BoltzGen**.
- **You are looking for a design tool whose native confidence is independent of AF2** → it is not, and neither is BindCraft 1. Independence comes from the refold engines, not from the designer.

## Outputs the evaluator parses

**Source of truth:** `3_Ranked/!_Ranked.csv` (v1.0.0) or a flat `<target>_ranked.csv` (pre-1.0, which is what our archived CBG/CALCA pools are). Accepted structures are **mmCIF**, not PDB.

```bash
binder-compare extract --bindcraft2 runs/<name>/bindcraft2 -o seqs.fasta
```

- **Never** extract from `1_Trajectories/!_Trajectories.csv` — its sequence column is the *pre-ProteinMPNN* hallucinated sequence, which is not a design. **Never** take `outcome='rejected'` rows from `2_Refolded/!_Refolded.csv`. **Never** resolve to `accepted.csv` (append-only, no rank column at all), `ranked_by_*.csv` (a user re-sort on some other metric) or `filtered.csv` (a post-hoc subset) — each would yield a plausible, wrongly-ordered pool.
- **Native rank comes from the tool's own file and is never recomputed** — the extractor sorts on the rank column and checks it really is 1..N. Ties are pervasive, so do not assert that `i_pDAE` decreases monotonically.
- **Native metrics land under a `bindcraft2_*` prefix**, deliberately distinct from BindCraft 1's `bindcraft_*`: `bindcraft2_ipdae` (the rank key), `bindcraft2_iptm`, `bindcraft2_ptm`, `bindcraft2_plddt`, `bindcraft2_ipae`, `bindcraft2_target_plddt`, `bindcraft2_ss_plddt`, `bindcraft2_interface_residues`, `bindcraft2_interface_buried_area`, `bindcraft2_interface_hydrophobicity`, `bindcraft2_surface_hydrophobicity`, `bindcraft2_backbone_clashes`, `bindcraft2_binder_rmsd`, `bindcraft2_target_rmsd`. The two tools' blocks must never be collapsed — they are different methods with different filters.
- `binder_id` is `bindcraft2_<design>`.
- **Scale traps:** `pLDDT` and `i_pTM` are **already 0–1** (no rescale, unlike AF3); `Binder_pLDDT` is 0–100; `i_pAE` is a normalized PAE, not Ångströms; mmCIF B-factors are 0–100.
- **Refused rather than mis-parsed:** a multi-target export (every metric cell becomes a `;`-joined vector) and a multi-chain binder (`/` in the sequence — a single-chain refold of a concatenated binder is a different molecule). Both fail loudly.
- **Structure join caveat on the two archived pools.** v1.0.0 writes `3_Ranked/<design>_seq<n>.cif`, but the delivered archives are `<Rank>_<Design>.cif` under inconsistent folder names, so `binder_id` does not join to them without a rank-prefix-aware resolver. Structure-consuming steps find nothing on those two pools — known, not fixed.

After the cross-engine refold, BindCraft 2's native block sits alongside `consensus_iptm_mean` and `ipsae_min` in the report, exactly as every other tool's does. It is never the ranking.

## Key knobs

| Knob | Where | Typical | Notes |
|---|---|---|---|
| `modality` | campaign JSON | `binder` | **Always write it explicitly.** With none named, no modality layer is applied at all and the resulting empty length range surfaces as a bare traceback, not a clean refusal. |
| `binder_lengths` | campaign JSON | per target | Written for `binder` / `large_binder` / `peptide`; **omitted for every scaffolded format** (VHH / ARP / scFv / Fab), where the scaffold sets the length. |
| `number_of_final_designs` | campaign JSON | 10–20 | A **quota of accepted designs**, not an attempt count. |
| `max_trajectories` | campaign JSON | quota × 50 | The **only** cap in the package. Unset = unbounded; selectable, but it must be a deliberate answer. |
| `targets[].hotspots` | campaign JSON | `A54,A56,B12-16` | Same syntax as our other tools. |
| `core` | campaign JSON | `benchmark` | Fixes the seed, disables autotuning and the desperation ladder. Required for A/B. |
| `project_folder` | campaign JSON | absolute path | **Never re-based** against the JSON's directory — a relative value nests the results inside themselves. Each parameter set gets its own versioned folder (`bindcraft2/`, `bindcraft2_v2/`), since resume is on by default. |
| `auto_multi_gpu` + `subbatch_size` | `--set`, at launch | `false` + `null` on aarch64 only | GB10 answers the card-memory query with `[N/A]`, which the memory probe cannot parse. **Both** are needed — one setting covers only one of the two call sites. Injected by the run script from `uname -m` on the *executing* host, never baked into the campaign JSON (configs are written on BM5 and run on x86). |
| `BINDCRAFT_AF2_PARAMS` | env | an existing AF2 cache | Reuse the params already on the machine instead of fetching ~5 GB again. Never export it *empty* — an empty value counts as a value and fails rather than falling back. |
| `JAX_COMPILATION_CACHE_DIR` | env | `~/.cache/bindmaster/bc2_xla/<card>` | Left unset, the compile cache is **per campaign**, so every new run re-pays compilation from cold. Set by us, and the card segment is ours to add — an operator-set value is used verbatim with no per-card subdirectory, and a compiled executable is not portable between GPU models. |
| `XLA_*` | env | leave alone | BindCraft 2 sets its own preallocation and XLA flags. |

Install and run:

```bash
bindmaster install --tool bindcraft2 --bc2-source <zip|dir>   # or export BINDCRAFT2_SOURCE
bindmaster configure                                          # Step 6h writes campaign.json + run_bindcraft2.sh
bash runs/<name>/run_bindcraft2.sh
```

Under `--tool all` on x86, a missing source **warns and skips**; an explicit `--tool bindcraft2` with no source **fails** with an instruction. On aarch64 it is never in `--tool all`.

## Sources

- **Upstream repository: not public.** BindCraft 2 is pre-publication and source-available under its own (non-MIT) licence; the source is supplied per machine via `--bc2-source` / `$BINDCRAFT2_SOURCE`, and `BindCraft2/` is gitignored. No URL is recorded here or anywhere in this repository.
- Lineage: the same lab's rewrite of BindCraft (Pacesa et al. 2024, bioRxiv 2024.09.30.615802), which remains a separate tool — see `bindcraft.md`.
- BindMaster integration plan, with the measurements quoted above: `docs/PLAN_bindcraft2_integration.md`
- Extractor (and the dual-schema reasoning): `Evaluator/binder_comparison/extractors/bindcraft2.py`
- Run-script template: `bindmaster_examples/run_bindcraft2.sh.template`
- Not to be confused with **BindMaster 2** (`docs/bindmaster2_grafts.md`), which is a different thing entirely.
