"""`binderscout status` -- campaign state across the fleet.

Probes on demand and caches nothing: the filesystem is the source of truth, so a
live read is as fresh as data can be, and a cache would only add staleness.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from status.collect import collect_local
from status.remote import DEFAULT_TIMEOUT_S, fleet_hosts, merge_host_results, probe_hosts
from status.render_term import render

# The checkout this CLI is running from: the local arm probes it directly. Derived here
# and not in collect.py, whose source is also shipped to remote boxes and run from a temp dir.
REPO = Path(__file__).resolve().parent.parent

USAGE = """\
binderscout status [options]

  --hosts a,b      probe these ssh aliases (default: $BINDERSCOUT_FLEET)
  --local          this box only, no ssh
  --json           emit the raw document (what the pushed page consumes)
  --html FILE      write a self-contained page to FILE (serve it; no account)
  --watch [SECS]   redraw every SECS seconds (default 60)
  --timeout SECS   per-host ssh timeout (default 25)
"""


# Only these two keys are taken from the file; anything else in it is ignored,
# so the document's shape cannot be widened by editing a local file.
_CAMPAIGN_MAP_KEYS = ("campaigns", "deadlines")


def load_campaign_map() -> dict:
    """Campaign labels and deadlines from $BINDERSCOUT_CAMPAIGNS, if it is set.

    These are operator facts -- which run directories are one campaign, and when
    it is due -- that no probe can discover, and they name real projects, so they
    stay in a machine-local file rather than anything tracked in this repo.
    A missing or malformed file is not an error: the view degrades to one block
    per run directory, which is what it did before.
    """
    raw = os.environ.get("BINDERSCOUT_CAMPAIGNS")
    if not raw:
        return {}
    try:
        loaded = json.loads(Path(raw).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: loaded[k] for k in _CAMPAIGN_MAP_KEYS if isinstance(loaded.get(k), dict)}


def build_document(hosts, timeout_s: int, repo_root=None) -> dict:
    """Probe the remote boxes AND this one.

    This box is always included: it is a campaign box like any other, and
    leaving it out once hid a finished arm and re-rendered it as `queued` from
    another box's empty run directory. Do not list this box in the fleet
    variable, or it is probed twice under two labels.
    """
    results = probe_hosts(hosts, timeout_s) if hosts else {}
    results.setdefault("local", collect_local(repo_root=repo_root, host="local"))
    return {**merge_host_results(results), **load_campaign_map()}


def write_html(path: Path, doc: dict) -> None:
    """Render `doc` to `path`, atomically.

    A browser polls this file on a timer, so it can read it at any instant --
    including the instant the renderer is half-way through writing it. Writing
    beside it and renaming means a reader sees either the old page or the new
    one, never a truncated one.
    """
    from status.render_html import render as render_html

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render_html(doc))
    tmp.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="binderscout status", usage=USAGE, add_help=True)
    parser.add_argument("--hosts", default=None)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--html", default=None)
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
        doc = build_document(hosts, args.timeout, repo_root=REPO)
        if args.html:
            write_html(Path(args.html), doc)
        if args.json:
            print(json.dumps(doc, indent=2))
        # With --html the page IS the output. A terminal dump on top of it would
        # only fill the timer's journal with a rendering nobody reads.
        elif not args.html:
            if args.watch:
                sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render(doc, color=sys.stdout.isatty()))
        if not args.watch:
            return 0
        sys.stdout.flush()
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())
