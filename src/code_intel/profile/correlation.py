"""Frame-to-symbol correlation for mapping profile frames to code-intel symbols.

This module provides:
- FrameNormaliser: Parses frame names from different profiler formats
- SymbolMatcher: Queries the code-intel graph to find matching symbols
- Confidence scoring for fuzzy matches
- Caching of resolved mappings
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from code_intel.graph.storage import GraphStorage
    from code_intel.profile.schema import FrameSymbolMapping
    from code_intel.profile.storage import ProfileStorage


class FrameLanguage(str, Enum):
    """Detected or specified language/runtime for a frame."""

    DOTNET = "dotnet"
    PYTHON = "python"
    JAVASCRIPT = "javascript"  # Includes TypeScript at runtime
    UNKNOWN = "unknown"


@dataclass
class NormalisedFrame:
    """A frame normalised for symbol lookup.

    Contains extracted components from a raw frame name that can be used
    to match against code-intel symbols.
    """

    original_name: str
    """The original frame name as it appeared in the profile."""

    function_name: str
    """The extracted function/method name (without class or namespace)."""

    class_name: str | None = None
    """The class name if this is a method."""

    namespace: str | None = None
    """The namespace/module path (e.g., 'MyApp.Services' or 'myapp.services')."""

    qualified_name: str | None = None
    """Fully qualified name for exact matching (e.g., 'MyApp.Services.UserService.GetUser')."""

    file_path: str | None = None
    """Source file path if present in the frame."""

    line_number: int | None = None
    """Line number if present in the frame."""

    column: int | None = None
    """Column number if present in the frame."""

    language: FrameLanguage = FrameLanguage.UNKNOWN
    """Detected or specified language/runtime."""

    metadata: dict = field(default_factory=dict)
    """Additional extracted metadata (e.g., generic type params, module name)."""


class FrameParser(ABC):
    """Abstract base class for language-specific frame parsers."""

    @property
    @abstractmethod
    def language(self) -> FrameLanguage:
        """The language this parser handles."""

    @abstractmethod
    def can_parse(self, frame_name: str) -> bool:
        """Check if this parser can handle the given frame name.

        Args:
            frame_name: The raw frame name from a profile.

        Returns:
            True if this parser recognises the format.
        """

    @abstractmethod
    def parse(self, frame_name: str, file: str | None = None, line: int | None = None) -> NormalisedFrame:
        """Parse a frame name into normalised components.

        Args:
            frame_name: The raw frame name from a profile.
            file: Optional file path from the frame.
            line: Optional line number from the frame.

        Returns:
            A NormalisedFrame with extracted components.
        """


class DotNetFrameParser(FrameParser):
    """.NET frame name parser.

    Handles formats:
    - Namespace.Class.Method(args)
    - Namespace.Class.Method
    - module!Namespace.Class.Method
    - Class.Method
    - GenericClass`1.Method (generic types)
    - Namespace.Class+NestedClass.Method (nested classes)
    - <Module>.Method (module-level methods)
    """

    # Pattern for module prefix: "module!..."
    MODULE_PREFIX_PATTERN = re.compile(r"^([^!]+)!(.+)$")

    # Pattern for nested classes: Class+NestedClass
    NESTED_CLASS_PATTERN = re.compile(r"\+")

    # Pattern for generic type indicators: `1, `2, etc.
    GENERIC_PATTERN = re.compile(r"`\d+")

    # Pattern for arguments in method signatures
    ARGS_PATTERN = re.compile(r"\([^)]*\)$")

    # Pattern for <Module> or similar synthetic names
    SYNTHETIC_NAME_PATTERN = re.compile(r"^<[^>]+>$")

    @property
    def language(self) -> FrameLanguage:
        return FrameLanguage.DOTNET

    def can_parse(self, frame_name: str) -> bool:
        """Check if this looks like a .NET frame.

        Indicators:
        - Contains ! (module prefix)
        - Contains + (nested class)
        - Contains ` (generic type)
        - Contains (args) typical of .NET signatures
        - Uses PascalCase naming convention
        """
        # Strong indicators
        if "!" in frame_name:
            return True
        if "+" in frame_name:
            return True
        if "`" in frame_name:
            return True

        # Check for typical .NET method signature: Namespace.Class.Method(type, type)
        if self.ARGS_PATTERN.search(frame_name):
            # Check for type names in args (System.String, int, etc.)
            args_match = self.ARGS_PATTERN.search(frame_name)
            if args_match:
                args = args_match.group()
                # .NET typically has type names or keywords in args
                if any(kw in args for kw in ["System.", "Int32", "String", "Boolean", "Object"]):
                    return True

        # Check for PascalCase with dots (typical .NET namespacing)
        parts = frame_name.split(".")
        if len(parts) >= 2:
            # Check if parts follow PascalCase (first letter uppercase)
            pascal_count = sum(1 for p in parts if p and p[0].isupper())
            # If most parts are PascalCase, likely .NET
            if pascal_count >= len(parts) * 0.75:
                return True

        return False

    def parse(self, frame_name: str, file: str | None = None, line: int | None = None) -> NormalisedFrame:
        """Parse a .NET frame name."""
        original = frame_name
        module_name: str | None = None

        # Extract module prefix if present
        module_match = self.MODULE_PREFIX_PATTERN.match(frame_name)
        if module_match:
            module_name = module_match.group(1)
            frame_name = module_match.group(2)

        # Strip arguments for matching
        frame_name = self.ARGS_PATTERN.sub("", frame_name)

        # Handle generic type indicators for display but strip for matching
        clean_name = self.GENERIC_PATTERN.sub("", frame_name)

        # Split into components
        parts = clean_name.split(".")

        if not parts:
            return NormalisedFrame(
                original_name=original,
                function_name=frame_name,
                language=FrameLanguage.DOTNET,
                file_path=file,
                line_number=line,
            )

        # Last part is the method name
        function_name = parts[-1]

        # Handle nested classes (Class+Nested)
        if "+" in function_name:
            nested_parts = function_name.split("+")
            function_name = nested_parts[-1]

        # Determine class and namespace
        class_name: str | None = None
        namespace: str | None = None

        if len(parts) >= 2:
            # Second-to-last is typically the class
            class_part = parts[-2]
            # Handle nested classes
            if "+" in class_part:
                nested_parts = class_part.split("+")
                class_name = nested_parts[-1]
            else:
                class_name = class_part

            if len(parts) >= 3:
                namespace = ".".join(parts[:-2])

        # Build qualified name (without generic markers for matching)
        qualified_parts = []
        if namespace:
            qualified_parts.append(namespace)
        if class_name:
            qualified_parts.append(class_name)
        qualified_parts.append(function_name)
        qualified_name = ".".join(qualified_parts)

        metadata = {}
        if module_name:
            metadata["module"] = module_name
        if "`" in frame_name:
            metadata["is_generic"] = True

        return NormalisedFrame(
            original_name=original,
            function_name=function_name,
            class_name=class_name,
            namespace=namespace,
            qualified_name=qualified_name,
            file_path=file,
            line_number=line,
            language=FrameLanguage.DOTNET,
            metadata=metadata,
        )


class PythonFrameParser(FrameParser):
    """Python frame name parser.

    Handles formats:
    - module.function
    - module.Class.method
    - <module>:lineno(function)
    - function (bare name)
    - <listcomp>, <dictcomp>, etc. (comprehensions)
    - <lambda>
    - Class.method
    """

    # Pattern for cProfile-style frames: <module>:lineno(function)
    CPROFILE_PATTERN = re.compile(r"^(.+?):(\d+)\((.+)\)$")

    # Pattern for file:lineno format
    FILE_LINE_PATTERN = re.compile(r"^(.+\.py):(\d+)(?::(.+))?$")

    # Pattern for synthetic names
    SYNTHETIC_NAMES = {"<module>", "<listcomp>", "<dictcomp>", "<setcomp>", "<genexpr>", "<lambda>"}

    @property
    def language(self) -> FrameLanguage:
        return FrameLanguage.PYTHON

    def can_parse(self, frame_name: str) -> bool:
        """Check if this looks like a Python frame.

        Indicators:
        - Contains :lineno( pattern (cProfile)
        - Contains .py: pattern
        - Contains <module>, <lambda>, etc.
        - Uses snake_case naming
        """
        # Strong indicators
        if self.CPROFILE_PATTERN.match(frame_name):
            return True
        if self.FILE_LINE_PATTERN.match(frame_name):
            return True
        if any(syn in frame_name for syn in self.SYNTHETIC_NAMES):
            return True

        # Check for snake_case (more common in Python)
        if "_" in frame_name and not frame_name.startswith("<"):
            # Likely Python if has underscores and no strong .NET indicators
            if "`" not in frame_name and "!" not in frame_name:
                return True

        return False

    def parse(self, frame_name: str, file: str | None = None, line: int | None = None) -> NormalisedFrame:
        """Parse a Python frame name."""
        original = frame_name

        # Try cProfile format first: <module>:lineno(function)
        cprofile_match = self.CPROFILE_PATTERN.match(frame_name)
        if cprofile_match:
            file_or_module = cprofile_match.group(1)
            line_num = int(cprofile_match.group(2))
            func_name = cprofile_match.group(3)

            # Determine if it's a file path or module name
            if file_or_module.endswith(".py"):
                file = file_or_module
            else:
                # It's a module path
                file = file or None

            return NormalisedFrame(
                original_name=original,
                function_name=func_name,
                qualified_name=func_name,
                file_path=file,
                line_number=line_num if line is None else line,
                language=FrameLanguage.PYTHON,
            )

        # Try file:lineno:function format
        file_line_match = self.FILE_LINE_PATTERN.match(frame_name)
        if file_line_match:
            file = file_line_match.group(1)
            line_num = int(file_line_match.group(2))
            func_name = file_line_match.group(3) or "<unknown>"

            return NormalisedFrame(
                original_name=original,
                function_name=func_name,
                qualified_name=func_name,
                file_path=file,
                line_number=line_num if line is None else line,
                language=FrameLanguage.PYTHON,
            )

        # Handle synthetic names
        if frame_name in self.SYNTHETIC_NAMES:
            return NormalisedFrame(
                original_name=original,
                function_name=frame_name,
                qualified_name=frame_name,
                file_path=file,
                line_number=line,
                language=FrameLanguage.PYTHON,
                metadata={"is_synthetic": True},
            )

        # Standard dotted name: module.Class.method or just function
        parts = frame_name.split(".")

        if len(parts) == 1:
            # Just a function name
            return NormalisedFrame(
                original_name=original,
                function_name=parts[0],
                qualified_name=parts[0],
                file_path=file,
                line_number=line,
                language=FrameLanguage.PYTHON,
            )

        # Last part is function/method name
        function_name = parts[-1]

        # Determine if second-to-last is a class (capitalized) or module (lowercase)
        class_name: str | None = None
        namespace: str | None = None

        if len(parts) >= 2:
            potential_class = parts[-2]
            # Python convention: classes are CamelCase, modules are snake_case
            if potential_class and potential_class[0].isupper():
                class_name = potential_class
                if len(parts) >= 3:
                    namespace = ".".join(parts[:-2])
            else:
                # It's all module path
                namespace = ".".join(parts[:-1])

        return NormalisedFrame(
            original_name=original,
            function_name=function_name,
            class_name=class_name,
            namespace=namespace,
            qualified_name=frame_name,
            file_path=file,
            line_number=line,
            language=FrameLanguage.PYTHON,
        )


class JavaScriptFrameParser(FrameParser):
    """JavaScript/TypeScript/Node.js frame name parser.

    Handles formats:
    - function (file:line:col)
    - Class.prototype.method
    - Class.method
    - anonymous function patterns
    - (anonymous) or <anonymous>
    - module.exports.function
    - Object.<anonymous>
    """

    # Pattern for Node.js format: function (file:line:col)
    NODEJS_PATTERN = re.compile(r"^(.+?)\s+\((.+):(\d+):(\d+)\)$")

    # Pattern for just file location: (file:line:col)
    LOCATION_ONLY_PATTERN = re.compile(r"^\((.+):(\d+):(\d+)\)$")

    # Pattern for anonymous functions
    ANONYMOUS_PATTERNS = {"(anonymous)", "<anonymous>", "anonymous"}

    # Pattern for prototype methods: Class.prototype.method
    PROTOTYPE_PATTERN = re.compile(r"^(.+?)\.prototype\.(.+)$")

    @property
    def language(self) -> FrameLanguage:
        return FrameLanguage.JAVASCRIPT

    def can_parse(self, frame_name: str) -> bool:
        """Check if this looks like a JavaScript/Node.js frame.

        Indicators:
        - Contains (file:line:col) pattern
        - Contains .prototype.
        - Contains anonymous patterns
        - Contains .js: or .ts:
        """
        # Strong indicators
        if self.NODEJS_PATTERN.match(frame_name):
            return True
        if self.LOCATION_ONLY_PATTERN.match(frame_name):
            return True
        if ".prototype." in frame_name:
            return True
        if any(anon in frame_name.lower() for anon in self.ANONYMOUS_PATTERNS):
            return True
        if ".js:" in frame_name or ".ts:" in frame_name:
            return True
        if "module.exports" in frame_name:
            return True

        return False

    def parse(self, frame_name: str, file: str | None = None, line: int | None = None) -> NormalisedFrame:
        """Parse a JavaScript/Node.js frame name."""
        original = frame_name

        # Try Node.js format: function (file:line:col)
        nodejs_match = self.NODEJS_PATTERN.match(frame_name)
        if nodejs_match:
            func_part = nodejs_match.group(1).strip()
            file = nodejs_match.group(2)
            line_num = int(nodejs_match.group(3))
            col_num = int(nodejs_match.group(4))

            # Parse the function part
            return self._parse_function_part(
                original, func_part, file, line_num, col_num
            )

        # Try location-only format: (file:line:col)
        location_match = self.LOCATION_ONLY_PATTERN.match(frame_name)
        if location_match:
            file = location_match.group(1)
            line_num = int(location_match.group(2))
            col_num = int(location_match.group(3))

            return NormalisedFrame(
                original_name=original,
                function_name="<anonymous>",
                file_path=file,
                line_number=line_num,
                column=col_num,
                language=FrameLanguage.JAVASCRIPT,
                metadata={"is_anonymous": True},
            )

        # Handle prototype methods: Class.prototype.method
        prototype_match = self.PROTOTYPE_PATTERN.match(frame_name)
        if prototype_match:
            class_name = prototype_match.group(1)
            method_name = prototype_match.group(2)

            return NormalisedFrame(
                original_name=original,
                function_name=method_name,
                class_name=class_name,
                qualified_name=f"{class_name}.{method_name}",
                file_path=file,
                line_number=line,
                language=FrameLanguage.JAVASCRIPT,
            )

        # Handle anonymous patterns
        if frame_name.lower() in self.ANONYMOUS_PATTERNS or frame_name.startswith("<anonymous"):
            return NormalisedFrame(
                original_name=original,
                function_name="<anonymous>",
                file_path=file,
                line_number=line,
                language=FrameLanguage.JAVASCRIPT,
                metadata={"is_anonymous": True},
            )

        # Standard dotted name or simple function
        return self._parse_function_part(original, frame_name, file, line, None)

    def _parse_function_part(
        self,
        original: str,
        func_part: str,
        file: str | None,
        line: int | None,
        col: int | None,
    ) -> NormalisedFrame:
        """Parse the function/method part of a frame name."""
        # Handle Class.method or just method
        parts = func_part.split(".")

        if len(parts) == 1:
            return NormalisedFrame(
                original_name=original,
                function_name=parts[0],
                qualified_name=parts[0],
                file_path=file,
                line_number=line,
                column=col,
                language=FrameLanguage.JAVASCRIPT,
            )

        # Last part is the method/function
        function_name = parts[-1]

        # Check for Class.method pattern
        class_name: str | None = None
        namespace: str | None = None

        if len(parts) >= 2:
            potential_class = parts[-2]
            # Skip 'prototype' as class name
            if potential_class.lower() == "prototype" and len(parts) >= 3:
                class_name = parts[-3]
            elif potential_class[0].isupper():
                class_name = potential_class
                if len(parts) >= 3:
                    namespace = ".".join(parts[:-2])
            else:
                namespace = ".".join(parts[:-1])

        return NormalisedFrame(
            original_name=original,
            function_name=function_name,
            class_name=class_name,
            namespace=namespace,
            qualified_name=func_part,
            file_path=file,
            line_number=line,
            column=col,
            language=FrameLanguage.JAVASCRIPT,
        )


class FrameNormaliser:
    """Normalises profile frame names for symbol lookup.

    Uses language-specific parsers to extract function names, class names,
    namespaces, and other components from frame names in various formats.

    Example:
        normaliser = FrameNormaliser()

        # .NET frame
        result = normaliser.normalise("MyApp.Services.UserService.GetUser(int)")
        # result.function_name == "GetUser"
        # result.class_name == "UserService"
        # result.qualified_name == "MyApp.Services.UserService.GetUser"

        # Python frame
        result = normaliser.normalise("myapp.services.user_service:45(get_user)")
        # result.function_name == "get_user"
        # result.line_number == 45

        # Node.js frame
        result = normaliser.normalise("processRequest (src/handler.js:123:5)")
        # result.function_name == "processRequest"
        # result.file_path == "src/handler.js"
    """

    def __init__(self) -> None:
        """Initialise with default language parsers."""
        self._parsers: list[FrameParser] = [
            DotNetFrameParser(),
            PythonFrameParser(),
            JavaScriptFrameParser(),
        ]

    def register_parser(self, parser: FrameParser) -> None:
        """Register an additional language parser.

        Args:
            parser: A FrameParser instance for a specific language.
        """
        # Insert at the beginning so custom parsers take priority
        self._parsers.insert(0, parser)

    def normalise(
        self,
        frame_name: str,
        file: str | None = None,
        line: int | None = None,
        language: FrameLanguage | None = None,
    ) -> NormalisedFrame:
        """Normalise a frame name for symbol lookup.

        Args:
            frame_name: The raw frame name from a profile.
            file: Optional file path from the frame.
            line: Optional line number from the frame.
            language: Optional language hint to skip detection.

        Returns:
            A NormalisedFrame with extracted components.
        """
        # If language specified, use that parser directly
        if language is not None:
            for parser in self._parsers:
                if parser.language == language:
                    return parser.parse(frame_name, file, line)

        # Auto-detect language and use appropriate parser
        for parser in self._parsers:
            if parser.can_parse(frame_name):
                return parser.parse(frame_name, file, line)

        # Fallback: basic parsing for unknown format
        return self._fallback_parse(frame_name, file, line)

    def _fallback_parse(
        self,
        frame_name: str,
        file: str | None,
        line: int | None,
    ) -> NormalisedFrame:
        """Fallback parser for unrecognised frame formats."""
        # Strip arguments if present
        clean_name = frame_name
        if "(" in clean_name:
            clean_name = clean_name.split("(")[0]

        # Split on dots
        parts = clean_name.split(".")

        function_name = parts[-1] if parts else frame_name
        qualified_name = clean_name

        class_name: str | None = None
        namespace: str | None = None

        if len(parts) >= 2:
            # Assume second-to-last might be a class
            class_name = parts[-2]
            if len(parts) >= 3:
                namespace = ".".join(parts[:-2])

        return NormalisedFrame(
            original_name=frame_name,
            function_name=function_name,
            class_name=class_name,
            namespace=namespace,
            qualified_name=qualified_name,
            file_path=file,
            line_number=line,
            language=FrameLanguage.UNKNOWN,
        )


class MatchConfidence(float, Enum):
    """Standard confidence levels for symbol matches."""

    EXACT = 1.0
    """Exact match on qualified name and location."""

    LOCATION = 0.95
    """Match based on file and line number."""

    QUALIFIED_NAME = 0.9
    """Exact match on qualified name without location."""

    NAME_AND_FILE = 0.85
    """Match on function name within the same file."""

    NAME_AND_CLASS = 0.8
    """Match on function name with matching class name."""

    NAME_ONLY = 0.7
    """Match on function name only (may have multiple matches)."""

    FUZZY = 0.6
    """Fuzzy match (partial name match or similar)."""

    LOW = 0.5
    """Low confidence match (best effort)."""


class SymbolMatchResult(BaseModel):
    """Result of a symbol match operation."""

    symbol_id: str = Field(description="ID of the matched code graph node")
    symbol_name: str = Field(description="Name of the matched symbol")
    qualified_name: str | None = Field(default=None, description="Fully qualified name")
    file_path: str | None = Field(default=None, description="Source file path")
    line_number: int | None = Field(default=None, description="Source line number")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Match confidence (1.0 = exact, lower = fuzzy)"
    )
    match_reason: str = Field(description="Why this match was selected")


class SymbolMatcher:
    """Matches normalised frames to code-intel symbols.

    Uses multiple strategies with decreasing confidence:
    1. Exact match on file + line (confidence: 0.95)
    2. Exact match on qualified name (confidence: 0.9)
    3. Match on function name + file (confidence: 0.85)
    4. Match on function name + class (confidence: 0.8)
    5. Match on function name only (confidence: 0.7)
    6. Fuzzy match (confidence: 0.5-0.6)

    Example:
        matcher = SymbolMatcher(graph_storage)
        normaliser = FrameNormaliser()

        frame = normaliser.normalise("MyClass.MyMethod(int)", file="src/service.py", line=42)
        result = matcher.match(frame, repo_path="/path/to/repo")

        if result:
            print(f"Matched {result.symbol_name} with confidence {result.confidence}")
    """

    def __init__(self, storage: GraphStorage) -> None:
        """Initialise with a graph storage instance.

        Args:
            storage: The GraphStorage to query for symbols.
        """
        self._storage = storage

    def match(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Find the best matching symbol for a normalised frame.

        Tries multiple matching strategies in order of confidence.

        Args:
            frame: The normalised frame to match.
            repo_path: Repository path for scoping the search.

        Returns:
            SymbolMatchResult if a match is found, None otherwise.
        """
        # Strategy 1: Location-based match (highest confidence)
        if frame.file_path and frame.line_number:
            result = self._match_by_location(frame, repo_path)
            if result:
                return result

        # Strategy 2: Exact qualified name match
        if frame.qualified_name:
            result = self._match_by_qualified_name(frame, repo_path)
            if result:
                return result

        # Strategy 3: Function name + file
        if frame.file_path:
            result = self._match_by_name_and_file(frame, repo_path)
            if result:
                return result

        # Strategy 4: Function name + class
        if frame.class_name:
            result = self._match_by_name_and_class(frame, repo_path)
            if result:
                return result

        # Strategy 5: Function name only
        result = self._match_by_name_only(frame, repo_path)
        if result:
            return result

        return None

    def _match_by_location(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Match by file path and line number."""
        if not frame.file_path or not frame.line_number:
            return None

        nodes = self._storage.get_nodes_by_file(frame.file_path, repo_path)

        for node in nodes:
            # Exact line match
            if node.location.start_line == frame.line_number:
                return SymbolMatchResult(
                    symbol_id=node.id,
                    symbol_name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=node.location.file_path,
                    line_number=node.location.start_line,
                    confidence=MatchConfidence.LOCATION.value,
                    match_reason="Exact file and line match",
                )

            # Line within function range with matching name
            if (
                node.location.start_line <= frame.line_number <= node.location.end_line
                and node.name == frame.function_name
            ):
                return SymbolMatchResult(
                    symbol_id=node.id,
                    symbol_name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=node.location.file_path,
                    line_number=node.location.start_line,
                    confidence=MatchConfidence.LOCATION.value,
                    match_reason="Line within function range with name match",
                )

        return None

    def _match_by_qualified_name(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Match by fully qualified name."""
        if not frame.qualified_name:
            return None

        # Search by function name first, then filter by qualified name
        nodes = self._storage.get_nodes_by_name(frame.function_name, repo_path)

        for node in nodes:
            if node.qualified_name == frame.qualified_name:
                return SymbolMatchResult(
                    symbol_id=node.id,
                    symbol_name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=node.location.file_path,
                    line_number=node.location.start_line,
                    confidence=MatchConfidence.QUALIFIED_NAME.value,
                    match_reason="Exact qualified name match",
                )

            # Try suffix match (e.g., "Class.method" matching "module.Class.method")
            if node.qualified_name and node.qualified_name.endswith(f".{frame.qualified_name}"):
                return SymbolMatchResult(
                    symbol_id=node.id,
                    symbol_name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=node.location.file_path,
                    line_number=node.location.start_line,
                    confidence=MatchConfidence.QUALIFIED_NAME.value - 0.05,
                    match_reason="Qualified name suffix match",
                )

        return None

    def _match_by_name_and_file(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Match by function name within a specific file."""
        if not frame.file_path:
            return None

        nodes = self._storage.get_nodes_by_file(frame.file_path, repo_path)

        matches = [n for n in nodes if n.name == frame.function_name]

        if len(matches) == 1:
            node = matches[0]
            return SymbolMatchResult(
                symbol_id=node.id,
                symbol_name=node.name,
                qualified_name=node.qualified_name,
                file_path=node.location.file_path,
                line_number=node.location.start_line,
                confidence=MatchConfidence.NAME_AND_FILE.value,
                match_reason="Function name match in file",
            )

        # If multiple matches in file, try to narrow down by class
        if len(matches) > 1 and frame.class_name:
            for node in matches:
                if node.qualified_name and f".{frame.class_name}." in node.qualified_name:
                    return SymbolMatchResult(
                        symbol_id=node.id,
                        symbol_name=node.name,
                        qualified_name=node.qualified_name,
                        file_path=node.location.file_path,
                        line_number=node.location.start_line,
                        confidence=MatchConfidence.NAME_AND_FILE.value,
                        match_reason="Function name match in file with class context",
                    )

        return None

    def _match_by_name_and_class(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Match by function name with class context."""
        if not frame.class_name:
            return None

        nodes = self._storage.get_nodes_by_name(frame.function_name, repo_path)

        for node in nodes:
            if node.qualified_name:
                # Check if class name appears in qualified name
                if f".{frame.class_name}." in node.qualified_name:
                    return SymbolMatchResult(
                        symbol_id=node.id,
                        symbol_name=node.name,
                        qualified_name=node.qualified_name,
                        file_path=node.location.file_path,
                        line_number=node.location.start_line,
                        confidence=MatchConfidence.NAME_AND_CLASS.value,
                        match_reason="Function name with class context match",
                    )

                # Check if it ends with Class.method
                expected_suffix = f"{frame.class_name}.{frame.function_name}"
                if node.qualified_name.endswith(expected_suffix):
                    return SymbolMatchResult(
                        symbol_id=node.id,
                        symbol_name=node.name,
                        qualified_name=node.qualified_name,
                        file_path=node.location.file_path,
                        line_number=node.location.start_line,
                        confidence=MatchConfidence.NAME_AND_CLASS.value,
                        match_reason="Function name with class suffix match",
                    )

        return None

    def _match_by_name_only(
        self,
        frame: NormalisedFrame,
        repo_path: str,
    ) -> SymbolMatchResult | None:
        """Match by function name only (lowest confidence)."""
        nodes = self._storage.get_nodes_by_name(frame.function_name, repo_path)

        if len(nodes) == 1:
            # Unique match
            node = nodes[0]
            return SymbolMatchResult(
                symbol_id=node.id,
                symbol_name=node.name,
                qualified_name=node.qualified_name,
                file_path=node.location.file_path,
                line_number=node.location.start_line,
                confidence=MatchConfidence.NAME_ONLY.value,
                match_reason="Unique function name match",
            )

        if len(nodes) > 1:
            # Multiple matches - return first but with lower confidence
            node = nodes[0]
            return SymbolMatchResult(
                symbol_id=node.id,
                symbol_name=node.name,
                qualified_name=node.qualified_name,
                file_path=node.location.file_path,
                line_number=node.location.start_line,
                confidence=MatchConfidence.FUZZY.value,
                match_reason=f"Best guess from {len(nodes)} matches",
            )

        return None


class ProfileCorrelator:
    """High-level interface for correlating profile frames with code symbols.

    Combines FrameNormaliser, SymbolMatcher, and caching to provide
    efficient frame-to-symbol correlation.

    Example:
        from code_intel.profile.correlation import ProfileCorrelator
        from code_intel.profile.storage import ProfileStorage
        from code_intel.graph.storage import GraphStorage

        graph_storage = GraphStorage(db_path)
        profile_storage = ProfileStorage(db_path)

        correlator = ProfileCorrelator(graph_storage, profile_storage)

        # Correlate a single frame
        mapping = correlator.correlate_frame("MyClass.Method()", repo_path="/repo")

        # Correlate all frames in a profile
        count = correlator.correlate_profile(profile_id, repo_path="/repo")
    """

    def __init__(
        self,
        graph_storage: GraphStorage,
        profile_storage: ProfileStorage,
    ) -> None:
        """Initialise with storage instances.

        Args:
            graph_storage: Storage for querying code symbols.
            profile_storage: Storage for profile data and mapping cache.
        """
        self._graph_storage = graph_storage
        self._profile_storage = profile_storage
        self._normaliser = FrameNormaliser()
        self._matcher = SymbolMatcher(graph_storage)

    def correlate_frame(
        self,
        frame_name: str,
        repo_path: str,
        *,
        file: str | None = None,
        line: int | None = None,
        use_cache: bool = True,
        min_confidence: float = 0.5,
    ) -> FrameSymbolMapping | None:
        """Correlate a single frame name to a symbol.

        Args:
            frame_name: The raw frame name from a profile.
            repo_path: Repository path for scoping symbol search.
            file: Optional file path from the frame.
            line: Optional line number from the frame.
            use_cache: Whether to check/update the mapping cache.
            min_confidence: Minimum confidence to accept a match.

        Returns:
            FrameSymbolMapping if correlated, None otherwise.
        """
        # Check cache first
        if use_cache:
            cached = self._profile_storage.get_symbol_mapping(frame_name)
            if cached is not None:
                return cached

        # Normalise the frame
        normalised = self._normaliser.normalise(frame_name, file, line)

        # Find matching symbol
        result = self._matcher.match(normalised, repo_path)

        if result is None or result.confidence < min_confidence:
            # No match or below threshold - cache negative result
            if use_cache:
                self._profile_storage.set_symbol_mapping(
                    frame_name, None, confidence=0.0
                )
            return None

        # Create and cache the mapping
        from code_intel.profile.schema import FrameSymbolMapping
        mapping = FrameSymbolMapping(
            frame_name=frame_name,
            symbol_id=result.symbol_id,
            confidence=result.confidence,
        )

        if use_cache:
            self._profile_storage.set_symbol_mapping(
                frame_name,
                result.symbol_id,
                confidence=result.confidence,
            )

        return mapping

    def correlate_profile(
        self,
        profile_id: str,
        repo_path: str,
        *,
        use_cache: bool = True,
        min_confidence: float = 0.5,
    ) -> int:
        """Correlate all frames in a profile to symbols.

        Args:
            profile_id: ID of the profile to correlate.
            repo_path: Repository path for scoping symbol search.
            use_cache: Whether to use/update the mapping cache.
            min_confidence: Minimum confidence to accept a match.

        Returns:
            Number of frames successfully correlated.
        """
        profile = self._profile_storage.get_profile(profile_id)
        if not profile:
            return 0

        correlations: dict[int, str] = {}

        for idx, frame in enumerate(profile.frames):
            mapping = self.correlate_frame(
                frame.name,
                repo_path,
                file=frame.file,
                line=frame.line,
                use_cache=use_cache,
                min_confidence=min_confidence,
            )

            if mapping and mapping.symbol_id:
                correlations[idx] = mapping.symbol_id

        if correlations:
            self._profile_storage.update_symbol_correlations(
                profile_id, correlations
            )

        return len(correlations)

    def get_unmapped_frames(
        self,
        profile_id: str | None = None,
    ) -> list[str]:
        """Get frame names that haven't been mapped to symbols.

        Args:
            profile_id: Optional profile to scope the search.

        Returns:
            List of unmapped frame names.
        """
        return self._profile_storage.get_unmapped_frames(profile_id)

    def clear_cache(self) -> int:
        """Clear all cached frame-symbol mappings.

        Returns:
            Number of mappings cleared.
        """
        return self._profile_storage.clear_symbol_mappings()
