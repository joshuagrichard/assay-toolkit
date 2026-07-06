from __future__ import annotations

from assay_platform.core import ToolRegistry
from assay_platform.tools.scratch_wound import scratch_wound_tool


def build_registry() -> ToolRegistry:
    return ToolRegistry([scratch_wound_tool])


registry = build_registry()
