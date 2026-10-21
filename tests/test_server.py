"""Unit tests for MCP Server protocol and tool execution."""
import json
import tempfile
import unittest
from pathlib import Path

from precision_mcp.server import MCPServer


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        (self.root / "sample.py").write_text('''
def greet(name: str):
    """Return greeting string."""
    return f"Hello {name}"
''', encoding="utf-8")

        self.server = MCPServer(str(self.root))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 1)
        self.assertEqual(res["result"]["serverInfo"]["name"], "precision-mcp")
        self.assertIn("tools", res["result"]["capabilities"])

    def test_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 2)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("index_codebase", tool_names)
        self.assertIn("find_symbol", tool_names)
        self.assertIn("get_outline", tool_names)
        self.assertIn("get_symbol_slice", tool_names)
        self.assertIn("find_callers", tool_names)

    def test_tools_call_find_symbol(self):
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "find_symbol",
                "arguments": {"query": "greet"},
            },
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 3)
        content = res["result"]["content"][0]["text"]
        self.assertIn("sample.py:2-4 [function] greet", content)

    def test_tools_call_get_symbol_slice(self):
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_symbol_slice",
                "arguments": {"file_path": "sample.py", "symbol_name": "greet"},
            },
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], 4)
        content = res["result"]["content"][0]["text"]
        self.assertIn("def greet(name: str):", content)
        self.assertIn('return f"Hello {name}"', content)


if __name__ == "__main__":
    unittest.main()
