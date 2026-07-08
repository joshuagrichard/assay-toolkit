from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable


@dataclass(frozen=True)
class ToolParameter:
    name: str
    label: str
    kind: str
    default: Any
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": list(self.choices),
        }


@dataclass
class AnalysisJobResult:
    tool_id: str
    output_dir: Path
    results_table: Path | None = None
    artifacts: dict[str, Path] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "output_dir": str(self.output_dir),
            "results_table": str(self.results_table) if self.results_table else None,
            "artifacts": {key: str(path) for key, path in self.artifacts.items()},
            "summary": self.summary,
            "warnings": self.warnings,
        }


RunTool = Callable[[Path, Path, Dict[str, Any]], AnalysisJobResult]


@dataclass(frozen=True)
class AssayTool:
    id: str
    name: str
    category: str
    description: str
    accepted_extensions: tuple[str, ...]
    parameters: tuple[ToolParameter, ...]
    run: RunTool

    def manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "accepted_extensions": list(self.accepted_extensions),
            "parameters": [param.to_dict() for param in self.parameters],
        }


class ToolRegistry:
    def __init__(self, tools: Iterable[AssayTool] = ()):
        self._tools: dict[str, AssayTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: AssayTool) -> None:
        if tool.id in self._tools:
            raise ValueError(f"Tool already registered: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> AssayTool:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown assay tool: {tool_id}") from exc

    def list(self) -> list[AssayTool]:
        return list(self._tools.values())

    def manifest(self) -> list[dict[str, Any]]:
        return [tool.manifest() for tool in self.list()]
