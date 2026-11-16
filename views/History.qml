import QtQuick
import qs.Commons
import "../components"

// Every stored report, newest first, with a way into it. Reads straight
// from `playbook reports`; the "View" action loads the report in the
// Playbooks section.
Item {
  id: view
  property var app: null
  readonly property bool formFocused: false

  property var reports: []
  property string loadError: ""

  function reload() {
    if (!view.app) return
    view.app.query(["reports"], function (data, err) {
      if (err || !Array.isArray(data)) {
        view.reports = []
        view.loadError = err || "could not read the reports"
        return
      }
      view.reports = data
      view.loadError = ""
    })
  }
  onAppChanged: reload()
  Connections { target: view.app; function onChanged() { view.reload() } }
  Component.onCompleted: reload()

  readonly property int sampleCount: {
    var n = 0
    for (var i = 0; i < reports.length; i++) if (reports[i] && reports[i].sample === true) n += 1
    return n
  }

  // ---- theme
  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  function shortDate(iso) { return String(iso || "").replace("T", " ").slice(0, 16) }
  function shortId(id) { return String(id || "").slice(-18) }

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

      // ---- header
      Item {
        width: parent.width
        height: headCol.implicitHeight
        Column {
          id: headCol
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)
          Text {
            text: "History"
            color: view.fg
            font.family: view.ff
            font.pixelSize: Style.font.heading
          }
          Note {
            text: view.reports.length === 0
              ? "No reports stored yet."
              : view.reports.length + " report" + (view.reports.length === 1 ? "" : "s")
                + (view.sampleCount > 0 ? "  ·  " + view.sampleCount + " sample" + (view.sampleCount === 1 ? "" : "s") : "")
            color: view.dimmer
          }
        }
        Rectangle {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: reloadLabel.implicitWidth + Style.space(20)
          height: reloadLabel.implicitHeight + Style.space(10)
          radius: height / 2
          color: "transparent"
          border.width: Style.normalBorderWidth
          border.color: reloadArea.containsMouse ? view.accent
            : (app ? app.cardBorder : view.dimmer)
          Text {
            id: reloadLabel
            anchors.centerIn: parent
            text: "Reload"
            color: reloadArea.containsMouse ? view.accent : view.dim
            font.family: view.ff
            font.pixelSize: Style.font.caption
          }
          MouseArea {
            id: reloadArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: view.reload()
          }
        }
      }

      Note {
        visible: view.loadError !== ""
        width: parent.width
        text: view.loadError
        color: view.urgent
      }

      // ---- the table
      TitledCard {
        app: view.app
        width: parent.width
        title: "ALL REPORTS"

        Row {
          width: parent.width
          spacing: Style.space(10)
          Caption { width: Style.space(96); text: "COIN" }
          Caption { width: Style.space(160); text: "GENERATED" }
          Caption { width: Style.space(70); text: "KIND" }
          Caption { width: parent.width - Style.space(96 + 160 + 70 + 80); text: "ID" }
        }

        Body {
          visible: view.reports.length === 0 && view.loadError === ""
          width: parent.width
          text: "The store is empty. Reports appear here as the daemon generates them — or press r to generate now."
          color: view.dim
        }

        Repeater {
          model: view.reports
          delegate: Item {
            id: reportRow
            required property var modelData
            width: parent.width
            height: Style.space(30)

            Body {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(96)
              text: String(reportRow.modelData.coin || "")
              elide: Text.ElideRight
              font.pixelSize: Style.font.bodySmall
            }
            Note {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(106)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(160)
              text: view.shortDate(reportRow.modelData.generated_at)
              color: view.dimmer
            }
            Caption {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(276)
              anchors.verticalCenter: parent.verticalCenter
              visible: reportRow.modelData.sample === true
              text: "SAMPLE"
              color: view.accent
            }
            Note {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(276)
              anchors.verticalCenter: parent.verticalCenter
              visible: reportRow.modelData.sample !== true
              text: "GENERATED"
              color: view.dimmer
            }
            Note {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(356)
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width - Style.space(356 + 80)
              elide: Text.ElideMiddle
              text: view.shortId(reportRow.modelData.id)
              color: view.dimmer
            }
            Text {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: "View  ›"
              color: viewArea.containsMouse ? view.fg : view.dim
              font.family: view.ff
              font.pixelSize: Style.font.caption
              MouseArea {
                id: viewArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (view.app) view.app.showReport(String(reportRow.modelData.id || ""), "playbooks")
              }
            }
          }
        }
      }
    }
  }
}
