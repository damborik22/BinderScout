"""BindCraft 2 sequence extractor.

BindCraft 2 (Pacesa Lab) is a rewrite of BindCraft, not a new version of it, and
it writes a different output tree. A completed campaign leaves three stage
tables under the project folder::

    1_Trajectories/!_Trajectories.csv   one row per gradient-design attempt
    2_Refolded/!_Refolded.csv           every scored ProteinMPNN candidate, pass and fail
    3_Ranked/!_Ranked.csv               the accepted designs, ranked  <-- we read this

Only the third is a design pool. The first holds the *pre-ProteinMPNN*
hallucinated sequence in its ``Binder_Sequence`` column, which is not a design
anyone should refold; the second mixes ``outcome='rejected'`` rows in with the
passes.

Two schemas, one extractor
--------------------------
The BindCraft 2 pools already archived in this project were produced by a
pre-1.0 build whose column vocabulary differs from the shipped v1.0.0: TitleCase
``Rank`` / ``Design`` / ``Sequence`` in a flat ``<target>_ranked.csv``, against
v1.0.0's lowercase ``rank`` / ``design`` / ``Binder_Sequence`` in
``3_Ranked/!_Ranked.csv``. An extractor written against the current
documentation alone cannot read our own archive, so both are supported through
an explicit alias map rather than a guess. The two are distinguished only by
which column names are present — nothing in either file records a version.

Ranking
-------
``i_pDAE`` is BindCraft 2's own ranking metric and the ``rank`` column is a
plain descending sort on it. That matters twice over:

* It is **not** i_pTM. Verified across all 100 rows of the two delivered pools:
  ranking by i_pTM reproduces neither file, and every structure's embedded
  campaign settings record ``ranking_metric: i_pDAE``.
* Ties are pervasive — the delivered values are rounded to two decimals, giving
  a 17-way tie in one pool and a 13-way tie in the other. Rank *within* a tie
  block is acceptance order, not quality order, and no assertion here may
  assume the metric is strictly decreasing.

The rank column is read from the tool's own file and never recomputed.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor, disambiguate_ids, resolve_single_match

# Probed in order; the first pattern that matches wins. Within one pattern,
# several matches is an error rather than a guess (resolve_single_match).
#
# Deliberately absent, and each for a reason that bites silently:
#   accepted.csv        the legacy append-only table — it has NO rank column at all
#   ranked_by_*.csv     a user re-sort from `bindcraft rank --on <other metric>`
#   filtered.csv        a post-hoc `bindcraft filter` subset
#   summary.csv         campaign-level aggregates, not designs
# Resolving to any of them would produce a plausible, wrongly-ordered pool.
_TABLE_PATTERNS: tuple[str, ...] = (
    "3_Ranked/!_Ranked.csv",  # v1.0.0 stage layout
    "!_Ranked.csv",  # pointed straight at 3_Ranked/
    "ranked.csv",  # pre-1.0 flat layout
    "*_ranked.csv",  # pre-1.0, as delivered (<target>_ranked.csv)
)

# (canonical purpose) -> column names, newest schema first.
_SEQUENCE_COLS = ("Binder_Sequence", "Sequence")
_DESIGN_COLS = ("design", "Design")
_RANK_COLS = ("rank", "Rank")
_TARGET_COLS = ("targets", "Targets")

# Native metrics whose spelling is the same in both schemas. Everything renamed
# between them (the pre-1.0 `Binder_Helix%` family became `*_Fraction` on a 0–1
# scale in v1.0.0) is deliberately NOT mapped: folding a 0–100 column and a 0–1
# column into one field would mix scales invisibly.
_NATIVE_COL_MAP: dict[str, tuple[str, ...]] = {
    "bindcraft2_ipdae": ("i_pDAE",),
    "bindcraft2_iptm": ("i_pTM",),
    "bindcraft2_ptm": ("pTM",),
    "bindcraft2_plddt": ("pLDDT",),
    "bindcraft2_ipae": ("i_pAE",),
    "bindcraft2_target_plddt": ("Target_pLDDT",),
    "bindcraft2_ss_plddt": ("SS_pLDDT",),
    "bindcraft2_interface_residues": ("Interface_Residues",),
    "bindcraft2_interface_buried_area": ("Interface_BuriedArea",),
    "bindcraft2_interface_hydrophobicity": ("Interface_Hydrophobicity",),
    "bindcraft2_surface_hydrophobicity": ("Surface_Hydrophobicity",),
    "bindcraft2_backbone_clashes": ("Backbone_Clashes",),
    "bindcraft2_binder_rmsd": ("Binder_RMSD",),
    "bindcraft2_target_rmsd": ("Target_RMSD",),
}

_INT_FIELDS = frozenset({"bindcraft2_interface_residues", "bindcraft2_backbone_clashes"})


def _first_present(row_or_cols, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate column that exists, or None."""
    for name in candidates:
        if name in row_or_cols:
            return name
    return None


class BindCraft2Extractor(SequenceExtractor):
    """Extract accepted designs from a BindCraft 2 campaign folder."""

    @property
    def tool_name(self) -> str:
        return "bindcraft2"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        table = self._resolve_table(input_dir)
        if table is None:
            warnings.warn(
                f"BindCraft 2: no ranked table under {input_dir}. Looked for "
                f"{', '.join(_TABLE_PATTERNS)}. A campaign that has not finished writes "
                f"3_Ranked/!_Ranked.csv only once a design is accepted.",
                stacklevel=2,
            )
            return []

        # A real CSV reader, not a split(','): five columns carry quoted commas
        # (one holds a Python dict literal), the delivered files are CRLF, and at
        # least one does not end with a newline.
        df = pd.read_csv(table)
        if df.empty:
            warnings.warn(f"BindCraft 2: {table} has no rows.", stacklevel=2)
            return []

        seq_col = _first_present(df.columns, _SEQUENCE_COLS)
        design_col = _first_present(df.columns, _DESIGN_COLS)
        rank_col = _first_present(df.columns, _RANK_COLS)
        if seq_col is None or design_col is None:
            raise ValueError(
                f"BindCraft 2: {table} has neither schema's identity columns "
                f"(need one of {_SEQUENCE_COLS} and one of {_DESIGN_COLS}); "
                f"found: {list(df.columns)[:12]}"
            )

        self._refuse_multi_target(df, table)

        if rank_col is not None:
            df = self._order_by_native_rank(df, rank_col, table)
        else:
            warnings.warn(
                f"BindCraft 2: {table} has no rank column; keeping file order as the "
                f"native order. Check this is the ranked table and not an append-only one.",
                stacklevel=2,
            )

        results: list[ExtractedBinder] = []
        for _, row in df.iterrows():
            raw = row[seq_col]
            if pd.isna(raw):  # before str(): "NAN" passes the amino-acid validator
                continue
            seq = str(raw).strip().upper()

            if "/" in seq:
                # Upstream strips the separator and treats the chains as one
                # string. We refuse instead: a single-chain refold of a
                # concatenated multi-chain binder is a different molecule, and
                # silently refolding it would look like a result.
                warnings.warn(
                    f"BindCraft 2: {row[design_col]} is a multi-chain binder "
                    f"('/'-separated); skipped, as this pipeline refolds one chain.",
                    stacklevel=2,
                )
                continue

            if not self._validate_sequence(seq):
                continue

            results.append(
                ExtractedBinder(
                    binder_id=f"bindcraft2_{row[design_col]}",
                    sequence=seq,
                    source_tool="bindcraft2",
                    native=self._native_metrics(row),
                )
            )

        disambiguate_ids(results, tool="BindCraft 2")
        return results

    def _resolve_table(self, input_dir: Path) -> Path | None:
        """First pattern that matches wins; ambiguity inside one pattern is an error."""
        for pattern in _TABLE_PATTERNS:
            exact = input_dir / pattern
            if exact.is_file():
                return exact
            matches = [p for p in input_dir.glob(pattern) if p.is_file()]
            if not matches:
                matches = [p for p in input_dir.rglob(pattern) if p.is_file()]
            if matches:
                return resolve_single_match(matches, tool="BindCraft2", what=pattern, input_dir=input_dir)
        return None

    def _refuse_multi_target(self, df: pd.DataFrame, table: Path) -> None:
        """Refuse a multi-target export rather than mis-parse its vector cells.

        In a multi-target campaign every metric cell becomes a ';'-joined vector
        in ``targets`` order, so a plain float() either raises or silently stores
        a string. Detection reads the targets column specifically — NOT a scan
        for ';' anywhere in the row, because the free-text ``Notes`` column
        legitimately contains semicolons in both delivered pools and a whole-row
        check would reject them both.
        """
        target_col = _first_present(df.columns, _TARGET_COLS)
        if target_col is None:
            return
        multi = {str(v) for v in df[target_col].dropna().unique() if ";" in str(v)}
        if multi:
            raise ValueError(
                f"BindCraft 2: {table} is a multi-target campaign "
                f"(e.g. {sorted(multi)[0]!r}). Every metric cell is a ';'-joined vector "
                f"there, which this extractor does not parse. Split the export per target, "
                f"or extract the single-target campaigns separately."
            )

    def _order_by_native_rank(self, df: pd.DataFrame, rank_col: str, table: Path) -> pd.DataFrame:
        """Sort by the tool's own rank column and check it really is 1..N.

        Native rank comes from the tool's raw file and is never recomputed —
        which is also the only correct choice here, because i_pDAE ties are
        pervasive and rank inside a tie block carries information (acceptance
        order) that re-sorting would destroy.
        """
        ranks = pd.to_numeric(df[rank_col], errors="coerce")
        if ranks.isna().any():
            warnings.warn(
                f"BindCraft 2: {table} has non-numeric values in '{rank_col}'; keeping file order instead of sorting.",
                stacklevel=2,
            )
            return df
        ordered = df.assign(_rank=ranks).sort_values("_rank", kind="stable")
        expected = list(range(1, len(ordered) + 1))
        if [int(r) for r in ordered["_rank"]] != expected:
            warnings.warn(
                f"BindCraft 2: '{rank_col}' in {table} is not 1..{len(ordered)} "
                f"(got {[int(r) for r in ordered['_rank']][:5]}...). This is a slice or a "
                f"re-sort of the ranked table, not the table itself; keeping its order.",
                stacklevel=2,
            )
        return ordered.drop(columns=["_rank"])

    def _native_metrics(self, row) -> NativeMetrics:
        """Read whatever native columns this campaign happened to write.

        Every read is optional: a metric column only exists if the campaign set
        a threshold for it, which is why the two delivered pools differ in width
        (62 columns vs 60 — the IDR-protocol one has no Target_RMSD or hotspot
        contact column).
        """
        native = NativeMetrics()
        for field_name, candidates in _NATIVE_COL_MAP.items():
            col = _first_present(row.index, candidates)
            if col is None or pd.isna(row[col]):
                continue
            try:
                value = float(row[col])
            except (TypeError, ValueError):
                continue
            setattr(native, field_name, int(value) if field_name in _INT_FIELDS else value)
        return native
