"""Standalone batch refolder for RF3 (RoseTTAFold3, RosettaCommons Foundry), a candidate AF3 replacement.

Run with the Foundry environment's ``rf3`` console script reachable (next to this interpreter or on PATH);
``binder_comparison`` must be importable here too (``pip install -e Evaluator``). Nothing of Foundry is
imported by this script: it drives the ``rf3`` executable and reads the files it writes.

Follows RosettaCommons/foundry, read at three points (all three agree on everything below unless noted):
tag ``v0.1.9`` (``a36d29c``, what ``install/install.sh`` pins for RFD3), tag ``v0.2.0`` (``3967144``) and the
default branch ``production`` (``0d0b0ba``). Sources read:

* https://github.com/RosettaCommons/foundry/blob/production/models/rf3/README.md  (``rf3 fold``, the JSON
  input, MSAs, arguments, outputs, checkpoints)
* ``models/rf3/src/rf3/cli.py`` + ``inference.py`` (Hydra entry point; ``rf3 fold k=v ...``),
  ``models/rf3/configs/inference_engine/{rf3,base}.yaml`` (every key this script passes exists at all three
  points), ``inference_engines/rf3.py`` (what is written and where, ``RF3Output.dump``,
  ``compute_ranking_score``, early stopping), ``utils/predicted_error.py``
  (``compile_af3_style_confidence_outputs``: the ``confidences`` dict), ``utils/inference.py`` (the JSON
  input, ``InferenceInput.from_json_dict``), ``metrics/predicted_error.py`` (``ComputeIPTM``),
  ``loss/af3_confidence_loss.py`` + ``configs/trainer/loss/losses/confidence_loss.yaml`` (bins, scales) and the
  checkpoint registry (``checkpoints.py`` on ``production``; ``foundry/inference_engines/checkpoint_registry.py``
  at the tags).
* AtomWorks 2.2.0, the library RF3 builds its input and MSAs with: ``io/tools/inference.py``
  (``components_to_atom_array``, chain order) and ``ml/transforms/msa/msa.py`` (``load_polymer_msas``).
* https://github.com/RosettaCommons/foundry/issues/198  (hardware, below).

LICENCE PIN (Evaluator/docs/second_engine_licences.md, RF3 row). The code is BSD-3-Clause. The sentence that
extends it to the weights ("This copyright and license covers both the source code and model weights
referenced for download in the README file.") exists only on the ``production`` branch (commit ``69d5f73``);
it is absent from the ``v0.2.0`` tag and the PyPI sdist, and ``install/install.sh`` pins ``rc-foundry==0.1.9``
from PyPI, older still. So this adapter does two things: it runs ONLY the allow-listed checkpoint file
(``LICENSED_CHECKPOINTS``; anything else, also a symlink that resolves to another file, is refused before any
work starts), and it RECORDS rather than assumes: ``engine_version`` is the ``rc-foundry`` distribution version
(plus the git commit of a VCS install) read from the ``rf3`` executable's own environment, ``weights_id`` is
the checkpoint file actually used. The allow-list holds one file, ``rf3_foundry_01_24_latest_remapped.ckpt``:
the README's "Latest (recommended)" download and the registry's ``rf3``. The README also lists a preprint and a
09/21-cutoff "benchmark" checkpoint, but under other file names than the registry's ``..._remapped`` ones, so
which file the sentence covers is not unambiguous, and neither is the model under test; extend the tuple only
after a legal read. Whether a result made with a PyPI release may be used commercially is the licence record's
caveat, not something this script can establish.

What was established (this is what the whole script rests on):

* Invocation: ``rf3 fold inputs=<json> out_dir=<dir> ckpt_path=<abs .ckpt> seed=<n> diffusion_batch_size=<n>
  num_steps=<n> n_recycles=10 early_stopping_plddt_threshold=0.0 compress_outputs=false dump_predictions=true
  annotate_b_factor_with_plddt=true`` (Hydra ``key=value``, no ``--flags``). ``ckpt_path`` is a path when it
  contains a ``.``, a registry name otherwise; an absolute path is always given. ``seed`` is a single integer
  and every diffusion sample of a run shares one Pairformer pass, so ``--num-seeds N`` is N sequential
  subprocesses (seeds 101, 102, ...), each in its own ``seed_<n>/`` output dir; ``--num-samples`` is
  ``diffusion_batch_size``. ``early_stopping_plddt_threshold`` defaults to 0.5: a design whose mean pLDDT after
  the first recycle is below it gets NO structure and exit code 0 (only a ``*_ranking_scores.csv`` saying
  ``early_stopped``). A low-confidence binder is exactly what a benchmark must still score, so it is set to 0
  (the code disables it for any value that is not positive).
* Settings: ``n_recycles`` 10 is the shipped default. ``num_steps`` is NOT: the shipped config default is 50
  while the README calls 200 "the standard" (50 shows no deterioration but is 2x faster), and this repo prefers
  accuracy to speed, so 200 is used (``--num-steps`` changes it). The deviation is on record here and in the
  start-up line; it is a setting of this benchmark, not of RF3's shipped CLI.
* Input: a JSON list with one ``{"name", "components": [...]}``. Components are concatenated in order, so the
  atom array and therefore the TOKENS run target (``chain_id`` A) then binder (``chain_id`` B).
  ``chain_type`` is passed explicitly (``polypeptide(L)``): RF3 infers it from the letters otherwise and a
  binder made only of A/C/G/T would be read as DNA.
* MSA: ``msa_path`` on a component takes a ``.a3m`` (parser chosen by extension). The target gets the shared
  ColabFold a3m (``get_target_msa``). The binder gets NO ``msa_path``: that is RF3's no-MSA convention (a chain
  without an MSA is padded and masked; a one-row query-only file would change ``token_idx_has_msa``). Two
  traps are closed. (1) A path that does not exist is a hard assertion, but a path that is not ATTACHED to its
  chain (a chain-id mismatch) is silent: RF3 just folds that chain single-sequence. So before every design
  RF3's own ``InferenceInput.from_json_dict`` is run, in the executable's environment, on the exact input file
  and the design fails unless chain A carries the target a3m and chain B none (``_check_msa_wiring``).
  (2) ``LOCAL_MSA_DIRS`` makes RF3 look every protein up by sequence hash in a local MSA library, which would
  hand the binder an MSA; it is removed from the subprocess environment. (A ``.env`` file RF3's entry point
  loads with ``override=True`` could still set it; none is read from the work dir, which is the cwd.)
* Output, per seed (``<out>`` = ``seed_<n>/``, ``<q>`` = the query id)::

      <out>/<q>/seed-<n>_sample-<k>/<q>_seed-<n>_sample-<k>_model.cif
      <out>/<q>/seed-<n>_sample-<k>/<q>_seed-<n>_sample-<k>_summary_confidences.json
      <out>/<q>/seed-<n>_sample-<k>/<q>_seed-<n>_sample-<k>_confidences.json
      <out>/<q>/<q>_{model.cif,summary_confidences.json,confidences.json,ranking_scores.csv}  (top copies)

  Only the per-sample files are read: the top-level copies belong to one seed. The summary holds ``ptm``,
  ``iptm``, ``has_clash`` and ``ranking_score`` (= 0.8 iptm + 0.2 ptm - 100 has_clash, AF3's rule); a sample
  without them (RF3 writes them only when its metrics ran) is not a candidate. ``chain_pair_pae`` in the
  summary is a per-chain-pair MEAN and is never used for the PAE.
* PAE: ``confidences["pae"]`` is the FULL ``[n_token, n_token]`` matrix, the expectation over 64 bins of
  centres 0.25..31.75 A (max 32 A), rounded to 2 decimals. It is TOKEN-level: for canonical protein residues one
  token per residue, so no atom reduction is needed; a non-standard residue or a ligand would change the token
  count and is refused. Row i is the aligned frame and column j the scored token (AF3's convention: ``ComputeIPTM``
  takes the max over rows of the mean over the other chain's columns, and the training loss is laid out
  ``N_frames x N_ca``), the same as the other adapters, so nothing is transposed. ``confidences`` also holds
  ``token_chain_ids`` (the ``chain_iid`` of each token, ``A_1`` / ``B_1``): it is used to CHECK that the first
  ``len(target)`` tokens are chain A and the rest chain B, so an order mistake cannot pass on sizes alone.
  ``native_pae_order`` is ``target_binder``.
* pLDDT: ``confidences["atom_plddts"]`` is per ATOM and carries no atom names. The per-residue value used here
  is the B-factor of the CA atoms of the top sample's ``.cif`` (``annotate_b_factor_with_plddt=true`` writes
  the pLDDT there), the same convention as the OpenFold3 / Protenix / Chai-1 adapters. RF3 writes pLDDT on a
  0-1 scale (50 bins, ``max_value`` 1.0; read from the checkpoint's own config), so it is multiplied by 100
  here for the driver, and a value above 1 is REFUSED (a checkpoint on another scale would otherwise be
  divided twice). A missing CA, a chain of the wrong length or zero / non-finite B-factors fails the design.
* Top sample: the highest ``ranking_score`` over every seed and sample; non-finite scores are skipped.
* Failure modes: a non-zero exit is a failed design. Exit 0 with no sample files (early stopping, or a
  prediction RF3 logged and skipped) is a failed design too; the error carries both streams and the
  ``*_ranking_scores.csv`` text.
* VERSIONS: ``rf3 fold`` cannot start on rc-foundry 0.1.9 (the version ``install/install.sh`` pins):
  ``rf3/inference.py`` calls ``rootutils.setup_root(..., indicator=".project-root")`` at import and raises
  ``FileNotFoundError`` in a pip install (checked on the installed 0.1.9 environment). Foundry commit ``9760188``
  ("remove reliance of rootutils for pip installed case"), first in v0.2.0, wraps it in ``try/except``. The
  cuEquivariance kernels are an optional import in the source at v0.2.0 and ``production``
  (``SHOULD_USE_CUEQUIVARIANCE`` guards ``import cuequivariance_torch``; the layer falls back to the plain
  einsum): read from the source, not run here.
* HARDWARE: Foundry issue #198 reports ``CUDA out of memory`` on a 23.65 GiB GPU for a ~1000-residue protein plus
  three small molecules at ``diffusion_batch_size=1`` (maintainers: no multi-GPU sharding). Large complexes may
  need a bigger card. ``PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`` is set for the subprocess unless the
  operator already set it (fragmentation, as for RFD3 in this repo). Each design is one ``rf3 fold`` process, so
  the checkpoint is loaded again for every design; an OOM then costs only that design.

Emits the same unprefixed CSV as ``refold_af3.py``; the engine name enters at merge time
(``add_iptm_from_pae_files(prefix="rf3")``). Sidecars in the output dir: ``target_msa_mode.json`` and
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
from pathlib import Path

import numpy as np
from binder_comparison.refolding.second_engine_driver import EngineError, run_cli

ENGINE = "rf3"
#: The checkpoint files the licence record covers. Exact file-name match, after resolving symlinks.
LICENSED_CHECKPOINTS = ("rf3_foundry_01_24_latest_remapped.ckpt",)
DEFAULT_CHECKPOINT = LICENSED_CHECKPOINTS[0]
CHECKPOINT_URL = "https://files.ipd.uw.edu/pub/rf3/rf3_foundry_01_24_latest_remapped.ckpt"
TARGET_CHAIN, BINDER_CHAIN = "A", "B"
CHAIN_TYPE = "polypeptide(L)"
#: Components are listed target-first, so the PAE rows/columns are [target | binder].
NATIVE_PAE_ORDER = "target_binder"
MSA_FILE_NAME = "target.a3m"  # the extension selects RF3's MSA parser
DEFAULT_SEED = 101
N_RECYCLES = 10  # the shipped default, passed explicitly so it is on record
DEFAULT_NUM_STEPS = 200  # README "standard"; the shipped CLI default is 50 (see the header)
WIRING_MARKER = "RF3_MSA_WIRING="
VERSION_MARKER = "RF3_FOUNDRY_DIST="
PROJECT_ROOT_CRASH = "Project root directory not found"

#: Run in the rf3 executable's interpreter: RF3's own parser says which MSA path each chain ended up with.
_WIRING_SNIPPET = (
    "import json, sys\n"
    "from rf3.utils.inference import InferenceInput\n"
    "doc = json.load(open(sys.argv[1]))\n"
    "item = doc[0] if isinstance(doc, list) else doc\n"
    "inp = InferenceInput.from_json_dict(item)\n"
    "wiring = {c: (str(v['msa_path']) if v.get('msa_path') else None) for c, v in inp.chain_info.items()}\n"
    f"print({WIRING_MARKER!r} + json.dumps(wiring))\n"
)
_VERSION_SNIPPET = (
    "import importlib.metadata as m, json\n"
    "d = m.distribution('rc-foundry')\n"
    f"print({VERSION_MARKER!r} + json.dumps({{'version': d.version, 'direct_url': d.read_text('direct_url.json')}}))\n"
)

_HYDRA_SAFE = re.compile(r"^[A-Za-z0-9_./:+\-]+$")


class UnlicensedCheckpointError(ValueError):
    """The requested checkpoint file is not one the licence record covers."""


class CheckpointNotFoundError(FileNotFoundError):
    """The licensed checkpoint file is not where it was looked for (nothing is ever downloaded here)."""


def require_licensed_checkpoint(checkpoint: str | Path) -> str:
    """Return the file name of ``checkpoint`` if it is on the allow-list; otherwise refuse, saying why."""
    name = Path(str(checkpoint)).name
    if name in LICENSED_CHECKPOINTS:
        return name
    raise UnlicensedCheckpointError(
        f"refusing RF3 checkpoint {str(checkpoint)!r}: only {', '.join(LICENSED_CHECKPOINTS)} is cleared for use "
        f"(licence record Evaluator/docs/second_engine_licences.md, RF3 row: BSD-3-Clause, with a sentence "
        f"covering the model weights referenced in the README). No other checkpoint has been checked against "
        f"the licence, and a registry name such as 'rf3' is not accepted because the registry, not this "
        f"script, would choose the file."
    )


def _foundry_checkpoint_dirs() -> list[Path]:
    """Where Foundry looks for a registered checkpoint: ``$FOUNDRY_CHECKPOINT_DIRS``, then ``~/.foundry/checkpoints``."""
    env_dirs = os.environ.get("FOUNDRY_CHECKPOINT_DIRS") or os.environ.get("FOUNDRY_CHECKPOINTS_DIR") or ""
    extra = [Path(p.strip()) for p in env_dirs.split(":") if p.strip()]
    return [*extra, Path.home() / ".foundry" / "checkpoints"]


def resolve_checkpoint(checkpoint: str, model_dir: str | Path | None) -> Path:
    """The licensed checkpoint FILE to run, as an absolute resolved path.

    ``checkpoint`` is a file name (searched for in ``model_dir``, else where Foundry looks) or a path. The
    licence check runs on the name first, then again on the symlink-resolved file, so a link with a licensed
    name cannot smuggle in another checkpoint.
    """
    require_licensed_checkpoint(checkpoint)
    given = Path(checkpoint)
    if given.parent != Path("."):
        searched = [given.parent]
        candidates = [given]
    else:
        searched = [Path(model_dir)] if model_dir else _foundry_checkpoint_dirs()
        candidates = [d / given.name for d in searched]
    for candidate in candidates:
        if candidate.is_file():
            resolved = candidate.resolve()
            require_licensed_checkpoint(resolved)
            return resolved
    raise CheckpointNotFoundError(
        f"RF3 checkpoint {given.name} not found in: {', '.join(str(d) for d in searched)}. This script never "
        f"downloads weights; fetch it from {CHECKPOINT_URL} (Foundry's models/rf3/README.md) and pass --model-dir."
    )


def _hydra_value(value) -> str:
    """A Hydra override value: bare when it only holds path-safe characters, single-quoted otherwise."""
    text = str(value)
    if _HYDRA_SAFE.match(text):
        return text
    return "'" + text.replace("'", "\\'") + "'"


# ---------------------------------------------------------------------------
# The executable and its environment
# ---------------------------------------------------------------------------


def _rf3_executable() -> str:
    sibling = Path(sys.executable).parent / "rf3"
    found = str(sibling) if sibling.exists() else shutil.which("rf3")
    if not found:
        raise EngineError("the 'rf3' executable was not found (run in the Foundry env: pip install 'rc-foundry[rf3]')")
    return found


def _env_python(exe: str) -> str:
    """The interpreter beside the ``rf3`` executable: the environment RF3 itself runs in, not this script's."""
    return str(Path(exe).parent / "python")


def _foundry_version(exe: str) -> str:
    """``rc-foundry <version>`` (plus the git commit of a VCS install), asked of the executable's own environment."""
    result = subprocess.run(
        [_env_python(exe), "-I", "-c", _VERSION_SNIPPET], capture_output=True, text=True, errors="replace"
    )
    line = next((ln for ln in reversed((result.stdout or "").splitlines()) if ln.startswith(VERSION_MARKER)), None)
    if result.returncode != 0 or line is None:
        raise EngineError(
            f"could not read the rc-foundry version from {_env_python(exe)} (exit code {result.returncode})",
            result.stderr or "",
        )
    try:
        info = json.loads(line[len(VERSION_MARKER) :])
        version = str(info["version"]).strip()
        direct = json.loads(info["direct_url"]) if info.get("direct_url") else {}
    except (ValueError, KeyError, TypeError) as exc:
        raise EngineError(f"unreadable rc-foundry version record {line!r}: {exc}") from exc
    if not version:
        raise EngineError("the rc-foundry distribution reports no version")
    commit = (direct.get("vcs_info") or {}).get("commit_id")
    return f"rc-foundry {version}" + (f" (git {commit})" if commit else "")


def _engine_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("LOCAL_MSA_DIRS", None)  # RF3 would look the binder up in a local MSA library by sequence hash
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    return env


# ---------------------------------------------------------------------------
# Input construction and the model call (the one seam the tests replace)
# ---------------------------------------------------------------------------


def build_input(query_id: str, binder_seq: str, target_seq: str, *, target_msa_path: Path | None) -> list[dict]:
    """The RF3 input JSON: a one-example list, TARGET first (chain A), binder second (chain B).

    Only the target carries an ``msa_path``; the binder never does (RF3's no-MSA convention).
    """
    target = {"seq": target_seq, "chain_id": TARGET_CHAIN, "chain_type": CHAIN_TYPE}
    binder = {"seq": binder_seq, "chain_id": BINDER_CHAIN, "chain_type": CHAIN_TYPE}
    if target_msa_path is not None:
        target["msa_path"] = str(Path(target_msa_path).absolute())
    return [{"name": query_id, "components": [target, binder]}]


def _check_msa_wiring(exe: str, input_json: Path, target_msa_path: Path) -> None:
    """Fail unless RF3's own parser attaches the target a3m to chain A and nothing to chain B."""
    result = subprocess.run(
        [_env_python(exe), "-I", "-c", _WIRING_SNIPPET, str(input_json)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        raise EngineError(
            f"could not verify the target MSA wiring with RF3's input parser (exit code {result.returncode})",
            result.stderr or "",
        )
    line = next((ln for ln in reversed((result.stdout or "").splitlines()) if ln.startswith(WIRING_MARKER)), None)
    wiring = None
    if line is not None:
        try:
            wiring = json.loads(line[len(WIRING_MARKER) :])
        except ValueError:
            wiring = None
    expected = str(Path(target_msa_path).absolute())
    if (
        not isinstance(wiring, dict)
        or not wiring.get(TARGET_CHAIN)
        or Path(wiring[TARGET_CHAIN]) != Path(expected)
        or wiring.get(BINDER_CHAIN)
    ):
        raise EngineError(
            f"RF3 did not attach the target MSA as intended (chain {TARGET_CHAIN} should carry {expected}, chain "
            f"{BINDER_CHAIN} none; RF3 reports {wiring!r}). RF3 folds a chain without an attached MSA "
            f"single-sequence and says nothing, so this design is refused rather than scored with the wrong MSA."
        )


def _run_fold(exe: str, overrides: dict[str, object], work_dir: Path, env: dict[str, str]):
    cmd = [exe, "fold", *(f"{key}={_hydra_value(value)}" for key, value in overrides.items())]
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env, cwd=str(work_dir))


def _predict_one(
    *,
    query_id: str,
    binder_seq: str,
    target_seq: str,
    target_msa_path: Path | None,
    work_dir: Path,
    checkpoint: Path,
    num_steps: int,
    num_seeds: int,
    num_samples: int,
) -> dict:
    """Run RF3 on one binder-target pair; return the top sample.

    THE MODEL SEAM: tests replace this function. It returns a dict with ``pae`` (token-level, native chain
    order: target then binder), ``summary`` (``iptm``, ``ptm``, ``sample_ranking_score``), ``cif`` (path),
    ``plddt_target`` / ``plddt_binder`` (per residue, 0-100) and ``seed``. Raises if the model produced nothing.
    """
    require_licensed_checkpoint(checkpoint)  # also here, so no caller can reach the model around configure()
    exe = _rf3_executable()
    work_dir = Path(work_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)  # never pick up samples of an earlier, partly failed attempt
    work_dir.mkdir(parents=True)
    input_json = work_dir / "input.json"
    input_json.write_text(
        json.dumps(build_input(query_id, binder_seq, target_seq, target_msa_path=target_msa_path), indent=2)
    )
    if target_msa_path is not None:
        _check_msa_wiring(exe, input_json, target_msa_path)

    env = _engine_env()
    for i in range(num_seeds):
        seed = DEFAULT_SEED + i
        out_dir = work_dir / f"seed_{seed}"
        result = _run_fold(
            exe,
            {
                "inputs": input_json,
                "out_dir": out_dir,
                "ckpt_path": checkpoint,
                "seed": seed,
                "diffusion_batch_size": num_samples,
                "num_steps": num_steps,
                "n_recycles": N_RECYCLES,
                "early_stopping_plddt_threshold": 0.0,
                "compress_outputs": "false",
                "dump_predictions": "true",
                "annotate_b_factor_with_plddt": "true",
            },
            work_dir,
            env,
        )
        stderr = result.stderr or ""
        if result.returncode != 0:
            print(f"  [rf3] STDERR: {stderr[-4000:]}" if stderr else "  [rf3] No stderr")
            hint = ""
            if PROJECT_ROOT_CRASH in stderr:
                hint = " (rf3 cannot start on rc-foundry 0.1.9, the version install.sh pins: it needs 0.2.0 or later)"
            raise EngineError(f"RF3 exited with code {result.returncode}{hint}", stderr)
        if not any((out_dir / query_id).glob(f"seed-*_sample-*/{query_id}_seed-*_sample-*_summary_confidences.json")):
            # Early stopping, or a prediction RF3 logged and skipped: the CLI still exits 0.
            ranking = "\n".join(
                p.read_text(errors="replace") for p in sorted((out_dir / query_id).glob("*_ranking_scores.csv"))
            )
            combined = "\n".join(s for s in (stderr, result.stdout or "", ranking) if s)
            print(f"  [rf3] STDERR: {combined[-4000:]}" if combined else "  [rf3] No stderr")
            raise EngineError(
                f"RF3 produced no prediction for {query_id} (exit code 0, no sample files for seed {seed})", combined
            )

    top = _load_top_sample(work_dir, query_id, len(target_seq), len(binder_seq))
    if top is None:
        raise EngineError(f"RF3 wrote samples for {query_id} but none has a finite ranking_score, ptm and iptm")
    return top


def _finite(value, what: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{what} is {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} is {number}")
    return number


def _load_top_sample(work_dir: Path, query_id: str, n_target: int, n_binder: int) -> dict | None:
    """Locate and load the sample with the highest ``ranking_score`` over all seeds and samples.

    Layout (``RF3Output.dump``): ``<work_dir>/seed_<n>/<query_id>/seed-<n>_sample-<k>/`` holding
    ``<query_id>_seed-<n>_sample-<k>_{summary_confidences.json, confidences.json, model.cif}``. A sample missing
    a file, or whose summary lacks a finite ranking_score / ptm / iptm, is not a candidate.
    """
    name_re = re.compile(rf"^{re.escape(query_id)}_seed-(-?\d+)_sample-(\d+)_summary_confidences\.json$")
    best = None
    for summary_fp in sorted(Path(work_dir).glob(f"seed_*/{query_id}/seed-*_sample-*/*_summary_confidences.json")):
        match = name_re.match(summary_fp.name)
        if match is None:
            continue
        stem = summary_fp.name.removesuffix("_summary_confidences.json")
        conf_fp, cif_fp = summary_fp.with_name(f"{stem}_confidences.json"), summary_fp.with_name(f"{stem}_model.cif")
        if not (conf_fp.is_file() and cif_fp.is_file()):
            continue
        try:
            summary = json.loads(summary_fp.read_text())
            score = _finite(summary.get("ranking_score"), "ranking_score")
            iptm, ptm = _finite(summary.get("iptm"), "iptm"), _finite(summary.get("ptm"), "ptm")
        except (OSError, ValueError, TypeError) as exc:
            print(f"  [rf3] Ignoring {summary_fp.name}: {exc}")
            continue
        if best is None or score > best[0]:
            best = (score, iptm, ptm, conf_fp, cif_fp, int(match.group(1)))
    if best is None:
        return None

    score, iptm, ptm, conf_fp, cif_fp, seed = best
    confidences = json.loads(conf_fp.read_text())
    pae = np.asarray(confidences["pae"], dtype=np.float32)
    _check_token_order(confidences.get("token_chain_ids"), pae, n_target, n_binder)
    plddt = _ca_plddt_by_chain(cif_fp, n_target, n_binder)
    return {
        "pae": pae,
        "summary": {"iptm": iptm, "ptm": ptm, "sample_ranking_score": score},
        "cif": cif_fp,
        "plddt_target": plddt[TARGET_CHAIN],
        "plddt_binder": plddt[BINDER_CHAIN],
        "seed": seed,
    }


def _check_token_order(token_chain_ids, pae: np.ndarray, n_target: int, n_binder: int) -> None:
    """Refuse a PAE whose tokens are not ``n_target`` chain-A tokens then ``n_binder`` chain-B tokens.

    The driver can only check the total size; this checks the chain order and the one-token-per-residue
    assumption using the ``token_chain_ids`` RF3 saves beside the PAE (``chain_iid``: ``A_1``, ``B_1``).
    """
    if token_chain_ids is None:
        raise ValueError("confidences file has no token_chain_ids, so the PAE chain order cannot be verified")
    labels = [str(label).split("_")[0] for label in token_chain_ids]
    n = n_target + n_binder
    if len(labels) != n or pae.shape != (n, n):
        raise ValueError(
            f"RF3 returned {len(labels)} token labels (PAE {pae.shape}) for {n_target} target + {n_binder} binder "
            f"residues; the PAE is residue-indexed only for canonical protein residues (non-standard residue "
            f"or ligand token?)"
        )
    if any(label != TARGET_CHAIN for label in labels[:n_target]) or any(
        label != BINDER_CHAIN for label in labels[n_target:]
    ):
        raise ValueError(
            f"PAE tokens are not target-first: the first {n_target} token chains are {sorted(set(labels[:n_target]))} "
            f"and the next {n_binder} are {sorted(set(labels[n_target:]))}, expected [{TARGET_CHAIN}] then [{BINDER_CHAIN}]"
        )


def _ca_plddt_by_chain(cif_path: Path, n_target: int, n_binder: int) -> dict[str, np.ndarray]:
    """Per-residue pLDDT (0-100) of chains A and B: the B-factor of their CA atoms, x100.

    RF3 writes pLDDT on a 0-1 scale into the B-factor column. Raises on a chain that is absent or has not
    exactly the expected number of CA atoms, on zero / non-finite values, and on values above 1 (another scale).
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
    if float(allv.min()) < 0.0 or float(allv.max()) > 1.0 + 1e-3:
        raise ValueError(
            f"{Path(cif_path).name}: CA B-factors span {allv.min():.3g}..{allv.max():.3g}, not the 0-1 pLDDT scale "
            f"RF3 writes; refusing to rescale a value of unknown scale"
        )
    return {chain: values * 100.0 for chain, values in out.items()}


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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class RF3Adapter:
    """RF3 plugged into the shared driver (``binder_comparison.refolding.second_engine_driver``)."""

    name = ENGINE
    description = __doc__
    native_pae_order = NATIVE_PAE_ORDER
    target_msa_filename = MSA_FILE_NAME

    def __init__(self) -> None:
        self.checkpoint: Path | None = None
        self.num_steps = DEFAULT_NUM_STEPS
        self._version: str | None = None

    def add_args(self, parser) -> None:
        parser.add_argument(
            "--checkpoint",
            default=DEFAULT_CHECKPOINT,
            help=f"RF3 checkpoint file name (or path); only {', '.join(LICENSED_CHECKPOINTS)} is accepted "
            f"(default {DEFAULT_CHECKPOINT}). Anything else is refused: the licence record covers that file only.",
        )
        parser.add_argument(
            "--model-dir",
            default=None,
            help="Directory holding the checkpoint file. Default: where Foundry looks ($FOUNDRY_CHECKPOINT_DIRS, "
            "then ~/.foundry/checkpoints). Nothing is downloaded.",
        )
        parser.add_argument(
            "--num-steps",
            type=int,
            default=DEFAULT_NUM_STEPS,
            help=f"Diffusion steps (default {DEFAULT_NUM_STEPS}, the README's 'standard'; RF3's shipped CLI default is 50)",
        )

    def configure(self, args) -> None:
        self.checkpoint = resolve_checkpoint(args.checkpoint, args.model_dir)
        if args.num_steps < 1:
            raise ValueError("--num-steps must be a positive integer")
        self.num_steps = args.num_steps
        _rf3_executable()  # fail before any work if RF3 is not there
        print(
            f"[rf3] checkpoint={self.checkpoint} num_steps={self.num_steps} n_recycles={N_RECYCLES} "
            f"(early stopping off). NOTE: the BSD-3-Clause sentence covering the model weights is on Foundry's "
            f"`production` branch only; see Evaluator/docs/second_engine_licences.md before relying on a PyPI release.",
            file=sys.stderr,
        )

    def engine_version(self) -> str:
        if self._version is None:
            self._version = _foundry_version(_rf3_executable())
        return self._version

    def weights_id(self) -> str:
        return self.checkpoint.name

    def predict_one(self, *, query_id, binder_seq, target_seq, target_msa_path, work_dir, num_seeds, num_samples):
        # Looked up at call time on purpose: the model seam tests replace.
        return _predict_one(
            query_id=query_id,
            binder_seq=binder_seq,
            target_seq=target_seq,
            target_msa_path=target_msa_path,
            work_dir=work_dir,
            checkpoint=self.checkpoint,
            num_steps=self.num_steps,
            num_seeds=num_seeds,
            num_samples=num_samples,
        )


def main(argv: list[str] | None = None) -> int:
    try:
        return run_cli(RF3Adapter(), argv)
    except (UnlicensedCheckpointError, CheckpointNotFoundError) as exc:
        # Raised from configure(), before any design, file or sidecar exists.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
