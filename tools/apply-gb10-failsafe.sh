#!/usr/bin/env bash
# apply-gb10-failsafe.sh -- install the GB10 unified-memory failsafe.
#
# Run with:  sudo ./apply-gb10-failsafe.sh [stage...]
# Stages (default: sysctl guard watchdog):
#   sysctl    VM reclaim floor + SysRq process-signalling      [instant, reversible, no restart]
#   guard     gb10-guard.service -- kills the GPU job          [starts a daemon]
#   watchdog  hand /dev/watchdog0 to PID 1 for auto-reboot     [changes reboot behaviour]
#   earlyoom  dumb backstop for host-side anon blowups         [installs a package]
#   all       everything above
#
# Every stage is independently revertible; see ./revert-gb10-failsafe.sh.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root: sudo $0 $*" >&2; exit 1; }

# Derived from this script's own location; it lives in <repo>/tools.
TOOLS="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO="$(cd "$TOOLS/.." && pwd)"
STAGES=("${@:-sysctl guard watchdog}")
[[ "${STAGES[*]}" == "all" ]] && STAGES=(sysctl guard watchdog earlyoom)
read -ra STAGES <<<"${STAGES[*]}"

has() { [[ " ${STAGES[*]} " == *" $1 "* ]]; }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

if has sysctl; then
  say "sysctl: reclaim floor + SysRq"
  install -m 0644 "$TOOLS/sysctl/99-gb10-unified-memory.conf" /etc/sysctl.d/
  sysctl --system >/dev/null
  echo "  vm.min_free_kbytes       = $(sysctl -n vm.min_free_kbytes)  (was 45167)"
  echo "  vm.watermark_scale_factor= $(sysctl -n vm.watermark_scale_factor)  (was 10)"
  echo "  kernel.sysrq             = $(sysctl -n kernel.sysrq)  (was 176; 240 enables Alt+SysRq+F)"
  # 20-nvidia-defaults.conf sorts BEFORE 99-, so we win. Verify rather than assume:
  for k in vm.min_free_kbytes vm.watermark_scale_factor; do
    want=$(grep -oP "(?<=^$k = ).*" "$TOOLS/sysctl/99-gb10-unified-memory.conf")
    got=$(sysctl -n "$k")
    [[ "$want" == "$got" ]] || echo "  WARNING: $k is $got, expected $want -- another sysctl.d file is overriding"
  done
fi

if has guard; then
  say "guard: gb10-guard.service"
  install -m 0755 "$TOOLS/gb10-guard.py" /usr/local/bin/gb10-guard.py
  # The unit ships with an @REPO@ placeholder: point ExecStart at the installed
  # copy under /usr/local/bin, and resolve every other @REPO@ to this checkout.
  sed -e 's#@REPO@/tools/gb10-guard.py#/usr/local/bin/gb10-guard.py#' \
      -e "s#@REPO@#$REPO#g" \
      "$TOOLS/systemd/gb10-guard.service" > /etc/systemd/system/gb10-guard.service
  systemd-analyze verify /etc/systemd/system/gb10-guard.service 2>&1 | grep -v '^$' && \
      echo "  (review any 'Unknown key name' lines above -- they mean a setting is being ignored)"
  systemctl daemon-reload
  systemctl enable gb10-guard.service
  systemctl restart gb10-guard.service   # restart, not --now: --now is a no-op if already running
  install -d -m 0755 /run/gb10-guard && install -d -m 1777 /run/gb10-guard/jobs
  sleep 2
  systemctl is-active gb10-guard.service | sed 's/^/  state: /'
  journalctl -u gb10-guard.service -n 4 --no-pager -o cat | sed 's/^/  /'
fi

if has watchdog; then
  say "watchdog: hand /dev/watchdog0 to PID 1"
  # Today nothing owns it, so the kernel's watchdog-core workqueue pets it forever -- which is
  # exactly why the box could sit wedged indefinitely. Transferring ownership to PID 1 changes
  # the reset predicate from "the kernel is dead" to "PID 1's event loop has not run for N
  # seconds", which is the failure that was actually observed.
  #
  # 180s, not 60s: the guard must have time to kill the job first. A watchdog reset is an
  # UNCLEAN reboot -- it is the fallback, not the plan. This box also mounts a CIFS share, and
  # a stalled mount blocking PID 1 briefly must not trigger a reset.
  mkdir -p /etc/systemd/system.conf.d
  cat > /etc/systemd/system.conf.d/10-gb10-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=180
RebootWatchdogSec=10min
EOF
  systemctl daemon-reexec
  echo "  RuntimeWatchdogUSec = $(systemctl show -p RuntimeWatchdogUSec --value)"
  echo "  watchdog0 state     = $(cat /sys/class/watchdog/watchdog0/state 2>/dev/null)"
  echo "  watchdog0 timeout   = $(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null)s"
  echo "  NOTE: sbsa_gwdt is two-stage with action=1 -- WS0 panics (captured by efi_pstore,"
  echo "        archived by systemd-pstore on next boot), WS1 hard-resets one period later."
fi

if has earlyoom; then
  say "earlyoom: host-side backstop"
  # Deliberately a BACKSTOP, not the primary. earlyoom ranks victims by oom_score/RSS, which
  # undercounts a GB10 GPU hog by exactly the bytes that matter -- it cannot see driver pages.
  # It is here only for the host-side anon shape (the 2026-06-05 event: 22.6 GiB anon-rss).
  DEBIAN_FRONTEND=noninteractive apt-get install -y earlyoom
  cat > /etc/default/earlyoom <<'EOF'
# -M/-S take KiB (absolute). -m/-s take PERCENT -- a classic mix-up on a 121 GiB box.
# SIGTERM at 12 GiB free, SIGKILL at 8 GiB: both ABOVE the ~6.8 GiB high watermark that
# min_free_kbytes=2G + watermark_scale_factor=200 produces, and BELOW gb10-guard's 40 GiB
# trip, so the guard always acts first and earlyoom only catches what it missed.
# -s 100,100 disables the swap AND-condition; without it earlyoom will not fire while swap
# is free, which at the real freeze it was.
EARLYOOM_ARGS="-M 12582912,8388608 -s 100,100 -r 60 -n --avoid '^(systemd|sshd|Xorg|gnome-shell|mutter-x11-fram|rustdesk|gb10-guard|dbus-daemon|systemd-journal|nvidia-persiste)$' --prefer '^(python3\.1[0-9]|boltz|pt_data_worker|binder-compare)$'"
EOF
  # -p would RAISE oom_score_adj from the unit's -1000 to -100, undoing the protection.
  mkdir -p /etc/systemd/system/earlyoom.service.d
  printf '[Service]\nOOMScoreAdjust=-1000\n' > /etc/systemd/system/earlyoom.service.d/10-protect.conf
  systemctl daemon-reload && systemctl enable --now earlyoom
  echo "  earlyoom oom_score_adj = $(cat /proc/"$(pgrep -x earlyoom | head -1)"/oom_score_adj 2>/dev/null)"
fi

say "done"
cat <<'EOF'
State after this run — check against `systemctl status`:
  gb10-guard.service   kills the GPU job instead of letting the kernel dismantle the box
  bindmaster-mps       driver-enforced per-client GPU ceiling (enable separately, --user unit)
  /dev/watchdog0       owned by PID 1 — a true wedge auto-reboots
  /run/gb10-guard/jobs 1777, where gpurun registers each job's declared budget

Remaining by hand:

 1. Route ad-hoc GPU work through gpurun. The bin/ wrappers (bindcraft, bindcraft2, boltzgen,
    mosaic, pxdesign, protein-hunter) already apply their budget automatically, but
    anything you launch directly does not:
        tools/gpurun --cap 24 -- boltz predict ...
    A job launched outside gpurun is UNREGISTERED: the guard cannot tell whether it is
    misbehaving, and ranks it above a registered job of the same size.

 2. Validate victim selection WITHOUT killing anything. Do not try to trigger the guard for
    real — v2 only fires when reclaim is genuinely failing, so provoking it means driving the
    box to the edge. Run a second instance in dry-run with relaxed thresholds instead; it
    prints the victim it WOULD pick and exits:
        GB10_DRY_RUN=1 GB10_FLOOR_MIB=999999 GB10_AVAIL_FLOOR_MIB=999999 \
        GB10_PSI_FULL_AVG10=0 GB10_SUSTAIN_POLLS=3 GB10_DEADBAND_MIB=1 \
        GB10_STATE_DIR=/tmp/gb10-dryrun GB10_LOG=/tmp/gb10-dryrun.log \
        timeout -s INT 8 python3 -u /usr/local/bin/gb10-guard.py
    Do this while a real job is running to confirm it picks the job and not a bystander.

 3. If a job dies unexpectedly, read /run/gb10-guard/last-kill before anything else. SIGKILL is
    indistinguishable from a crash from inside the job; that file names the guard, the reason,
    and the memory state at the trip. Full log: /var/log/gb10-guard.log (world-readable).

NOTE: MPS deliberately uses its own pipe directory (/tmp/bindmaster-mps/pipe) rather than
NVIDIA's default. That is isolation, not a bug: on the default pipe every CUDA client
auto-joins, including rustdesk, and MPS clients die with the server. Only gpurun and the bin/
wrappers join it.
EOF
