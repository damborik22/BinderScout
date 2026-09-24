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

That generates a run folder with a script per tool and runs them in sequence.
To exercise one tool instead of all eight:

```bash
bash runs/CALCA_smoke/run_rfd3.sh
```

### Why this target

`examples/CALCA/target.pdb` is **32 residues** — chain A of a real AlphaFold 3
refold from `tests/integration/golden_pool/`, so it is genuine campaign output
rather than a toy. Size is the point: every design tool's cost scales with
target length, and at 32 residues with `n_designs: 1` each tool finishes a
smoke run in minutes instead of hours.

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
| BindCraft filters | `no_filters` | `default_filters` |

`no_filters` is deliberate: BindCraft's own filters reject most designs, and a
1-design run that legitimately yields nothing looks identical to a broken
install. The smoke test is asking *"does this tool run?"*, not *"is this design
good?"*

**Do not read the output as science.** One design per tool, a 20–30 aa binder
and 20 diffusion steps will not produce a binder worth ordering.

### Cost

A smoke run still needs a GPU and still loads every model. Expect minutes per
tool, dominated by model loading rather than by the design itself, and note that
the refold step has real memory requirements — see the measured table in the
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
