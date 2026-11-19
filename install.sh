#!/bin/bash
# Crypto Playbook plugin installer.
#
# Copies the plugin into ~/.config/omarchy/plugins/windong.cryptoplaybook/
# (or sets it up in place when run from an installed copy), generates the
# bin/playbookd and bin/playbook wrappers, and creates a .venv there with
# the Python dependencies installed. Safe to re-run: when installing from a
# separate checkout the replacement is staged completely before the old
# files are swapped out, and the backup is kept until wrapper generation,
# virtualenv setup and dependency installation all succeed. Any earlier
# failure leaves the previous install intact. The .venv is reused when it
# already works.

set -euo pipefail

PLUGIN_ID="windong.cryptoplaybook"
PLUGIN_DIR="${CRYPTOPLAYBOOK_PLUGIN_DIR:-$HOME/.config/omarchy/plugins/$PLUGIN_ID}"
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

log() { printf '==> %s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

[ -f "$REPO_ROOT/manifest.json" ] || die "manifest.json not found in $REPO_ROOT — run this script from the repository checkout"
command -v python3 >/dev/null 2>&1 || die "python3 is required but not on PATH"

log "Installing $PLUGIN_ID into $PLUGIN_DIR"

# A marketplace install clones into the destination and runs this same script
# from there. Source and destination are then identical: deleting "managed"
# paths first would destroy the files we are about to copy (and any local
# edits), then fail. In that case only generate the wrappers and the venv.
same_dir() {
    [ "$(readlink -f -- "$1")" = "$(readlink -f -- "$2")" ]
}

if same_dir "$REPO_ROOT" "$PLUGIN_DIR"; then
    log "Running in place; keeping the files already in $PLUGIN_DIR"
    for required in manifest.json App.qml Service.qml BarWidget.qml requirements.txt; do
        [ -f "$PLUGIN_DIR/$required" ] || die "missing $required in $PLUGIN_DIR"
    done
    for required in views components engine samples; do
        [ -d "$PLUGIN_DIR/$required" ] || die "missing $required/ in $PLUGIN_DIR"
    done
else
    # Separate checkout: stage the full replacement before touching the
    # installed copy. Deleting first would lose the previous install (and any
    # local edits) if a later copy failed, so copies go to a staging directory
    # and the old paths are only swapped out once every copy has succeeded.
    log "Copying plugin files"
    mkdir -p "$PLUGIN_DIR"
    parent=$(dirname -- "$PLUGIN_DIR")

    managed=(
        manifest.json BarWidget.qml App.qml Service.qml requirements.txt
        views components engine samples bin
    )
    stage=$(mktemp -d "$parent/.cryptoplaybook-stage.XXXXXX") || die "cannot create staging directory"
    backup=$(mktemp -d "$parent/.cryptoplaybook-backup.XXXXXX") || {
        rm -rf -- "$stage"
        die "cannot create backup directory"
    }

    # If anything fails after staging, restore the previous installation.
    rollback=1
    swapped=0
    moved=()
    cleanup() {
        if [ "$rollback" -eq 1 ]; then
            # Only paths moved into place (swapped) can be partial replacements.
            if [ "$swapped" -eq 1 ]; then
                for name in "${managed[@]}"; do
                    rm -rf -- "$PLUGIN_DIR/$name"
                done
            fi
            if [ ${#moved[@]} -gt 0 ]; then
                for name in "${moved[@]}"; do
                    mv -- "$backup/$name" "$PLUGIN_DIR/$name"
                done
            fi
        fi
        rm -rf -- "$stage" "$backup"
    }
    trap cleanup EXIT

    cp -a "$REPO_ROOT/manifest.json" "$REPO_ROOT/BarWidget.qml" \
          "$REPO_ROOT/App.qml" "$REPO_ROOT/Service.qml" \
          "$REPO_ROOT/requirements.txt" "$stage/"
    cp -a "$REPO_ROOT/views" "$REPO_ROOT/components" \
          "$REPO_ROOT/engine" "$REPO_ROOT/samples" "$stage/"

    # Keep the old paths in backup, then install the staged ones. bin/ is
    # regenerated below, so only its previous copy is moved aside.
    for name in "${managed[@]}"; do
        if [ -e "$PLUGIN_DIR/$name" ]; then
            mv -- "$PLUGIN_DIR/$name" "$backup/$name"
            moved+=("$name")
        fi
    done
    swapped=1
    for name in manifest.json BarWidget.qml App.qml Service.qml requirements.txt \
                views components engine samples; do
        mv -- "$stage/$name" "$PLUGIN_DIR/$name"
    done

    # Keep the backup and the EXIT trap armed until setup finishes (wrappers,
    # venv and pip below). A failure in any later step must still restore the
    # previous install, not leave a half-updated plugin.
fi

# Never ship interpreter caches into the plugin dir.
find "$PLUGIN_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$PLUGIN_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

mkdir -p "$PLUGIN_DIR/bin"

# Generate the wrappers. The text matches the contract asserted in
# tests/test_daemon.py (WRAPPER_SCRIPT) — keep them byte-identical.
# Python runs with -B so it never writes __pycache__ into the plugin folder;
# the shell watches that folder and reloads the plugin on every file change.
write_wrapper() {
    local module="$1" target="$2"
    cat > "$target" <<EOF
#!/bin/sh
# Crypto Playbook ${module} wrapper (generated by install.sh; gitignored).
# Resolves its own directory so it works from any cwd, puts the plugin
# root on PYTHONPATH, and prefers the plugin's own .venv interpreter.
set -eu
self=\$(readlink -f -- "\$0")
root=\$(dirname -- "\$(dirname -- "\$self")")
export PYTHONPATH="\$root\${PYTHONPATH:+:\$PYTHONPATH}"
py="\$root/.venv/bin/python"
[ -x "\$py" ] || py=python3
exec "\$py" -B -m engine.${module} "\$@"
EOF
    chmod 755 "$target"
}

log "Generating bin/playbookd and bin/playbook"
write_wrapper daemon "$PLUGIN_DIR/bin/playbookd"
write_wrapper cli    "$PLUGIN_DIR/bin/playbook"

# Create (or reuse) the virtualenv and install dependencies into it.
# The plugin validator rejects symlinks inside the plugin folder, so the
# venv must contain real interpreter binaries (--copies) rather than the
# default symlinks to the base python, and the lib64 -> lib symlink that
# `python3 -m venv` adds has to be removed. If an existing .venv violates
# this (created by an older installer), rebuild it from scratch.
venv_ok() {
    [ -x "$PLUGIN_DIR/.venv/bin/python" ] \
        && [ ! -L "$PLUGIN_DIR/.venv/bin/python" ] \
        && ! find "$PLUGIN_DIR/.venv" -type l -print -quit | grep -q .
}

if ! venv_ok; then
    log "Creating virtualenv at $PLUGIN_DIR/.venv"
    rm -rf "$PLUGIN_DIR/.venv"
    python3 -m venv --copies "$PLUGIN_DIR/.venv"
fi
if [ -L "$PLUGIN_DIR/.venv/lib64" ]; then
    rm -f "$PLUGIN_DIR/.venv/lib64"
fi
log "Installing Python dependencies (this can take a minute on first run)"
# Exact versions and sha256 hashes are recorded in requirements.txt; enforce
# both so setup is deterministic and reviewable. Test-only packages are kept
# in requirements-dev.txt and never installed here.
"$PLUGIN_DIR/.venv/bin/pip" install --disable-pip-version-check --require-hashes \
    -r "$PLUGIN_DIR/requirements.txt"

cat <<EOF

Crypto Playbook installed to:
  $PLUGIN_DIR

Next steps:
  1. Reload the Omarchy shell so it discovers the plugin:
       omarchy-shell shell rescanPlugins
  2. Enable the plugin (its bar widget and panel):
       omarchy plugin enable $PLUGIN_ID
  3. Set the API key for LLM-grounded predictions (never commit it):
       open the dashboard panel -> API keys -> paste a key for your provider.
     Keys live in a private 600 keys.json under the data dir, never in the
     config or the reports. Any OpenAI-compatible endpoint works: pick
     openai, openrouter, deepseek, groq, or custom on the Model screen
     (or edit llm.provider / llm.base_url / llm.model in the config).
     Legacy fallback: export OPENAI_API_KEY in Quickshell's launch
     environment (e.g. your login shell profile) and restart the shell.
     Without a key the daemon still generates deterministic playbooks;
     only the narrative prediction is skipped.
  4. Query it from the shell or a terminal:
       $PLUGIN_DIR/bin/playbook status
       $PLUGIN_DIR/bin/playbook latest

Reports and config live outside the plugin dir (XDG):
  config: \${XDG_CONFIG_HOME:-~/.config}/crypto-playbook/config.json
  data:   \${XDG_DATA_HOME:-~/.local/share}/crypto-playbook/
EOF

# Setup completed: the EXIT trap now only removes the staging/backup dirs.
rollback=0
