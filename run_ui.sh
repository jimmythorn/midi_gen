#!/usr/bin/env bash
# Start MIDI Style Lab. No prompts — just open the URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8501}"
HOST="${HOST:-0.0.0.0}"

# Package import path when repo root *is* the package
PY_LINK_ROOT="${TMPDIR:-/tmp}/midi_gen_py"
mkdir -p "$PY_LINK_ROOT"
ln -sfn "$ROOT" "$PY_LINK_ROOT/midi_gen"
export PYTHONPATH="$PY_LINK_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Silence Streamlit's first-run email / onboarding prompt
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

echo "MIDI Style Lab → http://127.0.0.1:${PORT}"
exec python3 -m streamlit run "$ROOT/ui_app.py" \
  --server.port "$PORT" \
  --server.address "$HOST" \
  --server.headless true \
  --browser.gatherUsageStats false
