import QtQuick
import qs.Commons
import qs.Ui
import "../components"

// Settings: the coin list, the generation interval, and the LLM model.
// Every change goes through `playbook set-config`, which validates and
// atomically replaces the whole config — so each edit merges over the
// effective config read from `playbook config` first. The provider keys and
// selection live on their own screens (API keys, Model); this one links there.
Item {
  id: view
  property var app: null
  readonly property bool formFocused: coinsField.activeFocus || intervalField.activeFocus || modelField.activeFocus

  property var cfg: null

  function reload() {
    if (!app) return
    app.query(["config"], function (data, err) {
      if (err || !data || typeof data !== "object") {
        view.app.lastError = err || "could not read the config"
        return
      }
      view.cfg = data
      if (!coinsField.activeFocus)
        coinsField.text = Array.isArray(data.coins) ? data.coins.join(", ") : ""
      if (!intervalField.activeFocus)
        intervalField.text = String(data.interval_minutes === undefined ? "" : data.interval_minutes)
      if (!modelField.activeFocus && data.llm)
        modelField.text = data.llm.provider === "custom"
          ? String(data.llm.custom_model || "")
          : String(data.llm.model || "")
    })
  }
  onAppChanged: reload()
  Connections { target: view.app; function onChanged() { view.reload() } }
  Component.onCompleted: reload()

  // Merge the patch into the effective config and post the whole document —
  // the daemon validates the complete object, so sending a partial body
  // would be rejected.
  function postConfig(patch, doneText) {
    if (!view.cfg) { view.app.lastError = "the config has not loaded yet"; return }
    var merged = JSON.parse(JSON.stringify(view.cfg))
    for (var key in patch) merged[key] = patch[key]
    if (patch.llm) merged.llm = Object.assign({}, view.cfg.llm || {}, patch.llm)
    view.app.run(["set-config", JSON.stringify(merged)], doneText)
  }

  function applyCoins() {
    var raw = coinsField.text.split(",")
    var coins = []
    var bad = []
    for (var i = 0; i < raw.length; i++) {
      var coin = raw[i].trim().toUpperCase()
      if (coin === "") continue
      if (!/^[A-Z0-9]+\/[A-Z0-9]+$/.test(coin)) { bad.push(coin); continue }
      if (coins.indexOf(coin) === -1) coins.push(coin)
    }
    if (bad.length > 0) { view.app.lastError = "invalid coin(s): " + bad.join(", ") + " — expected BASE/QUOTE like BTC/USDT"; return }
    if (coins.length === 0) { view.app.lastError = "at least one coin is required"; return }
    view.postConfig({ coins: coins }, "coins: " + coins.join(", "))
  }

  function applyInterval() {
    var n = Number(intervalField.text.trim())
    if (!isFinite(n) || Math.floor(n) !== n || n < 5) {
      view.app.lastError = "interval_minutes must be a whole number of 5 or more"
      return
    }
    view.postConfig({ interval_minutes: n }, "interval: every " + n + " minutes")
  }

  function applyModel() {
    var model = modelField.text.trim()
    if (model === "") { view.app.lastError = "model must be a non-empty string"; return }
    var patch = { model: model }
    // Custom keeps its own destination; keep it in sync while it is active.
    if (view.cfg && view.cfg.llm && view.cfg.llm.provider === "custom")
      patch.custom_model = model
    view.postConfig({ llm: patch }, "model: " + model)
  }

  function handleKey(e) {
    if (e.modifiers !== Qt.NoModifier) return false
    if (e.key === Qt.Key_R) { view.reload(); return true }
    return false
  }

  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  component Caption: Text {
    color: view.dimmer
    font.family: view.ff
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
  }
  component Body: Text {
    color: view.fg
    font.family: view.ff
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
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
        text: "Settings"
        color: view.fg
        font.family: view.ff
        font.pixelSize: Style.font.heading
      }

      Row {
        width: parent.width
        spacing: Style.space(12)
        readonly property real colW: (width - spacing) / 2

        Column {
          width: parent.colW
          spacing: Style.space(12)

          TitledCard {
            app: view.app
            width: parent.width
            title: "COINS"
            Caption { text: "COMMA-SEPARATED" }
            TextField {
              id: coinsField
              width: parent.width
              foreground: view.fg
              accent: view.accent
              font.family: view.ff
              font.pixelSize: Style.font.body
              placeholderText: "BTC/USDT, ETH/USDT"
              Keys.onReturnPressed: view.applyCoins()
              Keys.onEnterPressed: view.applyCoins()
              Keys.onEscapePressed: view.forceActiveFocus()
            }
            Apply { text: "Apply"; onClicked: view.applyCoins() }
            Note { width: parent.width; text: "BASE/QUOTE, e.g. BTC/USDT. Validated on this side and again by the daemon; the first coin anchors what `latest` returns." }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "INTERVAL"
            Caption { text: "interval_minutes" }
            TextField {
              id: intervalField
              width: Style.space(110)
              foreground: view.fg
              accent: view.accent
              font.family: view.ff
              font.pixelSize: Style.font.body
              placeholderText: "60"
              Keys.onReturnPressed: view.applyInterval()
              Keys.onEnterPressed: view.applyInterval()
              Keys.onEscapePressed: view.forceActiveFocus()
            }
            Apply { text: "Apply"; onClicked: view.applyInterval() }
            Note { width: parent.width; text: "How often the daemon regenerates every configured coin. Whole minutes, 5 minimum. Takes effect on the next scheduler tick." }
          }
        }

        Column {
          width: parent.colW
          spacing: Style.space(12)

          TitledCard {
            app: view.app
            width: parent.width
            title: "LLM MODEL"
            Caption { text: "model" }
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
            Apply { text: "Apply"; onClicked: view.applyModel() }
            Note { width: parent.width; text: "The model the daemon asks to write the prediction narrative, grounded in the computed indicators. Prices stay deterministic either way." }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "API KEYS"
            Body { text: "Provider keys are managed on the API keys screen." }
            Note { width: parent.width; text: "Keys are stored in a private file the daemon reads at generation time — never in the config, the reports, or this window. Only a masked hint is shown; pick the active and fallback provider on the Model screen." }
            Apply { text: "Open API keys"; onClicked: if (app) app.setView("apikeys") }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "THE DAEMON"
            Body { text: (app && app.running ? "Running" : "Not running") + (app ? "  ·  " + app.addr : "") }
            Body { text: "Data: " + (app && app.status && app.status.data_dir ? String(app.status.data_dir) : "unknown") }
            Note { width: parent.width; text: "Loopback only. Every change on this screen goes through `playbook set-config`, the same validation the daemon applies to itself." }
          }
        }
      }
    }
  }
}
