"""TypeScript/JavaScript parser using Tree-sitter for AST analysis."""

from pathlib import Path
from typing import TYPE_CHECKING

from code_intel.parser.base import BaseParser

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Tree


class TypeScriptParser(BaseParser):
    """Parser for TypeScript and JavaScript source code using tree-sitter-typescript.

    Extracts:
    - Nodes: functions (declarations, expressions, arrows), classes, methods,
             interfaces, type aliases, enums, variables/constants, imports/exports
    - Edges: calls, imports, inheritance (extends), implementation (implements)

    Supports:
    - TypeScript (.ts, .tsx)
    - JavaScript (.js, .jsx, .mjs, .cjs)
    - ES Modules (import/export)
    - CommonJS (require, module.exports)
    """

    @property
    def language_name(self) -> str:
        return "typescript"

    @property
    def file_extensions(self) -> list[str]:
        return [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

    def _load_language(self) -> "Language":
        """Load the tree-sitter-typescript grammar."""
        from tree_sitter import Language
        import tree_sitter_typescript as tsts

        return Language(tsts.language_typescript())

    def extract_symbols(self, tree: "Tree", source: bytes) -> list[dict]:
        """Extract symbol definitions from TypeScript/JavaScript AST.

        Extracts:
        - Function declarations
        - Arrow functions assigned to variables
        - Function expressions assigned to variables
        - Class declarations
        - Method definitions
        - Interface declarations
        - Type alias declarations
        - Enum declarations
        - Import statements (ES modules and CommonJS)
        - Export statements
        - Variable/constant declarations

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
            context: Parent context (class/namespace) for qualified names.
        """
        # Function declarations
        if node.type == "function_declaration":
            self._extract_function(node, source, symbols, context)

        # Arrow functions and function expressions assigned to variables
        elif node.type in ("lexical_declaration", "variable_declaration"):
            self._extract_variable_declaration(node, source, symbols, context)

        # Class declarations (including abstract)
        elif node.type in ("class_declaration", "abstract_class_declaration"):
            self._extract_class(node, source, symbols, context)

        # Interface declarations
        elif node.type == "interface_declaration":
            self._extract_interface(node, source, symbols, context)

        # Type alias declarations
        elif node.type == "type_alias_declaration":
            self._extract_type_alias(node, source, symbols, context)

        # Enum declarations
        elif node.type == "enum_declaration":
            self._extract_enum(node, source, symbols, context)

        # Import statements (ES modules)
        elif node.type == "import_statement":
            self._extract_import_statement(node, source, symbols)

        # Export statements
        elif node.type == "export_statement":
            self._extract_export_statement(node, source, symbols, context)

        # CommonJS require calls at top level
        elif node.type == "expression_statement":
            self._extract_commonjs_require(node, source, symbols)

        else:
            # Recurse into children
            for child in node.children:
                self._extract_symbols_recursive(child, source, symbols, context)

    def _extract_function(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract function declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Extract return type
        return_type = self._extract_return_type(node, source)

        # Build signature
        signature = self._build_function_signature(name, params, return_type)

        # Check for async
        is_async = self._has_modifier(node, source, "async")

        # Check for generator
        is_generator = any(c.type == "generator_function" for c in node.children)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        # Extract type parameters (generics)
        type_params = self._extract_type_parameters(node, source)

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

        if is_async:
            symbol["metadata"]["async"] = True
        if is_generator:
            symbol["metadata"]["generator"] = True
        if return_type:
            symbol["metadata"]["return_type"] = return_type
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

    def _extract_variable_declaration(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract variable declarations, including arrow functions and function expressions."""
        # Determine if const, let, or var
        declaration_kind = "variable"
        if node.type == "lexical_declaration":
            first_child = node.children[0] if node.children else None
            if first_child and first_child.type == "const":
                declaration_kind = "constant"

        # Find variable declarators
        for child in node.children:
            if child.type == "variable_declarator":
                self._extract_variable_declarator(
                    child, source, symbols, context, declaration_kind
                )

    def _extract_variable_declarator(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
        declaration_kind: str,
    ) -> None:
        """Extract a single variable declarator."""
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")

        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Check if value is a function (arrow or expression)
        if value_node and value_node.type in ("arrow_function", "function_expression", "function"):
            self._extract_function_value(
                node, value_node, name, qualified_name, source, symbols, context
            )
        # Check if value is a require call (CommonJS import)
        elif value_node and value_node.type == "call_expression":
            func_node = value_node.child_by_field_name("function")
            if func_node and self.get_node_text(func_node, source) == "require":
                self._extract_require_call(node, value_node, source, symbols)
                return
            else:
                # Regular variable with call expression value
                type_annotation = self._extract_type_annotation(node, source)
                symbol = {
                    "name": name,
                    "kind": declaration_kind,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": qualified_name,
                    "metadata": {},
                }
                if type_annotation:
                    symbol["metadata"]["type"] = type_annotation
                symbols.append(symbol)
                return
        else:
            # Regular variable/constant
            type_annotation = self._extract_type_annotation(node, source)

            symbol = {
                "name": name,
                "kind": declaration_kind,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": qualified_name,
                "metadata": {},
            }

            if type_annotation:
                symbol["metadata"]["type"] = type_annotation

            symbols.append(symbol)

    def _extract_function_value(
        self,
        declarator_node: "Node",
        value_node: "Node",
        name: str,
        qualified_name: str,
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract arrow function or function expression assigned to a variable."""
        # Extract parameters
        params = self._extract_parameters(value_node, source)

        # Extract return type
        return_type = self._extract_return_type(value_node, source)

        # Build signature
        signature = self._build_function_signature(name, params, return_type)

        # Check for async
        is_async = self._has_modifier(value_node, source, "async")

        # Extract doc comment from declarator or parent
        docstring = self._extract_doc_comment(declarator_node, source)
        if not docstring and declarator_node.parent:
            docstring = self._extract_doc_comment(declarator_node.parent, source)

        # Extract type parameters
        type_params = self._extract_type_parameters(value_node, source)

        kind = "function"
        if value_node.type == "arrow_function":
            kind = "function"  # Treat arrow functions as functions

        symbol = {
            "name": name,
            "kind": kind,
            "line": declarator_node.start_point[0] + 1,
            "end_line": value_node.end_point[0] + 1,
            "start_column": declarator_node.start_point[1],
            "end_column": value_node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "docstring": docstring,
            "metadata": {
                "arrow_function": value_node.type == "arrow_function",
            },
        }

        if is_async:
            symbol["metadata"]["async"] = True
        if return_type:
            symbol["metadata"]["return_type"] = return_type
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

    def _extract_class(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract class declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Extract superclass (extends)
        extends_clause = self._find_child_by_type(node, "class_heritage")
        superclass = None
        implements = []

        if extends_clause:
            for child in extends_clause.children:
                if child.type == "extends_clause":
                    for ec in child.children:
                        if ec.type in ("identifier", "type_identifier", "member_expression", "generic_type"):
                            superclass = self.get_node_text(ec, source)
                            break
                elif child.type == "implements_clause":
                    for ic in child.children:
                        if ic.type in ("identifier", "type_identifier", "member_expression", "generic_type"):
                            impl_name = self.get_node_text(ic, source)
                            if impl_name not in ("implements", ","):
                                implements.append(impl_name)

        # Check for decorators
        decorators = self._extract_decorators(node, source)

        # Extract type parameters
        type_params = self._extract_type_parameters(node, source)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        # Check for abstract (either as modifier or by node type)
        is_abstract = node.type == "abstract_class_declaration" or self._has_modifier(node, source, "abstract")

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

        if superclass:
            symbol["metadata"]["extends"] = superclass
        if implements:
            symbol["metadata"]["implements"] = implements
        if decorators:
            symbol["metadata"]["decorators"] = decorators
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params
        if is_abstract:
            symbol["metadata"]["abstract"] = True

        symbols.append(symbol)

        # Extract class body (methods, properties)
        class_body = node.child_by_field_name("body")
        if class_body:
            new_context = {
                "type": "class",
                "name": name,
                "qualified_name": qualified_name,
            }
            self._extract_class_body(class_body, source, symbols, new_context)

    def _extract_class_body(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict,
    ) -> None:
        """Extract members from a class body."""
        for child in node.children:
            if child.type == "method_definition":
                self._extract_method(child, source, symbols, context)
            elif child.type == "public_field_definition":
                self._extract_property(child, source, symbols, context)
            elif child.type in ("property_signature", "field_definition"):
                self._extract_property(child, source, symbols, context)

    def _extract_method(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict,
    ) -> None:
        """Extract method definition from a class."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        qualified_name = f"{context['qualified_name']}.{name}"

        # Extract parameters
        params = self._extract_parameters(node, source)

        # Extract return type
        return_type = self._extract_return_type(node, source)

        # Build signature
        signature = self._build_method_signature(name, params, return_type)

        # Check modifiers
        is_async = self._has_modifier(node, source, "async")
        is_static = self._has_modifier(node, source, "static")
        is_private = self._has_modifier(node, source, "private")
        is_protected = self._has_modifier(node, source, "protected")
        is_public = self._has_modifier(node, source, "public")
        is_abstract = self._has_modifier(node, source, "abstract")
        is_readonly = self._has_modifier(node, source, "readonly")

        # Check for getter/setter
        is_getter = self._has_modifier(node, source, "get")
        is_setter = self._has_modifier(node, source, "set")

        # Determine kind
        kind = "method"
        if name == "constructor":
            kind = "constructor"

        # Extract decorators
        decorators = self._extract_decorators(node, source)

        # Extract type parameters
        type_params = self._extract_type_parameters(node, source)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": kind,
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "signature": signature,
            "docstring": docstring,
            "metadata": {},
        }

        if is_async:
            symbol["metadata"]["async"] = True
        if is_static:
            symbol["metadata"]["static"] = True
        if is_private:
            symbol["metadata"]["visibility"] = "private"
        elif is_protected:
            symbol["metadata"]["visibility"] = "protected"
        elif is_public:
            symbol["metadata"]["visibility"] = "public"
        if is_abstract:
            symbol["metadata"]["abstract"] = True
        if is_readonly:
            symbol["metadata"]["readonly"] = True
        if is_getter:
            symbol["metadata"]["accessor"] = "getter"
        if is_setter:
            symbol["metadata"]["accessor"] = "setter"
        if return_type:
            symbol["metadata"]["return_type"] = return_type
        if decorators:
            symbol["metadata"]["decorators"] = decorators
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

    def _extract_property(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict,
    ) -> None:
        """Extract property from a class."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            # Try to find identifier directly
            for child in node.children:
                if child.type in ("property_identifier", "identifier", "private_property_identifier"):
                    name_node = child
                    break

        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        qualified_name = f"{context['qualified_name']}.{name}"

        # Extract type annotation
        type_annotation = self._extract_type_annotation(node, source)

        # Check modifiers
        is_static = self._has_modifier(node, source, "static")
        is_private = self._has_modifier(node, source, "private")
        is_protected = self._has_modifier(node, source, "protected")
        is_public = self._has_modifier(node, source, "public")
        is_readonly = self._has_modifier(node, source, "readonly")

        # Extract decorators
        decorators = self._extract_decorators(node, source)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "property",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        if type_annotation:
            symbol["metadata"]["type"] = type_annotation
        if is_static:
            symbol["metadata"]["static"] = True
        if is_private:
            symbol["metadata"]["visibility"] = "private"
        elif is_protected:
            symbol["metadata"]["visibility"] = "protected"
        elif is_public:
            symbol["metadata"]["visibility"] = "public"
        if is_readonly:
            symbol["metadata"]["readonly"] = True
        if decorators:
            symbol["metadata"]["decorators"] = decorators

        symbols.append(symbol)

    def _extract_interface(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract interface declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Extract extends (interfaces can extend multiple interfaces)
        extends = []
        extends_clause = self._find_child_by_type(node, "extends_type_clause")
        if extends_clause:
            for child in extends_clause.children:
                if child.type in ("identifier", "type_identifier", "member_expression", "generic_type"):
                    ext_name = self.get_node_text(child, source)
                    if ext_name not in ("extends", ","):
                        extends.append(ext_name)

        # Extract type parameters
        type_params = self._extract_type_parameters(node, source)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        # Extract interface members
        members = []
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "property_signature":
                    member = self._extract_interface_member(child, source)
                    if member:
                        members.append(member)
                elif child.type == "method_signature":
                    member = self._extract_interface_method(child, source)
                    if member:
                        members.append(member)

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
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params
        if members:
            symbol["metadata"]["members"] = members

        symbols.append(symbol)

    def _extract_interface_member(self, node: "Node", source: bytes) -> dict | None:
        """Extract a property signature from an interface."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for child in node.children:
                if child.type in ("property_identifier", "identifier"):
                    name_node = child
                    break

        if name_node is None:
            return None

        name = self.get_node_text(name_node, source)
        type_annotation = self._extract_type_annotation(node, source)
        is_optional = "?" in self.get_node_text(node, source).split(":")[0]

        member = {"name": name, "kind": "property"}
        if type_annotation:
            member["type"] = type_annotation
        if is_optional:
            member["optional"] = True

        return member

    def _extract_interface_method(self, node: "Node", source: bytes) -> dict | None:
        """Extract a method signature from an interface."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for child in node.children:
                if child.type in ("property_identifier", "identifier"):
                    name_node = child
                    break

        if name_node is None:
            return None

        name = self.get_node_text(name_node, source)
        params = self._extract_parameters(node, source)
        return_type = self._extract_return_type(node, source)

        member = {
            "name": name,
            "kind": "method",
            "params": params,
        }
        if return_type:
            member["return_type"] = return_type

        return member

    def _extract_type_alias(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract type alias declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Extract the type value
        value_node = node.child_by_field_name("value")
        type_value = None
        if value_node:
            type_value = self.get_node_text(value_node, source)

        # Extract type parameters
        type_params = self._extract_type_parameters(node, source)

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "type",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        if type_value:
            symbol["metadata"]["type_value"] = type_value
        if type_params:
            symbol["metadata"]["type_parameters"] = type_params

        symbols.append(symbol)

    def _extract_enum(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract enum declaration."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self.get_node_text(name_node, source)

        # Build qualified name
        if context and context.get("qualified_name"):
            qualified_name = f"{context['qualified_name']}.{name}"
        else:
            qualified_name = name

        # Check for const enum
        is_const = self._has_modifier(node, source, "const")

        # Extract members
        members = []
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "enum_assignment":
                    member_name_node = child.child_by_field_name("name")
                    if member_name_node:
                        members.append(self.get_node_text(member_name_node, source))
                elif child.type == "property_identifier":
                    members.append(self.get_node_text(child, source))

        # Extract doc comment
        docstring = self._extract_doc_comment(node, source)

        symbol = {
            "name": name,
            "kind": "enum",
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "start_column": node.start_point[1],
            "end_column": node.end_point[1],
            "qualified_name": qualified_name,
            "docstring": docstring,
            "metadata": {},
        }

        if is_const:
            symbol["metadata"]["const"] = True
        if members:
            symbol["metadata"]["members"] = members

        symbols.append(symbol)

    def _extract_import_statement(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract ES module import statement."""
        # Get the source module
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return

        module_path = self.get_node_text(source_node, source).strip("'\"")

        # Extract imported items
        import_clause = self._find_child_by_type(node, "import_clause")
        if import_clause is None:
            # Side-effect import: import 'module'
            symbols.append({
                "name": module_path,
                "kind": "import",
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_column": node.start_point[1],
                "end_column": node.end_point[1],
                "qualified_name": module_path,
                "metadata": {
                    "import_type": "side_effect",
                    "module": module_path,
                },
            })
            return

        for child in import_clause.children:
            if child.type == "identifier":
                # Default import: import foo from 'module'
                name = self.get_node_text(child, source)
                symbols.append({
                    "name": name,
                    "kind": "import",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "start_column": node.start_point[1],
                    "end_column": node.end_point[1],
                    "qualified_name": f"{module_path}.default",
                    "metadata": {
                        "import_type": "default",
                        "module": module_path,
                        "local_name": name,
                    },
                })

            elif child.type == "named_imports":
                # Named imports: import { foo, bar as baz } from 'module'
                for spec in child.children:
                    if spec.type == "import_specifier":
                        self._extract_import_specifier(spec, source, symbols, module_path, node)

            elif child.type == "namespace_import":
                # Namespace import: import * as foo from 'module'
                for spec in child.children:
                    if spec.type == "identifier":
                        name = self.get_node_text(spec, source)
                        symbols.append({
                            "name": name,
                            "kind": "import",
                            "line": node.start_point[0] + 1,
                            "end_line": node.end_point[0] + 1,
                            "start_column": node.start_point[1],
                            "end_column": node.end_point[1],
                            "qualified_name": f"{module_path}.*",
                            "metadata": {
                                "import_type": "namespace",
                                "module": module_path,
                                "local_name": name,
                            },
                        })
                        break

    def _extract_import_specifier(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        module_path: str,
        import_node: "Node",
    ) -> None:
        """Extract a single import specifier."""
        name_node = node.child_by_field_name("name")
        alias_node = node.child_by_field_name("alias")

        if name_node is None:
            return

        original_name = self.get_node_text(name_node, source)
        local_name = self.get_node_text(alias_node, source) if alias_node else original_name

        symbols.append({
            "name": local_name,
            "kind": "import",
            "line": import_node.start_point[0] + 1,
            "end_line": import_node.end_point[0] + 1,
            "start_column": import_node.start_point[1],
            "end_column": import_node.end_point[1],
            "qualified_name": f"{module_path}.{original_name}",
            "metadata": {
                "import_type": "named",
                "module": module_path,
                "original_name": original_name,
                "local_name": local_name,
            },
        })

    def _extract_export_statement(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        context: dict | None,
    ) -> None:
        """Extract export statement."""
        # Check for re-exports: export { foo } from 'module'
        source_node = node.child_by_field_name("source")
        if source_node:
            module_path = self.get_node_text(source_node, source).strip("'\"")
            # This is a re-export, treat similarly to import
            export_clause = self._find_child_by_type(node, "export_clause")
            if export_clause:
                for spec in export_clause.children:
                    if spec.type == "export_specifier":
                        self._extract_export_specifier(spec, source, symbols, module_path, node)
            return

        # Check for export default
        for child in node.children:
            if child.type == "export_default":
                # Handle export default
                pass

        # Check for exported declarations
        for child in node.children:
            if child.type == "function_declaration":
                self._extract_function(child, source, symbols, context)
                # Mark as exported
                if symbols and symbols[-1]["name"] == self.get_node_text(
                    child.child_by_field_name("name"), source
                ):
                    symbols[-1]["metadata"]["exported"] = True

            elif child.type == "class_declaration":
                self._extract_class(child, source, symbols, context)
                if symbols:
                    symbols[-1]["metadata"]["exported"] = True

            elif child.type in ("lexical_declaration", "variable_declaration"):
                self._extract_variable_declaration(child, source, symbols, context)
                # Mark recent symbols as exported
                for child_node in child.children:
                    if child_node.type == "variable_declarator":
                        name_node = child_node.child_by_field_name("name")
                        if name_node:
                            var_name = self.get_node_text(name_node, source)
                            for sym in reversed(symbols):
                                if sym["name"] == var_name:
                                    sym["metadata"]["exported"] = True
                                    break

            elif child.type == "interface_declaration":
                self._extract_interface(child, source, symbols, context)
                if symbols:
                    symbols[-1]["metadata"]["exported"] = True

            elif child.type == "type_alias_declaration":
                self._extract_type_alias(child, source, symbols, context)
                if symbols:
                    symbols[-1]["metadata"]["exported"] = True

            elif child.type == "enum_declaration":
                self._extract_enum(child, source, symbols, context)
                if symbols:
                    symbols[-1]["metadata"]["exported"] = True

    def _extract_export_specifier(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
        module_path: str | None,
        export_node: "Node",
    ) -> None:
        """Extract a single export specifier."""
        name_node = node.child_by_field_name("name")
        alias_node = node.child_by_field_name("alias")

        if name_node is None:
            return

        original_name = self.get_node_text(name_node, source)
        export_name = self.get_node_text(alias_node, source) if alias_node else original_name

        symbol = {
            "name": export_name,
            "kind": "import",  # Re-exports are similar to imports
            "line": export_node.start_point[0] + 1,
            "end_line": export_node.end_point[0] + 1,
            "start_column": export_node.start_point[1],
            "end_column": export_node.end_point[1],
            "qualified_name": f"{module_path}.{original_name}" if module_path else original_name,
            "metadata": {
                "import_type": "re_export",
                "original_name": original_name,
                "export_name": export_name,
            },
        }

        if module_path:
            symbol["metadata"]["module"] = module_path

        symbols.append(symbol)

    def _extract_commonjs_require(
        self,
        node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract CommonJS require calls at module level."""
        # Look for: const foo = require('module')
        # or: const { foo, bar } = require('module')
        for child in node.children:
            if child.type in ("lexical_declaration", "variable_declaration"):
                for declarator in child.children:
                    if declarator.type == "variable_declarator":
                        value_node = declarator.child_by_field_name("value")
                        if value_node and value_node.type == "call_expression":
                            func_node = value_node.child_by_field_name("function")
                            if func_node and self.get_node_text(func_node, source) == "require":
                                self._extract_require_call(declarator, value_node, source, symbols)

    def _extract_require_call(
        self,
        declarator: "Node",
        call_node: "Node",
        source: bytes,
        symbols: list[dict],
    ) -> None:
        """Extract a require() call."""
        # Get module path
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return

        module_path = None
        for arg in args_node.children:
            if arg.type == "string":
                module_path = self.get_node_text(arg, source).strip("'\"")
                break

        if module_path is None:
            return

        # Get the bound name(s)
        name_node = declarator.child_by_field_name("name")
        if name_node is None:
            return

        if name_node.type == "identifier":
            # const foo = require('module')
            name = self.get_node_text(name_node, source)
            symbols.append({
                "name": name,
                "kind": "import",
                "line": declarator.start_point[0] + 1,
                "end_line": declarator.end_point[0] + 1,
                "start_column": declarator.start_point[1],
                "end_column": declarator.end_point[1],
                "qualified_name": module_path,
                "metadata": {
                    "import_type": "commonjs",
                    "module": module_path,
                    "local_name": name,
                },
            })

        elif name_node.type == "object_pattern":
            # const { foo, bar } = require('module')
            for child in name_node.children:
                if child.type == "shorthand_property_identifier_pattern":
                    name = self.get_node_text(child, source)
                    symbols.append({
                        "name": name,
                        "kind": "import",
                        "line": declarator.start_point[0] + 1,
                        "end_line": declarator.end_point[0] + 1,
                        "start_column": declarator.start_point[1],
                        "end_column": declarator.end_point[1],
                        "qualified_name": f"{module_path}.{name}",
                        "metadata": {
                            "import_type": "commonjs_destructured",
                            "module": module_path,
                            "local_name": name,
                        },
                    })

                elif child.type == "pair_pattern":
                    key_node = child.child_by_field_name("key")
                    value_node = child.child_by_field_name("value")
                    if key_node and value_node:
                        original_name = self.get_node_text(key_node, source)
                        local_name = self.get_node_text(value_node, source)
                        symbols.append({
                            "name": local_name,
                            "kind": "import",
                            "line": declarator.start_point[0] + 1,
                            "end_line": declarator.end_point[0] + 1,
                            "start_column": declarator.start_point[1],
                            "end_column": declarator.end_point[1],
                            "qualified_name": f"{module_path}.{original_name}",
                            "metadata": {
                                "import_type": "commonjs_destructured",
                                "module": module_path,
                                "original_name": original_name,
                                "local_name": local_name,
                            },
                        })

    def extract_references(
        self,
        tree: "Tree",
        source: bytes,
        file_path: Path | str | None = None,
    ) -> list[dict]:
        """Extract symbol references from TypeScript/JavaScript AST.

        Extracts:
        - Function/method calls
        - Import edges
        - Inheritance relationships (extends/implements)
        - Callback registrations
        - Promise chains

        Args:
            tree: Parsed tree-sitter Tree.
            source: Original source bytes.
            file_path: Optional path to the source file (unused).

        Returns:
            List of reference dictionaries.
        """
        references: list[dict] = []

        # First pass: collect all symbols for context
        symbols = self.extract_symbols(tree, source)
        symbol_map = {s["qualified_name"]: s for s in symbols if s.get("qualified_name")}

        # Build import map for resolving cross-module calls
        import_map = self._build_import_map(symbols)

        # Extract references
        self._extract_references_recursive(
            tree.root_node, source, references, context=None,
            symbol_map=symbol_map, import_map=import_map
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

        # Add inheritance edges
        for symbol in symbols:
            if symbol["kind"] == "class":
                if symbol.get("metadata", {}).get("extends"):
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": symbol["metadata"]["extends"],
                        "type": "inherits",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })
                for impl in symbol.get("metadata", {}).get("implements", []):
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": impl,
                        "type": "implements",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

            elif symbol["kind"] == "interface":
                for ext in symbol.get("metadata", {}).get("extends", []):
                    references.append({
                        "source": symbol["qualified_name"],
                        "target": ext,
                        "type": "inherits",
                        "line": symbol["line"],
                        "column": symbol["start_column"],
                    })

        return references

    def _build_import_map(self, symbols: list[dict]) -> dict[str, dict]:
        """Build a mapping of import names to their module information."""
        import_map: dict[str, dict] = {}

        for symbol in symbols:
            if symbol["kind"] == "import":
                metadata = symbol.get("metadata", {})
                local_name = metadata.get("local_name", symbol["name"])
                module = metadata.get("module", "")

                import_map[local_name] = {
                    "module": module,
                    "original_name": metadata.get("original_name", local_name),
                    "import_type": metadata.get("import_type", "unknown"),
                }

        return import_map

    def _extract_references_recursive(
        self,
        node: "Node",
        source: bytes,
        references: list[dict],
        context: dict | None,
        symbol_map: dict,
        import_map: dict[str, dict],
    ) -> None:
        """Recursively extract references from AST nodes."""
        new_context = context

        # Track context for calls
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.get_node_text(name_node, source)
                new_context = {
                    "type": "function",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node and context:
                name = self.get_node_text(name_node, source)
                qualified_name = f"{context.get('qualified_name', '')}.{name}"
                new_context = {
                    "type": "method",
                    "name": name,
                    "qualified_name": qualified_name,
                }

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.get_node_text(name_node, source)
                new_context = {
                    "type": "class",
                    "name": name,
                    "qualified_name": name,
                }

        elif node.type in ("arrow_function", "function_expression"):
            # Check if this is assigned to a variable
            if context and context.get("type") == "variable_assignment":
                new_context = {
                    "type": "function",
                    "name": context["name"],
                    "qualified_name": context["qualified_name"],
                }

        elif node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node and value_node and value_node.type in ("arrow_function", "function_expression"):
                name = self.get_node_text(name_node, source)
                new_context = {
                    "type": "function",
                    "name": name,
                    "qualified_name": name,
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
        import_map: dict[str, dict],
    ) -> None:
        """Extract a function/method call reference."""
        # Get the caller context
        caller = "<module>"
        if context and context.get("qualified_name"):
            caller = context["qualified_name"]

        # Get the function being called
        function_node = node.child_by_field_name("function")
        if function_node is None:
            return

        callee = None
        metadata: dict = {}

        if function_node.type == "identifier":
            # Simple function call: foo()
            callee = self.get_node_text(function_node, source)

            # Check if this is an imported function
            if callee in import_map:
                import_info = import_map[callee]
                metadata["target_module"] = import_info["module"]
                if import_info.get("original_name") and import_info["original_name"] != callee:
                    metadata["original_name"] = import_info["original_name"]

        elif function_node.type == "member_expression":
            # Method call: obj.method() or pkg.func()
            object_node = function_node.child_by_field_name("object")
            property_node = function_node.child_by_field_name("property")

            if object_node and property_node:
                obj_text = self.get_node_text(object_node, source)
                prop_text = self.get_node_text(property_node, source)

                # Check if object is an imported module
                if obj_text in import_map:
                    import_info = import_map[obj_text]
                    metadata["target_module"] = import_info["module"]
                    callee = prop_text
                else:
                    callee = f"{obj_text}.{prop_text}"

                # Detect special patterns
                if prop_text in ("then", "catch", "finally"):
                    metadata["promise_chain"] = True
                elif prop_text in ("on", "once", "addEventListener", "addListener"):
                    metadata["event_registration"] = True

        elif function_node.type == "new_expression":
            # Constructor call: new Foo()
            constructor_node = function_node.child_by_field_name("constructor")
            if constructor_node:
                callee = self.get_node_text(constructor_node, source)
                metadata["instantiation"] = True

        else:
            # Other complex expressions
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

    def _find_child_by_type(self, node: "Node", child_type: str) -> "Node | None":
        """Find a child node by type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _has_modifier(self, node: "Node", source: bytes, modifier: str) -> bool:
        """Check if a node has a specific modifier."""
        for child in node.children:
            if child.type == modifier:
                return True
            if child.type == "accessibility_modifier":
                if self.get_node_text(child, source) == modifier:
                    return True
        return False

    def _extract_parameters(self, node: "Node", source: bytes) -> list[str]:
        """Extract parameters from a function/method declaration."""
        params = []

        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            # Try to find formal_parameters
            params_node = self._find_child_by_type(node, "formal_parameters")

        if params_node is None:
            return params

        for child in params_node.children:
            if child.type in (
                "required_parameter",
                "optional_parameter",
                "rest_parameter",
                "identifier",
            ):
                param_text = self.get_node_text(child, source)
                params.append(param_text)

        return params

    def _extract_return_type(self, node: "Node", source: bytes) -> str | None:
        """Extract return type annotation from a function/method."""
        return_type_node = node.child_by_field_name("return_type")
        if return_type_node:
            # Skip the colon
            type_text = self.get_node_text(return_type_node, source)
            if type_text.startswith(":"):
                type_text = type_text[1:].strip()
            return type_text

        # Look for type_annotation child
        for child in node.children:
            if child.type == "type_annotation":
                type_text = self.get_node_text(child, source)
                if type_text.startswith(":"):
                    type_text = type_text[1:].strip()
                return type_text

        return None

    def _extract_type_annotation(self, node: "Node", source: bytes) -> str | None:
        """Extract type annotation from a variable/property declaration."""
        type_node = node.child_by_field_name("type")
        if type_node:
            return self.get_node_text(type_node, source)

        # Look for type_annotation child
        for child in node.children:
            if child.type == "type_annotation":
                type_text = self.get_node_text(child, source)
                if type_text.startswith(":"):
                    type_text = type_text[1:].strip()
                return type_text

        return None

    def _extract_type_parameters(self, node: "Node", source: bytes) -> list[str] | None:
        """Extract type parameters (generics) from a declaration."""
        type_params_node = node.child_by_field_name("type_parameters")
        if type_params_node is None:
            type_params_node = self._find_child_by_type(node, "type_parameters")

        if type_params_node is None:
            return None

        params = []
        for child in type_params_node.children:
            if child.type == "type_parameter":
                name_node = child.child_by_field_name("name")
                if name_node:
                    params.append(self.get_node_text(name_node, source))
                else:
                    # Try to find identifier
                    for c in child.children:
                        if c.type == "type_identifier":
                            params.append(self.get_node_text(c, source))
                            break

        return params if params else None

    def _extract_decorators(self, node: "Node", source: bytes) -> list[str] | None:
        """Extract decorators from a declaration."""
        decorators = []

        # Look for decorator nodes in siblings
        if node.prev_sibling and node.prev_sibling.type == "decorator":
            sibling = node.prev_sibling
            while sibling and sibling.type == "decorator":
                decorator_text = self.get_node_text(sibling, source)
                decorators.insert(0, decorator_text)
                sibling = sibling.prev_sibling

        # Also check children
        for child in node.children:
            if child.type == "decorator":
                decorator_text = self.get_node_text(child, source)
                decorators.append(decorator_text)

        return decorators if decorators else None

    def _extract_doc_comment(self, node: "Node", source: bytes) -> str | None:
        """Extract JSDoc comment from a declaration."""
        # Look for comment nodes that are siblings immediately before this node
        if node.prev_sibling is None:
            return None

        sibling = node.prev_sibling

        # Skip decorators to find the comment
        while sibling and sibling.type == "decorator":
            sibling = sibling.prev_sibling

        if sibling and sibling.type == "comment":
            comment_text = self.get_node_text(sibling, source)
            # Check if it's a JSDoc comment
            if comment_text.startswith("/**"):
                # Clean up the comment
                lines = comment_text.split("\n")
                cleaned_lines = []
                for line in lines:
                    line = line.strip()
                    if line.startswith("/**"):
                        line = line[3:].strip()
                    elif line.startswith("*/"):
                        line = line[:-2].strip()
                    elif line.startswith("*"):
                        line = line[1:].strip()
                    if line:
                        cleaned_lines.append(line)
                return "\n".join(cleaned_lines) if cleaned_lines else None

        return None

    def _build_function_signature(
        self,
        name: str,
        params: list[str],
        return_type: str | None,
    ) -> str:
        """Build a function signature string."""
        param_str = ", ".join(params)
        if return_type:
            return f"function {name}({param_str}): {return_type}"
        return f"function {name}({param_str})"

    def _build_method_signature(
        self,
        name: str,
        params: list[str],
        return_type: str | None,
    ) -> str:
        """Build a method signature string."""
        param_str = ", ".join(params)
        if return_type:
            return f"{name}({param_str}): {return_type}"
        return f"{name}({param_str})"
