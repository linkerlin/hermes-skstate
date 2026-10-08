"""SKILL.state MCP runtime.

The connected host agent is the only language model. This package does not
import Hermes and does not call an LLM API. One instrument prompt is the
host's operating procedure.
"""

from skstate.instrument import TOOL_NAMES

__all__ = ["TOOL_NAMES"]
