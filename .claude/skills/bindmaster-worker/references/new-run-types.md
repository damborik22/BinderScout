# New run types (extension to the worker skill)

> **Scaffold.** `TODO:` add per-tool command recipes, source-of-truth files, gotchas.

Execution playbooks for the BindMaster2-graft capabilities the worker now runs:

- **Maturation runs** — RFD3 *partial diffusion* (noise/partial schedule from parent backbones)
  and ProteinMPNN redesign of fixed backbones. Inputs come from `binder-compare mature` (parent
  ids + strategy). `TODO:` exact RFD3 partial-diffusion + mpnn commands.
- **Monomer refold** — refold each binder *alone* (ESMFold2 / Boltz-2) to feed
  `binder-compare monomer`. `TODO:` how to emit the binder-only PDBs matched by id.
- **Rosetta affinity** — `conda run -n BindCraft python Evaluator/scripts/interface_energy.py …`
  (PyRosetta in the BindCraft env, cross-platform incl. aarch64/Spark). `TODO:` interface spec
  (`B_A`), batching, runtime.
