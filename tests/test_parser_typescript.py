"""Tests for the TypeScript/JavaScript parser."""

import pytest
from pathlib import Path

from code_intel.parser.typescript import TypeScriptParser


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-typescript are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_typescript
        return True
    except ImportError:
        return False


# Skip all tests in this module if tree-sitter is not available
pytestmark = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-typescript not installed"
)


@pytest.fixture
def parser():
    """Create a TypeScript parser instance."""
    return TypeScriptParser()


class TestTypeScriptParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: TypeScriptParser):
        """Test language name property."""
        assert parser.language_name == "typescript"

    def test_file_extensions(self, parser: TypeScriptParser):
        """Test file extensions property."""
        assert ".ts" in parser.file_extensions
        assert ".tsx" in parser.file_extensions
        assert ".js" in parser.file_extensions
        assert ".jsx" in parser.file_extensions
        assert ".mjs" in parser.file_extensions
        assert ".cjs" in parser.file_extensions


class TestFunctionExtraction:
    """Tests for function definition extraction."""

    def test_simple_function(self, parser: TypeScriptParser):
        """Test extracting a simple function."""
        source = b'''
function hello() {
    console.log("hello");
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "hello"
        assert functions[0]["qualified_name"] == "hello"
        assert "function hello()" in functions[0]["signature"]

    def test_function_with_parameters(self, parser: TypeScriptParser):
        """Test extracting function with parameters."""
        source = b'''
function greet(name: string, count: number): void {
    console.log(name, count);
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert "name: string" in functions[0]["signature"]
        assert "count: number" in functions[0]["signature"]

    def test_function_with_return_type(self, parser: TypeScriptParser):
        """Test extracting function with return type."""
        source = b'''
function calculate(x: number): number {
    return x * 2;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("return_type") == "number"

    def test_async_function(self, parser: TypeScriptParser):
        """Test extracting async function."""
        source = b'''
async function fetchData(): Promise<string> {
    return "data";
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("async") is True

    def test_generic_function(self, parser: TypeScriptParser):
        """Test extracting generic function."""
        source = b'''
function identity<T>(value: T): T {
    return value;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("type_parameters") == ["T"]


class TestArrowFunctionExtraction:
    """Tests for arrow function extraction."""

    def test_arrow_function_const(self, parser: TypeScriptParser):
        """Test extracting arrow function assigned to const."""
        source = b'''
const add = (a: number, b: number): number => a + b;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "add"
        assert functions[0]["metadata"].get("arrow_function") is True

    def test_async_arrow_function(self, parser: TypeScriptParser):
        """Test extracting async arrow function."""
        source = b'''
const fetchUser = async (id: string): Promise<User> => {
    return { id };
};
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("async") is True
        assert functions[0]["metadata"].get("arrow_function") is True

    def test_arrow_function_no_params(self, parser: TypeScriptParser):
        """Test extracting arrow function with no parameters."""
        source = b'''
const getTime = () => Date.now();
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "getTime"


class TestClassExtraction:
    """Tests for class definition extraction."""

    def test_simple_class(self, parser: TypeScriptParser):
        """Test extracting a simple class."""
        source = b'''
class Person {
    name: string;

    constructor(name: string) {
        this.name = name;
    }

    greet(): void {
        console.log(this.name);
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "Person"
        assert classes[0]["qualified_name"] == "Person"

        # Check methods
        methods = [s for s in symbols if s["kind"] in ("method", "constructor")]
        assert len(methods) >= 1

        constructors = [m for m in methods if m["name"] == "constructor"]
        assert len(constructors) == 1

    def test_class_with_inheritance(self, parser: TypeScriptParser):
        """Test extracting class with extends."""
        source = b'''
class Animal {
    name: string;
}

class Dog extends Animal {
    bark(): void {}
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 2

        dog = next(c for c in classes if c["name"] == "Dog")
        assert dog["metadata"].get("extends") == "Animal"

    def test_class_implementing_interface(self, parser: TypeScriptParser):
        """Test extracting class implementing interface."""
        source = b'''
interface Runnable {
    run(): void;
}

class Task implements Runnable {
    run(): void {}
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1

        task = classes[0]
        assert "Runnable" in task["metadata"].get("implements", [])

    def test_abstract_class(self, parser: TypeScriptParser):
        """Test extracting abstract class."""
        source = b'''
abstract class Shape {
    abstract getArea(): number;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["metadata"].get("abstract") is True

    def test_generic_class(self, parser: TypeScriptParser):
        """Test extracting generic class."""
        source = b'''
class Container<T> {
    private value: T;

    constructor(value: T) {
        this.value = value;
    }

    getValue(): T {
        return this.value;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["metadata"].get("type_parameters") == ["T"]


class TestMethodExtraction:
    """Tests for method extraction."""

    def test_static_method(self, parser: TypeScriptParser):
        """Test extracting static method."""
        source = b'''
class Utils {
    static formatDate(date: Date): string {
        return date.toISOString();
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["metadata"].get("static") is True

    def test_private_method(self, parser: TypeScriptParser):
        """Test extracting private method."""
        source = b'''
class Service {
    private init(): void {}
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["metadata"].get("visibility") == "private"

    def test_async_method(self, parser: TypeScriptParser):
        """Test extracting async method."""
        source = b'''
class Api {
    async fetch(): Promise<Response> {
        return fetch('/api');
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["metadata"].get("async") is True

    def test_getter_setter(self, parser: TypeScriptParser):
        """Test extracting getter and setter."""
        source = b'''
class Person {
    private _name: string;

    get name(): string {
        return this._name;
    }

    set name(value: string) {
        this._name = value;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        getters = [m for m in methods if m["metadata"].get("accessor") == "getter"]
        setters = [m for m in methods if m["metadata"].get("accessor") == "setter"]

        assert len(getters) == 1
        assert len(setters) == 1


class TestInterfaceExtraction:
    """Tests for interface extraction."""

    def test_simple_interface(self, parser: TypeScriptParser):
        """Test extracting a simple interface."""
        source = b'''
interface User {
    id: string;
    name: string;
    email?: string;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "User"
        assert interfaces[0]["qualified_name"] == "User"

    def test_interface_with_methods(self, parser: TypeScriptParser):
        """Test extracting interface with method signatures."""
        source = b'''
interface Repository {
    find(id: string): Entity | null;
    save(entity: Entity): void;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1

        members = interfaces[0]["metadata"].get("members", [])
        method_names = [m["name"] for m in members if m["kind"] == "method"]
        assert "find" in method_names
        assert "save" in method_names

    def test_interface_extending(self, parser: TypeScriptParser):
        """Test extracting interface extending other interfaces."""
        source = b'''
interface Named {
    name: string;
}

interface Aged {
    age: number;
}

interface Person extends Named, Aged {
    greet(): void;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        person = next(i for i in interfaces if i["name"] == "Person")

        extends = person["metadata"].get("extends", [])
        assert "Named" in extends or "Named, Aged" in " ".join(extends)

    def test_generic_interface(self, parser: TypeScriptParser):
        """Test extracting generic interface."""
        source = b'''
interface Result<T, E> {
    value?: T;
    error?: E;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        type_params = interfaces[0]["metadata"].get("type_parameters", [])
        assert "T" in type_params
        assert "E" in type_params


class TestTypeAliasExtraction:
    """Tests for type alias extraction."""

    def test_simple_type_alias(self, parser: TypeScriptParser):
        """Test extracting simple type alias."""
        source = b'''
type ID = string;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert types[0]["name"] == "ID"

    def test_union_type(self, parser: TypeScriptParser):
        """Test extracting union type alias."""
        source = b'''
type Status = "pending" | "active" | "completed";
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert types[0]["name"] == "Status"

    def test_generic_type_alias(self, parser: TypeScriptParser):
        """Test extracting generic type alias."""
        source = b'''
type Nullable<T> = T | null;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1
        assert types[0]["metadata"].get("type_parameters") == ["T"]


class TestEnumExtraction:
    """Tests for enum extraction."""

    def test_simple_enum(self, parser: TypeScriptParser):
        """Test extracting a simple enum."""
        source = b'''
enum Color {
    Red,
    Green,
    Blue
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        enums = [s for s in symbols if s["kind"] == "enum"]
        assert len(enums) == 1
        assert enums[0]["name"] == "Color"

    def test_const_enum(self, parser: TypeScriptParser):
        """Test extracting const enum."""
        source = b'''
const enum Direction {
    Up,
    Down,
    Left,
    Right
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        enums = [s for s in symbols if s["kind"] == "enum"]
        assert len(enums) == 1
        assert enums[0]["metadata"].get("const") is True


class TestESModuleImportExtraction:
    """Tests for ES module import extraction."""

    def test_default_import(self, parser: TypeScriptParser):
        """Test extracting default import."""
        source = b'''
import React from 'react';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "React"
        assert imports[0]["metadata"].get("import_type") == "default"
        assert imports[0]["metadata"].get("module") == "react"

    def test_named_imports(self, parser: TypeScriptParser):
        """Test extracting named imports."""
        source = b'''
import { useState, useEffect } from 'react';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 2

        names = [i["name"] for i in imports]
        assert "useState" in names
        assert "useEffect" in names

    def test_aliased_import(self, parser: TypeScriptParser):
        """Test extracting aliased import."""
        source = b'''
import { Component as BaseComponent } from 'react';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "BaseComponent"
        assert imports[0]["metadata"].get("original_name") == "Component"

    def test_namespace_import(self, parser: TypeScriptParser):
        """Test extracting namespace import."""
        source = b'''
import * as fs from 'fs';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "fs"
        assert imports[0]["metadata"].get("import_type") == "namespace"

    def test_side_effect_import(self, parser: TypeScriptParser):
        """Test extracting side-effect import."""
        source = b'''
import './styles.css';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["metadata"].get("import_type") == "side_effect"


class TestCommonJSImportExtraction:
    """Tests for CommonJS import extraction."""

    def test_require_simple(self, parser: TypeScriptParser):
        """Test extracting simple require."""
        source = b'''
const fs = require('fs');
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "fs"
        assert imports[0]["metadata"].get("import_type") == "commonjs"
        assert imports[0]["metadata"].get("module") == "fs"

    def test_require_destructured(self, parser: TypeScriptParser):
        """Test extracting destructured require."""
        source = b'''
const { readFile, writeFile } = require('fs');
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 2

        names = [i["name"] for i in imports]
        assert "readFile" in names
        assert "writeFile" in names


class TestExportExtraction:
    """Tests for export statement extraction."""

    def test_exported_function(self, parser: TypeScriptParser):
        """Test extracting exported function."""
        source = b'''
export function hello(): void {}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["metadata"].get("exported") is True

    def test_exported_class(self, parser: TypeScriptParser):
        """Test extracting exported class."""
        source = b'''
export class MyService {}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["metadata"].get("exported") is True

    def test_exported_const(self, parser: TypeScriptParser):
        """Test extracting exported const."""
        source = b'''
export const VERSION = "1.0.0";
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 1
        assert constants[0]["metadata"].get("exported") is True


class TestCallExtraction:
    """Tests for function call reference extraction."""

    def test_simple_call(self, parser: TypeScriptParser):
        """Test extracting simple function call."""
        source = b'''
function caller() {
    helper();
}

function helper() {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

        call = next((c for c in calls if c["target"] == "helper"), None)
        assert call is not None
        assert call["source"] == "caller"

    def test_method_call(self, parser: TypeScriptParser):
        """Test extracting method call."""
        source = b'''
class Service {
    start() {
        this.init();
    }

    init() {}
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

    def test_imported_function_call(self, parser: TypeScriptParser):
        """Test extracting call to imported function."""
        source = b'''
import { formatDate } from './utils';

function display() {
    formatDate(new Date());
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        format_call = next((c for c in calls if c["target"] == "formatDate"), None)
        assert format_call is not None
        assert format_call.get("metadata", {}).get("target_module") == "./utils"


class TestInheritanceEdges:
    """Tests for inheritance relationship extraction."""

    def test_class_extends(self, parser: TypeScriptParser):
        """Test extracting class inheritance edge."""
        source = b'''
class Animal {}

class Dog extends Animal {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        assert len(inherits) == 1
        assert inherits[0]["source"] == "Dog"
        assert inherits[0]["target"] == "Animal"

    def test_class_implements(self, parser: TypeScriptParser):
        """Test extracting class implements edge."""
        source = b'''
interface Runnable {
    run(): void;
}

class Task implements Runnable {
    run() {}
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        implements = [r for r in refs if r["type"] == "implements"]
        assert len(implements) == 1
        assert implements[0]["source"] == "Task"
        assert implements[0]["target"] == "Runnable"


class TestImportEdges:
    """Tests for import relationship extraction."""

    def test_import_edges(self, parser: TypeScriptParser):
        """Test extracting import edges."""
        source = b'''
import { useState, useEffect } from 'react';
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        imports = [r for r in refs if r["type"] == "imports"]
        assert len(imports) == 2

        targets = [i["target"] for i in imports]
        assert "react.useState" in targets
        assert "react.useEffect" in targets


class TestParseToResult:
    """Tests for the high-level parse_to_result method."""

    def test_parse_to_result_typescript(self, parser: TypeScriptParser, tmp_path: Path):
        """Test complete parsing workflow for TypeScript."""
        source = '''
import { Injectable } from '@angular/core';

interface UserData {
    id: string;
    name: string;
}

@Injectable()
export class UserService {
    private users: UserData[] = [];

    async getUser(id: string): Promise<UserData | null> {
        return this.users.find(u => u.id === id) || null;
    }

    addUser(user: UserData): void {
        this.users.push(user);
    }
}
'''
        test_file = tmp_path / "user.service.ts"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        node_kinds = {n.node_type for n in result.nodes}
        assert "import" in node_kinds
        assert "interface" in node_kinds
        assert "class" in node_kinds
        assert "method" in node_kinds

        # Check edges
        edge_types = {e.edge_type for e in result.edges}
        assert "imports" in edge_types
        assert "calls" in edge_types

    def test_parse_to_result_javascript(self, parser: TypeScriptParser, tmp_path: Path):
        """Test complete parsing workflow for JavaScript."""
        source = '''
const express = require('express');

function createApp() {
    const app = express();

    app.get('/', (req, res) => {
        res.send('Hello');
    });

    return app;
}

module.exports = { createApp };
'''
        test_file = tmp_path / "app.js"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)

        # Check nodes
        node_kinds = {n.node_type for n in result.nodes}
        assert "import" in node_kinds or "function" in node_kinds

        # Check for function
        functions = [n for n in result.nodes if n.node_type == "function"]
        assert len(functions) >= 1


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: TypeScriptParser):
        """Test parsing empty file."""
        source = b""
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        refs = parser.extract_references(tree, source)

        assert symbols == []
        assert refs == []

    def test_syntax_error(self, parser: TypeScriptParser):
        """Test parsing file with syntax errors."""
        source = b'''
function broken( {
'''
        tree = parser.parse(source)
        assert tree.root_node.has_error

    def test_jsx_element(self, parser: TypeScriptParser):
        """Test parsing JSX/TSX."""
        source = b'''
function Component(): JSX.Element {
    return <div>Hello</div>;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "Component"

    def test_multiple_exports(self, parser: TypeScriptParser):
        """Test parsing multiple exports."""
        source = b'''
export const A = 1;
export const B = 2;
export function foo() {}
export class Bar {}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        exported = [s for s in symbols if s.get("metadata", {}).get("exported")]
        assert len(exported) >= 3

    def test_deeply_nested_calls(self, parser: TypeScriptParser):
        """Test parsing deeply nested call expressions."""
        source = b'''
function process() {
    return fetch('/api')
        .then(r => r.json())
        .then(data => transform(data))
        .catch(error => handle(error));
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        # Should have multiple calls: fetch, then (multiple), catch
        assert len(calls) >= 3

    def test_class_with_decorators(self, parser: TypeScriptParser):
        """Test parsing class with decorators."""
        source = b'''
@Component({
    selector: 'app-root'
})
class AppComponent {
    @Input() title: string;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1

    def test_optional_chaining_calls(self, parser: TypeScriptParser):
        """Test parsing optional chaining calls."""
        source = b'''
function getValue(obj: Obj | null) {
    return obj?.getValue?.() ?? 'default';
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        # Should still extract calls even with optional chaining
        calls = [r for r in refs if r["type"] == "calls"]
        assert len(calls) >= 1

    def test_template_literal_types(self, parser: TypeScriptParser):
        """Test parsing template literal types."""
        source = b'''
type EventName = `on${string}`;
type Getter<T extends string> = `get${Capitalize<T>}`;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 2

    def test_index_signatures(self, parser: TypeScriptParser):
        """Test parsing interfaces with index signatures."""
        source = b'''
interface Dictionary {
    [key: string]: unknown;
    length: number;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1

    def test_mapped_types(self, parser: TypeScriptParser):
        """Test parsing mapped types."""
        source = b'''
type Readonly<T> = {
    readonly [P in keyof T]: T[P];
};
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        types = [s for s in symbols if s["kind"] == "type"]
        assert len(types) == 1


class TestJavaScriptSpecific:
    """Tests for JavaScript-specific patterns."""

    def test_function_expression(self, parser: TypeScriptParser):
        """Test extracting function expression."""
        source = b'''
const greet = function(name) {
    return "Hello, " + name;
};
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "greet"

    def test_class_expression(self, parser: TypeScriptParser):
        """Test parsing class assigned to variable."""
        source = b'''
const MyClass = class {
    constructor() {}
    method() {}
};
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        # Should extract as variable/constant at minimum
        assert len(symbols) >= 1

    def test_iife(self, parser: TypeScriptParser):
        """Test parsing IIFE (Immediately Invoked Function Expression)."""
        source = b'''
(function() {
    console.log("IIFE");
})();
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        # Should still work without errors
        assert isinstance(refs, list)

    def test_spread_and_rest(self, parser: TypeScriptParser):
        """Test parsing spread and rest operators."""
        source = b'''
function merge(...arrays) {
    return [].concat(...arrays);
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1

    def test_destructuring_params(self, parser: TypeScriptParser):
        """Test parsing function with destructured parameters."""
        source = b'''
function processUser({ name, age }: { name: string; age: number }) {
    return `${name} is ${age}`;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "processUser"
