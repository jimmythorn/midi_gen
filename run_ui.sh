#!/usr/bin/env bash
# Start MIDI Style Lab. No prompts — just open the URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8501}"
HOST="${HOST:-0.0.0.0}"
export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Prefer editable install when available; otherwise symlink package name
if ! python3 -c "import midi_gen" >/dev/null 2>&1; then
  if [[ -f "$ROOT/pyproject.toml" ]]; then
    pip install --user -e "$ROOT" >/dev/null
  else
    PY_LINK_ROOT="${TMPDIR:-/tmp}/midi_gen_py"
    mkdir -p "$PY_LINK_ROOT"
    ln -sfn "$ROOT" "$PY_LINK_ROOT/midi_gen"
    export PYTHONPATH="$PY_LINK_ROOT${PYTHONPATH:+:$PYTHONPATH}"
  fi
fi

# Silence Streamlit first-run email prompt
STREAMLIT_DIR="${HOME}/.streamlit"
mkdir -p "$STREAMLIT_DIR"
cat > "$STREAMLIT_DIR/credentials.toml" <<'EOF'
[general]
email = ""
EOF
cat > "$STREAMLIT_DIR/config.toml" <<'EOF'
[browser]
gatherUsageStats = false

[server]
headless = true
EOF

if command -v midi-gen-ui >/dev/null 2>&1; then
  echo "MIDI Style Lab → http://127.0.0.1:${PORT}"
  export PORT HOST
  exec midi-gen-ui
fi

UI_APP="$(python3 - <<'PY'
import midi_gen, pathlib
print(pathlib.Path(midi_gen.__file__).resolve().parent / "ui_app.py")
PY
)"

echo "MIDI Style Lab → http://127.0.0.1:${PORT}"
exec python3 -m streamlit run "$UI_APP" \
  --server.port "$PORT" \
  --server.address "$HOST" \
  --server.headless true \
  --browser.gatherUsageStats false
