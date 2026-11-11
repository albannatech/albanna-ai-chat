"""Tool execution adapters — the implementations behind the port.

``core/port.py`` says how a tool is *called*.  This package says what happens
next, and it is the only part of the app that imports Frappe.

The split is the app's central decision made reversible: a second
implementation — one that spoke to a remote store over HTTP — would satisfy
the same port, and the contract, the authority layer and the model-facing
manifest would not change by a line.
"""

from albanna_ai_chat.tools.files import FILE_DOCTYPE, FILE_TOOL_NAMES, FileToolBackend

__all__ = ["FILE_DOCTYPE", "FILE_TOOL_NAMES", "FileToolBackend"]
