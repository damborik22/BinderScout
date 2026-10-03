"""Screen a candidate design-loss term on the CPU, before it costs a campaign.

Why this exists
---------------
A Mosaic design-loss arm costs a full hallucination campaign (>24 GB VRAM) plus refolds
on two independent engines -- hours. Most bad candidate terms are not *mediocre*, they are
**wrongly shaped**, and the wrong shape is visible from the gradient in seconds.

Worked example, 2026-09-29. Upstream Mosaic added ``UnigramExcess`` --
``sum(relu(empirical - natural)**2)`` over amino-acid frequencies -- and it looked like the
generation-side answer to our composition problem. It is not. Because the penalty is
one-sided ABOVE the natural marginal, it is inactive on exactly the residues hallucination
over-produces (E, T, K, S, D all sit above their marginal) and active only on the eight
that sit below it, five of which are hydrophobic. Measured at a soft PSSM it puts **2.1x
more suppressive gradient on hydrophobics than on all polar/charged residues combined** --
the opposite of what we wanted -- and its value swings 70x across our 65-100 aa length
scan with the distribution held fixed. Both facts are CPU-computable in under a second.
Neither would have been obvious from a campaign's summary metrics; it would have looked
like a term that "didn't help much".

The four checks
---------------
``direction``   At a soft PSSM, does the gradient push the named residue class the way the
                author intends? A loss is minimised, so d(loss)/d(class) > 0 SUPPRESSES
                that class. This catches sign errors and, more usefully, terms whose
                sign is right on average but wrong on the class you care about.
``length``      Evaluate at several binder lengths drawn from one fixed distribution. A
                composition term must not depend on L: our template scans 65->100, so a
                length-confounded term silently penalises short binders, and we already
                fight a length bias elsewhere in the pipeline.
``silence``     A one-sided hinge must be EXACTLY inert when the property is already
                satisfied. A term that always pulls is a term that always distorts.
``order``       Only for terms that claim to care about sequence order. If shuffling a
                sequence moves the value no more than shuffle noise, the term is
                measuring composition (or finite-sample sparsity) and adds nothing over
                a unigram term.

Backend
-------
Uses ``jax.grad`` when jax is importable (inside ``Mosaic/.venv``, where real Mosaic terms
live) and falls back to central finite differences on numpy otherwise -- so the harness
and its tests run in ``binder-eval`` and in CI, with no GPU and no jax.

A screen is advisory. It cannot tell you a term helps; it tells you a term is not
obviously broken, which is the cheap half of the question.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

#: Residue order the harness presents to a term. Callers using a different order must say
#: so via ``alphabet=``; getting it wrong silently permutes every per-class result.
#:
#: **Mosaic does not use this order.** ``mosaic.common.TOKENS`` is
#: ``ARNDCQEGHILKMFPSTWYV`` (checked 2026-10-03). Screening a real Mosaic loss term with
#: the default below therefore feeds it a permuted composition and every per-class number
#: is wrong while looking entirely plausible. Pass ``alphabet=TOKENS`` for Mosaic terms.
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"

#: The class our composition problem is about. Y is included by convention; excluding it
#: moves the natural fraction from ~0.379 to ~0.349, and our shipped
#: ``min_hydrophobic_frac >= 0.40`` floor sits above BOTH -- which is independent evidence
#: the floor is mis-set rather than that a pool is bad.
HYDROPHOBIC = "AVILMFWYC"

_EPS = 1e-6


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    numbers: dict = field(default_factory=dict)


@dataclass
class Screen:
    term: str
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def report(self) -> str:
        head = f"{'PASS' if self.ok else 'FLAG'}  {self.term}"
        lines = [head, "=" * len(head)]
        for c in self.checks:
            lines.append(f"  [{'ok  ' if c.passed else 'FLAG'}] {c.name}: {c.detail}")
        return "\n".join(lines)


# ── numeric backend ──────────────────────────────────────────────────────────────


def _grad(fn, pssm: np.ndarray) -> np.ndarray:
    """d(fn)/d(pssm). jax.grad where available, central differences otherwise."""
    try:
        import jax
        import jax.numpy as jnp

        return np.asarray(jax.grad(lambda x: fn(x))(jnp.asarray(pssm)))
    except Exception:
        g = np.zeros_like(pssm, dtype=float)
        h = 1e-5
        it = np.nditer(pssm, flags=["multi_index"])
        while not it.finished:
            i = it.multi_index
            up, dn = pssm.copy(), pssm.copy()
            up[i] += h
            dn[i] -= h
            g[i] = (float(fn(up)) - float(fn(dn))) / (2 * h)
            it.iternext()
        return g


def uniform_pssm(length: int, alphabet: str = ALPHABET) -> np.ndarray:
    """A maximally soft sequence -- the state early hallucination is actually in."""
    n = len(alphabet)
    return np.full((length, n), 1.0 / n, dtype=float)


def pssm_from_frequencies(length: int, freqs: dict[str, float], alphabet: str = ALPHABET) -> np.ndarray:
    """Every position carries the same composition, so composition is isolated from order."""
    row = np.array([freqs.get(a, 0.0) for a in alphabet], dtype=float)
    total = row.sum()
    if total <= 0:
        raise ValueError("frequencies sum to zero")
    return np.tile(row / total, (length, 1))


def pssm_from_sequence(seq: str, alphabet: str = ALPHABET) -> np.ndarray:
    """A one-hot PSSM, for order-sensitivity checks."""
    idx = {a: i for i, a in enumerate(alphabet)}
    out = np.zeros((len(seq), len(alphabet)), dtype=float)
    for pos, aa in enumerate(seq):
        if aa in idx:
            out[pos, idx[aa]] = 1.0
    return out


def _class_mask(residues: str, alphabet: str) -> np.ndarray:
    return np.array([1.0 if a in residues else 0.0 for a in alphabet], dtype=float)


# ── the four checks ──────────────────────────────────────────────────────────────


def check_direction(
    term,
    *,
    residues: str = HYDROPHOBIC,
    intent: str,
    probe_freqs: dict[str, float] | None = None,
    length: int = 65,
    alphabet: str = ALPHABET,
    ratio_tol: float = 1.0,
) -> Check:
    """Does the gradient push *residues* the way *intent* says?

    ``intent="promote"`` wants NEGATIVE mean gradient on the class (increasing it lowers
    the loss); ``intent="suppress"`` wants positive. The comparison is against the
    complement class, because a term can have the right sign overall and the wrong sign
    where it matters -- which is exactly how ``UnigramExcess`` reads as reasonable.
    """
    if intent not in ("promote", "suppress"):
        raise ValueError("intent must be 'promote' or 'suppress'")
    # Probe where the term is ACTIVE. A one-sided hinge is inert at a uniform PSSM by
    # design (uniform hydrophobic fraction is 9/20 = 0.45, above any sane target), so
    # probing only at uniform would flag a correct deficit hinge and wave through a term
    # that is active-but-wrongly-signed. Pass the violating composition explicitly.
    probe = (
        uniform_pssm(length, alphabet) if probe_freqs is None else pssm_from_frequencies(length, probe_freqs, alphabet)
    )
    g = _grad(term, probe)
    mask = _class_mask(residues, alphabet)
    per_res = g.sum(axis=0)
    inside = float((per_res * mask).sum())
    outside = float((per_res * (1.0 - mask)).sum())

    if abs(inside) < _EPS and abs(outside) < _EPS:
        where = "a uniform PSSM" if probe_freqs is None else "the supplied probe composition"
        return Check(
            "direction",
            False,
            f"gradient is zero everywhere at {where} — the term cannot steer design from "
            "there. If this is a one-sided hinge, probe it at a VIOLATING composition "
            "(probe_freqs=) instead; inertness at a satisfying one is what check_silence is for",
            {"inside": inside, "outside": outside},
        )
    want_negative = intent == "promote"
    signed_ok = (inside < 0) if want_negative else (inside > 0)
    # Suppressive pressure on the class relative to everything else.
    rel = abs(inside) / max(abs(outside), _EPS)
    n_out = len(alphabet) - len(residues)
    tail = "and exactly zero elsewhere" if abs(outside) < _EPS else f"(ratio {rel:.2f}x)"
    detail = (
        f"intent={intent}; summed gradient on {residues} = {inside:+.6f}, "
        f"on the other {n_out} residues = {outside:+.6f} {tail}"
    )
    if not signed_ok:
        return Check(
            "direction",
            False,
            detail + f" — WRONG SIGN for intent={intent}",
            {"inside": inside, "outside": outside, "ratio": rel},
        )
    if intent == "suppress" and rel < ratio_tol:
        return Check(
            "direction",
            False,
            detail + f" — right sign but weaker on the target class than off it (<{ratio_tol}x)",
            {"inside": inside, "outside": outside, "ratio": rel},
        )
    return Check("direction", True, detail, {"inside": inside, "outside": outside, "ratio": rel})


def check_length_invariance(
    term,
    *,
    freqs: dict[str, float],
    lengths: tuple[int, ...] = (30, 65, 100, 200),
    alphabet: str = ALPHABET,
    tol: float = 2.0,
    sampled: bool = False,
    n_samples: int = 24,
    seed: int = 0,
) -> Check:
    """Hold the distribution fixed, vary L. A composition term must barely move.

    ``tol`` is the allowed max/min ratio of the value across lengths. 2.0 is generous:
    ``UnigramExcess`` spans ~70x over this range.

    **Two regimes, and the default is the design-time one.**

    ``sampled=False`` (default) builds an exact-frequency PSSM: every position carries the
    same composition, so the value is a deterministic function of composition alone. This
    is the regime a design loss actually runs in -- it sees a SOFT PSSM, and the mean over
    it is smooth, not a finite sample. This mode catches the most common real length bug,
    an extensive term (``sum``) where an intensive one (``mean``) was meant, which grows
    linearly in L and silently penalises long binders.

    ``sampled=True`` draws iid one-hot sequences from *freqs*. This is the DISCRETE regime
    -- scoring a finished sequence rather than steering a design. Finite-sample deviation
    from *freqs* shrinks as 1/sqrt(L), so any term measuring deviation-from-reference looks
    length-confounded here whether or not it is confounded at design time. Upstream's
    ``UnigramExcess`` spans ~13x over 30-200 aa in this mode; so does a correctly-shaped
    one-sided hinge, because both fire on noise excursions. Informative about scoring,
    misleading about design -- which is why it is not the default.
    """
    rng = np.random.default_rng(seed)
    probs = np.array([freqs.get(a, 0.0) for a in alphabet], dtype=float)
    probs = probs / probs.sum()

    def value_at(L: int) -> float:
        if not sampled:
            return float(term(pssm_from_frequencies(L, freqs, alphabet)))
        draws = []
        for _ in range(n_samples):
            idx = rng.choice(len(alphabet), size=L, p=probs)
            oh = np.zeros((L, len(alphabet)), dtype=float)
            oh[np.arange(L), idx] = 1.0
            draws.append(float(term(oh)))
        return float(np.mean(draws))

    vals = {L: value_at(L) for L in lengths}
    finite = [v for v in vals.values() if math.isfinite(v)]
    if not finite:
        return Check("length", False, f"non-finite values: {vals}", vals)
    lo, hi = min(abs(v) for v in finite), max(abs(v) for v in finite)
    if hi < _EPS:
        return Check("length", True, f"identically ~0 at every length ({vals})", vals)
    ratio = hi / max(lo, _EPS)
    detail = "  ".join(f"L={L}:{v:.5f}" for L, v in vals.items()) + f"  (max/min {ratio:.1f}x)"
    return Check("length", ratio <= tol, detail, {**vals, "ratio": ratio})


def check_silence_when_satisfied(
    term,
    *,
    satisfied_freqs: dict[str, float],
    length: int = 65,
    alphabet: str = ALPHABET,
    tol: float = 1e-8,
) -> Check:
    """A one-sided hinge must be EXACTLY inert once the property holds.

    A term that still pulls when nothing is wrong distorts every design it touches, and
    the distortion is invisible because the term's own reported value looks fine.
    """
    p = pssm_from_frequencies(length, satisfied_freqs, alphabet)
    val = float(term(p))
    gnorm = float(np.abs(_grad(term, p)).max())
    ok = gnorm <= tol
    note = ""
    if not ok:
        note = " — still pulling when nothing is wrong"
        if gnorm <= 1e-4:
            # Distinguish a real two-sided term from an inexact probe. If the supplied
            # frequencies do not sum to exactly 1 they are renormalised, which perturbs
            # every entry by ~1e-4 and leaves a term that keys off an exact reference
            # distribution marginally active. A genuinely two-sided penalty is orders of
            # magnitude larger than this.
            note += (
                f" (but |grad| is only {gnorm:.1e} — if this term compares against an exact "
                "reference distribution, check that satisfied_freqs sums to 1.0 before "
                "reading this as two-sidedness)"
            )
    return Check(
        "silence",
        ok,
        f"at a satisfying composition: value={val:.6g}, max|grad|={gnorm:.3g}" + note,
        {"value": val, "max_grad": gnorm},
    )


def check_order_sensitivity(
    term,
    *,
    sequence: str,
    n_shuffles: int = 12,
    seed: int = 0,
    alphabet: str = ALPHABET,
) -> Check:
    """Only meaningful for terms claiming to read sequence ORDER.

    Shuffling destroys adjacency while preserving composition exactly. If the shift is
    inside shuffle noise, the term is reading composition, not order -- which is what
    ``BigramExcess`` turned out to be doing at our 65-100 aa lengths, where only ~100 of
    400 bigram cells can be occupied at all.
    """
    rng = np.random.default_rng(seed)
    base = float(term(pssm_from_sequence(sequence, alphabet)))
    chars = list(sequence)
    vals = []
    for _ in range(n_shuffles):
        rng.shuffle(chars)
        vals.append(float(term(pssm_from_sequence("".join(chars), alphabet))))
    mean, sd = float(np.mean(vals)), float(np.std(vals))
    shift = abs(base - mean)
    informative = shift > 2.0 * max(sd, _EPS)
    return Check(
        "order",
        informative,
        f"native={base:.6g}, shuffled={mean:.6g}+/-{sd:.3g}, shift={shift:.3g}"
        + ("" if informative else " — inside shuffle noise, so it reads composition, not order"),
        {"native": base, "shuffled_mean": mean, "shuffled_sd": sd, "shift": shift},
    )


def screen_composition_term(
    term,
    *,
    name: str,
    intent: str,
    residues: str = HYDROPHOBIC,
    natural_freqs: dict[str, float],
    satisfied_freqs: dict[str, float] | None = None,
    probe_freqs: dict[str, float] | None = None,
    lengths: tuple[int, ...] = (30, 65, 100, 200),
    alphabet: str = ALPHABET,
) -> Screen:
    """The standard three-check screen for a composition term. Order is not checked.

    ``probe_freqs`` is the composition at which DIRECTION is measured, and a one-sided
    hinge needs it: probed at a satisfying composition such a term is inert, which the
    direction check reports as unsteerable rather than guessing what you meant.
    """
    checks = [
        check_direction(term, residues=residues, intent=intent, probe_freqs=probe_freqs, alphabet=alphabet),
        check_length_invariance(term, freqs=natural_freqs, lengths=lengths, alphabet=alphabet),
    ]
    if satisfied_freqs is not None:
        checks.append(check_silence_when_satisfied(term, satisfied_freqs=satisfied_freqs, alphabet=alphabet))
    return Screen(name, checks)


# ── CLI ──────────────────────────────────────────────────────────────────────────


def _cli() -> int:
    """Screen a real Mosaic loss term by import path.

    Run inside the Mosaic venv, where the terms and jax live:

        Mosaic/.venv/bin/python tools/loss_screen.py \\
            --term mosaic.losses.trigram:UnigramExcess --intent promote

    A term is instantiated with no arguments and called as ``term(pssm)``. If a real term
    needs a different call shape, screen it from Python with the check functions directly --
    the checks take any callable ``f(pssm) -> float``.
    """
    import argparse
    import importlib

    ap = argparse.ArgumentParser(description=_cli.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--term", required=True, metavar="module:Class", help="e.g. mosaic.losses.trigram:UnigramExcess")
    ap.add_argument("--intent", required=True, choices=["promote", "suppress"], help="for the residue class")
    ap.add_argument("--residues", default=HYDROPHOBIC, help=f"residue class (default {HYDROPHOBIC})")
    ap.add_argument("--length", type=int, default=65)
    ap.add_argument(
        "--sampled",
        action="store_true",
        help="length check in the DISCRETE (scoring) regime instead of the design-time one. "
        "Read the caveat in check_length_invariance before believing the result.",
    )
    args = ap.parse_args()

    mod_name, _, attr = args.term.partition(":")
    if not attr:
        print(f"--term must be module:Class, got {args.term!r}")
        return 2
    obj = getattr(importlib.import_module(mod_name), attr)
    term = obj() if isinstance(obj, type) else obj

    # Swiss-Prot averages. A term with its own reference distribution uses that internally;
    # this is only the composition the harness probes AT.
    natural = {
        "A": 0.0826,
        "R": 0.0553,
        "N": 0.0406,
        "D": 0.0546,
        "C": 0.0138,
        "Q": 0.0393,
        "E": 0.0674,
        "G": 0.0708,
        "H": 0.0227,
        "I": 0.0591,
        "L": 0.0966,
        "K": 0.0582,
        "M": 0.0241,
        "F": 0.0386,
        "P": 0.0472,
        "S": 0.0661,
        "T": 0.0535,
        "W": 0.0109,
        "Y": 0.0292,
        "V": 0.0686,
    }
    screen = Screen(
        args.term,
        [
            check_direction(term, residues=args.residues, intent=args.intent, length=args.length),
            check_length_invariance(term, freqs=natural, sampled=args.sampled),
            check_silence_when_satisfied(term, satisfied_freqs=natural, length=args.length),
        ],
    )
    print(screen.report())
    print(
        "\nAdvisory. A pass means the term is not obviously mis-shaped — it does not mean "
        "the term helps. That still costs a campaign, judged on AF3 or ESMFold2 and never "
        "on Boltz-2, which Mosaic optimises by construction."
    )
    return 0 if screen.ok else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
