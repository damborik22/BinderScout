"""`binderscout status` -- campaign state across the fleet.

Probes on demand and caches nothing: the filesystem is the source of truth, so a
live read is as fresh as data can be, and a cache would only add staleness.
"""

import argparse
import json
import sys
import time

from status.collect import collect_local
from status.remote import DEFAULT_TIMEOUT_S, fleet_hosts, merge_host_results, probe_hosts
from status.render_term import render

USAGE = """\
binderscout status [options]

  --hosts a,b      probe these ssh aliases (default: $BINDERSCOUT_FLEET)
  --local          this box only, no ssh
  --json           emit the raw document (what the pushed page consumes)
  --watch [SECS]   redraw every SECS seconds (default 60)
  --timeout SECS   per-host ssh timeout (default 25)
"""


def build_document(hosts, timeout_s: int) -> dict:
    """Probe the remote boxes AND this one.

    This box is always included: it is a campaign box like any other, and
    leaving it out once hid a finished arm and re-rendered it as `queued` from
    another box's empty run directory. Do not list this box in the fleet
    variable, or it is probed twice under two labels.
    """
    results = probe_hosts(hosts, timeout_s) if hosts else {}
    results.setdefault("local", collect_local(host="local"))
    return merge_host_results(results)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="binderscout status", usage=USAGE, add_help=True)
    parser.add_argument("--hosts", default=None)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--watch", nargs="?", type=int, const=60, default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    if args.local:
        hosts = []
    elif args.hosts:
        hosts = [h for h in args.hosts.replace(",", " ").split() if h]
    else:
        hosts = fleet_hosts()

    while True:
        doc = build_document(hosts, args.timeout)
        if args.json:
            print(json.dumps(doc, indent=2))
        else:
            if args.watch:
                sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render(doc, color=sys.stdout.isatty()))
        if not args.watch:
            return 0
        sys.stdout.flush()
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())
