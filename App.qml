import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The application. The shell loads this Item when the panel is opened and
// calls open() and close() on it; the window itself is ours.
Item {
  id: root

  // Injected by the shell.
  property var shell: null
  property var manifest: null
  property var service: null
  property bool opened: false
  property bool closingFromHost: false

  readonly property string pluginId: manifest && manifest.id ? String(manifest.id) : "windong.cryptoplaybook"

  // ---- theme tokens, derived so the app follows whatever theme is running
  readonly property color foreground: Color.foreground
  readonly property color background: Color.background
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property color cardBorder: Style.normalBorderColor
  readonly property color dim: Qt.rgba(
    foreground.r * 0.68 + background.r * 0.32,
    foreground.g * 0.68 + background.g * 0.32,
    foreground.b * 0.68 + background.b * 0.32, 1)
  readonly property color dimmer: Qt.rgba(
    foreground.r * 0.45 + background.r * 0.55,
    foreground.g * 0.45 + background.g * 0.55,
    foreground.b * 0.45 + background.b * 0.55, 1)
  // Semantic colours, defined once and derived from the theme's own tokens:
  // long/bullish reads as accent, short/bearish as urgent, neutral as
  // plain foreground.
  readonly property color bullish: accent
  readonly property color bearish: urgent
  readonly property color neutral: foreground
  readonly property string fontFamily: Style.font.family

  // The kit hardcodes its durations per component, so the house language is
  // named once here and referenced from everywhere: a colour settles
  // quickly, geometry and opacity take the longer curve.
  readonly property int quickMs: 60
  readonly property int colourMs: 120
  readonly property int moveMs: 140

  // ---- the daemon
  readonly property string pluginDir: Qt.resolvedUrl(".").toString()
                                        .replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string helperPath: pluginDir + "/bin/playbook"
  readonly property string addr: "127.0.0.1:8099"
  readonly property bool built: !!service && service.built === true
  readonly property bool running: !!service && service.running === true

  readonly property var childEnv: ({
    "PATH": "/usr/bin:/bin",
    "HOME": Quickshell.env("HOME") || "",
    "XDG_CONFIG_HOME": Quickshell.env("XDG_CONFIG_HOME") || "",
    "XDG_DATA_HOME": Quickshell.env("XDG_DATA_HOME") || ""
  })

  // The latest report document ({"available": ...}), re-read after every
  // change and on a timer.
  property var snap: null
  // The daemon status document (coins, report count, run state, LLM key).
  property var status: null
  property string lastError: ""
  property string toast: ""

  // Fired after a change went through, so a view re-reads what it shows.
  signal changed()

  function refresh() {
    if (!root.running) return
    if (!fetchProc.running) fetchProc.running = true
    if (!statusProc.running) statusProc.running = true
  }

  // ---- derived report state
  readonly property var report: snap && snap.available === true ? snap.report : null
  readonly property bool hasReport: report !== null
  readonly property string primaryCoin: {
    if (report && report.coin) return String(report.coin)
    var coins = status && Array.isArray(status.coins) ? status.coins : []
    return coins.length > 0 ? String(coins[0]) : "BTC/USDT"
  }
  readonly property bool llmKeyMissing: status !== null && status.llm_key_present === false
  readonly property string llmKeyEnv: status && status.llm_key_env ? String(status.llm_key_env) : "OPENAI_API_KEY"
  readonly property var generating: status && Array.isArray(status.generating) ? status.generating : []

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
    bias === "bullish" ? bullish : bias === "bearish" ? bearish : neutral
  readonly property bool predictionAvailable:
    report && report.prediction && report.prediction.available === true

  function formatPrice(p) {
    if (!isFinite(p)) return "—"
    var d = p >= 100 ? 0 : p >= 1 ? 2 : 6
    var s = p.toFixed(d)
    var parts = s.split(".")
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",")
    return parts.join(".")
  }

  // Reads on behalf of a view: one at a time, the answer parsed and handed
  // to the callback as (data, errorText).
  property var queryQueue: []
  property var queryCallback: null

  function query(argv, cb) {
    if (!root.running) { if (cb) cb(null, "the daemon is not running"); return }
    root.queryQueue.push({ argv: argv, cb: cb })
    root.pumpQueries()
  }

  function pumpQueries() {
    if (queryProc.running || root.queryQueue.length === 0) return
    var job = root.queryQueue.shift()
    root.queryCallback = job.cb
    queryProc.out = ""
    queryProc.errText = ""
    queryProc.command = [root.helperPath].concat(job.argv).concat(["-addr", root.addr])
    queryProc.running = true
  }

  Process {
    id: queryProc
    clearEnvironment: true
    environment: root.childEnv
    property string out: ""
    property string errText: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: queryProc.out = String(text || "")
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: queryProc.errText = String(text || "").trim()
    }
    onExited: function (code, status) {
      var cb = root.queryCallback
      root.queryCallback = null
      var data = null
      var err = ""
      if (code === 0) {
        try { data = JSON.parse(queryProc.out) } catch (e) { err = "unreadable answer from the helper" }
      } else {
        err = queryProc.errText.split("\n")[0] || ("the helper exited with " + code)
      }
      if (cb) cb(data, err)
      Qt.callLater(root.pumpQueries)
    }
  }

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
        try { root.snap = JSON.parse(raw); root.lastError = "" }
        catch (e) { root.lastError = "could not read the latest report" }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var msg = String(text || "").trim()
        if (msg !== "") root.lastError = msg.split("\n")[0]
      }
    }
  }

  Process {
    id: statusProc
    command: [root.helperPath, "status", "-addr", root.addr]
    clearEnvironment: true
    environment: root.childEnv
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw === "") return
        try { root.status = JSON.parse(raw) } catch (e) { root.status = null }
      }
    }
  }

  // Every mutation goes through the CLI as an argv array: no shell, no string
  // building, the daemon's own validation, and stderr is the message shown.
  Process {
    id: mutateProc
    clearEnvironment: true
    environment: root.childEnv
    property string pending: ""
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var msg = String(text || "").trim()
        if (msg !== "") root.lastError = msg.split("\n")[0]
      }
    }
    onExited: function (code, status) {
      if (code === 0) {
        root.lastError = ""
        root.showToast(mutateProc.pending)
        root.refresh()
        root.changed()
      }
      mutateProc.pending = ""
      Qt.callLater(root.pumpMutations)
    }
  }

  // Changes queue rather than collide: a second submit while the first is
  // still running used to be dropped without a word.
  property var mutateQueue: []

  function run(argv, doneText) {
    root.mutateQueue.push({ argv: argv, done: doneText || "" })
    root.pumpMutations()
  }

  function pumpMutations() {
    if (mutateProc.running || root.mutateQueue.length === 0) return
    var job = root.mutateQueue.shift()
    mutateProc.pending = job.done
    mutateProc.command = [root.helperPath].concat(job.argv).concat(["-addr", root.addr])
    mutateProc.running = true
  }

  function showToast(text) {
    root.toast = text
    toastTimer.restart()
  }
  Timer { id: toastTimer; interval: 4000; onTriggered: root.toast = "" }

  // Nothing here may run for ever: a read or a write that hangs is stopped.
  Timer {
    interval: 15000
    repeat: false
    running: fetchProc.running || statusProc.running || mutateProc.running || queryProc.running
    onTriggered: {
      if (fetchProc.running) fetchProc.running = false
      if (statusProc.running) statusProc.running = false
      if (queryProc.running) queryProc.running = false
      if (mutateProc.running) {
        mutateProc.running = false
        root.mutateQueue = []
        root.lastError = "the helper did not answer"
      }
    }
  }

  onRunningChanged: if (running) Qt.callLater(root.refresh)
  onOpenedChanged: if (opened) Qt.callLater(root.refresh)
  Timer {
    interval: 30000
    running: root.opened && root.running
    repeat: true
    onTriggered: root.refresh()
  }

  // ---- navigation
  readonly property var views: [
    { id: "dashboard", label: "Dashboard", key: "1", glyph: "\uf201" },
    { id: "playbooks", label: "Playbooks", key: "2", glyph: "\uf0f6" },
    { id: "predictions", label: "Predictions", key: "3", glyph: "\uf0eb" },
    { id: "coins", label: "Coins", key: "4", glyph: "\uf51e" },
    { id: "history", label: "History", key: "5", glyph: "\uf017" },
    { id: "settings", label: "Settings", key: "6", glyph: "\uf013" },
    { id: "privacy", label: "Data & Privacy", key: "7", glyph: "\uf023" }
  ]
  property string view: "dashboard"
  property int navCursor: 0

  function setView(id) {
    for (var i = 0; i < views.length; i++) {
      if (views[i].id === id) { root.view = id; root.navCursor = i; return }
    }
  }

  function viewLabel(id) {
    for (var i = 0; i < views.length; i++)
      if (views[i].id === id) return views[i].label
    return id
  }

  // ---- shell contract
  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(String(payloadJson || "{}")) || ({}) } catch (e) {}
    closingFromHost = false
    opened = true
    if (payload.view) root.setView(String(payload.view))
    Qt.callLater(function () { focusScope.forceActiveFocus() })
  }

  function close() {
    closingFromHost = true
    opened = false
    closingFromHost = false
  }

  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  FloatingWindow {
    id: window
    visible: root.opened
    title: "Crypto Playbook"
    color: root.background
    implicitWidth: Style.space(1180)
    implicitHeight: Style.space(720)
    minimumSize: Qt.size(Style.space(880), Style.space(560))

    onVisibleChanged: {
      if (!visible && root.opened && !root.closingFromHost) root.requestClose()
    }

    FocusScope {
      id: focusScope
      anchors.fill: parent
      focus: true

      Keys.onPressed: function (e) {
        if (e.key === Qt.Key_Escape) {
          root.requestClose()
          e.accepted = true; return
        }
        if (e.modifiers !== Qt.NoModifier) return
        if (e.key === Qt.Key_R) { root.refresh(); e.accepted = true; return }
        if (e.key === Qt.Key_J || e.key === Qt.Key_Down) {
          root.navCursor = (root.navCursor + 1) % root.views.length
          root.view = root.views[root.navCursor].id
          e.accepted = true; return
        }
        if (e.key === Qt.Key_K || e.key === Qt.Key_Up) {
          root.navCursor = (root.navCursor - 1 + root.views.length) % root.views.length
          root.view = root.views[root.navCursor].id
          e.accepted = true; return
        }
        for (var i = 0; i < root.views.length; i++) {
          if (e.text === root.views[i].key) { root.setView(root.views[i].id); e.accepted = true; return }
        }
      }

      RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- nav rail
        Sidebar {
          Layout.fillHeight: true
          Layout.preferredWidth: Style.space(220)
          app: root
          manifest: root.manifest
        }

        // ---- content
        Item {
          Layout.fillWidth: true
          Layout.fillHeight: true

          // Until the daemon is built and running, this is the working
          // state; then the latest report, or the onboarding when the
          // store is empty or the LLM key is missing.
          Column {
            anchors.centerIn: parent
            visible: !root.running
            spacing: Style.space(10)
            width: Math.min(parent.width - Style.space(48), Style.space(520))

            Text {
              text: root.built ? "The daemon is not running" : "Not installed yet"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
            }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: root.built
                ? (root.service && root.service.lastError ? root.service.lastError : "It should start on its own within a few seconds.")
                : "The helpers are not in this plugin directory yet. Reinstall the plugin so bin/playbookd and bin/playbook land next to the screens."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          // Onboarding: on the daemon but nothing to show yet.
          Column {
            anchors.centerIn: parent
            visible: root.running && !root.hasReport
            spacing: Style.space(10)
            width: Math.min(parent.width - Style.space(48), Style.space(520))

            Text {
              text: "No playbook yet"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
            }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: "The daemon is running but the store holds no report for this coin. One is generated per configured coin on the configured interval (default 60 minutes), or press r to regenerate now."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              visible: root.llmKeyMissing
              text: "No LLM key configured (no key): the environment variable " + root.llmKeyEnv + " holds nothing for the daemon, so predictions stay unavailable. Set it and restart the daemon to ground the prediction blocks; playbooks themselves still generate."
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          // The latest report at a glance. The per-section screens land in
          // the following tasks; this proves the pipeline end to end.
          Column {
            anchors.centerIn: parent
            visible: root.running && root.hasReport
            spacing: Style.space(12)
            width: Math.min(parent.width - Style.space(48), Style.space(560))

            Text {
              text: root.viewLabel(root.view).toUpperCase()
              color: root.dimmer
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              text: root.report && root.report.coin ? String(root.report.coin) : ""
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              font.bold: true
            }
            Row {
              spacing: Style.space(16)
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: isFinite(root.price) ? "$" + root.formatPrice(root.price) : "—"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.heading
              }
              Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: biasChip.implicitWidth + Style.space(20)
                height: biasChip.implicitHeight + Style.space(8)
                radius: height / 2
                color: "transparent"
                border.width: Style.normalBorderWidth
                border.color: root.biasColor
                Text {
                  id: biasChip
                  anchors.centerIn: parent
                  text: root.biasLabel === "" ? "UNSET" : root.biasLabel
                  color: root.biasColor
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
              }
            }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: "Generated " + (root.report && root.report.generated_at ? String(root.report.generated_at) : "unknown")
                + " · prediction " + (root.predictionAvailable ? "available" : "unavailable")
                + (root.generating.length > 0 ? " · regenerating " + root.generating.join(", ") : "")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              visible: root.llmKeyMissing
              text: "No LLM key configured (no key): set " + root.llmKeyEnv + " before starting the daemon to ground the prediction blocks."
              color: root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // The message line: an error from the last command, or a toast.
          Rectangle {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            readonly property bool showing: root.lastError !== "" || root.toast !== ""
            height: showing ? Style.space(32) : 0
            visible: height > 0
            opacity: showing ? 1 : 0
            color: root.background
            Behavior on height { NumberAnimation { duration: root.moveMs; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: root.moveMs; easing.type: Easing.OutCubic } }
            Rectangle { anchors.top: parent.top; width: parent.width; height: Style.spacing.hairline; color: root.cardBorder }
            Row {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(20)
              anchors.right: parent.right
              anchors.rightMargin: Style.space(20)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)
              readonly property bool failed: root.lastError !== ""
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: parent.failed ? "\uf071" : "\uf00c"
                color: parent.failed ? root.urgent : root.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - Style.space(28)
                text: parent.failed ? root.lastError : root.toast
                color: parent.failed ? root.urgent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
            }
          }
        }
      }
    }
  }
}
