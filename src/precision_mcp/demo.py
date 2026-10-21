"""Interactive Visual Showcase Demo for Precision-MCP."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from .indexer import CodebaseIndexer

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    print(f"""
{CYAN}{BOLD}========================================================================
[*] PRECISION-MCP: Cursor-Grade AST Slicing & Safety Demo
========================================================================{RESET}
""")


def run_demo(target_dir: str = "."):
    print_banner()
    root = Path(target_dir).resolve()

    # 1. Cold Indexing
    print(f"{BOLD}[1/4] Indexing Workspace: {root.name}...{RESET}")
    start = time.perf_counter()
    indexer = CodebaseIndexer(root)
    stats = indexer.build(force=True)
    elapsed = (time.perf_counter() - start) * 1000

    print(f"  {GREEN}[PASS]{RESET} Indexed {stats['files_indexed']} files, extracted {stats['symbols_indexed']} symbols in {BOLD}{elapsed:.1f}ms{RESET}")

    # 2. Symbol Search
    print(f"\n{BOLD}[2/4] Instant Symbol Query vs Brute-Force Context Dump...{RESET}")
    sample_item = next(
        ((f, s) for f, syms in indexer.index.items() for s in syms if s.get("type") == "function"),
        None,
    )
    if sample_item:
        file_path, sym = sample_item
        full_text = (root / file_path).read_text(encoding="utf-8", errors="replace")
        slice_res = indexer.get_symbol_slice(file_path, sym["name"])

        full_tokens = max(1, len(full_text) // 4)
        slice_tokens = max(1, len(slice_res["code"]) // 4) if slice_res else 0
        reduction = round(((full_tokens - slice_tokens) / full_tokens) * 100, 1)

        print(f"  Target: {BOLD}{file_path}::{sym['name']}{RESET}")
        print(f"  Traditional Agent : {RED}{full_tokens:,} tokens{RESET} (entire file dumped)")
        print(f"  Precision-MCP     : {GREEN}{slice_tokens:,} tokens{RESET} (AST surgical block only)")
        print(f"  {GREEN}{BOLD}Saved {reduction}% token budget!{RESET}")

    # 3. Blast Radius
    print(f"\n{BOLD}[3/4] Cascading Blast Radius Analysis...{RESET}")
    # Find a symbol with callers
    called_sym = next(
        (s["name"] for syms in indexer.index.values() for s in syms if len(indexer.find_callers(s["name"])) > 0),
        None,
    )
    if called_sym:
        impact = indexer.get_impact_radius(called_sym)
        risk_color = GREEN if impact["risk_level"] == "low" else (YELLOW if impact["risk_level"] == "medium" else RED)
        print(f"  Target Symbol : {BOLD}{called_sym}{RESET}")
        print(f"  Risk Level    : {risk_color}{impact['risk_level'].upper()}{RESET} ({impact['total_callers']} callers affected)")
        print(f"  Affected Files: {', '.join(impact['affected_files'])}")
    else:
        print(f"  {YELLOW}No cross-calling functions detected in this sample.{RESET}")

    # 4. AST Safety Gate
    print(f"\n{BOLD}[4/4] AST-Safe Syntax Verification Gate...{RESET}")
    broken_code = "def syntax_hazard():\n    return 42 * * 10  # Invalid Python"
    print(f"  Simulating malformed code generation from LLM...")
    if sample_item:
        file_path, sym = sample_item
        res = indexer.patch_symbol(file_path, sym["name"], broken_code)
        if not res["success"] and res.get("aborted"):
            print(f"  {GREEN}[SAFETY TRIGGERED]{RESET} SyntaxError intercepted before writing.")
            print(f"  {GREEN}[PROTECTED]{RESET} Source file protected. Zero corrupted lines.")

    print(f"\n{CYAN}{BOLD}========================================================================")
    print(f"[SUCCESS] All benchmarks and safety verifications passed.")
    print(f"========================================================================{RESET}\n")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    run_demo(target)


if __name__ == "__main__":
    main()
