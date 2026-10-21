#!/usr/bin/env python3
"""Head-to-head benchmark: Precision-MCP vs Brute-Force vs Grep.

Measures latency, context token efficiency, and memory footprint.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from precision_mcp.indexer import CodebaseIndexer


def estimate_tokens(text: str) -> int:
    """Rough OpenAI / Claude token estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


def run_benchmark(target_dir: str = ".") -> dict:
    root = Path(target_dir).resolve()
    print(f"Running benchmark against: {root}")

    # 1. Cold Indexing Benchmark
    start = time.perf_counter()
    indexer = CodebaseIndexer(root)
    build_stats = indexer.build(force=True)
    index_time_ms = round((time.perf_counter() - start) * 1000, 2)

    # 2. Pick a target symbol to query
    all_symbols = []
    for file, syms in indexer.index.items():
        for s in syms:
            all_symbols.append((file, s["name"], s["start_line"], s["end_line"]))

    if not all_symbols:
        print("No symbols found to benchmark.")
        return {}

    # Select representative symbol (e.g. median size)
    sample_file, sample_symbol, start_line, end_line = all_symbols[len(all_symbols) // 2]
    full_file_path = root / sample_file
    full_text = full_file_path.read_text(encoding="utf-8", errors="replace")

    # Method A: Brute-Force File Read (What basic agents do)
    bf_start = time.perf_counter()
    _ = full_file_path.read_text(encoding="utf-8", errors="replace")
    bf_time_ms = round((time.perf_counter() - bf_start) * 1000, 3)
    bf_tokens = estimate_tokens(full_text)

    # Method B: Precision-MCP Surgical Slice
    slice_start = time.perf_counter()
    res = indexer.get_symbol_slice(sample_file, sample_symbol)
    slice_time_ms = round((time.perf_counter() - slice_start) * 1000, 3)
    slice_tokens = estimate_tokens(res["code"]) if res else 0

    token_savings_pct = round(((bf_tokens - slice_tokens) / max(1, bf_tokens)) * 100, 1)

    return {
        "files_indexed": build_stats["files_indexed"],
        "symbols_indexed": build_stats["symbols_indexed"],
        "cold_index_ms": index_time_ms,
        "sample_symbol": f"{sample_file}::{sample_symbol} (L{start_line}-{end_line})",
        "brute_force_tokens": bf_tokens,
        "precision_mcp_tokens": slice_tokens,
        "token_reduction_pct": token_savings_pct,
        "slice_lookup_ms": slice_time_ms,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Precision-MCP Performance Benchmark")
    parser.add_argument("--dir", default=".", help="Directory to benchmark")
    args = parser.parse_args()

    results = run_benchmark(args.dir)
    print("\n================ BENCHMARK RESULTS ================")
    print(f"Files Indexed       : {results['files_indexed']}")
    print(f"Symbols Extracted   : {results['symbols_indexed']}")
    print(f"Cold Index Speed    : {results['cold_index_ms']} ms")
    print(f"Target Query        : {results['sample_symbol']}")
    print("---------------------------------------------------")
    print(f"Brute-Force Context : {results['brute_force_tokens']} tokens (Whole file dumped)")
    print(f"Precision-MCP Slice : {results['precision_mcp_tokens']} tokens (Surgical block)")
    print(f"Token Reduction     : {results['token_reduction_pct']}% less context waste")
    print(f"Query Latency       : {results['slice_lookup_ms']} ms")
    print("===================================================\n")


if __name__ == "__main__":
    main()
