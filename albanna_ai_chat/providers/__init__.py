"""The providers — how a model is actually asked.

The port lives in :mod:`albanna_ai_chat.core.provider`; this package holds the
implementations, one per provider API, each in two halves:

* a **pure** half — the request translation (canonical ``Message`` objects into
  the provider's wire shape) and the response translation (the provider's
  payload back into a :class:`~albanna_ai_chat.core.provider.ProviderResponse`).
  It imports no Frappe, touches no network, and is tested under plain pytest.

* a **transport** half — one HTTP call and the mapping of every way it can fail
  into a response the turn loop can show the reader.

Why HTTP and not an SDK
-----------------------
``anthropic`` and ``openai`` are in :data:`~albanna_ai_chat.core.jobs.PROVIDER_MODULES`
for *extensions* — the core owns the provider layer, and the core's own choice
is plain HTTP over ``requests``, which Frappe already ships. An SDK is a
second dependency tree that pins its own ``httpx`` and must be kept current
with the provider's release cadence; the wire formats are stable and small,
and writing them down is what makes them auditable.

Where the key lives
-------------------
In ``site_config.json``, under ``ai_chat_<provider>_key`` — never in a
doctype field, which would put it in every backup, every log line that
renders the document, and every fixture a developer exports.
"""
