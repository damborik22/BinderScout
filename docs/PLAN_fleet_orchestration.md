# PLAN — BM5 fleet orchestration (LAN + Clara)

**Status:** design approved, not yet implemented
**Date:** 2026-07-27
**Branch:** `fleet-orchestration`

---

## 1. Why now

BM5 (DGX Spark) moved from a desk to the server room and is now on the Loschmidt
Lab subnet `<LAB_SUBNET>`, the same segment as BM1, BM2 and BM4, with public
MUNI addressing and no NAT. muni-disk (CIFS) mounts directly without a VPN.

That changes the coordination model. Until now the four machines shared no
network path, so campaigns were coordinated asynchronously through documents on
muni-disk: the orchestrator wrote `CLUSTER/<tool>_<machine>_SETTINGS.md`, a
Claude session or a human on each box executed it, packaged a tarball into
`RESULTS/`, and appended to `PROGRESS.md`. That model works but requires a
babysitter per machine and makes every dispatch a round trip through a
`soft`-mounted CIFS share.

With direct SSH available, BM5 can drive BM1/BM2/BM4 the same way it already
drives Clara. This plan makes that the primary path and demotes muni-disk from
coordination substrate to archive of record.

---

## 2. Fleet inventory (probed 2026-07-27)

> **This repo is public — no infrastructure identifiers live here.** Hostnames, IPs,
> usernames, home paths and host-key fingerprints are kept in the gitignored
> `docs/local/fleet-access.md`. Placeholders like `<BM5_HOST>` elsewhere in this file
> resolve there. Reach machines by their `~/.ssh/config` alias (`bm1`/`bm2`/`bm4`/`bm5`),
> never by a literal address.

| | **BM5** | **BM1** | **BM2** | **BM4** |
|---|---|---|---|---|
| Arch | aarch64 | x86_64 | x86_64 | x86_64 |
| OS | Ubuntu 24.04.4 | Ubuntu 24.04.4 | Ubuntu 24.04.4 | Ubuntu 24.04.4 |
| GPU | GB10 (unified) | RTX 3090 24 GB | RTX 3090 24 GB | RTX 3090 24 GB |
| Driver | 580.159.03 | 580.159.03 | 580.159.03 | 595.71.05 |
| Cores / RAM | 20 / 121 GB | 16 / **31 GB** | 16 / 62 GB | 16 / 62 GB |
| Disk free | 2.9 T | 1.5 T | 1.6 T | 921 G |
| tmux | 3.4 | 3.4 | 3.4 | 3.4 |
| Role | orchestrator + refold | design worker | design worker | design worker |

SSH host keys pinned in `~/.ssh/known_hosts` on BM5 after fingerprint
verification against two independent scans:

The fingerprints themselves are recorded in `docs/local/fleet-access.md`.

Key-based login from BM5 works to all three as of this date. No passwordless
sudo exists on any machine, and none is requested by this plan.

### Capability constraints that follow from the hardware

- **BM1 has half the RAM of its siblings (31 GB).** The BindCraft JAX RSS leak
  killed BM4 at 58 GB after nine days. On BM1 the same run OOMs far sooner, so
  BM1 must not take long BindCraft jobs. The three x86 boxes are *not*
  interchangeable.
- **All three x86 boxes are 24 GB Ampere**, so the RFD3 fragmentation OOM applies
  fleet-wide: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is mandatory
  before `rfd3 design` on any of them, not a BM4 quirk.
- **BM5 is aarch64**, so Protein-Hunter cannot run there (PyRosetta has no
  aarch64 wheels). PH work must be assigned to BM1/BM2/BM4 or Clara.
- **BM4 was running `binder-compare refold-boltz2` at design time** (started
  10:11, 19 GB VRAM). Refold is nominally BM5's role; consolidating that is
  worth doing, but not by interrupting a live job.

---

## 3. Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Control model | **Direct SSH fan-out** | Slurm's value is arbitrating contention among many jobs and users; here it is three GPUs and one campaign. Reuses the validated `clara-deploy.md` shape instead of introducing a new architecture. Slurm remains a later upgrade if contention becomes real. |
| D2 | Job launch | **tmux** | Installed 3.4 on all four. Survives SSH disconnect, `tmux has-session` is an unambiguous liveness check, and a human can attach to a live job. Single code path — no setsid fallback. |
| D3 | Tooling | **One `fleet.sh`** | `probe\|status\|launch\|poll\|fetch`, ~150 lines. Repeatable and testable; ad-hoc SSH incantations drift. |
| D4 | Archive model | **BM5 pulls, then archives** | Worker packages locally, BM5 rsyncs over LAN, verifies, refolds, then pushes one copy to muni-disk. Keeps CIFS off the hot path and satisfies the standing rule that refold inputs are staged Spark-local. |
| D5 | Clara VPN | **Manual, by the human** | No stored password, no systemd unit, no sudoers grant. Reverted from an earlier always-on proposal. |
| D6 | Clara key | **Passphrase-less; the VPN is the gate** | *Revised 2026-07-27 (superseded an earlier passphrase + `ssh-add -t 8h` decision).* With no passphrase there is no `ssh-add` step and no key-side window: Clara is reachable exactly while the manually-started, gateway-timed tunnel is up. Access control is the tunnel, opened by hand every time. |
| D7 | Clara `authorized_keys` | **`restrict,pty,expiry-time` — no `from=`** | *Applied 2026-07-27.* `from=` was dropped after verification: BM5 reaches Clara through the VPN, so the source address Clara sees is a per-session pool address (<CIIRC_VPN_POOL>) shared with other CIIRC users — pinning it is fragile and weak. `restrict` blocks port forwarding both ways (verified: `-R` refused, `-L` carries no traffic), `pty` keeps interactive shells usable. Since the key is unprotected, these options are the real protection, not hardening. |
| D8 | LAN key | **Left passphrase-less** | BM1/2/4 are the same trust domain with no VPN adjacency. Requiring an unlock would make routine monitoring need a human present. Asymmetry is deliberate: Clara is the credential worth protecting. |

---

## 4. Architecture

```
BM5  aarch64 GB10 · ORCHESTRATOR + REFOLD
 ├── ssh bm1   RTX 3090 ┐
 ├── ssh bm2   RTX 3090 ├── LAN · direct · no VPN · no NAT
 ├── ssh bm4   RTX 3090 ┘
 └── ssh clara CIIRC Slurm ─── human-established FortiClient tunnel

muni-disk (CIFS) ── archive of record, OFF the hot path
```

BM5 is the sole writer of campaign state for LAN jobs, which removes the
`PROGRESS.md` append races that the multi-writer model produced.

---

## 5. Components

### 5.1 Fleet SSH config

`Host bm1|bm2|bm4` aliases in `~/.ssh/config` with `ControlMaster auto` and
`ControlPersist 10m`. Multiplexing is the efficiency win: polling a running job
currently costs a full TCP and crypto handshake per check, whereas every poll
after the first rides the established connection.

### 5.2 Fleet inventory cache

`fleet.sh probe` writes `~/.claude/fleet/inventory.json` — per machine: arch,
GPU name and VRAM, free RAM and disk, conda envs present, BindMaster git SHA and
branch, muni-disk mount state, tmux version, reachability and timestamp.

This exists so tool-to-machine assignment is a lookup against reality rather
than recall. The constraints in §2 (BM1's RAM ceiling, BM5's PH block) are
encoded as data, not as prose someone has to remember.

### 5.3 Remote launch

```
ssh bmN "tmux new-session -d -s <TARGET>_<tool> \
   'cd <rundir> && bash run.sh > run.log 2>&1'"
```

Session named `<TARGET>_<tool>` so collisions are self-evident and `tmux ls`
reads as a job registry. The run script writes `settings.json` before the heavy
workload starts, per the existing per-run reproducibility convention.

### 5.4 Admission check, not a queue

Before launching, BM5 checks `nvidia-smi --query-compute-apps` and `tmux ls` on
the target and **refuses** if the GPU is occupied, unless explicitly forced.
With three boxes and one campaign that is the whole scheduler. Refusing loudly
beats queueing silently.

### 5.5 Result transport

Worker packages the tarball locally per the existing `packaging.md` convention.
BM5 pulls with `rsync --partial` (not `--append-verify` — it skips a
destination file whose size is already >= the source's, which would keep a
stale archive on re-fetch after a re-run), verifies integrity, refolds
locally, then pushes one archive copy to muni-disk out of band.

### 5.6 Clara access

The human starts the CIIRC VPN manually, every time:

```bash
vpn-ciirc        # = sudo openfortivpn -c /etc/openfortivpn/ciirc.conf
```

That is the whole access step. The key is passphrase-less, so there is nothing
to unlock — once the tunnel is up, `ssh clara` works. The tunnel is
gateway-timed and drops on its own after roughly a working day, which is also
what ends the access window.

Clara-side `authorized_keys` entry for this key:

```
restrict,pty,expiry-time="20270727" ssh-ed25519 AAAA... <CLARA_USER>@<BM5_HOSTNAME>-clara
```

`fleet.sh` detects tunnel state with `ip link show ppp0` and a short-timeout
`ssh clara true`, and fails fast with a clear message when down rather than
hanging on split-horizon DNS.

---

## 6. Data flow for one job

```
target dossier → orchestrator picks tool + machine (inventory lookup)
  → BM5 renders run script locally (configurator or template)
  → scp to bmN:runs/<target>/<tool>/
  → preflight: GPU free? env present? disk headroom?
  → tmux launch; run script writes settings.json
  → BM5 polls the per-tool source-of-truth file
  → job ends → BM5 rsync pulls the tarball, verifies
  → BM5 refolds locally (Boltz-2 + AF3 + ESMFold2)
  → BM5 writes PROGRESS.md and pushes the archive to muni-disk
```

---

## 7. Security model

**What BM5 holds:** passphrase-less keys for both the LAN machines and Clara.
Clara access is gated by the manually-started VPN tunnel, not by the key.

**What BM5 does not hold:** any VPN password, any sudo capability locally or on
the cluster.

**Acknowledged residual exposure.** The Clara key file is `0600 <BM5_USER>`
and unencrypted, so it is readable by anything running as that user — including
the pip dependency trees of the seven design environments, which execute
third-party code as `<BM5_USER>`. A copy of that key is a working credential.
Two things bound the damage: it is useless while the tunnel is down, which is
most of the time, and the Clara-side `restrict` blocks using it to forward
ports into the CIIRC network (verified). Accepted knowingly — the alternative
was a passphrase, which was considered and deliberately rejected in D6.

**Known weak point, not fixable locally.** `<CLARA_USER>` is a shared CIIRC account,
so key restrictions do not narrow the *account*. A genuinely scoped identity
requires CIIRC to issue a service account — an external request, tracked in §10.

**Related exposure noted, deferred.** BM5's root filesystem is unencrypted ext4
(`/dev/nvme0n1p2`, no dm-crypt), and a second account `micro` (uid 1001) is in
the `sudo` group. Anyone with physical access to the machine or root via that
account can read `~/.ssh`. Recorded here so the decision is explicit rather than
accidental.

---

## 8. Error handling

| Condition | Behaviour |
|---|---|
| Machine unreachable | Marked down in the inventory and surfaced. Never a silent skip. |
| tmux session gone, no output | Treated as a crash; BM5 pulls `run.log` for diagnosis. |
| GPU busy at launch | Refuse, report which PID holds it. No silent queueing. |
| BindCraft RSS > 50 GB | Poll-time check; kill and report (BM4 was kernel-killed at 58 GB). Threshold is lower on BM1 given 31 GB RAM. |
| RFD3 OOM | Prevented at launch by exporting `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. |
| Boltz-2 complex > ~820 tokens on BM5 | Refuse to launch locally — this hangs the whole box and needs a force-restart. |
| VPN down | Clara operations fail fast with an explicit message, not a DNS hang. |
| Clara unreachable | Almost always the tunnel. `status` reports `tunnel=DOWN`; prompt the human to re-run `vpn-ciirc`. The `key=` field is informational only with a passphrase-less key. |
| rsync partial | `--partial` (not `--append-verify` — see §5.5); verify tarball integrity before removing anything remote. |

---

## 9. Verification

1. `fleet.sh probe` returns a complete inventory for all three LAN machines
   (BM1/BM2/BM4) — the smoke test. BM5 is the orchestrator and is never a
   probe target.
2. A `sleep 60` canary job per machine exercises launch → poll → detect-exit →
   cleanup without consuming GPU time.
3. Admission check verified by attempting a launch against a machine with a
   busy GPU and confirming refusal.
4. Clara path verified by: tunnel down → `fleet.sh status` reports it clearly;
   tunnel up + key unlocked → `ssh clara true` succeeds; after 8 h → access
   lapses and the failure message names the cause.
5. `restrict` verified by confirming port forwarding to Clara is refused while
   `sbatch`/`squeue` still work.

---

## 10. Out of scope / deferred

- **Slurm across the lab** (D1 alternative) — revisit only if job contention
  becomes real.
- **Forced-command allowlist on the Clara key** — available if the threat model
  tightens; costs ad-hoc log reading, which is most of cluster debugging.
- **CIIRC service account** — an external request; would fix the account-breadth
  weak point in §7.
- **Full-disk encryption on BM5** and the `micro` sudo membership — recorded in
  §7, not addressed here.
- **Consolidating refold onto BM5** — BM4 currently runs refold work; migrate
  after its live job finishes.
- **BM4's Clara key was removed** from `authorized_keys` on 2026-07-27 (BM5 is
  the only machine that drives Clara now). David's laptop key is untouched and
  unrestricted, and is the way back in if BM5's entry is ever misconfigured.

---

## 11. Deliverables

1. `~/.ssh/config` fleet blocks + pinned `known_hosts` *(host keys already pinned)*
2. `tools/fleet.sh` — `probe|status|launch|poll|fetch`
3. `.claude/skills/bindmaster-orchestrator/references/lab-deploy.md` — playbook,
   sibling to `clara-deploy.md`
4. `CLAUDE.local.md` — add the fleet map and the Clara unlock procedure (§5.6).
   The existing VPN section is accurate and stays as-is; add a note that
   `/etc/openfortivpn/ciirc.conf` is owned by `<BM5_USER>`, not root, so it is
   readable by anything running as that user — it holds no secret today and must
   not be given one.

No daemon, no queue server, no UI.
