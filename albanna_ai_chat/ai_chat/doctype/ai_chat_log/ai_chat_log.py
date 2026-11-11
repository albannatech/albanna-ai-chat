"""AI Chat Log — the audit trail.

A log row records *that* something happened, never *what was said*.  The
content of a conversation is the reader's, and it lives in ``AI Chat Message``
behind the permission hooks; this table is the app's bookkeeping and is
readable by a System Manager for support.

The event vocabulary is closed, so the log can be counted rather than only
read — "how many writes were refused last month" is a question this table can
answer, and it cannot answer it if events are free text.
"""

from __future__ import annotations

from frappe.model.document import Document


class AIChatLog(Document):
    """One event in the audit trail."""
