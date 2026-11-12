"""The shared HTTP transport — one call, and every way it can fail.

The transport is the whole of what a provider implementation adds beyond its
wire translation, and it is deliberately thin. What it is careful about:

**Errors are responses, not exceptions.** A 401 is "the key was refused" — a
sentence the reader can be shown and the operator can fix. An exception in the
worker is a stack trace in a log and a turn that dies with no explanation. So
every failure mode is mapped into a :class:`ProviderResponse` with an ``error``
and a ``reason``, and nothing raises.

**The refusal and the outage are different.** A 401/403 means the
configuration is wrong and no retry will help (``REFUSED``). A timeout or a
5xx means the provider is unreachable and the turn may be retried (``ERROR``).
Collapsing them teaches the operator to restart a service for a bad key.

**The provider's own message is kept.** ``{"error": {"message": …}}`` is the
shape both Anthropic and OpenAI return, and it is the one sentence that says
what actually went wrong — "billing is disabled for this project" is not a
sentence this module could invent.
"""

from __future__ import annotations

import json

import requests

from albanna_ai_chat.core.provider import ERROR, REFUSED, ProviderResponse

#: How long to wait for a model, in seconds. A model call is a background
#: job, so this bounds a worker slot, not a reader's patience — and a job
#: that hangs holds a slot the queue cannot reuse.
HTTP_TIMEOUT = 90.0


def error_message(payload, fallback: str) -> str:
    """The provider's own sentence, from ``{"error": {"message": …}}``.

    Both major providers use this shape, and it is the sentence that says
    what actually went wrong. Anything the payload does not carry falls back
    to the caller's generic sentence rather than to ``str(payload)`` — a
    404 page rendered into a chat bubble is a bug a reader will report.
    """
    body = payload if isinstance(payload, dict) else {}
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str) and error:
        return error
    return fallback


def post(
    url: str,
    headers: dict[str, str],
    payload: dict,
    *,
    timeout: float = HTTP_TIMEOUT,
    transport=requests.post,
) -> tuple[ProviderResponse, dict | None]:
    """One HTTP call to a model provider, and the mapping of every outcome.

    @param url: the endpoint
    @param headers: authentication and content-type headers
    @param payload: the request body, already in the provider's shape
    @param timeout: seconds to wait; a model call bounds a worker slot
    @param transport: the callable that performs the call — the seam the
        tests inject a fake through, so no test ever touches the network
    @returns: ``(response, body)`` — ``body`` is the parsed JSON on a 2xx and
        ``None`` on any failure, so the caller translates its own success
        shape and never touches the network doing it
    """
    body = json.dumps(payload, default=str)
    try:
        response = transport(
            url,
            headers={**headers, "Content-Type": "application/json"},
            data=body,
            timeout=timeout,
        )
    except requests.Timeout:
        return ProviderResponse(
            error="The provider did not answer in time. The turn may be retried.",
            reason=ERROR,
        ), None
    except requests.RequestException as e:
        # A connection error, a DNS failure, a refused socket — the provider
        # is unreachable, which is an outage and may be retried.
        return ProviderResponse(
            error=f"The provider could not be reached ({e.__class__.__name__}).",
            reason=ERROR,
        ), None

    try:
        payload_out = response.json()
    except (ValueError, TypeError):
        payload_out = None

    if 200 <= response.status_code < 300:
        if payload_out is None:
            return ProviderResponse(
                error="The provider answered with a body that is not JSON.",
                reason=ERROR,
            ), None
        return ProviderResponse(), payload_out  # the caller parses its own shape

    refused = response.status_code in (401, 403, 402)
    message = error_message(
        payload_out,
        f"The provider answered HTTP {response.status_code}.",
    )
    if refused:
        # Configuration, not weather: no retry helps a bad key, and saying
        # so is what stops an operator from restarting a service for one.
        return ProviderResponse(
            error=f"The provider refused the request: {message}",
            reason=REFUSED,
        ), None
    if response.status_code == 429:
        return ProviderResponse(
            error=f"The provider is rate-limiting this site: {message}",
            reason=REFUSED,
        ), None
    return ProviderResponse(error=message, reason=ERROR), None
