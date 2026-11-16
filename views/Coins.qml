import QtQuick
import qs.Commons
import qs.Ui
import "../components"

// The configured coins: which pairs the daemon tracks, with a jump to the
// dashboard and a regenerate per coin. The list itself is edited in
// Settings — this view is the read-side control panel for it. (Bundled
// with Task 11 so the sidebar's Coins section is not a dead end.)
Item {
  id: view
  property var app: null
  readonly property bool formFocused: false

  readonly property var coins: app && Array.isArray(app.status && app.status.coins) ? app.status.coins : []
  readonly property string activeCoin: app && app.selectedCoin !== "" ? app.selectedCoin : (app ? app.primaryCoin : "")
  readonly property var generating: app && Array.isArray(app.generating) ? app.generating : []

  // ---- theme
  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  function isGenerating(coin) {
    for (var i = 0; i < generating.length; i++) if (generating[i] === coin) return true
    return false
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
  component Mini: Button {
    foreground: view.fg
    accent: view.accent
    fontFamily: view.ff
    fontSize: Style.font.caption
    bordered: true
    focusable: false
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
        text: "Coins"
        color: view.fg
        font.family: view.ff
        font.pixelSize: Style.font.heading
      }
      Note {
        width: parent.width
        text: "The daemon tracks these pairs. The list is edited in Settings — this view switches the dashboard to a coin and kicks off a regeneration."
        color: view.dimmer
      }

      Body {
        visible: view.coins.length === 0
        width: parent.width
        text: "No coins configured yet. Press 6 to add one in Settings."
        color: view.dim
      }

      Repeater {
        model: view.coins
        delegate: TitledCard {
          id: coinCard
          required property var modelData
          app: view.app
          width: col.width
          title: String(coinCard.modelData) + (view.activeCoin === String(coinCard.modelData) ? "  ·  SHOWING" : "")

          Row {
            spacing: Style.space(8)
            Mini {
              text: "View latest"
              onClicked: if (view.app) { view.app.selectCoin(String(coinCard.modelData)); view.app.setView("dashboard") }
            }
            Mini {
              text: view.isGenerating(String(coinCard.modelData)) ? "Regenerating…" : "Regenerate"
              onClicked: if (view.app && !view.isGenerating(String(coinCard.modelData)))
                view.app.run(["regenerate", String(coinCard.modelData)], "Regeneration started for " + coinCard.modelData)
            }
          }
        }
      }
    }
  }
}
