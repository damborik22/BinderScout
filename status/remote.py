"""SSH fan-out. Ships the probe source over stdin; requires nothing on the far box.

Sending the source means there is no version skew between what this renderer
expects and what a remote box reports -- and it works on a box with no checkout
at all. It is why the probe modules are stdlib-only.

The host list comes from the environment, never from a tracked file: this repo
is public and must carry no hostname, username or home path.
"""

import base64
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from status.schema import SCHEMA_VERSION

# Order matters only for readability; these are the modules collect_local needs.
_SHIPPED = ("__init__.py", "schema.py", "probes.py", "liveness.py", "collect.py")

DEFAULT_TIMEOUT_S = 25


def fleet_hosts() -> list:
    """Aliases to probe, from $BINDERSCOUT_FLEET only. Empty means local-only, the safe default."""
    raw = os.environ.get("BINDERSCOUT_FLEET") or ""
    return [h for h in raw.replace(",", " ").split() if h]


def _driver_source() -> str:
    here = Path(__file__).parent
    payload = {name: (here / name).read_text() for name in _SHIPPED}
    blob = base64.b64encode(json.dumps(payload).encode()).decode()
    return (
        "import base64, json, sys, tempfile, pathlib\n"
        f'_f = json.loads(base64.b64decode("{blob}").decode())\n'
        '_d = pathlib.Path(tempfile.mkdtemp()) / "status"\n'
        "_d.mkdir(parents=True)\n"
        "for _n, _s in _f.items(): (_d / _n).write_text(_s)\n"
        "sys.path.insert(0, str(_d.parent))\n"
        "from status.collect import collect_local\n"
        "print(json.dumps(collect_local()))\n"
    )


# ssh quotes the address and the account in almost every failure, and this
# document is published to a page in phase 2. Reduce to the category at capture
# time -- the only point that can guarantee the raw string is never stored.
_ERROR_CATEGORIES = (
    ("connection reset", "connection reset by host"),
    ("connection refused", "connection refused"),
    ("permission denied", "permission denied (key not authorised)"),
    ("no route to host", "no route to host"),
    ("name or service not known", "host does not resolve"),
    ("could not resolve", "host does not resolve"),
    ("operation timed out", "ssh timeout"),
    ("timeout", "ssh timeout"),
    ("host key verification", "host key verification failed"),
    ("broken pipe", "connection broken"),
)


def sanitise_ssh_error(raw: str) -> str:
    """The failure category, with no address, account or hostname in it."""
    low = (raw or "").lower()
    for needle, label in _ERROR_CATEGORIES:
        if needle in low:
            return label
    return "unreachable (ssh failed)"


def probe_host(host: str, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Run the probe on one box. An unreachable box is DATA, not an exception."""
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
            input=_driver_source(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"reachable": False, "error": f"ssh timeout ({timeout_s}s)"}
    except OSError as exc:
        return {"reachable": False, "error": sanitise_ssh_error(str(exc))}

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        reason = sanitise_ssh_error(detail[-1]) if detail else f"ssh exit {proc.returncode}"
        return {"reachable": False, "error": reason}
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"reachable": False, "error": "probe returned unparseable output"}


def probe_hosts(hosts, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Probe every box concurrently. One slow box does not serialise the rest."""
    if not hosts:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, len(hosts))) as pool:
        futures = {h: pool.submit(probe_host, h, timeout_s) for h in hosts}
        return {h: f.result() for h, f in futures.items()}


def merge_host_results(results: dict) -> dict:
    """Wrap per-host results in the versioned document the renderers read."""
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hosts": dict(results),
    }
