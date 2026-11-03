# Examples

A worked end-to-end run you can execute immediately after installing, and the
smallest campaign that still exercises **every** design tool.

Until now the repository shipped no target at all, so someone who finished a
~85 GB install had nothing to point it at.

---

## The smoke test — every tool, one design each

```bash
binderscout configure --config examples/CALCA/smoke.json
bash runs/CALCA_smoke/run_all.sh
```

That generates a run folder with a script per tool and runs them in sequence. The
config can be replayed from any directory: its relative paths are relative to the
BinderScout checkout, never to your cwd.
To exercise one tool instead of all eight:

```bash
bash runs/CALCA_smoke/run_rfd3.sh
```

### Reusing the config for another campaign

Copy it and change `name`; the run folder follows the name (`runs/<name>`). If
the last component of `run_dir` does not match `name`, the configurator derives
the folder from `name` and prints one line saying so, so two campaigns with
different names never share a folder. To use a different location, change the
parent of `run_dir`; its last component always follows `name`.

### Trimming an expression tag from a public target

The wizard offers to trim a purification tag (His6, an `AAALE` linker, ...) from the
target in Step 3. A `--config` replay never asks, so a deposited structure that still
carries its tag keeps it as designable surface. Add `"trim_construct_tag": true` to the
`cfg` block to answer that offer "yes": the tag is trimmed from `target_sequence` (read
from the structure if the config has none) and then from the coordinates, using the
depositor's own SEQADV / `_struct_ref_seq_dif` records first and a sequence pattern only
as a fallback. `false`, or leaving the key out, keeps the sequence exactly as written. The
generated run folder's `config.json` records the trimmed sequence, so it replays unchanged.

### Why this target

`examples/CALCA/target.pdb` is **32 residues** — chain A of a real AlphaFold 3
refold from `tests/integration/golden_pool/`, so it is genuine campaign output
rather than a toy. Size is the point: every design tool's cost scales with
target length, and at 32 residues with `n_designs: 1` most tools finish a
smoke run in minutes instead of hours. BoltzGen is the exception: it
over-generates and filters down to its budget, so a budget of 1 still runs a
100-design intermediate pool (see [Cost](#cost)).

It is also the target behind the committed golden pool, so a smoke run is
directly comparable with `tests/integration/golden_pool/` — real binders against
this same target, already scored by all three refold engines.

### What "small" means here

| setting | smoke value | a real campaign |
|---|---|---|
| designs per tool | **1** | 50–700 |
| binder length | 20–30 aa | 65–150 aa |
| RFD3 diffusion steps | 20 | 200 |
| Protein-Hunter cycles | 1 | 7–9 |
| BindCraft 2 attempts (`max_trajectories`) | 3 | sized to the target |
| PXDesign samples / Complexa designs | 2 / 2 | 1000 / 100 |
| BindCraft filters | `no_filters` | `default_filters` |

`no_filters` is deliberate: BindCraft's own filters reject most designs, and a
1-design run that legitimately yields nothing looks identical to a broken
install. The smoke test is asking *"does this tool run?"*, not *"is this design
good?"*

**Do not read the output as science.** One design per tool, a 20–30 aa binder
and 20 diffusion steps will not produce a binder worth ordering.

### Cost

A smoke run still needs a GPU and still loads every model. Expect minutes per
tool, dominated by model loading rather than by the design itself. **BoltzGen is
the slow one:** `boltzgen_budget: 1` becomes `--num_designs 100` (the configurator
scales the intermediate pool at 100 per requested design, with a floor of 50), and
at the measured 5.35 s per intermediate design on a 24 GB card that is about 9
minutes for the design step alone, before inverse folding, Boltz-2 folding and
analysis. Note also that the refold step has real memory requirements — see the measured table in the
main README. On a 12 GB card ESMFold2 cannot run at any size, so use
`--skip-esmfold2` there.

---

## The evaluator, with no GPU at all

To see a report without running a campaign:

```bash
pytest tests/integration/
```

That builds a deterministic three-engine pool, runs a real `binder-compare
report` against it, and pins the ranking against the committed golden pool. Ten
seconds, no GPU, no network. `CONTRIBUTING.md` shows how to keep the HTML.

---

## Checking an install instead

If the question is "is my install healthy", the smoke test is the slow way round:

```bash
binderscout install --tool all --verify
```

That checks the artifact each tool needs to **run** — a checkpoint on disk, an
importable package — rather than that its entry point answers, and names the fix
for anything unusable. `--repair` then re-installs only what failed.
