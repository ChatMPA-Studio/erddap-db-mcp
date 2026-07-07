"""
Developer catalog of available skills.
Auto-populated from skills/*/SKILL.md at import time.
"""

from pathlib import Path

SKILLS_DIR = Path(__file__).parent

registry = {}

for skill_dir in sorted(SKILLS_DIR.iterdir()):
    skill_file = skill_dir / "SKILL.md"
    if skill_dir.is_dir() and skill_file.exists():
        registry[skill_dir.name] = str(skill_file)
