"""Go parser using Tree-sitter for AST analysis."""

from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


class GoParser(BaseParser):
    """Parser for Go source code using tree-sitter-go.

    Extracts:
    - Nodes: packages, functions, methods, structs, interfaces, type aliases,
             constants, variables, imports
    - Edges: calls, imports, implements (struct implementing interface)
    """

    @property
    def language_name(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> list[str]:
        return [".go"]

    def _load_language(self) -> "Language":
        """Load the tree-sitter-go grammar."""
        from tree_sitter import Language
        import tree_sitter_go as tsgo

        return Language(tsgo.language())

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from Go AST.

        Extracts:
        - Package declarations
        - Function definitions
        - Method definitions (functions with receivers)
        - Struct definitions
        - Interface definitions
        - Type aliases
        - Constant declarations
        - Variable declarations
        - Import statements

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.

        Returns:
            List of symbol dictionaries.
        """
        symbols: list[dict] = []
        package_name: str | None = None

        # First pass: get package name
        for child in tree.root_node.children:
            if child.type == "package_clause":
                package_name = self._extract_package_name(child, source)
                break

        self._extract_symbols_recursive(
            tree.root_node, source, symbols, context=None, package=package_name
        )
        return symbols

    def _extract_symbols_recursive(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        package: str | None,
    ) -> None:
        """Recursively extract symbols from AST nodes.

        Args:
            node: Current AST node.
            source: Original source bytes.
            symbols: List to append symbols to.
            context: Parent context (struct/interface name) for qualified names.
            package: Current package name.
        """
        if node.type == "package_clause":
            self._extract_package(node, source, symbols)
        elif node.type == "import_declaration":
            self._extract_imports(node, source, symbols)
        elif node.type == "function_declaration":
            self._extract_function(node, source, symbols, context, package)
        elif node.type == "method_declaration":
            self._extract_method(node, source, symbols, context, package)
        elif node.type == "type_declaration":
            self._extract_type_declaration(node, source, symbols, context, package)
        elif node.type == "const_declaration":
            self._extract_const(node, source, symbols, package)
        elif node.type == "var_declaration":
            self._extract_var(node, source, symbols, package)
        else:
            # Recurse into children
            for child in node.children:
                self._extract_symbols_recursive(
                    child, source, symbols, context, package
                )

    def _extract_package_name(self, node: "Node", source: bytes) -> str | None:
        """Extract package name from package_clause node."""
        for child in node.children:
            if child.type == "package_identifier":
                return self.get_node_text(child, source)
        return None

    def _extract_package(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract package declaration."""
        name = self._extract_package_name(node, source)
        if name:
            symbols.append({
                "name": name,
                "kind": "package",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": name,
                "metadata": {},
            })

    def _extract_imports(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract import declarations."""
        # Handle both single imports and import blocks
        for child in node.children:
            if child.type == "import_spec":
                self._extract_import_spec(child, source, symbols)
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        self._extract_import_spec(spec, source, symbols)

    def _extract_import_spec(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract a single import spec."""
        alias = None
        path = None

        for child in node.children:
            if child.type == "package_identifier":
                # This is an alias
                alias = self.get_node_text(child, source)
            elif child.type == "interpreted_string_literal":
                # This is the import path
                path = self.get_node_text(child, source)
                # Strip quotes
                path = path.strip('"')
            elif child.type == "blank_identifier":
                # Import for side effects only: import _ "pkg"
                alias = "_"
            elif child.type == "dot":
                # Dot import: import . "pkg"
                alias = "."

        if path:
            # Get the package name from the path (last component)
            package_name = path.split("/")[-1] if "/" in path else path
            display_name = alias if alias and alias not in ("_", ".") else package_name

            symbols.append({
                "name": display_name,
                "kind": "import",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": path,
                "metadata": {
                    "import_type": "go",
                    "path": path,
                    "alias": alias,
                    "package_name": package_name,
                },
            })

    def _extract_function(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        package: str | None,
    ) -> None:
        """Extract function declaration."""
        name = self._get_function_name(node, source)
        if name is None:
            return

        # Build qualified name
        qualified_name = f"{package}.{name}" if package else name

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Extract return types
        returns = self._extract_return_types(node, source)

        # Build signature
        signature = self._build_function_signature(name, params, returns)

        # Check if exported (starts with uppercase)
        is_exported = name[0].isupper() if name else False

        # Extract doc comment
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
            "metadata": {
                "exported": is_exported,
            },
        }

        if returns:
            symbol["metadata"]["returns"] = returns

        symbols.append(symbol)

    def _extract_method(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        package: str | None,
    ) -> None:
        """Extract method declaration (function with receiver)."""
        name = self._get_function_name(node, source)
        if name is None:
            return

        # Extract receiver
        receiver = self._extract_receiver(node, source)

        # Build qualified name: package.ReceiverType.MethodName
        if receiver and receiver.get("type"):
            receiver_type = receiver["type"]
            if package:
                qualified_name = f"{package}.{receiver_type}.{name}"
            else:
                qualified_name = f"{receiver_type}.{name}"
        else:
            qualified_name = f"{package}.{name}" if package else name

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Extract return types
        returns = self._extract_return_types(node, source)

        # Build signature with receiver
        signature = self._build_method_signature(name, receiver, params, returns)

        # Check if exported
        is_exported = name[0].isupper() if name else False

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

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
            "metadata": {
                "exported": is_exported,
            },
        }

        if receiver:
            symbol["metadata"]["receiver"] = receiver
        if returns:
            symbol["metadata"]["returns"] = returns

        symbols.append(symbol)

    def _extract_type_declaration(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        package: str | None,
    ) -> None:
        """Extract type declarations (struct, interface, type alias)."""
        for child in node.children:
            if child.type == "type_spec":
                self._extract_type_spec(child, source, symbols, package)

    def _extract_type_spec(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        package: str | None,
    ) -> None:
        """Extract a single type specification."""
        name = None
        type_def = None

        # In Go AST, the first type_identifier is the name,
        # everything else is the underlying type definition
        found_name = False
        for child in node.children:
            if child.type == "type_identifier" and not found_name:
                name = self.get_node_text(child, source)
                found_name = True
            elif child.type in (
                "struct_type",
                "interface_type",
                "pointer_type",
                "slice_type",
                "array_type",
                "map_type",
                "channel_type",
                "function_type",
                "type_identifier",  # For type aliases like "type MyInt int"
                "qualified_type",
            ):
                type_def = child

        if name is None:
            return

        qualified_name = f"{package}.{name}" if package else name
        is_exported = name[0].isupper() if name else False

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        if type_def and type_def.type == "struct_type":
            # Struct definition
            fields = self._extract_struct_fields(type_def, source)
            symbol = {
                "name": name,
                "kind": "struct",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "docstring": docstring,
                "metadata": {
                    "exported": is_exported,
                    "fields": fields,
                },
            }
            symbols.append(symbol)

        elif type_def and type_def.type == "interface_type":
            # Interface definition
            methods, embeds = self._extract_interface_methods(type_def, source)
            symbol = {
                "name": name,
                "kind": "interface",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "docstring": docstring,
                "metadata": {
                    "exported": is_exported,
                    "methods": methods,
                },
            }
            if embeds:
                symbol["metadata"]["embeds"] = embeds
            symbols.append(symbol)

        else:
            # Type alias or other type definition
            underlying_type = self.get_node_text(type_def, source) if type_def else None
            symbol = {
                "name": name,
                "kind": "type",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "docstring": docstring,
                "metadata": {
                    "exported": is_exported,
                },
            }
            if underlying_type:
                symbol["metadata"]["underlying_type"] = underlying_type
            symbols.append(symbol)

    def _extract_struct_fields(
        self,
        node: "Node",
        source: bytes,
    ) -> list[dict]:
        """Extract fields from a struct type."""
        fields = []

        field_list = self._find_child_by_type(node, "field_declaration_list")
        if field_list is None:
            return fields

        for child in field_list.children:
            if child.type == "field_declaration":
                field_names = []
                field_type = None
                tag = None
                is_embedded = False

                for fc in child.children:
                    if fc.type == "field_identifier":
                        field_names.append(self.get_node_text(fc, source))
                    elif fc.type in (
                        "type_identifier",
                        "qualified_type",
                        "pointer_type",
                        "slice_type",
                        "array_type",
                        "map_type",
                        "struct_type",
                        "interface_type",
                        "channel_type",
                        "function_type",
                    ):
                        field_type = self.get_node_text(fc, source)
                        # Check for embedded field (no field name, just type)
                        if not field_names:
                            is_embedded = True
                            # Use type as field name for embedded fields
                            type_name = field_type.lstrip("*")  # Remove pointer
                            if "." in type_name:
                                type_name = type_name.split(".")[-1]
                            field_names.append(type_name)
                    elif fc.type == "raw_string_literal" or fc.type == "interpreted_string_literal":
                        tag = self.get_node_text(fc, source)

                for fname in field_names:
                    field_info = {
                        "name": fname,
                        "type": field_type,
                    }
                    if tag:
                        field_info["tag"] = tag
                    if is_embedded:
                        field_info["embedded"] = True
                    fields.append(field_info)

        return fields

    def _extract_interface_methods(
        self,
        node: "Node",
        source: bytes,
    ) -> tuple[list[dict], list[str]]:
        """Extract methods and embedded interfaces from an interface type."""
        methods = []
        embeds = []

        for child in node.children:
            # Interface methods can be method_spec or method_elem depending on grammar version
            if child.type in ("method_spec", "method_elem"):
                method_name = None
                params = []
                returns = []
                param_list_count = 0

                for mc in child.children:
                    if mc.type == "field_identifier":
                        method_name = self.get_node_text(mc, source)
                    elif mc.type == "parameter_list":
                        param_list_count += 1
                        if param_list_count == 1:
                            # First parameter_list is the method params
                            params = self._parse_parameter_list(mc, source)
                        else:
                            # Second parameter_list is the return types
                            returns = self._parse_return_list(mc, source)
                    elif mc.type in ("simple_type", "type_identifier", "pointer_type",
                                      "slice_type", "qualified_type"):
                        # Single return type (no parentheses)
                        returns = [self.get_node_text(mc, source)]

                if method_name:
                    methods.append({
                        "name": method_name,
                        "params": params,
                        "returns": returns,
                    })

            elif child.type == "type_identifier" or child.type == "qualified_type":
                # Embedded interface (direct child)
                embeds.append(self.get_node_text(child, source))

            # Handle type_elem for embedded interfaces in newer grammar
            elif child.type == "type_elem":
                for ec in child.children:
                    if ec.type in ("type_identifier", "qualified_type"):
                        embeds.append(self.get_node_text(ec, source))

            # Also handle struct_elem as fallback
            elif child.type == "struct_elem":
                for ec in child.children:
                    if ec.type in ("type_identifier", "qualified_type"):
                        embeds.append(self.get_node_text(ec, source))

        return methods, embeds

    def _extract_const(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        package: str | None,
    ) -> None:
        """Extract constant declarations."""
        for child in node.children:
            if child.type == "const_spec":
                self._extract_const_spec(child, source, symbols, package)

    def _extract_const_spec(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        package: str | None,
    ) -> None:
        """Extract a single const spec."""
        names = []
        const_type = None

        for child in node.children:
            if child.type == "identifier":
                names.append(self.get_node_text(child, source))
            elif child.type in ("type_identifier", "qualified_type"):
                const_type = self.get_node_text(child, source)

        for name in names:
            qualified_name = f"{package}.{name}" if package else name
            is_exported = name[0].isupper() if name else False

            symbol = {
                "name": name,
                "kind": "constant",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "metadata": {
                    "exported": is_exported,
                },
            }
            if const_type:
                symbol["metadata"]["type"] = const_type
            symbols.append(symbol)

    def _extract_var(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        package: str | None,
    ) -> None:
        """Extract variable declarations."""
        for child in node.children:
            if child.type == "var_spec":
                self._extract_var_spec(child, source, symbols, package)
            elif child.type == "var_spec_list":
                # Handle var block: var ( ... )
                for spec in child.children:
                    if spec.type == "var_spec":
                        self._extract_var_spec(spec, source, symbols, package)

    def _extract_var_spec(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        package: str | None,
    ) -> None:
        """Extract a single var spec."""
        names = []
        var_type = None

        for child in node.children:
            if child.type == "identifier":
                names.append(self.get_node_text(child, source))
            elif child.type in (
                "type_identifier",
                "qualified_type",
                "pointer_type",
                "slice_type",
                "array_type",
                "map_type",
            ):
                var_type = self.get_node_text(child, source)

        for name in names:
            qualified_name = f"{package}.{name}" if package else name
            is_exported = name[0].isupper() if name else False

            symbol = {
                "name": name,
                "kind": "variable",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "metadata": {
                    "exported": is_exported,
                },
            }
            if var_type:
                symbol["metadata"]["type"] = var_type
            symbols.append(symbol)

    def extract_references(
        self,
        tree: "Tree",
        source: bytes,
        file_path: Path | str | None = None,
    ) -> list[dict]:
        """Extract symbol references from Go AST.

        Extracts:
        - Function/method calls
        - Import edges
        - Type references (struct embedding, interface implementation hints)

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.
            file_path: Optional path to the source file (unused in Go parser).

        Returns:
            List of reference dictionaries.
        """
        references: list[dict] = []

        # First pass: collect all symbols for context
        symbols = self.extract_symbols(tree, source)
        symbol_map = {s["qualified_name"]: s for s in symbols if s.get("qualified_name")}

        # Build import map for resolving cross-package calls
        import_map = self._build_import_map(symbols)

        # Extract call references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None, symbol_map=symbol_map,
            import_map=import_map
        )

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
        """Build a mapping of import aliases to their full paths."""
        import_map: dict[str, str] = {}

        for symbol in symbols:
            if symbol["kind"] == "import":
                metadata = symbol.get("metadata", {})
                alias = metadata.get("alias")
                package_name = metadata.get("package_name", "")
                path = metadata.get("path", "")

                if alias and alias not in ("_", "."):
                    import_map[alias] = path
                elif package_name:
                    import_map[package_name] = path

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
        if node.type == "function_declaration":
            name = self._get_function_name(node, source)
            if name:
                new_context = {
                    "type": "function",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type == "method_declaration":
            name = self._get_function_name(node, source)
            receiver = self._extract_receiver(node, source)
            if name:
                if receiver and receiver.get("type"):
                    qualified_name = f"{receiver['type']}.{name}"
                else:
                    qualified_name = name
                new_context = {
                    "type": "method",
                    "name": name,
                    "qualified_name": qualified_name,
                    "receiver": receiver,
                }

        elif node.type == "call_expression":
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
        import_map: dict[str, str],
    ) -> None:
        """Extract a function/method call reference."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the function being called
        function_node = node.child_by_field_name("function")
        if function_node is None:
            # Try first child
            for child in node.children:
                if child.type in ("identifier", "selector_expression", "parenthesized_expression"):
                    function_node = child
                    break

        if function_node is None:
            return

        callee = None
        metadata: dict = {}

        if function_node.type == "identifier":
            # Simple function call: foo()
            callee = self.get_node_text(function_node, source)

        elif function_node.type == "selector_expression":
            # Method call or package function: pkg.Func() or obj.Method()
            full_text = self.get_node_text(function_node, source)

            # Split into parts
            if "." in full_text:
                parts = full_text.split(".")
                first_part = parts[0]
                rest = ".".join(parts[1:])

                # Check if first part is an imported package
                if first_part in import_map:
                    # This is a package.Function call
                    metadata["target_module"] = import_map[first_part]
                    callee = rest
                else:
                    # This is likely a method call on a variable
                    callee = full_text

            else:
                callee = full_text

        elif function_node.type == "parenthesized_expression":
            # Type assertion or conversion: (Type).Method()
            callee = self.get_node_text(function_node, source)

        else:
            # Complex expression, extract what we can
            callee = self.get_node_text(function_node, source)

        if callee:
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

    # ==================== Helper methods ====================

    def _get_function_name(self, node: "Node", source: bytes) -> str | None:
        """Get the function/method name from a declaration node."""
        for child in node.children:
            # Functions use "identifier", methods use "field_identifier"
            if child.type in ("identifier", "field_identifier"):
                return self.get_node_text(child, source)
        return None

    def _extract_receiver(self, node: "Node", source: bytes) -> dict | None:
        """Extract receiver information from a method declaration."""
        param_list = self._find_child_by_type(node, "parameter_list")
        if param_list is None:
            return None

        # The first parameter_list in a method_declaration is the receiver
        receiver_name = None
        receiver_type = None
        is_pointer = False

        for child in param_list.children:
            if child.type == "parameter_declaration":
                for pc in child.children:
                    if pc.type == "identifier":
                        receiver_name = self.get_node_text(pc, source)
                    elif pc.type == "pointer_type":
                        is_pointer = True
                        # Get the type inside the pointer
                        for ptc in pc.children:
                            if ptc.type == "type_identifier":
                                receiver_type = self.get_node_text(ptc, source)
                    elif pc.type == "type_identifier":
                        receiver_type = self.get_node_text(pc, source)

        if receiver_type:
            return {
                "name": receiver_name,
                "type": receiver_type,
                "pointer": is_pointer,
            }
        return None

    def _extract_parameters(self, node: "Node", source: bytes) -> list[str]:
        """Extract parameters from a function/method declaration."""
        params = []

        # Find all parameter_list nodes
        param_lists = [c for c in node.children if c.type == "parameter_list"]

        # For methods, the first parameter_list is the receiver
        # For functions, the first is the actual parameters
        # Skip receiver for methods by checking parent type
        start_idx = 0
        if node.type == "method_declaration" and len(param_lists) > 0:
            start_idx = 1

        for i, param_list in enumerate(param_lists):
            if i < start_idx:
                continue
            if i == start_idx:
                # This is the parameters list
                params = self._parse_parameter_list(param_list, source)
                break

        return params

    def _parse_parameter_list(self, node: "Node", source: bytes) -> list[str]:
        """Parse a parameter_list node into a list of parameter strings."""
        params = []

        for child in node.children:
            if child.type in ("parameter_declaration", "variadic_parameter_declaration"):
                param_text = self.get_node_text(child, source)
                params.append(param_text)

        return params

    def _extract_return_types(self, node: "Node", source: bytes) -> list[str]:
        """Extract return types from a function/method declaration."""
        returns = []

        # Find all parameter_list nodes
        param_lists = [c for c in node.children if c.type == "parameter_list"]

        # For methods, the receiver is first, params second, returns third
        # For functions, params first, returns second
        return_idx = 1 if node.type == "function_declaration" else 2

        for i, param_list in enumerate(param_lists):
            if i == return_idx:
                returns = self._parse_return_list(param_list, source)
                break

        # Also check for simple return type (single type without parentheses)
        if not returns:
            for child in node.children:
                if child.type in ("type_identifier", "qualified_type", "pointer_type",
                                  "slice_type", "array_type", "map_type"):
                    returns = [self.get_node_text(child, source)]
                    break

        return returns

    def _parse_return_list(self, node: "Node", source: bytes) -> list[str]:
        """Parse return types from a parameter_list node."""
        returns = []

        for child in node.children:
            if child.type == "parameter_declaration":
                # Named return values
                type_text = None
                for pc in child.children:
                    if pc.type in ("type_identifier", "qualified_type", "pointer_type",
                                   "slice_type", "array_type", "map_type"):
                        type_text = self.get_node_text(pc, source)
                if type_text:
                    returns.append(type_text)
            elif child.type in ("type_identifier", "qualified_type", "pointer_type",
                                "slice_type", "array_type", "map_type"):
                # Unnamed return values
                returns.append(self.get_node_text(child, source))

        return returns

    def _build_function_signature(
        self,
        name: str,
        params: list[str],
        returns: list[str],
    ) -> str:
        """Build a function signature string."""
        param_str = ", ".join(params)

        if not returns:
            return f"func {name}({param_str})"
        elif len(returns) == 1:
            return f"func {name}({param_str}) {returns[0]}"
        else:
            return f"func {name}({param_str}) ({', '.join(returns)})"

    def _build_method_signature(
        self,
        name: str,
        receiver: dict | None,
        params: list[str],
        returns: list[str],
    ) -> str:
        """Build a method signature string with receiver."""
        param_str = ", ".join(params)

        receiver_str = ""
        if receiver:
            recv_name = receiver.get("name", "")
            recv_type = receiver.get("type", "")
            if receiver.get("pointer"):
                receiver_str = f"({recv_name} *{recv_type})"
            else:
                receiver_str = f"({recv_name} {recv_type})"

        if not returns:
            return f"func {receiver_str} {name}({param_str})"
        elif len(returns) == 1:
            return f"func {receiver_str} {name}({param_str}) {returns[0]}"
        else:
            return f"func {receiver_str} {name}({param_str}) ({', '.join(returns)})"

    def _find_child_by_type(self, node: "Node", child_type: str) -> "Node | None":
        """Find a child node by type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _extract_doc_comment(self, node: "Node", source: bytes) -> str | None:
        """Extract documentation comment from a declaration.

        Go doc comments are // comments immediately preceding a declaration.
        """
        # Look for comment nodes that are siblings immediately before this node
        if node.prev_sibling is None:
            return None

        comments = []
        sibling = node.prev_sibling

        while sibling and sibling.type == "comment":
            comment_text = self.get_node_text(sibling, source)
            # Remove // prefix and strip
            if comment_text.startswith("//"):
                comment_text = comment_text[2:].strip()
            comments.insert(0, comment_text)
            sibling = sibling.prev_sibling

        if comments:
            return "\n".join(comments)
        return None
