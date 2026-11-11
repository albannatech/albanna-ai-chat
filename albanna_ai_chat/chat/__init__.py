"""The chat runtime's pure half — Frappe-free and testable without a site.

``message``  what a conversation is made of, and how it serialises to a
             provider's wire format
``turn``     the turn state machine: what a turn is, what may happen to it,
             and what the runtime should do next

Nothing here imports Frappe, a provider SDK, or a socket.  The Frappe-coupled
runtime — doctypes, the worker, the API — is a thin layer over this, and the
tests in ``tests/`` exercise this half directly.
"""

from albanna_ai_chat.chat.message import (
    Message,
    Role,
    ToolCall,
    estimate_tokens,
    to_wire,
)
from albanna_ai_chat.chat.turn import (
    MAX_PROVIDER_CALLS,
    MAX_TOOL_CALLS_PER_RESPONSE,
    Action,
    IllegalTransition,
    Turn,
    TurnEvent,
    TurnState,
    can_transition,
    next_state,
)

__all__ = [
    # message
    "Message",
    "Role",
    "ToolCall",
    "estimate_tokens",
    "to_wire",
    # turn
    "MAX_PROVIDER_CALLS",
    "MAX_TOOL_CALLS_PER_RESPONSE",
    "Action",
    "IllegalTransition",
    "Turn",
    "TurnEvent",
    "TurnState",
    "can_transition",
    "next_state",
]
