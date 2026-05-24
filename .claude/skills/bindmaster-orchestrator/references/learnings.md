# BindMaster — Empirical Campaign Learnings

Lessons accumulated from real campaigns. The **categories** are portable; the specific **2VDY / CBG numbers** are examples, not predictions for new targets.

Read this at the start of any campaign session. Test category claims early on a new target before committing serious compute to them.

## How to read this file

Each lesson is tagged:

- **[Likely portable]** — architectural facts or infrastructure quirks that generalize cleanly across targets and chemistries.
- **[Probable, test early]** — config heuristics validated on 1-2 targets that should re-validate quickly on a new target before scaling up.
- **[Worker-side]** — operational lessons that primarily affect the worker skill's responsibilities (env setup, log parsing). Cross-referenced here for orchestrator awareness; canonical home is the worker skill.

Specific numbers in examples are **anchors, not estimates**. A "95× yield lift" on 2VDY tells you the direction and rough magnitude of an effect — it doesn't predict the yield lift on ApoE4 or CALCA.

---

## 1. Boltz-2 MSA mode for known targets
**[Likely portable]**

For Boltz-2-based tools (Protein-Hunter, BoltzGen, Mosaic): if the target is in databases, use `mmseqs` MSA mode, not `single`. The de novo binder correctly gets no MSA either way, but the target gets a real MSA that drives iPTM scoring.

**2VDY example:** `single` → 1 design ≥ 0.85 (10.5 h wasted). `mmseqs` → 95 designs ≥ 0.85 (median 0.857). ~95× yield lift from one flag change.

**Mosaic specifically:** set binder `use_msa=False` (de novo binder, no MSA available) but keep target `use_msa=True`. Otherwise Mosaic's continuously-evolving binder triggers a fresh MMseqs request per design step and accumulates past the rate limit.

**Generalization rule:** ColabFold's MMseqs2 server is fine at ~200 designs/batch for known targets. For genuinely novel targets where ColabFold has no homologs either, `single` is correct.

**Applies to tool entries:** `tools/protein-hunter.md`, `tools/boltzgen.md`, `tools/mosaic.md`, `tools/boltz2.md`.

---

## 2. BindCraft hotspots and AF2 hallucination
**[Probable, test early]**

If a target's hotspots span multiple distant regions (different secondary-structure elements, different chain regions), BindCraft's AF2 hallucination may not be able to satisfy all of them simultaneously.

**2VDY example:** Four hotspot clusters — N-term helix (15–22), central sheet (232–242), pocket lid (260–267), C-term helix (366–371). With hotspots ON: BM2 10/10 trajectories failed pre-MPNN; BM4 ran 9 days with 0/203 accepted (every MPNN sequence failed AF2 cross-val on the V2 interface PAE filters). Same V2+V4 preset with hotspots OFF: BM2 22 accepts, Clara L40S 10 accepts.

**Generalization rule:** Hotspots clustered on one face (single binding pocket on one side) → hotspots-ON is fine. Hotspots spanning the protein → run BindCraft no-hotspots and let the trajectory find the binding mode unguided. Cross-engine refold at the end filters on actual interface metrics anyway.

**Applies to tool entries:** `tools/bindcraft.md` (Weaknesses, Pick when, Key knobs `target_hotspot_residues`).

---

## 3. BindCraft V2+V4 vs V1+default
**[Probable, test early]** — pair with §4 hardtarget

For difficult targets (large, no clear deep pocket, many surface residues), V2 relaxed filters + V4 advanced (`default_4stage_multimer_flexible_mpnn40_V4`) consistently produce more accepts than V1 default + plain `default_4stage_multimer`.

**2VDY example:** V1+default = 0/250+ trajectories across two machines. V2+V4 = 32 accepts across three machines.

**But:** the `default_4stage_multimer_hardtarget` variant (V1 filters + hardtarget advanced) produces extremely high-quality but very low-yield accepts. 2VDY_0002 (Feb 2026, ~80–100 trajectories) yielded 1 accept at iPTM 0.90 — higher than any V2+V4 accept. Worth running in parallel for the high-quality tail.

**Generalization rule:** V2+V4 is the workhorse for quantity. `default+hardtarget` is the specialty for top-quality outliers. Run both.

**Applies to tool entries:** `tools/bindcraft.md` (Key knobs — filters preset choice as an orchestration knob).

---

## 4. 24 GB cards have a length ceiling for BindCraft
**[Likely portable]** — physics, not target-specific

3090-class cards OOM in JAX BindCraft's Stage 1 Logits at lengths ≥130 aa with hotspots ON, or ≥145 aa even without hotspots. Cap at 120 on 24 GB. L40S (48 GB) handles 150 fine; H200 (141 GB) / GH200 fine to 200.

PXDesign, Mosaic, Protein-Hunter, Proteina-Complexa OOM on 24 GB at large targets (e.g. 2VDY's 389 aa) regardless of binder length — ship them to ≥48 GB cards.

**Applies to tool entries:** `tools/bindcraft.md`, `tools/pxdesign.md`, `tools/mosaic.md`, `tools/protein-hunter.md`, `tools/proteina-complexa.md`. Orchestrator must not assign length ≥ 130 BindCraft to a 24 GB node.

---

## 5. Scoring engines are not comparable
**[Likely portable]** — architectural fact

PC scores via AF2-multimer (stricter). PH scores via Boltz-2 + target MSA (more permissive). Empirically on 2VDY, PC iPTM 0.70 ≈ PH iPTM 0.85 in difficulty.

Don't filter PC outputs at "PH thresholds" or vice versa. Let the cross-engine refold step do unified scoring through `ipsae_min` (the evaluator's unbiased judge across methods).

**Applies to tool entries:** `tools/README.md` cross-method bias matrix, all design tool entries' "Outputs the evaluator parses" sections.

---

## 6. JAX / PyRosetta env traps on conda
**[Likely portable] [Worker-side]**

Two recurring traps that have cost days across the campaign:

- `set +u` around `conda activate` for envs that use cuda-nvcc activate.d hooks (they reference unset `NVCC_PREPEND_FLAGS`).
- PyRosetta's DAlphaBall.gcc subprocess strips env vars on Slurm — set `LD_LIBRARY_PATH` AND `LD_PRELOAD` inline on the python command with absolute paths to `libgfortran.so.5`.

Both are documented in `bindmaster_examples/run_*.sh.template`. Use the templates; don't hand-write run scripts.

**Canonical home:** the worker skill (`bindmaster-worker`). Listed here so the orchestrator knows to flag the trap in kickoff docs when relevant.

---

## 7. Slurm `.err` lies; the real error is in the tool's inner log
**[Likely portable] [Worker-side]**

Slurm `.err` only shows wrapper-level Python exceptions. Real Python tracebacks live in:

- PC: `$PC/logs/.../generate.log`
- PH: `runs/<n>/protein_hunter/.../*.log`
- BindCraft: `<run>/bindcraft/outputs/*.log` (inner) and `<run>/bindcraft.log` (outer)
- Mosaic: stdout in the sbatch `.out`

**Canonical home:** the worker skill. Listed here because the orchestrator may need to triage worker failures from PROGRESS.md updates without direct log access.

---

## 8. Compute budget tracking
**[Likely portable]** — methodology

Every PROGRESS.md row should record compute hours. By end of 2VDY, knowing "PH cost 22 GPU-h for 95 designs at ≥0.85" vs "PC cost 30 GPU-h for 13 at ≥0.70" was decisive for picking which tool to scale up.

Format: `"Compute: <wall> GPU-time on <node-id>."` Wrap up the campaign with a total budget summary.

**Applies to:** SKILL.md §3.2 (status table row format), §6.1 (math first heuristic).

---

## When to add a new learning

- The lesson would change behavior in a future campaign
- The reason is non-obvious or counter-intuitive
- It's not derivable from the current codebase (this file is for tribal knowledge, not for things grep can find)

When NOT to add:

- Tool-specific gotcha that already lives in `tools/<tool>.md` or `CLAUDE.md`
- Status of the current campaign (that's `PROGRESS.md`)
- Things that will likely be irrelevant after this campaign

When the new learning fits in an existing tool's reference (engine principle, knob, output format), add it to the tool file and cross-reference here. When it's a campaign-level pattern that spans tools or machines, add it as a new section here.

## Categorical patterns to watch for

Categories of lessons that have repeated themselves across the campaign. If a new puzzle fits one of these patterns, the existing learning may apply — check first before doing a new experiment:

- **Scoring engine ≠ scoring engine.** Numbers from different engines are not on the same scale (§5).
- **Same-model self-judging.** A design tool that uses engine X internally cannot be cross-validated by engine X alone. Use the bias matrix in `tools/README.md`.
- **GPU memory ceilings are tool × length, not just tool.** §4.
- **Negative results compound into campaign-level knowledge.** Don't delete 0-accept runs; archive them with explanation.
- **MSA mode is a per-tool axis, not a campaign default.** §1.
- **Filter presets matter more than you'd expect.** V2+V4 vs V1+default is a 0 → 32 effect on 2VDY (§3).
- **Logs lie at the wrapper level.** Real errors are deeper (§7).
