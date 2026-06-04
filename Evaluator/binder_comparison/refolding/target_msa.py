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
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import time
from pathlib import Path

import requests

COLABFOLD_HOST = "https://api.colabfold.com"
DEFAULT_MODE = "mmseqs2_uniref_env"
DEFAULT_POLL_INTERVAL_S = 5
DEFAULT_TIMEOUT_S = 60 * 60  # 1 h hard cap


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
    cache_dir = _resolve_cache_dir(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key(target_seq)
    cache_file = cache_dir / f"target_{key}.a3m"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        return cache_file.read_text()

    print(f"[target-msa] cache miss for {key} — querying ColabFold MSA server (~30-60 s)")
    a3m = _query_colabfold(target_seq)
    cache_file.write_text(a3m)
    n_seqs = a3m.count(">")
    print(f"[target-msa] cached {len(a3m)} bytes / {n_seqs} sequences → {cache_file}")
    return a3m


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

    a3m = get_target_msa(args.target_seq, cache_dir=args.cache_dir)
    n = a3m.count(">")
    print(f"OK — {n} sequences, {len(a3m)} bytes")
