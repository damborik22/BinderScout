"""Nothing the configurator ships or generates may name a cluster, a box or a job.

The repo is public and the generated run folders get copied around. The generators
carried a pointer to a machine-local notes file, a scheduler job id and fleet box names
inside comments. Each of those is an infrastructure identifier.

(The `bindmaster_*` conda-env fallback is deliberately NOT banned: it is a former env
name, not an infrastructure identifier, and both installers still reuse such an env in
place, so the wizard and the generated scripts must resolve it too.)

The forbidden words are assembled from pieces so this file does not itself contain
the identifiers it bans.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_CLUSTER = "cla" + "ra"
_NOTES = "CLAUDE" + r"\.local"
FORBIDDEN = re.compile(
    "|".join(
        [
            rf"\b{_CLUSTER}\b",
            r"\bBM[0-9]\b",
            r"\bbm[0-9]\b",
            r"bindmaster[0-9]",
            _NOTES,
            r"\bsacct\b",
            r"\bslurm\b",
            r"\bHPC\b",
            r"job [0-9]{5,}",
        ]
    ),
    re.IGNORECASE,
)


def _hits(text: str) -> list[str]:
    return [m.group(0) for m in FORBIDDEN.finditer(text)]


def test_the_configurator_source_names_no_cluster_or_box():
    src = (REPO / "configurator" / "configurator.py").read_text()
    assert _hits(src) == []


def test_the_run_script_templates_and_examples_name_no_cluster_or_box():
    files = [p for d in ("binderscout_examples", "examples") for p in (REPO / d).rglob("*") if p.is_file()]
    assert files, "nothing to scan"
    bad = {str(p.relative_to(REPO)): _hits(p.read_text(errors="replace")) for p in files if p.suffix != ".pdb"}
    assert {k: v for k, v in bad.items() if v} == {}


def test_generated_scripts_carry_no_cluster_names(tmp_path, fake_checkout, replay):
    payload = json.loads((REPO / "examples" / "CALCA" / "smoke.json").read_text())
    payload["cfg"]["run_dir"] = str(tmp_path / "run")
    payload["cfg"]["target_pdb_src"] = str(REPO / "examples" / "CALCA" / "target.pdb")
    config = tmp_path / "cfg.json"
    config.write_text(json.dumps(payload))

    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]

    scripts = sorted((tmp_path / "run").glob("run_*.sh"))
    assert len(scripts) >= 9, [s.name for s in scripts]
    # The scratch path itself carries this account's name; it is the test's, not the script's.
    offenders = {s.name: _hits(s.read_text().replace(str(tmp_path), "<tmp>")) for s in scripts}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_a_prerename_env_is_reported_as_the_installed_tool(tmp_path, monkeypatch):
    """Both installers reuse a pre-rename env in place and write the marker, so the wizard must see it."""
    import sys

    sys.path.insert(0, str(REPO / "configurator"))
    import configurator as conf

    envs = tmp_path / "envs"
    (envs / ("bindmaster" + "_pxdesign")).mkdir(parents=True)
    monkeypatch.setattr(conf, "CONDA_ENVS_DIR", envs)
    assert conf.detect_installs()["pxdesign_local"] is True

    # ...and the canonical name wins when both exist; with neither, the tool is absent.
    (envs / "binderscout_pxdesign").mkdir()
    assert conf.detect_installs()["pxdesign_local"] is True
    other = tmp_path / "other" / "envs"
    other.mkdir(parents=True)
    monkeypatch.setattr(conf, "CONDA_ENVS_DIR", other)
    assert conf.detect_installs()["pxdesign_local"] is False
