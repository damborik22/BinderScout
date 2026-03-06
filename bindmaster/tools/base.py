"""
Base class for all BindMaster tool adapters.
All tools (existing and new) should eventually conform to this interface.
New tools MUST implement this interface.
Existing tools are NOT required to be retrofitted.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ToolResult:
    """
    Standardized result container returned by every tool adapter.
    Existing tools return their own formats — this is for new tools only.
    """

    success: bool
    tool_name: str
    design_id: str
    output_dir: Path
    pdb_paths: list[Path]
    log_path: Path
    error_message: Optional[str] = None
    raw_scores: Optional[dict] = None  # Tool-specific scores, unmodified
    metadata: Optional[dict] = None  # Any additional tool-specific info


class ToolAdapter(ABC):
    """
    Abstract base for new tool adapters.
    Existing tools (BindCraft, BoltzGen, Mosaic) are NOT required to subclass this.
    """

    tool_name: str = "base"

    @abstractmethod
    def validate_environment(self) -> bool: ...

    @abstractmethod
    def validate_weights(self) -> bool: ...

    @abstractmethod
    def run(self, **kwargs) -> ToolResult: ...

    def preflight(self) -> bool:
        env_ok = self.validate_environment()
        weights_ok = self.validate_weights()
        if not env_ok:
            print(f"[{self.tool_name}] Environment check failed")
        if not weights_ok:
            print(f"[{self.tool_name}] Weights check failed")
        if env_ok and weights_ok:
            print(f"[{self.tool_name}] Preflight OK")
        return env_ok and weights_ok
