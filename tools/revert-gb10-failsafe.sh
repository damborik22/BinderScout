#!/usr/bin/env bash
# revert-gb10-failsafe.sh -- undo apply-gb10-failsafe.sh. Same stage names.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "must run as root: sudo $0 $*" >&2; exit 1; }
STAGES=("${@:-sysctl guard watchdog}")
[[ "${STAGES[*]}" == "all" ]] && STAGES=(sysctl guard watchdog earlyoom)
read -ra STAGES <<<"${STAGES[*]}"
has() { [[ " ${STAGES[*]} " == *" $1 "* ]]; }

if has sysctl; then
  rm -f /etc/sysctl.d/99-gb10-unified-memory.conf
  sysctl --system >/dev/null
  echo "sysctl reverted: min_free_kbytes=$(sysctl -n vm.min_free_kbytes) sysrq=$(sysctl -n kernel.sysrq)"
fi
if has guard; then
  systemctl disable --now gb10-guard.service 2>/dev/null || true
  rm -f /etc/systemd/system/gb10-guard.service /usr/local/bin/gb10-guard.py
  systemctl daemon-reload; echo "guard removed"
fi
if has watchdog; then
  rm -f /etc/systemd/system.conf.d/10-gb10-watchdog.conf
  systemctl daemon-reexec
  echo "watchdog released: RuntimeWatchdogUSec=$(systemctl show -p RuntimeWatchdogUSec --value)"
fi
if has earlyoom; then
  systemctl disable --now earlyoom 2>/dev/null || true
  rm -rf /etc/systemd/system/earlyoom.service.d
  systemctl daemon-reload; echo "earlyoom disabled (package left installed)"
fi
