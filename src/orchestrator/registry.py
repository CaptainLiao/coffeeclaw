from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

import yaml  # type: ignore[import-untyped,unused-ignore]


@dataclass(frozen=True)
class AgentRegistryEntry:
    name: str
    type: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    config_path: str = ""


@dataclass(frozen=True)
class RoutingRule:
    intent: str
    agent: str | None = None
    mode: str | None = None
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoutingDecision:
    intent: str
    selected_agents: list[str]
    mode: str


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistryEntry] = {}
        self._routing_rules: list[RoutingRule] = []

    def load_from_file(self, file_path: str | Path) -> None:
        payload = yaml.safe_load(Path(file_path).read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("agent-registry.yaml must contain an object.")

        self._agents.clear()
        self._routing_rules.clear()

        for row in payload.get("agents", []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            self._agents[name] = AgentRegistryEntry(
                name=name,
                type=str(row.get("type", "domain_expert")),
                description=str(row.get("description", "")),
                capabilities=[str(item) for item in row.get("capabilities", [])],
                tools=[str(item) for item in row.get("tools", [])],
                config_path=str(row.get("config_path", "")).strip(),
            )

        for row in payload.get("routing_rules", []):
            if not isinstance(row, dict):
                continue
            intent = str(row.get("intent", "")).strip()
            if not intent:
                continue
            self._routing_rules.append(
                RoutingRule(
                    intent=intent,
                    agent=str(row["agent"]).strip() if "agent" in row else None,
                    mode=str(row["mode"]).strip() if "mode" in row else None,
                    keywords=[str(item).lower() for item in row.get("keywords", [])],
                )
            )

    def list_agents(self) -> list[AgentRegistryEntry]:
        return list(self._agents.values())

    def get_agent(self, name: str) -> AgentRegistryEntry | None:
        return self._agents.get(name)

    def list_routing_rules(self) -> list[RoutingRule]:
        return list(self._routing_rules)

    def list_domain_agent_names(self) -> list[str]:
        return [entry.name for entry in self._agents.values() if entry.type != "orchestrator"]

    def resolve(self, intent: str) -> RoutingDecision:
        selected: list[str] = []
        selected_mode = "single"
        for rule in self._routing_rules:
            if fnmatch(intent, rule.intent):
                if rule.agent:
                    selected.append(rule.agent)
                if rule.mode:
                    selected_mode = rule.mode

        valid_selected = [name for name in selected if name in self._agents]
        if valid_selected:
            return RoutingDecision(
                intent=intent,
                selected_agents=valid_selected,
                mode=selected_mode,
            )

        fallback = self.list_domain_agent_names()
        return RoutingDecision(
            intent=intent,
            selected_agents=fallback[:1],
            mode="single",
        )

    def as_prompt_context(self) -> str:
        lines: list[str] = []
        for entry in self.list_agents():
            caps = ", ".join(entry.capabilities) if entry.capabilities else "-"
            lines.append(f"- {entry.name}: {entry.description} (capabilities: {caps})")
        return "\n".join(lines)

    @classmethod
    def from_file(cls, file_path: str | Path) -> "AgentRegistry":
        instance = cls()
        instance.load_from_file(file_path)
        return instance
