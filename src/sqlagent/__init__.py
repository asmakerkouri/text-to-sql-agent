"""Text-to-SQL agent with guardrails and schema-aware self-correction."""

from .agent import AgentResult, SQLAgent
from .schema import Schema

__all__ = ["SQLAgent", "AgentResult", "Schema"]
__version__ = "1.0.0"
