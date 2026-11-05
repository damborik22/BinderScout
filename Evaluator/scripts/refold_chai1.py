"""Standalone batch refolder for Chai-1 (chaidiscovery/chai-lab), a candidate AF3 replacement.

Run inside Chai-1's own env (``chai_lab`` importable, ``pandas[parquet]`` present as chai-lab requires
it); ``binder_comparison`` must be importable there too (``pip install -e Evaluator``).

Follows chai-lab tag ``v0.6.1`` (``8d5ac0f``, package ``chai_lab`` 0.6.1, the latest release). Sources
read for this script (all at that tag):

* https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/README.md  (CLI, "uses embeddings without MSAs
  or templates" by default, ``CHAI_DOWNLOADS_DIR``, Apache-2.0 for code and weights)
* https://github.com/chaidiscovery/chai-lab/blob/v0.6.1/examples/msas/README.md  (the
  ``.aligned.pqt`` format: four columns, file named by the sequence hash, ``source_database`` is
  FEATURISED, ``uniref90`` is the suggested catch-all)
* ``chai_lab/chai1.py`` (``run_inference`` signature, ``run_folding_on_context`` where PAE is computed,
  ``StructureCandidates``), ``chai_lab/ranking/rank.py`` + ``ptm.py`` (aggregate score, ipTM),
  ``chai_lab/data/dataset/inference_dataset.py`` (FASTA header syntax, chain order, tokenisation),
  ``chai_lab/data/dataset/msas/load.py`` (how a missing MSA file is handled),
  ``chai_lab/data/parsing/msas/aligned_pqt.py`` (``expected_basename``, the pandera schema),
  ``chai_lab/data/dataset/msas/colabfold.py`` (how chai-lab itself turns a ColabFold a3m into a
  parquet), ``chai_lab/data/dataset/embeddings/esm.py`` (ESM2 embeddings), ``chai_lab/data/io/
  cif_utils.py`` (the CIF it writes), ``chai_lab/utils/paths.py`` (weights).

VERSION PIN (Evaluator/docs/second_engine_licences.md): the licence record covers chai-lab ``v0.6.1``
(Apache-2.0 for code AND weights per the README sentence and the Hugging Face card; weights come from
``chaiassets.com``, whose terms were not separately checked). Earlier history of the repository carried a
non-commercial community licence, so this adapter refuses to run on ANY other installed version
(``require_cleared_version``) before a single design is touched, and the worker re-checks
``chai_lab.__version__`` in the process that actually imports the package. ``engine_version`` is the
installed package version; ``weights_id`` (``WEIGHTS_ID``) names the two weight sets the 0.6.1 package
downloads: the exported model components under ``.../chai1-inference-depencencies/models_v2/`` and the
traced ESM2 3B fp16 file ``traced_sdpa_esm2_t36_3B_UR50D_fp16.pt``. Caveat: the check reads the version
string, so a git checkout of ``main`` that still says 0.6.1 passes; install the PyPI release or the tag.

What was established (this is what the whole script rests on):

* The ``chai-lab fold`` CLI does NOT write the PAE: it writes ``pred.model_idx_N.cif`` and
  ``scores.model_idx_N.npz`` (aggregate_score, ptm, iptm, per_chain_*). The PAE exists only on the
  object ``run_inference`` returns: ``StructureCandidates.pae`` is ``[candidate, num_tokens,
  num_tokens]`` (float32 on the CPU), the expectation of the 64-bin PAE logits (bin centres 0.5..31.5 A),
  taken over the REAL tokens only (padding is removed with ``token_exists_mask``), so it is token-level
  and unpadded. ``StructureCandidates.plddt`` is a per-token average of per-ATOM pLDDT and is not used
  (see below). This script therefore calls the Python API, in a worker subprocess (see below).
* Token order = chain order = FASTA record order. ``read_inputs`` keeps the FASTA order, ``load_chains_
  from_raw`` numbers chains 1, 2, ... in that order and ``AllAtomStructureContext.merge`` concatenates
  their tokens. The FASTA written here lists the TARGET first (chain A) and the binder second (chain B)
  so the native order is ``[target | binder]`` and ``order="target_binder"`` is passed to
  ``to_binder_target_pae``. A protein residue is one token, so no atom reduction is needed. Two traps
  are closed here: ``load_chains_from_raw`` SILENTLY DROPS a chain that fails to tokenise (the PAE would
  then be binder-only, which the driver's size check refuses), and a size check cannot see an order
  mistake at equal lengths, so the saved CIF is also required to hold the target's residues in chain A
  and the binder's in chain B (checked from the residue names, which come from the same merged context
  as the PAE).
* Samples: ``num_diffn_samples`` diffusion samples per trunk; ``--num-seeds`` maps to
  ``num_trunk_samples`` (trunk ``k`` uses seed ``base + k``; the base is 101), ``--num-samples`` to
  ``num_diffn_samples`` (Chai-1's own default is 5). The top sample is the highest ``aggregate_score`` (0.2 ptm + 0.8 iptm - 100 *
  has_inter_chain_clashes) over every trunk and sample; non-finite scores are skipped. Reported ``iptm`` /
  ``ptm`` are Chai-1's own (``ptm_scores.interface_ptm`` / ``complex_ptm``).
* Model settings are Chai-1's documented defaults, passed explicitly: 3 trunk recycles, 200 diffusion
  steps, ``use_esm_embeddings=True`` (kept ON: the ESM2 3B embeddings are the binder's only evolutionary
  signal), ``low_memory=True``; no templates, no restraints, no MSA server.
* Inputs per chain: TARGET = ESM2 embeddings + the shared ColabFold MSA; BINDER = ESM2 embeddings + a
  single-sequence MSA (query only), i.e. no MSA. ``--no-msa`` (or a failed fetch with ``--allow-no-msa``)
  gives the target the same query-only treatment. Mechanics: Chai-1 reads MSAs from ``msa_directory``,
  one ``<sha256(UPPERCASE sequence)>.aligned.pqt`` per unique chain sequence; a chain without a file
  gets a one-row query-only MSA (``load.py``). The directory is therefore always passed (an empty one
  without a target MSA) so the binder's input is identical in both modes; chai-lab's own no-MSA default
  (``msa_directory=None``) would use an all-padding MSA instead, which differs slightly.
* a3m -> parquet: the cached ColabFold text (``get_target_msa``) is converted in-process, the way
  chai-lab's own ColabFold importer does it (``colabfold.py``): ``sequence`` is the a3m row as is
  (lowercase insertions and gaps kept), row 0 is ``query``, ``pairing_key`` is empty (an unpaired
  monomer MSA; the binder has none to pair with), ``comment`` is the a3m header. ``source_database`` is
  featurised by the model, so it is not left arbitrary: a row whose header starts with ``UniRef`` is
  labelled ``uniref90``, everything else ``bfd_uniclust`` -- exactly chai-lab's rule for ColabFold
  results. The cached a3m is ColabFold's ``uniref.a3m``, so nearly every row is ``uniref90``. Gap-only
  padding rows are dropped, and the query row must equal the target and every row must have the
  target's column count (chai-lab would otherwise fail on a token mismatch deep inside the model).
* pLDDT: ``StructureCandidates`` exposes per-token means; the structure carries per-ATOM pLDDT x100 in
  the B-factor column (``save_to_cif``: ``100 * plddt_scores_atom``). Per-residue pLDDT here is the
  B-factor of the CA atoms of the top sample's CIF (0-100; the driver rescales to 0-1), the same
  convention as the OpenFold3 and Protenix adapters. The CIF is read with a small stdlib reader of its
  ``_atom_site`` loop. A missing CA, a chain of the wrong length, a wrong residue sequence, an extra
  chain or all-zero B-factors fails the design loudly.
* The model call runs in a WORKER SUBPROCESS (this same file with ``--chai-worker <spec.json>``, one per
  design): a CUDA out-of-memory error can leave a CUDA process unusable and ``run_inference`` offers no
  recovery, so isolation is what lets the batch continue (that design gets a blank row). Cost: weights
  and the ESM model are reloaded for every design. An exit 0 without a result file is a FAILED design.
  ``chai_lab`` is imported only inside the worker.
* Weights are downloaded on first use into ``$CHAI_DOWNLOADS_DIR`` (default: ``<package>/downloads``);
  ``--model-dir`` sets that variable for the worker.

Emits the same unprefixed CSV as ``refold_af3.py``; the engine name enters at merge time
(``add_iptm_from_pae_files(prefix="chai1")``). Sidecars in the output dir: ``target_msa_mode.json`` and
``refold_run_info.json``.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
import pandas as pd
from binder_comparison.refolding.second_engine_driver import EngineError, run_cli

ENGINE = "chai1"
#: The one release the licence record covers (tag v0.6.1). Exact match.
CLEARED_VERSION = "0.6.1"
#: The weight sets chai-lab 0.6.1 downloads: exported components dir ``models_v2`` + traced ESM2 3B fp16.
WEIGHTS_ID = "chai1_models_v2+traced_sdpa_esm2_t36_3B_UR50D_fp16"
TARGET_CHAIN, BINDER_CHAIN = "A", "B"
TARGET_NAME, BINDER_NAME = "target", "binder"
#: Chains are listed target-first, so the PAE rows/columns are [target | binder].
NATIVE_PAE_ORDER = "target_binder"
MSA_FILE_NAME = "target.a3m"  # the driver writes the cached a3m here; it is converted to parquet per design
DEFAULT_SEED = 101
#: Chai-1's documented defaults, passed explicitly so the settings are on record.
NUM_TRUNK_RECYCLES = 3
NUM_DIFFN_TIMESTEPS = 200
RESULT_NAME = "chai_result.npz"
WORKER_FLAG = "--chai-worker"

_STANDARD = "ACDEFGHIKLMNPQRSTVWY"
_THREE_TO_ONE = {
    "ALA": "A",
    "CYS": "C",
    "ASP": "D",
    "GLU": "E",
    "PHE": "F",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LYS": "K",
    "LEU": "L",
    "MET": "M",
    "ASN": "N",
    "PRO": "P",
    "GLN": "Q",
    "ARG": "R",
    "SER": "S",
    "THR": "T",
    "VAL": "V",
    "TRP": "W",
    "TYR": "Y",
}


class UnclearedVersionError(ValueError):
    """The installed chai-lab is not the release the licence record covers."""


def require_cleared_version(version: str) -> str:
    """Return ``version`` if it is the cleared release; otherwise refuse, saying why."""
    if version == CLEARED_VERSION:
        return version
    raise UnclearedVersionError(
        f"refusing chai-lab version {version!r}: only chai-lab {CLEARED_VERSION} is cleared for use "
        f"(Apache-2.0 code and weights at tag v{CLEARED_VERSION}; Evaluator/docs/second_engine_licences.md). "
        f"Earlier versions were released under a non-commercial community licence and no other release "
        f"has been checked against the licence record. 'unknown' means chai_lab is not installed in this "
        f"environment or its version could not be read."
    )


def _engine_version() -> str:
    for name in ("chai_lab", "chai-lab"):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return "unknown"


# ---------------------------------------------------------------------------
# Input construction: FASTA, and the cached a3m as <sha256>.aligned.pqt
# ---------------------------------------------------------------------------


def build_fasta(binder_seq: str, target_seq: str) -> str:
    """The Chai-1 input: TARGET first (chain A), binder second (chain B); unique entity names."""
    return f">protein|name={TARGET_NAME}\n{target_seq}\n>protein|name={BINDER_NAME}\n{binder_seq}\n"


def aligned_pqt_name(sequence: str) -> str:
    """``chai_lab...aligned_pqt.expected_basename``: sha256 of the UPPERCASED sequence."""
    import hashlib

    return hashlib.sha256(sequence.upper().encode()).hexdigest() + ".aligned.pqt"


def _read_a3m(text: str) -> list[tuple[str, str]]:
    records: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            records.append((line[1:].strip(), []))
        elif records:
            records[-1][1].append(line)
    return [(header, "".join(parts)) for header, parts in records]


def a3m_to_aligned_df(a3m_text: str, target_seq: str) -> pd.DataFrame:
    """The ColabFold a3m text as chai-lab's ``AlignedParquetModel`` table (see the module docstring)."""
    records = _read_a3m(a3m_text)
    if not records:
        raise ValueError("the target MSA holds no records")
    n_cols = len(target_seq)
    query = re.sub(r"[a-z.\-]", "", records[0][1])
    if query.upper() != target_seq.upper():
        raise ValueError(
            f"the first (query) row of the target MSA is {query[:30]!r}... , not the target sequence "
            f"({target_seq[:30]!r}...); Chai-1 needs the query as row 0"
        )
    rows = []
    for i, (header, seq) in enumerate(records):
        if i > 0 and set(seq) == {"-"}:
            continue  # gap-only padding row, dropped as chai-lab's ColabFold importer does
        aligned_cols = len(re.sub(r"[a-z.]", "", seq))
        if aligned_cols != n_cols:
            raise ValueError(f"MSA row {i} ({header[:40]!r}) has {aligned_cols} aligned columns, expected {n_cols}")
        if i == 0:
            source = "query"
        else:
            source = "uniref90" if header.startswith("UniRef") else "bfd_uniclust"
        rows.append({"sequence": seq, "source_database": source, "pairing_key": "", "comment": header})
    return pd.DataFrame.from_records(rows, columns=["sequence", "source_database", "pairing_key", "comment"])


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path)  # pyarrow, which chai-lab's own requirements (pandas[parquet]) install


def prepare_inputs(work_dir: Path, binder_seq: str, target_seq: str, *, target_msa_path: Path | None) -> dict:
    """Write ``input.fasta`` and the MSA directory under ``work_dir``.

    The MSA directory always exists. With a target MSA it holds exactly one file, the target's; the binder
    (and the target, without an MSA) have none and are therefore single-sequence for Chai-1.
    """
    work_dir = Path(work_dir)
    msa_dir = work_dir / "msas"
    msa_dir.mkdir(parents=True, exist_ok=True)
    fasta = work_dir / "input.fasta"
    fasta.write_text(build_fasta(binder_seq, target_seq))
    if target_msa_path is not None:
        df = a3m_to_aligned_df(Path(target_msa_path).read_text(), target_seq)
        _write_parquet(df, msa_dir / aligned_pqt_name(target_seq))
    return {"fasta": fasta, "msa_dir": msa_dir}


# ---------------------------------------------------------------------------
# The model call (the one seam the tests replace) and its worker subprocess
# ---------------------------------------------------------------------------


def _predict_one(
    *,
    query_id: str,
    binder_seq: str,
    target_seq: str,
    target_msa_path: Path | None,
    work_dir: Path,
    model_dir: Path | None,
    num_seeds: int,
    num_samples: int,
) -> dict:
    """Run Chai-1 on one binder-target pair; return the top sample.

    THE MODEL SEAM: tests replace this function. It returns a dict with ``pae`` (token-level, native
    chain order: target then binder), ``summary`` (``iptm``, ``ptm``, ``sample_ranking_score``), ``cif``
    (path), ``plddt_target`` / ``plddt_binder`` (per residue, 0-100) and ``seed``. Raises if the model
    produced nothing.
    """
    require_cleared_version(_engine_version())  # also here, so no caller can reach the model around configure()
    work_dir = Path(work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)  # never pick up the output of an earlier, partly failed attempt
    work_dir.mkdir(parents=True)
    paths = prepare_inputs(work_dir, binder_seq, target_seq, target_msa_path=target_msa_path)
    # run_inference insists that its output directory is missing or empty: do not create it.
    spec = {
        "fasta": str(paths["fasta"]),
        "msa_dir": str(paths["msa_dir"]),
        "output_dir": str(work_dir / "chai_out"),
        "result": str(work_dir / RESULT_NAME),
        "num_samples": num_samples,
        "num_seeds": num_seeds,
        "seed": DEFAULT_SEED,
    }
    spec_path = work_dir / "worker_spec.json"
    spec_path.write_text(json.dumps(spec, indent=2))

    cmd = [sys.executable, str(Path(__file__).resolve()), WORKER_FLAG, str(spec_path)]
    env = dict(os.environ)
    if model_dir is not None:
        env["CHAI_DOWNLOADS_DIR"] = str(model_dir)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env)
    if proc.returncode != 0:
        print(f"  [chai1] STDERR: {proc.stderr[-4000:]}" if proc.stderr else "  [chai1] No stderr")
        raise EngineError(f"Chai-1 worker exited with code {proc.returncode}", proc.stderr or "")
    if not Path(spec["result"]).is_file():
        print(f"  [chai1] STDERR: {proc.stderr[-4000:]}" if proc.stderr else "  [chai1] No stderr")
        raise EngineError(
            f"Chai-1 worker exited 0 but wrote no result file for {query_id} (no prediction)", proc.stderr or ""
        )
    return _load_top_sample(
        Path(spec["result"]), num_samples=num_samples, seed=DEFAULT_SEED, binder_seq=binder_seq, target_seq=target_seq
    )


def _np(x) -> np.ndarray:
    """A torch tensor (or anything array-like) as a CPU numpy array."""
    if hasattr(x, "detach"):
        x = x.detach().cpu()
    if hasattr(x, "numpy"):
        return x.numpy()
    return np.asarray(x)


def _scalar(x) -> float:
    arr = _np(x).reshape(-1)
    if arr.size != 1:
        raise ValueError(f"expected one number, got {arr.size}")
    return float(arr[0])


def _run_worker(spec_path: Path) -> None:
    """Worker process: call ``chai_lab.chai1.run_inference`` and dump every candidate to ``result``."""
    spec = json.loads(Path(spec_path).read_text())
    import chai_lab  # lazy: only the Chai-1 env has it
    from chai_lab.chai1 import run_inference

    require_cleared_version(getattr(chai_lab, "__version__", "unknown"))
    n_samples, n_seeds = int(spec["num_samples"]), int(spec["num_seeds"])
    cand = run_inference(
        fasta_file=Path(spec["fasta"]),
        output_dir=Path(spec["output_dir"]),
        use_esm_embeddings=True,
        use_msa_server=False,
        msa_directory=Path(spec["msa_dir"]),
        num_trunk_recycles=NUM_TRUNK_RECYCLES,
        num_diffn_timesteps=NUM_DIFFN_TIMESTEPS,
        num_diffn_samples=n_samples,
        num_trunk_samples=n_seeds,
        seed=int(spec["seed"]),
        low_memory=True,
    )
    expected = n_samples * n_seeds
    pae = _np(cand.pae).astype(np.float32)
    if not (len(cand.cif_paths) == len(cand.ranking_data) == pae.shape[0] == expected):
        raise RuntimeError(
            f"Chai-1 returned {len(cand.cif_paths)} structures / {len(cand.ranking_data)} rankings / "
            f"{pae.shape[0]} PAE matrices for {expected} requested candidate(s)"
        )
    np.savez(
        spec["result"],
        pae=pae,
        aggregate_score=np.asarray([_scalar(rd.aggregate_score) for rd in cand.ranking_data], dtype=np.float32),
        iptm=np.asarray([_scalar(rd.ptm_scores.interface_ptm) for rd in cand.ranking_data], dtype=np.float32),
        ptm=np.asarray([_scalar(rd.ptm_scores.complex_ptm) for rd in cand.ranking_data], dtype=np.float32),
        cif_paths=np.asarray([str(Path(p).resolve()) for p in cand.cif_paths]),
    )


# ---------------------------------------------------------------------------
# The result: top sample, PAE, pLDDT
# ---------------------------------------------------------------------------


def _load_top_sample(result: Path, *, num_samples: int, seed: int, binder_seq: str, target_seq: str) -> dict:
    """The candidate with the highest finite ``aggregate_score`` (and an existing CIF), fully validated."""
    with np.load(result, allow_pickle=False) as res:
        pae, agg, iptm, ptm = res["pae"], res["aggregate_score"], res["iptm"], res["ptm"]
        cifs = [Path(str(p)) for p in res["cif_paths"]]
    n = len(agg)
    if not (n > 0 and n % num_samples == 0 and pae.shape[0] == len(iptm) == len(ptm) == len(cifs) == n):
        raise EngineError(
            f"Chai-1 result holds {n} candidate(s) ({pae.shape[0]} PAE / {len(cifs)} structures) for "
            f"{num_samples} sample(s) per trunk"
        )
    best = None
    for i in range(n):
        score = float(agg[i])
        if not math.isfinite(score):
            print(f"  [chai1] Ignoring candidate {i}: non-finite aggregate_score ({score})")
            continue
        if not cifs[i].is_file():
            print(f"  [chai1] Ignoring candidate {i}: structure {cifs[i].name} is missing")
            continue
        if best is None or score > best[0]:
            best = (score, i)
    if best is None:
        raise EngineError("Chai-1 produced no candidate with a finite aggregate_score and a structure")
    score, i = best
    plddt = _ca_plddt_by_chain(cifs[i], target_seq, binder_seq)
    return {
        "pae": pae[i].astype(np.float32),
        "summary": {"iptm": float(iptm[i]), "ptm": float(ptm[i]), "sample_ranking_score": score},
        "cif": cifs[i],
        "plddt_target": plddt[TARGET_CHAIN],
        "plddt_binder": plddt[BINDER_CHAIN],
        "seed": seed + i // num_samples,
    }


def _expected_residues(seq: str) -> list[str]:
    """One letter per residue as chai-lab will name it: the 20 standard, everything else UNK -> ``X``."""
    return [c if c in _STANDARD else "X" for c in seq.upper()]


def _ca_plddt_by_chain(cif_path: Path, target_seq: str, binder_seq: str) -> dict[str, np.ndarray]:
    """Per-residue pLDDT (0-100) of chains A and B: the B-factor of their CA atoms.

    Raises on a chain that is absent, on a CA count or residue sequence that differs from the expected
    sequence (this is also what catches a chain-order mistake at equal lengths), on any chain other than
    A and B, and on a column of zeros.
    """
    name = Path(cif_path).name
    rows = _atom_site_rows(Path(cif_path))
    extra = sorted({chain for chain, *_ in rows} - {TARGET_CHAIN, BINDER_CHAIN})
    if extra:
        raise ValueError(f"{name}: unexpected chain(s) {extra}; only the target (A) and the binder (B) were input")
    out: dict[str, np.ndarray] = {}
    for chain, role, seq in ((TARGET_CHAIN, "target", target_seq), (BINDER_CHAIN, "binder", binder_seq)):
        cas = [(comp, b) for c, atom, comp, b in rows if c == chain and atom == "CA"]
        if len(cas) != len(seq):
            raise ValueError(
                f"{name}: {role} chain {chain} has {len(cas)} CA atoms, expected {len(seq)} "
                f"(a residue without a CA, or a chain missing)"
            )
        found = [_THREE_TO_ONE.get(comp, "X") for comp, _ in cas]
        if found != _expected_residues(seq):
            raise ValueError(
                f"{name}: chain {chain} does not carry the {role} sequence (residue names differ; chain order "
                f"or tokenisation problem)"
            )
        out[chain] = np.asarray([b for _, b in cas], dtype=np.float32)
    allv = np.concatenate([out[TARGET_CHAIN], out[BINDER_CHAIN]])
    if not np.isfinite(allv).all() or float(allv.max()) <= 0.0:
        raise ValueError(f"{name}: CA B-factors are zero or non-finite; no pLDDT was written")
    return out


def _atom_site_rows(cif_path: Path) -> list[tuple[str, str, str, float]]:
    """``(chain, atom_name, residue_name, b_iso)`` for every row of the ``_atom_site`` loop of an mmCIF."""
    lines = [ln.strip() for ln in cif_path.read_text().splitlines()]
    for start, line in enumerate(lines):
        if line == "loop_" and start + 1 < len(lines) and lines[start + 1].startswith("_atom_site."):
            break
    else:
        raise ValueError(f"{cif_path.name}: no _atom_site loop found")
    i, columns = start + 1, []
    while i < len(lines) and lines[i].startswith("_atom_site."):
        columns.append(lines[i][len("_atom_site.") :])
        i += 1

    def pick(*names: str) -> int:
        for nm in names:
            if nm in columns:
                return columns.index(nm)
        raise ValueError(f"{cif_path.name}: _atom_site has none of {names}")

    idx = {
        "chain": pick("auth_asym_id", "label_asym_id"),
        "atom": pick("label_atom_id", "auth_atom_id"),
        "comp": pick("label_comp_id", "auth_comp_id"),
        "b": pick("B_iso_or_equiv"),
    }
    rows = []
    for line in lines[i:]:
        if not line or line.startswith(("#", "loop_", "_", "data_")):
            break
        parts = line.split()
        if len(parts) != len(columns):
            raise ValueError(f"{cif_path.name}: _atom_site row has {len(parts)} fields, expected {len(columns)}")
        rows.append(
            (
                parts[idx["chain"]],
                parts[idx["atom"]].strip("\"'"),
                parts[idx["comp"]].strip("\"'"),
                float(parts[idx["b"]]),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class Chai1Adapter:
    """Chai-1 (chai-lab 0.6.1) plugged into the shared driver (``binder_comparison.refolding.second_engine_driver``)."""

    name = ENGINE
    description = __doc__
    native_pae_order = NATIVE_PAE_ORDER
    target_msa_filename = MSA_FILE_NAME

    def __init__(self) -> None:
        self.model_dir: Path | None = None

    def add_args(self, parser) -> None:
        parser.add_argument(
            "--model-dir",
            default=None,
            help="Directory for Chai-1's downloaded weights (sets CHAI_DOWNLOADS_DIR for the worker). Default: "
            "chai-lab's own ($CHAI_DOWNLOADS_DIR, else <package>/downloads); missing files are downloaded. "
            "The directory must already exist.",
        )

    def configure(self, args) -> None:
        require_cleared_version(_engine_version())
        if args.model_dir:
            self.model_dir = Path(args.model_dir)
            if not self.model_dir.is_dir():
                raise FileNotFoundError(f"Chai-1 download directory not found: {self.model_dir}")

    def engine_version(self) -> str:
        return _engine_version()

    def weights_id(self) -> str:
        return WEIGHTS_ID

    def predict_one(self, *, query_id, binder_seq, target_seq, target_msa_path, work_dir, num_seeds, num_samples):
        # Looked up at call time on purpose: the model seam tests replace.
        return _predict_one(
            query_id=query_id,
            binder_seq=binder_seq,
            target_seq=target_seq,
            target_msa_path=target_msa_path,
            work_dir=work_dir,
            model_dir=self.model_dir,
            num_seeds=num_seeds,
            num_samples=num_samples,
        )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == [WORKER_FLAG]:
        _run_worker(Path(argv[1]))
        return 0
    try:
        return run_cli(Chai1Adapter(), argv)
    except UnclearedVersionError as exc:
        # Raised from configure(), before any design, file or sidecar exists.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
