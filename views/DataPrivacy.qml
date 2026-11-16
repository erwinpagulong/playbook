import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "../components"

// Data & privacy: what stays on this machine, what is transmitted (and why),
// how to take a copy of the reports, and how to remove them. Exports and
// deletes go through the CLI like everything else.
Item {
  id: view
  property var app: null
  readonly property bool formFocused: exportPath.activeFocus

  readonly property string home: Quickshell.env("HOME") || "~"
  readonly property string dataDir: app && app.status && app.status.data_dir ? String(app.status.data_dir) : home + "/.local/share/crypto-playbook"
  readonly property string defaultExport: home + "/Documents/crypto-playbook-export"
  property bool deleteArmed: false

  function doExport() {
    var dest = exportPath.text.trim()
    if (dest === "") { view.app.lastError = "pick a destination folder for the export"; exportPath.forceActiveFocus(); return }
    view.app.run(["export", dest], "reports exported to " + dest)
  }
  function doDelete() {
    if (!view.deleteArmed) { view.deleteArmed = true; return }
    view.deleteArmed = false
    view.app.run(["delete-reports"], "generated reports deleted")
  }

  function handleKey(e) {
    if (e.modifiers !== Qt.NoModifier) return false
    if (e.key === Qt.Key_E) { exportPath.forceActiveFocus(); exportPath.selectAll(); return true }
    return false
  }

  Component.onCompleted: exportPath.text = view.defaultExport
  onAppChanged: if (exportPath.text === "") exportPath.text = view.defaultExport

  Timer {
    interval: 4000
    running: view.deleteArmed
    onTriggered: view.deleteArmed = false
  }

  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
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
  component Go: Button {
    foreground: view.fg
    accent: view.accent
    fontFamily: view.ff
    fontSize: Style.font.caption
    bordered: true
  }
  component Danger: Button {
    foreground: view.urgent
    accent: view.urgent
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
        text: "Data & Privacy"
        color: view.fg
        font.family: view.ff
        font.pixelSize: Style.font.heading
      }
      Body {
        width: parent.width
        text: "Everything lives in this tool's own folder on this machine. No account, no broker, no order flow — analysis only. The daemon listens on the loopback address and nothing else."
        color: view.dim
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
            title: "WHERE IT LIVES"
            Body { text: view.dataDir; font.pixelSize: Style.font.bodySmall }
            Note { width: parent.width; text: "Reports: JSON for this window plus a markdown twin per report, under reports/. Hand-readable, back them up by copying the folder." }
            Body { text: configPath(); font.pixelSize: Style.font.bodySmall }
            Note { width: parent.width; text: "Config: coins, interval_minutes, llm.model. The API key is NOT in it — it comes from the environment variable at daemon startup." }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "WHAT LEAVES THE MACHINE"
            Note { width: parent.width; text: "Out: public market data — candles from Binance (yfinance when Binance fails) and quote snapshots. These requests name only a public trading pair, nothing about you." }
            Note { width: parent.width; text: "Out: the report payload — indicators, levels, quotes — sent to the LLM endpoint in your config (llm.base_url, default api.openai.com) so it can write the prediction narrative. Change base_url in the config to keep that traffic elsewhere." }
            Note { width: parent.width; text: "The API key is sent only to your configured LLM endpoint, in the Authorization header, when a prediction is generated — it is never stored in config, reports, or logs, and never leaves that request. Your files and identity are never sent. Everything else travels over 127.0.0.1." }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "REMOVING EVERYTHING"
            Note { width: parent.width; text: "In a terminal:" }
            Rectangle {
              width: parent.width
              height: purgeText.implicitHeight + Style.space(16)
              radius: Style.cornerRadius
              color: Qt.rgba(view.fg.r, view.fg.g, view.fg.b, 0.05)
              Text {
                id: purgeText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Style.space(8)
                text: "rm -rf " + view.dataDir + "\nomarchy plugin remove windong.cryptoplaybook"
                color: view.dim
                font.family: view.ff
                font.pixelSize: Style.font.caption
              }
            }
          }
        }

        Column {
          width: parent.colW
          spacing: Style.space(12)

          TitledCard {
            app: view.app
            width: parent.width
            title: "EXPORT"
            Note { width: parent.width; text: "Copies the reports folder (every JSON + markdown file) into the destination below. Existing files with the same name are overwritten." }
            Caption { text: "DESTINATION"; topPadding: Style.space(4) }
            TextField {
              id: exportPath
              width: parent.width
              foreground: view.fg
              accent: view.accent
              font.family: view.ff
              font.pixelSize: Style.font.body
              Keys.onReturnPressed: view.doExport()
              Keys.onEnterPressed: view.doExport()
              Keys.onEscapePressed: view.forceActiveFocus()
            }
            Go { text: "Export reports   e"; onClicked: view.doExport() }
            Note { width: parent.width; text: "Leave the destination empty and the daemon exports to the default ~/Documents/crypto-playbook-export." }
          }

          TitledCard {
            app: view.app
            width: parent.width
            title: "DELETE REPORTS"
            Note { width: parent.width; text: "Removes every generated report (JSON + markdown). The two bundled sample reports are kept, and so is anything unreadable. This cannot be undone — export first if you want a copy." }
            Danger {
              text: view.deleteArmed ? "Really delete — click again" : "Delete reports"
              onClicked: view.doDelete()
            }
            Note {
              visible: view.deleteArmed
              width: parent.width
              text: "Armed for a few seconds. Click again to delete, or wait."
              color: view.urgent
            }
          }
        }
      }
    }
  }

  function configPath() {
    var home = view.home
    var xdg = Quickshell.env("XDG_CONFIG_HOME") || ""
    var base = xdg !== "" ? xdg : home + "/.config"
    return base + "/crypto-playbook/config.json"
  }
}
