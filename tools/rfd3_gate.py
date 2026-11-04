"""Backbone-geometry + sequence-composition gate for RFD3.

Round 3 shipped 304 backbones that were extended coils (Rg/expected 1.90, long-range
contacts 0.28/res) because low_memory_mode=true silently randomised the
chunked_pairwise_embedder weights. NOTHING caught it: the old gate checked alanine,
E+R and Shannon entropy only, and a Pro/Gly coil passes all three (Ala 0.016, E+R 0.132,
H 2.47). It then cost a full refold and a wrong conclusion about the epitope.

So gate on GEOMETRY FIRST — before MPNN, before refolding — and on composition with the
axes that actually distinguish a protein from a linker.
"""

import collections
import glob
import gzip
import math
import statistics as st
import sys


def ca_chain(path, chain="B"):
    op = gzip.open if path.endswith(".gz") else open
    xs, hdr = [], []
    for raw in op(path, "rt"):
        l = raw.rstrip("\n")
        if l.startswith("_atom_site."):
            hdr.append(l.strip().split(".")[1])
        elif hdr and l and not l.startswith(("#", "_", "loop_")):
            p = l.split()
            if len(p) < len(hdr):
                continue
            d = dict(zip(hdr, p))
            if d.get("label_atom_id") == "CA" and d.get("label_asym_id") == chain:
                try:
                    xs.append((float(d["Cartn_x"]), float(d["Cartn_y"]), float(d["Cartn_z"])))
                except ValueError:
                    pass
        elif hdr and l.startswith("#"):
            hdr = []
    return xs


def geom(c):
    n = len(c)
    cx = sum(p[0] for p in c) / n
    cy = sum(p[1] for p in c) / n
    cz = sum(p[2] for p in c) / n
    rg = math.sqrt(sum((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2 for p in c) / n)
    lr = sum(
        1
        for i in range(n)
        for j in range(i + 9, n)
        if (c[i][0] - c[j][0]) ** 2 + (c[i][1] - c[j][1]) ** 2 + (c[i][2] - c[j][2]) ** 2 < 64
    )
    hx = [math.dist(c[i], c[i + 4]) for i in range(n - 4)]
    return rg / (2.2 * n**0.38), lr / n, (sum(1 for d in hx if 5.0 <= d <= 7.2) / len(hx) if hx else 0)


def check_origin(pattern, limit=40):
    """Cheapest possible detector, readable straight after the first batch.

    rfd3 records fixed_com (the fixed motif's centre of mass in the output frame) in
    every sidecar .json. With `infer_ori_strategy: hotspots` the frame is centred on the
    hotspot region, so the 389-aa target's COM sits ~23 A away. WITHOUT it, rfd3 centres
    on the whole target COM (fixed_com ~0) and seeds every diffused binder atom there —
    the binder nucleates inside the protein and grows as an extended coil.
    Measured: round-1 2VDY 23.05 A (Rg 10.9) vs round-3 0.008 A (Rg 23.1), and the ApoE4
    RFD3 run, which also omitted the key, 0.02 A (Rg 19.5).
    """
    import json

    mags, rgs = [], []
    for f in sorted(glob.glob(pattern))[:limit]:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        m = d.get("metrics", {})
        fc = m.get("fixed_com")
        if fc:
            mags.append(math.dist(fc, [0, 0, 0]))
        if m.get("radius_of_gyration"):
            rgs.append(m["radius_of_gyration"])
    if not mags:
        print("  ORIGIN GATE: no fixed_com in sidecars — CANNOT VERIFY (not a failure)")
        return None
    mm = st.mean(mags)
    print(f"  sidecars checked  {len(mags)}")
    print(f"  |fixed_com|       {mm:.2f} A   (want >5; round-1 was 23.05, BROKEN round-3 was 0.008)")
    if rgs:
        print(f"  binder Rg         {st.mean(rgs):.1f} A  (round-1 10.9; BROKEN 23.1)")
    ok = mm > 5.0
    print(f"  ORIGIN GATE: {'PASS' if ok else '*** FAIL — infer_ori_strategy: hotspots is missing ***'}")
    return ok


# Fewest chain-B CA atoms the geometry check is run on. 20 is the shortest binder it was MEASURED on (see the
# table in tests/test_rfd3_gate_helix_aware.py); below it the helix fraction rests on too few windows to mean anything.
MIN_BINDER_CA = 20

# Helix fraction (CA i,i+4 distance 5.0-7.2 A) at or above which a backbone is judged helical. The
# failure this gate exists for is an extended coil (measured helix 0.27, polyproline 0.23); a binder that is
# mostly helix is not that failure, whatever its Rg or long-range contacts say. See the measured table.
HELIX_DOMINANT = 0.40


# Longest binder the helix exemption below was MEASURED on. A longer helical binder is not exempt: a single straight
# helix of 60-150 aa has Rg/expected 2.5-4.4 and no long-range contacts, which is exactly what a mis-seeded run
# grows, and nothing measured says such a binder is fine.
HELIX_EXEMPT_MAX_CA = 60


def check_geometry(pattern, limit=40):
    rows = []
    lengths = []
    for f in sorted(glob.glob(pattern))[:limit]:
        c = ca_chain(f)
        if len(c) >= MIN_BINDER_CA:
            rows.append((len(c), *geom(c)))
        elif c:
            lengths.append(len(c))
    if not rows:
        if lengths:
            print(
                f"  GEOMETRY GATE: binder is {max(lengths)} aa, below the {MIN_BINDER_CA}-residue minimum "
                "this gate needs — CANNOT VERIFY (not a failure)"
            )
        else:
            print("  GEOMETRY GATE: no chain-B CA atoms found — CANNOT VERIFY (not a failure)")
        return None
    # Decided PER BACKBONE, not on the pool mean: a mean of 0.5 over one coil and one helix would otherwise
    # exempt the coil. A backbone is exempt only if it is helical itself AND no longer than the exemption was
    # measured on; every other backbone is judged on the original criteria.
    exempt = [r for r in rows if r[3] >= HELIX_DOMINANT and r[0] <= HELIX_EXEMPT_MAX_CA]
    judged = [r for r in rows if r not in exempt]
    print(f"  backbones checked      {len(rows)}")
    print(
        f"  helix fraction         {st.mean(r[3] for r in rows):.2f}   (a backbone counts as helical at "
        f">={HELIX_DOMINANT:.2f}; broken coil pool was 0.27)"
    )
    if exempt:
        # A helix has no long-range contacts (a single straight helix has none at all) and a straight helix is
        # LONGER than a compact fold of the same length, so neither criterion below says anything about it.
        # Applying them rejected a compact helical binder (helix 0.73, Rg/expected 1.23) for "0.00 contacts/res".
        print(
            f"  {len(exempt)} helical backbone(s) of <={HELIX_EXEMPT_MAX_CA} aa: Rg / contacts not applied "
            "(NOT VERIFIED: compactness and where the binder sits;\n"
            "  a binder grown from the wrong origin is still helical, the ORIGIN GATE (|fixed_com|) checks that)"
        )
    if not judged:
        print(
            "  GEOMETRY GATE: PASS — helix-dominated: every backbone is helical, so none is the coil failure this gate detects"
        )
        return True
    rgr = st.mean(r[1] for r in judged)
    lr = st.mean(r[2] for r in judged)
    print(f"  Rg / expected-compact  {rgr:.2f}   (want <=1.45; round-3 BROKEN pool was 1.90)")
    print(f"  long-range contacts    {lr:.2f}/res (want >=0.80; broken pool was 0.28)")
    ok = rgr <= 1.45 and lr >= 0.80
    print(f"  GEOMETRY GATE: {'PASS' if ok else '*** FAIL — these are coils, do NOT run MPNN ***'}")
    return ok


def check_composition(seqs):
    if not seqs:
        print("  COMPOSITION GATE: no sequences")
        return False

    def frac(s, aas):
        return sum(s.count(a) for a in aas) / len(s)

    def H(s):
        c = collections.Counter(s)
        n = len(s)
        return -sum((v / n) * math.log(v / n) for v in c.values())

    a = st.mean(frac(s, "A") for s in seqs)
    pg = st.mean(frac(s, "PG") for s in seqs)
    er = st.mean(frac(s, "ER") for s in seqs)
    hy = st.mean(frac(s, "AVILMFWY") for s in seqs)
    h = st.mean(H(s) for s in seqs)
    g4 = sum(1 for s in seqs if "GGGG" in s)
    print(f"  n sequences   {len(seqs)}")
    print(f"  alanine       {a:.3f}  (want <=0.20; validated pool 0.102)")
    print(f"  Pro+Gly       {pg:.3f}  (want <=0.12; validated 0.055; BROKEN pool 0.286)")
    print(f"  Glu+Arg       {er:.3f}  (want <=0.36 — poly-Glu is where an ALA bias relocates)")
    print(f"  hydrophobic   {hy:.3f}  (want >=0.40; validated ~0.50; BROKEN pool 0.243)")
    print(f"  entropy H     {h:.2f}   (want >=2.40 — NOTE: H alone does NOT catch Pro/Gly collapse)")
    print(f"  GGGG runs     {g4}/{len(seqs)}  (want 0)")
    ok = a <= 0.20 and pg <= 0.12 and er <= 0.36 and hy >= 0.40 and h >= 2.40 and g4 == 0
    print(f"  COMPOSITION GATE: {'PASS' if ok else '*** FAIL ***'}")
    return ok


def _exit(verdict):
    """0 = pass, 1 = measured failure, 2 = could not verify.

    The third code matters: "no fixed_com in the sidecars" and "no chain-B CA
    atoms" mean the check could not run -- an rc-foundry that renames a metric,
    or labels the binder chain something other than B. Collapsing those into 1
    made the caller abort a campaign, after the entire diffusion cost, with a
    confident and wrong diagnosis ("these backbones look like coils").
    """
    sys.exit(0 if verdict else (2 if verdict is None else 1))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "origin":
        _exit(check_origin(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 40))
    if mode == "geometry":
        _exit(check_geometry(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 40))
    seqs, tl = [], int(sys.argv[3])
    for fa in glob.glob(sys.argv[2]):
        for line in open(fa):
            line = line.strip()
            if line and not line.startswith(">"):
                b = line[tl:] if len(line) > tl else line
                if 40 <= len(b) <= 200 and set(b) <= set("ACDEFGHIKLMNPQRSTVWY"):
                    seqs.append(b)
    sys.exit(0 if check_composition(seqs) else 1)
