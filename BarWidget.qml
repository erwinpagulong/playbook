import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The glance: live prices and biases for every configured coin, read from the
// daemon on a timer. Clicking opens the app as its own window.
BarWidget {
  id: root

  moduleName: "windong.cryptoplaybook"

  readonly property var service: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor("windong.cryptoplaybook") : null

  readonly property string addr: setting("addr", "127.0.0.1:8099")
  readonly property int refreshSec: Math.max(5, Number(setting("refreshSec", 30)))

  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property bool built: !!service && service.built === true
  readonly property bool running: !!service && service.running === true

  readonly property string pluginDir: Qt.resolvedUrl(".").toString()
                                        .replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string helperPath: pluginDir + "/bin/playbook"

  // Configured coins and the newest report for each, keyed by coin string.
  // Null/unparseable replies are ignored so a transient daemon failure never
  // replaces a good snapshot with a stale or invented number.
  property var coins: []
  property var snaps: ({})
  property var latestQueue: []
  property string pendingCoin: ""

  readonly property string primaryCoin: coins.length > 0 ? String(coins[0]) : ""

  function reportFor(coin) {
    var snap = snaps[coin]
    return snap && snap.available === true ? snap.report : null
  }

  // The price this report speaks about: the first live quote, falling back
  // to the indicator payload of the freshest timeframe when quotes failed.
  function priceFor(coin) {
    var report = reportFor(coin)
    if (!report) return NaN
    var sources = report.snapshot && report.snapshot.sources
    if (Array.isArray(sources)) {
      for (var i = 0; i < sources.length; i++) {
        var p = Number(sources[i] && sources[i].price)
        if (isFinite(p) && p > 0) return p
      }
    }
    var ind = report.indicators || {}
    var order = ["1D", "4h", "15m"]
    for (var j = 0; j < order.length; j++) {
      var t = ind[order[j]]
      var pp = t ? Number(t.price) : NaN
      if (isFinite(pp) && pp > 0) return pp
    }
    return NaN
  }

  // The bias, from the daily trend first and the faster timeframes behind
  // it. bullish = LONG (accent), bearish = SHORT (urgent), flat = neutral.
  function biasFor(coin) {
    var report = reportFor(coin)
    if (!report) return ""
    var ind = report.indicators || {}
    var order = ["1D", "4h", "15m"]
    for (var i = 0; i < order.length; i++) {
      var t = ind[order[i]]
      if (t && t.trend) return String(t.trend).toLowerCase()
    }
    for (var k in ind) {
      if (ind[k] && ind[k].trend) return String(ind[k].trend).toLowerCase()
    }
    return ""
  }

  function biasColorFor(coin) {
    var b = biasFor(coin)
    return b === "bullish" ? accent : b === "bearish" ? urgent : foreground
  }

  function formatPrice(p) {
    var d = p >= 100 ? 0 : p >= 1 ? 2 : 6
    var s = p.toFixed(d)
    var parts = s.split(".")
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    return parts.join(".")
  }

  function figureFor(coin) {
    var p = priceFor(coin)
    if (!isFinite(p)) return "—"
    var s = formatPrice(p)
    var b = biasFor(coin)
    var label = b === "bullish" ? "LONG" : b === "bearish" ? "SHORT" : b === "flat" ? "FLAT" : ""
    return label === "" ? s : s + " · " + label
  }

  // Single-coin view used until the marquee rendering replaces it.
  readonly property var report: reportFor(primaryCoin)
  readonly property real price: priceFor(primaryCoin)
  readonly property string bias: biasFor(primaryCoin)
  readonly property string biasLabel:
    bias === "bullish" ? "LONG" : bias === "bearish" ? "SHORT" : bias === "flat" ? "FLAT" : ""
  readonly property color biasColor: biasColorFor(primaryCoin)
  readonly property string figure: figureFor(primaryCoin)

  implicitWidth: row.implicitWidth
  implicitHeight: button.implicitHeight

  function toggleApp() {
    if (bar && bar.shell && typeof bar.shell.toggle === "function")
      bar.shell.toggle("windong.cryptoplaybook", "{}")
  }

  function pumpQueue() {
    if (!root.running || coinsProc.running || latestProc.running) return
    if (root.latestQueue.length === 0) return
    var coin = root.latestQueue.shift()
    root.pendingCoin = coin
    latestProc.command = [root.helperPath, "latest", coin, "-addr", root.addr]
    latestProc.running = true
  }

  function refresh() {
    if (!root.running || coinsProc.running || latestProc.running) return
    coinsProc.running = true
  }

  onRunningChanged: if (running) Qt.callLater(root.refresh)
  Component.onCompleted: Qt.callLater(root.refresh)

  Timer {
    interval: root.refreshSec * 1000
    running: root.running
    repeat: true
    onTriggered: root.refresh()
  }

  readonly property var childEnv: ({
    "PATH": "/usr/bin:/bin",
    "HOME": Quickshell.env("HOME") || "",
    "XDG_CONFIG_HOME": Quickshell.env("XDG_CONFIG_HOME") || "",
    "XDG_DATA_HOME": Quickshell.env("XDG_DATA_HOME") || ""
  })

  // The configured coin list. Re-read on every refresh so Settings changes
  // are picked up without restarting the shell.
  Process {
    id: coinsProc
    command: [root.helperPath, "coins", "-addr", root.addr]
    clearEnvironment: true
    environment: root.childEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw !== "") {
          try {
            var parsed = JSON.parse(raw)
            if (Array.isArray(parsed)) {
              var list = []
              for (var i = 0; i < parsed.length; i++) {
                if (typeof parsed[i] === "string" && parsed[i] !== "") list.push(parsed[i])
              }
              root.coins = list
            }
          } catch (e) { /* keep the previous list */ }
        }
        root.latestQueue = root.coins.slice()
        root.pumpQueue()
      }
    }
  }

  // A read that never returns must not sit on a collector forever.
  Timer {
    interval: 15000
    repeat: false
    running: coinsProc.running
    onTriggered: {
      if (coinsProc.running) coinsProc.running = false
      root.latestQueue = root.coins.slice()
      root.pumpQueue()
    }
  }

  Process {
    id: latestProc
    command: []
    clearEnvironment: true
    environment: root.childEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var coin = root.pendingCoin
        root.pendingCoin = ""
        var raw = String(text || "").trim()
        if (coin !== "" && raw !== "") {
          try {
            var parsed = JSON.parse(raw)
            if (parsed && typeof parsed === "object") {
              var copy = Object.assign({}, root.snaps)
              copy[coin] = parsed
              root.snaps = copy
            }
          } catch (e) { /* keep the previous snapshot for this coin */ }
        }
        root.pumpQueue()
      }
    }
  }

  Timer {
    interval: 15000
    repeat: false
    running: latestProc.running
    onTriggered: {
      if (latestProc.running) latestProc.running = false
      root.pendingCoin = ""
      root.pumpQueue()
    }
  }

  Row {
    id: row
    anchors.verticalCenter: parent.verticalCenter
    spacing: 0

    BarIconButton {
      id: button
      bar: root.bar
      // The bar always carries the glyph, so a plugin that has never been
      // built still has something to click: the app is where the build is.
      text: "\uf201"
      labelVisible: false
      tooltipText: !root.built ? "CRYPTO PLAYBOOK: not installed yet, open to set up"
                 : !root.running ? "CRYPTO PLAYBOOK: daemon not running"
                 : root.report && root.figure !== "—" && root.report.coin
                   ? "CRYPTO PLAYBOOK: " + root.report.coin + " " + root.figure
                     + (root.report.generated_at ? " since " + root.report.generated_at : "")
                   : "CRYPTO PLAYBOOK: no report yet"
      dimmed: !root.running
      onPressed: root.toggleApp()
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.running
      text: root.figure
      // Longs read as accent, shorts as urgent, everything else as plain
      // foreground — the theme's own tokens, never a fixed hex.
      color: root.report ? root.biasColor : root.foreground
      font.family: bar ? bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.bodySmall
      rightPadding: Style.space(6)
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggleApp()
      }
    }
  }
}
