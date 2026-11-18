import QtQuick
import qs.Commons
import "../components"

// One report's prediction, section by section: conviction, the scenarios
// (grouped by horizon, probabilities labeled as subjective estimates), the
// per-timeframe reads, and the confirmation / invalidation / bottom line.
// Shows the latest report, or a saved one picked in History. Seeded sample
// reports carry no structured prediction — those fall back to the
// plain-text source document.
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

  readonly property var prediction: report && report.prediction ? report.prediction : ({})
  readonly property bool predictionAvailable: prediction.available === true
  readonly property var highestConviction: prediction.highest_conviction ? prediction.highest_conviction : null
  readonly property string convictionText: highestConviction && highestConviction.text ? String(highestConviction.text) : ""
  readonly property string confidenceLabel: {
    if (!predictionAvailable || !highestConviction) return "—"
    var c = Number(highestConviction.confidence)
    return isFinite(c) ? Math.round(c * 100) + "%" : "—"
  }
  readonly property var scenarios: Array.isArray(prediction.scenarios) ? prediction.scenarios : []
  readonly property var scenarioGroups: {
    var groups = []
    for (var i = 0; i < scenarios.length; i++) {
      var s = scenarios[i]
      if (!s || typeof s !== "object") continue
      var horizon = s.horizon ? String(s.horizon) : "all"
      var found = null
      for (var j = 0; j < groups.length; j++)
        if (groups[j].horizon === horizon) { found = groups[j]; break }
      if (!found) { found = { horizon: horizon, items: [] }; groups.push(found) }
      found.items.push(s)
    }
    return groups
  }
  readonly property var perTimeframe: prediction.per_timeframe && typeof prediction.per_timeframe === "object"
    ? prediction.per_timeframe : ({})
  readonly property var perTimeframeRows: {
    var rows = []
    for (var k in perTimeframe) rows.push({ tf: k, text: String(perTimeframe[k]) })
    return rows
  }
  readonly property string sourceDoc: report && typeof report.source_markdown === "string"
    ? report.source_markdown : ""
  readonly property bool hasSourceFallback: sourceDoc !== "" && !predictionAvailable

  // ---- theme
  readonly property color fg: app ? app.foreground : Color.foreground
  readonly property color dim: app ? app.dim : Color.foreground
  readonly property color dimmer: app ? app.dimmer : Color.foreground
  readonly property color accent: app ? app.accent : Color.accent
  readonly property color urgent: app ? app.urgent : Color.urgent
  readonly property string ff: app ? app.fontFamily : Style.font.family

  function price(v) { return app ? app.formatPrice(Number(v)) : String(v) }
  function shortDate(iso) { return String(iso || "").replace("T", " ").slice(0, 16) }

  component Caption: Text {
    color: view.dimmer
    font.family: view.ff
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
    // Provider text must never be parsed as markup: AutoText can load remote
    // images from an <img> tag while the report is merely displayed.
    textFormat: Text.PlainText
  }
  component Body: Text {
    color: view.fg
    font.family: view.ff
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
  }
  component Note: Text {
    color: view.dim
    font.family: view.ff
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
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
            text: "Predictions"
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

      // ---- unavailable state
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.hasReport && !view.predictionAvailable
        title: "PREDICTION"

        Body {
          width: parent.width
          text: "Prediction unavailable" +
            (view.prediction.reason ? ": " + String(view.prediction.reason) : ".")
          color: view.urgent
        }
        Note {
          width: parent.width
          text: "Predictions need the LLM key. The environment variable " + (app ? app.llmKeyEnv : "OPENAI_API_KEY") +
            " holds it for the daemon — it is never stored in this plugin. Set it and restart the daemon to ground the prediction blocks; playbooks still generate without it."
        }
      }

      // ---- conviction
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.predictionAvailable
        title: "HIGHEST CONVICTION"

        Row {
          width: parent.width
          spacing: Style.space(16)
          Column {
            spacing: Style.space(2)
            Caption { text: "CONFIDENCE" }
            Text {
              text: view.confidenceLabel
              color: view.accent
              font.family: view.ff
              font.pixelSize: Style.font.display
              font.bold: true
              textFormat: Text.PlainText
            }
          }
          Body {
            width: parent.width - Style.space(120)
            anchors.verticalCenter: parent.verticalCenter
            text: view.convictionText !== "" ? view.convictionText : "Recorded, without a conviction call."
          }
        }
        Note {
          width: parent.width
          text: "Confidence is the model's subjective estimate, not a measured win rate."
          color: view.dimmer
        }
      }

      // ---- scenarios
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.predictionAvailable
        title: "SCENARIOS"

        Repeater {
          model: view.scenarioGroups
          delegate: Column {
            id: group
            required property var modelData
            width: parent.width
            spacing: Style.space(4)
            Caption {
              text: String(group.modelData.horizon).toUpperCase()
              topPadding: Style.space(4)
            }
            Repeater {
              model: group.modelData.items
              delegate: Row {
                id: scenarioRow
                required property var modelData
                width: group.width
                spacing: Style.space(10)
                height: Style.space(24)
                Body {
                  width: parent.width - Style.space(210)
                  anchors.verticalCenter: parent.verticalCenter
                  elide: Text.ElideRight
                  text: String(scenarioRow.modelData.label || "")
                  font.pixelSize: Style.font.bodySmall
                }
                Note {
                  width: Style.space(120)
                  anchors.verticalCenter: parent.verticalCenter
                  text: view.price(scenarioRow.modelData.low) + " – " + view.price(scenarioRow.modelData.high)
                  color: view.dimmer
                }
                Body {
                  anchors.verticalCenter: parent.verticalCenter
                  text: (Number(scenarioRow.modelData.probability) || 0) + "%"
                  color: view.accent
                  font.bold: true
                  font.pixelSize: Style.font.bodySmall
                }
              }
            }
          }
        }
        Note {
          width: parent.width
          text: "Probabilities are the model's subjective estimates, not measured win rates."
          color: view.dimmer
        }
      }

      // ---- per timeframe
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.predictionAvailable && view.perTimeframeRows.length > 0
        title: "PER TIMEFRAME"

        Repeater {
          model: view.perTimeframeRows
          delegate: Row {
            id: ptfRow
            required property var modelData
            width: parent.width
            spacing: Style.space(10)
            Caption { width: Style.space(40); text: String(ptfRow.modelData.tf); anchors.verticalCenter: parent.verticalCenter }
            Body {
              width: ptfRow.width - Style.space(50)
              text: ptfRow.modelData.text
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      // ---- favored / confirmation / invalidation / bottom line
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.predictionAvailable
        title: "THE CALL"

        Caption { text: "FAVORED TRADE"; visible: !!view.prediction.favored_trade }
        Body { visible: !!view.prediction.favored_trade; width: parent.width; text: String(view.prediction.favored_trade || "") }
        Caption { text: "CONFIRMATION"; visible: !!view.prediction.confirmation; topPadding: Style.space(4) }
        Body { visible: !!view.prediction.confirmation; width: parent.width; text: String(view.prediction.confirmation || "") }
        Caption { text: "INVALIDATION"; visible: !!view.prediction.invalidation; topPadding: Style.space(4) }
        Body { visible: !!view.prediction.invalidation; width: parent.width; color: view.urgent; text: String(view.prediction.invalidation || "") }
        Caption { text: "BOTTOM LINE"; visible: !!view.prediction.bottom_line; topPadding: Style.space(4) }
        Body { visible: !!view.prediction.bottom_line; width: parent.width; text: String(view.prediction.bottom_line || ""); font.bold: true }
      }

      // ---- SOURCE DOCUMENT (sample fallback)
      TitledCard {
        app: view.app
        width: parent.width
        visible: view.hasSourceFallback
        title: "SOURCE DOCUMENT"

        Note {
          width: parent.width
          text: "This report ships its original document; the prediction block is absent. Shown as plain text."
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
