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

  // "BTC/USDT" -> "BTC"; the base symbol is what a glance needs.
  function symbolFor(coin) {
    var parts = String(coin || "").split("/")
    return parts.length > 0 ? parts[0] : ""
  }

  function figureFor(coin) {
    var sym = symbolFor(coin)
    var prefix = sym !== "" ? sym + " " : ""
    var p = priceFor(coin)
    if (!isFinite(p)) return prefix + "—"
    var s = formatPrice(p)
    var b = biasFor(coin)
    var label = b === "bullish" ? "LONG" : b === "bearish" ? "SHORT" : b === "flat" ? "FLAT" : ""
    return prefix + (label === "" ? s : s + " · " + label)
  }

  // Marquee geometry. The strip holds one copy per coin followed by the same
  // copy again, so scrolling exactly one copy width loops without a seam.
  readonly property real viewportWidth: Style.space(240)
  readonly property real figureWidth: Style.space(120)
  readonly property real figureSpacing: Style.space(12)
  readonly property real pxPerSec: 30
  readonly property real copyWidth: coins.length * (figureWidth + figureSpacing)
  property real offset: 0

  onCopyWidthChanged: root.offset = root.offset % (root.copyWidth > 0 ? root.copyWidth : 1)

  readonly property string tooltipText: {
    if (!root.built) return "CRYPTO PLAYBOOK: setup needed — run ~/.config/omarchy/plugins/windong.cryptoplaybook/install.sh once"
    if (!root.running) return "CRYPTO PLAYBOOK: daemon not running"
    if (root.coins.length === 0) return "CRYPTO PLAYBOOK: no coins configured"
    var snapsRef = root.snaps
    var parts = []
    for (var i = 0; i < root.coins.length; i++)
      parts.push(root.coins[i] + " " + root.figureFor(root.coins[i]))
    return "CRYPTO PLAYBOOK: " + parts.join("   |   ")
  }

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
        if (coin !== "") {
          var copy = Object.assign({}, root.snaps)
          if (raw !== "") {
            try {
              var parsed = JSON.parse(raw)
              if (parsed && typeof parsed === "object") copy[coin] = parsed
              else delete copy[coin]
            } catch (e) { delete copy[coin] }
          } else {
            delete copy[coin]
          }
          root.snaps = copy
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
      tooltipText: root.tooltipText
      dimmed: !root.running
      onPressed: root.toggleApp()
    }

    Item {
      id: viewport
      anchors.verticalCenter: parent.verticalCenter
      width: root.viewportWidth
      height: button.implicitHeight
      clip: true
      visible: root.running

      Row {
        id: ticker
        anchors.verticalCenter: parent.verticalCenter
        x: -root.offset
        spacing: root.figureSpacing
        Repeater {
          // The snaps read keeps figures fresh after each refresh cycle.
          model: { var latest = root.snaps; return root.coins.length > 1 ? root.coins.concat(root.coins) : [] }
          delegate: Item {
            width: root.figureWidth
            height: viewport.height
            Text {
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width
              elide: Text.ElideRight
              text: root.figureFor(modelData)
              // Longs read as accent, shorts as urgent, everything else as
              // foreground — the theme's own tokens, never a fixed hex.
              color: root.biasColorFor(modelData)
              font.family: bar ? bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      // A stepped offset keeps the wrap exact and makes hover pause simply a
      // matter of stopping the clock — no animation restart/jump on resume.
      Timer {
        interval: 33
        repeat: true
        running: root.coins.length > 1 && root.running && !marqueeMouse.containsMouse
        onTriggered: {
          if (root.copyWidth > 0)
            root.offset = (root.offset + root.pxPerSec * interval / 1000) % root.copyWidth
        }
      }

      Text {
        anchors.centerIn: parent
        visible: root.coins.length < 2
        text: root.coins.length === 1 ? root.figureFor(root.coins[0]) : "—"
        color: root.coins.length === 1 ? root.biasColorFor(root.coins[0]) : root.foreground
        font.family: bar ? bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      MouseArea {
        id: marqueeMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggleApp()
      }
    }
  }
}
