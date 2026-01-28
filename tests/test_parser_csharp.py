"""Tests for the C# parser."""

import pytest
from pathlib import Path

from code_intel.parser.csharp import CSharpParser


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-c-sharp are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_c_sharp
        return True
    except ImportError:
        return False


# Skip all tests in this module if tree-sitter is not available
pytestmark = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-c-sharp not installed"
)


@pytest.fixture
def parser():
    """Create a C# parser instance."""
    return CSharpParser()


class TestCSharpParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: CSharpParser):
        """Test language name property."""
        assert parser.language_name == "csharp"

    def test_file_extensions(self, parser: CSharpParser):
        """Test file extensions property."""
        assert ".cs" in parser.file_extensions


class TestClassExtraction:
    """Tests for class definition extraction."""

    def test_simple_class(self, parser: CSharpParser):
        """Test extracting a simple class."""
        source = b'''
public class MyClass
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "MyClass"
        assert "public" in classes[0]["metadata"].get("modifiers", [])

    def test_class_with_namespace(self, parser: CSharpParser):
        """Test extracting class with namespace."""
        source = b'''
namespace MyApp.Services
{
    public class Service
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["qualified_name"] == "MyApp.Services.Service"

    def test_class_inheritance(self, parser: CSharpParser):
        """Test extracting class with base class."""
        source = b'''
public class Child : Parent
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        bases = classes[0]["metadata"].get("bases", [])
        assert "Parent" in bases

    def test_class_multiple_inheritance(self, parser: CSharpParser):
        """Test extracting class with multiple interfaces."""
        source = b'''
public class MyClass : BaseClass, IInterface1, IInterface2
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        bases = classes[0]["metadata"].get("bases", [])
        assert "BaseClass" in bases
        assert "IInterface1" in bases
        assert "IInterface2" in bases

    def test_generic_class(self, parser: CSharpParser):
        """Test extracting generic class."""
        source = b'''
public class Container<T>
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        type_params = classes[0]["metadata"].get("type_parameters", [])
        assert "T" in type_params

    def test_partial_class(self, parser: CSharpParser):
        """Test extracting partial class."""
        source = b'''
public partial class MyClass
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["metadata"].get("partial") is True

    def test_abstract_class(self, parser: CSharpParser):
        """Test extracting abstract class."""
        source = b'''
public abstract class AbstractBase
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        modifiers = classes[0]["metadata"].get("modifiers", [])
        assert "abstract" in modifiers


class TestInterfaceExtraction:
    """Tests for interface definition extraction."""

    def test_simple_interface(self, parser: CSharpParser):
        """Test extracting a simple interface."""
        source = b'''
public interface IService
{
    void Process();
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "IService"

    def test_interface_inheritance(self, parser: CSharpParser):
        """Test extracting interface extending another interface."""
        source = b'''
public interface IExtended : IBase
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        bases = interfaces[0]["metadata"].get("bases", [])
        assert "IBase" in bases

    def test_generic_interface(self, parser: CSharpParser):
        """Test extracting generic interface."""
        source = b'''
public interface IRepository<T> where T : class
{
    T GetById(int id);
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        type_params = interfaces[0]["metadata"].get("type_parameters", [])
        assert "T" in type_params


class TestStructExtraction:
    """Tests for struct definition extraction."""

    def test_simple_struct(self, parser: CSharpParser):
        """Test extracting a simple struct."""
        source = b'''
public struct Point
{
    public int X;
    public int Y;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1
        assert structs[0]["name"] == "Point"

    def test_struct_with_interface(self, parser: CSharpParser):
        """Test extracting struct implementing interface."""
        source = b'''
public struct Coordinate : IEquatable<Coordinate>
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        structs = [s for s in symbols if s["kind"] == "struct"]
        assert len(structs) == 1
        bases = structs[0]["metadata"].get("bases", [])
        assert "IEquatable<Coordinate>" in bases


class TestRecordExtraction:
    """Tests for record type extraction."""

    def test_simple_record(self, parser: CSharpParser):
        """Test extracting a simple record."""
        source = b'''
public record Person(string Name, int Age);
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        records = [s for s in symbols if s["kind"] == "record"]
        assert len(records) == 1
        assert records[0]["name"] == "Person"
        params = records[0]["metadata"].get("primary_constructor_params", [])
        assert "string Name" in params
        assert "int Age" in params

    def test_record_with_body(self, parser: CSharpParser):
        """Test extracting a record with body."""
        source = b'''
public record Person(string Name)
{
    public string FullName => Name;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        records = [s for s in symbols if s["kind"] == "record"]
        assert len(records) == 1
        # Properties in records should be extracted
        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) >= 1


class TestEnumExtraction:
    """Tests for enum definition extraction."""

    def test_simple_enum(self, parser: CSharpParser):
        """Test extracting a simple enum."""
        source = b'''
public enum Status
{
    Active,
    Inactive,
    Pending
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        enums = [s for s in symbols if s["kind"] == "enum"]
        assert len(enums) == 1
        assert enums[0]["name"] == "Status"
        members = enums[0]["metadata"].get("members", [])
        assert "Active" in members
        assert "Inactive" in members
        assert "Pending" in members

    def test_flags_enum(self, parser: CSharpParser):
        """Test extracting a flags enum."""
        source = b'''
[Flags]
public enum Permissions
{
    None = 0,
    Read = 1,
    Write = 2
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        enums = [s for s in symbols if s["kind"] == "enum"]
        assert len(enums) == 1
        attributes = enums[0]["metadata"].get("attributes", [])
        assert "Flags" in attributes


class TestMethodExtraction:
    """Tests for method definition extraction."""

    def test_simple_method(self, parser: CSharpParser):
        """Test extracting a simple method."""
        source = b'''
public class MyClass
{
    public void DoSomething()
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["name"] == "DoSomething"
        assert "void" in methods[0]["signature"]

    def test_method_with_parameters(self, parser: CSharpParser):
        """Test extracting method with parameters."""
        source = b'''
public class MyClass
{
    public string GetGreeting(string name, int age)
    {
        return $"Hello {name}";
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert "string name" in methods[0]["signature"]
        assert "int age" in methods[0]["signature"]
        assert methods[0]["metadata"].get("return_type") == "string"

    def test_async_method(self, parser: CSharpParser):
        """Test extracting async method."""
        source = b'''
public class MyClass
{
    public async Task<int> FetchDataAsync()
    {
        return await Task.FromResult(42);
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["metadata"].get("async") is True
        assert "async" in methods[0]["signature"]
        assert methods[0]["metadata"].get("return_type") == "Task<int>"

    def test_static_method(self, parser: CSharpParser):
        """Test extracting static method."""
        source = b'''
public class MyClass
{
    public static void StaticMethod()
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        modifiers = methods[0]["metadata"].get("modifiers", [])
        assert "static" in modifiers

    def test_generic_method(self, parser: CSharpParser):
        """Test extracting generic method."""
        source = b'''
public class MyClass
{
    public T Convert<T>(object value)
    {
        return (T)value;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        type_params = methods[0]["metadata"].get("type_parameters", [])
        assert "T" in type_params

    def test_method_with_attribute(self, parser: CSharpParser):
        """Test extracting method with attribute."""
        source = b'''
public class MyClass
{
    [Obsolete("Use NewMethod instead")]
    public void OldMethod()
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        attributes = methods[0]["metadata"].get("attributes", [])
        assert any("Obsolete" in attr for attr in attributes)


class TestConstructorExtraction:
    """Tests for constructor extraction."""

    def test_simple_constructor(self, parser: CSharpParser):
        """Test extracting a simple constructor."""
        source = b'''
public class MyClass
{
    public MyClass()
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constructors = [s for s in symbols if s["kind"] == "constructor"]
        assert len(constructors) == 1
        assert constructors[0]["name"] == "MyClass"

    def test_constructor_with_parameters(self, parser: CSharpParser):
        """Test extracting constructor with parameters."""
        source = b'''
public class MyClass
{
    public MyClass(string name, int value)
    {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constructors = [s for s in symbols if s["kind"] == "constructor"]
        assert len(constructors) == 1
        assert "string name" in constructors[0]["signature"]
        assert "int value" in constructors[0]["signature"]


class TestPropertyExtraction:
    """Tests for property extraction."""

    def test_auto_property(self, parser: CSharpParser):
        """Test extracting auto-implemented property."""
        source = b'''
public class MyClass
{
    public string Name { get; set; }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) == 1
        assert properties[0]["name"] == "Name"
        assert properties[0]["metadata"].get("type") == "string"
        assert properties[0]["metadata"].get("has_getter") is True
        assert properties[0]["metadata"].get("has_setter") is True

    def test_readonly_property(self, parser: CSharpParser):
        """Test extracting read-only property."""
        source = b'''
public class MyClass
{
    public string Name { get; }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) == 1
        assert properties[0]["metadata"].get("has_getter") is True
        assert properties[0]["metadata"].get("has_setter") is False


class TestFieldExtraction:
    """Tests for field extraction."""

    def test_simple_field(self, parser: CSharpParser):
        """Test extracting a simple field."""
        source = b'''
public class MyClass
{
    private string _name;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        fields = [s for s in symbols if s["kind"] == "field"]
        assert len(fields) == 1
        assert fields[0]["name"] == "_name"
        assert fields[0]["metadata"].get("type") == "string"
        assert "private" in fields[0]["metadata"].get("modifiers", [])

    def test_readonly_field(self, parser: CSharpParser):
        """Test extracting readonly field."""
        source = b'''
public class MyClass
{
    private readonly int _value;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        fields = [s for s in symbols if s["kind"] == "field"]
        assert len(fields) == 1
        modifiers = fields[0]["metadata"].get("modifiers", [])
        assert "readonly" in modifiers

    def test_const_field(self, parser: CSharpParser):
        """Test extracting const field."""
        source = b'''
public class MyClass
{
    public const int MaxValue = 100;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        fields = [s for s in symbols if s["kind"] == "field"]
        assert len(fields) == 1
        modifiers = fields[0]["metadata"].get("modifiers", [])
        assert "const" in modifiers

    def test_multiple_fields(self, parser: CSharpParser):
        """Test extracting multiple fields in one declaration."""
        source = b'''
public class MyClass
{
    private int x, y, z;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        fields = [s for s in symbols if s["kind"] == "field"]
        assert len(fields) == 3
        names = [f["name"] for f in fields]
        assert "x" in names
        assert "y" in names
        assert "z" in names


class TestUsingExtraction:
    """Tests for using directive extraction."""

    def test_simple_using(self, parser: CSharpParser):
        """Test extracting simple using directive."""
        source = b'''
using System;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "System"
        assert imports[0]["metadata"].get("import_type") == "using"

    def test_qualified_using(self, parser: CSharpParser):
        """Test extracting qualified using directive."""
        source = b'''
using System.Collections.Generic;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "System.Collections.Generic"

    def test_multiple_usings(self, parser: CSharpParser):
        """Test extracting multiple using directives."""
        source = b'''
using System;
using System.Linq;
using System.Collections.Generic;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 3


class TestCallExtraction:
    """Tests for method call reference extraction."""

    def test_simple_call(self, parser: CSharpParser):
        """Test extracting simple method call."""
        source = b'''
public class MyClass
{
    public void Caller()
    {
        DoSomething();
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next((c for c in calls if c["target"] == "DoSomething"), None)
        assert call is not None
        assert call["source"] == "MyClass.Caller"

    def test_member_call(self, parser: CSharpParser):
        """Test extracting member method call."""
        source = b'''
public class MyClass
{
    public void Process()
    {
        Console.WriteLine("test");
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next((c for c in calls if "Console.WriteLine" in c["target"]), None)
        assert call is not None

    def test_this_call(self, parser: CSharpParser):
        """Test extracting this.method() call."""
        source = b'''
public class MyClass
{
    public void Caller()
    {
        this.Helper();
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1
        call = next((c for c in calls if "Helper" in c["target"]), None)
        assert call is not None

    def test_chained_calls(self, parser: CSharpParser):
        """Test extracting chained method calls."""
        source = b'''
public class MyClass
{
    public void Process()
    {
        list.Where(x => x > 0).Select(x => x * 2).ToList();
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        # Should have multiple calls in the chain
        assert len(calls) >= 3


class TestInheritanceExtraction:
    """Tests for inheritance relationship extraction."""

    def test_class_inheritance(self, parser: CSharpParser):
        """Test extracting class inheritance."""
        source = b'''
public class Child : Parent
{
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        assert len(inherits) == 1
        assert inherits[0]["source"] == "Child"
        assert inherits[0]["target"] == "Parent"

    def test_interface_implementation(self, parser: CSharpParser):
        """Test extracting interface implementation."""
        source = b'''
public class MyService : IService
{
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        implements = [r for r in refs if r["type"] == "implements"]
        assert len(implements) == 1
        assert implements[0]["source"] == "MyService"
        assert implements[0]["target"] == "IService"

    def test_mixed_inheritance(self, parser: CSharpParser):
        """Test extracting mixed inheritance and implementation."""
        source = b'''
public class MyService : BaseService, IService, IDisposable
{
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        implements = [r for r in refs if r["type"] == "implements"]

        assert len(inherits) == 1
        assert inherits[0]["target"] == "BaseService"

        assert len(implements) == 2
        targets = [i["target"] for i in implements]
        assert "IService" in targets
        assert "IDisposable" in targets


class TestImportEdgeExtraction:
    """Tests for import relationship extraction."""

    def test_import_edge(self, parser: CSharpParser):
        """Test extracting import edges from using directives."""
        source = b'''
using System;
using System.Collections.Generic;
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        imports = [r for r in refs if r["type"] == "imports"]
        assert len(imports) == 2

        targets = [i["target"] for i in imports]
        assert "System" in targets
        assert "System.Collections.Generic" in targets


class TestParseToResult:
    """Tests for the high-level parse_to_result method."""

    def test_parse_to_result(self, parser: CSharpParser, tmp_path: Path):
        """Test complete parsing workflow."""
        source = '''
using System;
using System.Collections.Generic;

namespace MyApp.Services
{
    public interface IService
    {
        void Process();
    }

    public class MyService : BaseClass, IService
    {
        private readonly string _name;

        public string Name { get; set; }

        public MyService(string name)
        {
            _name = name;
        }

        public void Process()
        {
            Console.WriteLine(_name);
        }
    }
}
'''
        # Write to temp file
        test_file = tmp_path / "test_service.cs"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        node_kinds = {n.node_type for n in result.nodes}
        assert "import" in node_kinds
        assert "namespace" in node_kinds
        assert "interface" in node_kinds
        assert "class" in node_kinds
        assert "field" in node_kinds
        assert "property" in node_kinds
        assert "constructor" in node_kinds
        assert "method" in node_kinds

        # Check edges
        edge_types = {e.edge_type for e in result.edges}
        assert "imports" in edge_types
        assert "inherits" in edge_types or "implements" in edge_types
        assert "calls" in edge_types

    def test_parse_to_result_with_content(self, parser: CSharpParser):
        """Test parsing with content string instead of file."""
        source = '''
public class Example
{
    public void Method() { }
}
'''
        result = parser.parse_to_result("virtual.cs", content=source)

        assert result.file_path == "virtual.cs"
        assert len(result.nodes) >= 2  # class + method


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: CSharpParser):
        """Test parsing empty file."""
        source = b""
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        refs = parser.extract_references(tree, source)

        assert symbols == []
        assert refs == []

    def test_syntax_error(self, parser: CSharpParser):
        """Test parsing file with syntax errors."""
        source = b'''
public class Broken {
    public void Method(
        // Missing closing paren
'''
        tree = parser.parse(source)
        # Should still be able to parse what's possible
        assert tree.root_node.has_error

    def test_nested_class(self, parser: CSharpParser):
        """Test parsing nested class."""
        source = b'''
public class Outer
{
    public class Inner
    {
        public void InnerMethod() { }
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 2
        assert any(c["name"] == "Outer" for c in classes)
        assert any(c["name"] == "Inner" for c in classes)

    def test_file_scoped_namespace(self, parser: CSharpParser):
        """Test parsing file-scoped namespace (C# 10+)."""
        source = b'''
namespace MyApp.Services;

public class MyService
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) == 1
        assert namespaces[0]["name"] == "MyApp.Services"
        assert namespaces[0]["metadata"].get("file_scoped") is True

    def test_nullable_types(self, parser: CSharpParser):
        """Test parsing nullable reference types."""
        source = b'''
public class MyClass
{
    public string? NullableName { get; set; }
    public int? NullableValue;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) == 1

        fields = [s for s in symbols if s["kind"] == "field"]
        assert len(fields) == 1

    def test_expression_bodied_members(self, parser: CSharpParser):
        """Test parsing expression-bodied members."""
        source = b'''
public class MyClass
{
    public int Value => 42;
    public int GetDouble(int x) => x * 2;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        methods = [s for s in symbols if s["kind"] == "method"]

        assert len(properties) == 1
        assert len(methods) == 1

    def test_primary_constructor(self, parser: CSharpParser):
        """Test parsing primary constructor (C# 12)."""
        source = b'''
public class Person(string Name, int Age)
{
    public string FullInfo => $"{Name}, {Age}";
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Primary constructor is part of class declaration
        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1

    def test_extension_method(self, parser: CSharpParser):
        """Test parsing extension method."""
        source = b'''
public static class StringExtensions
{
    public static string Reverse(this string str)
    {
        return new string(str.ToCharArray().Reverse().ToArray());
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert "this string str" in methods[0]["signature"]

    def test_attribute_with_arguments(self, parser: CSharpParser):
        """Test parsing attributes with arguments."""
        source = b'''
[Route("api/[controller]")]
[ApiController]
public class MyController
{
    [HttpGet("{id}")]
    public string Get(int id) { return ""; }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        attributes = classes[0]["metadata"].get("attributes", [])
        assert any("Route" in attr for attr in attributes)
        assert any("ApiController" in attr for attr in attributes)


class TestNamespaceExtraction:
    """Tests for namespace extraction."""

    def test_simple_namespace(self, parser: CSharpParser):
        """Test extracting simple namespace."""
        source = b'''
namespace MyApp
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) == 1
        assert namespaces[0]["name"] == "MyApp"

    def test_nested_namespace(self, parser: CSharpParser):
        """Test extracting nested namespace."""
        source = b'''
namespace MyApp.Services.Internal
{
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) == 1
        assert namespaces[0]["name"] == "MyApp.Services.Internal"
