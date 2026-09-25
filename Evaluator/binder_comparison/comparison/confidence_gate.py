"""BindCraft's confidence filters, ported to our refold columns (advisory).

BindCraft gates its designs on a conjunctive panel whose confidence half needs
no Rosetta: interface pAE, binder pLDDT and interface pTM. Those thresholds are
tuned on de novo minibinders of exactly the class we design, and they cost
nothing to evaluate on columns the report already carries — which matters most
for RFD3, a diffusion model that emits no quality score at all.

SHADOW MODE. This annotates and excludes nothing. ``would_exclude_confidence``
records what a hard gate *would* have dropped so its false-negative rate can be
measured against outcome labels before anyone turns it on. It must also never be
used to choose which designs get measured by something more expensive — that is
selection, and it destroys the very data needed to validate the flag.

Thresholds are BindCraft's own defaults (``settings_filters/default_filters.json``):

===================  =========================  ====================================
BindCraft            here                       note
===================  =========================  ====================================
Average_i_pAE 0.35   ``<= 10.85`` Å             normalised there, Ångströms here
Average_pLDDT 0.8    ``>= 0.8``                 same 0–1 scale
Average_i_pTM 0.5    ``>= 0.5``                 interface head, see below
===================  =========================  ====================================

**The i_pAE conversion is exact, not approximate.** ColabDesign divides PAE by
31.0 (``colabdesign/af/loss.py:252``), so 0.35 → 10.85 Å. It is not 31.75, which
is the last PAE bin *centre* rather than the divisor. And the quantity matches:
BindCraft symmetrises the PAE matrix and means it over the whole binder×target
block, which is identically ``(pae_bt_mean + pae_tb_mean) / 2``. All three of our
engines write ``pae_bt`` as binder-rows × target-cols and share AF2's 64-bin
discretisation, so one constant serves all three.

**ESMFold2's scalar ``iptm`` is the wrong column.** Its refold script says so
outright: the scalar "is chain-averaged and can be diluted", while
``pair_chains_iptm``'s off-diagonal "is the meaningful interface number for a
binder". On the six real designs in the golden pool the scalar runs +0.137 to
+0.239 above the pair value. AF3 and Boltz-2 need no such care — for a two-chain
complex their ``iptm`` is already the interface quantity.

**Boltz-2 emits no complex pTM**, only a binder-monomer pTM, so pTM is not part
of this gate rather than being silently computed from a different quantity.
"""

from __future__ import annotations

import pandas as pd

# ColabDesign normalises PAE by this before BindCraft thresholds it.
PAE_NORMALISER = 31.0
BINDCRAFT_IPAE_NORMALISED = 0.35

IPAE_MAX_ANGSTROM = BINDCRAFT_IPAE_NORMALISED * PAE_NORMALISER  # 10.85
PLDDT_MIN = 0.8
IPTM_MIN = 0.5

# engine -> the interface-iPTM column to read, most specific first. ESMFold2's
# bare `iptm` is deliberately absent: it is chain-averaged, not the interface.
_IPTM_COLS: dict[str, tuple[str, ...]] = {
    "boltz": ("boltz_iptm",),
    "af3": ("af3_iptm",),
    "esmfold2": ("esmfold2_iptm_pair", "esmfold2_chain_iptm_interface"),
}
_PLDDT_COL = "{engine}_plddt_binder_mean"
_PAE_BT_COL = "{engine}_pae_bt_mean"
_PAE_TB_COL = "{engine}_pae_tb_mean"


def _num(row: pd.Series, col: str) -> float | None:
    """A float from one cell, or None.

    ``pd.notna("")`` is True, so a blank object cell used to reach ``float()``
    and raise. Anything non-numeric is absent, not an error.
    """
    if col not in row.index:
        return None
    value = pd.to_numeric(row[col], errors="coerce")
    return None if pd.isna(value) else float(value)


def _first_present(row: pd.Series, candidates: tuple[str, ...]) -> float | None:
    for col in candidates:
        value = _num(row, col)
        if value is not None:
            return value
    return None


def _get(row: pd.Series, col: str) -> float | None:
    return _num(row, col)


def annotate_confidence_gate(df: pd.DataFrame) -> pd.DataFrame:
    """Add the advisory confidence-gate columns. Never drops or reorders.

    Adds, per engine present, ``<engine>_ipae_ang``; and overall
    ``passes_confidence_gate`` (NA when no engine was measured),
    ``confidence_fail_reasons``, ``confidence_n_engines`` and
    ``would_exclude_confidence``.
    """
    out = df.copy()
    ipae_cols: dict[str, list[float | None]] = {}
    passes: list[bool | None] = []
    reasons: list[str] = []
    missing: list[str] = []
    n_engines: list[int] = []

    for _, row in out.iterrows():
        failures: list[str] = []
        unchecked: list[str] = []
        measured = 0
        for engine in _IPTM_COLS:
            iptm = _first_present(row, _IPTM_COLS[engine])
            plddt = _get(row, _PLDDT_COL.format(engine=engine))
            bt = _get(row, _PAE_BT_COL.format(engine=engine))
            tb = _get(row, _PAE_TB_COL.format(engine=engine))

            ipae = None
            if bt is not None and tb is not None:
                ipae = (bt + tb) / 2.0
            elif bt is not None or tb is not None:
                # One direction only: still a real measurement of that side.
                ipae = bt if bt is not None else tb
            # Collected positionally, NOT written with .loc[row.name] -- that
            # writes to every row sharing an index label, so duplicate labels
            # silently give all of them the last row's value.
            ipae_cols.setdefault(f"{engine}_ipae_ang", []).append(
                None if ipae is None else round(ipae, 3)
            )

            if iptm is None and plddt is None and ipae is None:
                continue
            measured += 1
            # A threshold we could not evaluate is NOT a pass. Recording it
            # separately keeps "measured and good" distinct from "never checked":
            # esmfold2_iptm_pair is NaN whenever the model returns no
            # pair_chains_iptm, and an interface iPTM of 0.12 used to sail
            # through a 0.5 gate with nothing written down.
            if iptm is None:
                unchecked.append(f"{engine}_iptm")
            elif iptm < IPTM_MIN:
                failures.append(f"{engine}_iptm<{IPTM_MIN}")
            if plddt is None:
                unchecked.append(f"{engine}_plddt")
            elif plddt < PLDDT_MIN:
                failures.append(f"{engine}_plddt<{PLDDT_MIN}")
            if ipae is None:
                unchecked.append(f"{engine}_ipae")
            elif ipae > IPAE_MAX_ANGSTROM:
                failures.append(f"{engine}_ipae>{IPAE_MAX_ANGSTROM:g}A")

        n_engines.append(measured)
        # No engine measured this design: absence of evidence, not a failure.
        # A measured failure is False. Otherwise a clean True requires that every
        # threshold was actually evaluated -- a skipped check yields NA.
        if measured == 0:
            passes.append(None)
        elif failures:
            passes.append(False)
        else:
            passes.append(None if unchecked else True)
        reasons.append(";".join(failures))
        missing.append(";".join(unchecked))

    for col, values in ipae_cols.items():
        if any(v is not None for v in values):
            out[col] = values
    out["confidence_n_engines"] = n_engines
    out["passes_confidence_gate"] = pd.array(passes, dtype="boolean")
    out["confidence_fail_reasons"] = reasons
    out["confidence_missing"] = missing
    # Shadow mode: what a hard gate WOULD drop. An unmeasured design is never
    # excluded, so this is strictly "measured and failed".
    out["would_exclude_confidence"] = [p is False for p in passes]
    return out
