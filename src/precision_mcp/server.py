"""High-performance JSON-RPC stdio MCP server for precision-mcp."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any

from .indexer import CodebaseIndexer

SERVER_NAME = "precision-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS_DEFINITIONS = [
    {
        "name": "index_codebase",
        "description": "Scan and index all classes, functions, and methods across the workspace for sub-millisecond symbol search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Root path of the workspace (defaults to current working directory).",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force a fresh re-scan instead of using the on-disk index cache.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "find_symbol",
        "description": "Locate classes, functions, or methods by name. Returns file paths, exact line bounds [start_line, end_line], parameter signatures, and docstrings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The symbol name or substring to search for (e.g. 'assemble_piece', 'UserSession').",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_outline",
        "description": "Get the structural skeleton (all classes, functions, line bounds) of a file without reading its entire contents into context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File path relative to the workspace root (e.g. 'core/assemble.py').",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "get_symbol_slice",
        "description": "Extract the exact source code block of a single function or class by symbol name without reading the surrounding file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File path containing the symbol.",
                },
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the function, class, or method to slice.",
                },
            },
            "required": ["file_path", "symbol_name"],
        },
    },
    {
        "name": "find_callers",
        "description": "Find all functions and methods in the codebase that invoke a given function or method.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "The function or method name to trace callers for.",
                },
            },
            "required": ["symbol_name"],
        },
    },
]


class MCPServer:
    """Zero-dependency JSON-RPC stdio Model Context Protocol server."""

    def __init__(self, root_dir: str = ".") -> None:
        self.indexer = CodebaseIndexer(root_dir)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS_DEFINITIONS,
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                result_text = self.execute_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": result_text,
                            }
                        ]
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing tool '{tool_name}': {str(e)}\n{traceback.format_exc()}",
                            }
                        ],
                    },
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }

    def execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "index_codebase":
            workspace_path = args.get("workspace_path")
            if workspace_path:
                self.indexer = CodebaseIndexer(workspace_path)
            res = self.indexer.build(force=args.get("force", False))
            return json.dumps(res, indent=2)

        elif name == "find_symbol":
            query = args.get("query", "")
            matches = self.indexer.find_symbol(query)
            if not matches:
                return f"No symbols found matching '{query}'"
            lines = [f"Found {len(matches)} match(es) for '{query}':\n"]
            for m in matches:
                args_str = f"({', '.join(m.get('args', []))})" if "args" in m else ""
                lines.append(f"- {m['file']}:{m['start_line']}-{m['end_line']} [{m['type']}] {m['symbol']}{args_str}")
                if m.get("doc"):
                    first_line = m["doc"].strip().splitlines()[0]
                    lines.append(f"    doc: {first_line}")
            return "\n".join(lines)

        elif name == "get_outline":
            file_path = args.get("file_path", "")
            outline = self.indexer.get_outline(file_path)
            if not outline:
                return f"No symbols or file not found for '{file_path}'"
            lines = [f"Outline for {file_path}:\n"]
            for s in outline:
                lines.append(f"  L{s['start_line']}-{s['end_line']}: {s.get('type', 'symbol')} {s['name']}")
                for m in s.get("methods", []):
                    lines.append(f"    L{m['start_line']}-{m['end_line']}: method {m['name']}")
            return "\n".join(lines)

        elif name == "get_symbol_slice":
            file_path = args.get("file_path", "")
            symbol_name = args.get("symbol_name", "")
            res = self.indexer.get_symbol_slice(file_path, symbol_name)
            if not res:
                return f"Symbol '{symbol_name}' not found in '{file_path}'"
            return (
                f"### {res['file']}:{res['start_line']}-{res['end_line']} ({res['type']} {res['symbol']})\n\n"
                f"```python\n{res['code']}\n```"
            )

        elif name == "find_callers":
            symbol_name = args.get("symbol_name", "")
            callers = self.indexer.find_callers(symbol_name)
            if not callers:
                return f"No callers found for symbol '{symbol_name}'"
            lines = [f"Found {len(callers)} caller(s) for '{symbol_name}':\n"]
            for c in callers:
                lines.append(f"- {c['file']}:L{c['start_line']} in {c['caller_type']} '{c['caller_symbol']}'")
            return "\n".join(lines)

        else:
            raise ValueError(f"Unknown tool name: {name}")

    def run_stdio(self) -> None:
        """Run standard I/O loop reading newline-delimited JSON-RPC messages."""
        # Force utf-8 on stdio
        if sys.platform == "win32":
            import msvcrt
            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

        stdin_buffer = sys.stdin.buffer
        stdout_buffer = sys.stdout.buffer

        while True:
            line = stdin_buffer.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
                stdout_buffer.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                stdout_buffer.flush()
                continue

            response = self.handle_request(request)
            if response is not None:
                stdout_buffer.write((json.dumps(response) + "\n").encode("utf-8"))
                stdout_buffer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Precision-MCP Server")
    parser.add_argument("--root", default=".", help="Root directory for codebase indexing")
    args = parser.parse_args()

    server = MCPServer(args.root)
    server.run_stdio()


if __name__ == "__main__":
    main()
