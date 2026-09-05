"""
Shared Cursor agent sandbox for music identity and composition recipes.

OS sandbox + no MCP + denied shell/write/web tools + cwd limited to
agent_sandbox/. Prompt contract is music and musical composition only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MUSIC_SANDBOX_RULES = """
You are sandboxed to music and musical composition only.

Allowed: recording/performing musicians, bands, composers, DJs, ensembles;
named genres and styles; harmony, melody, rhythm, meter, tempo, timbre,
texture, form, orchestration, MIDI parameters, studio habits as they
affect a sketch.

Forbidden: non-music topics; crime; politics; medical or legal advice;
celebrity biography that is not about recorded or composed work;
secrets; credentials; filesystem paths; shell commands; code edits;
web browsing; MCP tools.

If the query is not music, reject. Do not answer around the sandbox.
Return only the requested JSON. No prose.
"""

MUSIC_AGENT_DISALLOWED_TOOLS = (
    "Shell",
    "Bash",
    "Write",
    "Delete",
    "StrReplace",
    "MCP",
    "Browser",
    "WebSearch",
    "WebFetch",
    "Task",
    "EditNotebook",
    "CallMcpTool",
)


def agent_sandbox_dir() -> Path:
    return Path(__file__).resolve().parent / "agent_sandbox"


def music_local_options() -> Any:
    from cursor_sdk import LocalAgentOptions, SandboxOptions

    root = str(agent_sandbox_dir())
    return LocalAgentOptions(
        cwd=root,
        dirs=[root],
        setting_sources=[],
        sandbox_options=SandboxOptions(enabled=True),
    )


def create_music_agent(*, api_key: str, name: str) -> Any:
    """Local agent: music sandbox cwd. Prompt + DOMAIN.txt deny tools."""
    from cursor_sdk import Agent

    return Agent.create(
        model="composer-2.5",
        api_key=api_key,
        name=name,
        local=music_local_options(),
    )
