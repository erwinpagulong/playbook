# Crypto Playbook

An Omarchy plugin that shows crypto playbooks and predictions: a compact bar-widget
glance, a sidebar-driven dashboard panel, and a background service that generates
deterministic playbooks (candles, indicators, entry/exit levels) plus LLM-grounded
predictions on a schedule and on demand.

Everything runs locally: the QML shell never touches the network. A Python daemon
on loopback (`127.0.0.1:8099`) does the fetching, analysis, and report storage, and
a thin CLI helper exposes JSON commands to QML.

## Install

From a clone of this repository:

```bash
./install.sh
```

The installer copies the plugin into `~/.config/omarchy/plugins/windong.cryptoplaybook/`,
generates the `bin/playbookd` (daemon) and `bin/playbook` (CLI) wrappers, creates a
`.venv` there, and installs `requirements.txt` into it. It is idempotent — re-run it
after pulling updates.

Then, as printed by the installer:

```bash
omarchy-shell shell rescanPlugins          # let the shell discover the plugin
omarchy plugin enable windong.cryptoplaybook
```

### Bar placement

When installing through Omarchy (for example `omarchy plugin add <repo-url> --enable`),
Omarchy asks which bar section to place the widget in. The manifest's
`barWidget.defaultSection` pre-selects `centerEnd` (beside the clock); choosing
`center` in that prompt also lands in `centerEnd`, because `center` is the
clock's own centered group. Available sections are `left`, `centerBegin`,
`center`, `centerEnd`, `tray`, and `right`.

If you installed with `./install.sh` (which skips Omarchy's placement prompt),
or want to move the widget later, use:

```bash
omarchy bar move windong.cryptoplaybook --section right   # or left, centerBegin, centerEnd
```

The shell hot-reloads `shell.json`, so no restart is needed.

LLM predictions need an API key for the active provider. The primary path is
the in-app **API keys** screen: open the dashboard panel, go to *API keys*,
paste your key for a provider (OpenAI, OpenRouter, DeepSeek, Groq, or a custom
OpenAI-compatible endpoint), and you're done. Keys are stored in a private
`keys.json` (mode `600`) under the data dir — never in the config, the reports,
or the QML shell — and the daemon reads them at generation time. The *Model*
screen picks which provider writes the prediction narrative and which one is
tried when the active provider fails.

The environment variable named by `llm.api_key_env` (`OPENAI_API_KEY` by
default) still works as a **legacy fallback**: if no key is stored in
`keys.json` for a provider, the daemon reads that variable at generation time. Because
the daemon is launched by Quickshell, such a variable must live in **Quickshell's
own launch environment**: export it in the shell session that starts
Omarchy/Quickshell (for example from your login shell profile) *before*
starting the shell, then restart the shell so the daemon inherits it. Exporting
it in a separate terminal after the shell is running will not reach the daemon,
and a stored key always wins over the environment.

The daemon starts with the Omarchy shell's background services and seeds two sample
reports (BTC/USDT playbook + prediction) into an empty report store, so the panel
has content on first launch.

## Dependencies and network access

`install.sh` needs Python 3 and `pip`. It creates a private `.venv` inside the
plugin directory (with real interpreter binaries, no symlinks) and installs the
packages pinned in `requirements.txt`: `pandas`, `numpy`, `requests`, and
`yfinance`. `pytest` is included for running the test suite and is not needed
at runtime.

The QML shell only talks to the daemon on loopback (`127.0.0.1:8099`); it never
makes a network request itself. The daemon fetches public market data on a
schedule or when you regenerate a report:

- Candles: the public Binance REST API, with Yahoo Finance (via `yfinance`) as
  a fallback, then a local on-disk cache.
- Quotes: Binance, CoinGecko, and Coinbase, on a best-effort basis.

No credentials are needed for market data. The only network call that can
carry your own data is an **optional** LLM prediction request: when a provider
key is configured, the computed indicator/level payload is sent to the selected
OpenAI-compatible provider to write the narrative. Without a key, the daemon
still produces deterministic playbooks and skips only that narrative. Reports,
config, and keys stay in XDG data/config directories on your machine.

## Configure

Configuration lives at `$XDG_CONFIG_HOME/crypto-playbook/config.json` (default
`~/.config/crypto-playbook/config.json`). Reports and other state live under
`$XDG_DATA_HOME/crypto-playbook/` (default `~/.local/share/crypto-playbook/`).
Missing keys fall back to these defaults:

```json
{
  "coins": ["BTC/USDT", "ETH/USDT"],
  "interval_minutes": 60,
  "llm": {
    "provider": "openai",
    "fallback_provider": null,
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key_env": "OPENAI_API_KEY",
    "timeout_s": 60
  }
}
```

`interval_minutes` must be an integer ≥ 5. Coins are `BASE/QUOTE` pairs like
`BTC/USDT`. Edit the file by hand, or through the CLI (which validates and saves
atomically):

```bash
~/.config/omarchy/plugins/windong.cryptoplaybook/bin/playbook set-config \
  '{"coins": ["BTC/USDT", "SOL/USDT"], "interval_minutes": 120}'
```

### Providers and keys

`llm.provider` selects which provider preset writes the prediction narrative;
`llm.fallback_provider` names a second provider that is tried when the active
one fails (set it to `null` to disable). Both must be one of the preset ids —
`openai`, `openrouter`, `deepseek`, `groq`, or `custom` — and the fallback must
differ from the active provider. Selecting a provider on the *Model* screen
fills in that preset's `base_url` and `model`; the `custom` preset ships empty
so you supply your own OpenAI-compatible endpoint (edited on the *API keys*
screen or in the config). Provider keys are stored per provider in
`$XDG_DATA_HOME/crypto-playbook/keys.json` (default
`~/.local/share/crypto-playbook/keys.json`), shaped
`{"providers": {"<id>": "<key>"}}` and kept mode `600`. Keys never appear in the
config, the reports, the CLI output, or the UI — the daemon re-reads the file
per request and only ever reports a boolean plus a masked hint.

Notes on the LLM configuration: the only environment variable read by default is
`OPENAI_API_KEY`, and only as a legacy fallback — the key value is placed in the
`Authorization` header and is never logged, printed, stored in the config, or
included in reports. The durable path is a stored key via the *API keys* screen
or `playbook set-key`; a stored key wins over the environment. To use a different
provider or model, edit `llm.provider` / `llm.base_url` / `llm.model` /
`llm.api_key_env` / `llm.timeout_s` in `config.json` (or via `set-config`);
`api_key_env` can name any environment variable you keep a fallback key in.
There are no `LLM_*` environment overrides. When the active provider fails, the
daemon retries the fallback (if configured) and records which provider answered
via `prediction.provider` / `prediction.model` / `prediction.fallback_used` in
the report.

### CLI cheat sheet

`~/.config/omarchy/plugins/windong.cryptoplaybook/bin/playbook <command>`

```
latest [coin]      newest report (optionally filtered by coin)
reports [coin]     stored reports, newest first
report <id>        one report by id
status             coins, interval, report count, run state
coins              configured coins
config             effective config (defaults merged)
set-config <json>  validate + atomically save a config object
providers          per-provider state: active/fallback, base_url, model, key set + masked hint
set-key <id> <key> store a provider key in the private keys file (600)
clear-key <id>     remove a stored provider key
regenerate <coin>  kick off a background generation run
export [dest]      copy the reports dir (default ~/Documents/crypto-playbook-export)
delete-reports     remove generated reports (samples are kept)
```

`set-key` sends the key in the request body only; the daemon answers with
`{"ok":true}` and never echoes the key.

Pass `-addr host:port` (before or after the command) to talk to a daemon on a
non-default address. `playbookd -port 0` picks an ephemeral port and prints it on
stdout; the default is `127.0.0.1:8099`.

## Uninstall

```bash
omarchy plugin disable windong.cryptoplaybook
rm -rf ~/.config/omarchy/plugins/windong.cryptoplaybook
```

Then reload the shell (`omarchy-shell shell rescanPlugins`). User state is kept by
default — remove it only if you want the reports and config gone too:

```bash
rm -rf ~/.local/share/crypto-playbook ~/.config/crypto-playbook
```

## Disclaimer

This plugin is for education and research only. Nothing it produces is financial
advice. Crypto playbooks are generated from historical price action and an LLM's
reading of it; they describe scenarios, not certainties. Crypto assets are volatile —
you are solely responsible for your own trades. Never trade money you cannot afford
to lose, and consult a licensed financial advisor before making investment decisions.
