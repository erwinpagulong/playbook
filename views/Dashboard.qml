import QtQuick
import qs.Commons
import "../components"

// This coin at a glance: the price, the bias, the conviction, the best
// setup, plus the entry/exit map, the scenarios, the indicator dashboard
// and the recent reports. Everything drawn here comes from app.snap, the
// daemon's latest-report document; a field the report does not carry
// leaves its card in the empty state. Seeded sample reports carry their
// original document in `source_markdown` — when nothing structured is
// there, it is rendered as plain text instead.
Item {
  id: view
  property var app: null
  readonly property bool formFocused: false

  // ---- the report
  readonly property var snap: app ? app.snap : null
  readonly property var snapReport: snap && snap.available === true ? snap.report : null
  readonly property var report: snapReport
  readonly property bool hasReport: report !== null
  readonly property var positions: report && report.levels && Array.isArray(report.levels.positions)
    ? report.levels.positions : []
  readonly property var keyLevels: report && report.levels && report.levels.key_levels
    ? report.levels.key_levels : ({})
  readonly property var support: Array.isArray(keyLevels.support) ? keyLevels.support : []
  readonly property var resistance: Array.isArray(keyLevels.resistance) ? keyLevels.resistance : []
  readonly property var indicators: report && report.indicators ? report.indicators : ({})
  readonly property var prediction: report && report.prediction ? report.prediction : ({})
  readonly property bool predictionAvailable: prediction.available === true
  readonly property var scenarios: Array.isArray(prediction.scenarios) ? prediction.scenarios : []
  readonly property var highestConviction: prediction.highest_conviction ? prediction.highest_conviction : null
  readonly property string sourceDoc: report && typeof report.source_markdown === "string"
    ? report.source_markdown : ""
  readonly property bool structured: positions.length > 0
    || Object.keys(indicators).length > 0
    || predictionAvailable
  readonly property bool hasSourceFallback: sourceDoc !== "" && !structured

  // ---- coin tabs
  readonly property var coinTabs: {
    var coins = app && Array.isArray(app.status && app.status.coins) ? app.status.coins : []
    if (coins.length === 0) coins = [app ? app.primaryCoin : "BTC/USDT"]
    return coins
  }
  readonly property string activeCoin: app && app.selectedCoin !== "" ? app.selectedCoin
    : (app ? app.primaryCoin : "BTC/USDT")

  // ---- derived figures
  readonly property real change24h: {
    var sources = report && report.snapshot && Array.isArray(report.snapshot.sources)
      ? report.snapshot.sources : []
    for (var i = 0; i < sources.length; i++) {
      var v = Number(sources[i] && sources[i].change_pct)
      if (isFinite(v)) return v
    }
    return NaN
  }
  readonly property real bestRR: {
    var best = NaN
    for (var i = 0; i < positions.length; i++) {
      var rr = Number(positions[i].rr)
      if (isFinite(rr) && (isNaN(best) || rr > best)) best = rr
    }
    return best
  }
  readonly property string confidenceLabel: {
    if (!predictionAvailable || !highestConviction) return "—"
    var c = Number(highestConviction.confidence)
    return isFinite(c) ? Math.round(c * 100) + "%" : "—"
  }
  readonly property var indicatorRows: {
    var rows = []
    var order = ["15m", "4h", "1D"]
    var keys = []
    for (var i = 0; i < order.length; i++) if (indicators[order[i]]) keys.push(order[i])
    for (var k in indicators) if (keys.indexOf(k) === -1) keys.push(k)
    for (var j = 0; j < keys.length; j++) {
      var t = indicators[keys[j]]
      if (!t || typeof t !== "object") continue
      var macd = t.macd || ({})
      var bands = t.bollinger || ({})
      rows.push({
        tf: keys[j],
        price: t.price,
        rsi: t.rsi,
        hist: macd.hist,
        trend: t.trend ? String(t.trend) : "",
        bands: bands.lower + " / " + bands.mid + " / " + bands.upper,
        atr: t.atr
      })
    }
    return rows
  }
  // Scenario groups keyed by horizon ("short-term" / "long-term" from the
  // LLM, or "all" for a flat list).
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

  // ---- recent reports
  property var recentReports: []
  function reloadRecent() {
    if (!app) return
    app.query(["reports"], function (data, err) {
      if (err || !Array.isArray(data)) { view.recentReports = []; return }
      view.recentReports = data.slice(0, 5)
    })
  }
  onAppChanged: reloadRecent()
  Connections { target: view.app; function onChanged() { view.reloadRecent() } }
  Component.onCompleted: reloadRecent()

  // ---- alert banner
  readonly property string alertText: {
    if (app && app.llmKeyMissing)
      return "No LLM key (" + app.llmKeyEnv + ") — predictions unavailable; playbooks still generate."
    if (hasReport && !predictionAvailable)
      return "Prediction unavailable for this report" +
        (prediction.reason ? ": " + String(prediction.reason) : ".")
    return ""
  }

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
  function rrTone(rr) { return rr >= 1.5 ? view.accent : view.urgent }
  function signedPct(n) { return (n >= 0 ? "+" : "") + Number(n).toFixed(2) + "%" }
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
    id: flick
    anchors.fill: parent
    contentWidth: width
    contentHeight: col.implicitHeight
    interactive: contentHeight > height
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    Column {
      id: col
      width: parent.width
      spacing: Style.space(12)

      // ---- header: coin tabs
      Item {
        width: parent.width
        height: Math.max(titleCol.implicitHeight, tabRow.implicitHeight)

        Column {
          id: titleCol
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)
          Text {
            text: "Dashboard"
            color: view.fg
            font.family: view.ff
            font.pixelSize: Style.font.heading
          }
          Note {
            text: view.hasReport
              ? "Generated " + view.shortDate(view.report.generated_at) + (view.report.sample ? "  ·  sample" : "")
              : "No report yet"
            color: view.dimmer
          }
        }

        Row {
          id: tabRow
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)
          Repeater {
            model: view.coinTabs
            delegate: Rectangle {
              required property var modelData
              readonly property bool current: view.activeCoin === String(modelData)
              width: tabLabel.implicitWidth + Style.space(22)
              height: tabLabel.implicitHeight + Style.space(10)
              radius: height / 2
              color: current ? Style.selectedAccentFill : "transparent"
              border.width: Style.selectedBorderWidth
              border.color: current ? Style.selectedBorderColor : "transparent"
              Behavior on color { ColorAnimation { duration: 120 } }
              Behavior on border.color { ColorAnimation { duration: 120 } }
              Text {
                id: tabLabel
                anchors.centerIn: parent
                text: String(parent.modelData)
                color: parent.current ? view.accent : view.dim
                font.family: view.ff
                font.pixelSize: Style.font.caption
                font.bold: parent.current
              }
              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: if (view.app) view.app.selectCoin(String(parent.modelData))
              }
            }
          }
        }
      }

      // ---- four metric cards
      Row {
        id: metrics
        width: parent.width
        spacing: Style.space(12)
        readonly property real cellWidth: (metrics.width - metrics.spacing * 3) / 4

        MetricCard {
          app: view.app
          width: metrics.cellWidth
          label: "LIVE PRICE"
          value: view.hasReport && isFinite(app ? app.price : NaN) ? "$" + view.price(app.price) : "—"
          sub: isFinite(view.change24h) ? "24h " + view.signedPct(view.change24h) : "no 24h baseline"
        }
        MetricCard {
          app: view.app
          width: metrics.cellWidth
          label: "BIAS"
          value: app && app.biasLabel !== "" ? app.biasLabel : "UNSET"
          sub: "trend structure (analysis)"
          tone: app ? app.biasColor : view.fg
        }
        MetricCard {
          app: view.app
          width: metrics.cellWidth
          label: "CONFIDENCE"
          value: view.confidenceLabel
          sub: view.predictionAvailable ? "subjective estimate" : "prediction unavailable"
          tone: view.predictionAvailable ? view.accent : view.dim
        }
        MetricCard {
          app: view.app
          width: metrics.cellWidth
          label: "BEST R:R"
          value: isFinite(view.bestRR) ? view.num(view.bestRR, 2) : "—"
          sub: view.positions.length > 0 ? "best of " + view.positions.length + " setups" : "no setups"
          tone: isFinite(view.bestRR) ? view.rrTone(view.bestRR) : view.dim
        }
      }

      // ---- alert banner
      Rectangle {
        id: alertBanner
        width: parent.width
        visible: view.alertText !== ""
        height: alertRow.height + Style.space(20)
        radius: Style.cornerRadius
        color: "transparent"
        border.width: Style.normalBorderWidth
        border.color: view.urgent
        Row {
          id: alertRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(12)
          anchors.rightMargin: Style.space(12)
          spacing: Style.space(10)
          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "\uf071"
            color: view.urgent
            font.family: view.ff
            font.pixelSize: Style.font.body
          }
          Note {
            id: alertNote
            width: parent.width - Style.space(24)
            anchors.verticalCenter: parent.verticalCenter
            text: view.alertText
            color: view.urgent
            font.pixelSize: Style.font.bodySmall
          }
        }
      }

      // ---- ENTRY / EXIT MAP + PREDICTION SCENARIOS
      Row {
        id: rowA
        width: parent.width
        spacing: Style.space(12)
        readonly property real leftWidth: Math.floor((rowA.width - rowA.spacing) * 0.56)
        readonly property real rightWidth: rowA.width - rowA.spacing - leftWidth

        TitledCard {
          id: entryCard
          app: view.app
          width: rowA.leftWidth
          title: "ENTRY & EXIT MAP"

          Row {
            id: entryHead
            width: parent.width
            spacing: Style.space(8)
            Caption { width: Style.space(40); text: "TF" }
            Caption { width: Style.space(54); text: "DIR" }
            Caption { width: Style.space(64); text: "ENTRY" }
            Caption { width: Style.space(64); text: "TP1" }
            Caption { width: Style.space(64); text: "TP2" }
            Caption { width: Style.space(64); text: "STOP" }
            Caption { text: "R:R" }
          }

          Body {
            visible: view.positions.length === 0
            width: parent.width
            text: view.hasSourceFallback
              ? "No structured levels in this report — see the source document below."
              : "No structured levels in this report."
            color: view.dim
          }

          Repeater {
            model: view.positions
            delegate: Row {
              id: posRow
              required property var modelData
              width: entryCard.width - entryCard.pad * 2
              spacing: Style.space(8)
              height: Style.space(26)
              Body {
                width: Style.space(40)
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: String(posRow.modelData.timeframe || "")
                color: view.dim
                font.pixelSize: Style.font.bodySmall
              }
              Body {
                width: Style.space(54)
                anchors.verticalCenter: parent.verticalCenter
                text: String(posRow.modelData.direction || "")
                color: view.dirTone(posRow.modelData.direction)
                font.bold: true
                font.pixelSize: Style.font.bodySmall
              }
              Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(64); text: view.price(posRow.modelData.entry); font.pixelSize: Style.font.bodySmall }
              Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(64); text: view.price(posRow.modelData.tp1); font.pixelSize: Style.font.bodySmall }
              Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(64); text: view.price(posRow.modelData.tp2); font.pixelSize: Style.font.bodySmall }
              Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(64); text: view.price(posRow.modelData.stop); color: view.urgent; font.pixelSize: Style.font.bodySmall }
              Body { anchors.verticalCenter: parent.verticalCenter; text: view.num(posRow.modelData.rr, 2); color: view.rrTone(Number(posRow.modelData.rr)); font.pixelSize: Style.font.bodySmall }
            }
          }

          Note {
            visible: view.support.length > 0 || view.resistance.length > 0
            width: parent.width
            text: "Support  " + view.support.join(" · ") + "\nResistance  " + view.resistance.join(" · ")
            color: view.dimmer
            font.pixelSize: Style.font.caption
          }
        }

        TitledCard {
          id: scenarioCard
          app: view.app
          width: rowA.rightWidth
          title: "PREDICTION SCENARIOS"

          Body {
            visible: !view.predictionAvailable
            width: parent.width
            text: "Prediction unavailable" +
              (view.prediction.reason ? ": " + String(view.prediction.reason) : ".") +
              (view.hasSourceFallback ? " See the source document below." : "")
            color: view.dim
          }

          Repeater {
            model: view.scenarioGroups
            delegate: Column {
              id: group
              required property var modelData
              width: scenarioCard.width - scenarioCard.pad * 2
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
                  spacing: Style.space(8)
                  height: Style.space(22)
                  Body {
                    width: parent.width - Style.space(150)
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: String(scenarioRow.modelData.label || "")
                    font.pixelSize: Style.font.bodySmall
                  }
                  Note {
                    width: Style.space(104)
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
            visible: view.predictionAvailable
            width: parent.width
            text: "Probabilities are the model's subjective estimates, not measured win rates."
            color: view.dimmer
          }
          Note { visible: view.predictionAvailable && !!view.prediction.favored_trade; width: parent.width; text: "FAVORED  " + String(view.prediction.favored_trade || "") }
          Note { visible: view.predictionAvailable && !!view.prediction.confirmation; width: parent.width; text: "CONFIRMATION  " + String(view.prediction.confirmation || "") }
          Note { visible: view.predictionAvailable && !!view.prediction.invalidation; width: parent.width; text: "INVALIDATION  " + String(view.prediction.invalidation || "") }
          Note { visible: view.predictionAvailable && !!view.prediction.bottom_line; width: parent.width; text: "BOTTOM LINE  " + String(view.prediction.bottom_line || ""); color: view.fg }
        }
      }

      // ---- INDICATOR DASHBOARD (full width)
      TitledCard {
        id: indicatorCard
        app: view.app
        width: parent.width
        title: "INDICATOR DASHBOARD"

        Row {
          id: indicatorHead
          width: parent.width
          spacing: Style.space(8)
          Caption { width: Style.space(40); text: "TF" }
          Caption { width: Style.space(80); text: "PRICE" }
          Caption { width: Style.space(56); text: "RSI" }
          Caption { width: Style.space(72); text: "MACD H" }
          Caption { width: Style.space(90); text: "TREND" }
          Caption { width: indicatorCard.width - indicatorCard.pad * 2 - Style.space(40 + 80 + 56 + 72 + 90 + 64) - Style.space(8) * 6; text: "BB LOWER / MID / UPPER" }
          Caption { text: "ATR" }
        }

        Body {
          visible: view.indicatorRows.length === 0
          width: parent.width
          text: view.hasSourceFallback ? "No structured indicators — see the source document below." : "No indicator data in this report."
          color: view.dim
        }

        Repeater {
          model: view.indicatorRows
          delegate: Row {
            id: indRow
            required property var modelData
            width: indicatorCard.width - indicatorCard.pad * 2
            spacing: Style.space(8)
            height: Style.space(26)
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(40); text: String(indRow.modelData.tf); color: view.accent; font.bold: true; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(80); text: view.num(indRow.modelData.price, 2); font.pixelSize: Style.font.bodySmall }
            Body {
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(56)
              font.pixelSize: Style.font.bodySmall
              readonly property real rsi: Number(indRow.modelData.rsi)
              text: view.num(indRow.modelData.rsi, 1)
              color: rsi < 30 ? view.accent : rsi > 70 ? view.urgent : view.fg
            }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(72); text: view.num(indRow.modelData.hist, 2); font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: Style.space(90); elide: Text.ElideRight; text: String(indRow.modelData.trend); color: indRow.modelData.trend === "bullish" ? view.bullish : indRow.modelData.trend === "bearish" ? view.bearish : view.dim; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; width: indicatorCard.width - indicatorCard.pad * 2 - Style.space(40 + 80 + 56 + 72 + 90 + 64) - Style.space(8) * 6; elide: Text.ElideRight; text: String(indRow.modelData.bands); color: view.dim; font.pixelSize: Style.font.bodySmall }
            Body { anchors.verticalCenter: parent.verticalCenter; text: view.num(indRow.modelData.atr, 2); color: view.dim; font.pixelSize: Style.font.bodySmall }
          }
        }
      }

      // ---- RECENT REPORTS (full width)
      TitledCard {
        id: recentCard
        app: view.app
        width: parent.width
        title: "RECENT REPORTS"

        Body {
          visible: view.recentReports.length === 0
          width: parent.width
          text: "No reports yet. The daemon writes one on its interval, or press r to regenerate."
          color: view.dim
        }
        Repeater {
          model: view.recentReports
          delegate: Item {
            id: recentRow
            required property var modelData
            width: recentCard.width - recentCard.pad * 2
            height: Style.space(28)
            Body {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(90)
              text: String(recentRow.modelData.coin || "")
              font.pixelSize: Style.font.bodySmall
            }
            Note {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(90)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(180)
              text: view.shortDate(recentRow.modelData.generated_at)
              color: view.dimmer
            }
            Note {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(270)
              anchors.verticalCenter: parent.verticalCenter
              visible: recentRow.modelData.sample === true
              text: "SAMPLE"
              color: view.accent
              font.letterSpacing: 1
              font.pixelSize: Style.font.caption
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
                onClicked: if (view.app) view.app.showReport(String(recentRow.modelData.id || ""), "playbooks")
              }
            }
          }
        }
        Note {
          visible: view.recentReports.length > 0
          text: "press 5 for the full history"
          color: view.dimmer
        }
      }

      // ---- SOURCE DOCUMENT (samples only, when nothing structured parsed)
      TitledCard {
        id: sourceCard
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
          height: Style.space(260)
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
