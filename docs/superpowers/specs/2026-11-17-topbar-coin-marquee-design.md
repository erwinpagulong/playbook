# Topbar coin marquee — design

## Intent / why

The bar widget currently shows one coin's price + bias. It calls `playbook latest`
with no coin filter, so the daemon returns the newest report **across all coins**.
Since the scheduler generates config coins in order (BTC, then ETH), ETH lands a
few seconds later and wins — the bar appears to "default to ETH bias" even though
nothing is hardcoded and the primary coin in config is BTC. The user wants the
topbar to show **all configured coins** (3–4 is the expected case) in a scrolling
marquee instead of one coin.

## Goals

- Topbar continuously scrolls one figure per configured coin: `price · LONG/SHORT`.
- Each figure uses the existing bias color tokens (accent / urgent / foreground).
- Seamless infinite loop; pauses on hover so a figure can be read.
- Click still opens the app (unchanged behavior).
- Adding/removing a coin in Settings updates the ticker without a code change.

## Non-goals / anti-goals

- No engine/daemon API changes — reuse existing `playbook coins` and
  `playbook latest <coin>` CLI commands.
- No new dependencies.
- Not a fix to `/api/latest` semantics (that remains "newest across all coins"
  when no filter is given); the widget simply stops relying on that path.
- Not a config setting for speed/width — sensible fixed defaults.

## Constraints

- QtQuick / Quickshell `BarWidget`; must keep `moduleName`, service probe, and
  `Process`-based helper invocation pattern already in `BarWidget.qml`.
- Bar width is limited: fixed clipped viewport, not an ever-growing row.
- Child process env stays the allowlisted `childEnv` (PATH/HOME/XDG_*).
- Existing theme tokens from `Color.*` / `Style.*`; no literal colors.

## Approaches considered

1. **Pin BTC in the widget** (`playbook latest BTC/USDT`) — rejected: ignores the
   configured coin list, so a future primary-coin change is not reflected.
2. **Fix `/api/latest` to default to the first configured coin** — rejected for
   this request: changes app-wide semantics and still shows only one coin.
3. **Rotate one coin every N seconds** — rejected: user explicitly asked for a
   marquee that scales to 3–4 coins.
4. **Scrolling marquee (chosen)** — shows every configured coin at once in a
   bounded width, scales with coin count, matches the request. Tradeoff: a
   continuously moving bar is less glanceable than a static figure; mitigated by
   hover-pause.

## Design (as approved)

- Reuse `helperPath` and a new `Process` for `playbook coins -addr <addr>` to get
  the coin list (bare JSON array); re-fetch on each refresh so Settings changes
  are picked up.
- For each coin, a `Process` runs `playbook latest <coin> -addr <addr>`; store the
  parsed snapshot in a `snaps` map keyed by coin. Keep existing error handling:
  non-JSON / empty output → no snap; a coin with no report renders `—`.
- Fixed, clipped viewport (~`Style.space(240)` wide); inside it a `Row` of
  `CoinFigure` delegates, each fixed `Style.space(120)` wide with elide, showing
  `formatPrice(price)` + ` · ` + `biasLabel`, colored by bias. Reuse the existing
  `price` / `bias` / `biasLabel` / `biasColor` derivation per snapshot.
- Render the coin list **twice** in the row. Animate the row's `x` from `0` to
  `-halfWidth` (width of one copy + spacing) on an infinite `NumberAnimation` at
  ~30 px/s (~4 s per coin). Restart the animation if the coin list or half-width
  changes; `running: !hovered` pauses on hover. When there are no coins, show a
  static `—` and no animation.
- Tooltip lists all coins and their figures; click handler unchanged.

## What's left to the builder

- Implement in `BarWidget.qml` only.
- Verify by loading in Quickshell: scroll loops seamlessly, hover pauses, click
  opens the app, a coin with no report shows `—`, and adding a coin to Settings
  adds it to the ticker. Run the existing `pytest` suite to confirm no engine
  regression (engine is untouched).
