# Investigation — installing on a bare box (2026-09-23)

**Context.** First install of the repository on a clean machine: x86_64, Ubuntu
26.04.1 LTS under WSL2, RTX 3060 (12 GB), 31 GB RAM, 954 GB free, no conda, and
**no C/C++ toolchain at all** — no `gcc`, `g++`, `make`, `cmake` or `unzip`.
`sudo` required a password, so nothing system-level could be added
non-interactively.

That combination is not exotic. Ubuntu's minimal rootfs — WSL, cloud images and
`docker pull ubuntu:26.04` alike — ships no compiler. **This is a base-image
property, not a WSL one**, and anyone installing from a container or a fresh
cloud VM meets it identically.

Every finding below is evidenced against the tree, and the ones marked
**live-confirmed** were reproduced by the actual `--tool all` run, not by reading.

**Not reproduced here:** anything about the toolchain *breaking a build*
(e.g. gcc 15 vs scikit-learn 0.20.4). Those are predictions until they fire;
this document records only what was observed.

---

## Summary

| # | Finding | Kind | Severity |
|---|---|---|---|
| B1 | README "Requirements" omits the C/C++ toolchain | doc | user-blocking |
| B2 | `preflight()` never checks for a toolchain — SoluProt is *last* in `--tool all` | code | ~80 GB wasted |
| B3 | README says "~60 GB"; the installer computes **~83 GB** | doc | can abort a "sufficient" disk |
| B4 | `preflight()` runs *after* Miniforge3 is downloaded and installed | code | contradicts own comment |
| B5 | Preflight reports GPU `memory.total`, never `memory.free` | code | misleading sizing |
| B6 | `print_tool_status()` shows 6 of 12 tools; 3 detectors exist but are unused | code | wrong status |
| B7 | GPU occupancy detection **fails open** when `--query-compute-apps` is empty-but-successful | code | **correctness** |
| B8 | Three different toolchain strategies for three tools | design | inconsistency |
| B9 | README Quick start calls `binderscout` before it is on `PATH` | doc | first-run failure |
| B10 | `install.sh` appends to `~/.bashrc` unprompted, from 3 duplicated blocks | code | unasked mutation |
| B11 | The interactive menu cannot install ESMFold2 — the **default** refold engine | code | **capability loss** |
| B12 | `--yes` without `--tool` installs a 5-tool subset and reports total success | code | **false success** |
| B13 | Bare `install.sh </dev/null` exits **0** having installed nothing | code | **false success** |
| B14 | No `set -e`/`-u`/`pipefail`; three tools report success over broken installs | code | **false success** |
| B15 | `--cuda` is honoured by 3 of 7 torch installs; the banner claims it for all | code | wrong wheels |

---

## B7 — GPU occupancy detection fails open (most serious)

`tools/fleet.sh:144-150` documents an explicit invariant:

> Three distinguishable outcomes: confirmed-idle (launch), confirmed-busy
> (refuse, name the PID), could-not-determine (refuse — nvidia-smi failed, or
> ssh itself failed). **An empty `$busy` must never be read as "idle" when it
> could mean "couldn't check"**: nvidia-smi's own exit status is captured
> remotely (not discarded) and surfaced as a distinct sentinel (exit 97)
> instead of folding into empty stdout.

The hardening assumes the only route to an empty list is `nvidia-smi` *failing*.
There is a second route: it **succeeding with no rows**.

Measured on this box:

```
nvidia-smi --query-compute-apps=pid,used_memory  →  ""        (exit 0)
nvidia-smi --query-gpu=memory.used               →  6033 MiB
```

WSL2 cannot enumerate the Windows-side clients holding that memory, so it
reports success and zero rows while half the card is gone. Sentinel 97 never
fires, `$busy` is empty, and `fleet.sh:176-180` launches onto a GPU with
~6 GB already taken — the precise condition the comment says must never occur.

This is **not WSL-specific**. The same empty-but-successful result occurs for
compute processes owned by another user, and inside containers where other PID
namespaces are invisible. WSL is simply the case that made it reproducible.

Same root cause disables the guard: `tools/gpu_mem_guard.sh:183-189` selects the
largest GPU client as its kill victim from that same list. With the list always
empty it logs `no GPU client found` on every tick and never acts, while
`MemAvailable` stays below the floor. It runs, it logs, it protects nothing.

**Proposed fix.** Cross-check the process list against total occupancy and treat
a disagreement as *could-not-determine*, not as idle:

```bash
# in the REMOTE heredoc, after the existing compute-apps query
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
attributed=$(printf '%s\n' "$out" | awk -F', *' '{s+=$2} END {print s+0}')
# Occupancy that no visible process accounts for: cannot be called idle.
if [ "${used:-0}" -gt "$GPU_BUSY_MIB" ] && [ "$attributed" -eq 0 ]; then
    echo "unattributable: ${used} MiB in use, no visible compute client" >&2
    exit 96
fi
```

and give `96` a `reason` in the `case "$ssh_rc"` block at `fleet.sh:163-168`, so
it joins the existing refuse-unless-`FLEET_FORCE` path. That keeps the three
documented outcomes and closes the fourth, undocumented one. `gpu_mem_guard.sh`
needs the same cross-check before it concludes there is nothing to kill.

---

## B2 / B4 / B5 — `preflight()` is weaker than its docstring claims

`preflight()` (`install/install.sh:3118-3168`) states its purpose at `3113-3117`:

> Cheap sanity checks BEFORE the installer starts downloading tens of GB.
> Without this, a host with too little free space failed an hour in with an
> opaque tar/pip error deep inside install.log, **leaving half-built envs
> behind**.

Three ways the implementation falls short of that:

**B2 — no toolchain check.** It checks disk (aborts), GPU (advisory) and network
(advisory). A missing compiler produces exactly the failure the docstring
describes, and is not checked. The check *does* exist — `_build_usearch_v12()`
at `install/install.sh:2757-2766` loops over `git make g++ gcc` and names the
missing one — but SoluProt is the **last** of eleven tools in `--tool all`, so it
runs after ~80 GB has been fetched. `install.sh --help` documents the
requirement only inside the `soluprot` tool description; `preflight` is where it
belongs.

**B4 — it does not run before "any download" (live-confirmed).** `main()` calls
`detect_conda || exit 1` at `install.sh:3173`, which downloads and installs
Miniforge3. `preflight` is only reached at `install.sh:3219-3223`, under the
comment *"and before any download"*. Our run printed, in order:

```
⚠ No writable conda found — installing local Miniforge3
✓ Downloading Miniforge3 (~80 MB)
✓ Installing Miniforge3 (batch mode)
✓ Miniforge3 installed at <repo>/conda
▶ Preflight checks
```

So an abort in `preflight` now leaves ~500 MB of Miniforge3 behind — a half-built
environment, which is what it was written to prevent. Either move `preflight`
above `detect_conda` (it needs no conda — it checks `df`, `nvidia-smi`, `curl`),
or amend the comment. Moving it is better: the disk estimate already adds `1` GB
for local Miniforge at `install.sh:3138`, i.e. it is *expecting* to run first.

**B5 — GPU line reports total, not free (live-confirmed).** `install.sh:3151-3153`
queries `--query-gpu=name,memory.total`. Our run printed:

```
✓ GPU: NVIDIA GeForce RTX 3060, 12288 MiB
```

while only **6166 MiB** was free. On a dedicated Linux box those are nearly the
same; anywhere with a desktop — or WSL, where the Windows compositor holds
several GB permanently — they are not. Add `memory.free` to the query and print
both; a user sizing jobs from "12288 MiB" will OOM at half that.

---

## B6 / B11 — five hardcoded tool lists, three unintended memberships

The installer enumerates its tools in **five** separate hardcoded places, and
they do not agree:

| List | `install.sh` | Count | Missing |
|---|---|---|---|
| `print_tool_status` | `743` | **6** | RFD3, Protein-Hunter, BindCraft 2, AF3, ESMFold2, SoluProt |
| `select_tools_interactive` | `773` | **8** | BindCraft 2, AF3, ESMFold2, SoluProt |
| `--tool all` | `112-124` | **11** | AF3 *(deliberate — gated weights)* |
| dispatch order | `3313-3326` | **12** | — |
| uninstall | `3244-3256` | **12** | — |

The `11` is by design and documented (`install.sh:3236-3238`). The **6** and the
**8** are not — they are lists that were never updated when Parts L and M added
Protein-Hunter and RFD3, and when ESMFold2/SoluProt/BindCraft 2 landed.

**B6 — the status table (6).** Six of twelve appear under a heading reading
`=== Installed Tools ===`. The detectors for three of the missing ones
**already exist and are simply never called**: `is_protein_hunter_installed()`
(`719`), `is_rfd3_installed()` (`723`), `is_bindcraft2_installed()` (`727`).

**B11 — the interactive menu (8) is the serious one.** `install.sh:773`:

```bash
local tools=("BindCraft" "BoltzGen" "Mosaic" "Evaluator" "RFD3" "PXDesign" "Proteina-Complexa" "Protein-Hunter")
```

with exactly 8 matching `DO_*` assignments at `846-853`. A user who runs
`binderscout install` with no `--tool` — the interactive path the README offers
first, and what the TUI's "Install tools" entry shells out to — **cannot select
ESMFold2 at all**. ESMFold2 is the *default* refold engine (CLAUDE.md), and
without it the cross-engine gate has one engine instead of three, so every
design fails the `--min-engines 3` default and is ranked last.

This is mitigated, not hidden: `Evaluator/evaluate.sh:261-269` counts engines
before any GPU work and prints the shortfall plus the exact install command. So
the cost is a wasted install round-trip, not a silent bad ranking.

**Proposed fix.** Replace all five with one shared array of
`(flag, display-name, detector, installer)` tuples and derive every list from
it, so a new tool cannot land in one and miss another.

The detectors for three of them **already exist and are simply never called**:
`is_protein_hunter_installed()` (`719`), `is_rfd3_installed()` (`723`),
`is_bindcraft2_installed()` (`727`). The uninstall path at `install.sh:3245-3256`
enumerates all twelve, so the script knows the full set elsewhere.

**Proposed fix.** Add the three existing detectors to the loop; write
`is_af3_installed` / `is_esmfold2_installed` / `is_soluprot_installed` (each an
`env_exists` call, matching the others) and add those too. Better still, drive
the loop and the uninstall list from one shared array so the next tool cannot
land in one and miss the other.

---

## B1 / B3 / B9 — README

**B1 — no toolchain in Requirements.** `README.md:449-454` lists NVIDIA driver,
`git`, `curl`, disk, and states *"Conda/Miniforge is **not required**"*. A
compiler is required — for SoluProt's USEARCH v12 and scikit-learn 0.20.4 builds,
and as a fallback for Proteina-Complexa's `cpdb-protein`. A user passes every
documented check and still fails.

**B3 — the disk figure is ~40 % low (live-confirmed).** `README.md:453` says
"~60 GB". `preflight()`'s own per-tool table (`install.sh:3123-3136`) sums for
`--tool all` to `8+10+8+2+12+8+8+6+12+6+2 = 82`, `+1` for local Miniforge = **83**,
and `+6` with AF3 = 89. Our run printed:

```
✓ Disk: 953 GB free, ~83 GB needed
```

A 70 GB disk satisfies the README and is then refused by the installer.

**B9 — Quick start's first command cannot work.** `README.md:203-210`:

```bash
git clone … ~/BinderScout
cd ~/BinderScout
binderscout install --tool all
```

`binderscout` is a shortcut the installer *creates* in `bin/`; the
`export PATH="$(pwd)/bin:$PATH"` line appears later in the document. On a fresh
clone step 2 is `command not found`. The working first command is
`python3 binderscout.py install --tool all` (or `bash install/install.sh`).
CLAUDE.md's quick start has the same ordering.

---

## B8 — three toolchain strategies for three tools

| `install.sh` | Tool | Strategy |
|---|---|---|
| `1462` | PXDesign | conda-installs `gcc_linux-64<14` + `gxx_linux-64<14` into the env — never needs a system compiler |
| `2002-2014` | Proteina-Complexa | prefers system `gcc`, falls back to conda's `x86_64-conda-linux-gnu-gcc` via `CC`/`CXX`, else warns with both apt and conda commands |
| `2757-2766` | SoluProt / USEARCH | requires system `git make g++ gcc`; warns and `return 1` if absent |

All three are reasonable in isolation; together they mean whether a bare box can
install a given tool depends on which tool it is. PXDesign's approach is the one
consistent with the project's stated standalone-mode goal of *"zero system
permissions"* (CLAUDE.md) — it is also the only one that works when the user
cannot `sudo`.

**Proposed fix.** Keep the system compiler as the fast path, but let the
`binder-eval-soluprot` env provide `gcc_linux-64` / `gxx_linux-64` from
conda-forge when none is found, as PXDesign already does, and pass `CC`/`CXX`
into the USEARCH `make` (which `install.sh:2776-2786` already parameterises).
That removes the last hard system-level dependency from the install.

Note the `<14` pin at `install.sh:1462`: someone already established that
gcc ≥ 14 breaks that build. The same constraint plausibly applies to SoluProt's
2019-era scikit-learn 0.20.4, which currently compiles against whatever the host
provides — gcc 15.2 here. Unverified until the build runs.

---

## B12 / B13 / B14 — success is reported for installs that are not complete

None of these is WSL- or bare-box-specific. They matter most to CI, to a wrapper
script, or to an agent. Note that `install.sh:3370` *does* exit 1 when
`failed_tools` is non-empty — the defect is not the exit statement, it is that
two of these three paths never populate that array.

Foundational fact: **there is no `set -e`, `set -u` or `set -o pipefail`
anywhere in the 3,373 lines** (`grep -cE '^[[:space:]]*set -[eu]|pipefail'` → `0`).
Nothing aborts on a failed command unless it is explicitly checked.

**B13 — bare `install.sh </dev/null` exits 0 having installed nothing.** With no
`--tool` and stdin at EOF, `select_tools_interactive`'s `read` (`822`) returns
non-zero with an empty `choice`, which matches the `""` arm (`836`); the menu
defaults (`763-767`) are all `true`, so the "no tools selected" guard does not
fire. `confirm "Proceed with installation?"` (`870`) then hits the same EOF,
`answer` is empty, matches `n|no|""` (`355`), and the script prints `Aborted.`
and **`exit 0`**. On this box it is worse than "nothing": `detect_conda` at
`3173` runs *first* and has no prompt, so ~80 MB of Miniforge3 is downloaded and
`conda/` materialised before the abort — state left behind, success reported.

**B12 — `--yes` without `--tool` installs a 5-tool subset and calls it complete.**
`AUTO_YES` short-circuits `confirm` (`365-367`), so the abort in B13 never
happens — but the menu still EOF'd into its defaults. The run installs
**BindCraft, BoltzGen, Mosaic, Evaluator, RFD3** only, then prints
`=== Installation Summary === / All selected tools installed successfully.` and
exits 0. That is a strict subset of `--tool all`, which also sets PXDesign,
Proteina-Complexa, Protein-Hunter, ESMFold2, SoluProt and BindCraft 2. The
summary line is therefore not a sufficient success check.

> **B14 was reproduced live on 2026-09-23, on RFD3.** A transient DNS failure
> (the operator dropped a VPN mid-run; `/etc/resolv.conf` carries a Tailscale
> search domain) killed the weight download:
>
> ```
> ✗ Failed to install rfd3: <urlopen error [Errno -3] Temporary failure in name resolution>
> ✗ Downloading RFD3 weights (~few GB)
> ⚠ RFD3 weight download failed — retry: conda run -n binderscout_rfd3 foundry install rfd3 …
> ▶ Smoke test: RFD3 CLI check
> ✓ RFD3 installation complete
> [7/12] PXDesign
> ```
>
> `weights/foundry/` is **empty** — `foundry install rfd3` fetches
> `rfd3_latest.ckpt` (~2.5 GB) and nothing landed. RFD3 cannot run. Yet
> `install_rfd3` returned 0, so `failed_tools` does not contain it, the run
> continued, and the final summary will report success. The smoke test passed
> because it is a **CLI check** — it verifies the `rfd3` console script exists,
> not that a checkpoint does.
>
> **Correction (2026-09-24).** An earlier revision of this entry said the exit
> code hid the failure. It does not: `install.sh:3370` is
> `[[ ${#failed_tools[@]} -gt 0 ]] && exit 1 || exit 0`, and the completed run
> exited **1**. The mistake came from reading a wrapper's trailing `echo`
> instead of the installer's own status.
>
> The real defect is narrower and still serious: the exit code faithfully
> reports `failed_tools`, but **`failed_tools` is incomplete**. This run exited
> 1 only because AF3 and ESMFold2 failed *loudly*. RFD3 and Proteina-Complexa
> were equally broken and never entered the array, so had those two been the
> only failures the run would have exited **0** under
> `All selected tools installed successfully.` The exit code is exactly as
> trustworthy as the detection behind it, and the detection is what is broken.

> **B14 fired a SECOND time in the same run, on Proteina-Complexa** — different
> tool, different root cause, identical outcome. `complexa download
> --everything` died on a torch/torchaudio ABI mismatch:
>
> ```
> OSError: …/Proteina-Complexa/.venv/lib/python3.12/site-packages/torchaudio/lib/
>          _torchaudio.abi3.so: undefined symbol: torch_library_impl
> ✗ Failed to download ESM2 weights
> ✗ Downloading all models (complexa download --everything)
> ▶ Installing foldseek
> ✓ Proteina-Complexa installation complete
> [9/12] Protein-Hunter
> ```
>
> Measured afterwards:
>
> | weights | state |
> |---|---|
> | **Complexa** (its own core model) | **absent** |
> | **ESM2** | 64 KB / 2 entries — effectively empty (expected ~2.5 GB) |
> | ProteinMPNN | 45 MB ✓ |
> | LigandMPNN | 120 MB ✓ |
> | AF2 | 5.3 GB ✓ (symlinked to BindCraft's, `install.sh:1845-1852`) |
>
> The tool is missing **its own primary weights** and was reported complete.
> Two firings, two unrelated causes (a DNS blip; a wheel ABI mismatch), one
> install run — which makes this the installer's dominant failure mode rather
> than an edge case. Note also that the retry logic worked as designed
> (`attempt 1/2 failed, retrying…`) and still ended in a green line: retrying a
> step whose failure is non-fatal does not make the result correct.

**B14 — PXDesign, Protein-Hunter and RFD3 report success over broken installs.**
Each `install_*` ends on `print_ok "... installation complete"`, which returns 0,
so the `|| failed_tools+=(...)` guards at `3320-3323` never fire. The only hard
gate among the three is PXDesign's, and it is `install.sh:1678-1680`:

```bash
smoke_test "PXDesign import check" \
    "${CONDA_CMD}" run -n binderscout_pxdesign python -c "import torch; print('PXDesign env OK')" \
    || return 1
```

It imports `torch` and nothing else — not `protenix`, not `pxdbench`, not `jax`
or `dm-haiku` — and never calls `torch.cuda.is_available()`. So it passes even
when the Protenix install (`1476`), PXDesignBench (`1481`), the CUDA PyTorch
re-install (`1498`, whose failure leaves the CPU-only `torch==2.3.1` from
`requirements.txt` in place) and the dm-haiku/JAX pin (`1524`) have all
soft-warned. Protein-Hunter (`2432`) and RFD3 (`2323`) route even their own
smoke tests to `print_warn`, so they have no gate at all.

The failures *are* visible: `run_logged`'s failure branch (`336-341`) prints a
red `✗` and the last 30 lines, and `266` tees everything to `install.log`. It is
the machine-readable contract that is wrong.

**Proposed fix.** Make each tool's smoke test import the packages that tool
actually needs and check CUDA where relevant; promote Protein-Hunter's and
RFD3's smoke tests from `print_warn` to `|| return 1`; and make the final
summary exit non-zero when `failed_tools` or `FAILED_EXAMPLES` is non-empty. For
B12/B13, refuse to proceed when `TOOL_SPECIFIED` is false and stdin is not a TTY
(`[[ -t 0 ]]`), rather than falling through to menu defaults.

## B15 — `--cuda` reaches 3 of 7 torch installs, but the banner claims all of them

Found live: the run was started with `--cuda 12.4`, the banner printed

```
CUDA: 12.4 | Arch: x86_64 | Standalone: auto | Skip examples: true
```

and the very next torch install logged `✓ Installing PyTorch cu121 (x86_64)`.

`CUDA_VERSION` (`install.sh:79`, set from `--cuda` at `157`) is interpolated in
three places:

| line | use |
|---|---|
| `946` | BindCraft — passes `--cuda "${CUDA_VERSION}"` to `install_bindcraft.sh` |
| `1495-1497` | PXDesign — `--index-url .../cu${CUDA_VERSION//./}` |
| `1664` | PXDesign — `nvidia/label/cuda-${CUDA_VERSION}.0` |

Four more hardcode a wheel index and ignore the flag entirely:

| line | value |
|---|---|
| `1116` | `torch==2.5.1+cu121` + `--index-url .../cu121` (BoltzGen) |
| `2294` | `--index-url .../cu121` |
| `2395` | `--index-url .../cu121` |
| `2638` | `local _torch_index=".../cu124"` |

`--help` describes `--cuda` as *"CUDA version for conda package resolution"*,
which is a partial defence — but `1495` and `2294`/`2395`/`2638` are all **pip**
wheel indexes, so the distinction is not what separates the two groups, and the
banner announces one CUDA version for the whole run.

**Observed live: three CUDA variants in one run.** The same install that
printed `CUDA: 12.4` produced:

| env | torch |
|---|---|
| `BoltzGen` | `2.5.1+cu121` |
| `binderscout_pxdesign` | `2.6.0+cu124` |
| `Proteina-Complexa/.venv` | `2.7.0+cu126` |

The third is not even one of the hardcoded indexes above — it comes from
Proteina-Complexa's own upstream resolution — and it is what produced B14's
second firing: a `torchaudio` wheel built against a different torch than the
`2.7.0+cu126` that landed, so `import torchaudio` raises `undefined symbol:
torch_library_impl` and the weight download dies. A single declared CUDA
version per run, honoured everywhere, would have made that mismatch
impossible.

**Why it matters beyond cosmetics.** cu121 wheels carry no `sm_120`/`sm_121`.
That is precisely the failure class CLAUDE.md documents on GB10, where a wrong
torch build is silently CPU-only or cannot lower bf16. On this box (sm_86,
driver 13.3) cu121 is fine, so the defect is invisible here — which is exactly
why it survives.

**Proposed fix.** Derive every index from `CUDA_VERSION` (`cu${CUDA_VERSION//./}`)
with a per-tool override only where a tool genuinely pins an older stack, and
make that override explicit and logged. Failing that, print the *effective*
CUDA per tool rather than one banner value.

## B10 — `~/.bashrc` is modified unprompted, from three copies

`install.sh:1215-1217`, `1986-1988` and `2162-2164` each contain the same block:

```bash
if ! grep -q '.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
    echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.bashrc"
```

Three copies of one behaviour, so a fix must be made three times. It also sits
awkwardly against standalone mode's stated goal of *"zero system permissions"*
(CLAUDE.md) — writing to a user's shell rc is not something the install
announces up front, and `--uninstall` explicitly does not remove it
(`install.sh:3277-3286`). Factor it into one `_ensure_local_bin_on_path`
helper, and say so in the install banner.

## Provenance

B1-B10 were found by direct inspection and by watching the live `--tool all`
run. B11-B14 came from a 56-agent adversarial sweep of `install.sh`
(1,007 tool calls): 51 candidate defects were raised, **43 were refuted** on
inspection of the actual lines, and 7 survived. The refuted ones are not
recorded here — that ratio is the reason each surviving entry carries its own
`file:line` evidence rather than a summary.

## Proposed fix order

1. **B14 + B12 + B13** — false-reported success is the worst class here: every
   other defect is discoverable by reading the log, these three defeat any
   automated check. Non-zero exit on `failed_tools`, real smoke tests, and
   refuse a non-TTY run with no `--tool`.
2. **B7** — correctness; a job can be launched onto an occupied GPU.
3. **B11 + B6** — one shared tool registry replacing five hardcoded lists.
   B11 costs a user a whole install round-trip to discover.
4. **B2 + B4** — hoist `preflight` above `detect_conda` and add the toolchain
   check. Together they make a bare-box failure cost seconds instead of ~80 GB.
5. **B1 + B3 + B9** — README; no code risk.
6. **B5** — add `memory.free` to the preflight GPU line.
7. **B10** — factor the three `~/.bashrc` blocks into one helper.
8. **B8** — the largest change; do it once the rest have landed.

None of these are blocking the install currently running: every one is either a
reporting defect, a path not taken (`--tool all --yes --skip-examples` avoids
B11/B12/B13 entirely), or already paid for (B4's Miniforge3 download succeeded).
