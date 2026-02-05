"""PHP parser using Tree-sitter for AST analysis with WordPress pattern support."""

from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


class PHPParser(BaseParser):
    """Parser for PHP source code using tree-sitter-php.

    Extracts:
    - Nodes: functions, classes, methods, traits, interfaces, constants,
             namespaces, use statements (imports)
    - Edges: calls, imports, inheritance, trait usage
    - WordPress patterns: hooks (add_action/add_filter), triggers (do_action/apply_filters),
                         shortcodes, AJAX handlers
    """

    # WordPress hook functions that register callbacks
    WP_HOOK_FUNCTIONS = {"add_action", "add_filter"}

    # WordPress functions that trigger hooks
    WP_TRIGGER_FUNCTIONS = {"do_action", "apply_filters", "do_action_ref_array", "apply_filters_ref_array"}

    # WordPress shortcode registration
    WP_SHORTCODE_FUNCTIONS = {"add_shortcode"}

    @property
    def language_name(self) -> str:
        return "php"

    @property
    def file_extensions(self) -> list[str]:
        return [".php", ".inc"]

    def _load_language(self) -> "Language":
        """Load the tree-sitter-php grammar."""
        from tree_sitter import Language
        import tree_sitter_php as tsphp

        # tree-sitter-php provides PHP language
        return Language(tsphp.language_php())

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from PHP AST.

        Extracts:
        - Function definitions
        - Class definitions
        - Method definitions
        - Trait definitions
        - Interface definitions
        - Constant definitions
        - Namespace declarations
        - Use statements (imports)

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.

        Returns:
            List of symbol dictionaries.
        """
        symbols: list[dict] = []
        namespace: str | None = None

        # First pass: find namespace
        for child in tree.root_node.children:
            if child.type == "namespace_definition":
                namespace = self._extract_namespace_name(child, source)
                break

        self._extract_symbols_recursive(
            tree.root_node, source, symbols, context=None, namespace=namespace
        )
        return symbols

    def _extract_symbols_recursive(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Recursively extract symbols from AST nodes.

        Args:
            node: Current AST node.
            source: Original source bytes.
            symbols: List to append symbols to.
            context: Parent context (class name) for qualified names.
            namespace: Current namespace.
        """
        if node.type == "namespace_definition":
            self._extract_namespace(node, source, symbols)
            # Update namespace for children
            namespace = self._extract_namespace_name(node, source)
            # Recurse into namespace body
            for child in node.children:
                if child.type == "compound_statement" or child.type == "declaration_list":
                    for subchild in child.children:
                        self._extract_symbols_recursive(
                            subchild, source, symbols, context, namespace
                        )
            return

        elif node.type == "namespace_use_declaration":
            self._extract_use_statement(node, source, symbols)

        elif node.type == "function_definition":
            self._extract_function(node, source, symbols, context, namespace)

        elif node.type == "class_declaration":
            self._extract_class(node, source, symbols, context, namespace)

        elif node.type == "trait_declaration":
            self._extract_trait(node, source, symbols, context, namespace)

        elif node.type == "interface_declaration":
            self._extract_interface(node, source, symbols, context, namespace)

        elif node.type == "const_declaration":
            self._extract_const(node, source, symbols, namespace)

        else:
            # Recurse into children
            for child in node.children:
                self._extract_symbols_recursive(child, source, symbols, context, namespace)

    def _extract_namespace_name(self, node: "Node", source: bytes) -> str | None:
        """Extract namespace name from namespace_definition node."""
        for child in node.children:
            if child.type == "namespace_name":
                return self.get_node_text(child, source)
        return None

    def _extract_namespace(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract namespace declaration."""
        name = self._extract_namespace_name(node, source)
        if name:
            symbols.append({
                "name": name,
                "kind": "namespace",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": name,
                "metadata": {},
            })

    def _extract_use_statement(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract use statement (import)."""
        for child in node.children:
            if child.type == "namespace_use_clause":
                self._extract_use_clause(child, source, symbols)
            elif child.type == "namespace_use_group":
                # Handle grouped use statements: use Foo\{Bar, Baz};
                self._extract_use_group(child, source, symbols)

    def _extract_use_clause(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract a single use clause."""
        qualified_name = None
        alias = None
        found_as = False

        for child in node.children:
            if child.type == "qualified_name" or child.type == "namespace_name":
                qualified_name = self.get_node_text(child, source)
            elif child.type == "namespace_aliasing_clause":
                # use Foo\Bar as Baz;
                for alias_child in child.children:
                    if alias_child.type == "name":
                        alias = self.get_node_text(alias_child, source)
            elif child.type == "as":
                found_as = True
            elif child.type == "name" and found_as:
                # Direct alias after 'as' keyword
                alias = self.get_node_text(child, source)

        if qualified_name:
            # Get the short name (last part of qualified name)
            short_name = qualified_name.split("\\")[-1] if "\\" in qualified_name else qualified_name
            display_name = alias if alias else short_name

            symbols.append({
                "name": display_name,
                "kind": "import",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "metadata": {
                    "import_type": "use",
                    "alias": alias,
                    "original_name": qualified_name,
                },
            })

    def _extract_use_group(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract grouped use statements."""
        prefix = None

        for child in node.children:
            if child.type == "namespace_name":
                prefix = self.get_node_text(child, source)
            elif child.type == "namespace_use_group_clause":
                for clause_child in child.children:
                    if clause_child.type == "namespace_use_clause":
                        # Build the full qualified name with prefix
                        name = None
                        alias = None

                        for c in clause_child.children:
                            if c.type == "namespace_name" or c.type == "name":
                                name = self.get_node_text(c, source)
                            elif c.type == "namespace_aliasing_clause":
                                for ac in c.children:
                                    if ac.type == "name":
                                        alias = self.get_node_text(ac, source)

                        if name:
                            qualified = f"{prefix}\\{name}" if prefix else name
                            short_name = name.split("\\")[-1] if "\\" in name else name
                            display_name = alias if alias else short_name

                            symbols.append({
                                "name": display_name,
                                "kind": "import",
                                "line": clause_child.start_point[0] + 1,
                                "end_line": clause_child.end_point[0] + 1,
                                "start_column": clause_child.start_point[1],
                                "end_column": clause_child.end_point[1],
                                "qualified_name": qualified,
                                "metadata": {
                                    "import_type": "use",
                                    "alias": alias,
                                    "original_name": qualified,
                                },
                            })

    def _extract_function(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract function definition."""
        name = self._get_function_name(node, source)
        if name is None:
            return

        # Build qualified name
        if namespace:
            qualified_name = f"{namespace}\\{name}"
        else:
            qualified_name = name

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Build signature
        signature = self._build_function_signature(name, params, node, source)

        # Extract docstring (PHPDoc comment)
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "function",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "docstring": docstring,
            "metadata": {},
        }

        symbols.append(symbol)

    def _extract_class(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract class definition and its members."""
        name = self._get_class_name(node, source)
        if name is None:
            return

        # Build qualified name
        if namespace:
            qualified_name = f"{namespace}\\{name}"
        else:
            qualified_name = name

        # Extract base class
        base_class = self._extract_base_class(node, source)

        # Extract implemented interfaces
        interfaces = self._extract_interfaces(node, source)

        # Extract traits used
        traits = self._extract_used_traits(node, source)

        # Extract docstring
        docstring = self._extract_doc_comment(node, source)

        # Check for modifiers (abstract, final)
        modifiers = self._extract_class_modifiers(node, source)

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

        if base_class:
            symbol["metadata"]["base_class"] = base_class
        if interfaces:
            symbol["metadata"]["interfaces"] = interfaces
        if traits:
            symbol["metadata"]["traits"] = traits
        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers

        symbols.append(symbol)

        # Create context for extracting methods
        class_context = {
            "type": "class",
            "name": name,
            "qualified_name": qualified_name,
        }

        # Extract members from class body
        body_node = self._find_child_by_type(node, "declaration_list")
        if body_node:
            for child in body_node.children:
                if child.type == "method_declaration":
                    self._extract_method(child, source, symbols, class_context, namespace)
                elif child.type == "property_declaration":
                    self._extract_property(child, source, symbols, class_context, namespace)
                elif child.type == "const_declaration":
                    self._extract_class_const(child, source, symbols, class_context, namespace)

    def _extract_trait(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract trait definition and its members."""
        name = self._get_class_name(node, source)
        if name is None:
            return

        # Build qualified name
        if namespace:
            qualified_name = f"{namespace}\\{name}"
        else:
            qualified_name = name

        # Extract docstring
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "trait",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        symbols.append(symbol)

        # Create context for extracting methods
        trait_context = {
            "type": "trait",
            "name": name,
            "qualified_name": qualified_name,
        }

        # Extract members from trait body
        body_node = self._find_child_by_type(node, "declaration_list")
        if body_node:
            for child in body_node.children:
                if child.type == "method_declaration":
                    self._extract_method(child, source, symbols, trait_context, namespace)
                elif child.type == "property_declaration":
                    self._extract_property(child, source, symbols, trait_context, namespace)

    def _extract_interface(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract interface definition."""
        name = self._get_class_name(node, source)
        if name is None:
            return

        # Build qualified name
        if namespace:
            qualified_name = f"{namespace}\\{name}"
        else:
            qualified_name = name

        # Extract extended interfaces
        extends = self._extract_interface_extends(node, source)

        # Extract docstring
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "interface",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        if extends:
            symbol["metadata"]["extends"] = extends

        symbols.append(symbol)

        # Create context for extracting method signatures
        interface_context = {
            "type": "interface",
            "name": name,
            "qualified_name": qualified_name,
        }

        # Extract method signatures from interface body
        body_node = self._find_child_by_type(node, "declaration_list")
        if body_node:
            for child in body_node.children:
                if child.type == "method_declaration":
                    self._extract_method(child, source, symbols, interface_context, namespace)
                elif child.type == "const_declaration":
                    self._extract_class_const(child, source, symbols, interface_context, namespace)

    def _extract_method(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract method definition."""
        name = self._get_function_name(node, source)
        if name is None:
            return

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}::{name}"
        elif namespace:
            qualified_name = f"{namespace}\\{name}"
        else:
            qualified_name = name

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Build signature
        signature = self._build_function_signature(name, params, node, source)

        # Extract docstring
        docstring = self._extract_doc_comment(node, source)

        # Extract visibility and modifiers
        visibility, modifiers = self._extract_method_modifiers(node, source)

        symbol = {
            "name": name,
            "kind": "method",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "docstring": docstring,
            "metadata": {},
        }

        if visibility:
            symbol["metadata"]["visibility"] = visibility
        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers

        symbols.append(symbol)

    def _extract_property(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract property declaration."""
        # Extract visibility and modifiers
        visibility, modifiers = self._extract_property_modifiers(node, source)

        # Extract property type
        prop_type = self._extract_property_type(node, source)

        # Extract property names (could be multiple)
        for child in node.children:
            if child.type == "property_element":
                name = None
                for prop_child in child.children:
                    if prop_child.type == "variable_name":
                        name = self.get_node_text(prop_child, source)
                        # Remove leading $
                        if name.startswith("$"):
                            name = name[1:]

                if name:
                    # Build qualified name
                    if context and context.get("qualified_name"):
                        qualified_name = f"{context['qualified_name']}::${name}"
                    else:
                        qualified_name = f"${name}"

                    symbol = {
                        "name": name,
                        "kind": "property",
                        "line": child.start_point[0] + 1,
                        "end_line": child.end_point[0] + 1,
                        "start_column": child.start_point[1],
                        "end_column": child.end_point[1],
                        "qualified_name": qualified_name,
                        "metadata": {},
                    }

                    if visibility:
                        symbol["metadata"]["visibility"] = visibility
                    if modifiers:
                        symbol["metadata"]["modifiers"] = modifiers
                    if prop_type:
                        symbol["metadata"]["type"] = prop_type

                    symbols.append(symbol)

    def _extract_const(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        namespace: str | None,
    ) -> None:
        """Extract constant declaration (not in class)."""
        for child in node.children:
            if child.type == "const_element":
                name = None
                for const_child in child.children:
                    if const_child.type == "name":
                        name = self.get_node_text(const_child, source)

                if name:
                    # Build qualified name
                    if namespace:
                        qualified_name = f"{namespace}\\{name}"
                    else:
                        qualified_name = name

                    symbols.append({
                        "name": name,
                        "kind": "constant",
                        "line": child.start_point[0] + 1,
                        "end_line": child.end_point[0] + 1,
                        "start_column": child.start_point[1],
                        "end_column": child.end_point[1],
                        "qualified_name": qualified_name,
                        "metadata": {},
                    })

    def _extract_class_const(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract class constant declaration."""
        # Extract visibility
        visibility = None
        for child in node.children:
            if child.type == "visibility_modifier":
                visibility = self.get_node_text(child, source)

        for child in node.children:
            if child.type == "const_element":
                name = None
                for const_child in child.children:
                    if const_child.type == "name":
                        name = self.get_node_text(const_child, source)

                if name:
                    # Build qualified name
                    if context and context.get("qualified_name"):
                        qualified_name = f"{context['qualified_name']}::{name}"
                    elif namespace:
                        qualified_name = f"{namespace}\\{name}"
                    else:
                        qualified_name = name

                    symbol = {
                        "name": name,
                        "kind": "constant",
                        "line": child.start_point[0] + 1,
                        "end_line": child.end_point[0] + 1,
                        "start_column": child.start_point[1],
                        "end_column": child.end_point[1],
                        "qualified_name": qualified_name,
                        "metadata": {},
                    }

                    if visibility:
                        symbol["metadata"]["visibility"] = visibility

                    symbols.append(symbol)

    def extract_references(
        self,
        tree: "Tree",
        source: bytes,
        file_path: Path | str | None = None,
    ) -> list[dict]:
        """Extract symbol references from PHP AST.

        Extracts:
        - Function/method calls
        - Import (use) edges
        - Inheritance edges
        - Trait usage edges
        - WordPress hook patterns

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.
            file_path: Optional path to the source file.

        Returns:
            List of reference dictionaries.
        """
        references: list[dict] = []

        # First pass: collect all symbols for context
        symbols = self.extract_symbols(tree, source)
        symbol_map = {s["qualified_name"]: s for s in symbols if s.get("qualified_name")}

        # Build import map for resolving namespaced calls
        import_map = self._build_import_map(symbols)

        # Extract call references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None, symbol_map=symbol_map,
            import_map=import_map
        )

        # Add inheritance edges
        for symbol in symbols:
            if symbol["kind"] == "class":
                base_class = symbol.get("metadata", {}).get("base_class")
                if base_class:
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": base_class,
                        "type": "inherits",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

                interfaces = symbol.get("metadata", {}).get("interfaces", [])
                for interface in interfaces:
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": interface,
                        "type": "implements",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

                traits = symbol.get("metadata", {}).get("traits", [])
                for trait in traits:
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": trait,
                        "type": "uses_trait",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

            elif symbol["kind"] == "interface":
                extends = symbol.get("metadata", {}).get("extends", [])
                for ext in extends:
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": ext,
                        "type": "extends",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

        # Add import edges
        for symbol in symbols:
            if symbol["kind"] == "import":
                references.append({
                    "source": "<module>",
                    "target": symbol["qualified_name"],
                    "type": "imports",
                    "line": symbol["line"],
                    "column": symbol["start_column"],
                    "metadata": symbol.get("metadata", {}),
                })

        return references

    def _build_import_map(self, symbols: list[dict]) -> dict[str, str]:
        """Build a mapping of imported names to their full qualified names."""
        import_map: dict[str, str] = {}

        for symbol in symbols:
            if symbol["kind"] == "import":
                # Map short name to full qualified name
                import_map[symbol["name"]] = symbol["qualified_name"]

        return import_map

    def _extract_references_recursive(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        symbol_map: dict,
        import_map: dict[str, str],
    ) -> None:
        """Recursively extract references from AST nodes."""
        new_context = context

        # Track context for calls
        if node.type == "function_definition":
            name = self._get_function_name(node, source)
            if name:
                new_context = {
                    "type": "function",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type == "method_declaration":
            name = self._get_function_name(node, source)
            if name and context and context.get("qualified_name"):
                qualified_name = f"{context['qualified_name']}::{name}"
                new_context = {
                    "type": "method",
                    "name": name,
                    "qualified_name": qualified_name,
                }

        elif node.type == "class_declaration":
            name = self._get_class_name(node, source)
            if name:
                new_context = {
                    "type": "class",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type == "trait_declaration":
            name = self._get_class_name(node, source)
            if name:
                new_context = {
                    "type": "trait",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type == "function_call_expression":
            self._extract_call_reference(node, source, references, context, import_map)

        elif node.type == "member_call_expression":
            self._extract_method_call_reference(node, source, references, context, import_map)

        elif node.type == "scoped_call_expression":
            self._extract_static_call_reference(node, source, references, context, import_map)

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
        import_map: dict[str, str],
    ) -> None:
        """Extract a function call reference, including WordPress hooks."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the function being called
        function_node = node.child_by_field_name("function")
        if function_node is None:
            # Try to find by type
            for child in node.children:
                if child.type in ("name", "qualified_name"):
                    function_node = child
                    break

        if function_node is None:
            return

        callee = self.get_node_text(function_node, source)
        metadata: dict = {}

        # Check for WordPress patterns
        if callee in self.WP_HOOK_FUNCTIONS:
            self._extract_wp_hook_registration(node, source, references, caller, callee)
            return

        if callee in self.WP_TRIGGER_FUNCTIONS:
            self._extract_wp_hook_trigger(node, source, references, caller, callee)
            return

        if callee in self.WP_SHORTCODE_FUNCTIONS:
            self._extract_wp_shortcode_registration(node, source, references, caller)
            return

        # Regular function call
        # Check if it's a namespaced call
        if "\\" in callee:
            # Full qualified name
            metadata["qualified"] = True
        elif callee in import_map:
            # Resolve via use statement
            metadata["target_module"] = import_map[callee]

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

    def _extract_method_call_reference(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        import_map: dict[str, str],
    ) -> None:
        """Extract method call reference (->method())."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the object being called on
        object_node = node.child_by_field_name("object")
        method_node = node.child_by_field_name("name")

        if method_node is None:
            return

        method_name = self.get_node_text(method_node, source)
        metadata: dict = {}

        if object_node:
            object_text = self.get_node_text(object_node, source)
            if object_text == "$this":
                metadata["same_class_call"] = True
            else:
                metadata["object"] = object_text

        ref = {
            "source": caller,
            "target": method_name,
            "type": "calls",
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
            "metadata": metadata,
        }
        references.append(ref)

    def _extract_static_call_reference(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        import_map: dict[str, str],
    ) -> None:
        """Extract static method call reference (::method())."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the class and method
        scope_node = node.child_by_field_name("scope")
        method_node = node.child_by_field_name("name")

        if method_node is None:
            return

        method_name = self.get_node_text(method_node, source)
        metadata: dict = {}

        if scope_node:
            scope_text = self.get_node_text(scope_node, source)
            if scope_text in ("self", "static", "parent"):
                metadata["same_class_call"] = True
                metadata["scope"] = scope_text
            else:
                # Build qualified target
                if scope_text in import_map:
                    target = f"{import_map[scope_text]}::{method_name}"
                else:
                    target = f"{scope_text}::{method_name}"
                ref = {
                    "source": caller,
                    "target": target,
                    "type": "calls",
                    "line": node.start_point[0] + 1,
                    "column": node.start_point[1],
                    "metadata": {"static": True},
                }
                references.append(ref)
                return

        ref = {
            "source": caller,
            "target": method_name,
            "type": "calls",
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
            "metadata": metadata,
        }
        references.append(ref)

    def _extract_wp_hook_registration(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        caller: str,
        function_name: str,
    ) -> None:
        """Extract WordPress hook registration (add_action/add_filter).

        Pattern: add_action('hook_name', 'callback_function')
        Pattern: add_action('hook_name', array($this, 'method_name'))
        Pattern: add_action('hook_name', [$this, 'method_name'])
        """
        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return

        args = self._extract_arguments(args_node, source)
        if len(args) < 2:
            return

        hook_name = args[0].strip("'\"")
        callback = args[1]

        # Determine edge type based on function
        edge_type = "registers_action" if function_name == "add_action" else "registers_filter"

        # Check for AJAX handlers (check nopriv first since it also starts with wp_ajax_)
        ajax_metadata = {}
        if hook_name.startswith("wp_ajax_nopriv_"):
            ajax_action = hook_name[15:]  # Remove 'wp_ajax_nopriv_' prefix
            ajax_metadata["ajax_action"] = ajax_action
            ajax_metadata["authenticated_only"] = False
        elif hook_name.startswith("wp_ajax_"):
            ajax_action = hook_name[8:]  # Remove 'wp_ajax_' prefix
            ajax_metadata["ajax_action"] = ajax_action
            ajax_metadata["authenticated_only"] = True

        # Parse callback - could be string, array, or closure
        callback_name = self._parse_wp_callback(callback)

        if callback_name:
            ref = {
                "source": callback_name,
                "target": hook_name,
                "type": edge_type,
                "line": node.start_point[0] + 1,
                "column": node.start_point[1],
                "metadata": {
                    "wordpress_hook": True,
                    "hook_type": "action" if function_name == "add_action" else "filter",
                    **ajax_metadata,
                },
            }
            references.append(ref)

    def _extract_wp_hook_trigger(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        caller: str,
        function_name: str,
    ) -> None:
        """Extract WordPress hook trigger (do_action/apply_filters).

        Pattern: do_action('hook_name', ...)
        Pattern: apply_filters('filter_name', $value, ...)
        """
        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return

        args = self._extract_arguments(args_node, source)
        if len(args) < 1:
            return

        hook_name = args[0].strip("'\"")

        # Determine edge type based on function
        edge_type = "triggers_action" if "action" in function_name else "triggers_filter"

        ref = {
            "source": caller,
            "target": hook_name,
            "type": edge_type,
            "line": node.start_point[0] + 1,
            "column": node.start_point[1],
            "metadata": {
                "wordpress_hook": True,
                "hook_type": "action" if "action" in function_name else "filter",
            },
        }
        references.append(ref)

    def _extract_wp_shortcode_registration(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        caller: str,
    ) -> None:
        """Extract WordPress shortcode registration.

        Pattern: add_shortcode('tag', 'callback_function')
        """
        args_node = node.child_by_field_name("arguments")
        if args_node is None:
            return

        args = self._extract_arguments(args_node, source)
        if len(args) < 2:
            return

        shortcode_tag = args[0].strip("'\"")
        callback = args[1]

        callback_name = self._parse_wp_callback(callback)

        if callback_name:
            ref = {
                "source": callback_name,
                "target": f"[{shortcode_tag}]",
                "type": "registers_shortcode",
                "line": node.start_point[0] + 1,
                "column": node.start_point[1],
                "metadata": {
                    "wordpress_shortcode": True,
                    "shortcode_tag": shortcode_tag,
                },
            }
            references.append(ref)

    def _extract_arguments(self, args_node: "Node", source: bytes) -> list[str]:
        """Extract argument values from an argument list node."""
        args: list[str] = []

        for child in args_node.children:
            if child.type == "argument":
                # Get the value of the argument
                for arg_child in child.children:
                    if arg_child.type not in (",", "(", ")"):
                        args.append(self.get_node_text(arg_child, source))
                        break
            elif child.type not in (",", "(", ")"):
                # Direct value (no argument wrapper)
                args.append(self.get_node_text(child, source))

        return args

    def _parse_wp_callback(self, callback_str: str) -> str | None:
        """Parse a WordPress callback specification.

        Handles:
        - String function name: 'my_function'
        - Array callback: array($this, 'method') or [$this, 'method']
        - Static callback: array('ClassName', 'method') or ['ClassName', 'method']
        """
        callback_str = callback_str.strip()

        # Simple string callback
        if callback_str.startswith("'") or callback_str.startswith('"'):
            return callback_str.strip("'\"")

        # Array callback - array($this, 'method') or [$this, 'method']
        if callback_str.startswith("array(") or callback_str.startswith("["):
            # Extract the method name from the callback array
            # Remove array wrapper
            inner = callback_str
            if inner.startswith("array("):
                inner = inner[6:]
                if inner.endswith(")"):
                    inner = inner[:-1]
            elif inner.startswith("["):
                inner = inner[1:]
                if inner.endswith("]"):
                    inner = inner[:-1]

            # Split by comma (handling potential nested content)
            if "," in inner:
                parts = inner.split(",", 1)
                if len(parts) >= 2:
                    method = parts[1].strip().strip("'\"")
                    return method

        return None

    # ==================== Helper methods ====================

    def _get_function_name(self, node: "Node", source: bytes) -> str | None:
        """Get the function/method name from a declaration node."""
        for child in node.children:
            if child.type == "name":
                return self.get_node_text(child, source)
        return None

    def _get_class_name(self, node: "Node", source: bytes) -> str | None:
        """Get the class/trait/interface name from a declaration node."""
        for child in node.children:
            if child.type == "name":
                return self.get_node_text(child, source)
        return None

    def _extract_parameters(self, node: "Node", source: bytes) -> list[str]:
        """Extract parameters from a function/method declaration."""
        params = []

        params_node = self._find_child_by_type(node, "formal_parameters")
        if params_node is None:
            return params

        for child in params_node.children:
            if child.type == "simple_parameter" or child.type == "variadic_parameter":
                param_text = self.get_node_text(child, source)
                params.append(param_text)

        return params

    def _build_function_signature(
        self,
        name: str,
        params: list[str],
        node: "Node",
        source: bytes,
    ) -> str:
        """Build a function signature string."""
        param_str = ", ".join(params)

        # Check for return type
        return_type_node = node.child_by_field_name("return_type")
        if return_type_node:
            return_type = self.get_node_text(return_type_node, source)
            return f"function {name}({param_str}): {return_type}"

        return f"function {name}({param_str})"

    def _extract_doc_comment(self, node: "Node", source: bytes) -> str | None:
        """Extract PHPDoc comment from a declaration."""
        # Look for comment node that is sibling before this node
        if node.prev_sibling is None:
            return None

        sibling = node.prev_sibling
        if sibling.type == "comment":
            comment_text = self.get_node_text(sibling, source)
            # Check if it's a PHPDoc comment (starts with /**)
            if comment_text.startswith("/**"):
                # Strip /** and */
                comment_text = comment_text[3:]
                if comment_text.endswith("*/"):
                    comment_text = comment_text[:-2]
                # Clean up line-by-line
                lines = []
                for line in comment_text.split("\n"):
                    line = line.strip()
                    if line.startswith("*"):
                        line = line[1:].strip()
                    if line:
                        lines.append(line)
                return "\n".join(lines) if lines else None
        return None

    def _extract_base_class(self, node: "Node", source: bytes) -> str | None:
        """Extract base class from class declaration."""
        for child in node.children:
            if child.type == "base_clause":
                for base_child in child.children:
                    if base_child.type in ("name", "qualified_name"):
                        return self.get_node_text(base_child, source)
        return None

    def _extract_interfaces(self, node: "Node", source: bytes) -> list[str]:
        """Extract implemented interfaces from class declaration."""
        interfaces = []

        for child in node.children:
            if child.type == "class_interface_clause":
                for iface_child in child.children:
                    if iface_child.type in ("name", "qualified_name"):
                        interfaces.append(self.get_node_text(iface_child, source))
                    elif iface_child.type == "name_list":
                        for name_child in iface_child.children:
                            if name_child.type in ("name", "qualified_name"):
                                interfaces.append(self.get_node_text(name_child, source))

        return interfaces

    def _extract_used_traits(self, node: "Node", source: bytes) -> list[str]:
        """Extract used traits from class/trait declaration."""
        traits = []

        body_node = self._find_child_by_type(node, "declaration_list")
        if body_node:
            for child in body_node.children:
                if child.type == "use_declaration":
                    for use_child in child.children:
                        if use_child.type in ("name", "qualified_name"):
                            traits.append(self.get_node_text(use_child, source))
                        elif use_child.type == "name_list":
                            for name_child in use_child.children:
                                if name_child.type in ("name", "qualified_name"):
                                    traits.append(self.get_node_text(name_child, source))

        return traits

    def _extract_interface_extends(self, node: "Node", source: bytes) -> list[str]:
        """Extract extended interfaces from interface declaration."""
        extends = []

        for child in node.children:
            if child.type == "base_clause":
                for base_child in child.children:
                    if base_child.type in ("name", "qualified_name"):
                        extends.append(self.get_node_text(base_child, source))
                    elif base_child.type == "name_list":
                        for name_child in base_child.children:
                            if name_child.type in ("name", "qualified_name"):
                                extends.append(self.get_node_text(name_child, source))

        return extends

    def _extract_class_modifiers(self, node: "Node", source: bytes) -> list[str]:
        """Extract class modifiers (abstract, final)."""
        modifiers = []

        for child in node.children:
            if child.type == "abstract_modifier":
                modifiers.append("abstract")
            elif child.type == "final_modifier":
                modifiers.append("final")
            elif child.type == "readonly_modifier":
                modifiers.append("readonly")

        return modifiers

    def _extract_method_modifiers(self, node: "Node", source: bytes) -> tuple[str | None, list[str]]:
        """Extract method visibility and modifiers."""
        visibility = None
        modifiers = []

        for child in node.children:
            if child.type == "visibility_modifier":
                visibility = self.get_node_text(child, source)
            elif child.type == "static_modifier":
                modifiers.append("static")
            elif child.type == "abstract_modifier":
                modifiers.append("abstract")
            elif child.type == "final_modifier":
                modifiers.append("final")

        return visibility, modifiers

    def _extract_property_modifiers(self, node: "Node", source: bytes) -> tuple[str | None, list[str]]:
        """Extract property visibility and modifiers."""
        visibility = None
        modifiers = []

        for child in node.children:
            if child.type == "visibility_modifier":
                visibility = self.get_node_text(child, source)
            elif child.type == "static_modifier":
                modifiers.append("static")
            elif child.type == "readonly_modifier":
                modifiers.append("readonly")

        return visibility, modifiers

    def _extract_property_type(self, node: "Node", source: bytes) -> str | None:
        """Extract property type declaration."""
        for child in node.children:
            if child.type in ("type_list", "named_type", "optional_type", "union_type",
                              "primitive_type", "qualified_name"):
                return self.get_node_text(child, source)
        return None

    def _find_child_by_type(self, node: "Node", child_type: str) -> "Node | None":
        """Find a child node by type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None
