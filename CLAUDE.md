# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

Code-intel is a Python library that provides semantic code understanding for AI assistants. It parses codebases using Tree-sitter, builds a graph of code relationships, and exposes queries for call graphs, references, type information, and impact analysis.

## Architecture

```
src/code_intel/
├── __init__.py          # Package exports
├── client.py            # CodeIntelClient (sync) - main API
├── async_client.py      # AsyncCodeIntelClient - async version
├── graph/               # SQLite graph storage
│   ├── __init__.py
│   ├── schema.py        # Graph node/edge schema
│   └── storage.py       # SQLite operations
└── parser/              # Tree-sitter parsing
    ├── __init__.py
    ├── base.py          # Base parser interface
    ├── typescript.py    # TypeScript/JS parser
    ├── python.py        # Python parser
    └── csharp.py        # C# parser
```

## Design Principles

### Lifted, Not Forked

This project lifts concepts and patterns from [code-graph-rag-mcp](https://github.com/er77/code-graph-rag-mcp) (MIT licensed) but is a clean-room Python implementation. We don't fork the TypeScript codebase - we learn from its API surface and implement what we need in our stack.

### Phased Delivery

1. **Phase 1**: Parser + SQLite graph + basic queries (find_callers, find_references, get_symbol_info)
2. **Phase 2**: Gateway MCP wrapper as thin plugin
3. **Phase 3**: Semantic search via Qdrant (optional)
4. **Phase 4**: Impact analysis, temporal coupling from git history

### SQLite for Storage

We use SQLite for graph storage because:
- Foundry already uses SQLite patterns
- No external infrastructure required
- Single file per indexed repo (`.code-intel.db`)
- Fast enough for typical project sizes

### Gateway MCP Integration

Code-intel is designed to be consumed via Gateway MCP:
- Exposed as `code_intel` service
- Actions: `index`, `find_callers`, `find_references`, `get_symbol_info`, `impact_analysis`
- Thin wrapper in `gateway-mcp/src/gateway_mcp/services/code_intel/plugin.py`

## Language Support Priority

Based on our codebases:
1. **TypeScript** - Foundry, Gateway MCP, Claude Code plugins (fastest iteration)
2. **Python** - Gateway MCP plugins, n8n code nodes
3. **C#** - PLOD (larger legacy codebase, benefits most from impact analysis)

## Development Patterns

### Following Memoria's Lead

This project follows the same patterns as [memoria](https://github.com/ashburnstudios/memoria):
- Standalone Python library with sync/async clients
- Gateway MCP wrapper as thin plugin
- Pydantic models for data structures
- pytest for testing

### Common Commands

```bash
# Install in development mode
pip install -e ".[dev,all-languages]"

# Run tests
pytest

# Type checking (when added)
mypy src/code_intel

# Build package
python -m build
```

## Key Files to Understand

When implementing features:
- `client.py` - Main API surface, start here
- `graph/schema.py` - Node and edge types
- `parser/base.py` - Parser interface that all language parsers implement

## Jira Integration

This project tracks work in the CINT Jira space. Cards follow the pattern:
- `CINT-XX` for code-intel library work
- `GTWY-XX` for Gateway MCP plugin work

## Version Control

Uses git with conventional commits. Commit regularly and autonomously when completing logical units of work.
