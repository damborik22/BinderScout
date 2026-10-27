"""RFD4-Proteina extractor: reads structures, not a table.

RFD4-Proteina is the only tool here that writes no CSV at all — one all-atom mmCIF
per sample, binder in chain B, target in chain A — so these tests exercise the
mmCIF path and the two ways it can come back empty.

The fixtures are built from the REAL 690-design run (2026-10-23, PD-L1 on Clara
l40s): the sequences, lengths, sample-directory names and design ids below are
copied verbatim from the first rows of that run's ``designs.csv``, and the
``_atom_site`` column set is the one the upstream generator emits
(``RFD4-Proteina/tests/data/sam_binder_generated_minimized.cif``). So a pass means
the extractor reproduces the sequences that run actually produced, not that it
agrees with a fixture written to match it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.extractors.rfd4 import RFD4Extractor

_EVALUATOR = Path(__file__).resolve().parents[2] / "Evaluator"

# First 40 aa of the run's PD-L1 target (metrics.csv target_sequence) — chain A.
_TARGET = "AFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYW"

# (sample directory, designs.csv id, binder sequence) from the real run's designs.csv.
# pdl1_binder_10 is included deliberately: a lexicographic sort puts "_10" before
# "_2", so it pins that the pool comes back in generation order.
_REAL_DESIGNS = [
    (
        "pdl1_binder_0",
        "rfd4_pdl1_0001",
        "SDSLIESLSDDELISSINTRLTFIESIASATMSDTNHSTVSTYVSSIRTALDEEDYSTALDHALNLKDFLESNSEATSAMLELINQVIYSLELLLE",
    ),
    (
        "pdl1_binder_1",
        "rfd4_pdl1_0002",
        "STLTVAVSSVSASSVTVTASGLSAGDTVTFTLTKMGSTWSTTKTATADSSGSASVTFTGLTPNSYYIVTASASGHSPASTFFKTK",
    ),
    (
        "pdl1_binder_2",
        "rfd4_pdl1_0003",
        "VELTEMEKQTFKSEAKEKILKEHPSAEILDIHILEATDHTVRLMVHYKLDGLDYIKTITLER",
    ),
    (
        "pdl1_binder_10",
        "rfd4_pdl1_0011",
        "VQLTQSPSSLSASVGDRVTITCRASQSVSSALAWYQQKPGQAPKLLIYSASSLESGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQYRDVWGQGTKVE",
    ),
]

_ONE_TO_THREE = {
    "A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS", "Q": "GLN",
    "E": "GLU", "G": "GLY", "H": "HIS", "I": "ILE", "L": "LEU", "K": "LYS",
    "M": "MET", "F": "PHE", "P": "PRO", "S": "SER", "T": "THR", "W": "TRP",
    "Y": "TYR", "V": "VAL",
}  # fmt: skip

# The generator's own _atom_site column set, in its own order.
_ATOM_SITE_COLS = [
    "group_PDB", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
    "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code",
    "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id", "id",
    "B_iso_or_equiv", "occupancy", "pdbx_formal_charge",
    "Cartn_x", "Cartn_y", "Cartn_z", "pdbx_PDB_model_num",
]  # fmt: skip


def _cif(chains: list[tuple[str, str]]) -> str:
    """An all-atom ``_generated.cif`` body for ``[(chain_id, sequence), ...]``."""
    lines = ["data_x", "#", "loop_"] + [f"_atom_site.{c} " for c in _ATOM_SITE_COLS]
    serial = 0
    for entity, (chain, seq) in enumerate(chains, start=1):
        for resnum, aa in enumerate(seq, start=1):
            three = _ONE_TO_THREE[aa]
            for atom, symbol in (("N", "N"), ("CA", "C"), ("C", "C")):
                serial += 1
                lines.append(
                    f"ATOM {symbol} {atom} . {three} {chain} {entity} {resnum} . {resnum} {three} "
                    f"{chain} {atom} {serial} 0.0 1.0 ? "
                    f"{resnum}.000 {resnum}.000 {resnum}.000 1"
                )
    return "\n".join([*lines, "#", ""])


def _sample(samples_dir: Path, name: str, chains: list[tuple[str, str]]) -> Path:
    d = samples_dir / name
    d.mkdir(parents=True)
    path = d / f"{name}_generated.cif"
    path.write_text(_cif(chains))
    return path


def _real_run(tmp_path: Path) -> Path:
    """The shipped layout: <out_dir>/runs/<tag>/inference_samples/<name>_<i>/..."""
    samples = tmp_path / "pdl1" / "prod" / "runs" / "prod" / "inference_samples"
    for name, _id, seq in _REAL_DESIGNS:
        _sample(samples, name, [("A", _TARGET), ("B", seq)])
    return tmp_path / "pdl1"


class TestRealRunExtraction:
    def test_returns_the_chain_b_sequences_the_real_run_produced(self, tmp_path):
        got = RFD4Extractor().extract(_real_run(tmp_path))
        assert [b.sequence for b in got] == [seq for _n, _i, seq in _REAL_DESIGNS]
        assert all(b.source_tool == "rfd4" for b in got)

    def test_chain_a_target_is_never_extracted(self, tmp_path):
        """Chain B is the binder and chain A the target — swapping them silently
        would refold the target against itself and score nothing meaningful."""
        got = RFD4Extractor().extract(_real_run(tmp_path))
        assert all(_TARGET not in b.sequence for b in got)

    def test_pool_is_in_generation_order_not_lexicographic(self, tmp_path):
        """``_10`` sorts before ``_2`` as text; the replicate index must win."""
        got = RFD4Extractor().extract(_real_run(tmp_path))
        assert [b.generation_index for b in got] == [0, 1, 2, 10]
        assert all(b.generation_index_source == "parsed" for b in got)

    def test_ids_name_the_sample_and_carry_no_fabricated_metric(self, tmp_path):
        got = RFD4Extractor().extract(_real_run(tmp_path))
        assert [b.binder_id for b in got] == [f"rfd4_{name}" for name, _i, _s in _REAL_DESIGNS]
        # RFD4 runs with `~metrics`, so every native field must stay None rather
        # than being filled with a zero that reads as a score.
        assert all(v is None for b in got for v in vars(b.native).values())


class TestEmptyIsLoud:
    """A step that produces nothing must not exit 0. The Proteina-Complexa harvest
    found nothing, exited 0, and the tool vanished from the pool unnoticed."""

    def test_no_structures_warns_and_returns_nothing(self, tmp_path):
        with pytest.warns(UserWarning, match="inference_samples"):
            assert RFD4Extractor().extract(tmp_path) == []

    def test_structures_without_a_binder_chain_warn_and_return_nothing(self, tmp_path):
        """Found files but no chain B is a DIFFERENT diagnosis from found nothing,
        and saying so is the difference between a fixed path and a fixed layout."""
        samples = tmp_path / "inference_samples"
        _sample(samples, "pdl1_binder_0", [("A", _TARGET)])
        with pytest.warns(UserWarning, match="chain B"):
            assert RFD4Extractor().extract(tmp_path) == []

    def test_extract_cli_exits_nonzero_and_names_rfd4(self, tmp_path):
        empty = tmp_path / "nothing_here"
        empty.mkdir()
        res = subprocess.run(
            [
                sys.executable, "-m", "binder_comparison", "extract",
                "--rfd4", str(empty),
                "--output", str(tmp_path / "seqs.fasta"),
            ],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(_EVALUATOR), "PATH": "/usr/bin:/bin"},
        )  # fmt: skip
        assert res.returncode != 0
        assert "produced 0 sequences" in res.stderr
        assert "rfd4" in res.stderr


class TestAmbiguousPoolIsRefused:
    def test_two_inference_samples_roots_refuse_rather_than_merge(self, tmp_path):
        """A timing job and a production job sit side by side under one target
        directory, so merging roots would pad the pool with throwaway designs."""
        for tag in ("timing", "prod"):
            _sample(
                tmp_path / tag / "runs" / "inference_samples",
                "pdl1_binder_0",
                [("A", _TARGET), ("B", _REAL_DESIGNS[0][2])],
            )
        with pytest.raises(ValueError, match="refusing to guess"):
            RFD4Extractor().extract(tmp_path)

    def test_one_root_is_fine_however_deeply_nested(self, tmp_path):
        got = RFD4Extractor().extract(_real_run(tmp_path).parent)
        assert len(got) == len(_REAL_DESIGNS)
