"""`detect_installs()` must require the marker AND the probe, once markers exist.

Each half alone shipped a wrong answer:

* **Marker alone** (the rule before this change) — a marker outlives what it
  describes, so deleting a conda env by hand left the tool reading "installed".
  That is BUG-06 in mirror image. It also keyed the probe/marker switch on the
  *directory*, so one `install --tool X` on a populated box made every other
  working tool read not-installed.
* **Probe alone** (the rule before markers existed) — a conda env directory or a
  venv python cannot tell a finished install from one that died half way, which is
  what BUG-06 was.

These exercise the real `detect_installs()` with `INSTALL_STATE_DIR` and the probe
inputs redirected, rather than reimplementing the rule.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "configurator"))

import configurator as cfg  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point the marker store at a tmpdir and make every probe pass."""
    store = tmp_path / ".install_state"
    monkeypatch.setattr(cfg, "INSTALL_STATE_DIR", store)

    envs = tmp_path / "envs"
    envs.mkdir()
    for name in (
        "BindCraft",
        "BoltzGen",
        "binder-eval",
        "bindmaster_pxdesign",
        "bindmaster_rfd3",
        "bindmaster_protein_hunter",
        "binder-eval-af3",
        "binder-eval-esmfold2",
        "binder-eval-soluprot",
    ):
        (envs / name).mkdir()
    monkeypatch.setattr(cfg, "CONDA_ENVS_DIR", envs)

    for venv in ("MOSAIC_VENV", "PROTEINA_COMPLEXA_VENV"):
        p = tmp_path / venv / "bin"
        p.mkdir(parents=True)
        (p / "python").touch()
        monkeypatch.setattr(cfg, venv, tmp_path / venv)

    evaluator = tmp_path / "Evaluator"
    evaluator.mkdir()
    (evaluator / "evaluate.sh").touch()
    monkeypatch.setattr(cfg, "EVALUATOR_DIR", evaluator)

    weights = tmp_path / "weights" / "foundry"
    weights.mkdir(parents=True)
    (weights / "rfd3_latest.ckpt").touch()
    monkeypatch.setattr(cfg, "FOUNDRY_WEIGHTS_DIR", weights)

    ph = tmp_path / "Protein-Hunter"
    ph.mkdir()
    monkeypatch.setattr(cfg, "PROTEIN_HUNTER_DIR", ph)

    return store


def mark(store: Path, *keys: str) -> None:
    store.mkdir(parents=True, exist_ok=True)
    for key in keys:
        (store / key).write_text("2026-10-28T00:00\tdeadbee\n")


class TestNoMarkersYet:
    def test_probes_alone_decide_while_the_store_is_empty(self, state):
        """A box installed before markers existed must still read correctly."""
        assert cfg.detect_installs()["bindcraft"] is True

    def test_an_existing_but_empty_directory_still_falls_back_to_probes(self, state):
        """`--uninstall --tool all` leaves the directory; `rm -f` empties it.

        The old `is_dir()` switch read that as "markers exist, none set" and
        reported everything uninstalled on a box where everything worked.
        """
        state.mkdir(parents=True)
        assert not any(state.iterdir())
        installed = cfg.detect_installs()
        assert installed["bindcraft"] is True
        assert installed["esmfold2"] is True


class TestOnceMarkersExist:
    def test_marker_plus_probe_is_installed(self, state):
        mark(state, "bindcraft")
        assert cfg.detect_installs()["bindcraft"] is True

    def test_an_unmarked_tool_is_not_installed(self, state):
        """Intended: once the installer records successes, a probe cannot override."""
        mark(state, "bindcraft")
        assert cfg.detect_installs()["boltzgen"] is False

    def test_a_marker_whose_environment_is_gone_is_not_installed(self, state, monkeypatch):
        """The regression the AND rule exists for: a stale marker must not win."""
        mark(state, "bindcraft", "boltzgen")
        monkeypatch.setattr(cfg, "CONDA_ENVS_DIR", state.parent / "nonexistent-envs")
        installed = cfg.detect_installs()
        assert installed["bindcraft"] is False, "a marker outlived its deleted conda env"
        assert installed["boltzgen"] is False

    def test_the_refold_engines_survive_a_single_new_install(self, state):
        """The failure this fixes end to end.

        Before: one marker switched the whole dict to marker-only, so Mosaic (which
        carries Boltz-2), AF3 and ESMFold2 all read not-installed, Step 9 printed
        three "skipped" lines and ended on "No refolding engine selected — Evaluator
        disabled". The migration in install.sh marks every passing probe, so the
        realistic post-migration store has them all.
        """
        mark(state, "mosaic", "af3", "esmfold2", "evaluator")
        installed = cfg.detect_installs()
        assert installed["mosaic"] is True
        assert installed["af3"] is True
        assert installed["esmfold2"] is True
        assert installed["evaluator"] is True


class TestMarkerKeysMatchTheInstaller:
    def test_pxdesign_dict_key_differs_from_its_marker_key(self, state):
        """`pxdesign_local` is the dict key; `pxdesign` is what install.sh writes.

        Getting this backwards would make PXDesign permanently uninstalled.
        """
        mark(state, "pxdesign")
        assert cfg.detect_installs()["pxdesign_local"] is True

    def test_every_marker_name_the_installer_writes_is_read_here(self, state):
        installer = (REPO_ROOT / "install" / "install.sh").read_text()
        import re

        written = set(re.findall(r"_install_step\s+([a-z0-9_]+)", installer))
        mark(state, *sorted(written))
        installed = cfg.detect_installs()
        unread = {
            k
            for k in written
            if not any((k == dict_key) or (dict_key == "pxdesign_local" and k == "pxdesign") for dict_key in installed)
        }
        assert not unread, f"install.sh marks {sorted(unread)} but detect_installs never reads them"
