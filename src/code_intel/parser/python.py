"""Python parser using Tree-sitter for AST analysis."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


@dataclass
class ImportEntry:
    """An entry in the import map tracking what an imported name resolves to.

    Attributes:
        local_name: The name used in the local scope (may be aliased).
        module: The fully-qualified module path the import comes from.
        symbol: The symbol name within the module (None if importing module itself).
        import_type: One of 'module', 'from', or 'wildcard'.
    """

    local_name: str
    module: str
    symbol: str | None = None
    import_type: str = "from"


class PythonParser(BaseParser):
    """Parser for Python source code using tree-sitter-python.

    Extracts:
    - Nodes: functions, classes, methods, module-level variables, imports
    - Edges: calls, imports, inheritance, references
    """

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def file_extensions(self) -> list[str]:
        return [".py", ".pyi"]

    def _load_language(self) -> "Language":
        """Load the tree-sitter-python grammar."""
        from tree_sitter import Language
        import tree_sitter_python as tspython

        # The language() function returns a PyCapsule that must be wrapped
        return Language(tspython.language())

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from Python AST.

        Extracts:
        - Function definitions (function_definition)
        - Class definitions (class_definition)
        - Method definitions (function_definition inside class)
        - Module-level variable assignments
        - Import statements

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.

        Returns:
            List of symbol dictionaries.
        """
        symbols: list[dict] = []
        self._extract_symbols_recursive(tree.root_node, source, symbols, context=None)
        return symbols

    def _extract_symbols_recursive(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Recursively extract symbols from AST nodes.

        Args:
            node: Current AST node.
            source: Original source bytes.
            symbols: List to append symbols to.
            context: Parent context (class name, etc.) for qualified names.
        """
        if node.type == "function_definition":
            self._extract_function(node, source, symbols, context)
        elif node.type == "class_definition":
            self._extract_class(node, source, symbols, context)
        elif node.type == "assignment" and self._is_module_level(node):
            self._extract_variable(node, source, symbols)
        elif node.type == "import_statement":
            self._extract_import(node, source, symbols)
        elif node.type == "import_from_statement":
            self._extract_import_from(node, source, symbols)
        else:
            # Recurse into children
            for child in node.children:
                self._extract_symbols_recursive(child, source, symbols, context)

    def _is_module_level(self, node: "Node") -> bool:
        """Check if a node is at module level.

        For assignments, they are wrapped in expression_statement, so we need
        to check if the grandparent is the module.
        """
        parent = node.parent
        if parent is None:
            return False

        # Direct child of module
        if parent.type == "module":
            return True

        # For assignments inside expression_statement
        if parent.type == "expression_statement":
            grandparent = parent.parent
            return grandparent is not None and grandparent.type == "module"

        return False

    def _extract_function(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract a function or method definition."""
        # Get function name
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Determine if this is a method (inside a class)
        is_method = context is not None and context.get("type") == "class"
        kind = "method" if is_method else "function"

        # Build qualified name
        qualified_name = name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"

        # Extract signature (function name + parameters)
        params_node = node.child_by_field_name("parameters")
        signature = None
        if params_node:
            params_text = self.get_node_text(params_node, source)
            # Check for return type annotation
            return_type = node.child_by_field_name("return_type")
            if return_type:
                return_type_text = self.get_node_text(return_type, source)
                signature = f"def {name}{params_text} -> {return_type_text}"
            else:
                signature = f"def {name}{params_text}"

        # Extract docstring if present
        docstring = self._extract_docstring(node, source)

        # Extract decorators
        decorators = self._extract_decorators(node, source)

        symbol = {
            "name": name,
            "kind": kind,
            "line": node.start_point[0] + 1,  # 1-indexed
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "docstring": docstring,
            "metadata": {},
        }

        if decorators:
            symbol["metadata"]["decorators"] = decorators

        # Check for async function
        if self._is_async_function(node):
            symbol["metadata"]["async"] = True
            if signature:
                symbol["signature"] = f"async {signature}"

        symbols.append(symbol)

        # Don't recurse into nested functions for now - they're local
        # We only want to extract methods from classes

    def _extract_class(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract a class definition and its methods."""
        # Get class name
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        qualified_name = name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"

        # Extract docstring
        docstring = self._extract_docstring(node, source)

        # Extract decorators
        decorators = self._extract_decorators(node, source)

        # Extract base classes
        bases = self._extract_base_classes(node, source)

        symbol = {
            "name": name,
            "kind": "class",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        if decorators:
            symbol["metadata"]["decorators"] = decorators
        if bases:
            symbol["metadata"]["bases"] = bases

        symbols.append(symbol)

        # Create context for extracting methods
        class_context = {
            "type": "class",
            "name": name,
            "qualified_name": qualified_name,
        }

        # Extract methods from class body
        body_node = node.child_by_field_name("body")
        if body_node:
            for child in body_node.children:
                self._extract_symbols_recursive(child, source, symbols, class_context)

    def _extract_variable(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract module-level variable assignments."""
        # Get the left side of assignment
        left = node.child_by_field_name("left")
        if left is None:
            return

        # Handle simple identifiers
        if left.type == "identifier":
            name = self.get_node_text(left, source)

            # Skip private/internal variables (optional, could be configurable)
            # For now, extract all module-level variables

            symbols.append({
                "name": name,
                "kind": "variable",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": name,
                "metadata": {},
            })

        # Handle tuple unpacking (a, b = 1, 2)
        elif left.type == "pattern_list" or left.type == "tuple_pattern":
            for child in left.children:
                if child.type == "identifier":
                    name = self.get_node_text(child, source)
                    symbols.append({
                        "name": name,
                        "kind": "variable",
                        "line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "start_column": child.start_point[1],
                        "end_column": child.end_point[1],
                        "qualified_name": name,
                        "metadata": {},
                    })

    def _extract_import(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract import statement (import x, import x.y, import x as y)."""
        for child in node.children:
            if child.type == "dotted_name":
                # import x.y.z
                module_name = self.get_node_text(child, source)
                symbols.append({
                    "name": module_name,
                    "kind": "import",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": module_name,
                    "metadata": {"import_type": "module"},
                })
            elif child.type == "aliased_import":
                # import x as y
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    module_name = self.get_node_text(name_node, source)
                    alias = (
                        self.get_node_text(alias_node, source)
                        if alias_node
                        else None
                    )
                    symbols.append({
                        "name": alias or module_name,
                        "kind": "import",
                        "line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "start_column": node.start_point[1],
                        "end_column": node.end_point[1],
                        "qualified_name": module_name,
                        "metadata": {
                            "import_type": "module",
                            "alias": alias,
                            "original_name": module_name,
                        },
                    })

    def _extract_import_from(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract from-import statement (from x import y, from x import y as z)."""
        # Get the module being imported from
        module_node = node.child_by_field_name("module_name")
        module_name = self.get_node_text(module_node, source) if module_node else ""

        # Find what's being imported
        for child in node.children:
            if child.type == "dotted_name" and child != module_node:
                # from x import y
                name = self.get_node_text(child, source)
                symbols.append({
                    "name": name,
                    "kind": "import",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": f"{module_name}.{name}" if module_name else name,
                    "metadata": {
                        "import_type": "from",
                        "module": module_name,
                    },
                })
            elif child.type == "aliased_import":
                # from x import y as z
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    name = self.get_node_text(name_node, source)
                    alias = (
                        self.get_node_text(alias_node, source)
                        if alias_node
                        else None
                    )
                    symbols.append({
                        "name": alias or name,
                        "kind": "import",
                        "line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "start_column": node.start_point[1],
                        "end_column": node.end_point[1],
                        "qualified_name": (
                            f"{module_name}.{name}" if module_name else name
                        ),
                        "metadata": {
                            "import_type": "from",
                            "module": module_name,
                            "alias": alias,
                            "original_name": name,
                        },
                    })
            elif child.type == "wildcard_import":
                # from x import *
                symbols.append({
                    "name": "*",
                    "kind": "import",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": f"{module_name}.*" if module_name else "*",
                    "metadata": {
                        "import_type": "wildcard",
                        "module": module_name,
                    },
                })

    def _extract_docstring(self, node: "Node", source: bytes) -> str | None:
        """Extract docstring from a function or class definition.

        Docstrings are the first statement in the body if it's an
        expression_statement containing a string.
        """
        body_node = node.child_by_field_name("body")
        if body_node is None:
            return None

        # Body should be a block
        if body_node.type != "block":
            return None

        # Find first non-comment child
        for child in body_node.children:
            if child.type == "expression_statement":
                # Check if it's a string literal
                if child.child_count > 0:
                    first = child.children[0]
                    if first.type == "string":
                        docstring = self.get_node_text(first, source)
                        # Strip quotes
                        return self._strip_string_quotes(docstring)
            # Stop at first non-expression statement
            elif child.type not in ("comment", "newline"):
                break

        return None

    def _strip_string_quotes(self, s: str) -> str:
        """Strip quotes from a string literal."""
        # Handle triple-quoted strings
        if s.startswith('"""') and s.endswith('"""'):
            return s[3:-3].strip()
        if s.startswith("'''") and s.endswith("'''"):
            return s[3:-3].strip()
        # Handle single-quoted strings
        if s.startswith('"') and s.endswith('"'):
            return s[1:-1].strip()
        if s.startswith("'") and s.endswith("'"):
            return s[1:-1].strip()
        return s

    def _extract_decorators(self, node: "Node", source: bytes) -> list[str]:
        """Extract decorator names from a function or class definition."""
        decorators = []

        # Look for decorator nodes before the definition
        # In tree-sitter-python, decorators are siblings before the def/class
        if node.parent is None:
            return decorators

        # Find all siblings that are decorators before this node
        # Actually, in tree-sitter-python, decorated definitions are wrapped
        # in a decorated_definition node, or decorators are direct children

        # Check if parent is decorated_definition
        parent = node.parent
        if parent and parent.type == "decorated_definition":
            for child in parent.children:
                if child.type == "decorator":
                    decorator_text = self.get_node_text(child, source)
                    # Remove the @ symbol
                    if decorator_text.startswith("@"):
                        decorator_text = decorator_text[1:]
                    decorators.append(decorator_text)

        return decorators

    def _extract_base_classes(self, node: "Node", source: bytes) -> list[str]:
        """Extract base class names from a class definition."""
        bases = []

        # Find argument_list (base classes)
        superclasses = node.child_by_field_name("superclasses")
        if superclasses is None:
            return bases

        for child in superclasses.children:
            if child.type == "identifier":
                bases.append(self.get_node_text(child, source))
            elif child.type == "attribute":
                # e.g., module.BaseClass
                bases.append(self.get_node_text(child, source))
            elif child.type == "keyword_argument":
                # e.g., metaclass=ABCMeta - skip these
                pass

        return bases

    def _is_async_function(self, node: "Node") -> bool:
        """Check if a function is async."""
        # In tree-sitter-python, async functions have 'async' as first child
        # or the parent might be an async statement
        if node.child_count > 0:
            first_child = node.children[0]
            if first_child.type == "async":
                return True

        # Check previous sibling
        if node.prev_sibling and node.prev_sibling.type == "async":
            return True

        return False

    def _build_import_map(
        self,
        symbols: list[dict],
        file_path: str | Path | None = None,
    ) -> dict[str, ImportEntry]:
        """Build a mapping of imported names to their resolved modules.

        This map enables resolution of module-qualified calls like `jira.add_worklog()`
        to their actual target symbols across files.

        Args:
            symbols: List of extracted symbols from the file.
            file_path: Path to the source file, used for relative import resolution.

        Returns:
            Dict mapping local names to ImportEntry objects.
        """
        import_map: dict[str, ImportEntry] = {}

        for symbol in symbols:
            if symbol["kind"] != "import":
                continue

            metadata = symbol.get("metadata", {})
            import_type = metadata.get("import_type", "module")
            local_name = symbol["name"]
            qualified_name = symbol.get("qualified_name", "")

            if import_type == "wildcard":
                # Wildcard imports can't be reliably resolved
                # Store them but mark as wildcard so we know resolution is best-effort
                module = metadata.get("module", "")
                resolved_module = self._resolve_relative_import(module, file_path)
                import_map[local_name] = ImportEntry(
                    local_name=local_name,
                    module=resolved_module,
                    symbol=None,
                    import_type="wildcard",
                )

            elif import_type == "from":
                # from x import y or from x import y as z
                module = metadata.get("module", "")
                resolved_module = self._resolve_relative_import(module, file_path)
                original_name = metadata.get("original_name", local_name)

                import_map[local_name] = ImportEntry(
                    local_name=local_name,
                    module=resolved_module,
                    symbol=original_name,
                    import_type="from",
                )

            else:
                # import x or import x as y
                # qualified_name is the full module path
                original_name = metadata.get("original_name", qualified_name)
                resolved_module = self._resolve_relative_import(
                    original_name, file_path
                )

                import_map[local_name] = ImportEntry(
                    local_name=local_name,
                    module=resolved_module,
                    symbol=None,
                    import_type="module",
                )

        return import_map

    def _resolve_relative_import(
        self,
        module_spec: str,
        file_path: str | Path | None,
    ) -> str:
        """Resolve a relative import to an absolute module path.

        Handles import patterns like:
        - `.sibling` -> resolves based on file_path's package
        - `..parent` -> resolves to parent package
        - `...grandparent.module` -> multiple levels up

        Args:
            module_spec: The module specification, possibly with leading dots.
            file_path: Path to the source file for context.

        Returns:
            Absolute module path, or the original spec if not relative or unresolvable.
        """
        if not module_spec or not module_spec.startswith("."):
            return module_spec

        if file_path is None:
            # Can't resolve relative imports without file path
            return module_spec

        file_path = Path(file_path)

        # Count leading dots to determine relative level
        dots = 0
        for char in module_spec:
            if char == ".":
                dots += 1
            else:
                break

        # Get the remaining module path after the dots
        remaining = module_spec[dots:]

        # Build package path from file path
        # e.g., /project/foundry/smith.py -> foundry (parent is package)
        parts = list(file_path.parts)

        # Remove filename, we want package path
        if parts:
            parts = parts[:-1]

        # Remove directories up based on dot count
        # `.` = same package (dots=1, go up 0 from parent)
        # `..` = parent package (dots=2, go up 1)
        # `...` = grandparent (dots=3, go up 2)
        levels_up = dots - 1
        if levels_up > 0 and len(parts) >= levels_up:
            parts = parts[:-levels_up]

        # Find the package root by looking for parts that look like packages
        # We assume package names don't have path separators
        # Try to find the deepest directory that could be a Python package
        package_parts: list[str] = []
        for part in reversed(parts):
            # Skip absolute path roots and common non-package dirs
            if part in ("", "/", "\\") or part.endswith(":"):
                break
            # Common project root markers
            if part in ("src", "lib", "packages"):
                break
            package_parts.insert(0, part)

        # Combine package path with remaining module
        if package_parts:
            if remaining:
                return ".".join(package_parts) + "." + remaining
            return ".".join(package_parts)
        elif remaining:
            return remaining
        else:
            return module_spec

    def extract_references(self, tree: "Tree", source: bytes, file_path: str | Path | None = None) -> list[dict]:
        """Extract symbol references from Python AST.

        Extracts:
        - Function calls (call expressions) with cross-file resolution hints
        - Import edges (which module imports what)
        - Class inheritance edges

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.
            file_path: Path to the source file, used for relative import resolution.

        Returns:
            List of reference dictionaries.
        """
        references: list[dict] = []

        # First pass: collect all symbols for context
        symbols = self.extract_symbols(tree, source)
        symbol_map = {s["qualified_name"]: s for s in symbols if s.get("qualified_name")}

        # Build import map for cross-file call resolution
        import_map = self._build_import_map(symbols, file_path)

        # Extract references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None, symbol_map=symbol_map,
            import_map=import_map
        )

        # Add inheritance edges with potential cross-file resolution hints
        for symbol in symbols:
            if symbol["kind"] == "class":
                bases = symbol.get("metadata", {}).get("bases", [])
                for base in bases:
                    ref = {
                        "source": symbol["qualified_name"],
                        "target": base,
                        "type": "inherits",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    }

                    # Check if base class reference can be resolved via imports
                    # Handle cases like: class Child(module.BaseClass)
                    if "." in base:
                        parts = base.split(".", 1)
                        obj_name, attr_name = parts[0], parts[1]
                        if obj_name in import_map:
                            entry = import_map[obj_name]
                            ref["target"] = attr_name
                            ref["metadata"] = {"target_module": entry.module}

                    references.append(ref)

        # Add import edges
        for symbol in symbols:
            if symbol["kind"] == "import":
                metadata = symbol.get("metadata", {})
                module = metadata.get("module", "")
                original_name = metadata.get("original_name", symbol["name"])

                if metadata.get("import_type") == "from":
                    # from x import y -> imports y from x
                    references.append({
                        "source": "<module>",  # Current module
                        "target": symbol["qualified_name"],
                        "type": "imports",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                        "metadata": {
                            "module": module,
                            "name": original_name,
                        },
                    })
                else:
                    # import x -> imports module x
                    references.append({
                        "source": "<module>",
                        "target": symbol["qualified_name"],
                        "type": "imports",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

        return references

    def _extract_references_recursive(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        symbol_map: dict,
        import_map: dict[str, ImportEntry] | None = None,
    ) -> None:
        """Recursively extract references from AST nodes.

        Args:
            node: Current AST node.
            source: Original source bytes.
            references: List to append references to.
            context: Current scope context (function/class name).
            symbol_map: Map of qualified names to symbols.
            import_map: Map of imported names to their resolved modules.
        """
        if import_map is None:
            import_map = {}

        # Track context for calls
        new_context = context

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.get_node_text(name_node, source)
                if context and context.get("qualified_name"):
                    qualified_name = f"{context['qualified_name']}.{name}"
                else:
                    qualified_name = name
                new_context = {
                    "type": "function",
                    "name": name,
                    "qualified_name": qualified_name,
                }

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.get_node_text(name_node, source)
                if context and context.get("qualified_name"):
                    qualified_name = f"{context['qualified_name']}.{name}"
                else:
                    qualified_name = name
                new_context = {
                    "type": "class",
                    "name": name,
                    "qualified_name": qualified_name,
                }

        elif node.type == "call":
            self._extract_call_reference(node, source, references, context, import_map)

        # Recurse into children
        for child in node.children:
            self._extract_references_recursive(
                child, source, references, new_context, symbol_map, import_map
            )

    def _extract_call_reference(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        import_map: dict[str, ImportEntry] | None = None,
    ) -> None:
        """Extract a function call reference with cross-file resolution hints.

        For attribute access patterns like `jira.add_worklog()`, this method:
        1. Splits the call into object and attribute parts
        2. Looks up the object in the import map
        3. If found, emits an edge with target_module metadata for cross-file resolution

        Args:
            node: The call AST node.
            source: Original source bytes.
            references: List to append references to.
            context: Current scope context (function/class name).
            import_map: Map of imported names to their resolved modules.
        """
        if import_map is None:
            import_map = {}

        # Get the function being called
        function_node = node.child_by_field_name("function")
        if function_node is None:
            return

        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the callee name and potentially resolve via import map
        metadata: dict = {}

        if function_node.type == "identifier":
            # Simple call: foo()
            callee = self.get_node_text(function_node, source)

            # Check if this is a directly imported symbol (from x import foo or from x import foo as bar)
            if callee in import_map:
                entry = import_map[callee]
                if entry.import_type == "from" and entry.symbol:
                    # Use the original symbol name (not alias) for better matching
                    callee = entry.symbol
                    metadata["target_module"] = entry.module

        elif function_node.type == "attribute":
            # Method/attribute call: obj.method() or module.function()
            full_callee = self.get_node_text(function_node, source)

            # Split into object and attribute
            # Handle nested attributes: a.b.c() -> obj="a.b", attr="c"
            if "." in full_callee:
                # Find the first part to check against imports
                parts = full_callee.split(".")
                first_part = parts[0]

                if first_part in import_map:
                    entry = import_map[first_part]

                    if entry.import_type == "module":
                        # import jira or import jira as j
                        # jira.add_worklog() -> target: add_worklog, module: jira
                        callee = ".".join(parts[1:])  # Everything after the import alias
                        # Build the full module path including nested attributes except the final call
                        if len(parts) > 2:
                            # a.b.c() where a is imported module
                            # target_module should be the submodule path
                            metadata["target_module"] = entry.module + "." + ".".join(parts[1:-1])
                        else:
                            metadata["target_module"] = entry.module

                    elif entry.import_type == "from" and entry.symbol:
                        # from foundry import jira; jira.add_worklog()
                        # This means jira is actually foundry.jira module
                        callee = ".".join(parts[1:])
                        metadata["target_module"] = entry.module + "." + entry.symbol

                    else:
                        # Unresolved or wildcard import - keep full name for fallback matching
                        callee = full_callee

                elif first_part == "self":
                    # self.method() - extract just the method name
                    # Same-class resolution will match by name or qualified_name
                    callee = ".".join(parts[1:])  # "self.process" -> "process"
                    metadata["same_class_call"] = True

                elif first_part == "cls":
                    # cls.method() - classmethod calling another classmethod
                    callee = ".".join(parts[1:])
                    metadata["same_class_call"] = True

                else:
                    # Unknown object (local variable, parameter, etc.)
                    # Keep the full qualified name for best-effort matching
                    callee = full_callee
            else:
                # No dot in attribute access (shouldn't happen for attribute type)
                callee = full_callee
        else:
            # Complex call expression, skip for now
            return

        ref = {
            "source": caller,
            "target": callee,
            "type": "calls",
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
        }

        if metadata:
            ref["metadata"] = metadata

        references.append(ref)
