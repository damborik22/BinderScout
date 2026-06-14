# Maturation strategy

> **Scaffold.** `TODO:` flesh out.

- Decision tree (`comparison/maturation.decide_maturation_strategy`): weak >500 nM → partial
  diffusion (2-10x); moderate >50 nM → MPNN redesign (2-5x); strong → mutation scan; target met → done.
- Parents: top-k tightest for backbone/sequence rounds; single best for a scan.
- Pre-experimental: use the `affinity` composite as a proxy when there is no Kd yet.
- `TODO:` per-program thresholds; stop criteria; how to seed the next RFD3 partial-diffusion /
  ProteinMPNN run from the parents.
