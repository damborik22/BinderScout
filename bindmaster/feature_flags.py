"""
BindMaster Feature Flags
========================
Controls which experimental features are enabled.
All new integrations default to DISABLED.
Set via environment variables or config file.

Usage:
    export BINDMASTER_ENABLE_RFAA=true
    export BINDMASTER_ENABLE_PXDESIGN=true

Or in Python:
    from bindmaster.feature_flags import flags
    if flags.rfaa_enabled:
        ...
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFlags:
    """Immutable feature flag set. Read once at import time."""

    # New tool integrations — default OFF
    rfaa_enabled: bool = False
    pxdesign_enabled: bool = False

    # Unified scoring — default OFF (uses per-tool scoring when False)
    unified_scoring_enabled: bool = False

    # Parallel campaigns — default OFF
    parallel_campaigns_enabled: bool = False

    # Debug mode — extra logging and validation
    debug_mode: bool = False

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """Read flags from environment variables."""

        def _bool(key: str, default: bool = False) -> bool:
            val = os.environ.get(key, str(default)).lower()
            return val in ("1", "true", "yes", "on")

        return cls(
            rfaa_enabled=_bool("BINDMASTER_ENABLE_RFAA"),
            pxdesign_enabled=_bool("BINDMASTER_ENABLE_PXDESIGN"),
            unified_scoring_enabled=_bool("BINDMASTER_ENABLE_UNIFIED_SCORING"),
            parallel_campaigns_enabled=_bool("BINDMASTER_ENABLE_PARALLEL_CAMPAIGNS"),
            debug_mode=_bool("BINDMASTER_DEBUG"),
        )


# Singleton — import this object everywhere
flags = FeatureFlags.from_env()
