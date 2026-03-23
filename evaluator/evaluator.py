#!/usr/bin/env python3
"""
BindMaster Evaluator — parses design outputs from Mosaic, BoltzGen, and BindCraft,
cross-ranks candidates by a configurable metric, and optionally re-folds top designs
with Boltz2.

IMPORTANT: Must run inside the Mosaic uv venv (the only env that has JAX + Boltz2):
  /path/to/Mosaic/.venv/bin/python evaluator.py <run-dir> [options]
  OR via the unified CLI:
  bindmaster evaluate <run-dir> [options]

Modes:
  1. Parse mode (default): reads CSV outputs from run-dir subdirs, merges and ranks.
  2. Sequence mode (--sequences FILE or --sequences -): rank/refold a list of bare
     sequences (one per line) without a run directory — useful for quick re-fold of
     sequences from any source.

CLI:
  evaluator.py <run-dir>  [--metric METRIC] [--top N] [--refold N] [--target PDB]
  evaluator.py --sequences FILE [--target PDB] [--refold N]
"""

import argparse
import csv
import math
import sys
from pathlib import Path

# ─── Metric configuration ─────────────────────────────────────────────────────
# For sorting: lower sort key = better rank.
# Higher-is-better metrics are negated so the sort always goes ascending.
HIGHER_IS_BETTER = {
    "iptm",
    "bt_ipsae",
    "tb_ipsae",
    "ipsae_min",
    "bt_iptm",
    "binder_ptm",
    "plddt_binder_mean",
    "plddt_binder_min",
    "plddt_aux",
    "iptm_aux",
    "i_ptm",  # BindCraft column alias
}
LOWER_IS_BETTER = {
    "ranking_loss",
    "pae_bb_mean",
    "pae_bt_mean",
    "pae_tb_mean",
    "pae_overall_mean",
    "pae_max",
    "i_pae",  # BindCraft column alias
}
VALID_METRICS = sorted(HIGHER_IS_BETTER | LOWER_IS_BETTER)

# ─── AA 3→1 lookup (for PDB sequence extraction) ─────────────────────────────
_AA3TO1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "MSE": "M",
    "HSD": "H",
    "HSE": "H",
    "HSP": "H",
}

# ─── Colors ───────────────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _print_step(msg):
    print(f"\n{CYAN}{BOLD}▶ {msg}{RESET}")


def _print_ok(msg):
    print(f"{GREEN}✓ {msg}{RESET}")


def _print_warn(msg):
    print(f"{YELLOW}⚠ {msg}{RESET}")


def _print_fail(msg):
    print(f"{RED}✗ {msg}{RESET}", file=sys.stderr)


# ─── Numeric helpers ──────────────────────────────────────────────────────────


def _safe_float(v, default=None):
    if v is None or str(v).strip() == "":
        return default
    try:
        s = str(v).strip().strip("[]")
        f = float(s)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _sort_key(row: dict, metric: str) -> float:
    """Return an ascending sort key (negate higher-is-better metrics).

    Missing values always sort last (return +inf).
    """
    v = _safe_float(row.get(metric))
    if v is None:
        return float("inf")
    return -v if metric in HIGHER_IS_BETTER else v


# ─── CSV utilities ────────────────────────────────────────────────────────────


def _read_csv(path: Path) -> list:
    rows = []
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
    except Exception as e:
        _print_warn(f"Could not read {path}: {e}")
    return rows


# ─── PDB sequence extractor ───────────────────────────────────────────────────


def _sequence_from_pdb(pdb_path: Path, chain_id: str = "A") -> str | None:
    seen: dict = {}
    try:
        with open(pdb_path) as f:
            for line in f:
                if line[:4] != "ATOM":
                    continue
                if line[12:16].strip() != "CA":
                    continue
                if line[21].strip().upper() != chain_id.upper():
                    continue
                res_name = line[17:20].strip().upper()
                key = (line[22:26].strip(), line[26].strip())
                if key not in seen:
                    seen[key] = _AA3TO1.get(res_name, "X")
    except OSError:
        return None
    return "".join(seen.values()) if seen else None


# ─── mmCIF sequence extractor ─────────────────────────────────────────────────


def _cif_tokenize(text: str) -> list:
    """
    Tokenize mmCIF text into a flat list of string tokens.
    Handles:
      - Multi-line  ;...\\n;  text fields (semicolon at line start)
      - Single- and double-quoted inline strings
      - Inline  #  comments
    """
    tokens: list = []
    i = 0
    n = len(text)

    while i < n:
        # Skip whitespace, track whether a newline was crossed
        preceded_by_newline = i == 0
        while i < n and text[i] in " \t\r\n":
            if text[i] in "\r\n":
                preceded_by_newline = True
            i += 1
        if i >= n:
            break

        c = text[i]

        # Inline comment — skip to end of line
        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue

        # Multi-line semicolon text field — ';' must be at line start
        if c == ";" and preceded_by_newline:
            i += 1  # consume opening ';'
            while i < n and text[i] != "\n":  # skip rest of opening line
                i += 1
            if i < n:
                i += 1  # skip the newline after ';\n'
            start = i
            while i < n:
                if text[i] == "\n" and i + 1 < n and text[i + 1] == ";":
                    tokens.append(text[start:i])
                    i += 2  # consume '\n' + closing ';'
                    while i < n and text[i] != "\n":
                        i += 1  # skip anything after closing ';'
                    break
                i += 1
            else:
                tokens.append(text[start:])  # unterminated — take rest
            continue

        # Quoted string
        if c in "\"'":
            q = c
            i += 1
            start = i
            while i < n and text[i] != q:
                i += 1
            tokens.append(text[start:i])
            if i < n:
                i += 1  # consume closing quote
            continue

        # Bare token
        start = i
        while i < n and text[i] not in " \t\r\n#":
            i += 1
        tokens.append(text[start:i])

    return tokens


def _sequence_from_cif(path: Path, chain_id: str = "A") -> str | None:
    """
    Extract the one-letter amino-acid sequence for *chain_id* from an mmCIF file.
    Strategy:
      1. Look for  pdbx_seq_one_letter_code_can  in an  _entity_poly  loop
         (or as a bare key-value pair).  Match by  pdbx_strand_id  when present.
      2. Fall back to  _atom_site  CA atoms (same logic as the PDB parser).
    """
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None

    tokens = _cif_tokenize(text)
    n = len(tokens)
    chain_id_up = chain_id.upper()

    # ── Pass 1: _entity_poly ──────────────────────────────────────────────────
    i = 0
    while i < n:
        t_low = tokens[i].lower()

        # Bare key-value (non-loop)
        if t_low == "_entity_poly.pdbx_seq_one_letter_code_can":
            if i + 1 < n:
                raw = tokens[i + 1].replace("\n", "").replace(" ", "").upper()
                if raw and raw not in (".", "?"):
                    return raw
            i += 1
            continue

        if t_low != "loop_":
            i += 1
            continue

        # Read loop_ column headers
        i += 1
        col_names: list = []
        while i < n and tokens[i].startswith("_"):
            col_names.append(tokens[i].lower())
            i += 1

        if not any("_entity_poly." in c for c in col_names):
            continue  # i already past the header; go back to outer loop

        num_cols = len(col_names)
        if num_cols == 0:
            continue

        seq_idx = next((j for j, c in enumerate(col_names) if "pdbx_seq_one_letter_code_can" in c), None)
        strand_idx = next((j for j, c in enumerate(col_names) if "pdbx_strand_id" in c), None)

        if seq_idx is None:
            continue

        # Read data rows
        while i + num_cols <= n:
            t0 = tokens[i].lower()
            if t0.startswith("_") or t0 in ("loop_", "data_", "save_"):
                break
            row = tokens[i : i + num_cols]
            raw = row[seq_idx].replace("\n", "").replace(" ", "").upper()
            if raw and raw not in (".", "?"):
                if strand_idx is None:
                    return raw  # single entity — take it
                strands = [s.strip().upper() for s in row[strand_idx].split(",")]
                if chain_id_up in strands:
                    return raw
            i += num_cols

    # ── Pass 2: _atom_site CA fallback ───────────────────────────────────────
    i = 0
    while i < n:
        if tokens[i].lower() != "loop_":
            i += 1
            continue
        i += 1
        col_names = []
        while i < n and tokens[i].startswith("_"):
            col_names.append(tokens[i].lower())
            i += 1

        if not any("_atom_site." in c for c in col_names):
            continue

        col = {c: ci for ci, c in enumerate(col_names)}
        atom_col = col.get("_atom_site.label_atom_id")
        chain_col = col.get("_atom_site.auth_asym_id") or col.get("_atom_site.label_asym_id")
        res_col = col.get("_atom_site.label_comp_id")
        seqn_col = col.get("_atom_site.auth_seq_id") or col.get("_atom_site.label_seq_id")
        ins_col = col.get("_atom_site.pdbx_pdb_ins_code")

        if None in (atom_col, chain_col, res_col, seqn_col):
            continue

        num_cols = len(col_names)
        seen: dict = {}
        while i + num_cols <= n:
            t0 = tokens[i].lower()
            if t0.startswith("_") or t0 in ("loop_", "data_", "save_"):
                break
            row = tokens[i : i + num_cols]
            if row[atom_col].strip() == "CA" and row[chain_col].strip().upper() == chain_id_up:
                res = row[res_col].strip().upper()
                seqn = row[seqn_col].strip()
                ins = row[ins_col].strip() if ins_col is not None else ""
                key = (seqn, ins)
                if key not in seen:
                    seen[key] = _AA3TO1.get(res, "X")
            i += num_cols

        if seen:
            return "".join(seen.values())

    return None


def _sequence_from_structure(path: Path, chain_id: str = "A") -> str | None:
    """Dispatch to the CIF or PDB extractor based on file extension."""
    if path.suffix.lower() in (".cif", ".mmcif"):
        return _sequence_from_cif(path, chain_id)
    return _sequence_from_pdb(path, chain_id)


# ─── Output parsers (one per tool) ────────────────────────────────────────────


def _parse_mosaic(run_dir: Path, *, top_only: bool = True) -> list:
    """Read Mosaic designs.csv (all Boltz2 metrics already present).

    When *top_only* is True (default) and an ``is_top`` column exists, only
    rows with ``is_top == 1`` are returned (the refolded subset).  Pass
    ``top_only=False`` (via ``--all-mosaic-designs``) to include everything.
    """
    csv_path = run_dir / "mosaic" / "designs.csv"
    if not csv_path.exists():
        return []
    rows = _read_csv(csv_path)
    total = len(rows)

    # Filter to refolded designs (is_top == 1) unless explicitly asked for all
    if top_only and rows and "is_top" in rows[0]:
        rows = [r for r in rows if _safe_float(r.get("is_top")) == 1.0]
        _print_ok(f"Mosaic: {len(rows)}/{total} designs (is_top=1) from {csv_path.name}")
    else:
        _print_ok(f"Mosaic: {len(rows)} designs from {csv_path.name}")

    for row in rows:
        row["source"] = "mosaic"
        row.setdefault("sequence", "")
    return rows


def _parse_boltzgen(run_dir: Path) -> list:
    """Read all CSV files from boltzgen/outputs/."""
    outputs_dir = run_dir / "boltzgen" / "outputs"
    if not outputs_dir.exists():
        return []
    all_rows = []
    csv_files = sorted(outputs_dir.glob("*.csv"))
    for csv_path in csv_files:
        rows = _read_csv(csv_path)
        for row in rows:
            row["source"] = "boltzgen"
            row.setdefault("sequence", "")
        all_rows.extend(rows)
    if all_rows:
        _print_ok(f"BoltzGen: {len(all_rows)} designs from {len(csv_files)} CSV file(s)")
    return all_rows


def _parse_bindcraft(run_dir: Path) -> list:
    """Read all CSV files from bindcraft/outputs/ and normalize column names."""
    outputs_dir = run_dir / "bindcraft" / "outputs"
    if not outputs_dir.exists():
        return []
    all_rows = []
    csv_files = sorted(outputs_dir.glob("*.csv"))
    for csv_path in csv_files:
        rows = _read_csv(csv_path)
        for row in rows:
            row["source"] = "bindcraft"
            # Normalize column name aliases (BindCraft uses mixed case)
            for alias in ("i_pTM", "i_ptm", "Average_i_pTM"):
                if alias in row and "iptm" not in row:
                    row["iptm"] = row[alias]
                    break
            for alias in ("i_pAE", "i_pae", "Average_i_pAE"):
                if alias in row and "pae_bt_mean" not in row:
                    row["pae_bt_mean"] = row[alias]
                    break
            # Prefer binder_sequence or Sequence column if sequence is missing
            if not row.get("sequence"):
                row["sequence"] = row.get("Sequence", "") or row.get("binder_sequence", "")
        all_rows.extend(rows)
    if all_rows:
        _print_ok(f"BindCraft: {len(all_rows)} designs from {len(csv_files)} CSV file(s)")
    return all_rows


def _normalize_pxdesign_row(row: dict) -> dict:
    """Map PXDesign column names to evaluator standard names."""
    col_map = {
        "i_pTM": "iptm",
        "af2_iptm": "iptm",
        "pLDDT": "plddt_binder_mean",
        "af2_plddt": "plddt_binder_mean",
    }
    for src, dst in col_map.items():
        if src in row and dst not in row:
            row[dst] = _safe_float(row[src])
    row["source"] = "pxdesign"
    row.setdefault("sequence", "")
    return row


def _parse_pxdesign(run_dir: Path) -> list:
    """Read PXDesign sequences from pxdesign/sequences.csv or sample_level_output.csv.

    Priority:
    1. pxdesign/sequences.csv — generated by the run script's collector
    2. pxdesign/outputs_len*/global_run_0/*/seed_*/predictions/sample_level_output.csv
    3. pxdesign/summary.csv or pxdesign/outputs/summary.csv (legacy single-length)
    """
    pxd_dir = run_dir / "pxdesign"
    if not pxd_dir.exists():
        return []

    # Strategy 1: sequences.csv (aggregated by run script)
    seq_csv = pxd_dir / "sequences.csv"
    if seq_csv.exists():
        rows = _read_csv(seq_csv)
        rows = [_normalize_pxdesign_row(r) for r in rows]
        if rows:
            _print_ok(f"PXDesign: {len(rows)} designs from sequences.csv")
            return rows

    # Strategy 2: sample_level_output.csv from pipeline mode (all lengths)
    all_rows = []
    for slcsv in sorted(pxd_dir.rglob("sample_level_output.csv")):
        csv_rows = _read_csv(slcsv)
        csv_rows = [_normalize_pxdesign_row(r) for r in csv_rows]
        all_rows.extend(csv_rows)
    if all_rows:
        _print_ok(f"PXDesign: {len(all_rows)} designs from sample_level_output.csv files")
        return all_rows

    # Strategy 3: summary.csv (legacy single-length or outputs/)
    candidates = [
        pxd_dir / "outputs" / "summary.csv",
        pxd_dir / "summary.csv",
    ]
    candidates.extend(sorted(pxd_dir.rglob("summary.csv")))
    for c in candidates:
        if c.exists():
            rows = _read_csv(c)
            rows = [_normalize_pxdesign_row(r) for r in rows]
            if rows:
                _print_ok(f"PXDesign: {len(rows)} designs from {c.name}")
                return rows

    return []


def _parse_rfaa(run_dir: Path) -> list:
    """Read RFAA + LigandMPNN output sequences.csv.

    The RFAA pipeline produces backbone PDBs (stage 1) and then runs
    LigandMPNN to design sequences (stage 2). The combined output is
    collected in rfaa/sequences.csv.
    """
    csv_path = run_dir / "rfaa" / "sequences.csv"
    if not csv_path.exists():
        outputs_dir = run_dir / "rfaa" / "outputs"
        if outputs_dir.exists():
            pdb_count = len(list(outputs_dir.glob("*.pdb")))
            if pdb_count:
                _print_warn(
                    f"RFAA: {pdb_count} backbone PDB(s) found but no sequences.csv. "
                    "Run LigandMPNN first (included in run_rfaa.sh)."
                )
        return []

    rows = _read_csv(csv_path)
    for row in rows:
        row["source"] = "rfaa"
        row.setdefault("sequence", "")
    rows = [r for r in rows if r.get("sequence")]
    if rows:
        _print_ok(f"RFAA: {len(rows)} sequences (via LigandMPNN)")
    return rows


def _normalize_complexa_row(row: dict) -> dict:
    """Map Proteina-Complexa column names to evaluator standard names."""
    col_map = {
        "self_complex_i_pTM": "iptm",
        "self_complex_pLDDT": "plddt_binder_mean",
        "self_complex_i_pAE": "pae_bt_mean",
        "self_binder_scRMSD": "scrmsd_binder",
    }
    for src, dst in col_map.items():
        if src in row and dst not in row:
            row[dst] = _safe_float(row[src])
    row["source"] = "proteina_complexa"
    row.setdefault("sequence", "")
    return row


def _parse_proteina_complexa(run_dir: Path) -> list:
    """Read Proteina-Complexa sequences from proteina_complexa/sequences.csv.

    Priority:
    1. proteina_complexa/sequences.csv — generated by the run script's collector
    2. proteina_complexa/evaluation_results/**/*.csv — from Complexa pipeline
    """
    pc_dir = run_dir / "proteina_complexa"
    if not pc_dir.exists():
        return []

    # Strategy 1: sequences.csv (aggregated by run script)
    seq_csv = pc_dir / "sequences.csv"
    if seq_csv.exists():
        rows = _read_csv(seq_csv)
        rows = [_normalize_complexa_row(r) for r in rows]
        rows = [r for r in rows if r.get("sequence")]
        if rows:
            _print_ok(f"Proteina-Complexa: {len(rows)} designs from sequences.csv")
            return rows

    # Strategy 2: evaluation_results CSVs
    all_rows = []
    for csv_path in sorted(pc_dir.rglob("*.csv")):
        if csv_path.name == "sequences.csv":
            continue
        csv_rows = _read_csv(csv_path)
        for r in csv_rows:
            r = _normalize_complexa_row(r)
            if r.get("sequence"):
                all_rows.append(r)
    if all_rows:
        _print_ok(f"Proteina-Complexa: {len(all_rows)} designs from evaluation CSVs")
        return all_rows

    return []


# ─── Ranking ──────────────────────────────────────────────────────────────────


def _rank(rows: list, metric: str) -> list:
    """Sort rows by metric (best first). Rows missing the metric go last.

    Filters out rows with clearly bogus metric values (e.g. ipTM > 1.0)
    that arise from CSV column misalignment.
    """
    # Sanity filter: ipTM/pTM are in [0,1]; values > 1 indicate broken CSV rows
    if metric in HIGHER_IS_BETTER and metric in ("iptm", "plddt_binder_mean", "binder_ptm"):
        clean = []
        dropped = 0
        for r in rows:
            v = _safe_float(r.get(metric))
            if v is not None and v > 1.0:
                dropped += 1
            else:
                clean.append(r)
        if dropped:
            _print_warn(f"Dropped {dropped} designs with {metric} > 1.0 (likely CSV parse error)")
        rows = clean

    has_metric = sum(1 for r in rows if _safe_float(r.get(metric)) is not None)
    if has_metric == 0:
        _print_warn(f"Metric '{metric}' not found in any design — output will be unsorted")
    return sorted(rows, key=lambda r: _sort_key(r, metric))


# ─── Writers ──────────────────────────────────────────────────────────────────


def _write_summary_csv(path: Path, rows: list):
    if not rows:
        return
    first_cols = ["rank", "source", "sequence"]
    all_keys = list({k for r in rows for k in r})
    extra = sorted(c for c in all_keys if c not in first_cols)
    columns = first_cols + extra
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(rows):
            out = dict(row)
            out["rank"] = i + 1
            writer.writerow(out)
    _print_ok(f"Summary CSV   → {path}")


def _write_report(path: Path, rows: list, metric: str, top_n: int):
    report_rows = rows[:top_n]
    lines = [
        "=" * 70,
        "BindMaster Evaluation Report",
        f"Sorted by: {metric}  |  Showing top {len(report_rows)} of {len(rows)} designs",
        "=" * 70,
        "",
    ]
    key_metrics = [
        "iptm",
        "bt_ipsae",
        "tb_ipsae",
        "ipsae_min",
        "ranking_loss",
        "plddt_binder_mean",
        "plddt_binder_min",
        "binder_ptm",
        "pae_bb_mean",
        "pae_bt_mean",
        "i_ptm",
        "i_pae",
    ]
    for i, row in enumerate(report_rows):
        lines.append(f"Rank {i + 1} — {row.get('source', '?').upper()}")
        seq = row.get("sequence", "")
        if seq:
            lines.append(f"  Sequence ({len(seq)} aa): {seq[:60]}{'...' if len(seq) > 60 else ''}")
        parts = []
        for m in key_metrics:
            v = _safe_float(row.get(m))
            if v is not None:
                parts.append(f"{m}={v:.4f}")
        if parts:
            lines.append(f"  Metrics: {', '.join(parts)}")
        pdb = row.get("pdb", "")
        if pdb:
            lines.append(f"  PDB: {pdb}")
        lines.append("")
    path.write_text("\n".join(lines))
    _print_ok(f"Report        → {path}")


# ─── Boltz2 re-fold ───────────────────────────────────────────────────────────


def _refold(rows: list, n: int, target_seq: str | None, output_dir: Path):
    """
    Re-fold top-N binder sequences with Boltz2 (Mosaic venv only).
    Each binder is folded in isolation first, then optionally with the target.
    NOTE: This runs in the Mosaic uv venv — do not mix conda envs here.
    """
    try:
        import jax
        import jax.numpy as jnp
        import numpy as np
        from mosaic.common import TOKENS
        from mosaic.models.boltz2 import Boltz2
        from mosaic.structure_prediction import TargetChain
    except ImportError as e:
        _print_fail(f"Boltz2 import failed — is Mosaic installed? {e}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    folder = Boltz2()

    seqs = [r.get("sequence", "") for r in rows if r.get("sequence")][:n]
    sources = [r.get("source", "?") for r in rows if r.get("sequence")][:n]

    if not seqs:
        _print_warn("No sequences available for re-folding")
        return

    _print_step(f"Re-folding top {len(seqs)} designs with Boltz2 (Mosaic venv)")

    for i, (seq_str, src) in enumerate(zip(seqs, sources)):
        print(f"\n[{i + 1}/{len(seqs)}] {src}: {len(seq_str)} aa  {seq_str[:40]}{'...' if len(seq_str) > 40 else ''}")
        try:
            chains = [TargetChain(sequence=seq_str, use_msa=True)]
            if target_seq:
                chains.append(TargetChain(sequence=target_seq, use_msa=False))

            features, writer = folder.target_only_features(chains=chains)

            seq_indices = jnp.array([TOKENS.index(c) for c in seq_str])
            pssm = jax.nn.one_hot(seq_indices, 20)

            prediction = folder.predict(
                PSSM=pssm,
                features=features,
                writer=writer,
                recycling_steps=3,
                key=jax.random.key(i),
            )

            iptm = float(prediction.iptm)
            plddt_mean = float(np.array(prediction.plddt).mean())
            pdb_path = output_dir / f"refolded_rank{i + 1}_{src}.pdb"
            with open(pdb_path, "w") as f:
                f.write(prediction.st.make_pdb_string())
            _print_ok(f"  iptm={iptm:.4f}  plddt_mean={plddt_mean:.4f}  → {pdb_path.name}")

        except Exception as e:
            _print_warn(f"  Re-fold failed: {e}")

    _print_ok(f"Re-folded structures → {output_dir}")


# ─── Sequence-only mode ───────────────────────────────────────────────────────


def _load_sequences(seq_source: str) -> list:
    """
    Load bare amino-acid sequences (one per line) from a file or stdin ('-').
    Returns a list of row dicts with source='sequence_input'.
    Comments (#) and blank lines are skipped.
    """
    if seq_source == "-":
        print(f"{CYAN}Enter sequences (one per line, Ctrl-D to finish):{RESET}")
        lines = sys.stdin.read().splitlines()
    else:
        path = Path(seq_source).expanduser()
        if not path.exists():
            _print_fail(f"Sequence file not found: {path}")
            sys.exit(1)
        lines = path.read_text().splitlines()

    rows = []
    valid_aa = set("ACDEFGHIKLMNPQRSTVWYX")
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        seq = line.upper()
        if not all(c in valid_aa for c in seq):
            _print_warn(f"Skipping non-sequence line: {raw[:60]}")
            continue
        rows.append({"source": "sequence_input", "sequence": seq})

    _print_ok(f"Loaded {len(rows)} sequences from '{seq_source}'")
    return rows


# ─── Main ─────────────────────────────────────────────────────────────────────


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bindmaster evaluate",
        description=(
            "Parse design outputs (Mosaic / BoltzGen / BindCraft), rank by metric, "
            "and optionally re-fold top designs with Boltz2 (Mosaic venv)."
        ),
    )
    parser.add_argument(
        "run_dir",
        nargs="?",
        help="Path to the run directory (e.g. runs/PDL1_test). "
        "Omit to be prompted, or use --sequences for sequence-only mode.",
    )
    parser.add_argument(
        "--sequences",
        metavar="FILE|-",
        help="Sequence-only mode: read bare AA sequences (one per line) from FILE "
        "or stdin ('-') instead of parsing a run directory.",
    )
    parser.add_argument(
        "--metric",
        default="iptm",
        choices=VALID_METRICS,
        help="Primary ranking metric (default: iptm; higher-is-better: "
        + ", ".join(sorted(HIGHER_IS_BETTER))
        + "). For sequence-only mode without CSVs, metric is unused.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="Number of top designs to show in the report (default: 10).",
    )
    parser.add_argument(
        "--refold",
        type=int,
        default=0,
        metavar="N",
        help="Re-fold top N designs with Boltz2 (Mosaic venv, default: 0 = skip).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        metavar="PDB",
        help="Target PDB or CIF file. Used to extract the target sequence for "
        "re-folding complex predictions. "
        "Auto-detected from run-dir/target/*.pdb or *.cif if omitted.",
    )
    parser.add_argument(
        "--all-mosaic-designs",
        action="store_true",
        help="Include all Mosaic designs (default: only is_top=1 refolded designs).",
    )
    return parser


def main():
    parser = _make_parser()
    args = parser.parse_args()

    # ── Sequence-only mode ─────────────────────────────────────────────────────
    if args.sequences:
        print()
        print(f"{BOLD}{'═' * 60}{RESET}")
        print(f"{BOLD}  BindMaster Evaluator — Sequence Mode{RESET}")
        print(f"{BOLD}{'═' * 60}{RESET}")

        rows = _load_sequences(args.sequences)
        if not rows:
            _print_fail("No valid sequences found.")
            sys.exit(1)

        target_seq = None
        if args.target and args.target.exists():
            target_seq = _sequence_from_structure(args.target, "A")
            if target_seq:
                _print_ok(f"Target sequence: {len(target_seq)} aa from {args.target.name}")

        if args.refold > 0:
            out_dir = Path("evaluation_refolded")
            _refold(rows, args.refold, target_seq, out_dir)
        else:
            for i, row in enumerate(rows[: args.top]):
                seq = row["sequence"]
                print(f"  [{i + 1}] {len(seq)} aa  {seq[:60]}{'...' if len(seq) > 60 else ''}")
        return

    # ── Run-dir parse mode ─────────────────────────────────────────────────────
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
    else:
        raw = input(f"{CYAN}Run directory{RESET}: ").strip()
        run_dir = Path(raw).expanduser().resolve()

    if not run_dir.exists():
        _print_fail(f"Run directory not found: {run_dir}")
        sys.exit(1)

    print()
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  BindMaster Evaluator{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"  Run directory : {run_dir}")
    print(f"  Metric        : {args.metric}")
    print(f"  Top designs   : {args.top}")
    if args.refold:
        print(f"  Re-fold top   : {args.refold}")
    print()

    # ── Parse tool outputs ─────────────────────────────────────────────────────
    _print_step("Parsing design outputs")
    all_rows: list = []
    all_rows.extend(_parse_mosaic(run_dir, top_only=not args.all_mosaic_designs))
    all_rows.extend(_parse_boltzgen(run_dir))
    all_rows.extend(_parse_bindcraft(run_dir))
    all_rows.extend(_parse_pxdesign(run_dir))
    all_rows.extend(_parse_rfaa(run_dir))
    all_rows.extend(_parse_proteina_complexa(run_dir))

    if not all_rows:
        _print_warn("No design outputs found.")
        print("  Expected one or more of:")
        print(f"    {run_dir}/mosaic/designs.csv")
        print(f"    {run_dir}/boltzgen/outputs/*.csv")
        print(f"    {run_dir}/bindcraft/outputs/*.csv")
        print(f"    {run_dir}/pxdesign/outputs/summary.csv (or pxdesign/summary.csv)")
        print(f"    {run_dir}/rfaa/sequences.csv")
        print(f"    {run_dir}/proteina_complexa/sequences.csv")
        sys.exit(1)

    _print_ok(f"Total designs loaded: {len(all_rows)}")

    # ── Cross-rank ─────────────────────────────────────────────────────────────
    _print_step(f"Ranking by '{args.metric}' (best first)")
    ranked = _rank(all_rows, args.metric)

    # ── Write evaluation outputs ───────────────────────────────────────────────
    eval_dir = run_dir / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    _print_step(f"Writing evaluation outputs → {eval_dir}")
    _write_summary_csv(eval_dir / "summary.csv", ranked)
    _write_report(eval_dir / "report.txt", ranked, args.metric, args.top)

    # ── Auto-detect target PDB ────────────────────────────────────────────────
    target_pdb = args.target
    if target_pdb is None:
        target_dir = run_dir / "target"
        if target_dir.exists():
            structs = sorted(target_dir.glob("*.pdb")) + sorted(target_dir.glob("*.cif"))
            if structs:
                target_pdb = structs[0]
                _print_ok(f"Auto-detected target structure: {target_pdb.name}")

    target_seq = None
    if target_pdb and target_pdb.exists():
        target_seq = _sequence_from_structure(target_pdb, "A")
        if target_seq:
            _print_ok(f"Target sequence: {len(target_seq)} aa")
    if target_seq is None:
        # Try to grab from rows (Mosaic includes target_sequence column)
        for r in ranked:
            ts = r.get("target_sequence", "").strip()
            if ts and ts.upper() != "REPLACE_ME":
                target_seq = ts
                _print_ok(f"Target sequence from designs.csv: {len(target_seq)} aa")
                break
        if target_seq is None:
            # Check if every candidate was REPLACE_ME
            has_placeholder = any(r.get("target_sequence", "").strip().upper() == "REPLACE_ME" for r in ranked)
            if has_placeholder:
                _print_warn("target_sequence in designs.csv is 'REPLACE_ME' (template placeholder) — ignored")

    # ── Optional Boltz2 re-fold ───────────────────────────────────────────────
    if args.refold > 0:
        _refold(ranked, args.refold, target_seq, eval_dir / "refolded")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"{BOLD}=== Evaluation complete ==={RESET}")
    src_counts: dict = {}
    for r in all_rows:
        s = r.get("source", "?")
        src_counts[s] = src_counts.get(s, 0) + 1
    for src, cnt in sorted(src_counts.items()):
        print(f"  {src}: {cnt} designs")
    print(f"  Total: {len(all_rows)}")
    print()
    print(f"  {eval_dir}/")
    print(f"    summary.csv — all designs ranked by {args.metric}")
    print(f"    report.txt  — top {args.top} with key metrics")
    if args.refold:
        print("    refolded/   — Boltz2 re-folded PDB structures (Mosaic venv)")


if __name__ == "__main__":
    main()
