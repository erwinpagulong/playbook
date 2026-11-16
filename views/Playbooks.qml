import QtQuick
import qs.Commons
import "../components"

// One report's playbook, section by section: the market snapshot, the
// entry/exit map, the key levels and the risk rules. Shows the latest
// report, or a saved one picked in History / Recent reports. Seeded sample
// reports carry their document in `source_markdown` and have no structured
// levels — those fall back to the plain-text document.
Item {
  id: view
  property var app: null
  readonly property bool formFocused: false

  // ---- which report
  readonly property var snapReport: app && app.snap && app.snap.available === true ? app.snap.report : null
  property var selectedReport: null
  property string selectedError: ""
  readonly property string selectedId: app ? String(app.selectedReportId || "") : ""
  readonly property var report: selectedReport !== null ? selectedReport : snapReport
  readonly property bool hasReport: report !== null
  readonly property bool viewingSelected: selectedId !== ""

  function reloadSelected() {
    if (!view.app) return
    if (view.selectedId === "") { view.selectedReport = null; view.selectedError = ""; return }
    view.app.query(["report", view.selectedId], function (data, err) {
      if (err || !data || typeof data !== "object") {
        view.selectedReport = null
        view.selectedError = err || "report not found"
        return
      }
      view.selectedReport = data
      view.selectedError = ""
    })
  }
  onAppChanged: reloadSelected()
  onSelectedIdChanged: reloadSelected()
  Connections { target: view.app; function onChanged() { view.reloadSelected() } }

  readonly property var positions: report && report.levels && Array.isArray(report.levels.positions)
    ? report.levels.positions : []
  readonly property var keyLevels: report && report.levels && report.levels.key_levels
    ? report.levels.key_levels : ({})
  readonly property var support: Array.isArray(keyLevels.support) ? keyLevels.support : []
  readonly property var resistance: Array.isArray(keyLevels.resistance) ? keyLevels.resistance : []
  readonly property var sources: report && report.snapshot && Array.isArray(report.snapshot.sources)
    ? report.snapshot.sources : []
  readonly property var riskRules: report && Array.isArray(report.risk_rules) ? report.risk_rules : []
  readonly property bool predictionAvailable: report && report.prediction && report.prediction.available === true
  readonly property string sourceDoc: report && typeof report.source_markdown === "string"
    ? report.source_markdown : ""
  readonly property bool structured: positions.length > 0 || sources.length > 0 || riskRules.length > 0
  readonly property bool hasSourceFallback: sourceDoc !== "" && !structured

  // ---- theme
  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
  readonly property color bullish: app ? app.bullish : Color.accent
  readonly property color bearish: app ? app.bearish : Color.urgent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  function num(v, digits) {
    var n = Number(v)
    return isFinite(n) ? n.toFixed(digits === undefined ? 2 : digits) : "—"
  }
  function price(v) { return app ? app.formatPrice(Number(v)) : String(v) }
  function shortDate(iso) { return String(iso || "").replace("T", " ").slice(0, 16) }
  function dirTone(d) {
    var s = String(d || "").toUpperCase()
    return s === "LONG" ? view.bullish : s === "SHORT" ? view.bearish : view.dim
  }

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
            text: "Playbooks"
            color: view.fg
            font.family: view.ff
            font.pixelSize: Style.font.heading
          }
          Note {
            text: view.hasReport
              ? (view.viewingSelected ? "Saved report " + view.selectedId : "Latest report · " + view.report.coin)
                + "  ·  " + view.shortDate(view.report.generated_at)
                + (view.report.sample ? "  ·  SAMPLE" : "")
              : "No report for this coin yet."
            color: view.dimmer
          }
          Note {
            visible: view.selectedError !== ""
            text: view.selectedError
            color: view.urgent
          }
        }
        Rectangle {
          visible: view.viewingSelected
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: clearLabel.implicitWidth + Style.space(20)
          height: clearLabel.implicitHeight + Style.space(10)
          radius: height / 2
          color: "transparent"
          border.width: Style.normalBorderWidth
          border.color: view.accent
          Text {
            id: clearLabel
            anchors.centerIn: parent
            text: "Back to latest"
            color: view.accent
            font.family: view.ff
            font.pixelSize: Style.font.caption
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (view.app) view.app.clearReportSelection()
          }
        }
      }

      Body {
        visible: !view.hasReport
        width: parent.width
        text: "Nothing to show yet. The daemon generates a report per configured coin on the configured interval — or press r to regenerate now."
        color: view.dim
      }

      // ---- MARKET SNAPSHOT
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.hasReport
        title: "MARKET SNAPSHOT"

        Row { width: parent.width; spacing: Style.space(12)
          Caption { width: Style.space(150); text: "SOURCE" }
          Caption { width: Style.space(110); text: "PRICE" }
          Caption { text: "24H CHANGE" }
        }
        Body {
          visible: view.sources.length === 0
          width: parent.width
          text: view.hasSourceFallback
            ? "No quote sources in this report — see the source document below."
            : "No quote sources in this report."
          color: view.dim
        }
        Repeater {
          model: view.sources
          delegate: Row {
            id: srcRow
            required property var modelData
            width: parent.width
            spacing: Style.space(12)
            height: Style.space(24)
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(150); elide: Text.ElideRight; text: String(srcRow.modelData.source || ""); font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(110); text: view.price(srcRow.modelData.price); font.pixelSize: Style.font.bodySmall }
            Body {
              anchors.verticalCenter: parent.verticalCenter
              readonly property real chg: Number(srcRow.modelData.change_pct)
              text: isFinite(chg) ? (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%" : "—"
              color: isFinite(chg) ? (chg >= 0 ? view.bullish : view.bearish) : view.dim
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      // ---- ENTRY & EXIT MAP
      TitledCard {
        id: entryCard
        app: view.app
        width: parent.width
        visible: view.hasReport
        title: "ENTRY & EXIT MAP"

        Row {
          id: entryHead
          width: parent.width
          spacing: Style.space(10)
          Caption { width: Style.space(44); text: "TF" }
          Caption { width: Style.space(58); text: "DIR" }
          Caption { width: Style.space(90); text: "SETUP" }
          Caption { width: Style.space(84); text: "ENTRY" }
          Caption { width: Style.space(84); text: "TP1" }
          Caption { width: Style.space(84); text: "TP2" }
          Caption { width: Style.space(84); text: "STOP" }
          Caption { text: "R:R" }
        }
        Body {
          visible: view.positions.length === 0
          width: parent.width
          text: view.hasSourceFallback ? "No structured levels — see the source document below." : "No structured levels in this report."
          color: view.dim
        }
        Repeater {
          model: view.positions
          delegate: Row {
            id: posRow
            required property var modelData
            width: entryCard.width - entryCard.pad * 2
            spacing: Style.space(10)
            height: Style.space(26)
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(44); text: String(posRow.modelData.timeframe || ""); color: view.dim; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(58); text: String(posRow.modelData.direction || ""); color: view.dirTone(posRow.modelData.direction); font.bold: true; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(90); elide: Text.ElideRight; text: String(posRow.modelData.label || ""); color: view.dim; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(84); text: view.price(posRow.modelData.entry); font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(84); text: view.price(posRow.modelData.tp1); font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(84); text: view.price(posRow.modelData.tp2); font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(84); text: view.price(posRow.modelData.stop); color: view.urgent; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; text: view.num(posRow.modelData.rr, 2); font.pixelSize: Style.font.bodySmall }
          }
        }
        Note {
          visible: view.support.length > 0 || view.resistance.length > 0
          width: parent.width
          text: "Support  " + view.support.join(" · ") + "\nResistance  " + view.resistance.join(" · ")
          color: view.dimmer
        }
      }

      // ---- RISK RULES
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.hasReport
        title: "RISK RULES"

        Body {
          visible: view.riskRules.length === 0
          width: parent.width
          text: "None recorded in this report."
          color: view.dim
        }
        Repeater {
          model: view.riskRules
          delegate: Row {
            id: ruleRow
            required property var modelData
            width: parent.width
            spacing: Style.space(8)
            Note {
              width: Style.space(14)
              text: "\uf00c"
              color: view.accent
            }
            Body {
              width: ruleRow.width - Style.space(22)
              text: typeof ruleRow.modelData === "string" ? ruleRow.modelData : JSON.stringify(ruleRow.modelData)
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      // ---- SOURCE DOCUMENT (sample fallback)
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.hasSourceFallback
        title: "SOURCE DOCUMENT"

        Note {
          width: parent.width
          text: "This report ships its original document; structured fields are absent. Shown as plain text."
          color: view.dimmer
        }
        Flickable {
          width: parent.width
          height: Style.space(320)
          contentWidth: width
          contentHeight: sourceText.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          Text {
            id: sourceText
            width: parent.width
            text: view.sourceDoc
            color: view.dim
            font.family: view.ff
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
          }
        }
      }
    }
  }
}
