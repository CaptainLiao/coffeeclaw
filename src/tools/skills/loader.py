from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped,unused-ignore]

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    version: str
    description: str
    require_tools: list[str] = field(default_factory=list)
    prompt: str = ""


class SkillLoader:
    @staticmethod
    def load(skill_dir: str | Path) -> SkillDefinition:
        skill_path = Path(skill_dir) / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(content)
        if match is None:
            raise ValueError(f"Skill file {skill_path} must include YAML frontmatter.")

        frontmatter_raw, body = match.groups()
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
        if not isinstance(frontmatter, dict):
            raise ValueError(f"Skill file {skill_path} frontmatter must be a mapping.")

        required = frontmatter.get("require_tools", [])
        if not isinstance(required, list):
            raise ValueError("require_tools must be a list.")
        return SkillDefinition(
            name=str(frontmatter.get("name", "")),
            version=str(frontmatter.get("version", "")),
            description=str(frontmatter.get("description", "")),
            require_tools=[str(item) for item in required],
            prompt=body.strip(),
        )


class SkillManager:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def load_from_dir(self, dir_path: str | Path) -> None:
        base = Path(dir_path)
        if not base.exists():
            return
        for skill_md in sorted(base.rglob("SKILL.md")):
            definition = SkillLoader.load(skill_md.parent)
            self._skills[definition.name] = definition

    def get(self, skill_name: str) -> SkillDefinition | None:
        return self._skills.get(skill_name)

    def list_all(self) -> list[SkillDefinition]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def inject_into_context(self, skill_name: str, agent_system_prompt: str) -> str:
        skill = self.get(skill_name)
        if skill is None:
            return agent_system_prompt
        merged = agent_system_prompt.strip()
        if merged:
            merged += "\n\n"
        merged += f"[Skill: {skill.name}]\n{skill.prompt}"
        return merged

    def inject_skills_for_agent(
        self,
        agent_config: dict[str, Any],
        agent_system_prompt: str,
    ) -> str:
        capabilities = agent_config.get("capabilities", {})
        if not isinstance(capabilities, dict):
            return agent_system_prompt
        skills = capabilities.get("skills", [])
        if not isinstance(skills, list):
            return agent_system_prompt

        merged_prompt = agent_system_prompt
        for skill_name in skills:
            merged_prompt = self.inject_into_context(str(skill_name), merged_prompt)
        return merged_prompt
