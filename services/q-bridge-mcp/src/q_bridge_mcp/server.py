from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider

from q_bridge_mcp.auth import setup_auth
from q_bridge_mcp.profiles import profile_app
from q_bridge_mcp.skills.provider import skills_provider

SERVER_INSTRUCTIONS = (
    "Before using Q Bridge tools, call profile_settings so the user can complete "
    "their profile and organization setup. If a tool reports that setup is "
    "incomplete, call profile_settings and ask the user to finish the form. "
    "MANDATORY skill preflight: before answering any user request, discover "
    "the configured Knowledge Base skills. Resource-capable clients must list "
    "the available skill:// resources and read the relevant "
    "skill://<name>/SKILL.md. Clients that cannot read MCP resources must call "
    "get_skill_guide with no skill first, then call it again with the relevant "
    "skill and file='SKILL.md'. Do not answer before completing this preflight. "
    "Match the request to relevant skills using their names and descriptions; "
    "the user does not need to name a skill. Read any supporting resources the "
    "skill references, then follow its instructions. Do not read unrelated "
    "skills. If no relevant skill exists, answer normally after the preflight."
)


def create_server() -> FastMCP:
    provider = FileSystemProvider(Path(__file__).parent / "tools")
    return FastMCP(
        name="q-bridge-mcp",
        instructions=SERVER_INSTRUCTIONS,
        auth=setup_auth(),
        providers=[provider, profile_app, skills_provider],
    )
