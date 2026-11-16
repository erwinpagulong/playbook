# Crypto Playbook & Prediction Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Omarchy bar-widget plugin with a themed, sidebar-driven dashboard that generates and displays local crypto playbooks and LLM-grounded predictions on a schedule and on demand.

**Architecture:** Fork the installed `karamble.omabudget` three-kind plugin shape (bar-widget + panel + service). QML never touches the network: a `Service.qml`-owned Python daemon on loopback does candle fetching, deterministic indicator/level computation, LLM narrative generation, and local report storage; a thin CLI helper exposes JSON commands to QML. Colors are derived from the shell's `Color.*` / `Style.*` singletons so the app retints on theme switch.

**Tech Stack:** QML / Quickshell (Quattro), Python 3.11+, pandas, numpy, requests, yfinance, pytest, stdlib `http.server`.

**Spec:** `docs/superpowers/specs/2026-11-16-crypto-playbook-plugin-design.md`

## Global Constraints

- Plugin ID: `windong.cryptoplaybook` (replace consistently if a different namespace is wanted).
- Plugin kinds: `["bar-widget", "panel", "service"]`; entry points: `BarWidget.qml`, `App.qml`, `Service.qml`.
- `manifest.json` required keys: `schemaVersion`, `id`, `name`, `version`, `kinds`, `entryPoints`; third-party IDs must not start with `omarchy.`; plugin folder contains no symlinks.
- Loopback address: `127.0.0.1:8099`. Daemon binds loopback only.
- Config: `$XDG_CONFIG_HOME/crypto-playbook/config.json`, default `~/.config/crypto-playbook/config.json`.
- Data: `$XDG_DATA_HOME/crypto-playbook/`, default `~/.local/share/crypto-playbook/`. Reports in `data/reports/`, raw candle cache in `data/candles/`.
- API key: read from the env var named in config `llm.api_key_env` (default `OPENAI_API_KEY`); never written to config, reports, logs, or repo. `.env`, `data/`, `bin/` are gitignored; `samples/` is committed.
- Default coins: `["BTC/USDT", "ETH/USDT"]`; default interval: 60 minutes.
- No literal hex colors in QML — all colors derive from `Color.*` / `Style.*` (imports `qs.Commons`, `qs.Ui`).
- Python dependencies: pandas, numpy, requests, yfinance. No TA-Lib (no native build).
- Validation: `omarchy plugin validate <dir>` and `qmllint -I "$OMARCHY_PATH/shell" <files>` must pass where the tools are available.

## Review Focus

- **No LLM key / no report yet:** opening the panel and the bar must show a clear onboarding/placeholder state, never an error or blank crash. → Task 9 test `test_latest_with_empty_store_returns_placeholder`; Task 7 test `test_call_llm_without_key_raises`.
- **LLM invents a price level or malformed JSON:** validator rejects it and the pipeline still saves a deterministic playbook with `prediction.available = false`. → Task 7 validator tests; Task 8 `test_llm_failure_still_saves_report`.
- **Exchange API down or rate-limited:** falls back to yfinance, then to cached candles, and still produces a report. → Task 5 `test_binance_failure_falls_back_to_yfinance`; Task 8 `test_fetch_failure_uses_cache`.
- **Theme switch:** all colors follow the shell; no hardcoded palette. → Task 10 `test_no_literal_hex_colors_in_qml`.
- **Double-click Regenerate racing the hourly scheduler:** generation is serialized, no duplicate report IDs. → Task 8 `test_generate_is_serialized`.

---

### Task 1: Scaffold, manifest, and repo hygiene

**Files:**
- Create: `manifest.json`, `requirements.txt`, `.gitignore`, `engine/__init__.py`, `tests/__init__.py`, `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a valid plugin manifest; Python package `engine`; dependency list.

- [ ] **Step 1: Write the failing manifest test**

```python
# tests/test_manifest.py
def test_manifest_has_required_keys():
    m = load_manifest()
    assert m["schemaVersion"] == 1
    assert m["id"] == "windong.cryptoplaybook"
    assert not m["id"].startswith("omarchy.")
    assert m["kinds"] == ["bar-widget", "panel", "service"]
    for entry in ("BarWidget.qml", "App.qml", "Service.qml"):
        assert m["entryPoints"][  # key maps to file
            {"BarWidget.qml": "barWidget", "App.qml": "panel", "Service.qml": "service"}[entry]
        ] == entry
        assert (REPO_ROOT / entry).exists()

def test_no_symlinks():
    assert not any(p.is_symlink() for p in REPO_ROOT.rglob("*"))
```

Define `load_manifest()` and `REPO_ROOT` as small helpers in `tests/conftest.py`, returning parsed JSON and `Path(__file__).resolve().parents[1]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: FAIL (manifest.json missing).

- [ ] **Step 3: Create scaffold files**

`manifest.json`: use the values pinned in Global Constraints; include `name: "Crypto Playbook"`, a `description`, `version: "0.1.0"`, `author: "windong"`, and a `barWidget` block with `displayName`, `description`, `category: "Finance"`, and a `defaults` object (`addr: "127.0.0.1:8099"`, `refreshSec: 30`). Do not add a settings `schema` array — settings are edited in-panel (Task 11).

`requirements.txt`: `pandas>=2.0`, `numpy>=1.24`, `requests>=2.31`, `yfinance>=0.2.40`, `pytest>=8.0`.

`.gitignore`: `.env`, `data/`, `bin/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.qmlc`.

`README.md`: what the plugin is, install path, the four env vars (`OPENAI_API_KEY` by default, plus `LLM_BASE_URL`, `LLM_MODEL`, `LLM_KEY_ENV`), that it is educational only and not financial advice.

Create empty `engine/__init__.py` and `tests/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add manifest.json requirements.txt .gitignore README.md engine/__init__.py tests/
git commit -m "feat: scaffold crypto playbook plugin"
```

---

### Task 2: Config module

**Files:**
- Create: `engine/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: Global Constraints paths.
- Produces: `DEFAULT_CONFIG`, `config_path() -> Path`, `data_path() -> Path`, `load_config(path: Path | None = None) -> dict`, `save_config(config: dict, path: Path | None = None) -> None`, `validate_config(config: dict) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults():
    c = load_config(tmp_path / "missing.json")
    assert c["coins"] == ["BTC/USDT", "ETH/USDT"]
    assert c["interval_minutes"] == 60
    assert c["llm"]["api_key_env"] == "OPENAI_API_KEY"
    assert c["llm"]["base_url"].startswith("https://")

def test_round_trip(tmp_path):
    p = tmp_path / "config.json"
    c = load_config(p)
    c["coins"] = ["ETH/USDT"]
    save_config(c, p)
    assert load_config(p)["coins"] == ["ETH/USDT"]

def test_validate_rejects_bad_coin_and_url():
    c = load_config(None)
    c["coins"] = ["NOT A COIN"]
    c["llm"]["base_url"] = "not-a-url"
    errors = validate_config(c)
    assert any("coin" in e for e in errors)
    assert any("base_url" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL (`engine.config` not importable).

- [ ] **Step 3: Implement `engine/config.py`**

`DEFAULT_CONFIG` shape: `{"coins": [...], "interval_minutes": 60, "llm": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY", "timeout_s": 60}}`. `load_config` reads JSON if present, deep-merges over defaults, returns a copy. `save_config` writes pretty JSON atomically (write temp + `os.replace`). `validate_config` returns human-readable errors for: empty coin list, coin not matching `^[A-Z0-9]+/[A-Z0-9]+$`, interval < 5, missing/!http(s) `base_url`, empty `model`. `config_path` / `data_path` respect `XDG_CONFIG_HOME` / `XDG_DATA_HOME` with the defaults from Global Constraints.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/config.py tests/test_config.py
git commit -m "feat: config load/save and validation"
```

---

### Task 3: Candle model and indicators

**Files:**
- Create: `engine/models.py`, `engine/indicators.py`, `tests/test_indicators.py`

**Interfaces:**
- Produces: `Candle` dataclass (`timestamp: int`, `open: float`, `high: float`, `low: float`, `close: float`, `volume: float`); `rsi(closes: list[float], period: int = 14) -> float`; `macd(closes: list[float]) -> dict` with keys `line`, `signal`, `hist`; `bollinger(closes: list[float]) -> dict` with `lower`, `mid`, `upper`; `atr(candles: list[Candle], period: int = 14) -> float`; `moving_averages(closes: list[float]) -> dict` with `ema12`, `ema26`, `sma20`, `sma50`, `sma200`; `analyze_timeframe(candles: list[Candle]) -> dict` combining the above plus `rsi`, `trend` (`"bullish" | "bearish" | "flat"`), and `price`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rsi_monotonic_rise_is_100():
    assert rsi([float(i) for i in range(1, 40)]) == 100.0

def test_rsi_monotonic_fall_is_0():
    assert rsi([float(i) for i in range(40, 0, -1)]) == 0.0

def test_bollinger_bands_are_ordered():
    b = bollinger([100, 101, 99, 102, 98, 103, 97, 104, 96, 105] * 3)
    assert b["lower"] < b["mid"] < b["upper"]

def test_atr_is_nonnegative():
    candles = [Candle(i, 100 + i, 102 + i, 99 + i, 101 + i, 1) for i in range(30)]
    assert atr(candles) >= 0

def test_analyze_timeframe_keys():
    candles = [Candle(i, 100, 102, 99, 101, 1) for i in range(210)]
    a = analyze_timeframe(candles)
    for key in ("rsi", "macd", "bollinger", "atr", "moving_averages", "trend", "price"):
        assert key in a
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_indicators.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the indicators**

Wilder-smoothed RSI; EMA-based MACD (12/26/9); Bollinger 20-period, 2 standard deviations; Wilder ATR; EMA12/EMA26 and SMA20/50/200. `analyze_timeframe` sets `trend` to `"bullish"` when price > sma20 > sma50, `"bearish"` when price < sma20 < sma50, else `"flat"`. Return floats rounded to 2 decimals.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_indicators.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/models.py engine/indicators.py tests/test_indicators.py
git commit -m "feat: deterministic technical indicators"
```

---

### Task 4: Entry/exit level assembly

**Files:**
- Create: `engine/levels.py`, `tests/test_levels.py`

**Interfaces:**
- Consumes: `analyze_timeframe` from Task 3.
- Produces: `build_levels(analysis: dict[str, dict], price: float) -> dict` with `key_levels` (`support: list[float]`, `resistance: list[float]`) and `positions: list[dict]`, each position shaped `{"timeframe", "direction", "label", "entry", "tp1", "tp2", "stop", "rr", "zone"}`. Also `rr(entry, target, stop) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rr_formula():
    assert rr(63950, 64945, 63700) == round(995 / 250, 2)

def test_positions_include_daily_long_tranche_and_short():
    analysis = {
        "15m": {...}, "4h": {...}, "1D": {...},  # use analyze_timeframe fixtures
    }
    levels = build_levels(analysis, price=64053)
    daily = [p for p in levels["positions"] if p["timeframe"] == "1D"]
    assert {p["direction"] for p in daily} == {"LONG", "SHORT"}
    assert len([p for p in daily if p["direction"] == "LONG"]) == 2

def test_every_position_has_required_fields():
    levels = build_levels(sample_analysis(), 64053)
    for p in levels["positions"]:
        assert set(("timeframe", "direction", "label", "entry", "tp1", "tp2", "stop", "rr", "zone")) <= p.keys()
```

Build `sample_analysis()` from `analyze_timeframe` on synthetic candles in the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_levels.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `engine/levels.py`**

Derive candidate levels from each timeframe's Bollinger bands, EMA/SMA values, and price: support = values below price sorted descending; resistance = values above price sorted ascending; deduplicate rounded to whole dollars, keep nearest 5. Build positions per timeframe from these levels using the sample playbook's logic: intraday bounce LONG near support / fade SHORT near resistance; short-term oversold LONG / sell-rally SHORT; long-term confirmed LONG, value-tranche LONG, and trend SHORT. Entry/TP/stop are chosen from the nearest support/resistance values so every number traces to the payload. `rr` = `abs(tp1 - entry) / abs(entry - stop)`, rounded to 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_levels.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/levels.py tests/test_levels.py
git commit -m "feat: assemble entry/exit map and R:R"
```

---

### Task 5: Data fetching with fallback

**Files:**
- Create: `engine/data.py`, `tests/test_data.py`

**Interfaces:**
- Consumes: `Candle` from Task 3.
- Produces: `fetch_candles(symbol: str, timeframe: str, limit: int = 200, cache_dir: Path | None = None) -> list[Candle]`; `fetch_quotes(symbol: str) -> list[dict]`; `TIMEFRAMES = ("15m", "4h", "1D")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_binance_parses_klines(monkeypatch, tmp_path):
    rows = [[1, "100", "102", "99", "101", "10", 1, 1, "0", 0, 0, "0"]]
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: rows)
    candles = data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)
    assert candles[0] == Candle(1, 100.0, 102.0, 99.0, 101.0, 10.0)

def test_binance_failure_falls_back_to_yfinance(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: [Candle(1, 1, 2, 0.5, 1.5, 1)])
    assert data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)[0].close == 1.5

def test_cached_candles_used_when_both_sources_fail(monkeypatch, tmp_path):
    cache = tmp_path / "BTC_USDT_15m.json"
    cache.write_text('[{"timestamp":1,"open":1,"high":2,"low":0.5,"close":1.5,"volume":1}]')
    monkeypatch.setattr(data, "_binance_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(data, "_yfinance_candles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert data.fetch_candles("BTC/USDT", "15m", cache_dir=tmp_path)[0].close == 1.5

def test_fetch_quotes_best_effort(monkeypatch):
    monkeypatch.setattr(data, "_quote_sources", lambda s: [("Binance", 64000.0, -2.1)])
    assert data.fetch_quotes("BTC/USDT")[0]["source"] == "Binance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `engine/data.py`**

`_binance_get(symbol, timeframe, limit)` requests `https://api.binance.com/api/v3/klines` with `symbol` normalized (`BTC/USDT` → `BTCUSDT`), interval mapped (`15m`, `4h`, `1d`) and returns parsed rows; raises `RuntimeError` on HTTP/non-200/JSON errors. `_yfinance_candles` uses `yfinance.download` with `BTC-USD`-style tickers. `fetch_candles` tries Binance → yfinance → cache, persisting successful results to `cache_dir/<SYMBOL>_<TF>.json`; if all fail, raise `DataUnavailable`. `fetch_quotes` iterates best-effort Binance/CoinGecko/Coinbase quote functions via `_quote_sources`, swallowing individual failures and returning a list of `{"source", "price", "change_pct"}` dicts (empty list is acceptable). `_quote_sources` is a separate injectable function so the test can patch it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_data.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/data.py tests/test_data.py
git commit -m "feat: candle fetching with fallback and cache"
```

---

### Task 6: Report schema, markdown rendering, and seed samples

**Files:**
- Create: `engine/report.py`, `samples/BTC_USDT_PLAYBOOK_2026-11-16.md`, `samples/BTC_USDT_PREDICTION-2026-11-16.md`, `tests/test_report.py`

**Interfaces:**
- Consumes: nothing external.
- Produces: `new_report(coin: str, snapshot: dict, analysis: dict, levels: dict) -> dict`; `render_markdown(report: dict) -> str`; `save_report(data_dir: Path, report: dict) -> Path`; `list_reports(data_dir: Path, coin: str | None = None) -> list[dict]`; `load_report(data_dir: Path, report_id: str) -> dict`; `seed_samples(data_dir: Path) -> None`.

Report keys: `schema_version`, `id`, `coin`, `generated_at`, `sample`, `snapshot`, `indicators`, `levels`, `prediction` (`{"available": bool, ...}`), `risk_rules`, `markdown`, `source_markdown` (optional).

- [ ] **Step 1: Write the failing tests**

```python
def test_new_report_shape():
    r = new_report("BTC/USDT", {"sources": []}, {}, {"positions": [], "key_levels": {}})
    assert r["coin"] == "BTC/USDT"
    assert r["schema_version"] == 1
    assert r["prediction"]["available"] is False
    assert "id" in r and "generated_at" in r

def test_save_list_load_round_trip(tmp_path):
    r = new_report("BTC/USDT", {}, {}, {})
    p = save_report(tmp_path, r)
    assert p.exists()
    assert load_report(tmp_path, r["id"])["id"] == r["id"]
    assert list_reports(tmp_path, "BTC/USDT")[0]["id"] == r["id"]

def test_markdown_has_required_sections():
    r = new_report("BTC/USDT", {}, {}, {})
    md = render_markdown(r)
    for heading in ("Market snapshot", "Indicator dashboard", "ENTRY & EXIT", "Prediction", "Risk rules"):
        assert heading.lower() in md.lower()

def test_seed_samples_only_when_empty(tmp_path):
    seed_samples(tmp_path)
    assert len(list_reports(tmp_path)) == 2
    assert all(r["sample"] for r in list_reports(tmp_path))
    seed_samples(tmp_path)
    assert len(list_reports(tmp_path)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the reports**

Copy the two provided markdown files verbatim into `samples/`. `new_report` builds the dict with id `f"{coin.replace('/','-')}-{utc_timestamp}"`, `generated_at` UTC ISO-8601, `sample: False`. `render_markdown` produces headings matching the test and renders tables from `levels["positions"]` and `prediction["scenarios"]`; if `source_markdown` is set, return it verbatim (seeded samples). `save_report` writes `data_dir/reports/<id>.json` and `<id>.md` atomically. `list_reports` sorts by `generated_at` descending. `seed_samples` creates two reports with ids `sample-playbook-20261116` and `sample-prediction-20261116`, `sample: True`, `coin: "BTC/USDT"`, `generated_at` in 2026-11-16, `source_markdown` set to the sample file contents; it is a no-op when reports already exist.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/report.py samples/ tests/test_report.py
git commit -m "feat: report schema, markdown, and seeded samples"
```

---

### Task 7: LLM call and grounded-output validation

**Files:**
- Create: `engine/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: config `llm` block from Task 2.
- Produces: `LLMUnavailable(Exception)`; `build_prompt(payload: dict) -> str`; `call_llm(llm_config: dict, prompt: str) -> dict`; `allowed_levels(payload: dict) -> list[float]`; `validate_prediction(prediction: dict, allowed: list[float]) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_call_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")

def test_call_llm_parses_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(llm, "_chat_completion", lambda *a, **k: '{"highest_conviction": {"text": "x", "confidence": 0.6}}')
    assert call_llm({"api_key_env": "OPENAI_API_KEY"}, "prompt")["highest_conviction"]["confidence"] == 0.6

def test_validator_rejects_unknown_price():
    p = {"scenarios": [{"label": "Bounce 64,945", "low": 64945, "high": 65200, "probability": 45}]}
    errors = validate_prediction(p, [64945.0, 63905.0])
    assert any("65200" in e or "price" in e for e in errors)

def test_validator_rejects_bad_probabilities_and_confidence():
    p = {"scenarios": [{"low": 100, "high": 200, "probability": 45}], "highest_conviction": {"confidence": 1.5}}
    errors = validate_prediction(p, [100.0, 200.0])
    assert any("probabilit" in e for e in errors)
    assert any("confidence" in e for e in errors)

def test_validator_accepts_valid():
    p = {"scenarios": [{"low": 100, "high": 200, "probability": 60}, {"low": 50, "high": 100, "probability": 40}],
         "highest_conviction": {"text": "x", "confidence": 0.6}}
    assert validate_prediction(p, [100.0, 200.0, 50.0]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_llm.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `engine/llm.py`**

`build_prompt` serializes the payload (indicators, levels, key_levels, quotes) as JSON and instructs: return JSON only with keys `highest_conviction {text, confidence}`, `scenarios` grouped by horizon (`"24-48h"`, `"1-2w"`) where each scenario has `label`, `low`, `high`, `probability`, plus `per_timeframe`, `favored_trade`, `confirmation`, `invalidation`, `bottom_line`; every `low`/`high` must be chosen from the supplied `allowed_levels`; probabilities are subjective estimates and must sum to 100 per horizon; never claim a guaranteed win rate; include the educational-only disclaimer. `_chat_completion` POSTs to `{base_url}/chat/completions` via `requests` with the key from `os.environ[api_key_env]`, timeout and `response_format: {"type": "json_object"}`. `call_llm` raises `LLMUnavailable` when the env var is missing/empty or the HTTP call fails, and returns parsed JSON. `allowed_levels` flattens every numeric price from the payload (key levels, entries, TPs, stops, indicator bands) plus psychological round levels derived from price. `validate_prediction` reports errors for: any `low`/`high` not within 0.5% of an allowed level (compare as floats), probabilities per horizon not summing to 100, confidence outside 0..1, presence of "75%" or "guaranteed".

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_llm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/llm.py tests/test_llm.py
git commit -m "feat: LLM call and grounded prediction validation"
```

---

### Task 8: Generation pipeline with serialized runs

**Files:**
- Create: `engine/generate.py`, `tests/test_generate.py`

**Interfaces:**
- Consumes: `fetch_candles`, `fetch_quotes` (Task 5); `analyze_timeframe` (Task 3); `build_levels` (Task 4); `new_report`, `save_report` (Task 6); `call_llm`, `validate_prediction`, `allowed_levels`, `LLMUnavailable` (Task 7).
- Produces: `generate_report(coin: str, config: dict, data_dir: Path) -> dict`; module-level thread `Lock` guarding generation; returns `{"report": dict, "error": str | None}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_pipeline_produces_prediction(monkeypatch, tmp_path):
    # monkeypatch data.fetch_candles, data.fetch_quotes, llm.call_llm with valid stubs
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is True

def test_llm_failure_still_saves_report(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (_ for _ in ()).throw(LLMUnavailable()))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [Candle(1, 100, 101, 99, 100, 1)] * 210)
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["prediction"]["available"] is False
    assert list_reports(tmp_path)[0]["id"] == result["report"]["id"]

def test_fetch_failure_uses_cache(monkeypatch, tmp_path):
    cache = tmp_path / "candles" / "BTC_USDT_15m.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps([{"timestamp": 1, "open": 100, "high": 101,
                                   "low": 99, "close": 100, "volume": 1}] * 210))
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: (_ for _ in ()).throw(DataUnavailable()))
    result = generate_report("BTC/USDT", load_config(None), tmp_path)
    assert result["report"]["indicators"]["15m"]["price"] == 100

def test_generate_is_serialized(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "fetch_candles", lambda *a, **k: [Candle(1, 100, 101, 99, 100, 1)] * 210)
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (time.sleep(0.05), valid_prediction())[1])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: generate_report("BTC/USDT", load_config(None), tmp_path), range(4)))
    ids = [r["report"]["id"] for r in results]
    assert len(ids) == len(set(ids)) == 4
```

Imports for this test file: `json`, `time`, `concurrent.futures`, plus the engine modules under test. Define a `valid_prediction()` helper in the test file returning the shape accepted by `validate_prediction` from Task 7.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_generate.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `engine/generate.py`**

Wrap the whole generation in a module-level `threading.Lock` (or equivalent) so concurrent callers serialize. For each timeframe in `TIMEFRAMES`, fetch candles and run `analyze_timeframe`; fetch quotes; call `build_levels`; assemble the payload; call `build_prompt` + `call_llm` + `validate_prediction`; on any LLM error or invalid output, log a short reason (never the key) and set `prediction = {"available": False, "reason": "..."}`; build the report with `new_report`, render markdown into `report["markdown"]`, and `save_report`. `deps` allows tests to inject stubs for `fetch_candles`, `fetch_quotes`, `call_llm`. Return `{"report": report, "error": None}` or `{"report": report, "error": reason}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_generate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/generate.py tests/test_generate.py
git commit -m "feat: serialized report generation pipeline"
```

---

### Task 9: Daemon, scheduler, and CLI helper

**Files:**
- Create: `engine/daemon.py`, `engine/cli.py`, `bin/playbookd`, `bin/playbook`, `tests/test_daemon.py`

**Interfaces:**
- Consumes: config (Task 2), reports (Task 6), generation (Task 8).
- Produces: HTTP endpoints on `127.0.0.1:8099`: `GET /api/status`, `GET /api/coins`, `GET /api/latest?coin=`, `GET /api/reports?coin=`, `GET /api/report?id=`, `POST /api/regenerate` (`{"coin": "..."}`), `GET /api/config`, `POST /api/config` (JSON body), `GET /api/health`. CLI commands: `latest [coin]`, `reports [coin]`, `report <id>`, `status`, `coins`, `regenerate <coin>`, `config`, `set-config <json>`, `export [dest_dir]`, `delete-reports`; all print compact JSON to stdout. Add `GET /api/export` and `POST /api/delete-reports` endpoints backing the last two.

- [ ] **Step 1: Write the failing tests**

```python
def test_latest_with_empty_store_returns_placeholder(tmp_path):
    # start server with empty data dir
    assert client.get("/api/latest?coin=BTC%2FUSDT").json() == {"available": False}

def test_regenerate_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon.generate, "generate_report", fake_generate)
    r = client.post("/api/regenerate", json={"coin": "BTC/USDT"})
    assert r.json()["started"] is True

def test_config_endpoint_round_trip(tmp_path):
    c = client.get("/api/config").json()
    c["interval_minutes"] = 15
    assert client.post("/api/config", json=c).json()["interval_minutes"] == 15

def test_cli_helper_prints_json(tmp_path):
    out = subprocess.check_output([str(BIN / "playbook"), "coins", "-addr", addr], text=True)
    assert json.loads(out) == ["BTC/USDT", "ETH/USDT"]
```

Use a pytest fixture that starts `daemon.build_server(config, data_dir)` on port 0 in a daemon thread and yields a `urllib`-based `client` with `.get/.post` returning an object with `.json()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_daemon.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the daemon and CLI**

`build_server(config, data_dir) -> ThreadingHTTPServer` with a `BaseHTTPRequestHandler` subclass routing the endpoints; JSON in/out; `POST /api/config` validates with `validate_config` and atomically saves; `POST /api/regenerate` launches generation in a background thread and returns immediately; `GET /api/export?dest=<dir>` copies the reports directory to `dest` (default `~/Documents/crypto-playbook-export`) and returns the path; `POST /api/delete-reports` removes report files (not samples) and returns the count. `main()` seeds samples, loads config, starts a scheduler thread that regenerates all coins every `interval_minutes` (and once at startup when `LLM_KEY_ENV` is present), then serves on loopback. `engine/cli.py` implements the commands as HTTP calls to `-addr` (default `127.0.0.1:8099`) and prints compact JSON. `bin/playbookd` and `bin/playbook` are executable shell wrappers that resolve their own directory, set `PYTHONPATH` to the plugin root, and exec `python3 -m engine.daemon` / `python3 -m engine.cli "$@"`; they are gitignored but created by `install.sh` (Task 12). For tests, create them in a temp `BIN` fixture.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_daemon.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/daemon.py engine/cli.py tests/test_daemon.py
git commit -m "feat: loopback daemon, scheduler, and CLI helper"
```

---

### Task 10: QML plugin shell, theme derivation, and sidebar

**Files:**
- Create: `Service.qml`, `BarWidget.qml`, `App.qml`, `components/Sidebar.qml`, `tests/test_qml_contract.py`

**Interfaces:**
- Consumes: `bin/playbookd`, `bin/playbook` (Task 9); daemon JSON commands.
- Produces: plugin shell with `shell.toggle("<id>", "{}")` on bar click, daemon lifecycle, theme-derived colors, sidebar navigation.

- [ ] **Step 1: Write the failing contract tests**

```python
def test_no_literal_hex_colors_in_qml():
    for p in QML_FILES:
        text = p.read_text()
        assert not re.search(r"#[0-9a-fA-F]{6}\b", text), p

def test_service_owns_daemon():
    text = (ROOT / "Service.qml").read_text()
    assert "bin/playbookd" in text
    assert "onExited" in text and "reap" in text

def test_bar_widget_toggles_shell():
    text = (ROOT / "BarWidget.qml").read_text()
    assert 'shell.toggle("windong.cryptoplaybook"' in text
    assert "windowTitle" not in text  # this is a bar widget, not a standalone window

def test_app_derives_theme_tokens():
    text = (ROOT / "App.qml").read_text()
    for token in ("Color.foreground", "Color.background", "Color.accent", "Color.urgent", "Style.normalBorderColor", "Style.font.family"):
        assert token in text
```

`QML_FILES` = all `*.qml` under the repo root.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_qml_contract.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the shell QML**

Model each file on its Omabudget counterpart. `Service.qml`: probe `bin/playbookd` + `bin/playbook` executables, start/restart with backoff, reap the process group on destruction, expose `built` and `running`. `BarWidget.qml`: `moduleName: "windong.cryptoplaybook"`, `setting("addr", "127.0.0.1:8099")`, a `Process` calling `playbook latest -json -addr ...` on a timer, a compact figure (price + bias) with a dash placeholder when unavailable, and `BarIconButton` whose click calls `bar.shell.toggle("windong.cryptoplaybook", "{}")`. `App.qml`: `property var shell/manifest/service`, `opened`, `open()`, `close()`, theme tokens derived from `Color.*`/`Style.*`, a centered `Panel` window, a `Process`-based `query()` helper (argv array, no shell) and `run()` mutation helper mirroring Omabudget's queues; `property var snap` refreshed from `playbook latest`. `components/Sidebar.qml`: brand label, numbered nav rows (Dashboard, Playbooks, Predictions, Coins, History, Settings, Data & Privacy), active row highlighted with `accent`, footer "Local. Private. Yours.", and a `Quick regenerate` button bound to `run(["regenerate", coin])`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_qml_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Service.qml BarWidget.qml App.qml components/ tests/test_qml_contract.py
git commit -m "feat: plugin shell, theme tokens, and sidebar"
```

---

### Task 11: Dashboard and sidebar views

**Files:**
- Create: `views/Dashboard.qml`, `views/Playbooks.qml`, `views/Predictions.qml`, `views/History.qml`, `views/Settings.qml`, `views/DataPrivacy.qml`, `components/TitledCard.qml`, `components/MetricCard.qml`, `tests/test_views_contract.py`

**Interfaces:**
- Consumes: `app.snap`, `app.query()`, `app.run()` from Task 10; daemon commands from Task 9.
- Produces: all sidebar views rendering report data and settings controls.

- [ ] **Step 1: Write the failing view contract tests**

```python
def test_dashboard_renders_core_cards():
    text = (ROOT / "views/Dashboard.qml").read_text()
    for label in ("ENTRY & EXIT", "INDICATOR DASHBOARD", "PREDICTION", "RECENT REPORTS"):
        assert label in text

def test_settings_exposes_coin_interval_model():
    text = (ROOT / "views/Settings.qml").read_text()
    for key in ("coins", "interval_minutes", "model"):
        assert key in text

def test_data_privacy_has_export_and_delete():
    text = (ROOT / "views/DataPrivacy.qml").read_text()
    assert "export" in text.lower() and "delete" in text.lower()

def test_onboarding_state_exists():
    text = (ROOT / "App.qml").read_text()
    assert "no key" in text.lower() or "onboarding" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_views_contract.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the views**

Follow the sample layout: `Dashboard.qml` shows a header with coin tabs, four `MetricCard`s (live price + 24h %, bias, confidence, best R:R), an alert banner using `Color.urgent`, then a card grid: `ENTRY / EXIT MAP` table from `snap.levels.positions`, `PREDICTION SCENARIOS` from `snap.prediction.scenarios`, `INDICATOR DASHBOARD` from `snap.indicators`, `RECENT REPORTS` from `playbook reports`. `Playbooks.qml` / `Predictions.qml` render the selected report's sections; `History.qml` lists all reports with a "View" action. `Settings.qml` edits `coins` (comma-separated, validated), `interval_minutes`, and LLM `model` via `run(["set-config", JSON])`; show a note that the key comes from env var. `DataPrivacy.qml` explains local storage and API transmission, with "Export reports" (`playbook export`, implemented as a copy to a chosen path via the CLI if present, otherwise a documented manual copy) and "Delete reports" (`playbook delete-reports`) actions. All colors from the theme-derived properties in `App.qml`; no literals. Add a clear onboarding state in `App.qml` when `snap.available === false` and status says no key.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_views_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add views/ components/ tests/test_views_contract.py
git commit -m "feat: dashboard and sidebar views"
```

---

### Task 12: Install script, validation, and GitHub push

**Files:**
- Create: `install.sh`, `UNINSTALL.md` (optional), modify `README.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a validated plugin installed under `~/.config/omarchy/plugins/windong.cryptoplaybook/` and pushed to GitHub.

- [ ] **Step 1: Write the install script and docs**

`install.sh`: resolve repo root; create plugin dir; copy manifest, QML, `views/`, `components/`, `engine/`, `samples/`; generate executable `bin/playbookd` and `bin/playbook` wrappers (they resolve their own dir and exec `<plugin-dir>/.venv/bin/python -m engine.daemon` / `engine.cli`, with the plugin dir on `PYTHONPATH`); create `.venv` with `python3 -m venv <plugin-dir>/.venv` and install dependencies with `<plugin-dir>/.venv/bin/pip install -r requirements.txt`; print next steps (`omarchy-shell shell rescanPlugins`, set env var, enable plugin). Update `README.md` with install, configure, uninstall, and the educational disclaimer.

- [ ] **Step 2: Validate the plugin folder**

```bash
PLUGIN_DIR="$HOME/.config/omarchy/plugins/windong.cryptoplaybook"
./install.sh
omarchy plugin validate "$PLUGIN_DIR"
qmllint -I "$OMARCHY_PATH/shell" "$PLUGIN_DIR"/*.qml "$PLUGIN_DIR"/views/*.qml "$PLUGIN_DIR"/components/*.qml
```

Expected: both commands exit 0. If `qmllint` is not installed, record that and rely on the Qt Creator/QML tooling check at runtime; do not skip `omarchy plugin validate`.

- [ ] **Step 3: Manual smoke test on the desktop**

Enable the plugin, confirm the bar widget appears, click it, confirm the centered dashboard opens with the sidebar and seeded sample reports, switch Omarchy themes and confirm the colors follow, click Regenerate with a key set and confirm a new report appears in History, then confirm Escape closes the panel. Record any failures to fix before push.

- [ ] **Step 4: Push to GitHub**

```bash
git remote add origin <USER_GITHUB_REPO_URL>
git push -u origin "$(git branch --show-current)"
```

Ask the user for the repo URL if not supplied; do not create a repo without confirmation.

- [ ] **Step 5: Commit the install/docs changes**

```bash
git add install.sh README.md
git commit -m "feat: install script and documentation"
```
