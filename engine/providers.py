"""Provider presets for OpenAI-compatible LLM endpoints.

Each preset carries ``name``, ``base_url``, ``model`` and ``api_key_env``.
Base URLs are the documented public OpenAI-compatible endpoints; models are
plausible documented defaults and are always editable in the config. The
``custom`` preset ships empty ``base_url``/``model`` so the user must supply
their own endpoint.

Keys themselves live in the private keys file (see ``engine.keys``) and are
never exposed here: ``provider_list`` reports only a boolean and a masked
hint.
"""

from __future__ import annotations

from pathlib import Path

from engine.keys import mask, resolved_key

#: Public OpenAI-compatible provider presets.
PRESETS: dict[str, dict] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "base_url": "",
        "model": "",
        "api_key_env": "CUSTOM_API_KEY",
    },
}


def is_valid_provider(provider: str | None) -> bool:
    """Return True when ``provider`` is a known preset id."""
    return isinstance(provider, str) and provider in PRESETS


def provider_llm_config(provider: str, config: dict) -> dict:
    """Return the effective LLM config for ``provider``.

    Starts from the preset. ``api_key_env`` is overlaid from the config only
    for the active provider (``config["llm"]["provider"]``); any other
    provider keeps its preset's own env var so the global legacy variable
    cannot stand in for a different provider's key. ``timeout_s`` is always
    overlaid from the config. ``base_url`` and ``model`` are overlaid from
    the config only for the active provider, so selecting a different one
    uses that preset's endpoint/model while user edits to the active one are
    honored. Returns a fresh dict.
    """
    if not is_valid_provider(provider):
        raise ValueError(f"unknown provider: {provider!r}")
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    merged = dict(PRESETS[provider])
    merged["provider"] = provider
    if provider == llm.get("provider"):
        merged["api_key_env"] = llm.get("api_key_env", merged["api_key_env"])
        if "base_url" in llm:
            merged["base_url"] = llm["base_url"]
        if "model" in llm:
            merged["model"] = llm["model"]
    merged["timeout_s"] = llm.get("timeout_s", 60)
    return merged


def provider_list(config: dict, keys_path: Path | None = None) -> list[dict]:
    """Return one row per preset describing selection and key state.

    Rows carry ``id``, ``name``, ``base_url``, ``model``, ``active``,
    ``fallback``, ``key_set`` and ``key_hint``. Key state comes from that
    provider's stored key or its own env var — the global legacy variable
    never marks an unrelated provider as keyed. Key material never appears —
    only a boolean and the masked hint from ``engine.keys.mask``.
    """
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    active = llm.get("provider")
    fallback = llm.get("fallback_provider")
    rows: list[dict] = []
    for pid, preset in PRESETS.items():
        effective = provider_llm_config(pid, config)
        key = resolved_key(pid, config, effective, keys_path)
        rows.append(
            {
                "id": pid,
                "name": preset["name"],
                "base_url": effective["base_url"],
                "model": effective["model"],
                "active": pid == active,
                "fallback": fallback is not None and pid == fallback,
                "key_set": bool(key),
                "key_hint": mask(key) if key else "",
            }
        )
    return rows
