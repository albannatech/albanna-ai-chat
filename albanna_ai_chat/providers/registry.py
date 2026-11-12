"""The provider registry — a configured name becomes a working provider.

The turn loop asks for the provider by name; this module answers. Reading the
key is the part that has to be right:

**The key lives in ``site_config.json``, never in a doctype field.** A field
puts the key in every backup, every log line that renders the document, and
every fixture a developer exports — and a credential that cannot be logged is
a credential that cannot be leaked. The name is ``ai_chat_<provider>_key``,
with the provider's registry name spelled exactly as the setting says it.

**A missing key is a refusal, not a crash.** The provider is constructed with
an honest refusal naming the site config line that fixes it — the same
discipline :class:`~albanna_ai_chat.core.provider.NullProvider` applies to a
site with no provider configured at all.
"""

from __future__ import annotations

import frappe

from albanna_ai_chat.core.provider import NullProvider, Provider
from albanna_ai_chat.providers.anthropic_provider import AnthropicProvider
from albanna_ai_chat.providers.openai_provider import OpenAIProvider

#: The providers this core ships, and the class each name builds.
#: A name that is in the settings dropdown but not in this mapping is a name
#: that refuses with "no implementation is installed for it yet" — the same
#: honesty the turn loop already applies to an empty setting.
REGISTRY: dict[str, type] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def site_config_key(provider: str) -> str:
    """The site config line that carries *provider*'s API key."""
    return f"ai_chat_{provider}_key"


def read_key(provider: str) -> str:
    """The configured API key for *provider*, from ``site_config.json``."""
    try:
        config = frappe.get_site_config() or {}
    except Exception:  # noqa: BLE001 — no site, no config
        return ""
    return str(config.get(site_config_key(provider)) or "")


def read_base_url(provider: str) -> str:
    """An optional base URL override, for a proxy or a compatible endpoint."""
    try:
        config = frappe.get_site_config() or {}
    except Exception:  # noqa: BLE001
        return ""
    return str(config.get(f"ai_chat_{provider}_base_url") or "")


def provider_for(name: str, model: str = "") -> Provider:
    """The configured provider, or an honest refusal.

    Every way this can be unconfigured becomes a sentence the operator can
    act on, because a stack trace in a worker log is not a thing a reader
    sees and a turn that dies silently is a turn they will report as a bug
    rather than as a configuration problem.

    @param name: the provider's registry name, from the settings row
    @param model: the model to ask for; empty means the provider's own
        recent default is *not* guessed — an empty model refuses, because a
        guessed model is a bill the operator did not authorise
    """
    name = str(name or "").strip()
    if not name:
        return NullProvider(
            "No model provider is configured for this site. Set a default "
            "provider and model in Albanna AI Chat Settings."
        )

    cls = REGISTRY.get(name)
    if cls is None:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        return NullProvider(
            f"Provider {name!r} is configured but is not one this core "
            f"implements. Installed providers: {known}."
        )

    model = str(model or "").strip()
    if not model:
        return NullProvider(
            f"Provider {name!r} is configured without a model. Set a default "
            "model in Albanna AI Chat Settings."
        )

    key = read_key(name)
    if not key:
        return NullProvider(
            f"Provider {name!r} has no API key. Add "
            f"`{site_config_key(name)}` to this site's site_config.json."
        )

    base_url = read_base_url(name)
    kwargs = {"base_url": base_url} if base_url else {}
    return cls(key, model, **kwargs)
