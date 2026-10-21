"""Codebase Indexer Engine for symbol graph and surgical slicing."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .parser import JS_TS_PATTERN, RUST_GO_PATTERN, parse_python_file, parse_regex_file

INDEX_FILENAME = ".precision_index.json"
DEFAULT_IGNORES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".agents",
    "dist",
    "build",
    ".idea",
    ".vscode",
}


class CodebaseIndexer:
    """Manages the symbol index and surgical code retrieval for a workspace."""

    def __init__(self, root_dir: Path | str = ".") -> None:
        self.root_dir = Path(root_dir).resolve()
        self.index_cache_path = self.root_dir / INDEX_FILENAME
        self.index: dict[str, list[dict[str, Any]]] = {}
        self.last_indexed_at: float = 0.0

    def build(self, force: bool = False) -> dict[str, Any]:
        """Scan workspace and generate/update symbol index."""
        start_time = time.perf_counter()
        self.index = {}

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORES and not d.startswith(".")]
            for f in files:
                p = Path(root) / f
                rel = p.relative_to(self.root_dir).as_posix()
                ext = p.suffix.lower()

                symbols: list[dict[str, Any]] = []
                if ext == ".py":
                    symbols = parse_python_file(p)
                elif ext in (".js", ".ts", ".jsx", ".tsx"):
                    symbols = parse_regex_file(p, JS_TS_PATTERN)
                elif ext in (".rs", ".go"):
                    symbols = parse_regex_file(p, RUST_GO_PATTERN)

                if symbols:
                    self.index[rel] = symbols

        self.last_indexed_at = time.time()
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Write cache
        try:
            self.index_cache_path.write_text(json.dumps(self.index, indent=2), encoding="utf-8")
        except Exception:
            pass

        total_symbols = sum(len(v) for v in self.index.values())
        return {
            "files_indexed": len(self.index),
            "symbols_indexed": total_symbols,
            "elapsed_ms": elapsed_ms,
            "root": str(self.root_dir),
        }

    def load_cache(self) -> bool:
        """Load index from on-disk cache if present."""
        if self.index_cache_path.is_file():
            try:
                self.index = json.loads(self.index_cache_path.read_text(encoding="utf-8"))
                return True
            except Exception:
                return False
        return False

    def ensure_indexed(self) -> None:
        """Ensure the index is available in memory."""
        if not self.index:
            if not self.load_cache():
                self.build()

    def find_symbol(self, query: str) -> list[dict[str, Any]]:
        """Search symbols across all indexed files."""
        self.ensure_indexed()
        matches = []
        q = query.lower()

        has_dot = "." in q
        for file_path, symbols in self.index.items():
            for sym in symbols:
                name = sym["name"]
                if q == name.lower() or q in name.lower():
                    matches.append({
                        "file": file_path,
                        "symbol": name,
                        "type": sym.get("type", "symbol"),
                        "start_line": sym.get("start_line"),
                        "end_line": sym.get("end_line"),
                        "args": sym.get("args", []),
                        "doc": sym.get("doc", ""),
                    })
                for m in sym.get("methods", []):
                    m_name = m["name"]
                    full_name = f"{name}.{m_name}"
                    matches_method = (q in full_name.lower()) if has_dot else (q == m_name.lower() or q in m_name.lower())
                    if matches_method:
                        matches.append({
                            "file": file_path,
                            "symbol": full_name,
                            "type": "method",
                            "start_line": m.get("start_line"),
                            "end_line": m.get("end_line"),
                            "args": m.get("args", []),
                            "doc": m.get("doc", ""),
                        })
        return matches

    def get_outline(self, file_path: str) -> list[dict[str, Any]]:
        """Get the structural skeleton (classes & functions) of a file."""
        self.ensure_indexed()
        norm_path = Path(file_path).as_posix()
        symbols = self.index.get(norm_path)
        if symbols is None:
            # Fuzzy path match
            match_key = next((k for k in self.index if k.endswith(norm_path)), None)
            symbols = self.index.get(match_key, []) if match_key else []
        return symbols

    def get_symbol_slice(self, file_path: str, symbol_name: str) -> dict[str, Any] | None:
        """Extract exact line boundaries and raw source text for a single symbol."""
        norm_path = Path(file_path).as_posix()
        full_path = self.root_dir / norm_path
        if not full_path.is_file():
            # Try fuzzy file match
            found = next((self.root_dir / k for k in self.index if k.endswith(norm_path)), None)
            if not found or not found.is_file():
                return None
            full_path = found
            norm_path = full_path.relative_to(self.root_dir).as_posix()

        outline = self.get_outline(norm_path)
        target = None
        for sym in outline:
            if sym["name"] == symbol_name:
                target = sym
                break
            for m in sym.get("methods", []):
                if m["name"] == symbol_name or f"{sym['name']}.{m['name']}" == symbol_name:
                    target = m
                    break
            if target:
                break

        if not target:
            return None

        start_line = target["start_line"]
        end_line = target["end_line"]

        try:
            lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
            # 1-indexed to 0-indexed slice
            slice_lines = lines[start_line - 1 : end_line]
            code = "\n".join(slice_lines)
            return {
                "file": norm_path,
                "symbol": symbol_name,
                "type": target.get("type", "symbol"),
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            }
        except Exception:
            return None

    def find_callers(self, symbol_name: str) -> list[dict[str, Any]]:
        """Find functions or methods that invoke the specified symbol."""
        self.ensure_indexed()
        callers = []
        for file_path, symbols in self.index.items():
            for sym in symbols:
                if symbol_name in sym.get("calls", []):
                    callers.append({
                        "file": file_path,
                        "caller_symbol": sym["name"],
                        "caller_type": sym.get("type", "function"),
                        "start_line": sym.get("start_line"),
                    })
                for m in sym.get("methods", []):
                    if symbol_name in m.get("calls", []):
                        callers.append({
                            "file": file_path,
                            "caller_symbol": f"{sym['name']}.{m['name']}",
                            "caller_type": "method",
                            "start_line": m.get("start_line"),
                        })
        return callers

    def get_impact_radius(self, symbol_name: str, max_depth: int = 2) -> dict[str, Any]:
        """Trace cascading downstream blast radius (who calls this, and who calls them)."""
        self.ensure_indexed()
        visited: set[str] = set()
        frontier: list[tuple[str, int]] = [(symbol_name, 0)]
        impact_tree: list[dict[str, Any]] = []
        affected_files: set[str] = set()

        while frontier:
            current_sym, depth = frontier.pop(0)
            if depth >= max_depth:
                continue

            callers = self.find_callers(current_sym)
            for c in callers:
                c_name = c["caller_symbol"]
                affected_files.add(c["file"])
                if c_name not in visited:
                    visited.add(c_name)
                    impact_tree.append({
                        "caller": c_name,
                        "file": c["file"],
                        "line": c["start_line"],
                        "depth": depth + 1,
                        "triggered_by": current_sym,
                    })
                    frontier.append((c_name, depth + 1))

        # Risk score calculation
        fanout = len(impact_tree)
        risk = "low" if fanout <= 2 else ("medium" if fanout <= 6 else "high")

        return {
            "target_symbol": symbol_name,
            "total_callers": fanout,
            "affected_files": sorted(list(affected_files)),
            "risk_level": risk,
            "call_chain": impact_tree,
        }

    def patch_symbol(self, file_path: str, symbol_name: str, new_code: str) -> dict[str, Any]:
        """Surgically replace a symbol's code block with AST syntax validation."""
        norm_path = Path(file_path).as_posix()
        full_path = self.root_dir / norm_path
        if not full_path.is_file():
            found = next((self.root_dir / k for k in self.index if k.endswith(norm_path)), None)
            if not found or not found.is_file():
                return {"success": False, "error": f"File not found: {file_path}"}
            full_path = found
            norm_path = full_path.relative_to(self.root_dir).as_posix()

        outline = self.get_outline(norm_path)
        target = None
        for sym in outline:
            if sym["name"] == symbol_name:
                target = sym
                break
            for m in sym.get("methods", []):
                if m["name"] == symbol_name or f"{sym['name']}.{m['name']}" == symbol_name:
                    target = m
                    break
            if target:
                break

        if not target:
            return {"success": False, "error": f"Symbol '{symbol_name}' not found in '{norm_path}'"}

        start_line = target["start_line"]
        end_line = target["end_line"]

        try:
            original_content = full_path.read_text(encoding="utf-8", errors="replace")
            lines = original_content.splitlines()

            # Preserve line endings
            newline = "\r\n" if "\r\n" in original_content else "\n"

            # Replace lines [start_line - 1 : end_line]
            replacement_lines = new_code.strip().splitlines()
            new_lines = lines[: start_line - 1] + replacement_lines + lines[end_line:]
            modified_content = newline.join(new_lines) + newline

            # AST Syntax Verification for Python
            if full_path.suffix.lower() == ".py":
                import ast
                try:
                    ast.parse(modified_content, filename=str(full_path))
                except SyntaxError as syn_err:
                    return {
                        "success": False,
                        "error": f"SyntaxError in replacement: {syn_err.msg} at line {syn_err.lineno}",
                        "aborted": True,
                    }

            # Atomic file write
            tmp_path = full_path.with_suffix(full_path.suffix + ".tmp")
            tmp_path.write_text(modified_content, encoding="utf-8")
            os.replace(tmp_path, full_path)

            # Refresh index for this file
            from .parser import parse_python_file, parse_regex_file, JS_TS_PATTERN, RUST_GO_PATTERN
            ext = full_path.suffix.lower()
            if ext == ".py":
                self.index[norm_path] = parse_python_file(full_path, modified_content)
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                self.index[norm_path] = parse_regex_file(full_path, JS_TS_PATTERN, modified_content)
            elif ext in (".rs", ".go"):
                self.index[norm_path] = parse_regex_file(full_path, RUST_GO_PATTERN, modified_content)

            return {
                "success": True,
                "file": norm_path,
                "symbol": symbol_name,
                "lines_replaced": f"{start_line}-{end_line}",
                "original_line_count": end_line - start_line + 1,
                "new_line_count": len(replacement_lines),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

