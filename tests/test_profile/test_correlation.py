"""Tests for frame-to-symbol correlation functionality."""

import pytest

from code_intel.graph.schema import GraphNode, Location, NodeKind
from code_intel.graph.storage import GraphStorage
from code_intel.profile.correlation import (
    DotNetFrameParser,
    FrameLanguage,
    FrameNormaliser,
    JavaScriptFrameParser,
    MatchConfidence,
    NormalisedFrame,
    ProfileCorrelator,
    PythonFrameParser,
    SymbolMatcher,
)
from code_intel.profile.schema import Frame, FunctionStats, Profile, ProfileType, ValueUnit
from code_intel.profile.storage import ProfileStorage


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def graph_storage() -> GraphStorage:
    """Create an in-memory graph storage."""
    return GraphStorage()


@pytest.fixture
def profile_storage() -> ProfileStorage:
    """Create an in-memory profile storage."""
    return ProfileStorage()


@pytest.fixture
def normaliser() -> FrameNormaliser:
    """Create a frame normaliser."""
    return FrameNormaliser()


@pytest.fixture
def indexed_graph(graph_storage: GraphStorage) -> GraphStorage:
    """Create a graph storage with sample nodes indexed."""
    repo_path = "/test/repo"

    # Python function
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/utils.py:process_data:10",
            name="process_data",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="/test/repo/src/utils.py",
                start_line=10,
                start_column=0,
                end_line=25,
                end_column=0,
            ),
            qualified_name="utils.process_data",
        ),
        repo_path,
    )

    # Python class method
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/services.py:UserService.get_user:30",
            name="get_user",
            kind=NodeKind.METHOD,
            location=Location(
                file_path="/test/repo/src/services.py",
                start_line=30,
                start_column=4,
                end_line=45,
                end_column=0,
            ),
            qualified_name="services.UserService.get_user",
        ),
        repo_path,
    )

    # .NET style method
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/Controllers/HomeController.cs:Index:15",
            name="Index",
            kind=NodeKind.METHOD,
            location=Location(
                file_path="/test/repo/src/Controllers/HomeController.cs",
                start_line=15,
                start_column=8,
                end_line=30,
                end_column=0,
            ),
            qualified_name="MyApp.Controllers.HomeController.Index",
        ),
        repo_path,
    )

    # JavaScript function
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/handler.js:handleRequest:5",
            name="handleRequest",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="/test/repo/src/handler.js",
                start_line=5,
                start_column=0,
                end_line=20,
                end_column=0,
            ),
            qualified_name="handler.handleRequest",
        ),
        repo_path,
    )

    # JavaScript class method
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/api.js:ApiClient.fetch:50",
            name="fetch",
            kind=NodeKind.METHOD,
            location=Location(
                file_path="/test/repo/src/api.js",
                start_line=50,
                start_column=4,
                end_line=70,
                end_column=0,
            ),
            qualified_name="api.ApiClient.fetch",
        ),
        repo_path,
    )

    # Another function with same name in different file
    graph_storage.create_node(
        GraphNode(
            id="/test/repo/src/other.py:process_data:5",
            name="process_data",
            kind=NodeKind.FUNCTION,
            location=Location(
                file_path="/test/repo/src/other.py",
                start_line=5,
                start_column=0,
                end_line=15,
                end_column=0,
            ),
            qualified_name="other.process_data",
        ),
        repo_path,
    )

    return graph_storage


# =============================================================================
# NormalisedFrame Tests
# =============================================================================


class TestNormalisedFrame:
    """Tests for NormalisedFrame dataclass."""

    def test_creation_minimal(self) -> None:
        """Test creating a NormalisedFrame with minimal fields."""
        frame = NormalisedFrame(
            original_name="test_func",
            function_name="test_func",
        )
        assert frame.original_name == "test_func"
        assert frame.function_name == "test_func"
        assert frame.class_name is None
        assert frame.language == FrameLanguage.UNKNOWN

    def test_creation_full(self) -> None:
        """Test creating a NormalisedFrame with all fields."""
        frame = NormalisedFrame(
            original_name="MyApp.Services.UserService.GetUser(int)",
            function_name="GetUser",
            class_name="UserService",
            namespace="MyApp.Services",
            qualified_name="MyApp.Services.UserService.GetUser",
            file_path="/src/services.cs",
            line_number=42,
            column=8,
            language=FrameLanguage.DOTNET,
            metadata={"is_generic": False},
        )
        assert frame.function_name == "GetUser"
        assert frame.class_name == "UserService"
        assert frame.namespace == "MyApp.Services"
        assert frame.language == FrameLanguage.DOTNET


# =============================================================================
# .NET Frame Parser Tests
# =============================================================================


class TestDotNetFrameParser:
    """Tests for .NET frame parsing."""

    @pytest.fixture
    def parser(self) -> DotNetFrameParser:
        return DotNetFrameParser()

    def test_can_parse_module_prefix(self, parser: DotNetFrameParser) -> None:
        """Test detection of module!symbol format."""
        assert parser.can_parse("mscorlib!System.String.Concat")
        assert parser.can_parse("MyApp!MyNamespace.MyClass.MyMethod")

    def test_can_parse_nested_class(self, parser: DotNetFrameParser) -> None:
        """Test detection of nested class format."""
        assert parser.can_parse("MyClass+NestedClass.Method")

    def test_can_parse_generic(self, parser: DotNetFrameParser) -> None:
        """Test detection of generic type format."""
        assert parser.can_parse("List`1.Add")
        assert parser.can_parse("Dictionary`2.TryGetValue")

    def test_can_parse_typical_dotnet(self, parser: DotNetFrameParser) -> None:
        """Test detection of typical .NET naming patterns."""
        assert parser.can_parse("MyApp.Services.UserService.GetUser")
        assert parser.can_parse("System.Web.Http.ApiController.ExecuteAsync")

    def test_parse_simple_method(self, parser: DotNetFrameParser) -> None:
        """Test parsing a simple Namespace.Class.Method format."""
        result = parser.parse("MyApp.Services.UserService.GetUser")

        assert result.function_name == "GetUser"
        assert result.class_name == "UserService"
        assert result.namespace == "MyApp.Services"
        assert result.qualified_name == "MyApp.Services.UserService.GetUser"
        assert result.language == FrameLanguage.DOTNET

    def test_parse_with_args(self, parser: DotNetFrameParser) -> None:
        """Test parsing a method with argument types."""
        result = parser.parse("MyApp.UserService.GetUser(System.Int32, System.String)")

        assert result.function_name == "GetUser"
        assert result.class_name == "UserService"
        # Args should be stripped from qualified name
        assert result.qualified_name == "MyApp.UserService.GetUser"

    def test_parse_with_module_prefix(self, parser: DotNetFrameParser) -> None:
        """Test parsing module!symbol format."""
        result = parser.parse("MyModule!MyApp.Services.UserService.GetUser")

        assert result.function_name == "GetUser"
        assert result.class_name == "UserService"
        assert result.namespace == "MyApp.Services"
        assert result.metadata.get("module") == "MyModule"

    def test_parse_generic_type(self, parser: DotNetFrameParser) -> None:
        """Test parsing generic type methods."""
        result = parser.parse("System.Collections.Generic.List`1.Add")

        assert result.function_name == "Add"
        assert result.class_name == "List"  # Generic marker stripped
        assert result.metadata.get("is_generic") is True

    def test_parse_nested_class(self, parser: DotNetFrameParser) -> None:
        """Test parsing nested class methods."""
        result = parser.parse("MyApp.OuterClass+InnerClass.Method")

        assert result.function_name == "Method"
        assert result.class_name == "InnerClass"

    def test_parse_class_only(self, parser: DotNetFrameParser) -> None:
        """Test parsing Class.Method without namespace."""
        result = parser.parse("UserService.GetUser")

        assert result.function_name == "GetUser"
        assert result.class_name == "UserService"
        assert result.namespace is None

    def test_parse_preserves_file_and_line(self, parser: DotNetFrameParser) -> None:
        """Test that file and line info is preserved."""
        result = parser.parse(
            "MyApp.UserService.GetUser",
            file="/src/services.cs",
            line=42,
        )

        assert result.file_path == "/src/services.cs"
        assert result.line_number == 42


# =============================================================================
# Python Frame Parser Tests
# =============================================================================


class TestPythonFrameParser:
    """Tests for Python frame parsing."""

    @pytest.fixture
    def parser(self) -> PythonFrameParser:
        return PythonFrameParser()

    def test_can_parse_cprofile_format(self, parser: PythonFrameParser) -> None:
        """Test detection of cProfile format."""
        assert parser.can_parse("<module>:1(process_data)")
        assert parser.can_parse("/path/to/module.py:45(my_function)")

    def test_can_parse_file_line_format(self, parser: PythonFrameParser) -> None:
        """Test detection of file:line format."""
        assert parser.can_parse("/path/to/script.py:123")
        assert parser.can_parse("script.py:45:some_func")

    def test_can_parse_synthetic_names(self, parser: PythonFrameParser) -> None:
        """Test detection of synthetic names."""
        assert parser.can_parse("<module>")
        assert parser.can_parse("<listcomp>")
        assert parser.can_parse("<lambda>")

    def test_can_parse_snake_case(self, parser: PythonFrameParser) -> None:
        """Test detection of Python snake_case patterns."""
        assert parser.can_parse("my_module.my_function")
        assert parser.can_parse("process_data")

    def test_parse_cprofile_format(self, parser: PythonFrameParser) -> None:
        """Test parsing cProfile format."""
        result = parser.parse("<module>:45(process_data)")

        assert result.function_name == "process_data"
        assert result.line_number == 45
        assert result.language == FrameLanguage.PYTHON

    def test_parse_cprofile_with_file(self, parser: PythonFrameParser) -> None:
        """Test parsing cProfile format with file path."""
        result = parser.parse("/path/to/utils.py:123(helper)")

        assert result.function_name == "helper"
        assert result.file_path == "/path/to/utils.py"
        assert result.line_number == 123

    def test_parse_simple_function(self, parser: PythonFrameParser) -> None:
        """Test parsing simple function name."""
        result = parser.parse("process_data")

        assert result.function_name == "process_data"
        assert result.qualified_name == "process_data"
        assert result.class_name is None

    def test_parse_module_function(self, parser: PythonFrameParser) -> None:
        """Test parsing module.function format."""
        result = parser.parse("myapp.utils.process_data")

        assert result.function_name == "process_data"
        assert result.namespace == "myapp.utils"
        assert result.qualified_name == "myapp.utils.process_data"

    def test_parse_class_method(self, parser: PythonFrameParser) -> None:
        """Test parsing Class.method format."""
        result = parser.parse("UserService.get_user")

        assert result.function_name == "get_user"
        assert result.class_name == "UserService"

    def test_parse_module_class_method(self, parser: PythonFrameParser) -> None:
        """Test parsing module.Class.method format."""
        result = parser.parse("myapp.services.UserService.get_user")

        assert result.function_name == "get_user"
        assert result.class_name == "UserService"
        assert result.namespace == "myapp.services"

    def test_parse_synthetic_lambda(self, parser: PythonFrameParser) -> None:
        """Test parsing lambda synthetic name."""
        result = parser.parse("<lambda>")

        assert result.function_name == "<lambda>"
        assert result.metadata.get("is_synthetic") is True

    def test_parse_synthetic_listcomp(self, parser: PythonFrameParser) -> None:
        """Test parsing list comprehension synthetic name."""
        result = parser.parse("<listcomp>")

        assert result.function_name == "<listcomp>"
        assert result.metadata.get("is_synthetic") is True


# =============================================================================
# JavaScript Frame Parser Tests
# =============================================================================


class TestJavaScriptFrameParser:
    """Tests for JavaScript/Node.js frame parsing."""

    @pytest.fixture
    def parser(self) -> JavaScriptFrameParser:
        return JavaScriptFrameParser()

    def test_can_parse_nodejs_format(self, parser: JavaScriptFrameParser) -> None:
        """Test detection of Node.js format."""
        assert parser.can_parse("processRequest (src/handler.js:123:5)")
        assert parser.can_parse("handleError (/app/utils.js:45:10)")

    def test_can_parse_location_only(self, parser: JavaScriptFrameParser) -> None:
        """Test detection of location-only format."""
        assert parser.can_parse("(src/anonymous.js:10:1)")

    def test_can_parse_prototype(self, parser: JavaScriptFrameParser) -> None:
        """Test detection of prototype method format."""
        assert parser.can_parse("MyClass.prototype.myMethod")

    def test_can_parse_anonymous(self, parser: JavaScriptFrameParser) -> None:
        """Test detection of anonymous patterns."""
        assert parser.can_parse("(anonymous)")
        assert parser.can_parse("<anonymous>")

    def test_parse_nodejs_format(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing Node.js format."""
        result = parser.parse("processRequest (src/handler.js:123:5)")

        assert result.function_name == "processRequest"
        assert result.file_path == "src/handler.js"
        assert result.line_number == 123
        assert result.column == 5
        assert result.language == FrameLanguage.JAVASCRIPT

    def test_parse_location_only(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing location-only format."""
        result = parser.parse("(src/anonymous.js:10:1)")

        assert result.function_name == "<anonymous>"
        assert result.file_path == "src/anonymous.js"
        assert result.line_number == 10
        assert result.column == 1
        assert result.metadata.get("is_anonymous") is True

    def test_parse_prototype_method(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing prototype method format."""
        result = parser.parse("ApiClient.prototype.fetch")

        assert result.function_name == "fetch"
        assert result.class_name == "ApiClient"
        assert result.qualified_name == "ApiClient.fetch"

    def test_parse_class_method(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing Class.method format."""
        result = parser.parse("UserService.getUser")

        assert result.function_name == "getUser"
        assert result.class_name == "UserService"

    def test_parse_simple_function(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing simple function name."""
        result = parser.parse("handleRequest")

        assert result.function_name == "handleRequest"
        assert result.qualified_name == "handleRequest"

    def test_parse_anonymous(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing anonymous function."""
        result = parser.parse("(anonymous)")

        assert result.function_name == "<anonymous>"
        assert result.metadata.get("is_anonymous") is True

    def test_parse_nodejs_with_class(self, parser: JavaScriptFrameParser) -> None:
        """Test parsing Node.js format with class."""
        result = parser.parse("ApiClient.fetch (src/api.js:50:4)")

        assert result.function_name == "fetch"
        assert result.class_name == "ApiClient"
        assert result.file_path == "src/api.js"
        assert result.line_number == 50


# =============================================================================
# FrameNormaliser Tests
# =============================================================================


class TestFrameNormaliser:
    """Tests for the FrameNormaliser class."""

    def test_auto_detect_dotnet(self, normaliser: FrameNormaliser) -> None:
        """Test auto-detection of .NET frames."""
        result = normaliser.normalise("MyApp.Services.UserService.GetUser(int)")

        assert result.language == FrameLanguage.DOTNET
        assert result.function_name == "GetUser"

    def test_auto_detect_python(self, normaliser: FrameNormaliser) -> None:
        """Test auto-detection of Python frames."""
        result = normaliser.normalise("<module>:45(process_data)")

        assert result.language == FrameLanguage.PYTHON
        assert result.function_name == "process_data"

    def test_auto_detect_javascript(self, normaliser: FrameNormaliser) -> None:
        """Test auto-detection of JavaScript frames."""
        result = normaliser.normalise("handleRequest (src/handler.js:10:5)")

        assert result.language == FrameLanguage.JAVASCRIPT
        assert result.function_name == "handleRequest"

    def test_explicit_language_hint(self, normaliser: FrameNormaliser) -> None:
        """Test using explicit language hint."""
        # This could be ambiguous without hint
        result = normaliser.normalise(
            "MyClass.MyMethod",
            language=FrameLanguage.PYTHON,
        )

        assert result.language == FrameLanguage.PYTHON

    def test_fallback_for_unknown(self, normaliser: FrameNormaliser) -> None:
        """Test fallback parsing for unknown format."""
        # Use a format that won't be detected by any parser
        # (no underscores = not Python, no dots = not .NET, no JS patterns)
        result = normaliser.normalise("SomeRandomFormat123")

        assert result.language == FrameLanguage.UNKNOWN
        assert result.function_name == "SomeRandomFormat123"

    def test_preserves_file_and_line(self, normaliser: FrameNormaliser) -> None:
        """Test that file and line info is preserved through normalisation."""
        result = normaliser.normalise(
            "process_data",
            file="/src/utils.py",
            line=42,
        )

        assert result.file_path == "/src/utils.py"
        assert result.line_number == 42


# =============================================================================
# SymbolMatcher Tests
# =============================================================================


class TestSymbolMatcher:
    """Tests for the SymbolMatcher class."""

    def test_match_by_location_exact(self, indexed_graph: GraphStorage) -> None:
        """Test matching by exact file and line."""
        matcher = SymbolMatcher(indexed_graph)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise(
            "process_data",
            file="/test/repo/src/utils.py",
            line=10,  # Exact start line
        )

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "process_data"
        assert result.confidence == MatchConfidence.LOCATION.value
        assert "line" in result.match_reason.lower()

    def test_match_by_location_in_range(self, indexed_graph: GraphStorage) -> None:
        """Test matching when line is within function range."""
        matcher = SymbolMatcher(indexed_graph)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise(
            "process_data",
            file="/test/repo/src/utils.py",
            line=15,  # Within range (10-25)
        )

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "process_data"
        assert result.confidence == MatchConfidence.LOCATION.value

    def test_match_by_qualified_name(self, indexed_graph: GraphStorage) -> None:
        """Test matching by qualified name."""
        matcher = SymbolMatcher(indexed_graph)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise("services.UserService.get_user")

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "get_user"
        assert result.confidence == MatchConfidence.QUALIFIED_NAME.value

    def test_match_by_name_and_file(self, indexed_graph: GraphStorage) -> None:
        """Test matching by function name within a file."""
        matcher = SymbolMatcher(indexed_graph)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise(
            "handleRequest",
            file="/test/repo/src/handler.js",
        )

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "handleRequest"
        assert result.confidence == MatchConfidence.NAME_AND_FILE.value

    def test_match_by_name_and_class(self, indexed_graph: GraphStorage) -> None:
        """Test matching by function name with class context."""
        matcher = SymbolMatcher(indexed_graph)

        # This frame has class context but no file
        # The qualified_name "ApiClient.fetch" will match as a suffix of "api.ApiClient.fetch"
        frame = NormalisedFrame(
            original_name="ApiClient.fetch",
            function_name="fetch",
            class_name="ApiClient",
            qualified_name="ApiClient.fetch",
            language=FrameLanguage.JAVASCRIPT,
        )

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "fetch"
        # Matches via qualified name suffix, which has higher confidence than NAME_AND_CLASS
        assert result.confidence >= MatchConfidence.NAME_AND_CLASS.value

    def test_match_by_name_only_unique(self, indexed_graph: GraphStorage) -> None:
        """Test matching by unique function name."""
        matcher = SymbolMatcher(indexed_graph)

        # Create a frame with NO qualified name to force name-only matching
        frame = NormalisedFrame(
            original_name="unique_test_func",
            function_name="unique_test_func",
            language=FrameLanguage.UNKNOWN,
        )

        # Add a unique symbol to match
        indexed_graph.create_node(
            GraphNode(
                id="/test/repo/src/unique.py:unique_test_func:100",
                name="unique_test_func",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="/test/repo/src/unique.py",
                    start_line=100,
                    start_column=0,
                    end_line=110,
                    end_column=0,
                ),
                qualified_name="unique.unique_test_func",
            ),
            "/test/repo",
        )

        result = matcher.match(frame, "/test/repo")

        assert result is not None
        assert result.symbol_name == "unique_test_func"
        assert result.confidence == MatchConfidence.NAME_ONLY.value

    def test_match_by_name_multiple_with_low_confidence(
        self, indexed_graph: GraphStorage
    ) -> None:
        """Test that multiple matches with same name return lower confidence."""
        matcher = SymbolMatcher(indexed_graph)

        # Add two symbols with identical names and no qualified name pattern
        for i, path in enumerate(["first.py", "second.py"]):
            indexed_graph.create_node(
                GraphNode(
                    id=f"/test/repo/src/{path}:ambiguous_func:{(i + 1) * 10}",
                    name="ambiguous_func",
                    kind=NodeKind.FUNCTION,
                    location=Location(
                        file_path=f"/test/repo/src/{path}",
                        start_line=(i + 1) * 10,  # Line numbers must be >= 1
                        start_column=0,
                        end_line=(i + 1) * 10 + 10,
                        end_column=0,
                    ),
                    # Same qualified prefix - can't disambiguate
                    qualified_name="module.ambiguous_func",
                ),
                "/test/repo",
            )

        # Frame with just the function name - can't disambiguate
        frame = NormalisedFrame(
            original_name="ambiguous_func",
            function_name="ambiguous_func",
            language=FrameLanguage.UNKNOWN,
        )

        result = matcher.match(frame, "/test/repo")

        # Should still return a result but with fuzzy confidence
        assert result is not None
        assert result.symbol_name == "ambiguous_func"
        assert result.confidence == MatchConfidence.FUZZY.value
        assert "guess" in result.match_reason.lower()

    def test_no_match_returns_none(self, indexed_graph: GraphStorage) -> None:
        """Test that non-matching frames return None."""
        matcher = SymbolMatcher(indexed_graph)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise("nonexistent_function_xyz")

        result = matcher.match(frame, "/test/repo")

        assert result is None


# =============================================================================
# ProfileCorrelator Tests
# =============================================================================


class TestProfileCorrelator:
    """Tests for the ProfileCorrelator class."""

    def test_correlate_frame_with_cache(
        self,
        indexed_graph: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test correlating a single frame with caching."""
        correlator = ProfileCorrelator(indexed_graph, profile_storage)

        # First call should compute and cache
        mapping = correlator.correlate_frame(
            "utils.process_data",
            repo_path="/test/repo",
            file="/test/repo/src/utils.py",
            line=10,
        )

        assert mapping is not None
        assert mapping.symbol_id is not None
        assert mapping.confidence >= MatchConfidence.LOCATION.value

        # Second call should use cache
        cached = profile_storage.get_symbol_mapping("utils.process_data")
        assert cached is not None
        assert cached.symbol_id == mapping.symbol_id

    def test_correlate_frame_below_threshold(
        self,
        indexed_graph: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test that low confidence matches are filtered by threshold."""
        # Create a new storage instance without the pre-indexed symbols
        fresh_graph = GraphStorage()
        fresh_profile = ProfileStorage()

        # Add symbols that will produce truly ambiguous matches
        # Key: both have qualified names that DON'T end with the simple function name
        fresh_graph.create_node(
            GraphNode(
                id="/test/repo/src/a.py:SomeClass.do_work:10",
                name="do_work",
                kind=NodeKind.METHOD,
                location=Location(
                    file_path="/test/repo/src/a.py",
                    start_line=10,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
                qualified_name="pkga.SomeClass.do_work",
            ),
            "/test/repo",
        )
        fresh_graph.create_node(
            GraphNode(
                id="/test/repo/src/b.py:OtherClass.do_work:10",
                name="do_work",
                kind=NodeKind.METHOD,
                location=Location(
                    file_path="/test/repo/src/b.py",
                    start_line=10,
                    start_column=0,
                    end_line=20,
                    end_column=0,
                ),
                qualified_name="pkgb.OtherClass.do_work",
            ),
            "/test/repo",
        )

        correlator = ProfileCorrelator(fresh_graph, fresh_profile)

        # Frame has a DIFFERENT qualified name pattern that won't suffix-match
        # This simulates a profile frame like "MyClass.do_work" that doesn't
        # match either "pkga.SomeClass.do_work" or "pkgb.OtherClass.do_work"
        mapping = correlator.correlate_frame(
            "DifferentClass.do_work",  # Qualified name won't match anything
            repo_path="/test/repo",
            min_confidence=0.7,  # Higher than fuzzy (0.6)
        )

        # Should be None because:
        # 1. No location match (no file/line)
        # 2. No qualified name match (DifferentClass != SomeClass/OtherClass)
        # 3. Name-only match would have FUZZY confidence (0.6) which is < 0.7
        assert mapping is None

    def test_correlate_profile(
        self,
        indexed_graph: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test correlating all frames in a profile."""
        # Create a test profile
        profile = Profile(
            id="test-correlation-profile",
            name="Correlation Test",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            frames=[
                Frame(
                    name="utils.process_data",
                    file="/test/repo/src/utils.py",
                    line=10,
                ),
                Frame(
                    name="services.UserService.get_user",
                    file="/test/repo/src/services.py",
                    line=30,
                ),
                Frame(
                    name="nonexistent_func",
                ),
            ],
            function_stats=[
                FunctionStats(
                    profile_id="test-correlation-profile",
                    frame_index=0,
                    name="utils.process_data",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
                FunctionStats(
                    profile_id="test-correlation-profile",
                    frame_index=1,
                    name="services.UserService.get_user",
                    self_weight=50,
                    total_weight=50,
                    call_count=1,
                ),
                FunctionStats(
                    profile_id="test-correlation-profile",
                    frame_index=2,
                    name="nonexistent_func",
                    self_weight=25,
                    total_weight=25,
                    call_count=1,
                ),
            ],
        )
        profile_storage.create_profile(profile)

        correlator = ProfileCorrelator(indexed_graph, profile_storage)

        # Correlate all frames
        count = correlator.correlate_profile(
            "test-correlation-profile",
            repo_path="/test/repo",
        )

        # Should correlate 2 out of 3 frames
        assert count == 2

        # Verify correlations were saved
        updated_profile = profile_storage.get_profile("test-correlation-profile")
        assert updated_profile is not None

        stats_by_idx = {s.frame_index: s for s in updated_profile.function_stats}
        assert stats_by_idx[0].symbol_id is not None
        assert stats_by_idx[1].symbol_id is not None
        assert stats_by_idx[2].symbol_id is None  # No match

    def test_get_unmapped_frames(
        self,
        indexed_graph: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test getting list of unmapped frames."""
        # Create a profile with unmapped frames
        profile = Profile(
            id="unmapped-test",
            name="Unmapped Test",
            profile_type=ProfileType.SAMPLED,
            unit=ValueUnit.MILLISECONDS,
            function_stats=[
                FunctionStats(
                    profile_id="unmapped-test",
                    frame_index=0,
                    name="mapped_func",
                    self_weight=100,
                    total_weight=100,
                    call_count=1,
                ),
                FunctionStats(
                    profile_id="unmapped-test",
                    frame_index=1,
                    name="unmapped_func",
                    self_weight=50,
                    total_weight=50,
                    call_count=1,
                ),
            ],
        )
        profile_storage.create_profile(profile)

        # Map one frame
        profile_storage.set_symbol_mapping("mapped_func", "some-symbol-id")

        correlator = ProfileCorrelator(indexed_graph, profile_storage)
        unmapped = correlator.get_unmapped_frames("unmapped-test")

        assert unmapped == ["unmapped_func"]

    def test_clear_cache(
        self,
        indexed_graph: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test clearing the mapping cache."""
        # Add some mappings
        profile_storage.set_symbol_mapping("func1", "symbol1")
        profile_storage.set_symbol_mapping("func2", "symbol2")

        correlator = ProfileCorrelator(indexed_graph, profile_storage)
        cleared = correlator.clear_cache()

        assert cleared == 2
        assert profile_storage.get_symbol_mapping("func1") is None
        assert profile_storage.get_symbol_mapping("func2") is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestCorrelationIntegration:
    """Integration tests for the full correlation workflow."""

    def test_dotnet_frame_correlation(
        self,
        graph_storage: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test correlating a typical .NET frame."""
        # Index a .NET symbol
        graph_storage.create_node(
            GraphNode(
                id="/repo/src/UserService.cs:GetUser:42",
                name="GetUser",
                kind=NodeKind.METHOD,
                location=Location(
                    file_path="/repo/src/UserService.cs",
                    start_line=42,
                    start_column=8,
                    end_line=60,
                    end_column=0,
                ),
                qualified_name="MyApp.Services.UserService.GetUser",
            ),
            "/repo",
        )

        correlator = ProfileCorrelator(graph_storage, profile_storage)

        # Correlate a typical .NET frame name
        mapping = correlator.correlate_frame(
            "MyApp.Services.UserService.GetUser(System.Int32)",
            repo_path="/repo",
        )

        assert mapping is not None
        assert mapping.symbol_id == "/repo/src/UserService.cs:GetUser:42"
        assert mapping.confidence >= MatchConfidence.QUALIFIED_NAME.value

    def test_python_frame_correlation(
        self,
        graph_storage: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test correlating a typical Python frame."""
        # Index a Python symbol
        graph_storage.create_node(
            GraphNode(
                id="/repo/src/utils.py:process_data:15",
                name="process_data",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="/repo/src/utils.py",
                    start_line=15,
                    start_column=0,
                    end_line=30,
                    end_column=0,
                ),
                qualified_name="utils.process_data",
            ),
            "/repo",
        )

        correlator = ProfileCorrelator(graph_storage, profile_storage)

        # Correlate a cProfile-style frame
        mapping = correlator.correlate_frame(
            "/repo/src/utils.py:15(process_data)",
            repo_path="/repo",
        )

        assert mapping is not None
        assert mapping.symbol_id == "/repo/src/utils.py:process_data:15"
        assert mapping.confidence >= MatchConfidence.LOCATION.value

    def test_nodejs_frame_correlation(
        self,
        graph_storage: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Test correlating a typical Node.js frame."""
        # Index a JavaScript symbol
        graph_storage.create_node(
            GraphNode(
                id="/repo/src/api.js:fetchData:25",
                name="fetchData",
                kind=NodeKind.FUNCTION,
                location=Location(
                    file_path="/repo/src/api.js",
                    start_line=25,
                    start_column=0,
                    end_line=40,
                    end_column=0,
                ),
                qualified_name="api.fetchData",
            ),
            "/repo",
        )

        correlator = ProfileCorrelator(graph_storage, profile_storage)

        # Correlate a Node.js-style frame
        mapping = correlator.correlate_frame(
            "fetchData (/repo/src/api.js:25:0)",
            repo_path="/repo",
        )

        assert mapping is not None
        assert mapping.symbol_id == "/repo/src/api.js:fetchData:25"
        assert mapping.confidence >= MatchConfidence.LOCATION.value
