import QtQuick
import qs.Commons
import qs.Ui
import "../components"

// Model: which provider writes the prediction narrative, and who answers
// when it fails. Both dropdowns post the full merged config document via
// `playbook set-config` — the same path Settings uses — so the daemon's own
// validation is the gate. Selecting a provider fills that preset's base URL
// and model; empty preset values (the Custom endpoint before it is filled in
// on the API keys screen) are left untouched.
Item {
  id: view
  property var app: null
  readonly property bool formFocused:
    modelField.activeFocus || activeBox.popupOpen || fallbackBox.popupOpen

  readonly property var rows: app && Array.isArray(app.providers) ? app.providers : []
  readonly property var llm: app && app.cfg && app.cfg.llm ? app.cfg.llm : ({})
  readonly property string currentProviderId: llm.provider ? String(llm.provider) : ""
  readonly property string currentFallbackId: llm.fallback_provider ? String(llm.fallback_provider) : "none"
  readonly property string currentModel: llm.model ? String(llm.model) : ""

  readonly property var providerOptions: {
    var out = []
    for (var i = 0; i < view.rows.length; i++)
      out.push({ value: String(view.rows[i].id), label: String(view.rows[i].name) })
    return out
  }
  readonly property var fallbackOptions:
    [{ value: "none", label: "None" }].concat(view.providerOptions)

  function rowFor(id) {
    for (var i = 0; i < view.rows.length; i++)
      if (String(view.rows[i].id) === id) return view.rows[i]
    return null
  }

  // Merge the patch into the effective config and post the whole document —
  // the daemon validates the complete object, so sending a partial body
  // would be rejected.
  function postConfig(patch, doneText) {
    var cfg = app ? app.cfg : null
    if (!cfg) { view.app.lastError = "the config has not loaded yet"; return }
    var merged = JSON.parse(JSON.stringify(cfg))
    for (var key in patch) merged[key] = patch[key]
    if (patch.llm) merged.llm = Object.assign({}, cfg.llm || {}, patch.llm)
    view.app.run(["set-config", JSON.stringify(merged)], doneText)
  }

  function selectActive(id) {
    var row = view.rowFor(id)
    var patch = { provider: id }
    // A preset with empty values (Custom, not yet configured) must not
    // blank out the config — base_url has to stay an http(s) URL.
    if (row) {
      if (String(row.base_url || "") !== "") patch.base_url = String(row.base_url)
      if (String(row.model || "") !== "") patch.model = String(row.model)
      // Never leave the previous provider's environment variable in the
      // config: a stale name could route its key to this provider's endpoint.
      if (String(row.api_key_env || "") !== "") patch.api_key_env = String(row.api_key_env)
    }
    // The fallback must differ from the active provider; activating the
    // provider that is currently the fallback clears the fallback rather
    // than posting a config the daemon would reject.
    if (view.currentFallbackId !== "none" && view.currentFallbackId === id)
      patch.fallback_provider = null
    view.postConfig({ llm: patch }, "active provider: " + (row ? row.name : id))
  }

  function selectFallback(id) {
    var fb = id === "none" ? null : id
    if (fb !== null && fb === view.currentProviderId) {
      view.app.lastError = "the fallback must differ from the active provider"
      return
    }
    view.postConfig({ llm: { fallback_provider: fb } },
                    fb === null ? "fallback: none" : "fallback: " + fb)
  }

  function applyModel() {
    var model = modelField.text.trim()
    if (model === "") { view.app.lastError = "model must be a non-empty string"; return }
    view.postConfig({ llm: { model: model } }, "model: " + model)
  }

  function handleKey(e) {
    if (e.modifiers !== Qt.NoModifier) return false
    if (e.key === Qt.Key_R) { if (app) app.refresh(); return true }
    return false
  }

  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  onAppChanged: if (app) app.refresh()
  Component.onCompleted: if (app) app.refresh()

  component Caption: Text {
    color: view.dimmer
    font.family: view.ff
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
  }
  component Note: Text {
    color: view.dim
    font.family: view.ff
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }
  component Apply: Button {
    foreground: view.fg
    accent: view.accent
    fontFamily: view.ff
    fontSize: Style.font.caption
    bordered: true
  }

  Flickable {
    anchors.fill: parent
    contentWidth: width
    contentHeight: col.implicitHeight
    interactive: contentHeight > height
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    Column {
      id: col
      width: parent.width
      spacing: Style.space(14)

      Text {
        text: "Model"
        color: view.fg
        font.family: view.ff
        font.pixelSize: Style.font.heading
      }

      TitledCard {
        app: view.app
        width: parent.width
        title: "ACTIVE PROVIDER"
        Caption { text: "llm.provider" }
        Dropdown {
          id: activeBox
          width: parent.width
          showLabel: false
          options: view.providerOptions
          foreground: view.fg
          accent: view.accent
          fontFamily: view.ff
          onChanged: function (v) { view.selectActive(v) }
        }
        Binding { target: activeBox; property: "value"; value: view.currentProviderId }
        Note { width: parent.width; text: "The provider that writes the prediction narrative. Selecting one fills its base URL and default model (an empty Custom preset keeps the current values); both stay editable as the active provider on the API keys screen." }
      }

      TitledCard {
        app: view.app
        width: parent.width
        title: "FALLBACK PROVIDER"
        Caption { text: "llm.fallback_provider" }
        Dropdown {
          id: fallbackBox
          width: parent.width
          showLabel: false
          options: view.fallbackOptions
          foreground: view.fg
          accent: view.accent
          fontFamily: view.ff
          onChanged: function (v) { view.selectFallback(v) }
        }
        Binding { target: fallbackBox; property: "value"; value: view.currentFallbackId }
        Note { width: parent.width; text: "Answers instead of the active provider when it fails with an auth, quota, rate-limit, timeout, network or 5xx error. Must differ from the active provider. The report records which provider and model actually answered." }
      }

      TitledCard {
        app: view.app
        width: parent.width
        title: "MODEL"
        Caption { text: "llm.model" }
        TextField {
          id: modelField
          width: parent.width
          foreground: view.fg
          accent: view.accent
          font.family: view.ff
          font.pixelSize: Style.font.body
          placeholderText: "gpt-4o-mini"
          Keys.onReturnPressed: view.applyModel()
          Keys.onEnterPressed: view.applyModel()
          Keys.onEscapePressed: view.forceActiveFocus()
        }
        Binding { target: modelField; property: "text"; value: view.currentModel; when: !modelField.activeFocus }
        Apply { text: "Apply"; onClicked: view.applyModel() }
        Note { width: parent.width; text: "The model the daemon asks the active provider for. Prices and indicators stay deterministic either way." }
      }

      Note {
        width: parent.width
        text: "Playbooks generate regardless of any of this. Only the prediction narrative needs a provider; without a usable key the daemon still writes the playbook and skips the narrative."
      }
    }
  }
}
