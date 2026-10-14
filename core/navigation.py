"""Registro de herramientas. Cada app de departamento registra las suyas en su AppConfig.ready()."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tool:
    label: str
    url_name: str
    description: str = ""


@dataclass
class DepartmentNav:
    slug: str
    label: str
    tools: list[Tool] = field(default_factory=list)


_registry: dict[str, list[Tool]] = {}


def register_tool(department: str, tool: Tool) -> None:
    tools = _registry.setdefault(department, [])
    if tool not in tools:
        tools.append(tool)


def tools_for(department: str) -> list[Tool]:
    return list(_registry.get(department, []))
