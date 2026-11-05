"""Standalone batch refolder for OpenFold3 (aqlaboratory/openfold-3), a candidate AF3 replacement.

Run inside OpenFold3's own conda/pip env (``run_openfold`` importable); ``binder_comparison``
must be importable there too (``pip install -e Evaluator``).

Follows OpenFold3 release 0.5.1 (git ``795e45b``), default weights OpenBind-0
(``openbind-2025-06-30-174k``, file ``of3-ob-2025-06-30-174k.pt``). Sources read for this script:

* https://openfold-3.readthedocs.io/en/latest/inference.html  (CLI flags, output layout, the
  ``*_confidences.json`` / ``*_confidences_aggregated.json`` contents, seeds and samples)
* https://openfold-3.readthedocs.io/en/latest/input_format_reference.html  (query JSON)
* https://openfold-3.readthedocs.io/en/latest/precomputed_msa_how_to.html  (per-chain MSA files
  are picked BY FILE NAME; ``colabfold_main`` is in the default ``aln_order``)
* the 0.5.1 source: ``openfold3/run_openfold.py`` (``predict`` options),
  ``openfold3/core/runners/writer.py`` (what is written and how), ``openfold3/core/metrics/
  aggregate_confidence_ranking.py`` (shape of ``pae``), ``openfold3/entry_points/validator.py``
  (``--num-model-seeds`` and seed 42), ``openfold3/entry_points/parameters.py`` (checkpoint names).
  The docs page quoted above still names an older default checkpoint (``openfold3_p2_v1``); the
  0.5.1 registry and ``DEFAULT_CHECKPOINT_NAME`` say ``openbind-2025-06-30-174k``, so that name is
  passed explicitly here and recorded as ``weights_id``.

What was established about the PAE (this is what the whole script rests on):

* ``confidences.json["pae"]`` is **token-level**, ``[N_token, N_token]``: it is
  ``probs_to_expected_error(softmax(pae_logits))`` and ``pae_logits`` is documented
  ``[*, N_token, N_token, 64]``. For a protein-protein complex of canonical residues there is one
  token per residue, so the matrix is ``(n_chain1 + n_chain2)`` square. (``plddt`` in the same file
  is per ATOM, which is why pLDDT is read from the CA atoms of the structure instead.) No
  atom-to-residue reduction is therefore needed; a non-canonical residue or a ligand would make
  the token count differ from the sequence lengths, and ``to_binder_target_pae`` refuses that.
* Row/column order is **the order of the chains in the query**: ``inference.py`` documents that
  the AtomArray "follows the chain IDs given in the Query object", and tokens follow the atoms.
  The query written here lists the TARGET first (chain A) and the binder second (chain B), so the
  native order is ``[target | binder]`` and ``order="target_binder"`` is passed to
  ``to_binder_target_pae``, exactly as for AF3.

pLDDT is per-atom 0-100 in OpenFold3 (also stored in the B-factor column of ``*_model.cif``) and is
rescaled to 0-1 here so it is comparable across engines. The top sample (over all seeds and
samples) is the one with the highest ``sample_ranking_score``, as AF3's is by ``ranking_score``.

Target MSA: fetched once through ``binder_comparison.refolding.target_msa.prepare_target_msa``
(ColabFold + shared on-disk cache), written to ``colabfold_main.a3m`` and handed to the target
chain as ``main_msa_file_paths``. The binder gets a one-sequence ``colabfold_main.a3m``, i.e. no
MSA. ``--use-msa-server false`` and ``--use-templates false`` are always passed: nothing is
queried online by OpenFold3 itself.

Emits the same unprefixed CSV as ``refold_af3.py``; the engine name enters at merge time
(``add_iptm_from_pae_files(prefix="openfold3")``). Sidecars in the output dir:
``target_msa_mode.json`` and ``refold_run_info.json``.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import numpy as np
from binder_comparison.refolding.second_engine_driver import EngineError, run_cli

ENGINE = "openfold3"
#: Registry name in openfold3/entry_points/parameters.py at 0.5.1 (== DEFAULT_CHECKPOINT_NAME).
DEFAULT_CKPT_NAME = "openbind-2025-06-30-174k"
TARGET_CHAIN, BINDER_CHAIN = "A", "B"
#: Chains are listed target-first in the query, so the PAE rows/columns are [target | binder].
NATIVE_PAE_ORDER = "target_binder"
#: OpenFold3 chooses an alignment by file name; this one is in its default ``aln_order``.
MSA_FILE_NAME = "colabfold_main.a3m"
DEFAULT_SEED = 42  # openfold3 InferenceExperimentSettings.seeds default


# ---------------------------------------------------------------------------
# Query construction and the model call (the one seam the tests replace)
# ---------------------------------------------------------------------------


def build_query(binder_seq: str, target_seq: str, *, msa_dir: Path, target_msa_path: Path | None) -> dict:
    """One OpenFold3 query: TARGET first (chain A), binder second (chain B).

    With a target MSA, both chains get ``main_msa_file_paths``; the binder's file holds only its
    own sequence (no MSA for a de novo binder). Without one the query is ``use_msas: false``.
    """
    chains = [
        {"molecule_type": "protein", "chain_ids": TARGET_CHAIN, "sequence": target_seq},
        {"molecule_type": "protein", "chain_ids": BINDER_CHAIN, "sequence": binder_seq},
    ]
    query: dict = {"chains": chains, "use_msas": target_msa_path is not None}
    if target_msa_path is not None:
        target_msa_path = Path(target_msa_path)
        if target_msa_path.name != MSA_FILE_NAME:
            raise ValueError(
                f"target MSA file must be named {MSA_FILE_NAME} (OpenFold3 selects alignments by file name), "
                f"got {target_msa_path.name}"
            )
        binder_msa = Path(msa_dir) / "binder" / MSA_FILE_NAME
        binder_msa.parent.mkdir(parents=True, exist_ok=True)
        binder_msa.write_text(f">query\n{binder_seq}\n")
        chains[0]["main_msa_file_paths"] = str(target_msa_path)
        chains[1]["main_msa_file_paths"] = str(binder_msa)
        # The binder has no MSA, so there is nothing to pair across chains.
        query["use_paired_msas"] = False
    return query


def _predict_one(
    *,
    query_id: str,
    binder_seq: str,
    target_seq: str,
    target_msa_path: Path | None,
    work_dir: Path,
    ckpt_path: Path | None,
    ckpt_name: str,
    num_seeds: int,
    num_samples: int,
) -> dict:
    """Run OpenFold3 on one binder-target pair; return the top sample.

    THE MODEL SEAM: tests replace this function. It returns a dict with ``pae`` (token-level,
    native chain order: target then binder), ``summary`` (``iptm``, ``ptm``,
    ``sample_ranking_score``), ``cif`` (path), ``plddt_target`` / ``plddt_binder`` (per residue,
    0-100) and ``seed``. Raises if the model produced nothing.
    """
    work_dir = Path(work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)  # never pick up samples of an earlier, partly failed attempt
    work_dir.mkdir(parents=True)
    query = build_query(binder_seq, target_seq, msa_dir=work_dir / "msa", target_msa_path=target_msa_path)
    query_json = work_dir / "query.json"
    query_json.write_text(json.dumps({"queries": {query_id: query}}, indent=2))
    output_dir = work_dir / "output"

    cmd = [
        sys.executable,
        "-m",
        "openfold3.run_openfold",
        "predict",
        "--query-json",
        str(query_json),
        "--output-dir",
        str(output_dir),
        "--use-msa-server",
        "false",
        "--use-templates",
        "false",
        "--num-diffusion-samples",
        str(num_samples),
    ]
    if ckpt_path is not None:
        cmd += ["--inference-ckpt-path", str(ckpt_path)]
    else:
        cmd += ["--inference-ckpt-name", ckpt_name]
    if num_seeds > 1:
        # With exactly one seed leave the flag out: --num-model-seeds 1 replaces seed 42 by a
        # derived random one (validator.generate_seeds), the plain default keeps 42.
        cmd += ["--num-model-seeds", str(num_seeds)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [openfold3] STDERR: {result.stderr[-4000:]}" if result.stderr else "  [openfold3] No stderr")
        raise EngineError(f"OpenFold3 exited with code {result.returncode}", result.stderr)

    top = _load_top_sample(output_dir, query_id)
    if top is None:
        # run_openfold's writer logs a failed query and carries on, so rc == 0 with no files happens.
        print(f"  [openfold3] STDERR: {result.stderr[-4000:]}" if result.stderr else "  [openfold3] No stderr")
        raise EngineError(
            f"OpenFold3 produced no prediction for {query_id} (exit code 0, no output files)", result.stderr
        )
    return top


def _load_top_sample(output_dir: Path, query_id: str) -> dict | None:
    """Locate and load the sample with the highest ``sample_ranking_score``.

    Layout (inference docs): ``<output_dir>/<query_id>/seed_<n>/<query_id>_seed_<n>_sample_<k>_*``
    with ``_model.cif``, ``_confidences.json`` and ``_confidences_aggregated.json``.
    """
    best = None
    for agg_fp in sorted(
        Path(output_dir).glob(f"{query_id}/seed_*/{query_id}_seed_*_sample_*_confidences_aggregated.json")
    ):
        prefix = str(agg_fp)[: -len("_confidences_aggregated.json")]
        conf_fp, cif_fp = Path(f"{prefix}_confidences.json"), Path(f"{prefix}_model.cif")
        if not (conf_fp.is_file() and cif_fp.is_file()):
            continue
        try:
            summary = json.loads(agg_fp.read_text())
            score = float(summary["sample_ranking_score"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"  [openfold3] Unreadable summary {agg_fp.name}: {exc}")
            continue
        if not math.isfinite(score):
            print(f"  [openfold3] Ignoring {agg_fp.name}: non-finite sample_ranking_score ({score})")
            continue
        if best is None or score > best[0]:
            best = (score, summary, conf_fp, cif_fp, agg_fp.parent.name)
    if best is None:
        return None

    _, summary, conf_fp, cif_fp, seed_dir = best
    pae = np.asarray(json.loads(conf_fp.read_text())["pae"], dtype=np.float32)
    plddt = _ca_plddt_by_chain(cif_fp)
    return {
        "pae": pae,
        "summary": summary,
        "cif": cif_fp,
        "plddt_target": plddt[TARGET_CHAIN],
        "plddt_binder": plddt[BINDER_CHAIN],
        "seed": int(seed_dir.removeprefix("seed_")),
    }


def _ca_plddt_by_chain(cif_path: Path) -> dict[str, np.ndarray]:
    """Per-residue pLDDT (0-100) of each chain: the B-factor of its CA atoms.

    ``confidences.json["plddt"]`` is per atom; the writer also stores it in the B-factor column,
    which keeps the atom order consistent with the structure we report on.
    """
    import gemmi  # OpenFold3's env has it; imported here so the module loads without it

    model = gemmi.read_structure(str(cif_path))[0]
    out: dict[str, np.ndarray] = {}
    for chain in model:
        vals = [atom.b_iso for residue in chain for atom in residue if atom.name == "CA"]
        out[chain.name] = np.asarray(vals, dtype=np.float32)
    missing = {TARGET_CHAIN, BINDER_CHAIN} - set(out)
    if missing:
        raise ValueError(f"{cif_path.name} has chains {sorted(out)}, expected {TARGET_CHAIN} and {BINDER_CHAIN}")
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _resolve_checkpoint(model_dir: str | None, ckpt_name: str) -> tuple[Path | None, str]:
    """``(ckpt_path or None, weights_id)``. ``model_dir`` is a ``.pt`` file or a directory with exactly one."""
    if not model_dir:
        return None, ckpt_name
    p = Path(model_dir)
    if p.is_dir():
        found = sorted(p.glob("*.pt"))
        if len(found) != 1:
            raise FileNotFoundError(f"expected exactly one .pt checkpoint in {p}, found {len(found)}")
        p = found[0]
    if not p.is_file():
        raise FileNotFoundError(f"OpenFold3 checkpoint not found: {p}")
    return p, p.stem


def _engine_version() -> str:
    try:
        return metadata.version("openfold3")
    except metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class OpenFold3Adapter:
    """OpenFold3 plugged into the shared driver (``binder_comparison.refolding.second_engine_driver``)."""

    name = ENGINE
    description = __doc__
    native_pae_order = NATIVE_PAE_ORDER
    target_msa_filename = MSA_FILE_NAME

    def __init__(self) -> None:
        self.ckpt_path: Path | None = None
        self.ckpt_name = DEFAULT_CKPT_NAME
        self._weights_id = DEFAULT_CKPT_NAME

    def add_args(self, parser) -> None:
        parser.add_argument(
            "--model-dir",
            default=None,
            help="OpenFold3 checkpoint: a .pt file, or a directory holding exactly one. "
            "Default: --ckpt-name from $OPENFOLD_CACHE",
        )
        parser.add_argument(
            "--ckpt-name", default=DEFAULT_CKPT_NAME, help="Registry name of the checkpoint (default OpenBind-0)"
        )

    def configure(self, args) -> None:
        self.ckpt_name = args.ckpt_name
        self.ckpt_path, self._weights_id = _resolve_checkpoint(args.model_dir, args.ckpt_name)

    def engine_version(self) -> str:
        return _engine_version()

    def weights_id(self) -> str:
        return self._weights_id

    def predict_one(self, *, query_id, binder_seq, target_seq, target_msa_path, work_dir, num_seeds, num_samples):
        # Looked up at call time on purpose: the model seam tests replace.
        return _predict_one(
            query_id=query_id,
            binder_seq=binder_seq,
            target_seq=target_seq,
            target_msa_path=target_msa_path,
            work_dir=work_dir,
            ckpt_path=self.ckpt_path,
            ckpt_name=self.ckpt_name,
            num_seeds=num_seeds,
            num_samples=num_samples,
        )


def main(argv: list[str] | None = None) -> int:
    return run_cli(OpenFold3Adapter(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
