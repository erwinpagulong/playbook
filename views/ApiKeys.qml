import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../components"

// API keys: one row per provider preset. Keys are write-only here — the
// daemon never returns one, only a masked hint (`sk-…4e18`) and a set/missing
// badge — and they live in a private file the daemon reads, never in the
// config, the reports, or this window. The Custom endpoint row edits the
// active provider's base URL/model (what the Custom preset needs once it is
// selected on the Model screen).
Item {
  id: view
  property var app: null
  // Pasted keys hold focus in delegates we cannot name from out here, so a
  // counter stands in for `field.activeFocus` checks.
  property int pasteFocusCount: 0
  readonly property bool formFocused:
    customBaseField.activeFocus || customModelField.activeFocus || view.pasteFocusCount > 0

  readonly property var rows: app && Array.isArray(app.providers) ? app.providers : []
  readonly property var llm: app && app.cfg && app.cfg.llm ? app.cfg.llm : ({})
  readonly property string currentBaseUrl: llm.base_url ? String(llm.base_url) : ""
  readonly property string currentModel: llm.model ? String(llm.model) : ""

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

  function saveKey(row, field) {
    var key = field.text.trim()
    var id = String(row.id)
    if (key === "") { view.app.lastError = "paste a key first"; return }
    // The key goes to the helper's stdin, never into its argv: process
    // arguments are readable by other accounts on a shared machine. run()
    // copies it into the queue synchronously, so clearing the field is safe.
    field.text = ""
    view.app.run(["set-key", id], "key saved for " + String(row.name), key)
  }

  function clearKey(row) {
    view.app.run(["clear-key", String(row.id)], "key cleared for " + String(row.name))
  }

  function applyCustom() {
    var base = customBaseField.text.trim()
    var model = customModelField.text.trim()
    if (!/^https?:\/\//.test(base)) { view.app.lastError = "base URL must start with http:// or https://"; return }
    if (model === "") { view.app.lastError = "model must be a non-empty string"; return }
    view.postConfig({ llm: { base_url: base, model: model } }, "endpoint: " + base)
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
  readonly property color border: app ? app.cardBorder : Style.normalBorderColor
  readonly property string ff: app ? app.fontFamily : Style.font.family

  onAppChanged: if (app) app.refresh()
  Component.onCompleted: if (app) app.refresh()
  // When the roster actually changes the row delegates are rebuilt and any
  // focused paste field is destroyed without a final focus-out; zero the
  // counter so bare keys are not swallowed forever.
  onRowsChanged: view.pasteFocusCount = 0

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
  // A small thin-bordered tag: the same monochrome chrome as the cards.
  component Pill: Rectangle {
    property string label: ""
    property color tone: view.accent
    radius: Style.cornerRadius
    color: "transparent"
    border.width: Style.normalBorderWidth
    border.color: tone
    implicitWidth: pillText.implicitWidth + Style.space(16)
    implicitHeight: pillText.implicitHeight + Style.space(6)
    Text {
      id: pillText
      anchors.centerIn: parent
      text: parent.label
      color: parent.tone
      font.family: view.ff
      font.pixelSize: Style.font.caption
      font.letterSpacing: 1
    }
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
        text: "API keys"
        color: view.fg
        font.family: view.ff
        font.pixelSize: Style.font.heading
      }

      Note {
        width: parent.width
        text: "Keys are stored in a private file the daemon reads at generation time — never in the config, the reports, or this window. Only a masked hint is shown; the full key is never returned by any command. OPENAI_API_KEY-style environment variables still work as a fallback when no key is stored here."
      }

      TitledCard {
        app: view.app
        width: parent.width
        title: "PROVIDERS"
        Repeater {
          model: view.rows
          delegate: Column {
            required property var modelData
            width: parent.width
            spacing: Style.space(6)

            RowLayout {
              width: parent.width
              spacing: Style.space(8)
              Text {
                text: String(modelData.name)
                color: view.fg
                font.family: view.ff
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Pill { visible: modelData.active === true; label: "ACTIVE"; tone: view.accent }
              Item { Layout.fillWidth: true }
              Pill {
                label: modelData.key_set === true ? "KEY SET" : "MISSING"
                tone: modelData.key_set === true ? view.accent : view.urgent
              }
            }

            Text {
              text: modelData.key_set === true ? ("key  " + String(modelData.key_hint)) : "no key stored"
              color: view.dim
              font.family: view.ff
              font.pixelSize: Style.font.caption
            }

            RowLayout {
              width: parent.width
              spacing: Style.space(8)
              TextField {
                id: keyField
                Layout.fillWidth: true
                foreground: view.fg
                accent: view.accent
                font.family: view.ff
                font.pixelSize: Style.font.body
                placeholderText: "paste the key…"
                echoMode: TextInput.Password
                onActiveFocusChanged: view.pasteFocusCount = Math.max(0, view.pasteFocusCount + (activeFocus ? 1 : -1))
                Keys.onReturnPressed: view.saveKey(modelData, keyField)
                Keys.onEnterPressed: view.saveKey(modelData, keyField)
                Keys.onEscapePressed: view.forceActiveFocus()
              }
              Apply { text: "Save"; onClicked: view.saveKey(modelData, keyField) }
              Apply {
                text: "Clear"
                visible: modelData.key_set === true
                onClicked: view.clearKey(modelData)
              }
            }

            Rectangle { width: parent.width; height: Style.spacing.hairline; color: view.border }
          }
        }
      }

      TitledCard {
        app: view.app
        width: parent.width
        title: "CUSTOM ENDPOINT"
        Caption { text: "llm.base_url · llm.model" }
        TextField {
          id: customBaseField
          width: parent.width
          foreground: view.fg
          accent: view.accent
          font.family: view.ff
          font.pixelSize: Style.font.body
          placeholderText: "https://api.example.com/v1"
          Keys.onReturnPressed: view.applyCustom()
          Keys.onEnterPressed: view.applyCustom()
          Keys.onEscapePressed: view.forceActiveFocus()
        }
        Binding { target: customBaseField; property: "text"; value: view.currentBaseUrl; when: !customBaseField.activeFocus }
        TextField {
          id: customModelField
          width: parent.width
          foreground: view.fg
          accent: view.accent
          font.family: view.ff
          font.pixelSize: Style.font.body
          placeholderText: "model name"
          Keys.onReturnPressed: view.applyCustom()
          Keys.onEnterPressed: view.applyCustom()
          Keys.onEscapePressed: view.forceActiveFocus()
        }
        Binding { target: customModelField; property: "text"; value: view.currentModel; when: !customModelField.activeFocus }
        Apply { text: "Apply"; onClicked: view.applyCustom() }
        Note { width: parent.width; text: "These apply to the active provider's config — select Custom on the Model screen to use your own OpenAI-compatible endpoint. The daemon validates them on every write." }
      }
    }
  }
}
