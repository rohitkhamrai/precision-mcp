"""AST and regex code symbol parser."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

# Regex patterns for C-style and dynamic languages
JS_TS_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+([a-zA-Z0-9_$]+)|class\s+([a-zA-Z0-9_$]+)|(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)",
    re.MULTILINE,
)
RUST_GO_PATTERN = re.compile(
    r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|func(?:\s*\([^)]*\))?)\s+([a-zA-Z0-9_]+)|^\s*(?:pub\s+)?(?:type|struct|interface|enum)\s+([a-zA-Z0-9_]+)",
    re.MULTILINE,
)


class CallVisitor(ast.NodeVisitor):
    """Collects all function calls within an AST node."""

    def __init__(self) -> None:
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.add(node.func.attr)
        self.generic_visit(node)


def parse_python_file(filepath: Path, content: str | None = None) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        if content is None:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(filepath))
    except Exception:
        return symbols

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller_visitor = CallVisitor()
            caller_visitor.visit(node)
            symbols.append({
                "name": node.name,
                "type": "function",
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "args": [a.arg for a in node.args.args],
                "doc": ast.get_docstring(node) or "",
                "calls": sorted(list(caller_visitor.calls)),
            })
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_calls = CallVisitor()
                    m_calls.visit(item)
                    methods.append({
                        "name": item.name,
                        "type": "method",
                        "start_line": item.lineno,
                        "end_line": getattr(item, "end_lineno", item.lineno),
                        "args": [a.arg for a in item.args.args],
                        "doc": ast.get_docstring(item) or "",
                        "calls": sorted(list(m_calls.calls)),
                    })
            symbols.append({
                "name": node.name,
                "type": "class",
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "methods": methods,
                "doc": ast.get_docstring(node) or "",
            })
    return symbols


def parse_regex_file(filepath: Path, pattern: re.Pattern, content: str | None = None) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    try:
        if content is None:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception:
        return symbols

    for i, line in enumerate(lines, 1):
        m = pattern.search(line)
        if m:
            name = next((g for g in m.groups() if g), None)
            if name:
                symbols.append({
                    "name": name,
                    "type": "symbol",
                    "start_line": i,
                    "end_line": i,
                    "args": [],
                    "doc": "",
                    "calls": [],
                })
    return symbols
