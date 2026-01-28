"""Python parser using Tree-sitter for AST analysis."""

from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


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

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol references from Python AST.

        Extracts:
        - Function calls (call expressions)
        - Import edges (which module imports what)
        - Class inheritance edges

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.

        Returns:
            List of reference dictionaries.
        """
        references: list[dict] = []

        # First pass: collect all symbols for context
        symbols = self.extract_symbols(tree, source)
        symbol_map = {s["qualified_name"]: s for s in symbols if s.get("qualified_name")}

        # Extract references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None, symbol_map=symbol_map
        )

        # Add inheritance edges
        for symbol in symbols:
            if symbol["kind"] == "class":
                bases = symbol.get("metadata", {}).get("bases", [])
                for base in bases:
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": base,
                        "type": "inherits",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

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
    ) -> None:
        """Recursively extract references from AST nodes.

        Args:
            node: Current AST node.
            source: Original source bytes.
            references: List to append references to.
            context: Current scope context (function/class name).
            symbol_map: Map of qualified names to symbols.
        """
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
            self._extract_call_reference(node, source, references, context)

        # Recurse into children
        for child in node.children:
            self._extract_references_recursive(
                child, source, references, new_context, symbol_map
            )

    def _extract_call_reference(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
    ) -> None:
        """Extract a function call reference."""
        # Get the function being called
        function_node = node.child_by_field_name("function")
        if function_node is None:
            return

        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the callee name
        if function_node.type == "identifier":
            # Simple call: foo()
            callee = self.get_node_text(function_node, source)
        elif function_node.type == "attribute":
            # Method call: obj.method()
            callee = self.get_node_text(function_node, source)
        else:
            # Complex call expression, skip for now
            return

        references.append({
            "source": caller,
            "target": callee,
            "type": "calls",
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
        })
