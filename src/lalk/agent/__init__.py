"""Bumblehive agent integration."""

from .bumblehive import AgentTurn, BumblehiveAgent
from .instructions import (
    DEFAULT_ROLE_INSTRUCTIONS,
    VOICE_AGENT_INSTRUCTIONS,
    compose_voice_agent_instructions,
)

__all__ = [
    "AgentTurn",
    "BumblehiveAgent",
    "DEFAULT_ROLE_INSTRUCTIONS",
    "VOICE_AGENT_INSTRUCTIONS",
    "compose_voice_agent_instructions",
]
