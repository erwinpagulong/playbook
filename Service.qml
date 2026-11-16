import QtQuick
import Quickshell
import Quickshell.Io

// The daemon, owned by the shell. Built when the plugin is enabled, destroyed
// when it is disabled or removed. No systemd unit is installed.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // Injected by the shell when it constructs the service.
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  readonly property string pluginDir: Qt.resolvedUrl(".").toString()
                                        .replace(/^file:\/\//, "").replace(/\/$/, "")
  readonly property string daemonPath: pluginDir + "/bin/playbookd"
  readonly property string helperPath: pluginDir + "/bin/playbook"

  // Respawn on failure, with backoff and a ceiling.
  readonly property int maxRestarts: 5
  property int restarts: 0
  property string lastError: ""
  // The bar and the app read these rather than probing the filesystem
  // themselves.
  property bool built: false
  property bool running: daemon.running

  function backoffMs() {
    return Math.min(30000, 1000 * Math.pow(2, root.restarts))
  }

  // Passed to every child. PATH reaches the interpreter in /usr/bin, HOME
  // finds the configuration and the data directory. The CLI helpers (in
  // App.qml) use this with a cleared environment; they never need the LLM key.
  // The daemon below deliberately keeps the full launch environment so it
  // inherits the exported variable that names the key (the config stores only
  // the variable's *name*, and the daemon reads its value from os.environ).
  readonly property var childEnv: ({
    "PATH": "/usr/bin:/bin",
    "HOME": Quickshell.env("HOME") || "",
    "XDG_CONFIG_HOME": Quickshell.env("XDG_CONFIG_HOME") || "",
    "XDG_DATA_HOME": Quickshell.env("XDG_DATA_HOME") || ""
  })

  // bin/ is not shipped, so a fresh clone has nothing to run. Both binaries
  // are checked: the app and the bar shell out to the CLI for every read,
  // and an install interrupted between the two leaves one without the
  // other, which would otherwise report built and then fail every query.
  Process {
    id: probe
    command: ["/usr/bin/test", "-x", root.daemonPath, "-a", "-x", root.helperPath]
    running: true
    clearEnvironment: true
    environment: root.childEnv

    onExited: function (code, status) {
      root.built = code === 0
      if (code === 0) {
        root.lastError = ""
        if (!daemon.running) daemon.running = true
        return
      }
      root.lastError = "not built yet"
      reprobe.restart()
    }
  }

  // Keep looking while there is nothing to run, so installing the helpers
  // starts the daemon without a shell restart.
  Timer {
    id: reprobe
    interval: 5000
    repeat: false
    onTriggered: if (!daemon.running) probe.running = true
  }

  Process {
    id: daemon
    command: [root.daemonPath]
    // Keep Quickshell's launch environment: the LLM API key is present only
    // as an exported variable there, and the daemon reads the value named by
    // llm.api_key_env from os.environ. Clearing the environment would strip
    // it and leave predictions permanently unavailable. PATH/HOME/XDG are
    // still overridden below via `environment`.
    clearEnvironment: false
    environment: root.childEnv

    onExited: function (code, status) {
      // A clean exit means it was told to stop.
      if (code === 0) return
      if (root.restarts >= root.maxRestarts) {
        root.lastError = "gave up after " + root.maxRestarts + " restarts"
        return
      }
      root.restarts++
      respawn.interval = root.backoffMs()
      respawn.restart()
    }

    stderr: StdioCollector {
      waitForEnd: false
      onStreamFinished: {
        var msg = String(text || "").trim()
        if (msg !== "") root.lastError = msg.split("\n")[0]
      }
    }
  }

  // Signal a process and its group. execDetached rather than a Process of our
  // own, because this is also called while this component is being destroyed,
  // and a Process owned by it would be torn down before it ran. A target that
  // has already gone makes kill fail harmlessly.
  function reap(pid) {
    if (!pid || pid <= 0) return
    Quickshell.execDetached(["/usr/bin/kill", "-TERM", "--", String(pid), "-" + pid])
  }

  // The probe is a one-shot test that should answer immediately. If it ever
  // does not, stop it rather than leaving a process and its collector alive.
  Timer {
    id: probeWatchdog
    interval: 10000
    repeat: false
    running: probe.running
    onTriggered: {
      if (!probe.running) return
      root.reap(probe.processId)
      probe.running = false
      root.lastError = "the build probe did not answer"
    }
  }

  // A daemon that has stayed up is not crash looping, so the budget is
  // returned rather than spent for the life of the session.
  Timer {
    interval: 120000
    repeat: true
    running: daemon.running
    onTriggered: if (root.restarts > 0) root.restarts = 0
  }

  Timer {
    id: respawn
    repeat: false
    onTriggered: if (!daemon.running) daemon.running = true
  }

  // Nothing destructive here: this also fires when the widget is toggled off.
  // Stopping the daemon is not destructive, and reaping its group is what
  // stops anything it spawned from outliving it.
  Component.onDestruction: {
    respawn.stop()
    reprobe.stop()
    probeWatchdog.stop()
    root.reap(daemon.processId)
    daemon.running = false
  }
}
