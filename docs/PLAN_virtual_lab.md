# PLAN — Virtual Agentic Lab: Scientific Critic & Deliberation (Parts Y · Z)

> **Status:** Evaluated, not started. **Investigate-first**, same discipline as
> `PLAN_ranking_and_engines_roadmap.md` — read current `master`, confirm findings against
> the codebase, propose a concrete implementation with its validation gate, and **wait for
> approval before writing code.**
>
> **Anchoring facts verified 2026-07-26 (`master` @ `a600090`):**
> - `.claude/skills/` ships **five** role-specialized agents — `bindmaster-target-analyst`,
>   `-orchestrator`, `-worker`, `-evaluator`, `-wetlab` — with explicit handoffs and
>   `PROGRESS.md` as shared state. → **BinderScout is already a virtual agentic lab.**
> - `grep -rniE 'critic|adversar|red.?team'` over `.claude/skills/` returns **no critic
>   role**. Adversarial review lives only as prose heuristics inside the orchestrator
>   (§6.1 "math first", §6.7 "propose, don't decide silently"). → **Part Y premise is real.**
> - `docs/LAB_DIARY.md` records **≥ 8 distinct methodology/claim errors** caught late or by
>   the human (see the evidence table below), including six in a single 2026-07-01 report
>   review. → **the critic has a measured base rate to beat, not a hypothetical one.**
> - Related roadmap: `PLAN_ranking_and_engines_roadmap.md` **Part X** (report gap audit) is
>   a one-shot manual instance of what Part Y automates. → **sequence X before Y.**

---

## Why this plan exists

The reference is **The Virtual Lab** (Swanson, Pak, Zou et al.; *Nature* 2025; bioRxiv
2024.11.11.623004): an LLM **principal-investigator agent** directs a team of
expertise-specialized **scientist agents** plus a dedicated **Scientific Critic agent**,
steered by a human through written agendas. Applied to SARS-CoV-2 it composed an
ESM + AlphaFold-Multimer + Rosetta pipeline and produced 92 experimentally-validated
nanobodies (scaffold-mutation, not de novo), two with improved binding to JN.1 / KP.3.

Mapping it onto this repo, **BinderScout already implements almost all of it** — and the
parts it implements, it implements *better*, because they are grounded in campaign
evidence rather than in agent deliberation:

| Virtual Lab | BinderScout equivalent |
|---|---|
| PI agent | main session running `bindmaster-orchestrator` |
| Scientist agents (by expertise) | `target-analyst` / `worker` / `evaluator` / `wetlab` |
| Team / individual meetings | `CLUSTER/<tool>_<machine>_SETTINGS.md` kickoff contracts |
| Agenda + agenda rules | kickoff "Why this run" + settings table + kill criterion |
| Tool selection | `analyze-target` dossier → orchestrator tool/settings choice |
| Parallel meetings → merge | cross-engine consensus; MSA/no-MSA complementary gates; §5.3 architectural diversity |
| Human steering | the user, at campaign level |
| **Scientific Critic** | **— absent —** |

**The whole opportunity is that one empty cell.** Everything else is either already built
or actively counter-indicated (below).

---

## The evidence: what a critic would have been for

Drawn from `docs/LAB_DIARY.md`. "Catchability" is an honest estimate of whether an LLM
critic *with repo access* would plausibly have flagged it.

| Date | Miss | Caught by | Catchability |
|---|---|---|---|
| 2026-07-01 | Report methodology claimed *"Adaptyv: 8 hand-curated targets, n > 3,700"* — **contradicted by this repo's own diary**; real = Adaptyv 4-target/662 + ProteinBase 4-target/175 | user review | **High** |
| 2026-07-01 | `agreement_count` legend read "0–2" against 3 engines; two tier systems under one count table; wet-lab strike-through read as definitive; 3 tools missing native ranks; `str(length).rstrip(".0")` → 140 renders "14" | user review (6 findings, one pass) | **High** |
| 2026-07-16→23 | BoltzGen's 29 Boltz-2-"selective" designs were **gamed** — 0/29 survived the AF3 confirm | AF3 counter-screen | **High** |
| 2026-06-18 | "screen-then-invert" looked usable pooled; actually a **Simpson's-paradox artifact** (replicates on EGFR only — IL7R flat, Nipah reversed) | per-target replication | **Med-High** |
| 2026-07-16→23 | *"are we using MSA for all targets?"* → re-gate produced **+10 all-new selectives, zero overlap** with the no-MSA funnel | **the human, acting as critic** | **High** |
| 2026-07-07→15 | **RFD3 alanine collapse** (~50 % Ala vs 0.21 in cross-validating winners) — "likely under-used RFD3 across the whole program" | late, manual | **Medium** (needs a computed composition check) |
| 2026-06-28 | SoluProt screen **"wired but never fires"** — env-name mismatch silently skipped it | investigation | **Low-Med** |
| 2026-07-07→15 | Probe Boltz-2 ran without `--output-dir` → index-based `--resume` silently emitted a prior pool's 1520-row CSV | debugging | **Low** (fix in code, not review) |
| 2026-07-26 | `CLAUDE.md` called Part N "planned" after it had landed **with a negative result**; `docs/plans.md` still carried the superseded plan | this audit | **High** |

**Read of the table.** Value concentrates in the **High** rows — claims, provenance,
legends, gaming, doc-vs-record consistency. Those are reasoning-over-text tasks with an
authoritative ground truth already in-repo (`LAB_DIARY.md`, `CHANGELOG.md`). The **Low**
rows are ops footguns better fixed in code (already TODO'd in the diary) and should *not*
be used to justify this part.

**The honest framing:** the user is already serving as the Scientific Critic, and it is
working. Part Y **systematizes and offloads an existing, effective role** — it does not
add a missing capability. That is the bar it must clear.

---

## Benefit / cost summary

| # | Task | Benefit | Cost | Campaign relevance | Do when |
|---|---|---|---|---|---|
| **Y** | `bindmaster-critic` skill — claims & report auditor | Catches the error class that reached published reports 6× in one review | ~1–2 days (docs only, no code) | Direct — wet-lab picks are made from these reports | **After Part X** |
| **Z** | Multi-agent deliberation at the planning gate | Possible better campaign plans on genuinely open questions | ~days + token cost | Speculative — no current blocker | **On demand only** |

---

## Part Y — `bindmaster-critic` skill *(the recommended work)*

**Goal.** A **separately-invoked** adversarial reviewer whose only job is to find flaws in
artifacts the other five skills produce. Scoped tightly to where the evidence says it pays.

**Non-negotiable design constraint.** The critic must run as its **own agent invocation
with its own context** — never as a section inside `bindmaster-orchestrator` or
`bindmaster-evaluator`. Self-critique by the agent that produced the artifact is precisely
the failure mode being fixed, and is why the Virtual Lab makes the Critic a separate role.

### Y.1 Primary gate — report / shortlist audit *(highest value)*

Fires before a report is trusted or wet-lab picks are committed:

- Every quantitative claim traced to a source in `LAB_DIARY.md` / `CHANGELOG.md` / a
  results CSV. **Unsourced or contradicted numbers are the top finding class** (2026-07-01).
- Benchmark provenance stated exactly: Adaptyv 4-target/662-design (macro AUC mean 0.710 /
  max 0.689) and ProteinBase 4-target/175-design (max ~0.755). Never "planned scope".
- Legends vs. reality: engine count, tier systems, which axis a flag encodes.
- **Same-engine gaming flagged per tool** — Mosaic / BoltzGen / Protein-Hunter vs Boltz-2;
  PXDesign vs Protenix; BindCraft vs AF2. A design that only its own engine likes is a
  finding, not a candidate.
- **Statistical hygiene:** any pooled claim must survive per-target replication
  (Simpson's-paradox check); any affinity/quality claim must address the binder-length
  confound (r ≈ −0.78 vs `ipsae_min`).

### Y.2 Secondary gate — campaign-plan review

Before compute commits: yield × time × compute math; a pre-committed kill criterion;
"is the thing we think is enabled actually enabled" (the SoluProt class); MSA / settings
caveats (the +10-selectives class); duplicate-run check.

### Y.3 Tertiary gate — dossier review

Hotspot claims literature-backed vs geometry-only; difficulty band not optimistic.

### Investigate-first checklist (no code)

- [ ] Y1. Consume **Part X**'s findings — the module → CSV → HTML gap table *is* the
      audit checklist. Do not invent a parallel one.
- [ ] Y2. Inventory the authoritative ground-truth sources a critic may cite
      (`LAB_DIARY.md`, `CHANGELOG.md`, per-engine refold CSVs, benchmark reports on MUNI)
      and write the precedence rule when they disagree.
- [ ] Y3. Draft `SKILL.md` + `references/` (claim-audit checklist, gaming matrix,
      statistical-hygiene checks). Mirror the existing five skills' structure.
- [ ] Y4. Define the invocation contract: which artifacts trigger it, what it emits
      (findings list with severity + evidence pointer), and that it **never edits** the
      artifact it reviews.

**Validation gate (hard).** Back-test the critic on the **2026-07-01 regenerated reports**,
blind to the diary entry: it must **independently rediscover the six known findings** —
above all the overstated benchmark provenance. Report precision/recall against that
labelled set. **If it cannot rediscover ≥ 4 of 6, document the negative result and stop.**
This is the same "reproduce a known result before trusting it" bar the T–X roadmap applies
to Promera, Chai-1 and RFD2-MI.

---

## Part Z — Multi-agent deliberation at the planning gate *(deferred)*

**Goal.** For genuinely open questions (which epitope; how to read ambiguous cross-engine
disagreement; the next selectivity objective), spawn expertise-diverse subagents that argue
the plan, with the orchestrator synthesizing — optionally run N× in parallel and merged,
the Virtual Lab's ensembling technique.

**Why it is deferred, not rejected.** There is precedent that this competency has a home
here: the **multi-state Mosaic negative-design run** (2026-07-16→23) composed a novel
objective from tool primitives — `loss = NoCys(E4) − w·NoCys(E3) − w·NoCys(E2)`, with the
flat-`LinearCombination` wrapping gotcha solved — to design *for* selectivity instead of
counter-screening for it. That is exactly Virtual-Lab-style invention, and it was produced
by reasoning, not by a framework. So the capability is already reachable without new
machinery, and no current campaign is blocked on it.

- [ ] Z1. Only if a campaign presents a design question the existing skills demonstrably
      cannot resolve. Name the question first; build second.

**Validation gate:** a deliberation output must be judged against what the orchestrator
alone proposed for the same question. No measured improvement → drop it.

---

## What we deliberately do NOT adopt

1. **Do not resolve ranking/affinity questions by agent deliberation.** This is the
   sharpest lesson on `master`. Affinity ranking was settled by exhaustive empirical search
   — 3 engines × confidence metrics, Rosetta ΔG, `|dG/dSASA|`, the BindCraft 14-metric
   panel, PRODIGY — then corroborated externally on **OpenBind** (molecular weight is the
   best predictor, ρ 0.48) and **SKEMPI** (PRODIGY 0.20, Rosetta ΔG 0.12). The answer was
   **negative**. Deliberation would have confidently produced a plausible composite; only
   benchmarks killed it. Parts T/U are the right instrument.
2. **Do not adopt `zou-group/virtual-lab` as infrastructure.** GPT-based; it reimplements
   multi-agent orchestration that Claude Code provides natively via skills + subagents.
   Borrow the *ideas* (separate critic, written agendas, parallel-merge), not the codebase.
3. **Do not re-derive the pipeline.** The screen half is solved and independently
   replicated (ESMFold2 ipTM AUC **0.91** on BindCraft *Nature* 2025 designs; 0.69 Adaptyv).
4. **Do not let consensus manufacture confidence.** Multi-agent agreement is not evidence.
   It is the same overconfidence the cross-engine ranking exists to defeat.
5. **Keep deliberation advisory.** Committed artifacts stay deterministic — kickoff docs,
   `settings.json`, per-engine CSVs. Free-form agent output is a recommendation a human
   approves, never a substitute for the reproducibility convention.

---

## Sequencing against the T–X roadmap

Part X is a **one-shot manual instance of Part Y**. Run it as specified; Y is then built
from its findings rather than from an invented checklist.

```
X (report gap audit)  →  Y.1 critic, back-tested on the 2026-07-01 six findings
                      →  Y.2 plan gate
                      →  [stop unless a campaign forces Z]
```

Y does not compete with T / U / O for the ranking question — it audits *how results are
claimed*, while T/U decide *which metric ranks*. They are orthogonal and can run in
parallel once X is done.

---

## Process discipline (inherited)

1. **Read current `master` first** — older PLAN docs go stale (this audit found two).
2. **Investigate → findings → plan + validation gate → wait for approval.**
3. **Negative results are deliverables.** If the critic can't rediscover the 2026-07-01
   findings, that verdict — documented — is the win.
4. **Surgical changes.** A new skill mirrors the five existing ones; do not refactor the
   skill layer to add one.

---

## References

- Swanson K., Pak J., Zou J. et al. *The Virtual Lab of AI agents designs new SARS-CoV-2
  nanobodies.* Nature (2025). Preprint: bioRxiv `10.1101/2024.11.11.623004`.
  Code: `github.com/zou-group/virtual-lab` (reference only — not a dependency).
- `PLAN_ranking_and_engines_roadmap.md` — Parts X/T/U/O/V/W; Part X precedes Part Y.
- `docs/LAB_DIARY.md` — the evidence table above; entries 2026-06-18, 06-22, 06-23,
  06-28, 07-01, 07-07→15, 07-16→23.
- `docs/completed_plans.md` — Part N (interface ΔG, landed negative).
- `.claude/skills/` — the five existing lab roles Part Y would join.
