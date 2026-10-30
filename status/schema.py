"""Document shape and the state vocabulary."""

SCHEMA_VERSION = 1

# Arm states. `running` is decided by the PROCESS, never by output age: RFD3
# writes ten designs at once every ~70 minutes, so a healthy arm is silent for
# most of its life (measured 2026-10-30, see the design doc).
DONE = "done"
RUNNING = "running"
DEAD = "dead"
QUEUED = "queued"

# Host-level only.
UNREACHABLE = "unreachable"

ALL_STATES = (DONE, RUNNING, DEAD, QUEUED)

# Rendered marks, deliberately ASCII: this is read over ssh in logs and tmux.
STATE_MARK = {DONE: "ok", RUNNING: "..", DEAD: "XX", QUEUED: "--"}
