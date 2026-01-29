"""OmniSharp protocol types for LSP communication.

This module defines Pydantic models for OmniSharp's HTTP/stdio API endpoints,
including /v2/codestructure and /findusages.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Point(BaseModel):
    """A point in a source file (line and column)."""

    line: int = Field(alias="Line", description="0-indexed line number")
    column: int = Field(alias="Column", description="0-indexed column number")

    model_config = {"populate_by_name": True}


class Range(BaseModel):
    """A range in a source file (start and end points)."""

    start: Point = Field(alias="Start")
    end: Point = Field(alias="End")

    model_config = {"populate_by_name": True}


class Location(BaseModel):
    """A location in a source file (file path and range)."""

    file_name: str = Field(alias="FileName")
    range: Range = Field(alias="Range")

    model_config = {"populate_by_name": True}


class CodeElement(BaseModel):
    """A code element from OmniSharp's /v2/codestructure response.

    Represents a symbol in the code (class, method, property, etc.) with
    its structural information and optional children for nested elements.
    """

    kind: str = Field(
        alias="Kind", description="Element kind (class, method, property, etc.)"
    )
    name: str = Field(alias="Name", description="Element name/identifier")
    display_name: str = Field(
        alias="DisplayName", description="Human-readable display name"
    )
    children: list[CodeElement] | None = Field(
        default=None, alias="Children", description="Nested child elements"
    )
    ranges: dict[str, Range] | None = Field(
        default=None,
        alias="Ranges",
        description="Named ranges (full, name, attributes, etc.)",
    )
    properties: dict[str, Any] | None = Field(
        default=None,
        alias="Properties",
        description="Additional properties (accessibility, modifiers, etc.)",
    )

    model_config = {"populate_by_name": True}


class CodeStructureRequest(BaseModel):
    """Request for /v2/codestructure endpoint."""

    file_name: str = Field(alias="FileName", description="Path to the file to analyse")

    model_config = {"populate_by_name": True}


class CodeStructureResponse(BaseModel):
    """Response from /v2/codestructure endpoint."""

    elements: list[CodeElement] | None = Field(
        default=None, alias="Elements", description="Top-level code elements"
    )

    model_config = {"populate_by_name": True}


class FindUsagesRequest(BaseModel):
    """Request for /findusages endpoint."""

    file_name: str = Field(alias="FileName", description="Path to the file")
    line: int = Field(alias="Line", description="0-indexed line number")
    column: int = Field(alias="Column", description="0-indexed column number")
    only_this_file: bool = Field(
        default=False,
        alias="OnlyThisFile",
        description="Limit search to this file only",
    )
    exclude_definition: bool = Field(
        default=True,
        alias="ExcludeDefinition",
        description="Exclude the definition from results",
    )

    model_config = {"populate_by_name": True}


class QuickFix(BaseModel):
    """A usage location from /findusages response.

    OmniSharp returns usages as QuickFix objects containing file location
    and contextual text.
    """

    file_name: str = Field(alias="FileName", description="Path to the file")
    line: int = Field(alias="Line", description="0-indexed start line")
    column: int = Field(alias="Column", description="0-indexed start column")
    end_line: int = Field(alias="EndLine", description="0-indexed end line")
    end_column: int = Field(alias="EndColumn", description="0-indexed end column")
    text: str = Field(alias="Text", description="Context text (line content)")
    projects: list[str] | None = Field(
        default=None, alias="Projects", description="Projects containing this usage"
    )

    model_config = {"populate_by_name": True}


class QuickFixResponse(BaseModel):
    """Response from /findusages endpoint."""

    quick_fixes: list[QuickFix] | None = Field(
        default=None, alias="QuickFixes", description="Found usages"
    )

    model_config = {"populate_by_name": True}


class OmniSharpRequest(BaseModel):
    """Base OmniSharp stdio request wrapper.

    OmniSharp stdio protocol wraps requests with sequence number and command.
    """

    seq: int = Field(description="Sequence number for request/response matching")
    command: str = Field(description="Endpoint command (e.g., '/v2/codestructure')")
    arguments: dict[str, Any] | None = Field(
        default=None, description="Request arguments"
    )
    type_: str = Field(default="request", alias="Type")

    model_config = {"populate_by_name": True}


class OmniSharpResponse(BaseModel):
    """Base OmniSharp stdio response wrapper.

    OmniSharp stdio protocol wraps responses with sequence number, success flag,
    and optional error message.
    """

    request_seq: int = Field(
        alias="Request_seq", description="Sequence number of the request"
    )
    command: str = Field(alias="Command", description="Endpoint command")
    running: bool = Field(alias="Running", description="Whether server is still running")
    success: bool = Field(alias="Success", description="Whether request succeeded")
    message: str | None = Field(
        default=None, alias="Message", description="Error message if failed"
    )
    body: Any = Field(
        default=None, alias="Body", description="Response payload (type varies by endpoint)"
    )
    type_: str = Field(alias="Type", description="Response type")

    model_config = {"populate_by_name": True}


class GotoDefinitionRequest(BaseModel):
    """Request for /v2/gotodefinition endpoint."""

    file_name: str = Field(alias="FileName", description="Path to the file")
    line: int = Field(alias="Line", description="0-indexed line number")
    column: int = Field(alias="Column", description="0-indexed column number")
    want_metadata: bool = Field(
        default=False,
        alias="WantMetadata",
        description="Include metadata in response",
    )

    model_config = {"populate_by_name": True}


class GotoDefinitionResponse(BaseModel):
    """Response from /v2/gotodefinition endpoint."""

    definitions: list[Location] | None = Field(
        default=None, alias="Definitions", description="Definition locations"
    )

    model_config = {"populate_by_name": True}
