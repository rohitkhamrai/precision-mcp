"""Unit tests for indexer and parser."""
import tempfile
import unittest
from pathlib import Path

from precision_mcp.indexer import CodebaseIndexer
from precision_mcp.parser import parse_python_file, parse_regex_file, JS_TS_PATTERN


class TestParser(unittest.TestCase):
    def test_parse_python(self):
        code = '''
def add(a, b):
    """Add two numbers."""
    return a + b

class Calculator:
    """A simple calculator class."""
    def multiply(self, x, y):
        return x * y

    async def compute(self, val):
        return add(val, 10)
'''
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = Path(f.name)

        try:
            symbols = parse_python_file(tmp_path)
            self.assertEqual(len(symbols), 2)

            func = symbols[0]
            self.assertEqual(func["name"], "add")
            self.assertEqual(func["type"], "function")
            self.assertEqual(func["args"], ["a", "b"])
            self.assertEqual(func["doc"], "Add two numbers.")

            cls = symbols[1]
            self.assertEqual(cls["name"], "Calculator")
            self.assertEqual(cls["type"], "class")
            self.assertEqual(len(cls["methods"]), 2)
            self.assertEqual(cls["methods"][0]["name"], "multiply")
            self.assertEqual(cls["methods"][1]["name"], "compute")
            self.assertIn("add", cls["methods"][1]["calls"])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_parse_js_ts(self):
        code = '''
export function calculateTax(amount) {
    return amount * 0.15;
}
export class OrderService {
    process() {}
}
const fetchUsers = async () => {};
'''
        with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = Path(f.name)

        try:
            symbols = parse_regex_file(tmp_path, JS_TS_PATTERN)
            names = [s["name"] for s in symbols]
            self.assertIn("calculateTax", names)
            self.assertIn("OrderService", names)
            self.assertIn("fetchUsers", names)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestIndexer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create sample files
        (self.root / "math_utils.py").write_text('''
def square(n):
    """Square of a number."""
    return n * n

def helper():
    return square(2)
''', encoding="utf-8")

        (self.root / "service.py").write_text('''
from math_utils import square

class Runner:
    def execute(self, val):
        return square(val)
''', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_build_and_find(self):
        indexer = CodebaseIndexer(self.root)
        stats = indexer.build()

        self.assertEqual(stats["files_indexed"], 2)
        self.assertGreater(stats["symbols_indexed"], 0)

        matches = indexer.find_symbol("square")
        self.assertTrue(any(m["symbol"] == "square" and m["file"] == "math_utils.py" for m in matches))

    def test_get_symbol_slice(self):
        indexer = CodebaseIndexer(self.root)
        indexer.build()

        res = indexer.get_symbol_slice("math_utils.py", "square")
        self.assertIsNotNone(res)
        self.assertEqual(res["start_line"], 2)
        self.assertEqual(res["end_line"], 4)
        self.assertIn("def square(n):", res["code"])
        self.assertIn("return n * n", res["code"])

    def test_find_callers(self):
        indexer = CodebaseIndexer(self.root)
        indexer.build()

        callers = indexer.find_callers("square")
        caller_symbols = [c["caller_symbol"] for c in callers]
        self.assertIn("helper", caller_symbols)
        self.assertIn("Runner.execute", caller_symbols)

    def test_get_impact_radius(self):
        indexer = CodebaseIndexer(self.root)
        indexer.build()

        impact = indexer.get_impact_radius("square", max_depth=2)
        self.assertEqual(impact["target_symbol"], "square")
        self.assertGreaterEqual(impact["total_callers"], 2)
        self.assertIn("math_utils.py", impact["affected_files"])
        self.assertIn("service.py", impact["affected_files"])

    def test_patch_symbol_success(self):
        indexer = CodebaseIndexer(self.root)
        indexer.build()

        new_code = '''def square(n):
    """Enhanced square with validation."""
    if not isinstance(n, (int, float)):
        raise TypeError("Number required")
    return n * n'''

        res = indexer.patch_symbol("math_utils.py", "square", new_code)
        self.assertTrue(res["success"])
        self.assertEqual(res["symbol"], "square")

        # Verify file content updated
        content = (self.root / "math_utils.py").read_text(encoding="utf-8")
        self.assertIn("Enhanced square with validation", content)

        # Verify re-indexed
        sym_slice = indexer.get_symbol_slice("math_utils.py", "square")
        self.assertIn("TypeError", sym_slice["code"])

    def test_patch_symbol_syntax_error_rollback(self):
        indexer = CodebaseIndexer(self.root)
        indexer.build()

        broken_code = '''def square(n):
    return n * * n  # Invalid syntax'''

        res = indexer.patch_symbol("math_utils.py", "square", broken_code)
        self.assertFalse(res["success"])
        self.assertTrue(res["aborted"])
        self.assertIn("SyntaxError", res["error"])

        # Verify original file untouched
        content = (self.root / "math_utils.py").read_text(encoding="utf-8")
        self.assertNotIn("n * * n", content)


if __name__ == "__main__":
    unittest.main()
