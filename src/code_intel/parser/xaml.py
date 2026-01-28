"""XAML parser for .NET MAUI and WPF UI markup.

Unlike the tree-sitter based parsers, this parser uses Python's xml.etree.ElementTree
since XAML is well-formed XML. The semantic extraction is what matters, not AST precision.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_intel.parser.base import ParsedEdge, ParsedNode, ParseResult


# Common XAML namespaces
XAML_2006_NS = "http://schemas.microsoft.com/winfx/2006/xaml"
XAML_2009_NS = "http://schemas.microsoft.com/winfx/2009/xaml"
MAUI_NS = "http://schemas.microsoft.com/dotnet/2021/maui"
WPF_PRESENTATION_NS = "http://schemas.microsoft.com/winfx/2006/xaml/presentation"

# x: namespace prefixes used in XAML
X_NAMESPACE_PREFIXES = {XAML_2006_NS, XAML_2009_NS}

# Common event handler attribute names in MAUI/WPF
EVENT_HANDLER_ATTRIBUTES = {
    # Button/interaction events
    "Clicked", "Tapped", "DoubleTapped", "LongPressed", "Pressed", "Released",
    "Unfocused", "Focused",
    # Text events
    "TextChanged", "Completed", "SearchButtonPressed",
    # Selection events
    "SelectedIndexChanged", "SelectionChanged", "ItemSelected", "ItemTapped",
    # Life cycle events
    "Appearing", "Disappearing", "Loaded", "Unloaded",
    # Layout events
    "SizeChanged", "LayoutChanged", "ChildAdded", "ChildRemoved",
    # Scroll events
    "Scrolled", "ScrollToRequested",
    # Property changed
    "PropertyChanged", "PropertyChanging",
    # WPF-specific
    "Click", "MouseDown", "MouseUp", "MouseEnter", "MouseLeave",
    "KeyDown", "KeyUp", "PreviewKeyDown", "PreviewKeyUp",
    "GotFocus", "LostFocus", "GotKeyboardFocus", "LostKeyboardFocus",
    "DragEnter", "DragLeave", "DragOver", "Drop",
    "Closing", "Closed", "Opening", "Opened",
}

# Regex patterns for markup extensions
BINDING_PATTERN = re.compile(r"\{Binding\s+([^}]*)\}")
STATIC_RESOURCE_PATTERN = re.compile(r"\{StaticResource\s+([^}]+)\}")
DYNAMIC_RESOURCE_PATTERN = re.compile(r"\{DynamicResource\s+([^}]+)\}")
TEMPLATE_BINDING_PATTERN = re.compile(r"\{TemplateBinding\s+([^}]+)\}")


# Pattern to extract xmlns declarations from raw XML
XMLNS_PATTERN = re.compile(r'xmlns(?::(\w+))?="([^"]+)"')


@dataclass
class XamlNamespaceMap:
    """Maps XML namespace prefixes to CLR namespaces."""

    prefixes: dict[str, str] = field(default_factory=dict)
    """Map of prefix -> namespace URI."""

    clr_namespaces: dict[str, str] = field(default_factory=dict)
    """Map of prefix -> CLR namespace (e.g., 'local' -> 'MyApp.Views')."""

    @classmethod
    def from_element(cls, root: ET.Element) -> "XamlNamespaceMap":
        """Extract namespace mappings from root element attributes.

        Note: ElementTree doesn't expose xmlns attributes, so this method
        only works with attributes that are present in root.attrib.
        For full namespace extraction, use from_xml_content() instead.

        Args:
            root: Root XML element containing xmlns declarations.

        Returns:
            XamlNamespaceMap with extracted namespace info.
        """
        prefixes: dict[str, str] = {}
        clr_namespaces: dict[str, str] = {}

        for attr, value in root.attrib.items():
            if attr.startswith("{"):
                # Handle {namespace}attr format
                continue
            if attr == "xmlns":
                # Default namespace
                prefixes[""] = value
            elif attr.startswith("xmlns:"):
                prefix = attr[6:]  # Remove "xmlns:"
                prefixes[prefix] = value

                # Extract CLR namespace from clr-namespace syntax
                # Format: clr-namespace:MyApp.Views;assembly=MyApp
                if value.startswith("clr-namespace:"):
                    parts = value.split(";")
                    clr_ns = parts[0][14:]  # Remove "clr-namespace:"
                    clr_namespaces[prefix] = clr_ns

        return cls(prefixes=prefixes, clr_namespaces=clr_namespaces)

    @classmethod
    def from_xml_content(cls, content: str) -> "XamlNamespaceMap":
        """Extract namespace mappings from raw XML content.

        ElementTree strips xmlns attributes, so we need to parse them
        directly from the raw XML string.

        Args:
            content: Raw XML content string.

        Returns:
            XamlNamespaceMap with extracted namespace info.
        """
        prefixes: dict[str, str] = {}
        clr_namespaces: dict[str, str] = {}

        # Find all xmlns declarations in the content
        for match in XMLNS_PATTERN.finditer(content):
            prefix = match.group(1) or ""  # None means default namespace
            uri = match.group(2)

            prefixes[prefix] = uri

            # Extract CLR namespace from clr-namespace syntax
            if uri.startswith("clr-namespace:"):
                parts = uri.split(";")
                clr_ns = parts[0][14:]  # Remove "clr-namespace:"
                clr_namespaces[prefix] = clr_ns

        return cls(prefixes=prefixes, clr_namespaces=clr_namespaces)


class XamlParser:
    """Parser for XAML files (.xaml) used in .NET MAUI and WPF applications.

    Extracts:
    - Nodes: Pages, Views, Controls, Resources, named elements (x:Name)
    - Edges: event_handler, binding, command, resource_ref, type_ref
    """

    @property
    def language_name(self) -> str:
        return "xaml"

    @property
    def file_extensions(self) -> list[str]:
        return [".xaml"]

    def parse_to_result(
        self, file_path: Path | str, content: str | None = None
    ) -> ParseResult:
        """Parse a XAML file and extract nodes/edges.

        Args:
            file_path: Path to the XAML file.
            content: Optional XAML content. If not provided, reads from file_path.

        Returns:
            ParseResult containing extracted nodes, edges, and any errors.
        """
        file_path = Path(file_path)
        errors: list[str] = []

        if content is None:
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                return ParseResult(
                    file_path=str(file_path),
                    nodes=[],
                    edges=[],
                    errors=[f"Failed to read file: {e}"],
                )

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            return ParseResult(
                file_path=str(file_path),
                nodes=[],
                edges=[],
                errors=[f"XML parse error: {e}"],
            )

        # Extract namespace mappings
        ns_map = XamlNamespaceMap.from_element(root)

        # Get line numbers (ElementTree doesn't preserve them, so we estimate)
        # For accurate line numbers we'd need a different parser, but this is adequate
        line_map = self._build_line_map(content)

        nodes: list[ParsedNode] = []
        edges: list[ParsedEdge] = []

        # Extract x:Class (code-behind link)
        x_class = self._extract_x_class(root, ns_map)
        if x_class:
            nodes.append(
                ParsedNode(
                    node_type="page",
                    name=x_class.split(".")[-1],
                    start_line=1,
                    end_line=1,
                    qualified_name=x_class,
                    metadata={"x_class": x_class, "is_code_behind": True},
                )
            )

        # Recursively extract from all elements
        self._extract_recursive(
            root, nodes, edges, ns_map, x_class, line_map, depth=0
        )

        return ParseResult(
            file_path=str(file_path),
            nodes=nodes,
            edges=edges,
            errors=errors,
        )

    def _build_line_map(self, content: str) -> dict[str, int]:
        """Build a map of element names to approximate line numbers.

        ElementTree doesn't preserve line numbers, so we search for element
        occurrences in the original content.
        """
        line_map: dict[str, int] = {}
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Find element starts like <Button, <Label, etc.
            matches = re.findall(r"<(\w+:)?(\w+)", line)
            for _, tag in matches:
                if tag not in line_map:
                    line_map[tag] = i

        return line_map

    def _get_line_for_element(
        self, element: ET.Element, line_map: dict[str, int]
    ) -> int:
        """Get approximate line number for an element."""
        tag = self._get_local_tag(element.tag)
        return line_map.get(tag, 1)

    def _get_local_tag(self, tag: str) -> str:
        """Extract local tag name from namespace-prefixed tag.

        Args:
            tag: Tag like "{http://namespace}LocalName"

        Returns:
            Local tag name without namespace.
        """
        if "}" in tag:
            return tag.split("}")[1]
        return tag

    def _get_namespace(self, tag: str) -> str | None:
        """Extract namespace from tag.

        Args:
            tag: Tag like "{http://namespace}LocalName"

        Returns:
            Namespace URI or None if not present.
        """
        if tag.startswith("{"):
            return tag[1:tag.index("}")]
        return None

    def _extract_x_class(
        self, root: ET.Element, ns_map: XamlNamespaceMap
    ) -> str | None:
        """Extract x:Class attribute value from root element.

        Args:
            root: Root XML element.
            ns_map: Namespace mappings.

        Returns:
            Fully qualified class name or None.
        """
        # Try both x: namespace versions
        for ns in X_NAMESPACE_PREFIXES:
            x_class = root.get(f"{{{ns}}}Class")
            if x_class:
                return x_class
        return None

    def _extract_x_name(
        self, element: ET.Element, ns_map: XamlNamespaceMap
    ) -> str | None:
        """Extract x:Name attribute value from an element.

        Args:
            element: XML element.
            ns_map: Namespace mappings.

        Returns:
            Name value or None.
        """
        for ns in X_NAMESPACE_PREFIXES:
            x_name = element.get(f"{{{ns}}}Name")
            if x_name:
                return x_name
        # Also check Name without x: prefix (WPF style)
        return element.get("Name")

    def _extract_x_key(
        self, element: ET.Element, ns_map: XamlNamespaceMap
    ) -> str | None:
        """Extract x:Key attribute value from a resource element.

        Args:
            element: XML element.
            ns_map: Namespace mappings.

        Returns:
            Key value or None.
        """
        for ns in X_NAMESPACE_PREFIXES:
            x_key = element.get(f"{{{ns}}}Key")
            if x_key:
                return x_key
        return None

    def _extract_recursive(
        self,
        element: ET.Element,
        nodes: list[ParsedNode],
        edges: list[ParsedEdge],
        ns_map: XamlNamespaceMap,
        page_class: str | None,
        line_map: dict[str, int],
        depth: int,
    ) -> None:
        """Recursively extract nodes and edges from XAML elements.

        Args:
            element: Current XML element.
            nodes: List to append nodes to.
            edges: List to append edges to.
            ns_map: Namespace mappings.
            page_class: The page's x:Class value (for edge sources).
            line_map: Map of tag names to line numbers.
            depth: Current nesting depth.
        """
        tag = self._get_local_tag(element.tag)
        namespace = self._get_namespace(element.tag)
        line = self._get_line_for_element(element, line_map)

        # Extract x:Name (creates a node for named elements)
        x_name = self._extract_x_name(element, ns_map)
        if x_name:
            nodes.append(
                ParsedNode(
                    node_type="named_element",
                    name=x_name,
                    start_line=line,
                    end_line=line,
                    qualified_name=f"{page_class}.{x_name}" if page_class else x_name,
                    metadata={"element_type": tag, "x_name": x_name},
                )
            )

        # Check if this is a resource (has x:Key)
        x_key = self._extract_x_key(element, ns_map)
        if x_key:
            nodes.append(
                ParsedNode(
                    node_type="resource",
                    name=x_key,
                    start_line=line,
                    end_line=line,
                    qualified_name=x_key,
                    metadata={"resource_type": tag, "x_key": x_key},
                )
            )

        # Extract event handlers and bindings from attributes
        for attr, value in element.attrib.items():
            attr_local = self._get_local_attr(attr)

            # Skip x: namespace attributes (already handled)
            if attr_local in ("Class", "Name", "Key"):
                continue

            # Check for event handlers
            if attr_local in EVENT_HANDLER_ATTRIBUTES:
                self._extract_event_handler(
                    element, attr_local, value, edges, page_class, tag, line
                )
                continue

            # Check for binding expressions in attribute value
            self._extract_markup_extensions(
                element, attr_local, value, edges, page_class, tag, line
            )

        # Recurse into children
        for child in element:
            self._extract_recursive(
                child, nodes, edges, ns_map, page_class, line_map, depth + 1
            )

    def _get_local_attr(self, attr: str) -> str:
        """Get local attribute name, removing namespace prefix.

        Args:
            attr: Attribute like "{http://ns}Name" or "Name"

        Returns:
            Local attribute name.
        """
        if "}" in attr:
            return attr.split("}")[1]
        return attr

    def _extract_event_handler(
        self,
        element: ET.Element,
        event_name: str,
        handler_name: str,
        edges: list[ParsedEdge],
        page_class: str | None,
        element_tag: str,
        line: int,
    ) -> None:
        """Extract an event handler edge.

        Args:
            element: The element with the event handler.
            event_name: Name of the event (e.g., "Clicked").
            handler_name: Name of the handler method (e.g., "OnButtonClicked").
            edges: List to append edge to.
            page_class: The page's x:Class for the source.
            element_tag: Tag name of the element.
            line: Line number.
        """
        # The handler method lives in the code-behind class
        source = f"{page_class}.xaml" if page_class else "unknown.xaml"
        target = f"{page_class}.{handler_name}" if page_class else handler_name

        x_name = self._extract_x_name(element, XamlNamespaceMap())
        element_id = x_name if x_name else element_tag

        edges.append(
            ParsedEdge(
                source_name=source,
                target_name=target,
                edge_type="event_handler",
                source_location=(line, 0),
                metadata={
                    "event": event_name,
                    "handler": handler_name,
                    "element": element_id,
                    "element_type": element_tag,
                },
            )
        )

    def _extract_markup_extensions(
        self,
        element: ET.Element,
        attr_name: str,
        attr_value: str,
        edges: list[ParsedEdge],
        page_class: str | None,
        element_tag: str,
        line: int,
    ) -> None:
        """Extract edges from markup extension syntax in attribute values.

        Handles: {Binding ...}, {StaticResource ...}, {DynamicResource ...},
        {TemplateBinding ...}

        Args:
            element: The element containing the attribute.
            attr_name: Name of the attribute.
            attr_value: Value containing potential markup extension.
            edges: List to append edges to.
            page_class: The page's x:Class for the source.
            element_tag: Tag name of the element.
            line: Line number.
        """
        source = f"{page_class}.xaml" if page_class else "unknown.xaml"
        x_name = self._extract_x_name(element, XamlNamespaceMap())
        element_id = x_name if x_name else element_tag

        # Extract {Binding ...}
        binding_match = BINDING_PATTERN.search(attr_value)
        if binding_match:
            binding_content = binding_match.group(1).strip()
            binding_info = self._parse_binding_content(binding_content)

            # Create binding edge
            path = binding_info.get("Path") or binding_info.get("_default", "")
            if path:
                edges.append(
                    ParsedEdge(
                        source_name=source,
                        target_name=path,
                        edge_type="binding",
                        source_location=(line, 0),
                        metadata={
                            "attribute": attr_name,
                            "path": path,
                            "element": element_id,
                            "element_type": element_tag,
                            "binding_info": binding_info,
                        },
                    )
                )

            # Check for Command binding specifically
            if attr_name == "Command" or "Command" in binding_info:
                command_path = binding_info.get("Command") or path
                edges.append(
                    ParsedEdge(
                        source_name=source,
                        target_name=command_path,
                        edge_type="command",
                        source_location=(line, 0),
                        metadata={
                            "attribute": attr_name,
                            "command": command_path,
                            "element": element_id,
                            "element_type": element_tag,
                        },
                    )
                )

        # Extract {StaticResource ...}
        static_match = STATIC_RESOURCE_PATTERN.search(attr_value)
        if static_match:
            resource_key = static_match.group(1).strip()
            edges.append(
                ParsedEdge(
                    source_name=source,
                    target_name=resource_key,
                    edge_type="resource_ref",
                    source_location=(line, 0),
                    metadata={
                        "attribute": attr_name,
                        "resource_key": resource_key,
                        "resource_type": "static",
                        "element": element_id,
                        "element_type": element_tag,
                    },
                )
            )

        # Extract {DynamicResource ...}
        dynamic_match = DYNAMIC_RESOURCE_PATTERN.search(attr_value)
        if dynamic_match:
            resource_key = dynamic_match.group(1).strip()
            edges.append(
                ParsedEdge(
                    source_name=source,
                    target_name=resource_key,
                    edge_type="resource_ref",
                    source_location=(line, 0),
                    metadata={
                        "attribute": attr_name,
                        "resource_key": resource_key,
                        "resource_type": "dynamic",
                        "element": element_id,
                        "element_type": element_tag,
                    },
                )
            )

        # Extract {TemplateBinding ...}
        template_match = TEMPLATE_BINDING_PATTERN.search(attr_value)
        if template_match:
            property_name = template_match.group(1).strip()
            edges.append(
                ParsedEdge(
                    source_name=source,
                    target_name=property_name,
                    edge_type="template_binding",
                    source_location=(line, 0),
                    metadata={
                        "attribute": attr_name,
                        "property": property_name,
                        "element": element_id,
                        "element_type": element_tag,
                    },
                )
            )

    def _parse_binding_content(self, content: str) -> dict[str, str]:
        """Parse the content inside a {Binding ...} expression.

        Handles formats like:
        - {Binding PropertyName}
        - {Binding Path=PropertyName}
        - {Binding Path=PropertyName, Mode=TwoWay}
        - {Binding Items[0].Name}

        Args:
            content: The content inside {Binding ...} without the braces.

        Returns:
            Dictionary of binding properties.
        """
        result: dict[str, str] = {}

        if not content:
            return result

        # Split by comma, but be careful of nested braces
        parts = self._split_binding_parts(content)

        for i, part in enumerate(parts):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                result[key.strip()] = value.strip()
            elif i == 0 and part:
                # First positional argument is the Path
                result["_default"] = part
                result["Path"] = part

        return result

    def _split_binding_parts(self, content: str) -> list[str]:
        """Split binding content by commas, respecting nested braces.

        Args:
            content: Binding content string.

        Returns:
            List of parts split by commas.
        """
        parts: list[str] = []
        current = ""
        brace_depth = 0

        for char in content:
            if char == "{":
                brace_depth += 1
                current += char
            elif char == "}":
                brace_depth -= 1
                current += char
            elif char == "," and brace_depth == 0:
                parts.append(current)
                current = ""
            else:
                current += char

        if current:
            parts.append(current)

        return parts

    def extract_controls(
        self, file_path: Path | str, content: str | None = None
    ) -> list[dict[str, Any]]:
        """Extract a list of all UI controls in the XAML file.

        This is a convenience method for getting control inventory.

        Args:
            file_path: Path to the XAML file.
            content: Optional XAML content.

        Returns:
            List of control dictionaries with type, name, attributes.
        """
        file_path = Path(file_path)
        controls: list[dict[str, Any]] = []

        if content is None:
            content = file_path.read_text(encoding="utf-8")

        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return controls

        self._extract_controls_recursive(root, controls)
        return controls

    def _extract_controls_recursive(
        self, element: ET.Element, controls: list[dict[str, Any]]
    ) -> None:
        """Recursively extract control information."""
        tag = self._get_local_tag(element.tag)
        namespace = self._get_namespace(element.tag)

        # Get x:Name if present
        x_name = None
        for ns in X_NAMESPACE_PREFIXES:
            x_name = element.get(f"{{{ns}}}Name")
            if x_name:
                break
        if not x_name:
            x_name = element.get("Name")

        # Collect relevant attributes (excluding xmlns and x: namespace attrs)
        attributes: dict[str, str] = {}
        for attr, value in element.attrib.items():
            attr_local = self._get_local_attr(attr)
            if not attr.startswith("xmlns") and attr_local not in ("Class", "Name", "Key"):
                attributes[attr_local] = value

        controls.append({
            "type": tag,
            "namespace": namespace,
            "name": x_name,
            "attributes": attributes,
        })

        for child in element:
            self._extract_controls_recursive(child, controls)
