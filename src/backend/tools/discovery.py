"""Tool discovery and registry helpers."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Iterable, List, Set, Type

from .core import Tool, ToolRegistry


def discover_tool_classes() -> List[Type[Tool]]:
    """Discover Tool subclasses declared under backend.tools.* modules."""
    tools_pkg = importlib.import_module(_tools_package_name())

    classes: List[Type[Tool]] = []
    seen: Set[Type[Tool]] = set()

    for module_info in pkgutil.walk_packages(tools_pkg.__path__, tools_pkg.__name__ + "."):
        module_name = module_info.name
        if module_name.endswith((".core", ".constants", ".discovery")):
            continue
        module = importlib.import_module(module_name)
        for obj in module.__dict__.values():
            if not inspect.isclass(obj) or not issubclass(obj, Tool) or obj is Tool:
                continue
            if obj.__module__ != module.__name__:
                continue
            if obj in seen:
                continue
            seen.add(obj)
            classes.append(obj)
    classes.sort(key=lambda cls: (cls.__module__, cls.__name__))
    return classes


def build_tool_registry(repo_root: Path) -> ToolRegistry:
    """Build a ToolRegistry by instantiating all discovered tools."""
    registry = ToolRegistry()
    for tool_cls in discover_tool_classes():
        registry.register(_instantiate_tool(tool_cls, repo_root))
    return registry


def _tools_package_name() -> str:
    module_name = __name__
    if module_name.endswith(".discovery"):
        return module_name.rsplit(".", 1)[0]
    return "backend.tools"


def _instantiate_tool(tool_cls: Type[Tool], repo_root: Path) -> Tool:
    signature = inspect.signature(tool_cls.__init__)
    params = [
        param
        for param in signature.parameters.values()
        if param.name != "self"
    ]
    required = [
        param
        for param in params
        if param.default is inspect._empty
        and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]

    if required:
        if len(required) == 1 and required[0].name == "repo_root":
            return tool_cls(repo_root)
        required_names = ", ".join(param.name for param in required)
        raise ValueError(
            f"Tool {tool_cls.__name__} requires unsupported init args: {required_names}"
        )

    if any(param.name == "repo_root" for param in params):
        return tool_cls(repo_root=repo_root)

    return tool_cls()
