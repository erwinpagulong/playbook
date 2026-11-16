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

LLM predictions need an API key, and the daemon reads it from the environment at
startup. Because the daemon is launched by Quickshell, the key must be in
**Quickshell's own launch environment**: export `OPENAI_API_KEY` in the shell session
that starts Omarchy/Quickshell (for example from your login shell profile) *before*
starting the shell, then restart the shell so the daemon inherits the variable:

```bash
export OPENAI_API_KEY=sk-...               # only needed for LLM predictions
# then restart Omarchy/Quickshell so the daemon picks the variable up
```

Exporting the key in a separate terminal after the shell is already running will not
reach the daemon. Without the key in Quickshell's environment, only the deterministic
playbooks are generated and the narrative prediction is skipped.

The daemon starts with the Omarchy shell's background services and seeds two sample
reports (BTC/USDT playbook + prediction) into an empty report store, so the panel
has content on first launch.

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

Notes on the LLM configuration: the only environment variable read by default is
`OPENAI_API_KEY`, and only because `llm.api_key_env` names it — the key value is
placed in the `Authorization` header and is never logged, printed, stored in the
config, or included in reports. It must be exported into Quickshell's launch
environment before the shell starts (see Install above), not just into a terminal.
To use a different provider or model, edit
`llm.base_url` / `llm.model` / `llm.api_key_env` / `llm.timeout_s` in
`config.json` (or via `set-config`); `api_key_env` can name any environment
variable you keep the key in. There are no `LLM_*` environment overrides.

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
regenerate <coin>  kick off a background generation run
export [dest]      copy the reports dir (default ~/Documents/crypto-playbook-export)
delete-reports     remove generated reports (samples are kept)
```

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
