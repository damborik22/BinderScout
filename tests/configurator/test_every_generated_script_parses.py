"""Every script the configurator generates must parse as bash, and the Python embedded in it must compile.

A generated script is not a tracked file, so CI's shellcheck (which lints `git ls-files '*.sh'`) never sees
one, and a writer that emits something bash cannot parse ships green: the first anyone knows is a step that
dies in 0 seconds on a compute node, or -- worse -- a design step that runs for hours and then fails in its
own harvest. The Proteina-Complexa harvest was exactly that on the 1.x line: its program was handed to
`python3 -c "..."`, a comment inside it carried double quotes, and `bash -n` rejected the script outright.

The config is `examples/CALCA/smoke.json`, the one that enables every design tool, plus RFD4-Proteina
(which needs an mmCIF target, so the example, a .pdb, cannot enable it) and the PXDesign length-scan mode
(a different script around the same harvest). The scripts are produced the way a user produces them, by a
headless `--config` replay in a subprocess.

`bash -n` is necessary and not sufficient. A stray quote that leaves the count EVEN parses cleanly and still
hands python3 a truncated program, and ruff cannot see it because the program is inside a string literal. So
each embedded Python program is also compiled, in the form bash delivers it: a quoted heredoc body is
delivered untouched, and an inline `python3 -c "..."` statement is executed under real bash with python3
replaced by a recorder, so what is compiled is what python3 would have received.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"
BASH = shutil.which("bash") or "bash"

# What a complete run folder holds. The test is vacuous if a tool silently generated nothing, so the set
# of scripts found is checked against this.
EXPECTED = {
    "run_all.sh",
    "run_evaluate.sh",
    "run_bindcraft.sh",
    "run_bindcraft2.sh",
    "run_boltzgen.sh",
    "run_mosaic.sh",
    "run_pxdesign.sh",
    "run_proteina_complexa.sh",
    "run_rfd3.sh",
    "run_protein_hunter.sh",
    "run_rfd4.sh",
}

_AA3 = {
    "A": "ALA",
    "R": "ARG",
    "N": "ASN",
    "D": "ASP",
    "C": "CYS",
    "Q": "GLN",
    "E": "GLU",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "L": "LEU",
    "K": "LYS",
    "M": "MET",
    "F": "PHE",
    "P": "PRO",
    "S": "SER",
    "T": "THR",
    "W": "TRP",
    "Y": "TYR",
    "V": "VAL",
}
_COLS = (
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

# `python3 - args <<'DELIM'` ... `DELIM`: a quoted delimiter, so bash delivers the body verbatim.
HEREDOC = re.compile(r"python3? -[^\n<]*<<'(\w+)'\n(.*?)\n\1\n", re.S)
HEREDOC_OPENER = re.compile(r"python3? -[^\n<]*<<")
INLINE_OPENER = 'python3 -c "'


def _mmcif(path: Path, sequence: str) -> Path:
    rows = [
        f"ATOM {i} C CA {_AA3[aa]} A {i} {3.8 * i:.3f} 0.000 0.000 1.00 30.0 {i} A 1"
        for i, aa in enumerate(sequence, 1)
    ]
    header = "\n".join(f"_atom_site.{c}" for c in _COLS)
    path.write_text(f"data_calca\n#\nloop_\n{header}\n" + "\n".join(rows) + "\n#\n")
    return path


def _generate(tmp_path: Path, fake_checkout: Path, replay, **cfg_overrides) -> Path:
    payload = json.loads(SMOKE.read_text())
    payload["tools_enabled"]["rfd4"] = True
    payload["cfg"].update(cfg_overrides)
    ex = fake_checkout / "examples" / "CALCA"
    ex.mkdir(parents=True)
    payload["cfg"]["target_pdb_src"] = str(_mmcif(ex / "target.cif", payload["cfg"]["target_sequence"]))
    config = ex / "smoke.json"
    config.write_text(json.dumps(payload))
    proc = replay(config, fake_checkout, tmp_path)
    assert proc.returncode == 0, "the replay itself failed:\n" + (proc.stdout + proc.stderr)[-2000:]
    return fake_checkout / "runs" / "CALCA_smoke"


@pytest.fixture(
    params=[{}, {"pxdesign_length_scan": True, "pxdesign_top_per_length": 5}],
    ids=["smoke", "pxdesign-length-scan"],
)
def run_dir(request, tmp_path, fake_checkout, replay) -> Path:
    return _generate(tmp_path, fake_checkout, replay, **request.param)


def _scripts(run_dir: Path) -> list[Path]:
    return sorted(run_dir.rglob("*.sh"))


def _inline_programs(text: str) -> list[tuple[int, list[str]]]:
    """Each `python3 -c "` statement as (line of its opener, lines opener..closer).

    Found by LINE, never by counting quotes, since counting is what a stray quote corrupts.
    """
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip() == INLINE_OPENER:
            close = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == '"'), None)
            assert close is not None, f"line {i + 1} opens `{INLINE_OPENER}` and no later line closes it"
            out.append((i + 1, lines[i : close + 1]))
            i = close
        i += 1
    openings = sum(INLINE_OPENER in line for line in lines)
    assert openings == len(out), (
        f"{openings} `{INLINE_OPENER}` statements but only {len(out)} are laid out as a block (opener alone on "
        "its line, closer alone on its line); lay it out that way or teach this test the new shape"
    )
    return out


def _received_by_python3(statement: list[str], run_dir: Path, workdir: Path) -> str:
    """Run the statement as written under bash; return the program python3 was handed after `-c`."""
    workdir.mkdir(parents=True)
    (workdir / "empty-path").mkdir()
    recorder = workdir / "recorder.sh"
    recorder.write_text('python3() { printf "%s\\0" "$@" > "$CALLED"; }\n')
    script = workdir / "statement.sh"
    script.write_text("\n".join(statement) + "\n")
    called = workdir / "called"
    proc = subprocess.run(
        [BASH, str(script)],
        capture_output=True,
        text=True,
        cwd=workdir,
        timeout=60,
        env={
            "PATH": str(workdir / "empty-path"),  # a backticked word is "command not found", not a command
            "HOME": str(workdir),
            "BASH_ENV": str(recorder),
            "CALLED": str(called),
            "RUN_DIR": str(run_dir),
        },
    )
    assert proc.returncode == 0 and not proc.stderr, f"bash said: {proc.stderr[:600]}"
    assert called.exists(), "python3 was never called"
    argv = called.read_bytes().decode().split("\0")[:-1]
    # A stray quote that leaves the count even splits the string at the next space: python3 then gets a
    # truncated program (a valid one, which does nothing) plus stray arguments.
    assert len(argv) == 2 and argv[0] == "-c", f"python3 was called with {len(argv)} arguments, not `-c <program>`"
    program = argv[1]
    last = statement[-2].strip()
    assert program.rstrip().endswith(last), (
        f"the program python3 received stops short of the writer's last line {last!r}"
    )
    return program


def test_the_replay_produced_every_script_there_is_to_check(run_dir):
    found = {p.name for p in _scripts(run_dir)}
    assert found >= EXPECTED, f"a tool generated nothing, so this test would not see its script: {EXPECTED - found}"


def test_bash_accepts_every_generated_script(run_dir):
    bad = []
    for script in _scripts(run_dir):
        proc = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            bad.append(f"{script.name} (rc={proc.returncode}): {proc.stderr.strip()[:300]}")
    assert not bad, "bash rejects generated scripts:\n  " + "\n  ".join(bad)


def test_every_embedded_python_program_compiles_as_bash_delivers_it(run_dir, tmp_path):
    bad, checked = [], 0
    for script in _scripts(run_dir):
        text = script.read_text()

        quoted = HEREDOC.findall(text)
        opened = len(HEREDOC_OPENER.findall(text))
        if opened != len(quoted):
            bad.append(f"{script.name}: {opened} python heredocs but only {len(quoted)} have a quoted delimiter")
        for delim, body in quoted:
            checked += 1
            try:
                compile(body, f"{script.name}:<<{delim}", "exec")
            except SyntaxError as exc:
                bad.append(f"{script.name} heredoc <<{delim}: {exc}")

        for n, (line, statement) in enumerate(_inline_programs(text)):
            checked += 1
            try:
                program = _received_by_python3(statement, run_dir, tmp_path / script.stem / str(n))
                compile(program, f"{script.name}:{line}", "exec")
            except (SyntaxError, AssertionError) as exc:
                bad.append(f"{script.name} inline program at line {line}: {exc}")

    assert not bad, "embedded Python that would not run:\n  " + "\n  ".join(bad)
    assert checked >= 4, f"only {checked} embedded programs were found; the patterns above have stopped matching"
