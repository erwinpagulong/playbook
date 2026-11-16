# Crypto Playbook & Prediction Plugin for Omarchy — Design

**Date:** 2026-11-16
**Status:** Draft for approval
**Repo:** current `playbook` repo (remote not yet configured — see Open questions)

## Intent and why

The user wants their **own** crypto analysis, not someone else's calls. Today that analysis
lives as two point-in-time markdown snapshots (a playbook with entry/TP1/TP2/stop levels, and a
prediction with scenarios, probabilities and confidence) for BTC/USDT. The goal is to turn that
into a living tool on the desktop: an Omarchy top-bar widget that opens a centered,
dashboard-style window where current and past playbooks and predictions for a set of coins can
be read at a glance, generated on a schedule and on demand.

Success looks like: click the bar widget → a themed dashboard opens instantly → the latest
playbook and prediction for BTC/ETH are there, with history one sidebar click away → "Regenerate"
produces a fresh, grounded report in seconds.

## Goals

- A `bar-widget` glance (e.g. BTC price + bias) in the Omarchy bar; clicking opens the app.
- A centered dashboard window with a **sidebar** in the style of the provided OMABUDGET sample
  (numbered nav, active row highlighted, "Local. Private. Yours."-style footer).
- Dashboard content: stat cards (live price + 24h %, bias, confidence, best R:R), an alert
  banner, the **entry/exit map** table, **prediction scenarios**, an **indicator dashboard**
  (15m / 4h / 1D), and a **recent reports / history** list.
- Sidebar sections: Dashboard, Playbooks, Predictions, Coins, History, Settings, Data & Privacy
  (adapted from the sample; exact labels are a builder detail).
- Reproduce the **structure and data-bearing sections** of the two sample docs (market snapshot,
  indicator dashboard, entry/exit map, risk rules, scenarios/confidence, bottom line) — not
  byte-exact text. The report schema allows an arbitrary number of position rows per timeframe
  (e.g. daily LONG confirmed + LONG value tranche + SHORT), not a fixed grid.
- Reports for **BTC/USDT and ETH/USDT** by default; the coin list is configurable.
- **Blend analysis**: deterministic indicators compute the numbers; a cloud LLM writes the
  narrative prediction grounded in those numbers.
- Reports stored **locally** as both JSON (machine-readable, for the UI) and markdown (human-
  readable archive, matching the two sample docs).
- Generation is **both scheduled (default: hourly) and manual** via a "Regenerate" button.
- The app **follows the active Omarchy theme live** — no hardcoded palette.
- Final repo pushed to the user's GitHub.

## Non-goals

- No trade execution, brokerage/broker connection, or order placement. This is analysis only.
- No local/on-machine LLM (explicitly rejected as too slow for the user's machine).
- No full TradingAgents-style multi-agent debate (bull/bear researcher teams, etc.).
- No changes to Omarchy's theme system or shell internals.
- No FinceptTerminal-scale data catalog or 100+ connectors.

## Anti-goals (would make this a failure even if it technically works)

- **Fabricated numbers.** The LLM must never invent price levels or indicators that were not
  derived from the fetched data. Probabilities and confidence are the one deliberate exception:
  they are **subjective estimates from the chart**, explicitly labeled as such in the sample
  prediction, not fabricated facts. (The sample also debunks made-up "75% win rate" claims; the
  design must not reproduce that failure mode.)
- **A hardcoded palette** that breaks or clashes when the user switches themes.
- **A blocking UI.** LLM and network work happens in the background daemon; the panel must open
  and scroll instantly even while a report is generating.
- **A leaked API key** in the repo, logs, or report files.

## Constraints

- Omarchy runs a single long-lived Quickshell ("Quattro") process. Plugins are QML, run
  unsandboxed with the user's permissions, and must never spawn a second shell.
- Plugin contract: `bar-widget` → `BarWidget.qml`, `panel` → `App.qml`, `service` → `Service.qml`.
- Validation: `omarchy plugin validate <dir>` and `qmllint -I "$OMARCHY_PATH/shell" ...` must pass.
- Theme tokens are available to QML through the shell singletons: `Color.foreground`,
  `Color.background`, `Color.accent`, `Color.urgent`, and `Style.normalBorderColor`,
  `Style.font.family` (imports `qs.Commons`, `qs.Ui`). Omabudget derives semantic colors from
  these and retints on theme switch — this plugin does the same.
- API keys are supplied via environment variable, read by the Python daemon, never committed.
  `.env` files and report data are gitignored.
- Candle data: Binance public REST (no key), matching the sample docs; yfinance (`BTC-USD`,
  `ETH-USD`) as fallback. Yahoo data is personal-use-only and may throttle.
- Python engine: prefer pure pandas/numpy indicator implementations over TA-Lib to avoid a
  native C build dependency on the user's machine.

## Approaches considered

- **A. Fork the installed Omabudget plugin structure — CHOSEN.** Reuse its three-kind plugin
  (`bar-widget` + `panel` + `service`), theme-token derivation, sidebar/views dashboard and
  loopback-daemon IPC; replace the finance daemon with the Python analysis engine. Lowest risk,
  closest to the user's visual reference, fastest.
- **B. Start from Omarchy's built-in clock clone (official tutorial).** Bar-widget + nested panel
  only; no dashboard, sidebar, service or history scaffolding. Much more from-scratch work and
  the panel anchors to the bar instead of being centered.
- **C. Web dashboard in a WebView.** Easier rich charts, but theme adoption becomes manual, the
  feel is less native, and a WebView dependency is added.

## Decided how (the parts the user chose)

### Plugin shell (approach A)

- `manifest.json`: `kinds: ["bar-widget", "panel", "service"]`, with `entryPoints` mapping to
  `BarWidget.qml`, `App.qml`, `Service.qml`. A namespaced ID (e.g. `<user>.cryptoplaybook`).
- `Service.qml`: owns the Python daemon process on loopback, with backoff/respawn like Omabudget;
  the daemon is started when the plugin is enabled and reaped on teardown.
- `BarWidget.qml`: a compact glance reading the latest report via a short-lived CLI helper call
  on a timer; click toggles the panel through the shell (`shell.toggle`).
- `App.qml` + `views/*`: the centered window, sidebar, and per-section views. QML never calls the
  LLM or an exchange directly — all reads/writes go through the CLI helper to the daemon.

### Analysis engine (Python daemon + CLI helper)

Pipeline, per coin, per generation:

1. **Fetch** OHLCV candles for 15m, 4h and 1D (~200 bars each) from Binance public REST; fall
   back to yfinance on failure. Best-effort CoinGecko/Coinbase quotes fill the sample's
   multi-source market snapshot when available. Cache raw candles locally to survive rate limits.
2. **Compute** indicators deterministically: RSI(14), MACD line/signal/hist, Bollinger Bands,
   ATR(14), and the moving-average stack on each timeframe; derive support/resistance levels.
3. **Assemble levels**: the entry / TP1 / TP2 / stop table per timeframe and direction, plus
   R:R — the exact structure of the sample playbook. This step is pure math, no LLM.
4. **Ground the LLM**: send the computed payload — including the assembled entry/exit table from
   step 3, not just raw indicators — with a strict instruction to return JSON containing scenarios
   with probabilities, a highest-conviction call, confidence, and confirmation/invalidation rules
   — the shape of the sample prediction. Validate the reply against a schema: every specific price
   level in the narrative must be present in the payload; scenario probabilities must be labeled
   as subjective estimates. Do not require probabilities to come from the payload.
5. **Write** a report as `report.json` (for the UI) and `report.md` (readable archive) under a
   local data dir, keyed by coin + timestamp. Expose current + history through the daemon.

### LLM configuration

- Provider-agnostic: any OpenAI-compatible chat endpoint (OpenAI, Anthropic via compatible proxy,
  Gemini, Groq, DeepSeek, OpenRouter, etc.), configured by base URL + model + env-var key name.
- Low temperature, bounded output, timeout, and limited retries.
- Graceful degradation: if the LLM call fails or is invalid, still save and show the
  deterministic playbook, with the prediction section clearly marked unavailable.

### Scheduling and manual regenerate

- The daemon runs a scheduler (default interval: 1 hour, configurable) that regenerates every
  configured coin.
- The panel's "Regenerate" button requests an on-demand run for the selected coin and shows a
  progress state; the run happens in the daemon, never on the UI thread.
- Run status and the latest report are exposed to the UI; the bar glance updates on completion.

### Settings and Data & Privacy (hybrid — chosen)

- **Settings:** coin list, generation interval and LLM model are editable in the panel and saved
  to a local config file the daemon reads. The API key stays in an env var and is never typed into
  the UI or written to config.
- **Data & Privacy:** explains where reports/config live, that analysis text is sent to the
  configured LLM provider, and offers "Export reports" and "Delete reports" actions.

### First run and empty state

- On first start with an empty report store, seed the two provided BTC/USDT sample reports,
  clearly marked **sample** (dated 2026-11-16), so the dashboard has immediate content.
- If an LLM key is configured, trigger one generation at daemon startup rather than waiting for
  the first hourly tick; if no key is configured, show a clear onboarding state pointing to
  Settings.
- The bar widget shows a placeholder (e.g. "—") until a report exists.

### Theme adoption

- Derive `foreground`, `background`, `accent`, `urgent`, border and font from `Color.*`/`Style.*`
  in `App.qml`, exactly as Omabudget does; pass them into views.
- Semantic colors derived from those tokens: long/bullish = accent, short/bearish = urgent,
  neutral = foreground, warning = accent/urgent mix. No literal hex values in views.

## What's left to the builder (reasonable calls, flag if wrong)

- Exact plugin ID and GitHub repo URL/remote (user has not supplied the repo yet).
- Loopback port number, data/config directory paths, and a report retention policy.
- Default LLM provider/model and the precise env-var name (design is provider-agnostic).
- Specific sidebar labels, card arrangement and spacing within the sample's visual language.
- Use a CLI helper for daemon IPC (recommended, mirrors Omabudget) vs direct HTTP from QML.
- Exact indicator formulas and the R:R computation, transcribed from the sample playbook's
  structure and the standard RSI/MACD/BB/ATR definitions.
