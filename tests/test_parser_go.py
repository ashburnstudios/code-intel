"""Tests for the Go parser."""

import pytest
from pathlib import Path

from code_intel.parser.go import GoParser


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-go are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_go
        return True
    except ImportError:
        return False


# Skip all tests in this module if tree-sitter is not available
pytestmark = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-go not installed"
)


@pytest.fixture
def parser():
    """Create a Go parser instance."""
    return GoParser()


class TestGoParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: GoParser):
        """Test language name property."""
        assert parser.language_name == "go"

    def test_file_extensions(self, parser: GoParser):
        """Test file extensions property."""
        assert ".go" in parser.file_extensions


class TestPackageExtraction:
    """Tests for package declaration extraction."""

    def test_simple_package(self, parser: GoParser):
        """Test extracting simple package declaration."""
        source = b'''
package main
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        packages = [s for s in symbols if s["kind"] == "package"]
        assert len(packages) == 1
        assert packages[0]["name"] == "main"
        assert packages[0]["qualified_name"] == "main"

    def test_library_package(self, parser: GoParser):
        """Test extracting library package declaration."""
        source = b'''
package mypackage
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        packages = [s for s in symbols if s["kind"] == "package"]
        assert len(packages) == 1
        assert packages[0]["name"] == "mypackage"


class TestImportExtraction:
    """Tests for import statement extraction."""

    def test_single_import(self, parser: GoParser):
        """Test extracting single import."""
        source = b'''
package main

import "fmt"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "fmt"
        assert imports[0]["qualified_name"] == "fmt"

    def test_multi_import(self, parser: GoParser):
        """Test extracting multiple imports."""
        source = b'''
package main

import (
    "fmt"
    "os"
    "strings"
)
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 3

        names = [i["name"] for i in imports]
        assert "fmt" in names
        assert "os" in names
        assert "strings" in names

    def test_aliased_import(self, parser: GoParser):
        """Test extracting aliased import."""
        source = b'''
package main

import f "fmt"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "f"
        assert imports[0]["qualified_name"] == "fmt"
        assert imports[0]["metadata"].get("alias") == "f"

    def test_path_import(self, parser: GoParser):
        """Test extracting import with full path."""
        source = b'''
package main

import "github.com/user/repo/pkg"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "pkg"
        assert imports[0]["qualified_name"] == "github.com/user/repo/pkg"
        assert imports[0]["metadata"].get("package_name") == "pkg"

    def test_blank_import(self, parser: GoParser):
        """Test extracting blank import (for side effects)."""
        source = b'''
package main

import _ "net/http/pprof"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["metadata"].get("alias") == "_"

    def test_dot_import(self, parser: GoParser):
        """Test extracting dot import."""
        source = b'''
package main

import . "fmt"
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["metadata"].get("alias") == "."


class TestFunctionExtraction:
    """Tests for function definition extraction."""

    def test_simple_function(self, parser: GoParser):
        """Test extracting a simple function."""
        source = b'''
package main

func main() {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "main"
        assert functions[0]["qualified_name"] == "main.main"
        assert "func main()" in functions[0]["signature"]

    def test_function_with_parameters(self, parser: GoParser):
        """Test extracting function with parameters."""
        source = b'''
package main

func greet(name string, count int) {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert "name string" in functions[0]["signature"]
        assert "count int" in functions[0]["signature"]

    def test_function_with_return(self, parser: GoParser):
        """Test extracting function with return type."""
        source = b'''
package main

func calculate(x int) int {
    return x * 2
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert "int" in functions[0].get("metadata", {}).get("returns", [])

    def test_function_with_multiple_returns(self, parser: GoParser):
        """Test extracting function with multiple return values."""
        source = b'''
package main

func divide(a, b int) (int, error) {
    return a / b, nil
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        returns = functions[0].get("metadata", {}).get("returns", [])
        assert len(returns) == 2

    def test_exported_function(self, parser: GoParser):
        """Test that exported functions are marked correctly."""
        source = b'''
package main

func PublicFunc() {
}

func privateFunc() {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 2

        public = next(f for f in functions if f["name"] == "PublicFunc")
        private = next(f for f in functions if f["name"] == "privateFunc")

        assert public["metadata"].get("exported") is True
        assert private["metadata"].get("exported") is False


class TestMethodExtraction:
    """Tests for method definition extraction."""

    def test_value_receiver_method(self, parser: GoParser):
        """Test extracting method with value receiver."""
        source = b'''
package main

type Person struct{}

func (p Person) Name() string {
    return ""
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["name"] == "Name"
        assert methods[0]["qualified_name"] == "main.Person.Name"

        receiver = methods[0]["metadata"].get("receiver")
        assert receiver is not None
        assert receiver["type"] == "Person"
        assert receiver["pointer"] is False

    def test_pointer_receiver_method(self, parser: GoParser):
        """Test extracting method with pointer receiver."""
        source = b'''
package main

type Person struct{}

func (p *Person) SetName(name string) {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["name"] == "SetName"

        receiver = methods[0]["metadata"].get("receiver")
        assert receiver is not None
        assert receiver["type"] == "Person"
        assert receiver["pointer"] is True
        assert "(p *Person)" in methods[0]["signature"]

    def test_method_with_multiple_params(self, parser: GoParser):
        """Test extracting method with multiple parameters."""
        source = b'''
package main

type Calculator struct{}

func (c Calculator) Add(a int, b int) int {
    return a + b
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert "a int" in methods[0]["signature"]
        assert "b int" in methods[0]["signature"]


class TestStructExtraction:
    """Tests for struct definition extraction."""

    def test_simple_struct(self, parser: GoParser):
        """Test extracting a simple struct."""
        source = b'''
package main

type Person struct {
    Name string
    Age  int
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1
        assert structs[0]["name"] == "Person"
        assert structs[0]["qualified_name"] == "main.Person"

        fields = structs[0]["metadata"].get("fields", [])
        assert len(fields) == 2

        field_names = [f["name"] for f in fields]
        assert "Name" in field_names
        assert "Age" in field_names

    def test_struct_with_tags(self, parser: GoParser):
        """Test extracting struct with field tags."""
        source = b'''
package main

type User struct {
    ID   int    `json:"id"`
    Name string `json:"name,omitempty"`
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1

        fields = structs[0]["metadata"].get("fields", [])
        assert len(fields) == 2

        id_field = next(f for f in fields if f["name"] == "ID")
        assert "json" in id_field.get("tag", "")

    def test_struct_with_embedded_field(self, parser: GoParser):
        """Test extracting struct with embedded field."""
        source = b'''
package main

type Base struct{}

type Derived struct {
    Base
    Value int
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 2

        derived = next(s for s in structs if s["name"] == "Derived")
        fields = derived["metadata"].get("fields", [])

        embedded = next((f for f in fields if f.get("embedded")), None)
        assert embedded is not None
        assert embedded["name"] == "Base"

    def test_struct_with_pointer_field(self, parser: GoParser):
        """Test extracting struct with pointer field."""
        source = b'''
package main

type Node struct {
    Value int
    Next  *Node
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1

        fields = structs[0]["metadata"].get("fields", [])
        next_field = next(f for f in fields if f["name"] == "Next")
        assert "*Node" in next_field["type"]

    def test_exported_struct(self, parser: GoParser):
        """Test that exported structs are marked correctly."""
        source = b'''
package main

type PublicType struct{}
type privateType struct{}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 2

        public = next(s for s in structs if s["name"] == "PublicType")
        private = next(s for s in structs if s["name"] == "privateType")

        assert public["metadata"].get("exported") is True
        assert private["metadata"].get("exported") is False


class TestInterfaceExtraction:
    """Tests for interface definition extraction."""

    def test_simple_interface(self, parser: GoParser):
        """Test extracting a simple interface."""
        source = b'''
package main

type Reader interface {
    Read(p []byte) (n int, err error)
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "Reader"
        assert interfaces[0]["qualified_name"] == "main.Reader"

        methods = interfaces[0]["metadata"].get("methods", [])
        assert len(methods) == 1
        assert methods[0]["name"] == "Read"

    def test_interface_with_multiple_methods(self, parser: GoParser):
        """Test extracting interface with multiple methods."""
        source = b'''
package main

type ReadWriter interface {
    Read(p []byte) (n int, err error)
    Write(p []byte) (n int, err error)
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1

        methods = interfaces[0]["metadata"].get("methods", [])
        assert len(methods) == 2

        method_names = [m["name"] for m in methods]
        assert "Read" in method_names
        assert "Write" in method_names

    def test_embedded_interface(self, parser: GoParser):
        """Test extracting interface with embedded interface."""
        source = b'''
package main

type Reader interface {
    Read(p []byte) (n int, err error)
}

type ReadCloser interface {
    Reader
    Close() error
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 2

        read_closer = next(i for i in interfaces if i["name"] == "ReadCloser")
        embeds = read_closer["metadata"].get("embeds", [])
        assert "Reader" in embeds

    def test_empty_interface(self, parser: GoParser):
        """Test extracting empty interface."""
        source = b'''
package main

type Any interface{}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "Any"


class TestTypeAliasExtraction:
    """Tests for type alias extraction."""

    def test_simple_type_alias(self, parser: GoParser):
        """Test extracting simple type alias."""
        source = b'''
package main

type MyInt int
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert types[0]["name"] == "MyInt"
        assert types[0]["metadata"].get("underlying_type") == "int"

    def test_pointer_type_alias(self, parser: GoParser):
        """Test extracting pointer type alias."""
        source = b'''
package main

type StringPtr *string
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert "*string" in types[0]["metadata"].get("underlying_type", "")

    def test_slice_type_alias(self, parser: GoParser):
        """Test extracting slice type alias."""
        source = b'''
package main

type IntSlice []int
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert "[]int" in types[0]["metadata"].get("underlying_type", "")


class TestConstExtraction:
    """Tests for constant declaration extraction."""

    def test_simple_const(self, parser: GoParser):
        """Test extracting simple constant."""
        source = b'''
package main

const MaxSize = 100
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 1
        assert constants[0]["name"] == "MaxSize"
        assert constants[0]["qualified_name"] == "main.MaxSize"

    def test_typed_const(self, parser: GoParser):
        """Test extracting typed constant."""
        source = b'''
package main

const MaxSize int = 100
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 1
        assert constants[0]["metadata"].get("type") == "int"

    def test_const_block(self, parser: GoParser):
        """Test extracting constant block."""
        source = b'''
package main

const (
    A = 1
    B = 2
    C = 3
)
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 3

        names = [c["name"] for c in constants]
        assert "A" in names
        assert "B" in names
        assert "C" in names

    def test_exported_const(self, parser: GoParser):
        """Test that exported constants are marked correctly."""
        source = b'''
package main

const PublicConst = 1
const privateConst = 2
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 2

        public = next(c for c in constants if c["name"] == "PublicConst")
        private = next(c for c in constants if c["name"] == "privateConst")

        assert public["metadata"].get("exported") is True
        assert private["metadata"].get("exported") is False


class TestVarExtraction:
    """Tests for variable declaration extraction."""

    def test_simple_var(self, parser: GoParser):
        """Test extracting simple variable."""
        source = b'''
package main

var count int
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        variables = [s for s in symbols if s["kind"] == "variable"]
        assert len(variables) == 1
        assert variables[0]["name"] == "count"
        assert variables[0]["metadata"].get("type") == "int"

    def test_var_block(self, parser: GoParser):
        """Test extracting variable block."""
        source = b'''
package main

var (
    name   string
    age    int
    active bool
)
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        variables = [s for s in symbols if s["kind"] == "variable"]
        assert len(variables) == 3

        names = [v["name"] for v in variables]
        assert "name" in names
        assert "age" in names
        assert "active" in names


class TestCallExtraction:
    """Tests for function call reference extraction."""

    def test_simple_call(self, parser: GoParser):
        """Test extracting simple function call."""
        source = b'''
package main

func caller() {
    helper()
}

func helper() {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

        call = next((c for c in calls if c["target"] == "helper"), None)
        assert call is not None
        assert call["source"] == "caller"

    def test_package_function_call(self, parser: GoParser):
        """Test extracting package function call."""
        source = b'''
package main

import "fmt"

func main() {
    fmt.Println("hello")
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

        call = next((c for c in calls if c["target"] == "Println"), None)
        assert call is not None
        assert call.get("metadata", {}).get("target_module") == "fmt"

    def test_method_call(self, parser: GoParser):
        """Test extracting method call."""
        source = b'''
package main

type Service struct{}

func (s *Service) Start() {
    s.init()
}

func (s *Service) init() {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

        # Method call on receiver
        call = next((c for c in calls if "init" in c["target"]), None)
        assert call is not None


class TestImportEdgeExtraction:
    """Tests for import relationship extraction."""

    def test_import_edges(self, parser: GoParser):
        """Test extracting import edges."""
        source = b'''
package main

import (
    "fmt"
    "os"
)
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        imports = [r for r in refs if r["type"] == "imports"]
        assert len(imports) == 2

        targets = [i["target"] for i in imports]
        assert "fmt" in targets
        assert "os" in targets


class TestParseToResult:
    """Tests for the high-level parse_to_result method."""

    def test_parse_to_result(self, parser: GoParser, tmp_path: Path):
        """Test complete parsing workflow."""
        source = '''
package main

import (
    "fmt"
    "os"
)

const Version = "1.0"

type Server struct {
    Host string
    Port int
}

type Handler interface {
    Handle(req []byte) ([]byte, error)
}

func (s *Server) Start() error {
    fmt.Println("Starting server")
    return nil
}

func main() {
    s := &Server{Host: "localhost", Port: 8080}
    s.Start()
}
'''
        # Write to temp file
        test_file = tmp_path / "main.go"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        node_kinds = {n.node_type for n in result.nodes}
        assert "package" in node_kinds
        assert "import" in node_kinds
        assert "constant" in node_kinds
        assert "struct" in node_kinds
        assert "interface" in node_kinds
        assert "method" in node_kinds
        assert "function" in node_kinds

        # Check edges
        edge_types = {e.edge_type for e in result.edges}
        assert "imports" in edge_types
        assert "calls" in edge_types

    def test_parse_to_result_with_content(self, parser: GoParser):
        """Test parsing with content string instead of file."""
        source = '''
package main

func Hello() string {
    return "Hello"
}
'''
        result = parser.parse_to_result("virtual.go", content=source)

        assert result.file_path == "virtual.go"
        assert len(result.nodes) >= 2  # package + function


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: GoParser):
        """Test parsing empty file."""
        source = b""
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        refs = parser.extract_references(tree, source)

        assert symbols == []
        assert refs == []

    def test_package_only(self, parser: GoParser):
        """Test parsing file with only package declaration."""
        source = b"package main"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        packages = [s for s in symbols if s["kind"] == "package"]
        assert len(packages) == 1

    def test_syntax_error(self, parser: GoParser):
        """Test parsing file with syntax errors."""
        source = b'''
package main

func broken( {
'''
        tree = parser.parse(source)
        # Should still be able to parse what's possible
        assert tree.root_node.has_error

    def test_complex_generics(self, parser: GoParser):
        """Test parsing Go 1.18+ generics."""
        source = b'''
package main

type Container[T any] struct {
    Value T
}

func Map[T, U any](s []T, f func(T) U) []U {
    return nil
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Should extract struct and function even with generics
        structs = [s for s in symbols if s["kind"] == "struct"]
        functions = [s for s in symbols if s["kind"] == "function"]

        assert len(structs) >= 1
        assert len(functions) >= 1

    def test_multiple_receivers(self, parser: GoParser):
        """Test parsing multiple methods with different receivers."""
        source = b'''
package main

type A struct{}
type B struct{}

func (a A) MethodA() {}
func (b B) MethodB() {}
func (a *A) MethodC() {}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 3

        method_a = next(m for m in methods if m["name"] == "MethodA")
        method_b = next(m for m in methods if m["name"] == "MethodB")
        method_c = next(m for m in methods if m["name"] == "MethodC")

        assert method_a["metadata"]["receiver"]["type"] == "A"
        assert method_b["metadata"]["receiver"]["type"] == "B"
        assert method_c["metadata"]["receiver"]["type"] == "A"
        assert method_c["metadata"]["receiver"]["pointer"] is True

    def test_variadic_function(self, parser: GoParser):
        """Test parsing variadic function."""
        source = b'''
package main

func sum(nums ...int) int {
    return 0
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert "...int" in functions[0]["signature"]

    def test_init_function(self, parser: GoParser):
        """Test parsing init function."""
        source = b'''
package main

func init() {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "init"
        # init is lowercase but special
        assert functions[0]["metadata"].get("exported") is False

    def test_anonymous_struct(self, parser: GoParser):
        """Test parsing anonymous struct in var declaration."""
        source = b'''
package main

var config struct {
    Debug bool
    Port  int
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Should extract the variable, but anonymous struct handling may vary
        variables = [s for s in symbols if s["kind"] == "variable"]
        assert len(variables) >= 1

    def test_named_return_values(self, parser: GoParser):
        """Test parsing function with named return values."""
        source = b'''
package main

func divide(a, b int) (result int, err error) {
    return a / b, nil
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1

    def test_channel_type(self, parser: GoParser):
        """Test parsing channel type in struct."""
        source = b'''
package main

type Worker struct {
    done chan bool
    work chan<- string
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1

        fields = structs[0]["metadata"].get("fields", [])
        assert len(fields) == 2
