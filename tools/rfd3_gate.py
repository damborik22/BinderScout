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


def check_geometry(pattern, limit=40):
    rows = []
    for f in sorted(glob.glob(pattern))[:limit]:
        c = ca_chain(f)
        if len(c) >= 25:
            rows.append(geom(c))
    if not rows:
        print("  GEOMETRY GATE: no chain-B CA atoms found — CANNOT VERIFY (not a failure)")
        return None
    rgr = st.mean(r[0] for r in rows)
    lr = st.mean(r[1] for r in rows)
    hx = st.mean(r[2] for r in rows)
    print(f"  backbones checked      {len(rows)}")
    print(f"  Rg / expected-compact  {rgr:.2f}   (want <=1.45; round-3 BROKEN pool was 1.90)")
    print(f"  long-range contacts    {lr:.2f}/res (want >=0.80; broken pool was 0.28)")
    print(f"  helix fraction         {hx:.2f}")
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
