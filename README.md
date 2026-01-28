# Code-Intel

Code graph intelligence for AI assistants - semantic code understanding via AST analysis.

## Overview

Code-intel provides a semantic understanding layer for codebases that goes beyond text matching:

- **"Find all callers of this function"** - call graph traversal, not grep
- **"What type is this variable?"** - type inference from AST
- **"Show inheritance hierarchy"** - structural understanding
- **"What breaks if I change this interface?"** - impact analysis

## Architecture

```
┌────────────────────┐     ┌─────────────────────┐     ┌────────────────────┐
│   Data Sources     │     │   Graph Index       │     │  Query Layer       │
├────────────────────┤     ├─────────────────────┤     ├────────────────────┤
│ • Tree-sitter      │     │                     │     │                    │
│ • Static analysis  │ ──▶ │  Nodes: files,      │ ──▶ │  Python Client     │
│ • Git history      │     │  functions,         │     │  Gateway MCP       │
│ • Import graphs    │     │  classes, types     │     │  Plugin            │
│                    │     │                     │     │                    │
│                    │     │  Edges: calls,      │     │                    │
│                    │     │  imports,           │     │                    │
│                    │     │  inherits,          │     │                    │
│                    │     │  references         │     │                    │
└────────────────────┘     └─────────────────────┘     └────────────────────┘
```

## Installation

```bash
pip install code-intel
```

With language support:

```bash
# TypeScript/JavaScript
pip install code-intel[typescript]

# Python
pip install code-intel[python]

# C#
pip install code-intel[csharp]

# All languages
pip install code-intel[all-languages]
```

## Quick Start

```python
from code_intel import CodeIntelClient

client = CodeIntelClient()

# Index a repository
client.index_repo("/path/to/repo")

# Find all callers of a function
callers = client.find_callers("processPayment")
for caller in callers:
    print(f"{caller.file}:{caller.line} - {caller.function}")

# Find all references to a symbol
refs = client.find_references("UserService")
print(f"Found {len(refs)} references")

# Get symbol information
info = client.get_symbol_info("authenticate")
print(f"Type: {info.type}, Defined in: {info.file}:{info.line}")

# Impact analysis
impact = client.impact_analysis("IAuthProvider")
print(f"Changing this interface affects {len(impact.affected_files)} files")
```

## Supported Languages

| Language | Status | Parser |
|----------|--------|--------|
| TypeScript | Planned | tree-sitter-typescript |
| Python | Planned | tree-sitter-python |
| C# | Planned | tree-sitter-c-sharp |

## Storage

Code-intel uses SQLite for graph storage, keeping things simple and portable:

- Single `.code-intel.db` file per indexed repository
- No external database infrastructure required
- Fast graph queries via optimised schema

## Gateway MCP Integration

Code-intel is designed to be exposed via Gateway MCP as the `code_intel` service:

```python
# Via Gateway MCP
mcp__gateway__call(
    service="code_intel",
    action="find_callers",
    params={"symbol": "processPayment", "repo": "/path/to/repo"}
)
```

## Development

### Setup

```bash
git clone https://github.com/ashburnstudios/code-intel.git
cd code-intel
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,all-languages]"
```

### Testing

```bash
pytest
```

## Related Projects

- [Memoria](https://github.com/ashburnstudios/memoria) - Persistent semantic memory for AI assistants
- [Gateway MCP](https://github.com/ashburnstudios/gateway-mcp) - Unified MCP gateway
- [Foundry](https://github.com/ashburnstudios/foundry) - Autonomous development system

## License

MIT - see [LICENSE](LICENSE)
