"""Semantic indexers for code-intel.

This module provides semantic indexers that use language servers
for comprehensive code analysis beyond what Tree-sitter can provide.
"""

from code_intel.indexer.roslyn import RoslynIndexer

__all__ = [
    "RoslynIndexer",
]
