# Campaign status monitor — design

**Date:** 2026-10-30
**Status:** approved, phase 1 in implementation
**Problem:** a campaign's arms run on five boxes with no shared filesystem, and
there is no way to see their state without hand-probing each one over SSH.

## Why the obvious thing is wrong

A progress bar per arm is not enough, and the measurement that proves it was taken
on the completed pMHC RFD3 arm (2026-10-30):

| | |
|---|---|
| designs land | **10 at a time** (each burst inside 1 s) |
| gap between bursts | **4213, 4182, 4185, 4164 s** (~70 min) |

So for 70 minutes at a stretch the design count does not move. Polling once a
second yields a number no fresher than polling once an hour. A bar reading
`20/50` can be a full batch behind the truth, and **a stalled arm and a healthy
arm are indistinguishable on the count alone.**

Measured at the same moment on the live TfR1 RFD3 arm:

| signal | reading | what it implies |
|---|---|---|
| design count | 0 | looks dead |
| log mtime | silent 664 s | looks dead |
| **process + GPU** | **99% util, 6692 MiB held, CPU 695 s / 692 s elapsed, state `Rl`** | **healthy, mid-batch** |

Only the third signal is continuous. Liveness must therefore come from the
process and the GPU, not from output files — the opposite of what a progress bar
normally does.

This is the same class of error as the problems already logged: P-55 (BindCraft
OOM reported `rc=0`), P-57 (Proteina-Complexa succeeded and the collector read
zero), P-59 (400 Protein-Hunter designs against the wrong target, invisible for a
day).

## Scope

In: a `binderscout status` subcommand; a stdlib-only probe layer; a terminal
renderer; an SSH fan-out across the fleet. Later phase: a pushed page.

Out: changing any tool, any run script, or the Evaluator.

## Architecture

```
status/
├── probes.py     one probe per tool -> (done, total, mtimes, warnings)
├── liveness.py   process + GPU attribution
├── collect.py    discover runs, classify state, build the document
├── remote.py     SSH fan-out
├── render_term.py
└── schema.py     document shape + version
```

**Stdlib only.** The same rationale as `binderscout.py` itself: the probe must
run on any box with system Python 3.10, including one whose conda envs are
irrelevant or absent. This is what lets `remote.py` ship the probe source over
stdin rather than requiring a checkout on the far box — so there is no version
skew between what the local renderer expects and what a remote box reports.
Pinned by a test asserting the probe imports nothing outside a stdlib allowlist.

**Probes count, they never parse.** A monitor must not crash on a half-written
CSV. Counting files is also fast enough to need no cache — and a cache *is*
staleness, which is the whole point. This is why the Evaluator's extractors are
not reused despite knowing the same layouts: they parse, they are slow, and they
live in a conda env. The duplication is paid for by a test asserting each probe's
glob agrees with its extractor's.

### State classification

Five states, from (done, total, proc_alive, settings.json present, log markers):

| state | condition |
|---|---|
| `done` | `done >= total` |
| `running` | process alive — **regardless of output age**, per the 70-minute measurement |
| `dead` | no process, `0 < done < total` |
| `dead` | no process, `done == 0`, **but `settings.json` exists** |
| `queued` | no process, no output, **no `settings.json`** |

The fourth row is load-bearing and comes free from an existing convention: every
run script writes `settings.json` *before* the design step. So a tool directory
holding settings and nothing else is a tool that started and died in seconds —
exactly the `EnvironmentNameNotFound` and argument-discarding-wrapper failures
recorded in `CLAUDE.local.md` §6.2/§6.3, which cost a campaign round its
PXDesign arm and looked identical to a fast crash in `sacct`.

The probe also greps the log tail for `run_arm.sh`'s
`######## <tool> FAILED` marker and reports the captured `rc`.

### Liveness, without the pgrep trap

**`pgrep -f` is forbidden** — it matches its own command line, the bug recorded in
`CLAUDE.local.md` and deliberately avoided in `tfr1_queue.sh` by using `kill -0`.
Instead: scan `/proc/*/cmdline`, match on the executable path, exclude own PID and
ancestors, then attach GPU memory per PID from
`nvidia-smi --query-compute-apps=pid,used_memory`. Pinned by a test asserting the
string `pgrep -f` appears nowhere in the module.

### ETA from cadence, never from the count

Cluster output mtimes (writes within 2 s = one batch), take the median inter-batch
gap and the median batch size, then
`eta = ceil(remaining / batch_size) * median_gap`. Report `null` until **two**
batches have been observed. A fabricated ETA is worse than none.

### Correctness gates

Cheap fields the probe already has the file open for, each mapping to a logged
loss:

- **RFD3** `|fixed_com|` from the first sidecar. `< 1.0 Å` means
  `infer_ori_strategy: hotspots` is missing and every design in the arm is void
  (304 backbones lost once already). Rendered inline as a warning.
- **RFD4** chain count in the first generated `.cif` against the configured chains.
- **Sequence-fed tools** configured chain count vs `cfg.chains` — the P-59 class.

### Freshness, by surface

- **Terminal:** probe on demand, no cache. Nothing is fresher than the filesystem
  read at the moment of asking. Hosts concurrent, per-host timeout; an
  unreachable host renders as `unreachable` beside live bars and never aborts the
  view (Clara is offline now and must not break it).
- **Page (phase 2):** necessarily a push, so it carries its own data age and greys
  out past a threshold. The risk is not the interval, it is a dead pusher showing
  old numbers that look current.

### Hygiene

The repo is public. The host list comes from `$BINDERSCOUT_FLEET` (falling back to
`$FLEET_MACHINES`), defaulting to local-only. No hostname, username or absolute
home path enters a tracked file; the existing tree test enforces this.

## Testing

| test | pins |
|---|---|
| `test_probes.py` | fake run dir per tool -> (done, total) |
| `test_state_classification.py` | all five states, incl. settings-without-output -> `dead` |
| `test_liveness_never_uses_pgrep_f.py` | the string is absent |
| `test_probe_is_stdlib_only.py` | import allowlist |
| `test_cadence_eta.py` | the measured RFD3 mtimes -> batch 10, gap ~4190 s, `None` under two batches |
| `test_unreachable_host_does_not_abort.py` | one host failing still renders the rest |

## Phasing

1. **Done.** Probe + classification + terminal renderer + SSH fan-out, as
   `binderscout status [--local] [--json] [--watch [SECS]]`. Validated against the
   live pMHC and TfR1 arms, which is where five of its bugs came from; fixtures
   found none of those. 70 tests, 11 mutations killed.
2. **Done.** The pushed page, reading the same document from the `db` capability
   at `status/latest`. The page's own data age is its most prominent figure and
   turns amber at 5 min, red at 20 min, with text saying the push may have
   stopped — because a dashboard showing an old number as current is the failure
   this feature exists to prevent. Deadlines come from a `deadlines` map in the
   same document, since the probe cannot know them.

   **Its honest limit:** nothing on the boxes can write to that store. The push
   is `binderscout status --json` captured and written by an agent session, so
   the page is exactly as current as the last push and says so rather than
   implying live data. A cron on the orchestrator cannot replace that without a
   server-side writer, which does not exist here.

   **What that limit cost, measured 2026-10-31.** Scheduling the push on a
   10-minute timer made the page current and made the session unusable: each
   firing is a visible agent turn, so a surface built to be checked at a glance
   produced a notification every ten minutes, almost always to report that
   nothing had changed. The push is the wrong mechanism for an unattended
   refresh, and no interval fixes that — the cost is per firing, not per change.
3. **Done (2026-10-31), and now the default unattended surface.**
   `binderscout status --html FILE` writes a self-contained page that any box can
   regenerate from a timer and serve over HTTP. No account, no token, nothing to
   push, and no agent in the loop, so a 5-minute refresh costs nothing and
   notifies nobody.

   Three things it must get right, each pinned by a test:
   - **Grouping is imported, not reimplemented** (`_rows`, `_deadline_for` from
     the terminal renderer). Two copies would drift, and the first rule to drift
     would be the dedup key `(run, tool)` — collapsing on `(campaign, tool)`
     shows one RFD3 arm for TfR1 and silently drops 350 designs.
   - **The freshness band is recomputed in the browser from the stamp.** Baked in
     at render time it reads `fresh` forever once the generator dies, which is
     the single failure this page exists to catch. Server-side the band defaults
     to `stale`, so the no-script case errs toward distrust.
   - **The file is written beside and renamed.** The generator's period and the
     browser's 60 s poll are unrelated clocks, so a read eventually lands inside
     a write; in-place writing hands that reader a truncated page, which renders
     as blank and looks exactly like a dead fleet.

   Serving it is deliberately left to the operator: binding a port and installing
   a persistent timer are machine-local decisions, and the unit files are staged
   rather than installed. `python3 -m http.server` on one directory is adequate
   on a trusted lab LAN and must not be exposed beyond it.
4. Optional: `progress.jsonl` heartbeats written by the run scripts, preferred by
   the probe when present. Deferred because it cannot see any arm now running.
