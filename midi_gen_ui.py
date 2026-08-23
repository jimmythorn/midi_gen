"""Console entry: `midi-gen-ui` → Streamlit Style Lab."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _silence_streamlit_onboarding() -> None:
    streamlit_dir = Path.home() / ".streamlit"
    streamlit_dir.mkdir(parents=True, exist_ok=True)
    (streamlit_dir / "credentials.toml").write_text('[general]\nemail = ""\n', encoding="utf-8")
    (streamlit_dir / "config.toml").write_text(
        "[browser]\ngatherUsageStats = false\n\n[server]\nheadless = true\n",
        encoding="utf-8",
    )
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")


def main() -> None:
    _silence_streamlit_onboarding()
    # Prefer installed package path; fall back to repo-local ui_app.py
    try:
        import midi_gen

        ui = Path(midi_gen.__file__).resolve().parent / "ui_app.py"
    except Exception:
        ui = Path(__file__).resolve().parent / "ui_app.py"

    port = os.environ.get("PORT", "8501")
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"MIDI Style Lab → http://127.0.0.1:{port}")
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ui),
            "--server.port",
            port,
            "--server.address",
            host,
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
    )


if __name__ == "__main__":
    main()
