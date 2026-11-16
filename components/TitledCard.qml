import QtQuick
import qs.Commons

// A bordered card with a small-caps title above its content. Same contract
// as the Omabudget card the app was modeled on: the app hands itself in as
// `app` and the card only renders.
Rectangle {
  id: card

  default property alias content: inner.data
  property var app: null
  property string title: ""
  property real pad: Style.space(16)

  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property string ff: app ? app.fontFamily : Style.font.family
  readonly property real titleHeight: Style.font.caption + Style.space(8)

  radius: Style.cornerRadius
  color: "transparent"
  border.width: Style.normalBorderWidth
  border.color: app ? app.cardBorder : Style.normalBorderColor
  height: inner.implicitHeight + card.pad * 2 + card.titleHeight

  Text {
    x: card.pad
    y: card.pad
    text: card.title
    color: card.dimmer
    font.family: card.ff
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
  }

  Column {
    id: inner
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.leftMargin: card.pad
    anchors.rightMargin: card.pad
    anchors.topMargin: card.pad + card.titleHeight
    spacing: Style.space(10)
  }
}
