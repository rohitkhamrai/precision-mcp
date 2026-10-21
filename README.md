<div align="center">

# ⚡ Precision-MCP

**Cursor-style AST Codebase Indexing & Surgical Slicing MCP Server for AI Coding Agents**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: >=3.10](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Protocol: MCP](https://img.shields.io/badge/MCP-2024--11--05-green.svg)](https://modelcontextprotocol.io/)
[![Zero External Dependencies](https://img.shields.io/badge/Dependencies-Zero-success.svg)](#features)

*Stop dumping 500-line files into your LLM context window. Give any AI agent Cursor-grade AST symbol navigation in <15ms.*

</div>

---

## 🚀 The Problem

Modern coding agents (Claude Code, Gemini CLI, Cursor, Windsurf, OpenCode) suffer from **context rot**:
1. **Whole-File Dumping**: Reading entire files to inspect a single 20-line method floods the context window with boilerplate, increasing API costs by 10x.
2. **Context Window Degradation**: Large codebases cause fast models to lose instruction adherence, skip edge cases, or crash on token limits.
3. **Slow Brute-Force Regex**: Scanning with regex fails to distinguish between declarations, call sites, and comments.

**Precision-MCP** solves this by providing a lightweight, high-performance AST indexing engine over the **Model Context Protocol (MCP)**. It indexes your workspace in milliseconds and lets agents retrieve exact symbol slices with zero surrounding bloat.

---

## ⚡ Performance Benchmarks

*Benchmarked on a real-world repository (50 files, ~8,000 LOC, Python 3.13)*:

| Operation | Brute-Force File Read | Standard Ripgrep | **Precision-MCP** |
|---|---|---|---|
| **Cold Workspace Indexing** | N/A | N/A | **<18 ms** |
| **Symbol Line Lookup** | ~45 ms (read all) | ~25 ms (text search) | **<1.2 ms** (indexed AST) |
| **Context Overhead** | 500+ lines dumped | Match line only (no body) | **Exact block slice only** |
| **Memory Footprint** | Process memory bloat | Variable | **<12 MB** (Zero dependencies) |

---

## 🛠️ Architecture

```
┌────────────────────────────────────────────────────────┐
│  AI Coding Agent (Claude Code / Cursor / Gemini CLI)  │
└──────────────────────────┬─────────────────────────────┘
                           │ JSON-RPC 2.0 (stdio)
                           ▼
┌────────────────────────────────────────────────────────┐
│                    Precision-MCP                       │
│                                                        │
│  ┌──────────────────┐           ┌───────────────────┐  │
│  │   MCP Server     │           │    AST Parser     │  │
│  │  (stdio driver)  │ ────────► │  (Python AST +    │  │
│  └────────┬─────────┘           │   Regex TS/Go/Rs) │  │
│           │                     └─────────┬─────────┘  │
│           ▼                               ▼            │
│  ┌──────────────────────────────────────────────────┐  │
│  │     CodebaseIndexer (.precision_index.json)      │  │
│  │     - Symbol graph (Classes, Methods, Funcs)     │  │
│  │     - Exact [start_line, end_line] slices        │  │
│  │     - Call-site graph & caller tracing           │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 📦 Installation & Setup

### Option 1: Run instantly with `uvx` (No installation needed)
```bash
uvx precision-mcp
```

### Option 2: Install via `pip`
```bash
pip install -e .
precision-mcp
```

---

## ⚙️ Configuration in Agents

### 1. Claude Desktop / Claude Code (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "precision-mcp": {
      "command": "python",
      "args": ["-m", "precision_mcp.server", "--root", "/path/to/your/project"]
    }
  }
}
```

### 2. Cursor IDE (`settings.json`)
```json
{
  "mcp": {
    "servers": {
      "precision-mcp": {
        "command": "precision-mcp",
        "args": ["--root", "."]
      }
    }
  }
}
```

### 3. Antigravity IDE / Gemini CLI (`mcp_config.json`)
```json
{
  "mcpServers": {
    "precision-mcp": {
      "command": "python",
      "args": ["-m", "precision_mcp.server", "--root", "."]
    }
  }
}
```

---

## 🧩 Exposed MCP Tools

| Tool | Parameters | Description |
|---|---|---|
| `index_codebase` | `workspace_path?`, `force?` | Scans and indexes the workspace into an in-memory symbol graph in <18ms. |
| `find_symbol` | `query` | Locates functions, classes, or methods with exact line boundaries `[start, end]`, signatures, and docstrings. |
| `get_outline` | `file_path` | Generates structural skeleton of any file without reading its entire body. |
| `get_symbol_slice` | `file_path`, `symbol_name` | Extracts the exact source code block of a single function or class. |
| `find_callers` | `symbol_name` | Identifies all direct callers of a given symbol across the codebase. |
| `get_impact_radius` | `symbol_name`, `max_depth?` | **Blast Radius Analyzer**: Traces cascading multi-level callers and affected files before refactoring. |
| `patch_symbol` | `file_path`, `symbol_name`, `new_code` | **AST-Safe Surgical Mutator**: Replaces a symbol block and verifies AST syntax. Rolls back automatically if syntax is invalid. |


---

## 🧪 Testing

Run unit tests across parser, indexer, and MCP protocol handlers:

```bash
python -m unittest discover -s tests -v
```

---

## 📄 License

MIT © [Rohit Kumar Khamrai](https://github.com/rohitkhamrai)
