"""The refold-engine registry: the one place that names the engines of a panel.

A panel is exactly three slots: ``boltz`` (the anchor), ``second`` (AF3 by default, or
Protenix) and ``esmfold2``. A four-engine panel cannot be expressed. Adding another
second-slot engine later is one row in ``_ENGINES`` plus its name in ``SECOND_ENGINES``.

Every value here is a literal that used to be spelled out at several call sites
(per-engine output directory, results CSV, ``*_pae_iptm`` / ``*_ipsae_min`` columns,
structure-path columns, binder chain id, iPSAE pass threshold). The column prefix is the
real engine name, never a stand-in.
"""

from __future__ import annotations

from dataclasses import dataclass

# DunbrackLab iPSAE cutoff (10 A). Kept as a literal so this module stays import-light;
# scoring.IPSAE_PASS_THRESHOLD carries the same value.
_IPSAE_PASS_THRESHOLD = 0.61


@dataclass(frozen=True)
class Engine:
    name: str
    display: str
    prefix: str
    refold_dir: str
    results_csv: str
    iptm_col: str
    ipsae_col: str
    pdb_cols: tuple[str, ...]
    binder_chain: str
    default_threshold: float
    #: Row/column order of the PAE matrix this engine's refold saves (``<prefix>_pae_file``):
    #: ``"binder_target"`` ([binder|target], Boltz-2 and every second-engine adapter, which
    #: re-block before saving) or ``"target_binder"`` (token order, target first: AF3, ESMFold2).
    pae_order: str = "target_binder"


@dataclass(frozen=True)
class Panel:
    boltz: Engine
    second: Engine
    esmfold2: Engine

    @property
    def engines(self) -> tuple[Engine, Engine, Engine]:
        return (self.boltz, self.second, self.esmfold2)

    @property
    def iptm_cols(self) -> list[str]:
        return [e.iptm_col for e in self.engines]

    @property
    def ipsae_cols(self) -> list[str]:
        return [e.ipsae_col for e in self.engines]

    @property
    def label(self) -> str:
        return " + ".join(e.display for e in self.engines)

    @property
    def slug(self) -> str:
        return "+".join(e.name for e in self.engines)


_ENGINES: dict[str, Engine] = {
    "boltz": Engine(
        name="boltz",
        display="Boltz-2",
        prefix="boltz",
        refold_dir="refold_boltz2",
        results_csv="boltz2_results.csv",
        # Boltz-2 is the one engine whose iPSAE column carries the "pae" infix
        # (add_boltz_ipsae_from_files), unlike the "<prefix>_ipsae_min" of the others.
        iptm_col="boltz_pae_iptm",
        ipsae_col="boltz_pae_ipsae_min",
        pdb_cols=("boltz_pdb", "boltz_cif"),
        binder_chain="A",  # Boltz-2 writes the binder first
        default_threshold=_IPSAE_PASS_THRESHOLD,
        pae_order="binder_target",
    ),
    "af3": Engine(
        name="af3",
        display="AF3",
        prefix="af3",
        refold_dir="refold_af3",
        results_csv="af3_results.csv",
        iptm_col="af3_pae_iptm",
        ipsae_col="af3_ipsae_min",
        pdb_cols=("af3_pdb", "af3_cif"),
        binder_chain="B",  # target first, binder second
        default_threshold=_IPSAE_PASS_THRESHOLD,
    ),
    "protenix": Engine(
        name="protenix",
        display="Protenix",
        prefix="protenix",
        refold_dir="refold_protenix",
        results_csv="protenix_results.csv",
        iptm_col="protenix_pae_iptm",
        ipsae_col="protenix_ipsae_min",
        pdb_cols=("protenix_pdb", "protenix_cif"),
        binder_chain="B",  # the adapter writes target = chain A, binder = chain B
        default_threshold=_IPSAE_PASS_THRESHOLD,
        # The shared second-engine driver re-blocks to [binder|target] before np.save
        # (second_engine_driver._score_prediction), whatever the engine's native order was.
        pae_order="binder_target",
    ),
    "esmfold2": Engine(
        name="esmfold2",
        display="ESMFold2",
        prefix="esmfold2",
        refold_dir="refold_esmfold2",
        results_csv="esmfold2_results.csv",
        iptm_col="esmfold2_pae_iptm",
        ipsae_col="esmfold2_ipsae_min",
        pdb_cols=("esmfold2_pdb", "esmfold2_cif"),
        binder_chain="B",
        default_threshold=_IPSAE_PASS_THRESHOLD,
    ),
}

# The engines that may fill the panel's second slot.
SECOND_ENGINES: tuple[str, ...] = ("af3", "protenix")


def engine(name: str) -> Engine:
    """The registered engine called *name*."""
    try:
        return _ENGINES[name]
    except KeyError:
        raise ValueError(f"unknown engine {name!r}; registered: {', '.join(_ENGINES)}") from None


def resolve_panel(second: str = "af3") -> Panel:
    """The three-engine panel with *second* in the second slot.

    Only the second slot is selectable: ``boltz`` and ``esmfold2`` are fixed, so anything
    outside ``SECOND_ENGINES`` is refused rather than coerced into a four-engine panel.
    """
    if second not in SECOND_ENGINES:
        valid = ", ".join(repr(s) for s in SECOND_ENGINES)
        raise ValueError(f"unknown second engine {second!r}; valid values: {valid}")
    return Panel(boltz=_ENGINES["boltz"], second=_ENGINES[second], esmfold2=_ENGINES["esmfold2"])
