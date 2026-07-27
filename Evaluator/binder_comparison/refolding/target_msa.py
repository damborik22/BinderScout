"""Target MSA generation via the ColabFold MSA server, with on-disk cache.

Used by refold_af3 and refold_esmfold2 to provide a cached target MSA so
both engines see the same evolutionary context as Boltz-2 (which already
calls the ColabFold server internally).

The cache key is the SHA-256 of the target sequence — sequences identical
across runs share the same cache entry.  Default cache directory:
``$BINDMASTER_MSA_CACHE`` or ``~/.cache/bindmaster/target_msa/``.

The implementation queries the public ColabFold MSA server
(``https://api.colabfold.com``) using the same protocol as the
ColabFold notebook + Boltz-2's MSA helper — POST a job, poll for
COMPLETE, download the tar.gz, extract the .a3m.

Only the *target* MSA is generated.  For de novo binders there is no
homology and the binder MSA is left empty (single-sequence).

Cache integrity: the a3m is written atomically (temp file in the same
directory + ``os.replace``) and validated on every read, so two engines
started together on a cold cache can never hand each other a
half-written MSA.

MSA provenance: ``get_target_msa_with_mode`` reports whether the MSA came
from the cache, was freshly fetched, or is unavailable.  ``note_msa_mode``
prints that fact (a warning when an engine proceeds without an MSA) and
records it next to the refold outputs — cross-engine iPTMs are only
comparable when every engine saw the same evolutionary context.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

COLABFOLD_HOST = "https://api.colabfold.com"
DEFAULT_MODE = "mmseqs2_uniref_env"
DEFAULT_POLL_INTERVAL_S = 5
DEFAULT_TIMEOUT_S = 60 * 60  # 1 h hard cap

#: MSA came from the shared on-disk cache (no server call).
MSA_MODE_CACHED = "cached"
#: MSA was fetched from the ColabFold server this run and cached.
MSA_MODE_FETCHED = "fetched"
#: No MSA — the engine folds the target single-sequence.
MSA_MODE_NONE = "single_sequence"

#: Filename of the per-engine provenance record written by ``note_msa_mode``.
MSA_MODE_FILENAME = "target_msa_mode.json"


def get_target_msa(target_seq: str, cache_dir: str | Path | None = None) -> str:
    """Return the A3M MSA for *target_seq*; cache to disk.

    Args:
        target_seq: target amino acid sequence (no header, no whitespace).
        cache_dir: directory for the on-disk cache.  Defaults to
            ``$BINDMASTER_MSA_CACHE`` then ``~/.cache/bindmaster/target_msa``.

    Returns:
        The A3M MSA as a single string (suitable for AF3's ``unpairedMsa``
        JSON field or for parsing into ESMFold2's MSA object).
    """
    return get_target_msa_with_mode(target_seq, cache_dir)[0]


def get_target_msa_with_mode(target_seq: str, cache_dir: str | Path | None = None) -> tuple[str, str]:
    """Like :func:`get_target_msa`, but also report where the MSA came from.

    Returns:
        ``(a3m, mode)`` where *mode* is :data:`MSA_MODE_CACHED` (disk hit) or
        :data:`MSA_MODE_FETCHED` (queried the ColabFold server this call).
        A cached file that fails validation (truncated / corrupt / not an
        a3m) is discarded and re-fetched rather than returned.
    """
    cache_dir = _resolve_cache_dir(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key(target_seq)
    cache_file = cache_dir / f"target_{key}.a3m"
    cached = _read_valid_a3m(cache_file)
    if cached is not None:
        _warn_on_query_mismatch(cached, target_seq, str(cache_file))
        return cached, MSA_MODE_CACHED

    print(f"[target-msa] cache miss for {key} — querying ColabFold MSA server (~30-60 s)")
    a3m = _query_colabfold(target_seq)
    problem = _a3m_problem(a3m)
    if problem is not None:
        raise RuntimeError(f"ColabFold returned an unusable MSA for {key}: {problem}")
    _warn_on_query_mismatch(a3m, target_seq, "ColabFold response")
    _atomic_write_text(cache_file, a3m)
    n_seqs = a3m.count(">")
    print(f"[target-msa] cached {len(a3m)} bytes / {n_seqs} sequences → {cache_file}")
    return a3m, MSA_MODE_FETCHED


def target_msa_cache_path(target_seq: str, cache_dir: str | Path | None = None) -> Path | None:
    """Return the on-disk path of the cached target MSA, or None if not cached.

    Unlike ``get_target_msa`` this never queries the MSA server — it only reports
    whether a usable cached A3M already exists.  Offline consumers (e.g. the
    Boltz-2 refold) need the a3m *file path* for the Boltz input YAML, and must
    not trigger an online fetch on a no-internet compute node.

    A cached file that fails validation counts as *not cached* (None) — the
    caller must not feed a truncated MSA to a folding engine.
    """
    cache_dir = _resolve_cache_dir(cache_dir)
    cache_file = cache_dir / f"target_{_cache_key(target_seq)}.a3m"
    if _read_valid_a3m(cache_file) is not None:
        return cache_file
    return None


# ---------------------------------------------------------------------------
# MSA provenance + enforcement (F21)
# ---------------------------------------------------------------------------


class MissingTargetMSA(RuntimeError):
    """A refold engine could not obtain the shared target MSA and must not run.

    Refolding without an MSA is not a silent fallback: the MSA drives *target*
    fold confidence, and iPTM is an interface metric over both chains — so an
    engine that quietly missed the MSA is *systematically* penalised.  It drags
    ``consensus_iptm_mean`` down and can demote a good design with nothing
    visible in the report.  Consistency across engines is the property that
    matters, so the default is to abort; the operator opts out explicitly.
    """


#: Env-var opt-out, for callers that cannot pass ``allow_no_msa`` (shared CLI).
ALLOW_NO_MSA_ENV = "BINDMASTER_ALLOW_NO_MSA"


def allow_no_msa_default() -> bool:
    """True when ``$BINDMASTER_ALLOW_NO_MSA`` opts this host out of the MSA gate."""
    return os.environ.get(ALLOW_NO_MSA_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def prepare_target_msa(
    target_seq: str,
    *,
    engine: str,
    cache_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    use_msa: bool = True,
    allow_no_msa: bool = False,
) -> tuple[str, str]:
    """Pre-warm the shared target MSA for *engine*, or abort.

    The MSA is fetched once per target and cached on disk, so the first engine
    to call this pays the ColabFold round-trip and every later engine — in this
    run or a later one — is a disk hit.  That is what makes the per-engine
    iPTMs comparable.

    Args:
        target_seq:   target amino acid sequence.
        engine:       engine name for log lines (``af3`` / ``esmfold2`` / ``boltz2``).
        cache_dir:    override the shared MSA cache directory.
        out_dir:      refold output directory; a ``target_msa_mode.json``
                      provenance record is written there.
        use_msa:      False = the operator explicitly asked for single-sequence
                      mode (``--no-msa``); no abort, the state is recorded.
        allow_no_msa: True = proceed without an MSA if it cannot be obtained
                      (air-gapped nodes).  The state is recorded either way.

    Returns:
        ``(a3m, mode)`` — ``a3m`` is ``""`` when running without an MSA.

    Raises:
        MissingTargetMSA: the MSA could not be obtained and neither
            ``allow_no_msa`` nor ``$BINDMASTER_ALLOW_NO_MSA`` was set.
    """
    if not use_msa:
        note_msa_mode(engine, MSA_MODE_NONE, out_dir=out_dir, detail="explicit --no-msa (single-sequence requested)")
        return "", MSA_MODE_NONE

    try:
        a3m, mode = get_target_msa_with_mode(target_seq, cache_dir=cache_dir)
    except Exception as exc:
        if not (allow_no_msa or allow_no_msa_default()):
            raise MissingTargetMSA(no_msa_abort_message(engine, target_seq, exc, cache_dir=cache_dir)) from exc
        note_msa_mode(engine, MSA_MODE_NONE, out_dir=out_dir, detail=f"MSA unavailable ({exc}); --allow-no-msa given")
        return "", MSA_MODE_NONE

    note_msa_mode(engine, mode, out_dir=out_dir, n_seqs=a3m.count(">"))
    return a3m, mode


def no_msa_abort_message(
    engine: str,
    target_seq: str,
    reason: object,
    cache_dir: str | Path | None = None,
) -> str:
    """The operator-facing abort text: why we stopped, and the two ways forward."""
    cache_file = _resolve_cache_dir(cache_dir) / f"target_{_cache_key(target_seq)}.a3m"
    return (
        f"[{engine}] ABORTING: the shared target MSA could not be obtained ({reason}).\n"
        f"\n"
        f"Refolding without an MSA is not allowed by default. The MSA drives target fold\n"
        f"confidence and iPTM is an interface metric over both chains, so an engine that\n"
        f"silently ran single-sequence is systematically penalised: it drags\n"
        f"consensus_iptm_mean down and can demote a good design with nothing visible in\n"
        f"the report. Every engine must see the same evolutionary context.\n"
        f"\n"
        f"Do one of:\n"
        f"  1. Pre-warm the shared cache once for this target (on any host with network):\n"
        f"       python -m binder_comparison.refolding.target_msa --target-seq <TARGET_SEQ>\n"
        f"     All three engines then read {cache_file} — no further server calls.\n"
        f"     (Copy that .a3m over to run air-gapped nodes with a full MSA.)\n"
        f"  2. If this node is air-gapped and you accept scores that are NOT comparable\n"
        f"     to MSA-using engines, re-run with --allow-no-msa (or set\n"
        f"     {ALLOW_NO_MSA_ENV}=1). The no-MSA state is recorded in\n"
        f"     {MSA_MODE_FILENAME} next to the outputs."
    )


def note_msa_mode(
    engine: str,
    mode: str,
    *,
    out_dir: str | Path | None = None,
    n_seqs: int | None = None,
    detail: str | None = None,
) -> dict:
    """Print — and optionally record — which MSA mode *engine* ran under.

    When *mode* is :data:`MSA_MODE_NONE` this prints a WARNING naming the
    consequence: the engine's scores are not directly comparable to engines
    that used an MSA, and ``consensus_iptm`` mixes them.

    When *out_dir* is given, a ``target_msa_mode.json`` record is written
    there so a later reader can tell a cold cache from a bad design.
    Recording is best-effort — a failure never blocks a refold.
    """
    record = {
        "engine": engine,
        "target_msa_mode": mode,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if n_seqs is not None:
        record["n_sequences"] = n_seqs
    if detail:
        record["detail"] = detail

    if mode == MSA_MODE_NONE:
        print(
            f"[{engine}] WARNING: no target MSA — folding the target single-sequence. "
            f"This engine's scores are not directly comparable to engines that used an MSA "
            f"(consensus_iptm / consensus_iptm_mean average across engines). "
            f"Pre-warm the shared cache "
            f"(python -m binder_comparison.refolding.target_msa --target-seq <seq>) "
            f"so every engine sees the same evolutionary context.",
            flush=True,
        )
    else:
        suffix = f", {n_seqs} sequences" if n_seqs is not None else ""
        extra = f" ({detail})" if detail else ""
        print(f"[{engine}] target MSA mode: {mode}{suffix}{extra}", flush=True)

    if out_dir is not None:
        with contextlib.suppress(OSError, TypeError, ValueError):
            path = Path(out_dir)
            path.mkdir(parents=True, exist_ok=True)
            (path / MSA_MODE_FILENAME).write_text(json.dumps(record, indent=2) + "\n")
    return record


# ---------------------------------------------------------------------------
# ColabFold MSA query
# ---------------------------------------------------------------------------


def _query_colabfold(seq: str, mode: str = DEFAULT_MODE) -> str:
    """Submit *seq* to ColabFold MSA, poll, download A3M, return the text."""
    submit = requests.post(
        f"{COLABFOLD_HOST}/ticket/msa",
        data={"q": f">target\n{seq}\n", "mode": mode},
        timeout=60,
    )
    submit.raise_for_status()
    job = submit.json()
    job_id = job["id"]

    deadline = time.time() + DEFAULT_TIMEOUT_S
    status = job.get("status", "UNKNOWN")
    while status not in ("COMPLETE", "ERROR"):
        if time.time() > deadline:
            raise TimeoutError(f"ColabFold MSA timed out after {DEFAULT_TIMEOUT_S}s (job {job_id})")
        time.sleep(DEFAULT_POLL_INTERVAL_S)
        r = requests.get(f"{COLABFOLD_HOST}/ticket/{job_id}", timeout=30)
        r.raise_for_status()
        status = r.json().get("status", "UNKNOWN")

    if status != "COMPLETE":
        raise RuntimeError(f"ColabFold MSA failed for job {job_id}: status={status}")

    dl = requests.get(f"{COLABFOLD_HOST}/result/download/{job_id}", timeout=120)
    dl.raise_for_status()
    return _extract_a3m_from_tar(dl.content)


def _extract_a3m_from_tar(blob: bytes) -> str:
    """ColabFold returns a tar.gz containing uniref.a3m + bfd.mgnify.a3m etc.

    For a target MSA we want the *unpaired* MSA — uniref.a3m is the standard
    pick (largest, most diverse).  Concatenate paired MSAs are only useful
    for multimers where pairing matters, which doesn't apply to a
    single-chain target.
    """
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
        # Prefer uniref.a3m; fall back to anything ending .a3m
        target_member = None
        for name in ("uniref.a3m", "bfd.mgnify30.metaeuk30.smag30.a3m"):
            try:
                target_member = tf.getmember(name)
                break
            except KeyError:
                continue
        if target_member is None:
            for member in tf.getmembers():
                if member.name.endswith(".a3m"):
                    target_member = member
                    break
        if target_member is None:
            raise RuntimeError(f"No .a3m in ColabFold MSA tarball (members: {[m.name for m in tf.getmembers()]})")
        fh = tf.extractfile(target_member)
        if fh is None:
            raise RuntimeError(f"Cannot read {target_member.name} from tarball")
        raw = fh.read().decode("utf-8", errors="replace")
        return _sanitise_a3m(raw)


def _sanitise_a3m(text: str) -> str:
    """Strip null bytes and trailing whitespace; AF3 + ESMFold2 reject either.

    The ColabFold .a3m sometimes ends with a stray NUL (0x00) padding byte
    from the tar archive, and may carry trailing blank lines that confuse
    AF3's input validator.  Also strip any line containing a NUL — those
    appear to be tar padding records, never legitimate MSA content.
    """
    # Remove any line containing a NUL or that is purely whitespace at the tail.
    lines = [ln.replace("\x00", "") for ln in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _a3m_problem(text: str | None) -> str | None:
    """Return a human reason why *text* is not a usable A3M, or None if it is.

    ``st_size > 0`` does not validate anything — a half-written file passes it.
    An a3m must start with a FASTA header, carry at least one sequence, and end
    with a complete record (trailing newline, last record not a bare header).
    """
    if not text or not text.strip():
        return "empty file"
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip()), "")
    if not first.startswith(">"):
        return f"does not start with a FASTA header (first line: {first[:40]!r})"
    if not any(ln.strip() and not ln.startswith(">") for ln in lines):
        return "no sequence records (headers only)"
    if not text.endswith("\n"):
        return "truncated: file does not end with a newline"
    last = next((ln for ln in reversed(lines) if ln.strip()), "")
    if last.startswith(">"):
        return "truncated: last record is a header with no sequence"
    return None


def _read_valid_a3m(cache_file: Path) -> str | None:
    """Read *cache_file* and return its text, or None if missing/unusable.

    An unreadable or invalid cache entry is reported and treated as a miss so
    the caller re-fetches instead of feeding a truncated MSA to an engine.
    """
    try:
        text = cache_file.read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[target-msa] WARNING: cannot read cache {cache_file} ({exc}) — re-fetching")
        return None
    problem = _a3m_problem(text)
    if problem is not None:
        print(f"[target-msa] WARNING: discarding invalid cached MSA {cache_file} ({problem}) — re-fetching")
        return None
    return text


def _first_record_sequence(text: str) -> str | None:
    """Return the first record's sequence (gaps and a3m inserts stripped)."""
    seen_header = False
    parts: list[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            if seen_header:
                break
            seen_header = True
            continue
        if seen_header:
            parts.append(line.strip())
    if not parts:
        return None
    seq = "".join(parts)
    return "".join(c for c in seq if c.isupper())


def _warn_on_query_mismatch(a3m: str, target_seq: str, source: str) -> None:
    """Warn (never reject) when the a3m query row is not the target sequence."""
    first = _first_record_sequence(a3m)
    if first is None or first == target_seq.upper():
        return
    print(
        f"[target-msa] WARNING: {source} query row does not match the target sequence "
        f"(msa {len(first)} aa vs target {len(target_seq)} aa) — the MSA may belong to a different target"
    )


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (temp file in the same dir + replace).

    Readers only ever see the complete file: ``os.replace`` is atomic within a
    filesystem on POSIX, so a concurrent engine either sees the old entry or
    the new one — never a partial write.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _resolve_cache_dir(override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    env = os.environ.get("BINDMASTER_MSA_CACHE")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "bindmaster" / "target_msa"


def _cache_key(seq: str) -> str:
    return hashlib.sha256(seq.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI for ad-hoc use / pre-warming
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Generate and cache target MSA via ColabFold.")
    p.add_argument("--target-seq", required=True, help="Target amino acid sequence")
    p.add_argument("--cache-dir", default=None, help="MSA cache directory")
    args = p.parse_args()

    a3m, mode = get_target_msa_with_mode(args.target_seq, cache_dir=args.cache_dir)
    n = a3m.count(">")
    print(f"OK — {n} sequences, {len(a3m)} bytes (mode={mode})")
