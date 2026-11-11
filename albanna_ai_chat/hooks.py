"""Frappe app hooks — the one file Frappe reads to wire this app in.

Everything the framework calls on this app's behalf is registered here: the
assets that load on every Desk page, the installer, the scheduler, and the
document events that keep a conversation's derived fields honest.

The load-bearing part is the permission story, and it is the same shape
``albanna`` uses — because the same reasoning applies.  A conversation is
private to the user who started it, and the two permission hooks at the bottom
are what make that mean *the owner*: a reader who is not the owner sees
nothing of it.  A System Manager is not exempt, because running the site and
reading somebody's chat are different acts.

Widening the doctype without narrowing these hooks widens it for everyone, so
both are edited together or not at all.
"""

app_name = "albanna_ai_chat"
app_title = "Albanna AI Chat"
app_publisher = "Albanna Software Solutions"
app_description = "The frappe-mcp core: chat runtime, file tools, and the extension seam."
app_email = "ahmedalbanna966@gmail.com"
app_license = "mit"

# --------------------------------------------------------------------------
# The extension seam.
#
# This is the hook every other `-mcp` repo implements.  An app that wants to
# contribute tools declares ``frappe_mcp_tools`` in its own hooks.py and
# returns a list of ``ToolSpec`` — the core validates them, tags their
# provenance, and absorbs them into the registry.
#
# It is a Frappe hook rather than a Python entry point on purpose.  An entry
# point lives in the bench *venv*, which every site on the bench shares, so an
# extension installed there would appear on sites that do not have its app —
# tools referencing doctypes that do not exist.  A Frappe hook is site-scoped:
# install the app and its tools exist; uninstall it and they are gone.
# --------------------------------------------------------------------------

#: Apps may extend this list; the core reads it through ``get_hooks``.
frappe_mcp_tools = []

# --------------------------------------------------------------------------
# Desk assets.
#
# Every entry carries ``.bundle.`` on purpose.  Frappe's ``include_style``
# resolves a hashed, content-addressed URL only for entries that contain
# ``.bundle.`` and do not start with ``/assets``.  A raw path is served from a
# URL that never changes under a one-year ``max-age``, which silently pins
# every returning user to the stylesheet they loaded first — and an entry
# without it is passed through untouched and requested from the site root,
# where it does not exist.  The request 404s, the browser logs it, and nothing
# on the page says so: the feature is simply absent, on every page, for every
# user, forever.
# --------------------------------------------------------------------------

app_include_js = ["albanna-ai-chat.bundle.js"]
app_include_css = ["albanna-ai-chat.bundle.css"]

# --------------------------------------------------------------------------
# Permissions — the load-bearing part.
#
# Chat history is private to the user who started it.  The doctype grants the
# ``Albanna Chat User`` role read/write, every row ``if_owner``, and these two
# hooks are what make that mean "the owner".
# --------------------------------------------------------------------------

permission_query_conditions = {
    "AI Chat Conversation": "albanna_ai_chat.permissions.get_conversation_query_conditions",
    "AI Chat Message": "albanna_ai_chat.permissions.get_message_query_conditions",
}

has_permission = {
    "AI Chat Conversation": "albanna_ai_chat.permissions.has_conversation_permission",
    "AI Chat Message": "albanna_ai_chat.permissions.has_message_permission",
}

# --------------------------------------------------------------------------
# Installation.
#
# The installer creates the Single settings row so the app is usable the
# moment it is installed, instead of failing on a missing document the first
# time somebody opens the widget.
# --------------------------------------------------------------------------

after_install = "albanna_ai_chat.install.after_install"
after_migrate = "albanna_ai_chat.install.after_migrate"

# --------------------------------------------------------------------------
# Document events.
#
# A conversation's ``last_activity`` and message count are derived, and a
# derived field that is computed in two places is a derived field that
# disagrees with itself.  Both are maintained here, on the event that makes
# them change, and nowhere else.
# --------------------------------------------------------------------------

doc_events = {
    "AI Chat Message": {
        "after_insert": "albanna_ai_chat.services.conversation_service.on_message_inserted",
    },
}

# --------------------------------------------------------------------------
# Scheduler.
#
# Chat logs are an audit trail, not a business record.  They are pruned by age
# so the table does not grow without bound; conversations are kept until the
# user deletes them.
# --------------------------------------------------------------------------

scheduler_events = {
    "daily": ["albanna_ai_chat.services.retention.prune_chat_logs"],
}
