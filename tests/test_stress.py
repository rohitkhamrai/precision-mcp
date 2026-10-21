"""Stress tests and complex edge cases for Precision-MCP."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from precision_mcp.indexer import CodebaseIndexer
from precision_mcp.parser import parse_python_file


class TestStressAndEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_complex_python_constructs(self):
        code = '''
from typing import Union, Optional, Callable, AsyncIterator
import functools

def custom_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

class BaseEngine:
    pass

@custom_decorator
class AdvancedProcessor(BaseEngine):
    """Class with complex methods and annotations."""
    
    @property
    def is_active(self) -> bool:
        return True

    @custom_decorator
    async def stream_records(
        self,
        query: dict[str, Union[int, str]],
        handler: Optional[Callable[[str], None]] = None,
    ) -> AsyncIterator[dict]:
        """Stream items matching query.
        
        Example:
            >>> stream_records({"id": 1})
        """
        self.log_call("stream_records")
        yield {"status": "ok"}

    def log_call(self, name: str):
        pass
'''
        file_path = self.root / "advanced.py"
        file_path.write_text(code, encoding="utf-8")

        indexer = CodebaseIndexer(self.root)
        stats = indexer.build()
        self.assertEqual(stats["files_indexed"], 1)

        # 1. Verify class extraction with methods
        classes = indexer.find_symbol("AdvancedProcessor")
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0]["type"], "class")

        # 2. Verify async annotated method extraction
        method = indexer.find_symbol("stream_records")
        self.assertEqual(len(method), 1)
        self.assertIn("AdvancedProcessor.stream_records", method[0]["symbol"])

        # 3. Verify callers tracing for method calls
        callers = indexer.find_callers("log_call")
        caller_names = [c["caller_symbol"] for c in callers]
        self.assertIn("AdvancedProcessor.stream_records", caller_names)

        # 4. Verify exact slice extraction preserves indentation
        slice_res = indexer.get_symbol_slice("advanced.py", "stream_records")
        self.assertIsNotNone(slice_res)
        self.assertIn("async def stream_records", slice_res["code"])
        self.assertIn('yield {"status": "ok"}', slice_res["code"])

    def test_concurrent_indexer_queries(self):
        # Create 10 files
        for i in range(10):
            (self.root / f"mod_{i}.py").write_text(f'''
def func_{i}(x):
    return x + {i}

def caller_{i}():
    return func_{i}(10)
''', encoding="utf-8")

        indexer = CodebaseIndexer(self.root)
        indexer.build()

        def query_worker(idx):
            sym = indexer.find_symbol(f"func_{idx}")
            slice_data = indexer.get_symbol_slice(f"mod_{idx}.py", f"func_{idx}")
            callers = indexer.find_callers(f"func_{idx}")
            return len(sym) == 1 and slice_data is not None and len(callers) == 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(query_worker, i) for i in range(10)]
            results = [f.result() for f in futures]

        self.assertTrue(all(results))

    def test_patch_symbol_multiline_replacement(self):
        code = '''
def calculate():
    # Simple calculation
    return 42
'''
        p = self.root / "calc.py"
        p.write_text(code, encoding="utf-8")

        indexer = CodebaseIndexer(self.root)
        indexer.build()

        new_code = '''def calculate():
    val = 100
    for i in range(5):
        val += i
    return val'''

        res = indexer.patch_symbol("calc.py", "calculate", new_code)
        self.assertTrue(res["success"])

        # Validate resulting code executes and returns 110
        import subprocess, sys
        test_run = subprocess.run(
            [sys.executable, "-c", "import calc; assert calc.calculate() == 110"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(test_run.returncode, 0)


if __name__ == "__main__":
    unittest.main()
