# Reading the ranking

> **Scaffold.** `TODO:` flesh out with examples.

- **Two-stage** (default): max-screen top 50% by `consensus_iptm`, then mean-rank survivors.
- **`chain_iptm_interface`** (ESMFold2): best single binder screen (~0.745 AUC); the autosize gate.
- **Same-model bias matrix** — never trust a tool on the engine it designed against (see
  `bindmaster-orchestrator/references/tools/README.md`).
- `ipsae_min`, `agreement_count`, quality tiers — secondary/diagnostic.
- `TODO:` how to explain a ranking to a human; when engines disagree.
