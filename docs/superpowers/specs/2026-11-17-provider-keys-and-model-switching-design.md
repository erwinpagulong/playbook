# Provider Keys and Model Switching — Design

**Date:** 2026-11-17
**Status:** Draft for approval
**Relates to:** `docs/superpowers/specs/2026-11-16-crypto-playbook-plugin-design.md`

## Intent and why

The shipped plugin reads its LLM key from an environment variable that must be exported into
Quickshell's launch environment, then requires a re-login to change. The user wants to store keys
for several providers inside the app, paste/change them from a sidebar screen, switch the active
model with one click, and have a second configured model take over automatically when the primary
runs out of usage. The user monitors remaining quota on each provider's own dashboard; the plugin
does **not** need to check quota itself.

## Goals

- An **API keys** sidebar screen (under Providers), styled after the Hermes reference: provider
  rows with masked key hints (`sk-…4e18`), a paste field per provider, an active indicator, and a
  custom-endpoint row.
- A **Model** sidebar screen with an active-model dropdown and a fallback-model dropdown (`None`
  by default). Selecting a provider/model fills its base URL and default model; both remain
  editable in Settings.
- Keys stored in one private file with mode `600`, never in `config.json`, reports, logs,
  `/api/config`, or `/api/status`.
- Manual selection takes effect on the **next generation** with no re-login.
- Automatic, silent fallback to the configured second provider on quota/rate-limit, auth,
  timeout, network, or 5xx errors. The report records which provider and model actually answered.
- Existing `OPENAI_API_KEY` env-var behavior keeps working as a fallback, so today's install is
  unaffected.

## Non-goals

- No quota/balance checking or provider usage dashboards in the plugin — the user monitors those
  externally.
- No system keyring integration (extra DBus dependency; may not be unlocked at shell start).
- No Mixture of Agents, auxiliary models, tier selectors, or context-window override from the
  Hermes screenshots.
- No changes to deterministic indicator/level generation.

## Anti-goals

- A key appearing in any log, report, config response, or UI text other than its own masked hint.
- Falling back on **invalid or ungrounded model output** — that is a prompt-quality problem; a
  second model would just produce a different bad answer. Deterministic playbook stays last resort.
- Switching providers silently without recording the switch in the report.

## Constraints

- Keys file: `$XDG_DATA_HOME/crypto-playbook/keys.json` (default
  `~/.local/share/crypto-playbook/keys.json`), created with mode `600`.
- Config gains `llm.provider` (active) and `llm.fallback_provider` (nullable); existing
  `base_url`, `model`, `api_key_env`, `timeout_s` remain.
- Key resolution order per call: key from `keys.json` for that provider → env var named by
  `api_key_env` (legacy fallback) → `LLMUnavailable`.
- Plugin ID `windong.cryptoplaybook`; QML colors remain theme-derived (`Color.*` / `Style.*`), no
  literal hex; tests offline; no API key available in this environment, so no live LLM calls in
  tests.
- Validation: `omarchy plugin validate` and `qmllint` (if available) must pass.

## Approaches considered

- **A. Keys file + provider presets + model picker + automatic fallback — CHOSEN.** Covers both
  planned and surprise switches; contained increment.
- **B. Keys + picker, no automatic fallback.** A scheduled run that hits an exhausted primary
  produces no narrative; insufficient for the user's stated concern.
- **C. Keep env vars, add only a model dropdown.** Switching provider would still need a key
  re-export and re-login — the friction being removed.

## Decided how

### Storage and API

- New `engine/keys.py`: `load_keys(path=None)`, `save_keys(data, path=None)`, `set_key(provider,
  key)`, `clear_key(provider)`, `mask(key)`, `key_for(provider, config)`. Atomic writes, mode
  `600`, never returns a full key through read-only endpoints.
- Daemon endpoints: `GET /api/providers` (presets with `key_set` and masked hint only),
  `POST /api/providers/key` (`{"provider": id, "key": "..."}`), `DELETE /api/providers/key`
  (`{"provider": id}`). Active/fallback selection goes through the existing `/api/config` with
  `llm.provider` and `llm.fallback_provider`.
- CLI commands: `providers`, `set-key <provider> <key>`, `clear-key <provider>`; existing
  `config` / `set-config` handle active/fallback. Keys are never printed by `status`, `config`, or
  `report`.
- `engine/llm.py` refactor: `call_llm` accepts an explicit resolved key (or an `LLMProvider`
  dict) instead of reading `os.environ` directly; env fallback is resolved in one place.

### Fallback behavior

- `engine/generate.py`: build the primary provider config from active selection; on a provider
  error (429/402/401/403, timeout, transport error, 5xx, or an `insufficient_quota` /
  `rate_limit` marker in the error body), retry once with the fallback provider if configured.
- Do not fall back on schema/grounding validation failure or any other invalid output; save the
  deterministic report with `prediction.available = false` and a short reason as today.
- Report gains `prediction.provider`, `prediction.model`, and `prediction.fallback_used` so the UI
  can show what actually answered.

### UI

- Sidebar gains `Model` (Main model, Fallback model) and, under `Providers`, `API keys`.
- `views/ApiKeys.qml`: preset rows with masked hints, paste field per provider, active marker,
  custom endpoint row; mutations via the CLI helper. No full key is ever rendered.
- `views/Model.qml`: active and fallback dropdowns; provider choice fills base URL/model but both
  stay editable in Settings. Keep existing `Settings.qml` coins/interval/model fields.
- Replace the read-only "THE API KEY" status card with a link to the API keys screen; keep a
  masked/set-or-missing status line.

## What's left to the builder

- Exact preset list and their base URLs/default models (OpenAI, OpenRouter, DeepSeek, Groq,
  OpenCode-compatible, custom endpoint). Verify endpoint shapes; do not guess an undocumented API.
- Exact CLI command names and `/api/providers` response shape if the briefs leave them open.
- UI layout, spacing, and ordering within the sample's visual language.
- Whether to offer an import of an existing env-var key into `keys.json` (default: no; env remains
  a fallback).
