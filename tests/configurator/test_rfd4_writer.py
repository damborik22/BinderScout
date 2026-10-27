"""RFD4-Proteina: the two things that cost GPU jobs, pinned.

1. The contig's residue ids are the mmCIF `label_seq_id`, never `auth_seq_id`.
   On the PD-L1 / TrkA pool run of 2026-10-23 that mistake killed two queued
   jobs — `Preserved segment 'A18-132' runs outside chain A, whose residues are
   2-116`, and `Preserved segment 'A282-382' matched no atoms in the input
   structure` — and a user pointing the wizard at a structure straight from the
   PDB walks into it, because the two numberings differ there as a matter of
   course.

2. `'~metrics'` removes RFD4's native metrics block, which runs AF2/AF3 oracles
   out of environments this install does not create. Without it the run fails,
   so the flag is load-bearing rather than an optimisation, and it must stay
   quoted so the shell leaves the leading `~` alone.

Everything here is static: no design job is run.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

_ATOM_SITE_COLS = (
    "group_PDB",
    "id",
    "type_symbol",
    "label_atom_id",
    "label_comp_id",
    "label_asym_id",
    "label_seq_id",
    "Cartn_x",
    "Cartn_y",
    "Cartn_z",
    "occupancy",
    "B_iso_or_equiv",
    "auth_seq_id",
    "auth_asym_id",
    "pdbx_PDB_model_num",
)


def _mmcif(path: Path, chains, block="test") -> Path:
    """Write a CA-only mmCIF. `chains` is [(chain, [(label_seq_id, auth_seq_id, resname)])]."""
    rows, serial = [], 0
    for chain, residues in chains:
        for label_id, auth_id, res in residues:
            serial += 1
            rows.append(
                f"ATOM {serial} C CA {res} {chain} {label_id} 0.000 0.000 {serial}.000 1.00 30.0 {auth_id} {chain} 1"
            )
    header = "\n".join(f"_atom_site.{c}" for c in _ATOM_SITE_COLS)
    path.write_text(f"data_{block}\n#\nloop_\n{header}\n" + "\n".join(rows) + "\n#\n")
    return path


# PD-L1 5O45 chain A as the wizard would meet it: the user reads "18-132" off the
# PDB entry, the label column says 2-116, and only the label range resolves.
_PDL1_LABEL = (2, 116)
_PDL1_AUTH = (18, 132)


@pytest.fixture
def cif_cfg(tmp_path):
    run_dir = tmp_path / "runs" / "pdl1"
    (run_dir / "rfd4").mkdir(parents=True)
    residues = [(lab, lab + 16, "ALA") for lab in range(_PDL1_LABEL[0], _PDL1_LABEL[1] + 1)]
    cif = _mmcif(tmp_path / "pdl1.cif", [("A", residues)], block="pdl1")
    return {
        "name": "pdl1",
        "run_dir": run_dir,
        "target_pdb": tmp_path / "pdl1.pdb",
        "target_pdb_src": str(cif),
        "target_cif": cif,
        "target_sequence": "A" * len(residues),
        "chains": "A",
        "hotspots": "54,56,115",
        "min_length": 60,
        "max_length": 100,
        "n_designs": 8,
        "rfd4_seed": 101,
    }


class TestLabelSeqIdIsTheContigNumbering:
    def test_cif_chain_numbering_reports_both_schemes(self, cif_cfg):
        info = conf.cif_chain_numbering(str(cif_cfg["target_cif"]), "A")
        assert (info["label_lo"], info["label_hi"]) == _PDL1_LABEL
        assert (info["auth_lo"], info["auth_hi"]) == _PDL1_AUTH
        assert info["n_residues"] == _PDL1_LABEL[1] - _PDL1_LABEL[0] + 1

    def test_the_contig_uses_the_label_range(self, cif_cfg, capsys):
        spec = cif_cfg["run_dir"] / "rfd4" / "input.yaml"
        conf.write_rfd4_input_yaml(spec, cif_cfg)
        contig = next(line.split('"')[1] for line in spec.read_text().splitlines() if line.startswith("  contig: "))
        assert contig == "60-100, /0, A2-116"
        # The author range must not reach the spec at all: it is the value rfd4
        # rejects, and a user who sees it there will believe it worked.
        assert "A18-132" not in contig

    def test_a_label_auth_mismatch_is_reported_not_silent(self, cif_cfg, capsys):
        conf.write_rfd4_input_yaml(cif_cfg["run_dir"] / "rfd4" / "input.yaml", cif_cfg)
        out = capsys.readouterr().out
        assert "label_seq_id" in out
        assert "18-132" in out and "2-116" in out

    def test_matching_numbering_says_nothing(self, tmp_path, cif_cfg, capsys):
        """No warning when the two agree — the ones that matter must stand out."""
        residues = [(i, i, "GLY") for i in range(1, 21)]
        cif_cfg["target_cif"] = _mmcif(tmp_path / "flat.cif", [("A", residues)])
        conf.write_rfd4_input_yaml(cif_cfg["run_dir"] / "rfd4" / "input.yaml", cif_cfg)
        assert "label_seq_id" not in capsys.readouterr().out

    def test_an_unknown_chain_is_refused(self, cif_cfg):
        cif_cfg["chains"] = "Z"
        with pytest.raises(RuntimeError, match="label_asym_id"):
            conf.write_rfd4_input_yaml(cif_cfg["run_dir"] / "rfd4" / "input.yaml", cif_cfg)

    def test_a_pdb_target_is_refused_before_anything_is_generated(self, cif_cfg, capsys):
        """A .pdb has no label_seq_id, so there is no contig to write. preflight
        has to say that, rather than a later writer raising mid-generation."""
        cif_cfg["target_pdb_src"] = str(cif_cfg["target_pdb"])
        with pytest.raises(SystemExit):
            conf.preflight(cif_cfg, {"rfd4": True})
        out = capsys.readouterr().out
        assert "mmCIF" in out and "label_seq_id" in out

        cif_cfg.pop("target_cif")
        with pytest.raises(RuntimeError, match="label_seq_id"):
            conf.write_rfd4_input_yaml(cif_cfg["run_dir"] / "rfd4" / "input.yaml", cif_cfg)


class TestGeneratedRunScript:
    def test_metrics_is_removed_and_quoted(self, cif_cfg):
        script = cif_cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cif_cfg)
        body = script.read_text()
        assert "    '~metrics'" in body, "~metrics must be passed, and quoted against tilde expansion"
        assert '"~metrics"' not in body

    def test_the_invocation_is_the_one_that_was_run(self, cif_cfg):
        script = cif_cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cif_cfg)
        body = script.read_text()
        for arg in ('inputs="$INPUT_YAML"', "num_replicates=8", "batch_size=1", "seed=101", 'out_dir="$GEN_DIR"'):
            assert arg in body, f"missing {arg} from the rfd4-generate call"

    def test_it_runs_from_the_venv_not_a_conda_env(self, cif_cfg):
        script = cif_cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cif_cfg)
        body = script.read_text()
        assert ".venv/bin/rfd4-generate" in body
        assert "conda activate" not in body

    def test_producing_nothing_is_a_failure(self, cif_cfg):
        """2.0 rule: a run that designed nothing must not exit 0."""
        script = cif_cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cif_cfg)
        body = script.read_text()
        assert "wrote no non-empty *_generated.cif" in body
        assert "exit 1" in body

    def test_the_spec_is_read_back_by_the_script(self, cif_cfg, tmp_path):
        """The awk lines must actually parse the spec the configurator writes —
        settings.json records the contig that ran, so a silent empty read there
        would make the provenance wrong rather than absent."""
        spec = cif_cfg["run_dir"] / "rfd4" / "input.yaml"
        conf.write_rfd4_input_yaml(spec, cif_cfg)
        script = cif_cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cif_cfg)
        awk_lines = [ln for ln in script.read_text().splitlines() if ln.startswith(("CONTIG=", "INPUT_CIF="))]
        assert len(awk_lines) == 2
        runner = tmp_path / "read_spec.sh"
        runner.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    f'INPUT_YAML="{spec}"',
                    *awk_lines,
                    'printf "%s\\n%s\\n" "$CONTIG" "$INPUT_CIF"',
                ]
            )
            + "\n"
        )
        proc = subprocess.run(["bash", str(runner)], capture_output=True, text=True, check=True)
        contig, input_cif = proc.stdout.splitlines()
        assert contig == "60-100, /0, A2-116"
        assert Path(input_cif) == cif_cfg["target_cif"].resolve()


class TestSequenceExtraction:
    """The design pool is read out of the generated mmCIFs: the binder is the
    chain that is NOT the preserved target chain. Verified on the pool run, where
    every output carried chains [B, A] with A the untouched target."""

    @staticmethod
    def _extract(cfg, gen_dir, tmp_path):
        script = cfg["run_dir"] / "run_rfd4.sh"
        conf.write_run_rfd4(script, cfg)
        lines = script.read_text().splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith('python3 - "$GEN_DIR"'))
        end = next(i for i in range(start, len(lines)) if lines[i] == "PYEOF")
        runner = tmp_path / "extract.sh"
        runner.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    f'GEN_DIR="{gen_dir}"',
                    f'RFD4_OUT="{cfg["run_dir"] / "rfd4"}"',
                    f'TARGET_CHAIN="{cfg.get("chains", "A").split(",")[0]}"',
                    *lines[start : end + 1],
                ]
            )
            + "\n"
        )
        return subprocess.run(["bash", str(runner)], capture_output=True, text=True)

    def test_the_designed_chain_is_what_lands_in_the_pool(self, cif_cfg, tmp_path):
        gen_dir = cif_cfg["run_dir"] / "rfd4" / "generate"
        for i in (0, 1):
            sample = gen_dir / "inference_samples" / f"pdl1_{i}"
            sample.mkdir(parents=True)
            _mmcif(
                sample / f"pdl1_{i}_generated.cif",
                [
                    ("B", [(1, 1, "LEU"), (2, 2, "GLU"), (3, 3, "ASP")]),
                    ("A", [(1, 1, "MET"), (2, 2, "ALA"), (3, 3, "GLU")]),
                ],
                block=f"pdl1_{i}",
            )
        proc = self._extract(cif_cfg, gen_dir, tmp_path)
        assert proc.returncode == 0, proc.stderr
        csv_text = (cif_cfg["run_dir"] / "rfd4" / "sequences.csv").read_text()
        assert "rfd4_pdl1_0,LED,3,B," in csv_text
        assert "rfd4_pdl1_1,LED,3,B," in csv_text
        assert "MAE" not in csv_text, "the preserved target must not be reported as a design"
        fasta = (cif_cfg["run_dir"] / "rfd4" / "sequences.fasta").read_text()
        assert fasta.startswith(">rfd4_pdl1_0  length=3  source=rfd4\nLED\n")

    def test_an_empty_pool_exits_nonzero(self, cif_cfg, tmp_path):
        gen_dir = cif_cfg["run_dir"] / "rfd4" / "generate"
        gen_dir.mkdir(parents=True)
        proc = self._extract(cif_cfg, gen_dir, tmp_path)
        assert proc.returncode != 0
        assert "no binder sequences" in proc.stderr

    def test_a_structure_missing_the_target_chain_is_named_and_skipped(self, cif_cfg, tmp_path):
        gen_dir = cif_cfg["run_dir"] / "rfd4" / "generate"
        (gen_dir / "inference_samples" / "pdl1_0").mkdir(parents=True)
        _mmcif(
            gen_dir / "inference_samples" / "pdl1_0" / "pdl1_0_generated.cif",
            [("B", [(1, 1, "LEU")]), ("C", [(1, 1, "MET")])],
            block="pdl1_0",
        )
        proc = self._extract(cif_cfg, gen_dir, tmp_path)
        assert proc.returncode != 0
        assert "preserved target chain A absent" in proc.stderr


class TestNoHotspotConditioning:
    def test_hotspots_are_not_written(self, cif_cfg):
        """RFD4 supports C_HOT, but nothing in this project has run it, so the
        wizard's hotspot answer must not silently appear in the spec."""
        spec = cif_cfg["run_dir"] / "rfd4" / "input.yaml"
        conf.write_rfd4_input_yaml(spec, cif_cfg)
        body = spec.read_text()
        assert "C_HOT" not in body
        assert "C_CRDGRP" in body and "C_SEQ" in body
        conf.write_run_rfd4(cif_cfg["run_dir"] / "run_rfd4.sh", cif_cfg)
        assert "not applied" in (cif_cfg["run_dir"] / "run_rfd4.sh").read_text()


class TestTemplateAndWriterAgree:
    TEMPLATE = Path(__file__).resolve().parents[2] / "binderscout_examples" / "run_rfd4.sh.template"

    def test_the_template_exists_and_carries_the_load_bearing_bits(self):
        body = self.TEMPLATE.read_text()
        assert "    '~metrics'" in body
        assert "label_seq_id" in body
        assert ".venv/bin/rfd4-generate" in body

    def test_the_template_is_valid_bash_once_filled(self, tmp_path):
        filled = self.TEMPLATE.read_text()
        for key, value in {
            "RUN_DIR": str(tmp_path / "runs" / "t"),
            "RFD4_REPO": str(tmp_path / "RFD4-Proteina"),
            "TARGET_CHAIN": "A",
            "NUM_REPLICATES": "8",
            "SEED": "1",
        }.items():
            filled = filled.replace("{{" + key + "}}", value)
        assert "{{" not in filled, "unreplaced placeholder in the template"
        script = tmp_path / "run_rfd4.sh"
        script.write_text(filled)
        subprocess.run(["bash", "-n", str(script)], check=True)
