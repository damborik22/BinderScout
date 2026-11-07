"""``binder-compare refold-protenix``: a thin wrapper that runs scripts/refold_protenix_v1.py in-process.

The adapter itself (licence pin, command line, PAE reading) is tested in test_refold_protenix_v1_script.py;
what is pinned here is what the wrapper adds: the torch kernels are ALWAYS forwarded and cannot be turned
off, the adapter's exit code (3 = partial failure) reaches the shell, and the flags reach the adapter.
No GPU, no Protenix: the adapter's ``main`` is replaced by a recorder.
"""

from __future__ import annotations

import pytest
from binder_comparison import main as main_mod
from binder_comparison.cli import refold_protenix

KERNELS = ["--trimul-kernel", "torch", "--triatt-kernel", "torch", "--layernorm-type", "torch"]
BASE = ["refold-protenix", "--sequences", "seqs.fasta", "--target-seq", "ACDEFGHIKL", "-o", "out.csv"]


@pytest.fixture()
def adapter(monkeypatch):
    """Replace the adapter's ``main``; ``calls`` records every argv it is invoked with."""
    calls: list[list[str]] = []
    state = {"rc": 0}

    def fake_main(argv):
        calls.append(list(argv))
        return state["rc"]

    monkeypatch.setattr(refold_protenix, "_load_adapter_main", lambda scripts_path: fake_main)
    monkeypatch.delenv("PROTENIX_MODEL_DIR", raising=False)
    return calls, state


def _run(argv):
    main_mod.main(argv)


def _opt(argv, flag):
    return argv[argv.index(flag) + 1]


def test_registered_as_a_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["--help"])
    assert exc.value.code == 0
    assert "refold-protenix" in capsys.readouterr().out
    assert "refold_protenix" in refold_protenix.__name__
    from binder_comparison import cli

    assert "refold_protenix" in cli.__all__


def test_help_works_and_states_environment_and_licence(capsys):
    with pytest.raises(SystemExit) as exc:
        main_mod.main(["refold-protenix", "--help"])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Protenix environment" in out
    assert "Apache-2.0" in out
    assert "v1." in out


def test_required_arguments_and_core_flags_are_forwarded(adapter):
    calls, _ = adapter
    _run([*BASE, "--output-dir", "dd"])
    assert len(calls) == 1
    argv = calls[0]
    assert _opt(argv, "--sequences") == "seqs.fasta"
    assert _opt(argv, "--target-seq") == "ACDEFGHIKL"
    assert _opt(argv, "--output") == "out.csv"
    assert _opt(argv, "--output-dir") == "dd"
    assert _opt(argv, "--num-seeds") == "1"
    assert _opt(argv, "--num-samples") == "5"
    assert "--resume" not in argv
    assert "--no-msa" not in argv
    assert "--model-dir" not in argv
    assert "--model-name" not in argv


def test_default_output_dir_is_refold_protenix(adapter):
    calls, _ = adapter
    _run(BASE)
    assert _opt(calls[0], "--output-dir") == "./refold_protenix"


def test_torch_kernels_are_always_forwarded_with_exact_values(adapter):
    calls, _ = adapter
    _run(BASE)
    argv = calls[0]
    assert _opt(argv, "--trimul-kernel") == "torch"
    assert _opt(argv, "--triatt-kernel") == "torch"
    assert _opt(argv, "--layernorm-type") == "torch"
    assert argv.count("--trimul-kernel") == argv.count("--triatt-kernel") == argv.count("--layernorm-type") == 1


@pytest.mark.parametrize("flag", ["--trimul-kernel", "--triatt-kernel", "--layernorm-type"])
@pytest.mark.parametrize("value", ["torch", "cuequivariance"])
def test_user_supplied_kernel_flags_are_refused(adapter, capsys, flag, value):
    calls, _ = adapter
    with pytest.raises(SystemExit) as exc:
        _run([*BASE, flag, value])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert flag in err
    assert "always" in err and "torch" in err
    assert calls == []  # refused before the adapter ran


def test_model_name_is_not_exposed(adapter, capsys):
    calls, _ = adapter
    with pytest.raises(SystemExit) as exc:
        _run([*BASE, "--model-name", "protenix-v2"])
    assert exc.value.code == 2
    assert "--model-name" in capsys.readouterr().err
    assert calls == []


def test_partial_failure_exit_code_3_passes_through(adapter):
    _, state = adapter
    state["rc"] = 3
    with pytest.raises(SystemExit) as exc:
        _run(BASE)
    assert exc.value.code == 3


@pytest.mark.parametrize("rc", [1, 2])
def test_other_nonzero_exit_codes_pass_through(adapter, rc):
    _, state = adapter
    state["rc"] = rc
    with pytest.raises(SystemExit) as exc:
        _run(BASE)
    assert exc.value.code == rc


def test_success_returns_without_exiting(adapter):
    calls, state = adapter
    state["rc"] = 0
    _run(BASE)  # must not raise SystemExit
    assert len(calls) == 1


def test_resume_num_samples_num_seeds_and_no_msa_passthrough(adapter):
    calls, _ = adapter
    _run([*BASE, "--resume", "--num-samples", "3", "--num-seeds", "2", "--no-msa"])
    argv = calls[0]
    assert "--resume" in argv
    assert "--no-msa" in argv
    assert _opt(argv, "--num-samples") == "3"
    assert _opt(argv, "--num-seeds") == "2"


def test_allow_no_msa_and_msa_cache_dir_passthrough(adapter):
    calls, _ = adapter
    _run([*BASE, "--allow-no-msa", "--msa-cache-dir", "cache"])
    argv = calls[0]
    assert "--allow-no-msa" in argv
    assert _opt(argv, "--msa-cache-dir") == "cache"


def test_model_dir_defaults_to_env_var(adapter, monkeypatch, tmp_path):
    calls, _ = adapter
    monkeypatch.setenv("PROTENIX_MODEL_DIR", str(tmp_path / "from_env"))
    _run(BASE)
    assert _opt(calls[0], "--model-dir") == str(tmp_path / "from_env")


def test_explicit_model_dir_overrides_env_var(adapter, monkeypatch, tmp_path):
    calls, _ = adapter
    monkeypatch.setenv("PROTENIX_MODEL_DIR", str(tmp_path / "from_env"))
    _run([*BASE, "--model-dir", str(tmp_path / "explicit")])
    assert _opt(calls[0], "--model-dir") == str(tmp_path / "explicit")


def test_empty_env_var_is_not_a_model_dir(adapter, monkeypatch):
    calls, _ = adapter
    monkeypatch.setenv("PROTENIX_MODEL_DIR", "")
    _run(BASE)
    assert "--model-dir" not in calls[0]


def test_the_real_adapter_module_is_found_and_exposes_main():
    main = refold_protenix._load_adapter_main(None)
    assert callable(main)
    assert main.__module__ == "refold_protenix_v1"


def test_missing_scripts_path_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        refold_protenix._load_adapter_main(tmp_path / "nope")
