#!/usr/bin/env bash
# Start MIDI Style Lab. No prompts — just open the URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8501}"
HOST="${HOST:-0.0.0.0}"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# Keep the project venv first. Prepending /usr/local/bin shadows it with
# system python3 while `pip` can still be the venv one, which then rejects --user.
if [[ -x "$ROOT/venv/bin/python" ]]; then
  PYTHON="$ROOT/venv/bin/python"
  export PATH="$ROOT/venv/bin:${HOME}/.local/bin:/usr/local/bin:${PATH}"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
  export PATH="${VIRTUAL_ENV}/bin:${HOME}/.local/bin:/usr/local/bin:${PATH}"
else
  export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"
  PYTHON="$(command -v python3)"
fi

# Prefer editable install when available; otherwise symlink package name
if ! "$PYTHON" -c "import midi_gen" >/dev/null 2>&1; then
  if [[ -f "$ROOT/pyproject.toml" ]]; then
    "$PYTHON" -m pip install -e "$ROOT"
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

UI_APP="$("$PYTHON" - <<'PY'
import midi_gen, pathlib
print(pathlib.Path(midi_gen.__file__).resolve().parent / "ui_app.py")
PY
)"

echo "MIDI Style Lab → http://127.0.0.1:${PORT}"
exec "$PYTHON" -m streamlit run "$UI_APP" \
  --server.port "$PORT" \
  --server.address "$HOST" \
  --server.headless true \
  --browser.gatherUsageStats false
