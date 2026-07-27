"""Tests for the shared `--<tool> DIR` argparse group.

`extract` and `run` declared their tool flags independently and drifted: `run`
offered 5 of the 7, so the advertised single-command path silently omitted every
RFD3 and Protein-Hunter design and argparse rejected `--rfd3` outright.
"""

import argparse
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.cli._tool_args import TOOL_DESTS, TOOL_FLAGS, add_tool_args, requested_tools

_ALL_SEVEN = {
    "bindcraft",
    "boltzgen",
    "mosaic",
    "pxdesign",
    "proteina_complexa",
    "protein_hunter",
    "rfd3",
}


def _parser_with_tools():
    p = argparse.ArgumentParser()
    add_tool_args(p)
    return p


class TestSharedToolFlags:
    def test_table_covers_every_design_tool(self):
        assert set(TOOL_DESTS) == _ALL_SEVEN

    def test_hyphenated_flags_keep_underscore_dests(self):
        args = _parser_with_tools().parse_args(["--proteina-complexa", "/a", "--protein-hunter", "/b"])
        assert args.proteina_complexa == "/a"
        assert args.protein_hunter == "/b"

    def test_rfd3_is_accepted(self):
        """Regression: `binder-compare run --rfd3 DIR` was an argparse error."""
        assert _parser_with_tools().parse_args(["--rfd3", "/r"]).rfd3 == "/r"

    def test_unpassed_tools_default_to_none(self):
        args = _parser_with_tools().parse_args([])
        assert all(getattr(args, dest) is None for dest in TOOL_DESTS)

    def test_requested_tools_returns_only_what_was_passed_in_table_order(self):
        args = _parser_with_tools().parse_args(["--rfd3", "/r", "--bindcraft", "/b"])
        assert requested_tools(args) == [("bindcraft", "/b"), ("rfd3", "/r")]


class TestExtractAndRunAgreeOnTools:
    """The whole point of the shared table: neither subcommand can fall behind."""

    def _dests(self, module_name):
        import importlib

        mod = importlib.import_module(f"binder_comparison.cli.{module_name}")
        sub = argparse.ArgumentParser().add_subparsers()
        mod.add_parser(sub)
        parser = sub.choices[module_name.replace("_", "-")]
        opts = {a.dest for a in parser._actions}
        return opts & _ALL_SEVEN

    def test_extract_offers_all_seven(self):
        assert self._dests("extract") == _ALL_SEVEN

    def test_run_offers_all_seven(self):
        assert self._dests("run") == _ALL_SEVEN

    def test_run_forwards_every_flag_it_accepts(self):
        """A flag `run` accepts but never forwards to extract is worse than no flag."""
        src = (Path(__file__).resolve().parents[2] / "Evaluator/binder_comparison/cli/run.py").read_text()
        assert "for flag, dest, _help in TOOL_FLAGS:" in src, (
            "run.py should build the extract command from the shared table, "
            "not a hand-written if-chain that can fall behind"
        )
        assert len(TOOL_FLAGS) == 7


class TestZeroYieldIsAnError:
    """Regression (F40): the guard only fired when EVERY tool came up empty, so a
    typo in one of four --tool paths printed "→ 0 sequences", exited 0, and
    run_evaluate.sh under `set -e` then spent hours of GPU time on a partial pool."""

    def _run_extract(self, tmp_path, extra=()):
        import subprocess

        empty = tmp_path / "nothing_here"
        empty.mkdir()
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "binder_comparison",
                "extract",
                "--rfd3",
                str(empty),
                "--output",
                str(tmp_path / "seqs.fasta"),
                *extra,
            ],
            capture_output=True,
            text=True,
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "Evaluator"),
                "PATH": "/usr/bin:/bin",
            },
        )

    def test_empty_tool_dir_exits_nonzero(self, tmp_path):
        res = self._run_extract(tmp_path)
        assert res.returncode != 0
        assert "produced 0 sequences" in res.stderr
        assert "rfd3" in res.stderr

    def test_allow_empty_names_the_escape_hatch(self, tmp_path):
        res = self._run_extract(tmp_path)
        assert "--allow-empty" in res.stderr


class TestRfd3FastaFallbackGuard:
    """Regression (F39): mpnn writes the FULL chain (target prefix + binder). With no
    target to strip, an unguarded fallback handed the refold engines a target+binder
    concatenation labelled as a binder, making every iPTM computed for it meaningless."""

    def _extract(self, tmp_path, seq):
        from binder_comparison.extractors.rfd3 import RFD3Extractor

        d = tmp_path / "rfd3" / "mpnn"
        d.mkdir(parents=True)
        (d / "design_0.fa").write_text(f">design_0 sequence_recovery=0.42\n{seq}\n")
        return RFD3Extractor().extract(tmp_path / "rfd3")

    def test_plausible_binder_is_accepted(self, tmp_path):
        got = self._extract(tmp_path, "ACDEFGHIKLMNPQRSTVWY" * 4)  # 80 aa
        assert len(got) == 1
        assert got[0].source_tool == "rfd3"

    def test_full_chain_length_is_rejected_with_a_warning(self, tmp_path):
        from binder_comparison.extractors.rfd3 import _MAX_PLAUSIBLE_BINDER_LEN

        oversized = "A" * (_MAX_PLAUSIBLE_BINDER_LEN + 1)
        with pytest.warns(UserWarning, match="target prefix"):
            got = self._extract(tmp_path, oversized)
        assert got == []
