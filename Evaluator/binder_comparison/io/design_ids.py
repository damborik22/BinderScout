"""Filesystem names for per-design artifacts, keyed by ``binder_id``.

One module, imported by all three refold engines and by the Foldseek join, because
those four places have to agree on the mapping ``binder_id -> filename stem``. They
live in four different conda environments; a second implementation that differs by
one character silently breaks the ability to find a structure by its id, which is the
whole point of naming them this way.

Before this, every engine named structures by loop index -- ``refold7_a1b2c3d4.pdb``,
``af3_0007.pdb``, ``esmfold2_0007.pdb``. Those are three different names for one
design, none of them the design's own id, and the index is only meaningful relative
to the FASTA that produced it.
"""

from __future__ import annotations

import re

#: Characters kept verbatim besides alphanumerics. Everything else becomes ``_``,
#: which also makes path traversal impossible: ``..`` sanitises to ``__``.
_SAFE_EXTRA = "-_"


def safe_stem(binder_id) -> str:
    """The filename stem for *binder_id* -- alphanumerics, dash and underscore only.

    Deliberately lossy, and deliberately shared: this is the join key between a
    structure on disk and a row in the report.
    """
    return "".join(c if (c.isalnum() or c in _SAFE_EXTRA) else "_" for c in str(binder_id))


def header_binder_id(header: str) -> str | None:
    """The ``binder_id`` of one FASTA header: its first whitespace token.

    Raises ``ValueError`` when the header's second token is not a ``key=value`` tag,
    because that means the id itself contains a space (``>CALCA-Protein Hunter-01``).
    Reading only the first token would then give ``CALCA-Protein`` to every design from
    that source, the stems would be rescued from colliding by ``__2``, ``__3`` suffixes
    in file order, and no file would carry the design's own id. Measured 2026-10-14 on a
    114-design pool: 12 structures named ``CALCA-Protein_af3.pdb`` and ``__2``..``__6``.
    Refusing before the GPU is spent is the only point where this is cheap.
    """
    tokens = header.split()
    if not tokens:
        return None
    if len(tokens) > 1 and "=" not in tokens[1]:
        raise ValueError(
            f"FASTA header {header!r} has a space inside its id: only {tokens[0]!r} would be "
            "kept as the binder_id, and structures could not be matched back to designs. "
            "Remove the space (use '_') in the header and re-run."
        )
    return tokens[0]


def structure_stems(binder_ids, fallbacks, *, engine: str | None = None) -> list[str]:
    """One unique, filesystem-safe stem per design: ``<binder_id>_<engine>``.

    Args:
        binder_ids: One id per design, positionally aligned with *fallbacks*. ``None``
            (no ids available at all -- e.g. sequences pasted interactively) keeps the
            engine's legacy index-based names unchanged.
        fallbacks: The engine's legacy stem for each design, used wherever an id is
            missing or sanitises away to nothing. These already name their engine
            (``af3_0007``), so they are never suffixed again.
        engine: Appended to the id, e.g. ``rfd3_b7_boltz2``. Each engine writes into its
            own directory, so this is not needed to avoid a collision there -- it is
            needed the moment the three directories are pooled, which is the normal way
            to hand someone "all the PDBs". Without it, one design's three structures
            are three identically-named files.

    Raises:
        ValueError: if the two lists differ in length. This is the failure mode worth
            being loud about: an off-by-one here writes every structure under a
            *different* design's id, every file exists, every path resolves, and
            nothing downstream can detect it.

    Two designs claiming the same id get ``__2``, ``__3`` suffixes rather than one
    overwriting the other -- ``extract --keep-duplicates`` can emit a repeated id, and
    losing a structure to a silent clobber is worse than an ugly name.
    """
    fallbacks = list(fallbacks)
    if binder_ids is None:
        return fallbacks
    binder_ids = list(binder_ids)
    if len(binder_ids) != len(fallbacks):
        raise ValueError(
            f"{len(binder_ids)} binder id(s) for {len(fallbacks)} design(s) — refusing to name "
            "structures. An off-by-one here labels every file with another design's id, and "
            "every path still resolves, so nothing downstream would catch it."
        )

    used: set[str] = set()
    stems: list[str] = []
    for binder_id, fallback in zip(binder_ids, fallbacks, strict=True):
        stem = safe_stem(binder_id) if binder_id is not None else ""
        if not stem.strip("_"):
            stem = fallback  # already engine-named; suffixing would give af3_0007_af3
        elif engine:
            stem = f"{stem}_{safe_stem(engine)}"
        base, n = stem, 2
        while stem in used:
            stem = f"{base}__{n}"
            n += 1
        used.add(stem)
        stems.append(stem)
    return stems


def parse_fasta_pairs(text: str) -> list[tuple[str | None, str]]:
    """``(binder_id, sequence)`` pairs from FASTA text.

    The binder id is the header's **first whitespace token**, which is exactly what
    ``binder-compare extract`` writes and what ``merger._attach_fasta_metadata`` reads
    back, so a structure named from this agrees with the ``binder_id`` in the report.

    Match the merger's rule here even where it looks wrong. A header carrying only tags
    (``>  source=boltzgen``) yields the id ``source=boltzgen``, which is obviously not an
    id -- but the merger will put that same string in the report's ``binder_id`` column,
    and a structure named by a *better* rule would then be unfindable. Consistency with
    the join key beats tidiness.

    Text with no ``>`` at all is a bare list of sequences -- one per line, or separated
    by commas/semicolons -- and yields ``None`` ids, so those designs simply keep the
    engine's legacy names. Handling that here matters: treating a headerless file as
    FASTA would concatenate every line into a single enormous "sequence".
    """
    if ">" not in text:
        return [(None, tok) for tok in re.split(r"[;,\s]+", text.strip()) if tok]

    pairs: list[tuple[str | None, str]] = []
    pending: str | None = None
    parts: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if parts:
                pairs.append((pending, "".join(parts)))
                parts = []
                pending = None
            tokens = line[1:].split()
            pending = tokens[0] if tokens else None
            continue
        parts.append(line)
    if parts:
        pairs.append((pending, "".join(parts)))
    return pairs
