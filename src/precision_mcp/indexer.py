"""Codebase Indexer Engine with incremental mtime caching and multi-language AST support."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .parser import (
    JS_TS_PATTERNS,
    RUST_GO_PATTERNS,
    parse_c_family_file,
    parse_python_file,
    validate_syntax,
)

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
        self.file_mtimes: dict[str, float] = {}
        self.last_indexed_at: float = 0.0

    def build(self, force: bool = False) -> dict[str, Any]:
        """Scan workspace and generate or incrementally update symbol index."""
        start_time = time.perf_counter()

        if not force and not self.index:
            self.load_cache()

        existing_index = {} if force else self.index
        existing_mtimes = {} if force else self.file_mtimes

        new_index: dict[str, list[dict[str, Any]]] = {}
        new_mtimes: dict[str, float] = {}
        scanned_files = 0
        reparsed_files = 0

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORES and not d.startswith(".")]
            for f in files:
                p = Path(root) / f
                rel = p.relative_to(self.root_dir).as_posix()
                ext = p.suffix.lower()

                if ext not in (".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go"):
                    continue

                scanned_files += 1
                try:
                    mtime = os.path.getmtime(p)
                except OSError:
                    continue

                new_mtimes[rel] = mtime

                # Incremental cache hit
                if not force and rel in existing_index and existing_mtimes.get(rel) == mtime:
                    new_index[rel] = existing_index[rel]
                    continue

                # Parse modified or new file
                reparsed_files += 1
                symbols: list[dict[str, Any]] = []
                if ext == ".py":
                    symbols = parse_python_file(p)
                elif ext in (".js", ".ts", ".jsx", ".tsx"):
                    symbols = parse_c_family_file(p, JS_TS_PATTERNS)
                elif ext in (".rs", ".go"):
                    symbols = parse_c_family_file(p, RUST_GO_PATTERNS)

                if symbols:
                    new_index[rel] = symbols

        self.index = new_index
        self.file_mtimes = new_mtimes
        self.last_indexed_at = time.time()
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Write cache
        self.save_cache()

        total_symbols = sum(len(v) for v in self.index.values())
        return {
            "files_indexed": len(self.index),
            "total_scanned": scanned_files,
            "reparsed_count": reparsed_files,
            "symbols_indexed": total_symbols,
            "elapsed_ms": elapsed_ms,
            "root": str(self.root_dir),
        }

    def save_cache(self) -> None:
        """Persist index and file mtimes to disk."""
        data = {
            "metadata": {"last_indexed": self.last_indexed_at, "version": "2.0"},
            "files": {
                rel: {"mtime": self.file_mtimes.get(rel, 0.0), "symbols": syms}
                for rel, syms in self.index.items()
            },
        }
        try:
            self.index_cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_cache(self) -> bool:
        """Load index from on-disk cache if present."""
        if not self.index_cache_path.is_file():
            return False
        try:
            data = json.loads(self.index_cache_path.read_text(encoding="utf-8"))
            files_data = data.get("files", {})
            self.index = {rel: info["symbols"] for rel, info in files_data.items() if "symbols" in info}
            self.file_mtimes = {rel: info.get("mtime", 0.0) for rel, info in files_data.items()}
            return True
        except Exception:
            return False

    def ensure_indexed(self) -> None:
        """Ensure the index is available in memory with incremental refresh."""
        if not self.index:
            if not self.load_cache():
                self.build(force=True)
            else:
                # Fast incremental check for dirty files
                self.build(force=False)

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
            match_key = next((k for k in self.index if k.endswith(norm_path)), None)
            symbols = self.index.get(match_key, []) if match_key else []
        return symbols

    def get_symbol_slice(self, file_path: str, symbol_name: str) -> dict[str, Any] | None:
        """Extract exact line boundaries and raw source text for a single symbol."""
        norm_path = Path(file_path).as_posix()
        full_path = self.root_dir / norm_path
        if not full_path.is_file():
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
        """Surgically replace a symbol's code block with multi-language AST syntax validation."""
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

            newline = "\r\n" if "\r\n" in original_content else "\n"

            # Replace lines [start_line - 1 : end_line]
            replacement_lines = new_code.strip().splitlines()
            new_lines = lines[: start_line - 1] + replacement_lines + lines[end_line:]
            modified_content = newline.join(new_lines) + newline

            # Multi-Language Syntax Verification Gate
            is_valid, err_msg = validate_syntax(full_path.suffix, modified_content)
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Syntax verification failed: {err_msg}",
                    "aborted": True,
                }

            # Atomic file write
            tmp_path = full_path.with_suffix(full_path.suffix + ".tmp")
            tmp_path.write_text(modified_content, encoding="utf-8")
            os.replace(tmp_path, full_path)

            # Update cache & mtime for this file
            ext = full_path.suffix.lower()
            if ext == ".py":
                self.index[norm_path] = parse_python_file(full_path, modified_content)
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                self.index[norm_path] = parse_c_family_file(full_path, JS_TS_PATTERNS, modified_content)
            elif ext in (".rs", ".go"):
                self.index[norm_path] = parse_c_family_file(full_path, RUST_GO_PATTERNS, modified_content)

            self.file_mtimes[norm_path] = os.path.getmtime(full_path)
            self.save_cache()

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
