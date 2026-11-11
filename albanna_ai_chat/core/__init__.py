"""The frappe-mcp core contract — Frappe-free, and testable without a site.

Nothing in this package may import Frappe.  That is not a style preference,
it is what makes the contract checkable in plain Python: the validator, the
flow rules and the registry all run under ``pytest`` with no bench, no
database and no worker.

The split mirrors the one ``albanna`` documented and ``erpnext-mcp``
independently arrived at: the *contract* lives here, the *handlers* live
behind a port elsewhere, and a test asserts the two cannot drift.
"""

from albanna_ai_chat.core.file_tools import (
    CORE_TOOLS,
    EDIT_FILE,
    READ_FILE,
    WRITE_FILE,
)
from albanna_ai_chat.core.flow import (
    MECHANISMS,
    MAX_FLOW_STEPS,
    MIN_FLOW_STEPS,
    CompensationSpec,
    FlowSpec,
    FlowStep,
    validate_flow_steps_resolve,
)
from albanna_ai_chat.core.port import (
    PermissionChecker,
    Principal,
    ToolBackend,
    ToolContext,
    ToolResult,
)
from albanna_ai_chat.core.tools import (
    CORE_TOOL_NAMES,
    FORBIDDEN_PARAM_NAMES,
    MAX_RESULT_CHARS,
    READ,
    SQL_PARAM_NAMES,
    TIER_ORDER,
    WRITE,
    ToolRegistry,
    ToolSpec,
    compact_json,
    truncate_result,
    validate_arguments,
)
from albanna_ai_chat.core.validate import (
    MAX_TOOLS,
    TIERS_ATTR,
    TOOLS_ATTR,
    ContractViolation,
    absorb,
    load_module,
    validate_module,
)

__all__ = [
    # tools
    "CORE_TOOL_NAMES",
    "FORBIDDEN_PARAM_NAMES",
    "MAX_RESULT_CHARS",
    "READ",
    "SQL_PARAM_NAMES",
    "TIER_ORDER",
    "WRITE",
    "ToolRegistry",
    "ToolSpec",
    "compact_json",
    "truncate_result",
    "validate_arguments",
    # the core's own tools
    "CORE_TOOLS",
    "EDIT_FILE",
    "READ_FILE",
    "WRITE_FILE",
    # flow
    "MECHANISMS",
    "MAX_FLOW_STEPS",
    "MIN_FLOW_STEPS",
    "CompensationSpec",
    "FlowSpec",
    "FlowStep",
    "validate_flow_steps_resolve",
    # the execution port
    "PermissionChecker",
    "Principal",
    "ToolBackend",
    "ToolContext",
    "ToolResult",
    # validate
    "MAX_TOOLS",
    "TIERS_ATTR",
    "TOOLS_ATTR",
    "ContractViolation",
    "absorb",
    "load_module",
    "validate_module",
]
