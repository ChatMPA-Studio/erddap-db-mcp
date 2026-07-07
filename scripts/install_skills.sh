#!/bin/bash
# Install skills locally to ~/.claude/skills/ for direct invocation
set -e

SKILLS_DIR="$(dirname "$0")/../skills"
TARGET_DIR="$HOME/.claude/skills"

mkdir -p "$TARGET_DIR"

for skill_dir in "$SKILLS_DIR"/*/; do
    skill_name=$(basename "$skill_dir")
    skill_file="$skill_dir/SKILL.md"
    if [ -f "$skill_file" ]; then
        cp "$skill_file" "$TARGET_DIR/${skill_name}.md"
        echo "Installed: $skill_name"
    fi
done

echo "Skills installed to $TARGET_DIR"
