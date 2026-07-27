"""Tests for the shared target-MSA cache (audit findings F21 + F22).

F22 — the cache write must be atomic (temp file + os.replace) and every read
must be validated, so two engines started together can never hand each other a
half-written a3m.

F21 — the MSA must be fetched once up front and shared; an engine may only run
without one when the operator explicitly opts in, and that state is recorded.

The ColabFold network call is always mocked — these tests never touch the
network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from binder_comparison.refolding import target_msa as tm

TARGET = "MKTAYIAKQRQISFVKSHFSRQ"
GOOD_A3M = f">101\n{TARGET}\n>UniRef90_A0A1\n{TARGET[:-2]}--\n"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Isolated MSA cache — never the real ~/.cache/bindmaster."""
    d = tmp_path / "msa_cache"
    d.mkdir()
    monkeypatch.setenv("BINDMASTER_MSA_CACHE", str(d))
    monkeypatch.delenv(tm.ALLOW_NO_MSA_ENV, raising=False)
    return d


@pytest.fixture
def fake_server(monkeypatch):
    """Stub the ColabFold query; records how many times it was called."""
    calls: list[str] = []

    def _fake(seq, mode=tm.DEFAULT_MODE):
        calls.append(seq)
        return GOOD_A3M

    monkeypatch.setattr(tm, "_query_colabfold", _fake)
    return calls


def _cache_file(cache_dir: Path) -> Path:
    return cache_dir / f"target_{tm._cache_key(TARGET)}.a3m"


# ---------------------------------------------------------------------------
# F22 — read validation
# ---------------------------------------------------------------------------

CORRUPT_CASES = {
    "empty": "",
    "whitespace_only": "\n\n",
    "no_header": f"{TARGET}\n",
    "headers_only": ">101\n>102\n",
    "truncated_mid_sequence": f">101\n{TARGET}\n>UniRef90_A0A1\nMKTAY",  # no trailing newline
    "truncated_after_header": f">101\n{TARGET}\n>UniRef90_A0A1\n",
}


@pytest.mark.parametrize("name", sorted(CORRUPT_CASES))
def test_corrupt_cache_is_rejected_and_refetched(name, cache_dir, fake_server):
    """A truncated/corrupt cache entry must never be returned to an engine."""
    bad = CORRUPT_CASES[name]
    _cache_file(cache_dir).write_text(bad)

    a3m, mode = tm.get_target_msa_with_mode(TARGET)

    assert a3m == GOOD_A3M, f"corrupt cache ({name}) was returned instead of re-fetched"
    assert mode == tm.MSA_MODE_FETCHED
    assert len(fake_server) == 1
    # the bad entry was replaced on disk
    assert _cache_file(cache_dir).read_text() == GOOD_A3M


def test_size_gt_zero_is_not_validation(cache_dir, fake_server):
    """The old `st_size > 0` guard passes a truncated file — this must not."""
    truncated = CORRUPT_CASES["truncated_mid_sequence"]
    _cache_file(cache_dir).write_text(truncated)
    assert _cache_file(cache_dir).stat().st_size > 0

    a3m, _ = tm.get_target_msa_with_mode(TARGET)
    assert a3m != truncated


def test_valid_cache_is_a_hit_and_never_queries(cache_dir, fake_server):
    _cache_file(cache_dir).write_text(GOOD_A3M)

    a3m, mode = tm.get_target_msa_with_mode(TARGET)

    assert a3m == GOOD_A3M
    assert mode == tm.MSA_MODE_CACHED
    assert fake_server == []


def test_cache_path_helper_rejects_corrupt_file(cache_dir):
    _cache_file(cache_dir).write_text(CORRUPT_CASES["truncated_after_header"])
    assert tm.target_msa_cache_path(TARGET) is None

    _cache_file(cache_dir).write_text(GOOD_A3M)
    assert tm.target_msa_cache_path(TARGET) == _cache_file(cache_dir)


def test_a3m_problem_accepts_a_real_a3m():
    assert tm._a3m_problem(GOOD_A3M) is None


# ---------------------------------------------------------------------------
# F22 — atomic write
# ---------------------------------------------------------------------------


def test_write_is_temp_file_then_replace(cache_dir, fake_server, monkeypatch):
    """The final name must appear only via os.replace, already complete."""
    observed: dict = {}
    real_replace = os.replace

    def spy(src, dst):
        observed["src"] = str(src)
        observed["dst"] = str(dst)
        observed["src_content"] = Path(src).read_text()
        observed["dst_existed_before_replace"] = Path(dst).exists()
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)

    tm.get_target_msa(TARGET)

    assert observed, "cache was written without os.replace — the write is not atomic"
    final = _cache_file(cache_dir)
    assert observed["dst"] == str(final)
    assert observed["src"] != str(final), "temp file must be a distinct path"
    assert Path(observed["src"]).parent == final.parent, "temp file must be in the same directory (same filesystem)"
    # a reader can only ever see the complete file
    assert observed["src_content"] == GOOD_A3M
    assert observed["dst_existed_before_replace"] is False
    assert final.read_text() == GOOD_A3M
    assert list(cache_dir.glob("*.tmp")) == [], "temp file left behind"


def test_failed_write_leaves_no_partial_file(cache_dir, fake_server, monkeypatch):
    """If the write dies, the final name must not exist and no temp may linger."""

    def boom(src, dst):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        tm.get_target_msa(TARGET)

    assert not _cache_file(cache_dir).exists()
    assert list(cache_dir.iterdir()) == [], "temp file left behind after a failed write"


def test_fetched_msa_is_validated_before_caching(cache_dir, monkeypatch):
    monkeypatch.setattr(tm, "_query_colabfold", lambda seq, mode=tm.DEFAULT_MODE: ">101\n")

    with pytest.raises(RuntimeError, match="unusable MSA"):
        tm.get_target_msa(TARGET)
    assert not _cache_file(cache_dir).exists()


# ---------------------------------------------------------------------------
# F21 — fetched once, shared, and reported
# ---------------------------------------------------------------------------


def test_fetched_once_then_shared_by_every_engine(cache_dir, fake_server, tmp_path):
    """The first engine pays the round-trip; the others are disk hits."""
    modes = [tm.prepare_target_msa(TARGET, engine=e, out_dir=tmp_path / e)[1] for e in ("boltz2", "af3", "esmfold2")]
    assert modes == [tm.MSA_MODE_FETCHED, tm.MSA_MODE_CACHED, tm.MSA_MODE_CACHED]
    assert len(fake_server) == 1


def test_msa_available_engine_proceeds_and_records(cache_dir, fake_server, tmp_path, capsys):
    out = tmp_path / "refold_af3"
    a3m, mode = tm.prepare_target_msa(TARGET, engine="af3", out_dir=out)

    assert a3m == GOOD_A3M
    assert mode == tm.MSA_MODE_FETCHED
    record = json.loads((out / tm.MSA_MODE_FILENAME).read_text())
    assert record["engine"] == "af3"
    assert record["target_msa_mode"] == tm.MSA_MODE_FETCHED
    assert record["n_sequences"] == 2
    assert "WARNING" not in capsys.readouterr().out


def test_no_msa_without_optin_aborts_and_names_the_flag(cache_dir, monkeypatch, tmp_path):
    def offline(seq, mode=tm.DEFAULT_MODE):
        raise ConnectionError("air-gapped node")

    monkeypatch.setattr(tm, "_query_colabfold", offline)

    with pytest.raises(tm.MissingTargetMSA) as excinfo:
        tm.prepare_target_msa(TARGET, engine="esmfold2", out_dir=tmp_path)

    msg = str(excinfo.value)
    assert "ABORTING" in msg
    assert "air-gapped node" in msg  # the underlying reason
    assert "--allow-no-msa" in msg  # how to proceed anyway
    assert tm.ALLOW_NO_MSA_ENV in msg
    assert "python -m binder_comparison.refolding.target_msa --target-seq" in msg  # how to pre-warm
    assert not (tmp_path / tm.MSA_MODE_FILENAME).exists()


def test_no_msa_with_flag_proceeds_and_records(cache_dir, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tm, "_query_colabfold", lambda seq, mode=tm.DEFAULT_MODE: (_ for _ in ()).throw(ConnectionError("offline"))
    )

    a3m, mode = tm.prepare_target_msa(TARGET, engine="boltz2", out_dir=tmp_path, allow_no_msa=True)

    assert a3m == ""
    assert mode == tm.MSA_MODE_NONE
    record = json.loads((tmp_path / tm.MSA_MODE_FILENAME).read_text())
    assert record["target_msa_mode"] == tm.MSA_MODE_NONE
    assert "offline" in record["detail"]
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "not directly comparable" in out


def test_env_var_is_an_equivalent_optin(cache_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(
        tm, "_query_colabfold", lambda seq, mode=tm.DEFAULT_MODE: (_ for _ in ()).throw(ConnectionError("offline"))
    )
    monkeypatch.setenv(tm.ALLOW_NO_MSA_ENV, "1")

    a3m, mode = tm.prepare_target_msa(TARGET, engine="af3", out_dir=tmp_path)
    assert (a3m, mode) == ("", tm.MSA_MODE_NONE)


def test_explicit_no_msa_request_is_not_an_abort(cache_dir, fake_server, tmp_path, capsys):
    a3m, mode = tm.prepare_target_msa(TARGET, engine="af3", out_dir=tmp_path, use_msa=False)

    assert (a3m, mode) == ("", tm.MSA_MODE_NONE)
    assert fake_server == [], "use_msa=False must not query the server"
    record = json.loads((tmp_path / tm.MSA_MODE_FILENAME).read_text())
    assert record["target_msa_mode"] == tm.MSA_MODE_NONE
    assert "--no-msa" in record["detail"]
    assert "WARNING" in capsys.readouterr().out


def test_note_msa_mode_warning_names_the_consequence(tmp_path, capsys):
    tm.note_msa_mode("esmfold2", tm.MSA_MODE_NONE, out_dir=tmp_path)
    out = capsys.readouterr().out
    assert "not directly comparable to engines that used an MSA" in out
    assert "consensus_iptm" in out


def test_query_row_mismatch_warns_but_keeps_the_msa(cache_dir, monkeypatch, capsys):
    other = ">101\nWWWWWWWW\n>UniRef90_X\nWWWWWWWW\n"
    _cache_file(cache_dir).write_text(other)

    a3m, mode = tm.get_target_msa_with_mode(TARGET)

    assert mode == tm.MSA_MODE_CACHED
    assert a3m == other
    assert "does not match the target sequence" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# API compatibility — existing callers must keep working
# ---------------------------------------------------------------------------


def test_get_target_msa_still_returns_a_plain_string(cache_dir, fake_server):
    assert tm.get_target_msa(TARGET) == GOOD_A3M
    assert tm.get_target_msa(TARGET, cache_dir=str(cache_dir)) == GOOD_A3M
