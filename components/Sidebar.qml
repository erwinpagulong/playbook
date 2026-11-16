import QtQuick
import qs.Commons
import qs.Ui

// The rail on the left: brand, the numbered sections, the quick action and
// the footer. The app owns the view state and hands itself in as `app`;
// this file only renders it.
Item {
  id: root

  // Injected by the app.
  property var app: null
  property var manifest: null

  readonly property string view: app && app.view ? String(app.view) : "dashboard"
  readonly property string coin: app && app.primaryCoin ? String(app.primaryCoin) : "BTC/USDT"
  readonly property var views: app && app.views ? app.views : []
  readonly property bool generating: app && Array.isArray(app.generating) && app.generating.length > 0

  // ---- theme tokens, derived so the rail follows whatever theme is running
  readonly property color foreground: Color.foreground
  readonly property color background: Color.background
  readonly property color accent: Color.accent
  readonly property color cardBorder: Style.normalBorderColor
  readonly property color dim: Qt.rgba(
    foreground.r * 0.68 + background.r * 0.32,
    foreground.g * 0.68 + background.g * 0.32,
    foreground.b * 0.68 + background.b * 0.32, 1)
  readonly property color dimmer: Qt.rgba(
    foreground.r * 0.45 + background.r * 0.55,
    foreground.g * 0.45 + background.g * 0.55,
    foreground.b * 0.45 + background.b * 0.55, 1)
  readonly property string fontFamily: Style.font.family
  readonly property int colourMs: 120

  implicitWidth: Style.space(220)

  Rectangle {
    anchors.fill: parent
    color: root.background
  }
  Rectangle {
    anchors.right: parent.right
    width: Style.spacing.hairline
    height: parent.height
    color: root.cardBorder
  }

  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(16)
    spacing: Style.space(4)

    Row {
      spacing: Style.space(8)
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: "\uf201"
        color: root.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: "CRYPTO PLAYBOOK"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
      }
    }
    Text {
      text: "v" + (root.manifest && root.manifest.version ? root.manifest.version : "dev")
      color: root.dimmer
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      bottomPadding: Style.space(16)
    }

    Repeater {
      model: root.views
      delegate: Rectangle {
        required property var modelData
        required property int index
        width: parent.width
        height: Style.space(36)
        radius: Style.cornerRadius
        readonly property bool current: root.view === modelData.id
        color: current ? Style.selectedAccentFill : "transparent"
        // The width is reserved rather than switched, so becoming the
        // current row tints a border into view instead of growing the row
        // by a pixel a side and nudging its neighbours.
        border.width: Style.selectedBorderWidth
        border.color: current ? Style.selectedBorderColor : "transparent"
        Behavior on color { ColorAnimation { duration: root.colourMs } }
        Behavior on border.color { ColorAnimation { duration: root.colourMs } }

        Row {
          anchors.fill: parent
          anchors.leftMargin: Style.space(12)
          spacing: Style.space(10)
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: modelData.glyph
            color: current ? root.accent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.icon
            Behavior on color { ColorAnimation { duration: root.colourMs } }
          }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: modelData.label
            color: current ? root.foreground : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            Behavior on color { ColorAnimation { duration: root.colourMs } }
          }
        }
        Text {
          anchors.right: parent.right
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          text: modelData.key
          color: current ? root.accent : root.dimmer
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          Behavior on color { ColorAnimation { duration: root.colourMs } }
        }
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: if (root.app) root.app.setView(modelData.id)
        }
      }
    }
  }

  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: Style.space(16)
    spacing: Style.space(4)

    Button {
      width: parent.width
      text: root.generating ? "Regenerating…" : "Quick regenerate   r"
      tooltipText: "Re-run generation for " + root.coin
      foreground: root.foreground
      accent: root.accent
      fontFamily: root.fontFamily
      fontSize: Style.font.caption
      bordered: true
      focusable: false
      onClicked: if (!root.generating && root.app) root.app.run(["regenerate", coin], "Regeneration started for " + coin)
    }
    Text {
      topPadding: Style.space(8)
      text: "Local. Private. Yours."
      color: root.dimmer
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}
