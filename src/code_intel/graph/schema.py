"""Schema definitions for the code graph."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    """Types of nodes in the code graph."""

    # Structural
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"

    # Variables
    VARIABLE = "variable"
    PARAMETER = "parameter"
    CONSTANT = "constant"

    # Types
    TYPE_ALIAS = "type_alias"
    INTERFACE = "interface"
    ENUM = "enum"
    ENUM_MEMBER = "enum_member"

    # Other
    IMPORT = "import"
    DECORATOR = "decorator"


class EdgeKind(str, Enum):
    """Types of relationships between nodes."""

    # Structural relationships
    CONTAINS = "contains"  # Parent contains child (module->class, class->method)
    INHERITS = "inherits"  # Class inheritance
    IMPLEMENTS = "implements"  # Interface implementation

    # Usage relationships
    CALLS = "calls"  # Function/method calls another
    REFERENCES = "references"  # Symbol reference
    IMPORTS = "imports"  # Import relationship
    INSTANTIATES = "instantiates"  # Object creation

    # Type relationships
    RETURNS = "returns"  # Function return type
    PARAMETER_TYPE = "parameter_type"  # Parameter type annotation
    TYPE_OF = "type_of"  # Variable type


class Location(BaseModel):
    """Source code location."""

    file_path: str = Field(description="Path to the source file")
    start_line: int = Field(ge=1, description="Starting line number (1-indexed)")
    start_column: int = Field(ge=0, description="Starting column (0-indexed)")
    end_line: int = Field(ge=1, description="Ending line number (1-indexed)")
    end_column: int = Field(ge=0, description="Ending column (0-indexed)")


class GraphNode(BaseModel):
    """A node in the code graph representing a code symbol."""

    id: str = Field(description="Unique identifier for the node")
    name: str = Field(description="Symbol name")
    kind: NodeKind = Field(description="Type of symbol")
    location: Location = Field(description="Source location")
    qualified_name: str | None = Field(
        default=None, description="Fully qualified name (e.g., module.Class.method)"
    )
    signature: str | None = Field(
        default=None, description="Function/method signature"
    )
    docstring: str | None = Field(default=None, description="Documentation string")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional language-specific metadata"
    )


class GraphEdge(BaseModel):
    """An edge in the code graph representing a relationship."""

    source_id: str = Field(description="ID of the source node")
    target_id: str = Field(description="ID of the target node")
    kind: EdgeKind = Field(description="Type of relationship")
    location: Location | None = Field(
        default=None, description="Location where the relationship is established"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional relationship metadata"
    )


class CodeGraph(BaseModel):
    """Complete code graph for a codebase or file."""

    nodes: list[GraphNode] = Field(default_factory=list, description="All nodes")
    edges: list[GraphEdge] = Field(default_factory=list, description="All edges")

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)

    def get_node(self, node_id: str) -> GraphNode | None:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_edges_from(self, node_id: str) -> list[GraphEdge]:
        """Get all edges originating from a node."""
        return [e for e in self.edges if e.source_id == node_id]

    def get_edges_to(self, node_id: str) -> list[GraphEdge]:
        """Get all edges pointing to a node."""
        return [e for e in self.edges if e.target_id == node_id]
