"""C# parser using Tree-sitter for AST analysis."""

from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


class CSharpParser(BaseParser):
    """Parser for C# source code using tree-sitter-c-sharp.

    Extracts:
    - Nodes: namespaces, classes, structs, interfaces, records, enums,
             methods, constructors, properties, fields
    - Edges: calls, imports (using statements), inherits, implements
    """

    @property
    def language_name(self) -> str:
        return "csharp"

    @property
    def file_extensions(self) -> list[str]:
        return [".cs"]

    def _load_language(self) -> "Language":
        """Load the tree-sitter-c-sharp grammar."""
        from tree_sitter import Language
        import tree_sitter_c_sharp as tscsharp

        return Language(tscsharp.language())

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from C# AST.

        Extracts:
        - Namespace declarations
        - Class, struct, interface, record, enum definitions
        - Method declarations (including constructors)
        - Property declarations
        - Field declarations
        - Using directives (as imports)

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.

        Returns:
            List of symbol dictionaries.
        """
        symbols: list[dict] = []
        self._extract_symbols_recursive(
            tree.root_node, source, symbols, context=None, namespace=None
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
            context: Parent context (class/struct name, etc.) for qualified names.
            namespace: Current namespace.
        """
        if node.type == "using_directive":
            self._extract_using(node, source, symbols)
        elif node.type == "namespace_declaration":
            self._extract_namespace(node, source, symbols, context, namespace)
        elif node.type == "file_scoped_namespace_declaration":
            self._extract_file_scoped_namespace(node, source, symbols, context, namespace)
        elif node.type == "class_declaration":
            self._extract_class(node, source, symbols, context, namespace)
        elif node.type == "struct_declaration":
            self._extract_struct(node, source, symbols, context, namespace)
        elif node.type == "interface_declaration":
            self._extract_interface(node, source, symbols, context, namespace)
        elif node.type == "record_declaration":
            self._extract_record(node, source, symbols, context, namespace)
        elif node.type == "enum_declaration":
            self._extract_enum(node, source, symbols, context, namespace)
        elif node.type == "method_declaration":
            self._extract_method(node, source, symbols, context, namespace)
        elif node.type == "constructor_declaration":
            self._extract_constructor(node, source, symbols, context, namespace)
        elif node.type == "property_declaration":
            self._extract_property(node, source, symbols, context, namespace)
        elif node.type == "field_declaration":
            self._extract_field(node, source, symbols, context, namespace)
        else:
            # Recurse into children
            for child in node.children:
                self._extract_symbols_recursive(
                    child, source, symbols, context, namespace
                )

    def _extract_using(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract using directive."""
        # Find the namespace being imported
        for child in node.children:
            if child.type in ("identifier", "qualified_name"):
                name = self.get_node_text(child, source)
                symbols.append({
                    "name": name,
                    "kind": "import",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": name,
                    "metadata": {"import_type": "using"},
                })
                break

    def _extract_namespace(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        parent_namespace: str | None,
    ) -> None:
        """Extract namespace declaration."""
        # Get namespace name
        name = None
        for child in node.children:
            if child.type in ("identifier", "qualified_name"):
                name = self.get_node_text(child, source)
                break

        if name is None:
            return

        # Build full namespace path
        full_namespace = (
            f"{parent_namespace}.{name}" if parent_namespace else name
        )

        symbols.append({
            "name": name,
            "kind": "namespace",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": full_namespace,
            "metadata": {},
        })

        # Extract declarations inside namespace
        declaration_list = self._find_child_by_type(node, "declaration_list")
        if declaration_list:
            for child in declaration_list.children:
                self._extract_symbols_recursive(
                    child, source, symbols, context=None, namespace=full_namespace
                )

    def _extract_file_scoped_namespace(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        parent_namespace: str | None,
    ) -> None:
        """Extract file-scoped namespace declaration (C# 10+)."""
        # Get namespace name
        name = None
        for child in node.children:
            if child.type in ("identifier", "qualified_name"):
                name = self.get_node_text(child, source)
                break

        if name is None:
            return

        full_namespace = (
            f"{parent_namespace}.{name}" if parent_namespace else name
        )

        symbols.append({
            "name": name,
            "kind": "namespace",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": full_namespace,
            "metadata": {"file_scoped": True},
        })

        # File-scoped namespaces don't have a declaration_list - members are siblings
        # So we need to continue processing from the parent
        parent = node.parent
        if parent:
            # Find index of this node and process all following siblings
            found = False
            for child in parent.children:
                if found:
                    self._extract_symbols_recursive(
                        child, source, symbols, context=None, namespace=full_namespace
                    )
                elif child == node:
                    found = True

    def _extract_class(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract class declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        # Build qualified name
        qualified_name = self._build_qualified_name(name, context, namespace)

        # Extract modifiers
        modifiers = self._extract_modifiers(node, source)

        # Extract base classes and interfaces
        bases = self._extract_base_list(node, source)

        # Extract attributes
        attributes = self._extract_attributes(node, source)

        # Extract type parameters (generics)
        type_params = self._extract_type_parameters(node, source)

        symbol = {
            "name": name,
            "kind": "class",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if bases:
            symbol["metadata"]["bases"] = bases
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params
        if "partial" in modifiers:
            symbol["metadata"]["partial"] = True

        symbols.append(symbol)

        # Create context for extracting members
        class_context = {
            "type": "class",
            "name": name,
            "qualified_name": qualified_name,
        }

        # Extract members from declaration list
        declaration_list = self._find_child_by_type(node, "declaration_list")
        if declaration_list:
            for child in declaration_list.children:
                self._extract_symbols_recursive(
                    child, source, symbols, class_context, namespace
                )

    def _extract_struct(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract struct declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        qualified_name = self._build_qualified_name(name, context, namespace)
        modifiers = self._extract_modifiers(node, source)
        bases = self._extract_base_list(node, source)
        attributes = self._extract_attributes(node, source)
        type_params = self._extract_type_parameters(node, source)

        symbol = {
            "name": name,
            "kind": "struct",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if bases:
            symbol["metadata"]["bases"] = bases
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

        # Extract members
        struct_context = {
            "type": "struct",
            "name": name,
            "qualified_name": qualified_name,
        }

        declaration_list = self._find_child_by_type(node, "declaration_list")
        if declaration_list:
            for child in declaration_list.children:
                self._extract_symbols_recursive(
                    child, source, symbols, struct_context, namespace
                )

    def _extract_interface(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract interface declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        qualified_name = self._build_qualified_name(name, context, namespace)
        modifiers = self._extract_modifiers(node, source)
        bases = self._extract_base_list(node, source)
        attributes = self._extract_attributes(node, source)
        type_params = self._extract_type_parameters(node, source)

        symbol = {
            "name": name,
            "kind": "interface",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if bases:
            symbol["metadata"]["bases"] = bases
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

        # Extract members
        interface_context = {
            "type": "interface",
            "name": name,
            "qualified_name": qualified_name,
        }

        declaration_list = self._find_child_by_type(node, "declaration_list")
        if declaration_list:
            for child in declaration_list.children:
                self._extract_symbols_recursive(
                    child, source, symbols, interface_context, namespace
                )

    def _extract_record(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract record declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        qualified_name = self._build_qualified_name(name, context, namespace)
        modifiers = self._extract_modifiers(node, source)
        bases = self._extract_base_list(node, source)
        attributes = self._extract_attributes(node, source)
        type_params = self._extract_type_parameters(node, source)

        # Extract primary constructor parameters if present
        params = self._extract_parameters(node, source)

        symbol = {
            "name": name,
            "kind": "record",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if bases:
            symbol["metadata"]["bases"] = bases
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params
        if params:
            symbol["metadata"]["primary_constructor_params"] = params

        symbols.append(symbol)

        # Extract members if declaration_list exists
        record_context = {
            "type": "record",
            "name": name,
            "qualified_name": qualified_name,
        }

        declaration_list = self._find_child_by_type(node, "declaration_list")
        if declaration_list:
            for child in declaration_list.children:
                self._extract_symbols_recursive(
                    child, source, symbols, record_context, namespace
                )

    def _extract_enum(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract enum declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        qualified_name = self._build_qualified_name(name, context, namespace)
        modifiers = self._extract_modifiers(node, source)
        attributes = self._extract_attributes(node, source)

        # Extract enum members
        members = []
        member_list = self._find_child_by_type(node, "enum_member_declaration_list")
        if member_list:
            for child in member_list.children:
                if child.type == "enum_member_declaration":
                    member_name = self._get_identifier(child, source)
                    if member_name:
                        members.append(member_name)

        symbol = {
            "name": name,
            "kind": "enum",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if members:
            symbol["metadata"]["members"] = members

        symbols.append(symbol)

    def _extract_method(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract method declaration."""
        name = self._get_method_name(node, source)
        if name is None:
            return

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = self._build_qualified_name(name, None, namespace)

        modifiers = self._extract_modifiers(node, source)
        attributes = self._extract_attributes(node, source)
        type_params = self._extract_type_parameters(node, source)

        # Get return type
        return_type = self._get_return_type(node, source)

        # Get parameters
        params = self._extract_parameters(node, source)

        # Build signature
        signature = self._build_method_signature(name, return_type, params, modifiers)

        symbol = {
            "name": name,
            "kind": "method",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params
        if return_type:
            symbol["metadata"]["return_type"] = return_type
        if "async" in modifiers:
            symbol["metadata"]["async"] = True

        symbols.append(symbol)

    def _extract_constructor(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract constructor declaration."""
        name = self._get_identifier(node, source)
        if name is None:
            return

        # Constructor qualified name uses .ctor convention
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = self._build_qualified_name(name, None, namespace)

        modifiers = self._extract_modifiers(node, source)
        attributes = self._extract_attributes(node, source)
        params = self._extract_parameters(node, source)

        # Build signature
        param_str = ", ".join(params) if params else ""
        signature = f"{name}({param_str})"

        symbol = {
            "name": name,
            "kind": "constructor",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if attributes:
            symbol["metadata"]["attributes"] = attributes

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
        name = self._get_identifier(node, source)
        if name is None:
            return

        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = self._build_qualified_name(name, None, namespace)

        modifiers = self._extract_modifiers(node, source)
        attributes = self._extract_attributes(node, source)

        # Get property type
        prop_type = self._get_type(node, source)

        # Check accessors
        has_getter = False
        has_setter = False
        accessor_list = self._find_child_by_type(node, "accessor_list")
        if accessor_list:
            for child in accessor_list.children:
                if child.type == "accessor_declaration":
                    accessor_text = self.get_node_text(child, source)
                    if "get" in accessor_text:
                        has_getter = True
                    if "set" in accessor_text:
                        has_setter = True

        symbol = {
            "name": name,
            "kind": "property",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "metadata": {},
        }

        if modifiers:
            symbol["metadata"]["modifiers"] = modifiers
        if attributes:
            symbol["metadata"]["attributes"] = attributes
        if prop_type:
            symbol["metadata"]["type"] = prop_type
        symbol["metadata"]["has_getter"] = has_getter
        symbol["metadata"]["has_setter"] = has_setter

        symbols.append(symbol)

    def _extract_field(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        namespace: str | None,
    ) -> None:
        """Extract field declaration."""
        modifiers = self._extract_modifiers(node, source)
        attributes = self._extract_attributes(node, source)

        # Get field type
        field_type = self._get_type(node, source)

        # Find variable declaration to get field names
        var_decl = self._find_child_by_type(node, "variable_declaration")
        if var_decl is None:
            return

        # Extract each variable declarator (can have multiple: int a, b, c;)
        for child in var_decl.children:
            if child.type == "variable_declarator":
                name = self._get_identifier(child, source)
                if name is None:
                    continue

                if context and context.get("qualified_name"):
                    qualified_name = f"{context['qualified_name']}.{name}"
                else:
                    qualified_name = self._build_qualified_name(name, None, namespace)

                symbol = {
                    "name": name,
                    "kind": "field",
                    "line": child.start_point[0] + 1,
                    "end_line": child.end_point[0] + 1,
                    "start_column": child.start_point[1],
                    "end_column": child.end_point[1],
                    "qualified_name": qualified_name,
                    "metadata": {},
                }

                if modifiers:
                    symbol["metadata"]["modifiers"] = modifiers
                if attributes:
                    symbol["metadata"]["attributes"] = attributes
                if field_type:
                    symbol["metadata"]["type"] = field_type

                symbols.append(symbol)

    def extract_references(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol references from C# AST.

        Extracts:
        - Method/function calls (invocation expressions)
        - Import edges (using directives)
        - Inheritance/implementation edges

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

        # Extract call references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None, symbol_map=symbol_map
        )

        # Add inheritance/implementation edges
        for symbol in symbols:
            if symbol["kind"] in ("class", "struct", "interface", "record"):
                bases = symbol.get("metadata", {}).get("bases", [])
                for base in bases:
                    # Determine if this is inheritance or implementation
                    # Interface names typically start with I
                    edge_type = "implements" if base.startswith("I") else "inherits"
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": base,
                        "type": edge_type,
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
        """Recursively extract references from AST nodes."""
        new_context = context

        # Track context for calls
        if node.type in ("class_declaration", "struct_declaration",
                         "interface_declaration", "record_declaration"):
            name = self._get_identifier(node, source)
            if name:
                new_context = {
                    "type": node.type.replace("_declaration", ""),
                    "name": name,
                    "qualified_name": name,  # Simplified, actual qualified name handled elsewhere
                }

        elif node.type in ("method_declaration", "constructor_declaration"):
            name = self._get_identifier(node, source)
            if name:
                qualified_name = name
                if context and context.get("qualified_name"):
                    qualified_name = f"{context['qualified_name']}.{name}"
                new_context = {
                    "type": "method",
                    "name": name,
                    "qualified_name": qualified_name,
                }

        elif node.type == "invocation_expression":
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
        """Extract a method call reference from invocation_expression."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the callee - can be identifier or member_access_expression
        callee = None
        for child in node.children:
            if child.type == "identifier":
                # Simple call: SomeMethod()
                callee = self.get_node_text(child, source)
                break
            elif child.type == "member_access_expression":
                # Member access: obj.Method() or Type.StaticMethod()
                callee = self.get_node_text(child, source)
                break
            elif child.type == "generic_name":
                # Generic method: Method<T>()
                callee = self.get_node_text(child, source)
                break

        if callee:
            references.append({
                "source": caller,
                "target": callee,
                "type": "calls",
                "line": node.start_point[0] + 1,
                "column": node.start_point[1],
            })

    # ==================== Helper methods ====================

    def _get_identifier(self, node: "Node", source: bytes) -> str | None:
        """Get the identifier name from a declaration node."""
        for child in node.children:
            if child.type == "identifier":
                return self.get_node_text(child, source)
        return None

    def _get_method_name(self, node: "Node", source: bytes) -> str | None:
        """Get the method name from a method declaration.

        For method declarations, there can be multiple identifiers - the return type
        (if not generic) and the method name. The method name is always the identifier
        that appears right before the parameter_list.
        """
        # Find the parameter_list to determine where the method name is
        param_list_idx = -1
        for i, child in enumerate(node.children):
            if child.type == "parameter_list":
                param_list_idx = i
                break

        if param_list_idx == -1:
            # No parameter list found, fall back to first identifier
            return self._get_identifier(node, source)

        # The method name is the identifier immediately before the parameter_list
        # Work backwards from param_list_idx to find it
        for i in range(param_list_idx - 1, -1, -1):
            child = node.children[i]
            if child.type == "identifier":
                return self.get_node_text(child, source)

        return None

    def _find_child_by_type(self, node: "Node", child_type: str) -> "Node | None":
        """Find a child node by type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _build_qualified_name(
        self,
        name: str,
        context: dict | None,
        namespace: str | None,
    ) -> str:
        """Build a fully qualified name."""
        parts = []
        if namespace:
            parts.append(namespace)
        if context and context.get("qualified_name"):
            parts.append(context["qualified_name"])
        parts.append(name)

        # Deduplicate if namespace is already in context
        if len(parts) >= 2 and namespace and context:
            context_qn = context.get("qualified_name", "")
            if context_qn.startswith(namespace):
                parts = [context_qn, name]

        return ".".join(parts)

    def _extract_modifiers(self, node: "Node", source: bytes) -> list[str]:
        """Extract modifiers from a declaration."""
        modifiers = []
        for child in node.children:
            if child.type == "modifier":
                # The modifier node contains the actual modifier keyword
                modifier_text = self.get_node_text(child, source)
                modifiers.append(modifier_text)
        return modifiers

    def _extract_attributes(self, node: "Node", source: bytes) -> list[str]:
        """Extract attributes from a declaration."""
        attributes = []
        for child in node.children:
            if child.type == "attribute_list":
                # Extract each attribute in the list
                for attr_child in child.children:
                    if attr_child.type == "attribute":
                        attr_text = self.get_node_text(attr_child, source)
                        attributes.append(attr_text)
        return attributes

    def _extract_base_list(self, node: "Node", source: bytes) -> list[str]:
        """Extract base classes/interfaces from a declaration."""
        bases = []
        base_list = self._find_child_by_type(node, "base_list")
        if base_list:
            for child in base_list.children:
                if child.type in ("identifier", "qualified_name", "generic_name"):
                    bases.append(self.get_node_text(child, source))
        return bases

    def _extract_type_parameters(self, node: "Node", source: bytes) -> list[str]:
        """Extract type parameters from a generic declaration."""
        type_params = []
        type_param_list = self._find_child_by_type(node, "type_parameter_list")
        if type_param_list:
            for child in type_param_list.children:
                if child.type == "type_parameter":
                    type_params.append(self.get_node_text(child, source))
        return type_params

    def _extract_parameters(self, node: "Node", source: bytes) -> list[str]:
        """Extract parameters from a method/constructor declaration."""
        params = []
        param_list = self._find_child_by_type(node, "parameter_list")
        if param_list:
            for child in param_list.children:
                if child.type == "parameter":
                    params.append(self.get_node_text(child, source))
        return params

    def _get_return_type(self, node: "Node", source: bytes) -> str | None:
        """Get the return type from a method declaration."""
        for child in node.children:
            if child.type in (
                "predefined_type",
                "identifier",
                "qualified_name",
                "generic_name",
                "nullable_type",
                "array_type",
                "tuple_type",
            ):
                return self.get_node_text(child, source)
        return None

    def _get_type(self, node: "Node", source: bytes) -> str | None:
        """Get the type from a property or field declaration."""
        # Type can be predefined_type, identifier, generic_name, etc.
        for child in node.children:
            if child.type in (
                "predefined_type",
                "identifier",
                "qualified_name",
                "generic_name",
                "nullable_type",
                "array_type",
                "tuple_type",
            ):
                return self.get_node_text(child, source)

        # Also check in variable_declaration for fields
        var_decl = self._find_child_by_type(node, "variable_declaration")
        if var_decl:
            for child in var_decl.children:
                if child.type in (
                    "predefined_type",
                    "identifier",
                    "qualified_name",
                    "generic_name",
                    "nullable_type",
                    "array_type",
                ):
                    return self.get_node_text(child, source)

        return None

    def _build_method_signature(
        self,
        name: str,
        return_type: str | None,
        params: list[str],
        modifiers: list[str],
    ) -> str:
        """Build a method signature string."""
        parts = []

        if "async" in modifiers:
            parts.append("async")

        if return_type:
            parts.append(return_type)

        param_str = ", ".join(params) if params else ""
        parts.append(f"{name}({param_str})")

        return " ".join(parts)
