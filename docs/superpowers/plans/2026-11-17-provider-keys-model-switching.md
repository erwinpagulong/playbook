# Provider Keys and Model Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user store LLM provider keys in the app, switch the active model from a sidebar screen, and automatically fall back to a second configured provider when the primary runs out of quota or fails.

**Architecture:** Add a private keys file and provider presets to the Python engine. The daemon exposes key management over loopback; the CLI helper and QML views use it. The generation pipeline resolves a key per call, retries with a configured fallback provider only on provider failures (quota/auth/network/5xx), and records which model answered in the report. The env-var path stays as a backward-compatible fallback.

**Tech Stack:** Python 3.11+ (stdlib, requests), QML/Quickshell (Quattro), pytest, existing engine modules.

**Spec:** `docs/superpowers/specs/2026-11-17-provider-keys-and-model-switching-design.md`

## Global Constraints

- Keys file: `$XDG_DATA_HOME/crypto-playbook/keys.json`, default `~/.local/share/crypto-playbook/keys.json`, mode `600`. Never in the repo, `config.json`, reports, logs, `/api/config`, `/api/status`, or full UI text.
- Config gains `llm.provider` (active id) and `llm.fallback_provider` (nullable id); existing `llm.base_url`, `model`, `api_key_env`, `timeout_s` remain.
- Key resolution per call: key from keys file for that provider → env var named by `llm.api_key_env` → `LLMUnavailable`.
- Fallback applies to provider failures only: HTTP 401/402/403/429, 5xx, transport/timeouts, or an `insufficient_quota` / `rate_limit` marker. Never on invalid/ungrounded output.
- Report gains `prediction.provider`, `prediction.model`, `prediction.fallback_used`.
- Plugin ID `windong.cryptoplaybook`; kinds unchanged. No literal hex colors in QML; all colors from `Color.*` / `Style.*` via app properties.
- Tests offline; no real network; no API key available in this environment — do not attempt real LLM calls.
- `omarchy plugin validate` and `qmllint` (if available) must pass.
- Existing env-var setup must keep working.

## Review Focus

- **Key leakage** — a key must never appear in config responses, status, reports, or logs; masked hints only. → Task 1 `test_key_hint_is_masked`; Task 5 `test_providers_response_has_no_full_key`.
- **Quota exhaustion** — a 429/402/insufficient_quota error must trigger the fallback and the report must record the fallback provider. → Task 4 `test_quota_failure_uses_fallback`.
- **Invalid output must not fall back** — a grounded/schema failure stays a deterministic-only report. → Task 4 `test_invalid_output_does_not_fall_back`.
- **Switch takes effect immediately** — changing active provider in config changes the next generation's endpoint without re-login. → Task 4 `test_active_provider_selects_endpoint`.
- **Legacy env-var install** — with no keys file, the env var still authorizes the call. → Task 3 `test_env_fallback_when_no_keys_file`.

---

### Task 1: Private key storage

**Files:**
- Create: `engine/keys.py`, `tests/test_keys.py`

**Interfaces:**
- Consumes: `engine.config.data_path()`.
- Produces: `keys_path(path: Path | None = None) -> Path`; `load_keys(path: Path | None = None) -> dict` shaped `{"providers": {provider_id: key}}`; `set_key(provider: str, key: str, path: Path | None = None) -> None`; `clear_key(provider: str, path: Path | None = None) -> None`; `mask(key: str) -> str`; `key_for(provider: str, config: dict, path: Path | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_keys_file_is_mode_600_and_round_trips(tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "sk-1234567890abcdef", p)
    assert p.stat().st_mode & 0o777 == 0o600
    assert load_keys(p) == {"providers": {"openrouter": "sk-1234567890abcdef"}}

def test_key_hint_is_masked():
    assert mask("sk-1234567890abcdef") == "sk-…cdef"
    assert mask("short") == "••••short"

def test_clear_key_removes_only_that_provider(tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "a", p); set_key("deepseek", "b", p)
    clear_key("openrouter", p)
    assert load_keys(p)["providers"] == {"deepseek": "b"}

def test_key_for_prefers_file_then_env(monkeypatch, tmp_path):
    p = tmp_path / "keys.json"
    set_key("openrouter", "file-key", p)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = {"llm": {"api_key_env": "OPENAI_API_KEY"}}
    assert key_for("openrouter", cfg, p) == "file-key"
    assert key_for("deepseek", cfg, p) == "env-key"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert key_for("deepseek", cfg, p) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_keys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.keys'`.

- [ ] **Step 3: Implement `engine/keys.py`**

Atomic writes (temp file in target dir + `os.replace`) and `os.chmod(path, 0o600)` after every write, including creation. `mask` returns `"sk-…" + last4` when the key starts with `sk-`, else `"••••" + key`; for keys shorter than 5 chars, return `"••••" + key`. `key_for` returns the stored key for the provider if non-empty, else `os.environ.get(config["llm"]["api_key_env"], "")`, else `""`. Missing/corrupt file behaves as empty. No logging of key values.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_keys.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/keys.py tests/test_keys.py
git commit -m "feat: private provider key storage"
```

---

### Task 2: Provider presets and config selection

**Files:**
- Create: `engine/providers.py`, `tests/test_providers.py`
- Modify: `engine/config.py` (`DEFAULT_CONFIG`, `validate_config`)

**Interfaces:**
- Consumes: `engine.keys.key_for`, `mask`, `load_keys`.
- Produces: `PRESETS: dict[str, dict]`; `provider_llm_config(provider: str, config: dict) -> dict`; `provider_list(config: dict, keys_path: Path | None = None) -> list[dict]`; `is_valid_provider(provider: str | None) -> bool`.

`PRESETS` entries carry `name`, `base_url`, `model`, `api_key_env`. Required ids: `openai`, `openrouter`, `deepseek`, `groq`, `custom`. Use documented public OpenAI-compatible endpoints and plausible default models; if a default model cannot be verified, use the provider's documented generic model id and leave it editable.

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults_and_merging():
    cfg = load_config(None)
    assert cfg["llm"]["provider"] == "openai"
    assert cfg["llm"]["fallback_provider"] is None
    assert provider_llm_config("deepseek", cfg)["base_url"] == PRESETS["deepseek"]["base_url"]
    cfg["llm"]["provider"] = "deepseek"
    cfg["llm"]["model"] = "my-model"
    assert provider_llm_config("deepseek", cfg)["model"] == "my-model"
    assert provider_llm_config("openrouter", cfg)["model"] == PRESETS["openrouter"]["model"]

def test_provider_list_has_no_full_key(tmp_path, monkeypatch):
    p = tmp_path / "keys.json"
    set_key("openrouter", "sk-secret-value-1234", p)
    cfg = load_config(None); cfg["llm"]["provider"] = "openrouter"
    rows = provider_list(cfg, p)
    row = next(r for r in rows if r["id"] == "openrouter")
    assert row["active"] is True and row["key_set"] is True
    assert row["key_hint"] == "sk-…1234"
    assert "sk-secret-value-1234" not in json.dumps(rows)

def test_validation_rejects_bad_provider_and_self_fallback():
    cfg = load_config(None)
    cfg["llm"]["provider"] = "nope"
    assert any("provider" in e for e in validate_config(cfg))
    cfg["llm"]["provider"] = "openai"; cfg["llm"]["fallback_provider"] = "openai"
    assert any("fallback" in e for e in validate_config(cfg))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_providers.py -v`
Expected: FAIL (`engine.providers` missing / config keys missing).

- [ ] **Step 3: Implement presets and config changes**

`provider_llm_config` starts from the preset dict and always overlays `api_key_env` / `timeout_s` from `config["llm"]`. It overlays config `base_url` / `model` **only when `provider == config["llm"]["provider"]`** (the active provider), so selecting a different provider uses that preset's endpoint/model while user edits to the active one are honored. Return a fresh dict. `provider_list` returns one row per preset with `id`, `name`, `base_url`, `model`, `active`, `fallback`, `key_set`, `key_hint`. `is_valid_provider` checks membership in `PRESETS`. Add `provider: "openai"` and `fallback_provider: None` to `DEFAULT_CONFIG["llm"]`; extend `validate_config` to reject unknown provider/fallback ids and fallback equal to active. Keep all existing validation rules.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_providers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/providers.py engine/config.py tests/test_providers.py
git commit -m "feat: provider presets and active/fallback config"
```

---

### Task 3: LLM accepts an explicit key and classifies provider failures

**Files:**
- Modify: `engine/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `LLMProviderError(LLMUnavailable)` with attributes `status: int | None`, `marker: str | None`; `is_provider_failure(exc: BaseException) -> bool`; `_chat_completion(llm_config: dict, prompt: str, api_key: str | None = None) -> str`; `call_llm(llm_config: dict, prompt: str, api_key: str | None = None) -> dict`. Existing `build_prompt`, `allowed_levels`, `validate_prediction`, retry behavior unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_explicit_key_is_used(monkeypatch):
    seen = {}
    def fake_post(url, json, headers, timeout):
        seen["auth"] = headers["Authorization"]
        return FakeResponse({"choices": [{"message": {"content": "{}"}}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.call_llm({"base_url": "https://x.test/v1", "model": "m", "api_key_env": "NOPE"}, "p", api_key="sk-explicit")
    assert seen["auth"] == "Bearer sk-explicit"

def test_env_fallback_when_no_keys_file(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse({"choices": [{"message": {"content": "{}"}}]}))
    assert isinstance(llm.call_llm({"api_key_env": "OPENAI_API_KEY"}, "p"), dict)

def test_quota_error_is_provider_failure(monkeypatch):
    response = FakeErrorResponse(429, '{"error":{"code":"insufficient_quota"}}')
    def fake_post(*a, **k): raise requests.HTTPError("429", response=response)
    monkeypatch.setattr(llm.requests, "post", fake_post)
    with pytest.raises(llm.LLMProviderError) as ei:
        llm.call_llm({"api_key_env": "K"}, "p", api_key="v")
    assert ei.value.status == 429 and ei.value.marker == "insufficient_quota"
    assert llm.is_provider_failure(ei.value) is True

def test_invalid_json_is_not_provider_failure(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse({"choices": [{"message": {"content": "not json"}}]}))
    with pytest.raises(llm.LLMUnavailable) as ei:
        llm.call_llm({"api_key_env": "K"}, "p", api_key="v")
    assert llm.is_provider_failure(ei.value) is False
```

Define tiny `FakeResponse` / `FakeErrorResponse` helpers in the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_llm.py -v`
Expected: FAIL (`LLMProviderError` / `is_provider_failure` / `api_key` parameter missing).

- [ ] **Step 3: Implement the refactor**

`api_key` wins when supplied; otherwise read `os.environ[api_key_env]` as today; missing/empty still raises `LLMUnavailable`. In `_chat_completion`, catch `requests.HTTPError` and raise `LLMProviderError` carrying `status` and a marker parsed from the response body (`insufficient_quota` / `rate_limit` when present); transport/timeout errors raise `LLMProviderError(status=None)`. `call_llm` must let `LLMProviderError` propagate (it subclasses `LLMUnavailable`) and keep bounded retries for transient errors. `is_provider_failure` returns True for `LLMProviderError` unless it came from invalid output; plain `LLMUnavailable` and JSON/validation errors return False. No key value in any exception text.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS; also run `/tmp/opencode/venv-playbook/bin/python -m pytest -q` once.

- [ ] **Step 5: Commit**

```bash
git add engine/llm.py tests/test_llm.py
git commit -m "feat: explicit LLM key and provider-failure classification"
```

---

### Task 4: Generation uses active provider and falls back

**Files:**
- Modify: `engine/generate.py`, `tests/test_generate.py`

**Interfaces:**
- Consumes: `engine.providers.provider_llm_config`, `engine.keys.key_for`, `engine.llm.call_llm`, `LLMProviderError`, `is_provider_failure`.
- Produces: `_predict(config: dict, payload: dict, keys_path: Path | None = None) -> tuple[dict | None, str | None, dict | None]` where the third value is `{"provider": str, "model": str, "fallback_used": bool}` or `None`. `generate_report` unchanged (`(coin, config, data_dir) -> {"report", "error"}`); its report's `prediction` dict gains the three metadata fields.

- [ ] **Step 1: Write the failing tests**

```python
def test_quota_failure_uses_fallback(monkeypatch, tmp_path):
    calls = []
    def fake_call(cfg, prompt, api_key=None):
        calls.append((cfg["base_url"], api_key))
        if len(calls) == 1: raise llm.LLMProviderError("429", status=429, marker="insufficient_quota")
        return valid_prediction()
    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None)
    cfg["llm"]["provider"] = "openrouter"; cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert len(calls) == 2
    assert result["report"]["prediction"]["fallback_used"] is True
    assert result["report"]["prediction"]["provider"] == "deepseek"

def test_invalid_output_does_not_fall_back(monkeypatch, tmp_path):
    calls = []
    def fake_call(cfg, prompt, api_key=None):
        calls.append(1)
        return {"scenarios": [{"low": 99999, "high": 99999, "probability": 100}]}
    monkeypatch.setattr(llm, "call_llm", fake_call)
    cfg = load_config(None); cfg["llm"]["fallback_provider"] = "deepseek"
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert len(calls) == 1
    assert result["report"]["prediction"]["available"] is False

def test_active_provider_selects_endpoint(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(llm, "call_llm", lambda cfg, p, api_key=None: (seen.append(cfg["base_url"]), valid_prediction())[1])
    cfg = load_config(None); cfg["llm"]["provider"] = "deepseek"
    generate_report("BTC/USDT", cfg, tmp_path)
    assert seen == [providers.PRESETS["deepseek"]["base_url"]]

def test_no_fallback_configured_stays_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: (_ for _ in ()).throw(llm.LLMProviderError("429", status=429)))
    cfg = load_config(None)
    result = generate_report("BTC/USDT", cfg, tmp_path)
    assert result["report"]["prediction"]["available"] is False
```

Reuse the `valid_prediction()` helper from Task 8 of the first plan (it must pass `validate_prediction`).

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_generate.py -v`
Expected: FAIL (`_predict` signature / metadata fields missing).

- [ ] **Step 3: Implement provider selection and fallback**

In `_predict`: resolve the active provider via `config["llm"]["provider"]`, build its llm config with `provider_llm_config`, resolve the key with `key_for(provider, config, keys_path)`, and call `llm.call_llm(cfg, prompt, api_key=key)`. On `LLMProviderError` where `is_provider_failure(exc)` is True and `config["llm"]["fallback_provider"]` is set and different, repeat once with the fallback provider/key and return metadata with `fallback_used: True`. On success return `(reply, None, {"provider": id, "model": cfg["model"], "fallback_used": False/True})`. On any other failure return `(None, reason, None)` with the existing short, key-free reason. In `_generate`, merge the metadata into `report["prediction"]` for both available and unavailable cases (unavailable gets provider/model of the last attempt when known). Keep serialization, microsecond IDs, and the deterministic-only path unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_generate.py -v`, then `/tmp/opencode/venv-playbook/bin/python -m pytest -q`.
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add engine/generate.py tests/test_generate.py
git commit -m "feat: active provider selection and quota fallback"
```

---

### Task 5: Daemon endpoints and CLI commands

**Files:**
- Modify: `engine/daemon.py`, `engine/cli.py`, `tests/test_daemon.py`

**Interfaces:**
- Consumes: `engine.keys.set_key`, `clear_key`, `engine.providers.provider_list`.
- Produces: `GET /api/providers`; `POST /api/providers/key` (`{"provider","key"}`); `POST /api/providers/clear-key` (`{"provider"}`). CLI: `providers`, `set-key <provider> <key>`, `clear-key <provider>`. `/api/status` gains `provider` and `fallback_provider`; no key material anywhere.

- [ ] **Step 1: Write the failing tests**

```python
def test_set_key_then_providers_shows_mask_only(tmp_path):
    client = start_server(tmp_path)
    assert client.post("/api/providers/key", {"provider": "openrouter", "key": "sk-secret-1234"}).status == 200
    rows = client.get("/api/providers").json()
    row = next(r for r in rows if r["id"] == "openrouter")
    assert row["key_set"] is True and row["key_hint"] == "sk-…1234"
    assert "sk-secret-1234" not in json.dumps(rows)
    assert "sk-secret-1234" not in json.dumps(client.get("/api/status").json())
    assert "sk-secret-1234" not in json.dumps(client.get("/api/config").json())

def test_clear_key(tmp_path):
    client = start_server(tmp_path)
    client.post("/api/providers/key", {"provider": "openrouter", "key": "sk-secret-1234"})
    assert client.post("/api/providers/clear-key", {"provider": "openrouter"}).status == 200
    assert next(r for r in client.get("/api/providers").json() if r["id"] == "openrouter")["key_set"] is False

def test_set_key_rejects_unknown_provider(tmp_path):
    client = start_server(tmp_path)
    r = client.post("/api/providers/key", {"provider": "nope", "key": "x"})
    assert r.status == 400

def test_cli_key_commands(client_addr, tmp_path):
    out = subprocess.check_output([str(BIN/"playbook"), "set-key", "openrouter", "sk-1234", "-addr", client_addr], text=True)
    assert json.loads(out)["ok"] is True
    rows = json.loads(subprocess.check_output([str(BIN/"playbook"), "providers", "-addr", client_addr], text=True))
    assert any(r["id"] == "openrouter" for r in rows)
```

Reuse the daemon `client` / `start_server` and `BIN` fixtures from `tests/test_daemon.py`; make `start_server` accept a keys-path override via XDG env isolation.

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_daemon.py -v`
Expected: FAIL (404/command missing).

- [ ] **Step 3: Implement endpoints and CLI**

Add the three routes to `_POST_ROUTES` and `do_POST`; validate provider ids with `is_valid_provider`, reject empty keys with 400, return `{"ok": True}` on success. `GET /api/providers` returns `provider_list(config, keys_path)` (no full key). Add `provider`/`fallback_provider` to `_status_payload`. Keep JSON-for-every-verb behavior and loopback binding. Add CLI subcommands `providers`, `set-key`, `clear-key` with `-addr` support, compact JSON output, and non-zero exit on 4xx.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_daemon.py -v`, then the full suite.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/daemon.py engine/cli.py tests/test_daemon.py
git commit -m "feat: key management endpoints and CLI"
```

---

### Task 6: QML Model and API keys screens

**Files:**
- Modify: `App.qml`, `components/Sidebar.qml`, `views/Settings.qml`, `tests/test_qml_contract.py`, `tests/test_views_contract.py`
- Create: `views/Model.qml`, `views/ApiKeys.qml`

**Interfaces:**
- Consumes: `app.query`, `app.run`, `app.providers` (array from `playbook providers`), `app.cfg` (effective config), theme properties from `App.qml`.
- Produces: two new sidebar views; active/fallback selection via `set-config` (full merged config document, as Settings already does); key set/clear via `set-key` / `clear-key`.

- [ ] **Step 1: Write the failing contract tests**

```python
def test_new_views_exist_and_are_management_screens():
    app = (ROOT / "App.qml").read_text()
    assert 'id: "model"' in app and 'id: "apikeys"' in app
    block = app.split("readonly property bool needsReport:", 1)[1].split("}", 1)[0]
    assert '"model"' in block and '"apikeys"' in block

def test_api_keys_view_uses_key_commands():
    text = (ROOT / "views/ApiKeys.qml").read_text()
    assert 'set-key' in text and 'clear-key' in text and 'key_hint' in text

def test_model_view_has_active_and_fallback():
    text = (ROOT / "views/Model.qml").read_text()
    assert 'fallback_provider' in text and 'provider' in text

def test_no_full_key_literal_in_settings():
    text = (ROOT / "views/Settings.qml").read_text()
    assert "THE API KEY" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_qml_contract.py tests/test_views_contract.py -v`
Expected: FAIL (new views missing).

- [ ] **Step 3: Implement the UI**

Add `{ id: "model", label: "Model" }` and `{ id: "apikeys", label: "API keys" }` to `App.qml`'s `views` list and `viewFile()` mapping; include both in the `needsReport: false` branch. Add `property var providers: []` refreshed via `query(["providers"], cb)` alongside status/config. `views/Model.qml`: two dropdowns (active provider/model from `app.providers`, fallback with a `None` entry) that post the full merged config via `set-config`, plus a short explanation. `views/ApiKeys.qml`: provider rows showing `name`, `key_hint` and a set/missing badge, a paste field and Save/Clear buttons using `app.run(["set-key", id, key])` / `app.run(["clear-key", id])`, and a custom-endpoint row with base URL/model fields. Replace Settings' "THE API KEY" card with a short link to the API keys screen. All colors from theme-derived properties; no literal hex.

- [ ] **Step 4: Run test to verify it passes**

Run: `/tmp/opencode/venv-playbook/bin/python -m pytest tests/test_qml_contract.py tests/test_views_contract.py -v`, then full suite; run `qmllint` if available and `omarchy plugin validate` on the installed copy after re-running `install.sh`.
Expected: PASS; validation exit 0.

- [ ] **Step 5: Commit**

```bash
git add App.qml components/Sidebar.qml views/ tests/test_qml_contract.py tests/test_views_contract.py
git commit -m "feat: model picker and API keys sidebar screens"
```

---

### Task 7: Docs, reinstall, and push

**Files:**
- Modify: `README.md`, `install.sh` (only if new files need copying)

**Interfaces:**
- Consumes: all previous tasks.

- [ ] **Step 1: Update README**

Remove the instruction that a key must be exported into Quickshell's launch environment as a prerequisite; document the in-app API keys screen as the primary path and the env var as a legacy fallback. Document `llm.provider` / `llm.fallback_provider` and the new CLI commands `providers`, `set-key`, `clear-key`. Keep the educational disclaimer.

- [ ] **Step 2: Validate the installed plugin**

```bash
cd /home/windong/orca/workspaces/playbook/guillemot
./install.sh
omarchy plugin validate ~/.config/omarchy/plugins/windong.cryptoplaybook
```

Expected: install exit 0; validate exit 0. Run `qmllint` if available and report warnings honestly.

- [ ] **Step 3: Commit, then push**

Run the full suite once, then commit **before** pushing:

```bash
git add README.md install.sh
git commit -m "docs: in-app provider keys and model switching"
git push origin HEAD:install-superpowers
git push origin HEAD:main
```

Report the pushed commit SHA and remote URL. Do not create a PR (default branch already contains the work).

- [ ] **Step 4: Report**

Write a short completion report to the plan's ledger with validation and push output.

---

## Self-review notes

- Spec coverage: keys storage (T1), presets/config (T2), explicit key + failure classification (T3), fallback + metadata (T4), daemon/CLI (T5), sidebar UI (T6), docs/validation/push (T7). No gaps.
- Type consistency: `key_for(provider, config, path)`, `provider_llm_config(provider, config)`, `_predict -> (prediction, reason, meta)` and `LLMProviderError(status, marker)` use the same names in every task.
- Review Focus items are pinned in T1, T5, T4 (×2), T4, and T3 respectively.
- Proportion: the plan pins signatures, exact test assertions and file ownership; bodies are left to implementers.
