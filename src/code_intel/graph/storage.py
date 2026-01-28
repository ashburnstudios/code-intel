"""SQLite storage layer for the code graph."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from code_intel.graph.schema import (
    CodeGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    Location,
    NodeKind,
)

# Schema version for migration support
SCHEMA_VERSION = 1

# SQL statements for schema creation
_CREATE_SCHEMA = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Nodes table: stores code symbols
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    file_path TEXT NOT NULL,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    signature TEXT,
    docstring TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Edges table: stores relationships between nodes
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    location_file TEXT,
    location_start_line INTEGER,
    location_start_column INTEGER,
    location_end_line INTEGER,
    location_end_column INTEGER,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_nodes_repo ON nodes(repo_path);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_qualified_name ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
"""


class GraphStorage:
    """SQLite-backed storage for code graphs.

    Provides persistent storage for code graph nodes and edges with
    efficient querying capabilities.

    Example:
        storage = GraphStorage(Path("project/.code-intel.db"))
        storage.create_node(node)
        callers = storage.get_edges_to(node_id, edge_type=EdgeKind.CALLS)
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialise the storage.

        Args:
            db_path: Path to the SQLite database file. If None, uses
                     an in-memory database (useful for testing).
        """
        self._is_memory = db_path is None
        if self._is_memory:
            self._db_path = ":memory:"
            # For in-memory databases, maintain a persistent connection
            # since each new connection gets a fresh database
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys = ON")
        else:
            self._db_path = str(Path(db_path).resolve())
            self._persistent_conn = None

        self._initialise_schema()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with proper configuration."""
        if self._persistent_conn is not None:
            # Use the persistent connection for in-memory databases
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            except Exception:
                self._persistent_conn.rollback()
                raise
        else:
            # Create a new connection for file-based databases
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _initialise_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript(_CREATE_SCHEMA)

            # Check and update schema version
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            current_version = row["version"] if row else 0

            if current_version < SCHEMA_VERSION:
                self._run_migrations(conn, current_version, SCHEMA_VERSION)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

    def _run_migrations(
        self, conn: sqlite3.Connection, from_version: int, to_version: int
    ) -> None:
        """Run schema migrations between versions.

        Args:
            conn: Database connection.
            from_version: Current schema version.
            to_version: Target schema version.
        """
        # Future migrations will be added here
        # Example:
        # if from_version < 2 and to_version >= 2:
        #     conn.execute("ALTER TABLE nodes ADD COLUMN language TEXT")
        pass

    def create_node(self, node: GraphNode, repo_path: str) -> None:
        """Insert or update a node in the database.

        Args:
            node: GraphNode to store.
            repo_path: Repository root path for scoping.
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO nodes (
                    id, repo_path, file_path, node_type, name, qualified_name,
                    start_line, start_column, end_line, end_column,
                    signature, docstring, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    repo_path,
                    node.location.file_path,
                    node.kind.value,
                    node.name,
                    node.qualified_name,
                    node.location.start_line,
                    node.location.start_column,
                    node.location.end_line,
                    node.location.end_column,
                    node.signature,
                    node.docstring,
                    json.dumps(node.metadata) if node.metadata else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def create_edge(self, edge: GraphEdge) -> int:
        """Insert an edge into the database.

        Args:
            edge: GraphEdge to store.

        Returns:
            The ID of the created edge.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO edges (
                    source_id, target_id, edge_type,
                    location_file, location_start_line, location_start_column,
                    location_end_line, location_end_column, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.source_id,
                    edge.target_id,
                    edge.kind.value,
                    edge.location.file_path if edge.location else None,
                    edge.location.start_line if edge.location else None,
                    edge.location.start_column if edge.location else None,
                    edge.location.end_line if edge.location else None,
                    edge.location.end_column if edge.location else None,
                    json.dumps(edge.metadata) if edge.metadata else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return cursor.lastrowid or 0

    def get_node(self, node_id: str) -> GraphNode | None:
        """Retrieve a node by its ID.

        Args:
            node_id: Unique identifier of the node.

        Returns:
            GraphNode if found, None otherwise.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
            row = cursor.fetchone()
            return self._row_to_node(row) if row else None

    def get_nodes_by_name(
        self,
        name: str,
        repo_path: str | None = None,
        node_type: NodeKind | None = None,
    ) -> list[GraphNode]:
        """Find nodes by symbol name.

        Args:
            name: Symbol name to search for.
            repo_path: Optional repository path to scope the search.
            node_type: Optional node type filter.

        Returns:
            List of matching GraphNode objects.
        """
        query = "SELECT * FROM nodes WHERE name = ?"
        params: list[str] = [name]

        if repo_path:
            query += " AND repo_path = ?"
            params.append(repo_path)

        if node_type:
            query += " AND node_type = ?"
            params.append(node_type.value)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_nodes_by_file(self, file_path: str, repo_path: str) -> list[GraphNode]:
        """Get all nodes in a specific file.

        Args:
            file_path: Path to the source file.
            repo_path: Repository root path.

        Returns:
            List of GraphNode objects in the file.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM nodes WHERE file_path = ? AND repo_path = ?",
                (file_path, repo_path),
            )
            return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_edges_from(
        self, node_id: str, edge_type: EdgeKind | None = None
    ) -> list[GraphEdge]:
        """Get all edges originating from a node.

        Args:
            node_id: Source node ID.
            edge_type: Optional filter by edge type.

        Returns:
            List of GraphEdge objects.
        """
        query = "SELECT * FROM edges WHERE source_id = ?"
        params: list[str] = [node_id]

        if edge_type:
            query += " AND edge_type = ?"
            params.append(edge_type.value)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_edge(row) for row in cursor.fetchall()]

    def get_edges_to(
        self, node_id: str, edge_type: EdgeKind | None = None
    ) -> list[GraphEdge]:
        """Get all edges pointing to a node.

        Args:
            node_id: Target node ID.
            edge_type: Optional filter by edge type.

        Returns:
            List of GraphEdge objects.
        """
        query = "SELECT * FROM edges WHERE target_id = ?"
        params: list[str] = [node_id]

        if edge_type:
            query += " AND edge_type = ?"
            params.append(edge_type.value)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_edge(row) for row in cursor.fetchall()]

    def clear_repo(self, repo_path: str) -> int:
        """Remove all data for a repository (for re-indexing).

        Args:
            repo_path: Repository root path to clear.

        Returns:
            Number of nodes deleted.
        """
        with self._get_connection() as conn:
            # Get count before deletion
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM nodes WHERE repo_path = ?", (repo_path,)
            )
            count = cursor.fetchone()["count"]

            # Delete nodes (edges are cascaded due to foreign key)
            conn.execute("DELETE FROM nodes WHERE repo_path = ?", (repo_path,))

            return count

    def clear_file(self, file_path: str, repo_path: str) -> int:
        """Remove all data for a specific file (for incremental re-indexing).

        Args:
            file_path: Path to the source file.
            repo_path: Repository root path.

        Returns:
            Number of nodes deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM nodes WHERE file_path = ? AND repo_path = ?",
                (file_path, repo_path),
            )
            count = cursor.fetchone()["count"]

            conn.execute(
                "DELETE FROM nodes WHERE file_path = ? AND repo_path = ?",
                (file_path, repo_path),
            )

            return count

    def get_all_nodes(self, repo_path: str | None = None) -> list[GraphNode]:
        """Get all nodes, optionally filtered by repository.

        Args:
            repo_path: Optional repository path filter.

        Returns:
            List of all GraphNode objects.
        """
        if repo_path:
            query = "SELECT * FROM nodes WHERE repo_path = ?"
            params: tuple[str, ...] = (repo_path,)
        else:
            query = "SELECT * FROM nodes"
            params = ()

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_all_edges(self, repo_path: str | None = None) -> list[GraphEdge]:
        """Get all edges, optionally filtered by repository.

        Args:
            repo_path: Optional repository path filter.

        Returns:
            List of all GraphEdge objects.
        """
        if repo_path:
            query = """
                SELECT e.* FROM edges e
                JOIN nodes n ON e.source_id = n.id
                WHERE n.repo_path = ?
            """
            params: tuple[str, ...] = (repo_path,)
        else:
            query = "SELECT * FROM edges"
            params = ()

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_edge(row) for row in cursor.fetchall()]

    def to_code_graph(self, repo_path: str | None = None) -> CodeGraph:
        """Export storage contents to an in-memory CodeGraph.

        Args:
            repo_path: Optional repository path filter.

        Returns:
            CodeGraph containing all nodes and edges.
        """
        return CodeGraph(
            nodes=self.get_all_nodes(repo_path),
            edges=self.get_all_edges(repo_path),
        )

    def from_code_graph(self, graph: CodeGraph, repo_path: str) -> None:
        """Import a CodeGraph into storage.

        Args:
            graph: CodeGraph to import.
            repo_path: Repository path for the imported data.
        """
        for node in graph.nodes:
            self.create_node(node, repo_path)
        for edge in graph.edges:
            self.create_edge(edge)

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        """Convert a database row to a GraphNode."""
        return GraphNode(
            id=row["id"],
            name=row["name"],
            kind=NodeKind(row["node_type"]),
            location=Location(
                file_path=row["file_path"],
                start_line=row["start_line"],
                start_column=row["start_column"],
                end_line=row["end_line"],
                end_column=row["end_column"],
            ),
            qualified_name=row["qualified_name"],
            signature=row["signature"],
            docstring=row["docstring"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _row_to_edge(self, row: sqlite3.Row) -> GraphEdge:
        """Convert a database row to a GraphEdge."""
        location = None
        if row["location_file"]:
            location = Location(
                file_path=row["location_file"],
                start_line=row["location_start_line"],
                start_column=row["location_start_column"],
                end_line=row["location_end_line"],
                end_column=row["location_end_column"],
            )

        return GraphEdge(
            source_id=row["source_id"],
            target_id=row["target_id"],
            kind=EdgeKind(row["edge_type"]),
            location=location,
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
