"""Standalone batch refolder for Protenix v1.x (bytedance/Protenix), a candidate AF3 replacement.

Run inside Protenix's own env (the ``protenix`` console script importable/installed);
``binder_comparison`` must be importable there too (``pip install -e Evaluator``).

Follows Protenix tag ``v1.1.0`` (``4f1eedf``, package ``protenix`` 1.1.0). Sources read for this
script (all at that tag):

* https://github.com/bytedance/Protenix/blob/v1.1.0/README.md  (model table, ``protenix pred``)
* https://github.com/bytedance/Protenix/blob/v1.1.0/docs/infer_json_format.md  (input JSON,
  ``unpairedMsaPath`` / ``pairedMsaPath``, optional chain ``id``, output file descriptions)
* https://github.com/bytedance/Protenix/blob/v1.1.0/docs/training_inference_instructions.md
  (``protenix pred`` flags; inference cost table: 500 tokens ~6 GB / 17 s, 1000 tokens ~18 GB / 59 s)
* ``runner/batch_inference.py`` (the ``pred`` options, ``preprocess_input``, the supported model
  names), ``runner/msa_search.py`` (``need_msa_search``), ``runner/inference.py`` (output loop,
  error handling), ``runner/dumper.py`` (what is written and where), ``protenix/model/
  sample_confidence.py`` (``token_pair_pae``, ranking score), ``protenix/data/inference/
  json_to_feature.py`` (chain ids, entity order), ``protenix/data/msa/msa_featurizer.py`` (how the
  MSA files are read) and ``configs/configs_inference.py`` (defaults, ``PROTENIX_ROOT_DIR``).

LICENCE PIN (Evaluator/docs/second_engine_licences.md): only the v1.x checkpoints are covered
(Apache-2.0 code and parameters at v1.1.0). The ``main`` README states that the Protenix-v2 weights
are proprietary, so this adapter runs ONLY the checkpoint names in ``LICENSED_MODELS`` and refuses
``protenix-v2`` and everything else before any work starts. The default is
``protenix_base_default_v1.0.0`` (the licence record's model); the model name is recorded as
``weights_id`` and the package version as ``engine_version``.

What was established (this is what the whole script rests on):

* Invocation: ``protenix pred -i input.json -o <dir> -s <seeds> -e <samples> -n <model> --use_msa
  <bool> --use_default_params true --need_atom_confidence true``. ``--use_default_params true`` sets
  10 cycles / 200 diffusion steps for the two v1 base models and raises for an unknown model name.
  ``--need_atom_confidence true`` is required: without it no ``*_full_data_sample_*.json`` is
  written and the PAE is not saved anywhere (the summary JSON holds scalars only).
* Input: a top-level JSON LIST of jobs ``{"name", "sequences": [{"proteinChain": {"sequence",
  "count", "id": [...], "unpairedMsaPath"}}, ...]}``. Chains are built in the order of
  ``sequences``; the explicit ``id`` fixes the chain names. Here: target = entity 1 (chain A),
  binder = entity 2 (chain B).
* MSA: ``unpairedMsaPath`` takes a standard a3m whose FIRST row is the query. The target gets the
  shared ColabFold a3m (``get_target_msa``). The binder gets a one-sequence a3m of its own, i.e. no
  MSA. This file is NOT optional: ``need_msa_search`` is true as soon as ANY protein chain has
  neither path, and ``update_seq_msa`` then queries the MSA server for EVERY protein chain and
  overwrites the paths. With no target MSA at all the run uses ``--use_msa false`` instead.
* Output (the docs say ``<name>/<seed>/``; the source writes ``seed_<seed>/predictions/``)::

      <out>/<name>/seed_<seed>/predictions/<name>_sample_<rank>.cif
      <out>/<name>/seed_<seed>/predictions/<name>_summary_confidence_sample_<rank>.json
      <out>/<name>/seed_<seed>/predictions/<name>_full_data_sample_<rank>.json   (needs the flag)
      <out>/<name>/seed_<seed>/predictions/<name>_sample_<rank>_wounresol.cif    (only if the atom
                                                                       array has ``is_resolved``)

  ``<rank>`` is the sample's rank by ``ranking_score`` WITHIN its seed (0 = best); this script
  nevertheless compares ``ranking_score`` across every seed and sample. The ``_wounresol.cif`` copy
  matches a naive ``*_sample_*.cif`` glob and is excluded.
* PAE: ``full_data["token_pair_pae"]`` is ``[N_token, N_token]`` (the expected value of the
  binned PAE logits, rounded to 2 decimals in the JSON). It is TOKEN-level: for canonical protein
  residues one token per residue, so no atom reduction is needed; a non-standard residue or a ligand
  would change the token count and is refused. Tokens follow the atom array, which follows the
  entity order of the input, so the native order is ``[target | binder]`` and
  ``order="target_binder"`` is passed to ``to_binder_target_pae``. The same file carries
  ``token_asym_id`` ([N_token], shared across samples); it is used to CHECK that the first
  ``len(target)`` tokens are one chain and the next ``len(binder)`` another, so an order mistake
  cannot pass on sizes alone.
* pLDDT: ``full_data["atom_plddt"]`` is per ATOM (0-1, rounded to 0.01). The per-residue value used
  here is the B-factor of the CA atoms of the top sample's ``.cif`` (the dumper writes
  ``atom_plddt * 100`` there, 0-100; the driver rescales to 0-1), the same convention as the
  OpenFold3 adapter. The CIF is read with a small stdlib reader of its ``_atom_site`` loop (the
  Protenix env has biotite, not necessarily gemmi). A missing CA, a chain of the wrong length, or
  all-zero B-factors (the column absent) fails the design loudly.
* Top sample: the highest ``ranking_score`` (= 0.8 iptm + 0.2 ptm + 0.5 disorder - 100 has_clash)
  over all seeds and samples; non-finite scores are skipped.
* Failure mode: ``inference.py`` catches a failed sample, writes ``<out>/ERR/<name>.txt`` and the
  CLI still exits 0. An exit 0 with no sample files is therefore a FAILED design, and the ERR file
  text is attached to the error.
* Weights and data: the checkpoint ``<PROTENIX_ROOT_DIR>/checkpoint/<model>.pt`` and the CCD data
  under the same root are downloaded on first use when missing (default root: ``$HOME``).
  ``--model-dir`` sets ``PROTENIX_ROOT_DIR`` for the subprocess.

Host switches (live smoke on aarch64/GB10, sm_121): ``--trimul-kernel torch --triatt-kernel torch`` are
REQUIRED there (the default cuequivariance kernels abort in Triton's LLVM: 'sm_121a' is not recognised);
``--layernorm-type torch`` exports LAYERNORM_TYPE=torch, which avoids the import-time CUDA extension build
that needs nvcc and ninja. The values used are recorded in ``refold_run_info.json`` under ``settings``.

Emits the same unprefixed CSV as ``refold_af3.py``; the engine name enters at merge time
(``add_iptm_from_pae_files(prefix="protenix")``). Sidecars in the output dir:
``target_msa_mode.json`` and ``refold_run_info.json``.
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
from binder_comparison.refolding.second_engine_driver import EngineError, run_cli

ENGINE = "protenix"
#: The checkpoints the licence record covers (Apache-2.0 code and parameters, v1.x only). Exact match.
LICENSED_MODELS = ("protenix_base_default_v1.0.0", "protenix_base_20250630_v1.0.0")
DEFAULT_MODEL = "protenix_base_default_v1.0.0"
TARGET_CHAIN, BINDER_CHAIN = "A", "B"
#: Entities are listed target-first, so the PAE rows/columns are [target | binder].
NATIVE_PAE_ORDER = "target_binder"
MSA_FILE_NAME = "non_pairing.a3m"
DEFAULT_SEED = 101  # `protenix pred -s` default
#: Values `protenix pred` accepts (v1.1.0 configs_inference.py). The cuequivariance kernels abort on
#: aarch64 / sm_121 (LLVM: 'sm_121a' not recognised), where `torch` works.
TRIMUL_KERNELS = ("cuequivariance", "torch")
TRIATT_KERNELS = ("triattention", "cuequivariance", "deepspeed", "torch")
#: LAYERNORM_TYPE is read at import by protenix/model/triangular/layers.py; the default builds a CUDA
#: extension at import (needs nvcc and ninja), `torch` does not.
LAYERNORM_TYPES = ("fast_layernorm", "torch")


class UnlicensedModelError(ValueError):
    """The requested checkpoint is not one the licence record covers."""


def require_licensed_model(name: str) -> str:
    """Return ``name`` if it is on the allow-list; otherwise refuse, saying why."""
    if name in LICENSED_MODELS:
        return name
    raise UnlicensedModelError(
        f"refusing Protenix model {name!r}: only {', '.join(LICENSED_MODELS)} are cleared for use "
        f"(Apache-2.0 parameters, v1.x; Evaluator/docs/second_engine_licences.md). The Protenix-v2 "
        f"weights are described by the upstream README as proprietary and confidential, and no other name "
        f"has been checked against the licence."
    )


# ---------------------------------------------------------------------------
# Input construction and the model call (the one seam the tests replace)
# ---------------------------------------------------------------------------


def build_input(
    query_id: str, binder_seq: str, target_seq: str, *, msa_dir: Path, target_msa_path: Path | None
) -> list[dict]:
    """The Protenix input JSON: a one-job list, TARGET first (chain A), binder second (chain B).

    With a target MSA BOTH chains carry an ``unpairedMsaPath`` (the binder's file holds only its own
    sequence, i.e. no MSA): a chain with no path at all makes Protenix search an MSA server for every
    chain. Without a target MSA no path is given and the run is started with ``--use_msa false``.
    """
    target = {"sequence": target_seq, "count": 1, "id": [TARGET_CHAIN]}
    binder = {"sequence": binder_seq, "count": 1, "id": [BINDER_CHAIN]}
    if target_msa_path is not None:
        binder_msa = Path(msa_dir).absolute() / "binder" / MSA_FILE_NAME
        binder_msa.parent.mkdir(parents=True, exist_ok=True)
        binder_msa.write_text(f">query\n{binder_seq}\n")
        target["unpairedMsaPath"] = str(Path(target_msa_path).absolute())
        binder["unpairedMsaPath"] = str(binder_msa)
    return [{"name": query_id, "sequences": [{"proteinChain": target}, {"proteinChain": binder}]}]


def _protenix_executable() -> str:
    sibling = Path(sys.executable).parent / "protenix"
    return str(sibling) if sibling.exists() else (shutil.which("protenix") or "protenix")


def _predict_one(
    *,
    query_id: str,
    binder_seq: str,
    target_seq: str,
    target_msa_path: Path | None,
    work_dir: Path,
    model_name: str,
    model_dir: Path | None,
    num_seeds: int,
    num_samples: int,
    trimul_kernel: str | None = None,
    triatt_kernel: str | None = None,
    layernorm_type: str | None = None,
) -> dict:
    """Run Protenix on one binder-target pair; return the top sample.

    THE MODEL SEAM: tests replace this function. It returns a dict with ``pae`` (token-level,
    native chain order: target then binder), ``summary`` (``iptm``, ``ptm``, ``sample_ranking_score``),
    ``cif`` (path), ``plddt_target`` / ``plddt_binder`` (per residue, 0-100) and ``seed``. Raises if
    the model produced nothing.
    """
    require_licensed_model(model_name)  # also here, so no caller can reach the model around configure()
    work_dir = Path(work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)  # never pick up samples of an earlier, partly failed attempt
    work_dir.mkdir(parents=True)
    doc = build_input(query_id, binder_seq, target_seq, msa_dir=work_dir / "msa", target_msa_path=target_msa_path)
    input_json = work_dir / "input.json"
    input_json.write_text(json.dumps(doc, indent=2))
    output_dir = work_dir / "output"
    seeds = ",".join(str(DEFAULT_SEED + i) for i in range(num_seeds))

    cmd = [
        _protenix_executable(),
        "pred",
        "-i",
        str(input_json),
        "-o",
        str(output_dir),
        "-s",
        seeds,
        "-e",
        str(num_samples),
        "-n",
        model_name,
        "--use_msa",
        "true" if target_msa_path is not None else "false",
        "--use_default_params",
        "true",
        "--need_atom_confidence",
        "true",
    ]
    if trimul_kernel:
        cmd += ["--trimul_kernel", trimul_kernel]
    if triatt_kernel:
        cmd += ["--triatt_kernel", triatt_kernel]
    env = dict(os.environ)
    if model_dir is not None:
        env["PROTENIX_ROOT_DIR"] = str(model_dir)
    if layernorm_type:
        env["LAYERNORM_TYPE"] = layernorm_type

    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env)
    if result.returncode != 0:
        print(f"  [protenix] STDERR: {result.stderr[-4000:]}" if result.stderr else "  [protenix] No stderr")
        raise EngineError(f"Protenix exited with code {result.returncode}", result.stderr or "")

    top = _load_top_sample(output_dir, query_id, len(target_seq), len(binder_seq))
    if top is None:
        # inference.py logs a failed sample to <out>/ERR/<name>.txt and the CLI still exits 0.
        err_text = "\n".join(p.read_text(errors="replace") for p in sorted((output_dir / "ERR").glob("*.txt")))
        stderr = "\n".join(s for s in (result.stderr or "", err_text) if s)
        print(f"  [protenix] STDERR: {stderr[-4000:]}" if stderr else "  [protenix] No stderr")
        raise EngineError(f"Protenix produced no prediction for {query_id} (exit code 0, no output files)", stderr)
    return top


def _scalar(value, what: str) -> float:
    arr = np.asarray(value, dtype=float).reshape(-1)
    if arr.size != 1:
        raise ValueError(f"expected one number for {what}, got {value!r}")
    return float(arr[0])


def _load_top_sample(output_dir: Path, query_id: str, n_target: int, n_binder: int) -> dict | None:
    """Locate and load the sample with the highest ``ranking_score`` over all seeds and samples.

    Layout (``runner/dumper.py``): ``<output_dir>/<query_id>/seed_<n>/predictions/`` holding
    ``<query_id>_summary_confidence_sample_<k>.json``, ``<query_id>_full_data_sample_<k>.json`` and
    ``<query_id>_sample_<k>.cif``. A sample missing its structure or its full-data (PAE) file is
    not a candidate.
    """
    best = None
    for summary_fp in sorted(
        Path(output_dir).glob(f"{query_id}/seed_*/predictions/{query_id}_summary_confidence_sample_*.json")
    ):
        match = re.search(r"_summary_confidence_sample_(\d+)\.json$", summary_fp.name)
        if match is None:
            continue
        pred_dir, rank = summary_fp.parent, match.group(1)
        cif_fp = pred_dir / f"{query_id}_sample_{rank}.cif"
        full_fp = pred_dir / f"{query_id}_full_data_sample_{rank}.json"
        if not (cif_fp.is_file() and full_fp.is_file()):
            continue
        try:
            summary = json.loads(summary_fp.read_text())
            score = _scalar(summary["ranking_score"], "ranking_score")
        except (OSError, ValueError, KeyError) as exc:
            print(f"  [protenix] Unreadable summary {summary_fp.name}: {exc}")
            continue
        if not math.isfinite(score):
            print(f"  [protenix] Ignoring {summary_fp.name}: non-finite ranking_score ({score})")
            continue
        if best is None or score > best[0]:
            best = (score, summary, full_fp, cif_fp, pred_dir.parent.name)
    if best is None:
        return None

    score, summary, full_fp, cif_fp, seed_dir = best
    full = json.loads(full_fp.read_text())
    pae = np.asarray(full["token_pair_pae"], dtype=np.float32)
    _check_token_order(full.get("token_asym_id"), pae, n_target, n_binder)
    plddt = _ca_plddt_by_chain(cif_fp, n_target, n_binder)
    return {
        "pae": pae,
        "summary": {
            "iptm": _scalar(summary["iptm"], "iptm"),
            "ptm": _scalar(summary["ptm"], "ptm"),
            "sample_ranking_score": score,
        },
        "cif": cif_fp,
        "plddt_target": plddt[TARGET_CHAIN],
        "plddt_binder": plddt[BINDER_CHAIN],
        "seed": int(seed_dir.removeprefix("seed_")),
    }


def _check_token_order(token_asym_id, pae: np.ndarray, n_target: int, n_binder: int) -> None:
    """Refuse a PAE whose tokens are not ``n_target`` target tokens then ``n_binder`` binder tokens.

    The driver can only check the total size; this checks the chain order and the one-token-per-
    residue assumption using the ``token_asym_id`` Protenix saves beside the PAE.
    """
    if token_asym_id is None:
        raise ValueError("full_data has no token_asym_id, so the PAE chain order cannot be verified")
    asym = np.asarray(token_asym_id).reshape(-1)
    n = n_target + n_binder
    if asym.size != n or pae.shape != (n, n):
        raise ValueError(
            f"Protenix returned {asym.size} tokens (PAE {pae.shape}) for {n_target} target + {n_binder} binder "
            f"residues; the PAE is residue-indexed only for canonical protein residues (non-standard residue "
            f"or ligand token?)"
        )
    first, second = np.unique(asym[:n_target]), np.unique(asym[n_target:])
    # asym ids are numbered in entity order, so the target's id must be the smaller one.
    if len(first) != 1 or len(second) != 1 or not first[0] < second[0]:
        raise ValueError(
            f"PAE tokens are not target-first: token_asym_id over the first {n_target} tokens is "
            f"{first.tolist()} and over the next {n_binder} is {second.tolist()}"
        )


def _ca_plddt_by_chain(cif_path: Path, n_target: int, n_binder: int) -> dict[str, np.ndarray]:
    """Per-residue pLDDT (0-100) of chains A and B: the B-factor of their CA atoms.

    ``atom_plddt`` is per atom; the dumper stores it x100 in the B-factor column. Raises on a chain
    that is absent or has not exactly the expected number of CA atoms, and on a column of zeros.
    """
    by_chain: dict[str, list[float]] = {}
    for chain, atom, b_iso in _atom_site_rows(Path(cif_path)):
        if atom == "CA":
            by_chain.setdefault(chain, []).append(b_iso)
    out: dict[str, np.ndarray] = {}
    for chain, role, expected in ((TARGET_CHAIN, "target", n_target), (BINDER_CHAIN, "binder", n_binder)):
        vals = by_chain.get(chain, [])
        if len(vals) != expected:
            raise ValueError(
                f"{Path(cif_path).name}: {role} chain {chain} has {len(vals)} CA atoms, expected {expected} "
                f"(a residue without a CA, or a chain missing)"
            )
        out[chain] = np.asarray(vals, dtype=np.float32)
    allv = np.concatenate([out[TARGET_CHAIN], out[BINDER_CHAIN]])
    if not np.isfinite(allv).all() or float(allv.max()) <= 0.0:
        raise ValueError(f"{Path(cif_path).name}: CA B-factors are zero or non-finite; no pLDDT was written")
    return out


def _atom_site_rows(cif_path: Path) -> list[tuple[str, str, float]]:
    """``(chain, atom_name, b_iso)`` for every row of the ``_atom_site`` loop of an mmCIF."""
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
    idx = _column_indices(columns, cif_path)
    rows = []
    for line in lines[i:]:
        if not line or line.startswith(("#", "loop_", "_", "data_")):
            break
        parts = line.split()
        if len(parts) != len(columns):
            raise ValueError(f"{cif_path.name}: _atom_site row has {len(parts)} fields, expected {len(columns)}")
        rows.append((parts[idx["chain"]], parts[idx["atom"]].strip("\"'"), float(parts[idx["b"]])))
    return rows


def _column_indices(columns: list[str], cif_path: Path) -> dict[str, int]:
    def pick(*names: str) -> int:
        for name in names:
            if name in columns:
                return columns.index(name)
        raise ValueError(f"{cif_path.name}: _atom_site has none of {names}")

    return {
        "chain": pick("auth_asym_id", "label_asym_id"),
        "atom": pick("label_atom_id", "auth_atom_id"),
        "b": pick("B_iso_or_equiv"),
    }


def _engine_version() -> str:
    try:
        return metadata.version("protenix")
    except metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class ProtenixAdapter:
    """Protenix v1.x plugged into the shared driver (``binder_comparison.refolding.second_engine_driver``)."""

    name = ENGINE
    description = __doc__
    native_pae_order = NATIVE_PAE_ORDER
    target_msa_filename = MSA_FILE_NAME

    def __init__(self) -> None:
        self.model_name = DEFAULT_MODEL
        self.model_dir: Path | None = None
        self.trimul_kernel: str | None = None
        self.triatt_kernel: str | None = None
        self.layernorm_type: str | None = None

    def add_args(self, parser) -> None:
        parser.add_argument(
            "--model-name",
            default=DEFAULT_MODEL,
            help=f"Protenix checkpoint; only {', '.join(LICENSED_MODELS)} are accepted (default {DEFAULT_MODEL}). "
            "protenix-v2 is refused: its weights are proprietary.",
        )
        parser.add_argument(
            "--model-dir",
            default=None,
            help="Protenix data root (sets PROTENIX_ROOT_DIR): holds checkpoint/<model>.pt and common/. "
            "Default: Protenix's own ($PROTENIX_ROOT_DIR, else $HOME); missing files are downloaded.",
        )
        parser.add_argument(
            "--trimul-kernel",
            default=None,
            choices=TRIMUL_KERNELS,
            help="Pass --trimul_kernel through. REQUIRED as `torch` on aarch64/GB10, where the default "
            "cuequivariance kernels abort with an LLVM sm_121a error.",
        )
        parser.add_argument(
            "--triatt-kernel",
            default=None,
            choices=TRIATT_KERNELS,
            help="Pass --triatt_kernel through (`torch` on aarch64/GB10, see --trimul-kernel).",
        )
        parser.add_argument(
            "--layernorm-type",
            default=None,
            choices=LAYERNORM_TYPES,
            help="Export LAYERNORM_TYPE to the engine. `torch` avoids the import-time CUDA extension build "
            "(needs nvcc and ninja). Default: pass nothing.",
        )

    def configure(self, args) -> None:
        self.model_name = require_licensed_model(args.model_name)
        if args.model_dir:
            self.model_dir = Path(args.model_dir)
            if not self.model_dir.is_dir():
                raise FileNotFoundError(f"Protenix data root not found: {self.model_dir}")
        self.trimul_kernel, self.triatt_kernel = args.trimul_kernel, args.triatt_kernel
        self.layernorm_type = args.layernorm_type

    def engine_version(self) -> str:
        return _engine_version()

    def weights_id(self) -> str:
        return self.model_name

    def run_info_extra(self) -> dict:
        """The non-default settings a result must be tied to; ``default`` = nothing was passed."""
        return {
            "trimul_kernel": self.trimul_kernel or "default",
            "triatt_kernel": self.triatt_kernel or "default",
            # An inherited LAYERNORM_TYPE reaches the subprocess too, so it is what was actually used.
            "layernorm_type": self.layernorm_type or os.environ.get("LAYERNORM_TYPE") or "default",
        }

    def predict_one(self, *, query_id, binder_seq, target_seq, target_msa_path, work_dir, num_seeds, num_samples):
        # Looked up at call time on purpose: the model seam tests replace.
        return _predict_one(
            query_id=query_id,
            binder_seq=binder_seq,
            target_seq=target_seq,
            target_msa_path=target_msa_path,
            work_dir=work_dir,
            model_name=self.model_name,
            model_dir=self.model_dir,
            num_seeds=num_seeds,
            num_samples=num_samples,
            trimul_kernel=self.trimul_kernel,
            triatt_kernel=self.triatt_kernel,
            layernorm_type=self.layernorm_type,
        )


def main(argv: list[str] | None = None) -> int:
    try:
        return run_cli(ProtenixAdapter(), argv)
    except UnlicensedModelError as exc:
        # Raised from configure(), before any design, file or sidecar exists.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
