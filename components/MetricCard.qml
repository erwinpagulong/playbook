import QtQuick
import qs.Commons

// One headline figure for the dashboard's stat row: a small-caps label, the
// value, and a line of subtext underneath. `tone` tints the value (long is
// accent, short is urgent) and defaults to plain foreground.
Rectangle {
  id: card

  property var app: null
  property string label: ""
  property string value: "—"
  property string sub: ""
  property color tone: app ? app.foreground : Color.foreground

  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property string ff: app ? app.fontFamily : Style.font.family

  radius: Style.cornerRadius
  color: "transparent"
  border.width: Style.normalBorderWidth
  border.color: app ? app.cardBorder : Style.normalBorderColor
  height: Style.space(104)

  Column {
    anchors.fill: parent
    anchors.margins: Style.space(14)
    spacing: Style.space(4)

    Text {
      text: card.label
      color: card.dimmer
      font.family: card.ff
      font.pixelSize: Style.font.caption
      font.letterSpacing: 1
    }
    Text {
      width: parent.width
      text: card.value
      color: card.tone
      font.family: card.ff
      font.pixelSize: Style.font.display
      font.bold: true
      fontSizeMode: Text.HorizontalFit
      minimumPixelSize: Style.font.body
      elide: Text.ElideRight
    }
    Item { height: 1 }
    Text {
      width: parent.width
      text: card.sub
      color: card.dim
      font.family: card.ff
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
    }
  }
}
