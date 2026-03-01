"""Output writers for FASTA, CSV, and JSON."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path

import pandas as pd


def write_fasta(
    sequences: Iterable[str],
    path: str | Path,
    headers: Iterable[str] | None = None,
    tags: Iterable[dict] | None = None,
    line_width: int = 0,
) -> None:
    """Write sequences to a FASTA file.

    Args:
        sequences: Amino acid strings.
        path:      Output path.
        headers:   One header per sequence (without '>').
                   Defaults to '>seq_{i}'.
        tags:      Optional per-sequence dicts of key=value tags
                   appended to the header line.
        line_width: Wrap sequence at this many chars. 0 = no wrap.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sequences = list(sequences)
    if headers is None:
        headers = [f"seq_{i}" for i in range(len(sequences))]
    else:
        headers = list(headers)
    if tags is None:
        tags = [{} for _ in sequences]
    else:
        tags = list(tags)

    with path.open("w") as fh:
        for header, seq, tag_dict in zip(headers, sequences, tags):
            tag_str = "  ".join(f"{k}={v}" for k, v in tag_dict.items())
            full_header = f">{header}  {tag_str}".rstrip()
            fh.write(full_header + "\n")
            if line_width > 0:
                for i in range(0, len(seq), line_width):
                    fh.write(seq[i : i + line_width] + "\n")
            else:
                fh.write(seq + "\n")


def write_csv(df: pd.DataFrame, path: str | Path, **kwargs) -> None:
    """Write a DataFrame to CSV, creating parent dirs as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, **kwargs)


def write_json(data: dict | list, path: str | Path, indent: int = 2) -> None:
    """Write JSON, replacing NaN/Inf with null."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _clean(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_clean(x) for x in obj]
        return obj

    with path.open("w") as fh:
        json.dump(_clean(data), fh, indent=indent)
