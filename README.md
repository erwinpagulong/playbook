# Crypto Playbook

An Omarchy plugin that shows crypto playbooks and predictions: a compact bar-widget
glance, a sidebar-driven dashboard panel, and a background service that generates
deterministic playbooks (candles, indicators, entry/exit levels) plus LLM-grounded
predictions on a schedule and on demand.

Everything runs locally: the QML shell never touches the network. A Python daemon
on loopback (`127.0.0.1:8099`) does the fetching, analysis, and report storage, and
a thin CLI helper exposes JSON commands to QML.

## Install

Clone or copy this repository to the Omarchy plugin directory:

```bash
~/.config/omarchy/plugins/windong.cryptoplaybook/
```

Then enable the plugin with the Omarchy plugin tooling. Python dependencies are in
`requirements.txt`:

```bash
python3 -m pip install -r requirements.txt
```

## Environment variables

Narrative generation is provider-agnostic: any OpenAI-compatible chat endpoint works.
Configuration comes from four environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | API key read by default (never stored in config, reports, logs, or the repo) |
| `LLM_BASE_URL` | OpenAI-compatible default | Base URL of the chat endpoint |
| `LLM_MODEL` | built-in default | Model name to call |
| `LLM_KEY_ENV` | `OPENAI_API_KEY` | Name of the env var that holds the API key |

## Disclaimer

This plugin is for education and research only. Nothing it produces is financial
advice. Crypto assets are volatile — you are solely responsible for your own trades.
