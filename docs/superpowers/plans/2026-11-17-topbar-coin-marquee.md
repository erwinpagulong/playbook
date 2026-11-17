# Topbar coin marquee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-coin topbar glance with a seamless scrolling marquee showing every configured coin's price + bias.

**Architecture:** All changes are in `BarWidget.qml`. Two concerns: (1) fetch the config coin list and one latest snapshot per coin via the existing `playbook` CLI, keeping a coin→snapshot map; (2) render a fixed, clipped viewport containing the coin figures twice and animate the inner row left by exactly one copy's width on an infinite loop, pausing on hover. No engine/daemon changes.

**Tech Stack:** QtQuick / Quickshell (`Process`, `StdioCollector`, `Timer`, `NumberAnimation`, `MouseArea`, `Repeater`), Python CLI already in `bin/playbook`.

**Spec:** `docs/superpowers/specs/2026-11-17-topbar-coin-marquee-design.md`

## Global Constraints

- No engine/daemon API changes. Reuse `playbook coins -addr <addr>` and `playbook latest <coin> -addr <addr>`.
- Child processes use the existing allowlisted `childEnv` (`PATH`, `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`) with `clearEnvironment: true`.
- Theme tokens only (`Color.*`, `Style.*`, existing `accent`/`urgent`/`foreground`); no literal hex colors.
- Keep `moduleName`, service probe, built/running gating, click-to-open (`toggleApp`), and refresh/backoff behavior intact.
- QML has **no automated test harness in this repo** (only Python `pytest` under `tests/`); QML verification is a manual load in Quickshell plus `pytest -q` for no engine regressions.

## Review Focus

- A coin with no report yet → render `—`, do not break the loop. Pinned in Task 2 verification step (configure a third coin with no report).
- Coin list changes at runtime via Settings → ticker picks it up without a shell restart. Pinned in Task 1 verification step (re-fetch on each refresh).
- Empty / non-JSON CLI output → ignore it, never crash or leave a stale figure. Pinned in Task 1 verification step.
- Hover pause → scroll stops while hovered and resumes on leave; click still opens the app. Pinned in Task 2 verification step.
- Zero or one configured coin → no divide-by-zero / no pointless animation; show a static figure or `—`. Pinned in Task 2 verification step.

---

### Task 1: Per-coin data fetching in `BarWidget.qml`

**Files:**
- Modify: `BarWidget.qml` (properties block ~30–91 and `Process` block ~123–144)

**Interfaces:**
- Consumes: existing `addr`, `helperPath`, `childEnv`, `running`, `refresh()`, `Component.onCompleted`, refresh `Timer`.
- Produces: `property var coins` (array of coin strings), `property var snaps` (map coin → latest payload), and helper functions `priceFor(coin) -> real`, `biasFor(coin) -> string`, `biasColorFor(coin) -> color`, `figureFor(coin) -> string`. Task 2 consumes all of these.

- [ ] **Step 1: Baseline**

Run: `cd /home/windong/orca/workspaces/playbook/guillemot && pytest -q`
Expected: all tests pass.
Run the helper against the live daemon to confirm shapes:
`<plugin>/bin/playbook coins` → JSON array e.g. `["BTC/USDT","ETH/USDT"]`;
`<plugin>/bin/playbook latest BTC/USDT` → object with `available` and `report`.

- [ ] **Step 2: Add coin list and per-coin snapshot state**

Replace the single `snap`/`report` state with:
- `property var coins: []` — the configured coin list.
- `property var snaps: ({})` — map from coin string to the parsed `latest` payload.
- A `Process` (`coinsProc`) running `[helperPath, "coins", "-addr", addr]` with `clearEnvironment`/`childEnv`, whose `StdioCollector.onStreamFinished` parses the array (ignore empty/invalid output, keep previous `coins`).
- A `Process` (`latestProc`) and a queue: for each coin in `coins`, run `[helperPath, "latest", coin, "-addr", addr]` and store the parsed payload in `snaps[coin]`; ignore empty/non-JSON output. Guard with `fetchProc.running` equivalents so calls do not overlap.
- Re-run the coin fetch at the start of each `refresh()` so Settings changes are picked up.
- Add `priceFor(coin)`, `biasFor(coin)`, `biasColorFor(coin)`, `figureFor(coin)` as pure functions over `snaps[coin]`, reusing the existing price fallback (quote → 1D/4h/15m indicator price), bias derivation (daily trend first), and `formatPrice`. `figureFor` returns `formatPrice(price)` + ` · ` + `LONG|SHORT|FLAT` (price only when bias is empty); returns `—` when the coin has no report.

- [ ] **Step 3: Verify data layer**

Run: `./install.sh` then `omarchy-shell shell rescanPlugins`, reload the shell, and check the Quickshell log for QML errors (no "ReferenceError"/"TypeError").
Manual probe: add a third coin in Settings, wait one refresh, confirm the coin fetch re-ran (e.g. a temporary `console.log` of `coins`/`Object.keys(snaps)` removed before commit) and that an empty/non-JSON reply leaves state unchanged.
Run: `pytest -q`
Expected: all tests pass (engine untouched).

- [ ] **Step 4: Commit**

```bash
git add BarWidget.qml
git commit -m "feat: fetch per-coin snapshots for topbar marquee"
```

### Task 2: Marquee rendering, loop, and hover pause

**Files:**
- Modify: `BarWidget.qml` (the `Row`/`Text` display block ~146–183 and tooltip ~158–163)

**Interfaces:**
- Consumes: `coins`, `snaps`, `figureFor(coin)`, `biasColorFor(coin)` from Task 1; `toggleApp()`.
- Produces: no new external API; final widget behavior.

- [ ] **Step 1: Add viewport and loop geometry properties**

Add: `viewportWidth: Style.space(240)`, `figureWidth: Style.space(120)`, `figureSpacing: Style.space(12)`, `pxPerSec: 30`, `copyWidth: coins.length * (figureWidth + figureSpacing)`.
`duration` for the animation = `copyWidth / pxPerSec * 1000`.

- [ ] **Step 2: Build the marquee**

Replace the single price `Text` with: a clipped `Item` viewport of `viewportWidth`; inside it a `Row` (`id: ticker`, spacing `figureSpacing`) whose model is the coin list rendered **twice** (two `Repeater`s, or one repeater over a `coins.concat(coins)` array), each delegate a fixed-width `CoinFigure` showing `figureFor(coin)` in `biasColorFor(coin)` with horizontal elide.
Add an infinite `NumberAnimation` on `ticker.x` from `0` to `-copyWidth`, duration as above, `loops: Animation.Infinite`, `running: coins.length > 0 && !marqueeMouse.containsMouse`. Restart it in a root `onCopyWidthChanged` handler so a changed coin list re-computes the loop; when `coins.length === 0`, show a static `—` and no animation.
Add a `MouseArea` (`id: marqueeMouse`, `hoverEnabled: true`, fill viewport) whose `onPressed` calls `root.toggleApp()`.

- [ ] **Step 3: Verify marquee behavior**

Install/rescan/reload as above and confirm visually:
- Strip scrolls left continuously and loops seamlessly (no visible jump at the wrap point).
- Hovering stops the scroll; leaving resumes it.
- Clicking opens the app panel.
- A coin with no report shows `—` without breaking the loop.
- Setting the coin list to one coin (or zero) leaves a static figure/`—` with no runaway animation.
- Adding a coin in Settings adds it to the ticker after a refresh.
Run: `pytest -q` → all pass.

- [ ] **Step 4: Commit**

```bash
git add BarWidget.qml
git commit -m "feat: scroll all configured coins in topbar marquee"
```
