import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The glance: this coin's live price and the current bias, read from the
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

  // The last read of `playbook latest`. Null until the daemon has answered
  // once; {"available": false} when the store is empty.
  property var snap: null

  readonly property var report: snap && snap.available === true ? snap.report : null

  // The price this report speaks about: the first live quote, falling back
  // to the indicator payload of the freshest timeframe when quotes failed.
  readonly property real price: {
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
  readonly property string bias: {
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
  readonly property string biasLabel:
    bias === "bullish" ? "LONG" : bias === "bearish" ? "SHORT" : bias === "flat" ? "FLAT" : ""
  readonly property color biasColor:
    bias === "bullish" ? accent : bias === "bearish" ? urgent : foreground

  // What the bar shows. A dash until the daemon answers, so a fresh install
  // shows a placeholder rather than a stale or invented number.
  readonly property string figure: {
    if (!isFinite(price)) return "—"
    var s = formatPrice(price)
    return biasLabel === "" ? s : s + " · " + biasLabel
  }

  function formatPrice(p) {
    var d = p >= 100 ? 0 : p >= 1 ? 2 : 6
    var s = p.toFixed(d)
    var parts = s.split(".")
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    return parts.join(".")
  }

  implicitWidth: row.implicitWidth
  implicitHeight: button.implicitHeight

  function toggleApp() {
    if (bar && bar.shell && typeof bar.shell.toggle === "function")
      bar.shell.toggle("windong.cryptoplaybook", "{}")
  }

  function refresh() {
    if (!root.running || fetchProc.running) return
    fetchProc.running = true
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

  Process {
    id: fetchProc
    command: [root.helperPath, "latest", "-addr", root.addr]
    clearEnvironment: true
    environment: root.childEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw === "") return
        try { root.snap = JSON.parse(raw) } catch (e) { root.snap = null }
      }
    }
  }

  // A read that never returns must not sit on a collector forever.
  Timer {
    interval: 15000
    repeat: false
    running: fetchProc.running
    onTriggered: if (fetchProc.running) fetchProc.running = false
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
