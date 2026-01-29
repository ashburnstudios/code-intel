"""Tests for LSP protocol types."""

import pytest
from code_intel.lsp.protocol import (
    CodeElement,
    CodeStructureRequest,
    CodeStructureResponse,
    FindUsagesRequest,
    GotoDefinitionRequest,
    GotoDefinitionResponse,
    Location,
    OmniSharpRequest,
    OmniSharpResponse,
    Point,
    QuickFix,
    QuickFixResponse,
    Range,
)


class TestPoint:
    """Tests for Point model."""

    def test_create_point(self):
        """Test creating a Point."""
        point = Point(line=10, column=5)
        assert point.line == 10
        assert point.column == 5

    def test_point_zero_indexed(self):
        """Test that points can be zero-indexed."""
        point = Point(line=0, column=0)
        assert point.line == 0
        assert point.column == 0


class TestRange:
    """Tests for Range model."""

    def test_create_range(self):
        """Test creating a Range."""
        range_obj = Range(
            start=Point(line=10, column=0),
            end=Point(line=15, column=20),
        )
        assert range_obj.start.line == 10
        assert range_obj.end.line == 15


class TestCodeElement:
    """Tests for CodeElement model."""

    def test_create_simple_element(self):
        """Test creating a simple CodeElement."""
        element = CodeElement(
            kind="class",
            name="MyClass",
            display_name="MyClass",
        )
        assert element.kind == "class"
        assert element.name == "MyClass"
        assert element.display_name == "MyClass"
        assert element.children is None
        assert element.ranges is None

    def test_element_with_children(self):
        """Test CodeElement with children."""
        child = CodeElement(
            kind="method",
            name="MyMethod",
            display_name="MyMethod()",
        )
        parent = CodeElement(
            kind="class",
            name="MyClass",
            display_name="MyClass",
            children=[child],
        )
        assert parent.children is not None
        assert len(parent.children) == 1
        assert parent.children[0].name == "MyMethod"

    def test_element_with_ranges(self):
        """Test CodeElement with ranges."""
        element = CodeElement(
            kind="method",
            name="Method",
            display_name="Method()",
            ranges={
                "full": Range(
                    start=Point(line=5, column=0),
                    end=Point(line=10, column=5),
                ),
                "name": Range(
                    start=Point(line=5, column=12),
                    end=Point(line=5, column=18),
                ),
            },
        )
        assert element.ranges is not None
        assert "full" in element.ranges
        assert element.ranges["full"].start.line == 5

    def test_element_from_alias(self):
        """Test creating CodeElement from OmniSharp JSON format."""
        data = {
            "Kind": "class",
            "Name": "TestClass",
            "DisplayName": "TestClass",
            "Children": [
                {
                    "Kind": "method",
                    "Name": "TestMethod",
                    "DisplayName": "TestMethod()",
                }
            ],
            "Properties": {
                "accessibility": "public",
                "static": False,
            },
        }
        element = CodeElement.model_validate(data)
        assert element.kind == "class"
        assert element.name == "TestClass"
        assert element.children is not None
        assert len(element.children) == 1
        assert element.properties == {"accessibility": "public", "static": False}


class TestCodeStructureRequest:
    """Tests for CodeStructureRequest model."""

    def test_create_request(self):
        """Test creating a CodeStructureRequest."""
        request = CodeStructureRequest(file_name="/path/to/file.cs")
        assert request.file_name == "/path/to/file.cs"

    def test_serialise_with_alias(self):
        """Test serialising with OmniSharp field names."""
        request = CodeStructureRequest(file_name="/path/to/file.cs")
        data = request.model_dump(by_alias=True)
        assert "FileName" in data
        assert data["FileName"] == "/path/to/file.cs"


class TestCodeStructureResponse:
    """Tests for CodeStructureResponse model."""

    def test_empty_response(self):
        """Test creating an empty response."""
        response = CodeStructureResponse()
        assert response.elements is None

    def test_response_with_elements(self):
        """Test creating a response with elements."""
        element = CodeElement(
            kind="class",
            name="TestClass",
            display_name="TestClass",
        )
        response = CodeStructureResponse(elements=[element])
        assert response.elements is not None
        assert len(response.elements) == 1


class TestFindUsagesRequest:
    """Tests for FindUsagesRequest model."""

    def test_create_request(self):
        """Test creating a FindUsagesRequest."""
        request = FindUsagesRequest(
            file_name="/path/to/file.cs",
            line=10,
            column=5,
        )
        assert request.file_name == "/path/to/file.cs"
        assert request.line == 10
        assert request.column == 5
        assert request.exclude_definition is True  # Default

    def test_request_with_options(self):
        """Test creating a request with options."""
        request = FindUsagesRequest(
            file_name="/path/to/file.cs",
            line=10,
            column=5,
            only_this_file=True,
            exclude_definition=False,
        )
        assert request.only_this_file is True
        assert request.exclude_definition is False


class TestQuickFix:
    """Tests for QuickFix model."""

    def test_create_quick_fix(self):
        """Test creating a QuickFix."""
        fix = QuickFix(
            file_name="/path/to/file.cs",
            line=10,
            column=5,
            end_line=10,
            end_column=15,
            text="method.Call()",
        )
        assert fix.file_name == "/path/to/file.cs"
        assert fix.line == 10
        assert fix.text == "method.Call()"

    def test_from_omnisharp_format(self):
        """Test parsing from OmniSharp JSON format."""
        data = {
            "FileName": "/path/to/file.cs",
            "Line": 10,
            "Column": 5,
            "EndLine": 10,
            "EndColumn": 15,
            "Text": "    var result = method.Call();",
            "Projects": ["MyProject"],
        }
        fix = QuickFix.model_validate(data)
        assert fix.file_name == "/path/to/file.cs"
        assert fix.line == 10
        assert fix.projects == ["MyProject"]


class TestQuickFixResponse:
    """Tests for QuickFixResponse model."""

    def test_empty_response(self):
        """Test creating an empty response."""
        response = QuickFixResponse()
        assert response.quick_fixes is None

    def test_response_with_fixes(self):
        """Test creating a response with fixes."""
        fix = QuickFix(
            file_name="/path/to/file.cs",
            line=10,
            column=5,
            end_line=10,
            end_column=15,
            text="method.Call()",
        )
        response = QuickFixResponse(quick_fixes=[fix])
        assert response.quick_fixes is not None
        assert len(response.quick_fixes) == 1


class TestOmniSharpRequest:
    """Tests for OmniSharpRequest wrapper."""

    def test_create_request(self):
        """Test creating an OmniSharp request."""
        request = OmniSharpRequest(
            seq=1,
            command="/v2/codestructure",
            arguments={"FileName": "/path/to/file.cs"},
        )
        assert request.seq == 1
        assert request.command == "/v2/codestructure"
        assert request.arguments == {"FileName": "/path/to/file.cs"}

    def test_serialise_for_stdio(self):
        """Test serialising request for stdio transport."""
        request = OmniSharpRequest(
            seq=1,
            command="/v2/codestructure",
            arguments={"FileName": "/path/to/file.cs"},
        )
        data = request.model_dump(by_alias=True, exclude_none=True)
        assert data["seq"] == 1
        assert data["command"] == "/v2/codestructure"
        assert "Type" in data
        assert data["Type"] == "request"


class TestOmniSharpResponse:
    """Tests for OmniSharpResponse wrapper."""

    def test_parse_success_response(self):
        """Test parsing a successful response."""
        data = {
            "Request_seq": 1,
            "Command": "/v2/codestructure",
            "Running": True,
            "Success": True,
            "Body": {"Elements": []},
            "Type": "response",
        }
        response = OmniSharpResponse.model_validate(data)
        assert response.request_seq == 1
        assert response.success is True
        assert response.body == {"Elements": []}

    def test_parse_error_response(self):
        """Test parsing an error response."""
        data = {
            "Request_seq": 1,
            "Command": "/v2/codestructure",
            "Running": True,
            "Success": False,
            "Message": "File not found",
            "Type": "response",
        }
        response = OmniSharpResponse.model_validate(data)
        assert response.success is False
        assert response.message == "File not found"


class TestGotoDefinitionRequest:
    """Tests for GotoDefinitionRequest model."""

    def test_create_request(self):
        """Test creating a GotoDefinitionRequest."""
        request = GotoDefinitionRequest(
            file_name="/path/to/file.cs",
            line=10,
            column=5,
        )
        assert request.file_name == "/path/to/file.cs"
        assert request.line == 10
        assert request.column == 5
        assert request.want_metadata is False  # Default


class TestGotoDefinitionResponse:
    """Tests for GotoDefinitionResponse model."""

    def test_empty_response(self):
        """Test creating an empty response."""
        response = GotoDefinitionResponse()
        assert response.definitions is None
