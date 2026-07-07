"""
Scans skills/*/SKILL.md at startup and registers them as MCP prompts.
"""

import re
from pathlib import Path

import mcp.types as types

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a SKILL.md file."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text
    raw_meta, body = match.group(1), match.group(2)
    meta = {}
    for line in raw_meta.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, body.strip()


def _load_skill(skill_dir: Path) -> types.Prompt | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    text = skill_file.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    if not meta.get("name"):
        return None
    return types.Prompt(
        name=meta["name"],
        description=meta.get("description", ""),
        arguments=[],
    )


def load_skills() -> list[types.Prompt]:
    prompts = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if skill_dir.is_dir() and not skill_dir.name.startswith("_"):
            prompt = _load_skill(skill_dir)
            if prompt:
                prompts.append(prompt)
    return prompts


def get_skill(name: str, arguments: dict | None) -> types.GetPromptResult:
    for skill_dir in SKILLS_DIR.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if meta.get("name") == name:
            return types.GetPromptResult(
                description=meta.get("description", ""),
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(type="text", text=body),
                    )
                ],
            )
    raise ValueError(f"Skill not found: {name}")
