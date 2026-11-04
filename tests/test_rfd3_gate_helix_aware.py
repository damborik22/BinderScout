"""rfd3_gate.check_geometry on short helical binders, and on the coil it exists to catch.

Why this exists. The geometry gate was calibrated on 60-100 aa binders against a 389-aa target and
asked two things of every binder: Rg/expected <= 1.45 and >= 0.80 long-range CA contacts per residue.
A helix has neither property -- a straight helix has NO contact between residues >= 9 apart, and is
longer than a compact fold of its own length -- so a compact helical 26-30 aa binder was rejected
("long-range contacts 0.00/res"), and below 25 residues the gate declined to look at all, which kept
the CALCA smoke example (binders 20-30 aa) from ever exercising it.

MEASURED, not guessed. Real RFD3 backbones against the shipped CALCA target (32-aa helix,
hotspots A5,A9,A12), 8 backbones per row, rfd3 at the template's settings. "good" is the shipped YAML;
"broken" is the same YAML without `infer_ori_strategy: hotspots`. Means; the criteria are the ones the
gate computes (Rg = Rg/expected-compact, lr = long-range contacts per residue, hx = helix fraction by
CA i,i+4 distance) plus |fixed_com| from the sidecar (the origin gate) and d_com (binder COM to target
COM, A). T = diffusion steps (T=20 is the smoke example's setting, T=200 the template's); n is the number of
backbones. Cells are mean (min-max).

  T   L  set     n  Rg/exp        lr/res        helix         |fixed_com|  d_com
  200  20  good    8  1.20 (0.98-1.35)  0.06 (0.00-0.20)  0.85 (0.62-1.00)  22.72 (22.72-22.72)  23.3 (17.5-27.0)
  200  26  good    4  1.17 (1.00-1.32)  0.20 (0.00-0.65)  0.78 (0.59-0.86)  22.70 (22.70-22.70)  22.9 (20.8-26.9)
  20  20  good    8  1.11 (0.95-1.30)  0.08 (0.00-0.20)  0.77 (0.50-1.00)  22.72 (22.72-22.72)  23.6 (18.5-28.2)
  20  20  broken  8  1.31 (1.29-1.39)  0.00 (0.00-0.00)  0.95 (0.75-1.00)  0.10 (0.10-0.10)  7.9 (3.5-10.0)
  20  26  good    8  1.14 (0.98-1.55)  0.29 (0.00-0.85)  0.54 (0.23-0.82)  22.70 (22.70-22.70)  21.9 (19.0-24.4)
  20  26  broken  8  1.41 (1.06-1.57)  0.02 (0.00-0.19)  0.89 (0.68-1.00)  0.10 (0.10-0.10)  7.7 (5.8-10.1)
  20  30  good    8  1.21 (1.03-1.44)  0.18 (0.00-0.63)  0.63 (0.46-0.81)  22.68 (22.68-22.68)  20.9 (17.5-23.9)
  20  30  broken  8  1.42 (1.16-1.63)  0.02 (0.00-0.17)  0.81 (0.65-1.00)  0.10 (0.10-0.10)  6.3 (3.7-9.9)
  20  40  good    8  1.14 (0.97-1.48)  0.37 (0.15-0.55)  0.65 (0.42-0.89)  22.62 (22.62-22.62)  20.7 (18.4-25.5)
  20  40  broken  8  1.27 (1.11-1.74)  0.23 (0.00-0.55)  0.81 (0.61-0.92)  0.10 (0.10-0.10)  6.9 (3.7-8.8)
  20  60  good    8  1.18 (1.01-1.26)  0.35 (0.12-0.53)  0.70 (0.50-0.79)  22.53 (22.53-22.53)  20.8 (19.1-22.5)
  20  60  broken  8  1.23 (1.13-1.44)  0.36 (0.08-0.87)  0.74 (0.57-0.89)  0.10 (0.10-0.10)  5.2 (3.5-7.2)

What the table says, and what the gate therefore does:
  * lr cannot be the criterion for a helical binder: good backbones at 20-60 aa score 0.06-0.37 against
    a 0.80 floor, so the old gate would have failed every one of them.
  * Rg/expected is not either: individual good backbones reach 1.55; an ideal straight 26-mer is 1.51.
  * Helix fraction does separate a helical binder from the coil failure (0.27 by DSSP in the measured
    broken coil pool of the 389-aa target, polyproline 0.23; this gate's CA-based measure gives a polyproline
    chain 0.00, see the coil test), so a helical backbone (own hx >= 0.40, at most HELIX_EXEMPT_MAX_CA aa) is passed with a plain
    statement of what was not verified, and anything below keeps the original two criteria.
  * On THIS target the broken set (measured at T=20 only; no T=200 broken run completed) is NOT
    geometrically a coil: it is as helical as the good set. Only
    |fixed_com| (0.10 vs ~22.7 A, no overlap at any length) and d_com (<= 10 vs >= 17 A) tell them
    apart. So the geometry gate cannot catch a mis-centred helical run; the origin gate does, and the
    gate says so rather than implying otherwise. d_com is NOT added as a criterion: its threshold
    depends on the target's size and one target is not a calibration.
  * NOT measured here: a real coil. The 389-aa target whose broken run gave the coil (Rg/expected 1.90,
    contacts 0.28/res) is not in this tree, so the coil verdict is shown on a synthetic polyproline chain and
    rests on those recorded numbers; the 0.40 cut sits between the lowest pooled good mean measured here
    (0.54) and that pool's recorded 0.27, which was a DSSP value, not this gate's CA-based one.
"""

from __future__ import annotations

import importlib.util
import math
import os
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "tools" / "rfd3_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("rfd3_gate_helix_under_test", GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _helix(n: int):
    """Ideal alpha helix: 2.3 A radius, 100 deg and 1.5 A per residue."""
    return [(2.3 * math.cos(math.radians(100 * i)), 2.3 * math.sin(math.radians(100 * i)), 1.5 * i) for i in range(n)]


def _coil(n: int):
    """Polyproline-II-like extended chain: 3.1 A per residue, 3 residues per turn, 2.8 A radius."""
    return [(2.8 * math.cos(math.radians(120 * i)), 2.8 * math.sin(math.radians(120 * i)), 3.1 * i) for i in range(n)]


def _globule(n: int, seed: int = 0, radius: float = 11.0):
    """A compact, non-helical fold: a seeded 3.8 A-step random walk confined to a sphere, no clashes."""
    rnd = random.Random(seed)
    while True:
        pts = [(0.0, 0.0, 0.0)]
        for _ in range(1, n):
            for _try in range(200):
                v = [rnd.gauss(0, 1) for _ in range(3)]
                norm = math.sqrt(sum(a * a for a in v))
                q = tuple(pts[-1][k] + 3.8 * v[k] / norm for k in range(3))
                if math.sqrt(sum(a * a for a in q)) < radius and all(math.dist(q, p) >= 4.5 for p in pts[:-1]):
                    break
            else:
                break
            pts.append(q)
        if len(pts) == n:
            return pts


def _write_cif(path: Path, binder) -> Path:
    lines = [
        "data_x",
        "loop_",
        "_atom_site.label_atom_id",
        "_atom_site.label_asym_id",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
    ]
    for i in range(5):
        lines.append(f"CA A {i * 3.8:.3f} 40.000 0.000")
    for x, y, z in binder:
        lines.append(f"CA B {x:.3f} {y:.3f} {z:.3f}")
    lines.append("#")
    path.write_text("\n".join(lines) + "\n")
    return path


def _verdict(tmp_path, binder, capsys):
    gate = _load_gate()
    _write_cif(tmp_path / "d0.cif", binder)
    verdict = gate.check_geometry(str(tmp_path / "*.cif"))
    return verdict, capsys.readouterr().out


class TestHelicalBinderIsNotRejected:
    def test_compact_helical_26_mer_passes(self, tmp_path, capsys):
        verdict, out = _verdict(tmp_path, _helix(26), capsys)
        assert verdict is True
        assert "helix-dominated" in out, "the helical branch was not the one reached"

    def test_helical_binder_says_what_it_did_not_verify(self, tmp_path, capsys):
        verdict, out = _verdict(tmp_path, _helix(26), capsys)
        assert verdict is True
        assert "NOT VERIFIED" in out and "ORIGIN GATE" in out

    def test_control_the_old_criteria_would_have_failed_it(self, tmp_path):
        """The helix has 0.00 long-range contacts/res: the old rule's verdict is a failure."""
        gate = _load_gate()
        _, lr, hx = gate.geom(_helix(26))
        assert lr < 0.80 and hx >= gate.HELIX_DOMINANT


class TestCoilStillFails:
    def test_extended_coil_fails(self, tmp_path, capsys):
        verdict, out = _verdict(tmp_path, _coil(60), capsys)
        assert verdict is False
        assert "FAIL" in out and "helix-dominated" not in out

    def test_extended_coil_at_the_new_floor_fails(self, tmp_path, capsys):
        gate = _load_gate()
        verdict, _ = _verdict(tmp_path, _coil(gate.MIN_BINDER_CA), capsys)
        assert verdict is False

    def test_control_coil_is_below_the_helix_threshold(self):
        gate = _load_gate()
        rgr, lr, hx = gate.geom(_coil(60))
        assert hx < gate.HELIX_DOMINANT and rgr > 1.45 and lr < 0.80

    def test_compact_nonhelical_fold_still_passes_the_original_criteria(self, tmp_path, capsys):
        gate = _load_gate()
        _, _, hx = gate.geom(_globule(48))
        assert hx < gate.HELIX_DOMINANT, "control: the globule must take the non-helical branch"
        verdict, out = _verdict(tmp_path, _globule(48), capsys)
        assert verdict is True
        assert "helix-dominated" not in out and "want >=0.80" in out


class TestHelixExemptionIsBounded:
    """The exemption covers a helical backbone of a measured length; it does not cover a long rod or a mixed pool."""

    def test_a_long_straight_helix_is_not_exempt(self, tmp_path, capsys):
        gate = _load_gate()
        for n in (gate.HELIX_EXEMPT_MAX_CA + 1, 90, 150):
            for f in tmp_path.glob("*.cif"):
                f.unlink()
            verdict, out = _verdict(tmp_path, _helix(n), capsys)
            assert verdict is False, f"a {n}-aa straight helix passed the geometry gate"
            assert "helix-dominated" not in out

    def test_a_helix_at_the_measured_maximum_is_still_exempt(self, tmp_path, capsys):
        gate = _load_gate()
        verdict, _ = _verdict(tmp_path, _helix(gate.HELIX_EXEMPT_MAX_CA), capsys)
        assert verdict is True

    def test_a_coil_is_not_rescued_by_a_helix_in_the_same_pool(self, tmp_path, capsys):
        gate = _load_gate()
        _write_cif(tmp_path / "a_helix.cif", _helix(30))
        _write_cif(tmp_path / "b_coil.cif", _coil(30))
        verdict = gate.check_geometry(str(tmp_path / "*.cif"))
        out = capsys.readouterr().out
        assert verdict is False, "the pool MEAN of helix fraction exempted the coil"
        assert "FAIL" in out


class TestFloor:
    def test_binder_below_the_floor_is_honestly_unverifiable(self, tmp_path, capsys):
        gate = _load_gate()
        n = gate.MIN_BINDER_CA - 1
        verdict, out = _verdict(tmp_path, _helix(n), capsys)
        assert verdict is None
        assert f"{n} aa" in out and "minimum" in out and "no chain-B CA atoms" not in out

    def test_smoke_example_lengths_are_measured(self, tmp_path, capsys):
        """The CALCA smoke example designs 20-30 aa binders; every one of those lengths is checked."""
        for n in (20, 24, 26, 30):
            verdict, _ = _verdict(tmp_path, _helix(n), capsys)
            assert verdict is True, f"{n} aa helix was not measured and passed"

    def test_floor_is_the_shortest_length_measured(self):
        assert _load_gate().MIN_BINDER_CA == 20


class TestExitCodes:
    """The call site: `python rfd3_gate.py geometry <glob>` is what the run scripts execute."""

    def _rc(self, tmp_path, binder):
        _write_cif(tmp_path / "d0.cif", binder)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        p = subprocess.run(
            [sys.executable, str(GATE_PATH), "geometry", str(tmp_path / "*.cif")],
            capture_output=True,
            text=True,
            env=env,
        )
        return p.returncode, p.stdout

    def test_helix_exits_0(self, tmp_path):
        rc, out = self._rc(tmp_path, _helix(26))
        assert rc == 0 and "helix-dominated" in out

    def test_coil_exits_1(self, tmp_path):
        rc, _ = self._rc(tmp_path, _coil(60))
        assert rc == 1

    def test_too_short_exits_2(self, tmp_path):
        rc, out = self._rc(tmp_path, _helix(12))
        assert rc == 2 and "CANNOT VERIFY" in out


DATA = REPO / "tests" / "data" / "rfd3_real_ca"


class TestRealRfd3Backbones:
    """CA-only copies of real rfd3 output against the shipped CALCA target (see the table above)."""

    def _verdict(self, names, tmp_path, capsys):
        import shutil

        for n in names:
            shutil.copy(DATA / f"{n}.cif", tmp_path / f"{n}.cif")
        gate = _load_gate()
        verdict = gate.check_geometry(str(tmp_path / "*.cif"))
        return verdict, capsys.readouterr().out

    def test_good_26_mer_the_old_gate_rejected_now_passes(self, tmp_path, capsys):
        gate = _load_gate()
        _, lr, hx = gate.geom(gate.ca_chain(str(DATA / "good_L26_a.cif")))
        assert lr == 0.0 and hx > 0.7, "control: this is the 'long-range contacts 0.00/res' case"
        verdict, out = self._verdict(["good_L26_a", "good_L26_b"], tmp_path, capsys)
        assert verdict is True and "helix-dominated" in out

    def test_good_20_mer_is_checked_not_skipped(self, tmp_path, capsys):
        verdict, out = self._verdict(["good_L20"], tmp_path, capsys)
        assert verdict is True and "CANNOT VERIFY" not in out

    def test_mis_centred_helical_backbone_is_not_claimed_to_be_caught_by_geometry(self, tmp_path, capsys):
        """On the 32-aa helix target the broken (no infer_ori_strategy) backbones are still helices.

        Geometry cannot tell them from good ones; the gate must say so and point at the origin gate
        rather than imply it checked where the binder sits.
        """
        verdict, out = self._verdict(["broken_L26", "broken_L30"], tmp_path, capsys)
        assert verdict is True
        assert "NOT VERIFIED" in out and "where the binder sits" in out and "ORIGIN GATE" in out


class TestRunScriptsNameTheFloor:
    """The shell warning that follows exit 2 must name the real reason, with the gate's own number."""

    def test_template_and_emitter_quote_the_gate_floor(self):
        n = _load_gate().MIN_BINDER_CA
        for path in (
            REPO / "binderscout_examples" / "run_rfd3.sh.template",
            REPO / "configurator" / "configurator.py",
        ):
            assert f"only binders under {n} residues" in path.read_text(), path
