"""
prompts — auto-discovers skills/*/SKILL.md and registers them as MCP prompts.
"""

from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger("erddap_mcp.prompts")

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.index("---", 3)
    fm_block = text[3:end].strip()
    body = text[end + 3:].strip()
    meta: dict = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def discover_prompts(mcp) -> None:
    """Scan skills/*/SKILL.md and register each as an @mcp.prompt."""
    if not _SKILLS_DIR.exists():
        logger.warning("Skills directory not found: %s", _SKILLS_DIR)
        return

    for skill_file in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        try:
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            name = meta.get("name") or skill_file.parent.name
            description = meta.get("description", "")
            skill_body = body

            def _make_prompt(n: str, d: str, b: str):
                @mcp.prompt(name=n, description=d)
                def _prompt() -> str:
                    return b
                return _prompt

            _make_prompt(name, description, skill_body)
            logger.info("Registered prompt: %s", name)

        except Exception as e:
            logger.error("Failed to load skill '%s': %s", skill_file, e)
