#!/usr/bin/env bash
# Configure the /watch skill for the Gemini engine on this machine.
#
#   bash setup-watch.sh              # configure the gemini engine
#   bash setup-watch.sh --local      # also install the local toolchain (ffmpeg, yt-dlp)
#
# The key is read with the terminal echo off and handed to Python on stdin, so it
# never reaches your shell history, the process list, or this script's output.
# Writing goes through the skill's own config writer, which replaces
# ~/.config/watch/.env atomically at mode 0600.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/watch/scripts"
WITH_LOCAL=0
[ "${1:-}" = "--local" ] && WITH_LOCAL=1

say() { printf '[setup-watch] %s\n' "$1"; }
die() { printf '[setup-watch] %s\n' "$1" >&2; exit 1; }

[ -f "$SCRIPTS_DIR/setup.py" ] || die "Cannot find skills/watch/scripts/setup.py next to this script."

# --- interpreter -------------------------------------------------------------
PY=""
for candidate in python3 python; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || die "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and rerun."
say "Using $($PY --version 2>&1)."

# --- optional local toolchain ------------------------------------------------
if [ "$WITH_LOCAL" -eq 1 ]; then
  say "Installing the local toolchain (this is optional for the gemini engine)…"
  "$PY" "$SCRIPTS_DIR/setup.py" --engine local || die "Local toolchain install failed; see the error above."
fi

# --- scaffold the config -----------------------------------------------------
# Exit 3 means "config created, key still missing" — expected on a first run.
set +e
"$PY" "$SCRIPTS_DIR/setup.py" --engine gemini >/dev/null 2>&1
scaffold_status=$?
set -e
[ "$scaffold_status" -eq 0 ] || [ "$scaffold_status" -eq 3 ] \
  || die "setup.py --engine gemini failed (exit $scaffold_status). Run it directly to see the error."

CONFIG_FILE="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import config; print(config.CONFIG_FILE)' "$SCRIPTS_DIR")"

# --- key ---------------------------------------------------------------------
if "$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import config; raise SystemExit(0 if config.load_gemini_key() else 1)' "$SCRIPTS_DIR"; then
  say "A Gemini key is already configured. Leaving it alone."
else
  if [ ! -t 0 ]; then
    die "No key configured and no terminal to prompt from. Add GEMINI_API_KEY to $CONFIG_FILE yourself, then rerun."
  fi
  echo
  echo "Paste your Google AI Studio key (free: https://aistudio.google.com/apikey)."
  echo "It will not be shown as you type, and is never printed or logged."
  printf 'GEMINI_API_KEY: '
  IFS= read -rs GEMINI_KEY_INPUT || true
  echo
  [ -n "${GEMINI_KEY_INPUT:-}" ] || die "No key entered; nothing was written."

  printf '%s' "$GEMINI_KEY_INPUT" | "$PY" -c '
import sys
sys.path.insert(0, sys.argv[1])
import config
key = sys.stdin.read().strip()
if not key:
    raise SystemExit("no key on stdin")
config.write_settings({"GEMINI_API_KEY": key}, config.CONFIG_FILE)
' "$SCRIPTS_DIR" || die "Could not write the key to $CONFIG_FILE."
  unset GEMINI_KEY_INPUT
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
  say "Key saved to $CONFIG_FILE (mode 0600)."
fi

# --- verify ------------------------------------------------------------------
"$PY" "$SCRIPTS_DIR/setup.py" --engine gemini || die "Setup did not complete; see the error above."

say "Status:"
"$PY" "$SCRIPTS_DIR/setup.py" --json | "$PY" -c '
import json, sys
d = json.load(sys.stdin)
for k in ("engine", "configured_engine", "gemini_key_present", "gemini_model", "missing_binaries", "config_file"):
    if k in d:
        print(f"  {k}: {d[k]}")
'
echo
say "Done. In Claude Code, try:  /watch https://youtu.be/dQw4w9WgXcQ what happens at the 30 second mark?"
