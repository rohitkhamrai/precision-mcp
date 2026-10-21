"""AST and structural code symbol parser for Python and C-family languages."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

# Extended regex patterns for TypeScript, JavaScript, Go, and Rust
JS_TS_PATTERNS = [
    # export [default] [async] function name(...)
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\("),
    # export [default] class name
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_$]+)"),
    # const/let/var name = [async] (...) => or function
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"),
    # interface Name
    re.compile(r"^\s*(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)"),
    # type Name =
    re.compile(r"^\s*(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*="),
    # Method in class/object: name(...) { or async name(...) {
    re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:async\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{"),
]

RUST_GO_PATTERNS = [
    # fn / func name(...)
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|func)\s+(?:\([^)]*\)\s+)?([a-zA-Z0-9_]+)\s*\("),
    # type/struct/interface/enum
    re.compile(r"^\s*(?:pub\s+)?(?:type|struct|interface|enum)\s+([a-zA-Z0-9_]+)"),
]

# Legacy single-pattern aliases for backward compatibility
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
    """Extract AST symbols for Python files."""
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


def find_block_end(lines: list[str], start_idx: int) -> int:
    """Find closing brace of a C-family code block using balance tracking."""
    depth = 0
    found_open = False

    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        # Ignore comments
        clean = line.split("//")[0].split("/*")[0]
        for char in clean:
            if char == "{":
                depth += 1
                found_open = True
            elif char == "}":
                depth -= 1
                if found_open and depth <= 0:
                    return idx + 1  # 1-indexed line number

    return start_idx + 1


def parse_c_family_file(
    filepath: Path,
    patterns: list[re.Pattern],
    content: str | None = None,
) -> list[dict[str, Any]]:
    """Parse symbols and compute multi-line block boundaries for C-family code."""
    symbols: list[dict[str, Any]] = []
    try:
        if content is None:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
    except Exception:
        return symbols

    seen_names = set()
    for i, line in enumerate(lines):
        line_num = i + 1
        for pattern in patterns:
            m = pattern.search(line)
            if m:
                name = next((g for g in m.groups() if g), None)
                if name and name not in seen_names and name not in {"if", "for", "while", "switch"}:
                    seen_names.add(name)
                    end_line = find_block_end(lines, i)
                    # Heuristic type detection
                    sym_type = "class" if "class" in line or "struct" in line else "function"
                    symbols.append({
                        "name": name,
                        "type": sym_type,
                        "start_line": line_num,
                        "end_line": max(line_num, end_line),
                        "args": [],
                        "doc": "",
                        "calls": [],
                    })
                break
    return symbols


def parse_regex_file(filepath: Path, pattern: re.Pattern, content: str | None = None) -> list[dict[str, Any]]:
    """Legacy regex file parser for backward compatibility."""
    return parse_c_family_file(filepath, [pattern], content)


def validate_syntax(ext: str, code: str) -> tuple[bool, str]:
    """Validate syntax of modified code across Python and C-family languages."""
    ext = ext.lower()
    if ext == ".py":
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"

    # Structural balance verification for C-family code
    if ext in (".js", ".ts", ".jsx", ".tsx", ".go", ".rs"):
        stack = []
        matching = {")": "(", "}": "{", "]": "["}
        lines = code.splitlines()

        in_string = False
        str_char = ""

        for line_idx, line in enumerate(lines, 1):
            i = 0
            while i < len(line):
                ch = line[i]

                # Handle comments
                if not in_string and i + 1 < len(line) and line[i : i + 2] == "//":
                    break

                # Handle quotes
                if ch in ('"', "'", "`") and (i == 0 or line[i - 1] != "\\"):
                    if in_string and ch == str_char:
                        in_string = False
                    elif not in_string:
                        in_string = True
                        str_char = ch

                elif not in_string:
                    if ch in ("(", "{", "["):
                        stack.append((ch, line_idx))
                    elif ch in (")", "}", "]"):
                        if not stack or stack[-1][0] != matching[ch]:
                            expected = [k for k, v in matching.items() if stack and v == stack[-1][0]]
                            exp_str = expected[0] if expected else "none"
                            return False, f"Unbalanced '{ch}' at line {line_idx} (expected '{exp_str}')"
                        stack.pop()
                i += 1

        if stack:
            unclosed, open_line = stack[-1]
            return False, f"Unclosed '{unclosed}' from line {open_line}"

    return True, ""
