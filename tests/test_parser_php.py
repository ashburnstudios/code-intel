"""Tests for the PHP parser with WordPress patterns."""

import pytest
from pathlib import Path

from code_intel.parser.php import PHPParser


def _check_tree_sitter_available():
    """Check if tree-sitter and tree-sitter-php are available."""
    try:
        from tree_sitter import Parser
        import tree_sitter_php
        return True
    except ImportError:
        return False


# Skip all tests in this module if tree-sitter is not available
pytestmark = pytest.mark.skipif(
    not _check_tree_sitter_available(),
    reason="tree-sitter or tree-sitter-php not installed"
)


@pytest.fixture
def parser():
    """Create a PHP parser instance."""
    return PHPParser()


class TestPHPParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: PHPParser):
        """Test language name property."""
        assert parser.language_name == "php"

    def test_file_extensions(self, parser: PHPParser):
        """Test file extensions property."""
        assert ".php" in parser.file_extensions
        assert ".inc" in parser.file_extensions


class TestNamespaceExtraction:
    """Tests for namespace extraction."""

    def test_simple_namespace(self, parser: PHPParser):
        """Test extracting simple namespace."""
        source = b'''<?php
namespace MyApp;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) == 1
        assert namespaces[0]["name"] == "MyApp"

    def test_nested_namespace(self, parser: PHPParser):
        """Test extracting nested namespace."""
        source = b'''<?php
namespace MyApp\\Services\\Database;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) == 1
        assert namespaces[0]["name"] == "MyApp\\Services\\Database"


class TestUseStatementExtraction:
    """Tests for use statement (import) extraction."""

    def test_simple_use(self, parser: PHPParser):
        """Test extracting simple use statement."""
        source = b'''<?php
use MyApp\\Services\\UserService;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "UserService"
        assert imports[0]["qualified_name"] == "MyApp\\Services\\UserService"

    def test_aliased_use(self, parser: PHPParser):
        """Test extracting aliased use statement."""
        source = b'''<?php
use MyApp\\Services\\UserService as Users;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 1
        assert imports[0]["name"] == "Users"
        assert imports[0]["qualified_name"] == "MyApp\\Services\\UserService"
        assert imports[0]["metadata"].get("alias") == "Users"

    def test_multiple_use(self, parser: PHPParser):
        """Test extracting multiple use statements."""
        source = b'''<?php
use MyApp\\Models\\User;
use MyApp\\Models\\Post;
use MyApp\\Services\\Auth;
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        imports = [s for s in symbols if s["kind"] == "import"]
        assert len(imports) == 3

        names = [i["name"] for i in imports]
        assert "User" in names
        assert "Post" in names
        assert "Auth" in names


class TestFunctionExtraction:
    """Tests for function extraction."""

    def test_simple_function(self, parser: PHPParser):
        """Test extracting simple function."""
        source = b'''<?php
function hello() {
    echo "Hello";
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "hello"
        assert "function hello()" in functions[0]["signature"]

    def test_function_with_parameters(self, parser: PHPParser):
        """Test extracting function with parameters."""
        source = b'''<?php
function greet(string $name, int $count = 1): string {
    return str_repeat("Hello {$name}! ", $count);
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert "$name" in functions[0]["signature"]
        assert "$count" in functions[0]["signature"]
        assert ": string" in functions[0]["signature"]

    def test_namespaced_function(self, parser: PHPParser):
        """Test extracting function in namespace."""
        source = b'''<?php
namespace MyApp\\Utils;

function formatDate(string $date): string {
    return $date;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        functions = [s for s in symbols if s["kind"] == "function"]
        assert len(functions) == 1
        assert functions[0]["name"] == "formatDate"
        assert functions[0]["qualified_name"] == "MyApp\\Utils\\formatDate"


class TestClassExtraction:
    """Tests for class extraction."""

    def test_simple_class(self, parser: PHPParser):
        """Test extracting simple class."""
        source = b'''<?php
class User {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "User"

    def test_class_with_extends(self, parser: PHPParser):
        """Test extracting class with inheritance."""
        source = b'''<?php
class Admin extends User {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "Admin"
        assert classes[0]["metadata"].get("base_class") == "User"

    def test_class_with_interfaces(self, parser: PHPParser):
        """Test extracting class implementing interfaces."""
        source = b'''<?php
class UserService implements ServiceInterface, LoggableInterface {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        interfaces = classes[0]["metadata"].get("interfaces", [])
        assert "ServiceInterface" in interfaces
        assert "LoggableInterface" in interfaces

    def test_abstract_class(self, parser: PHPParser):
        """Test extracting abstract class."""
        source = b'''<?php
abstract class BaseController {
    abstract public function handle(): void;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert "abstract" in classes[0]["metadata"].get("modifiers", [])

    def test_final_class(self, parser: PHPParser):
        """Test extracting final class."""
        source = b'''<?php
final class ImmutableValue {
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert "final" in classes[0]["metadata"].get("modifiers", [])


class TestMethodExtraction:
    """Tests for method extraction."""

    def test_public_method(self, parser: PHPParser):
        """Test extracting public method."""
        source = b'''<?php
class User {
    public function getName(): string {
        return $this->name;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["name"] == "getName"
        assert methods[0]["metadata"].get("visibility") == "public"

    def test_private_method(self, parser: PHPParser):
        """Test extracting private method."""
        source = b'''<?php
class User {
    private function validate(): bool {
        return true;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["metadata"].get("visibility") == "private"

    def test_static_method(self, parser: PHPParser):
        """Test extracting static method."""
        source = b'''<?php
class Factory {
    public static function create(): self {
        return new self();
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert "static" in methods[0]["metadata"].get("modifiers", [])

    def test_method_qualified_name(self, parser: PHPParser):
        """Test method qualified name includes class."""
        source = b'''<?php
namespace MyApp;

class UserService {
    public function findById(int $id): ?User {
        return null;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["qualified_name"] == "MyApp\\UserService::findById"


class TestPropertyExtraction:
    """Tests for property extraction."""

    def test_typed_property(self, parser: PHPParser):
        """Test extracting typed property."""
        source = b'''<?php
class User {
    public string $name;
    private int $age;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) == 2

        name_prop = next(p for p in properties if p["name"] == "name")
        assert name_prop["metadata"].get("visibility") == "public"
        assert name_prop["metadata"].get("type") == "string"

        age_prop = next(p for p in properties if p["name"] == "age")
        assert age_prop["metadata"].get("visibility") == "private"
        assert age_prop["metadata"].get("type") == "int"

    def test_static_property(self, parser: PHPParser):
        """Test extracting static property."""
        source = b'''<?php
class Counter {
    private static int $count = 0;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        properties = [s for s in symbols if s["kind"] == "property"]
        assert len(properties) == 1
        assert "static" in properties[0]["metadata"].get("modifiers", [])


class TestTraitExtraction:
    """Tests for trait extraction."""

    def test_simple_trait(self, parser: PHPParser):
        """Test extracting simple trait."""
        source = b'''<?php
trait Loggable {
    public function log(string $message): void {
        echo $message;
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        traits = [s for s in symbols if s["kind"] == "trait"]
        assert len(traits) == 1
        assert traits[0]["name"] == "Loggable"

        # Trait methods should also be extracted
        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
        assert methods[0]["name"] == "log"

    def test_class_using_trait(self, parser: PHPParser):
        """Test extracting class that uses traits."""
        source = b'''<?php
class UserService {
    use Loggable;
    use Cacheable;

    public function save(): void {
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        traits = classes[0]["metadata"].get("traits", [])
        assert "Loggable" in traits
        assert "Cacheable" in traits


class TestInterfaceExtraction:
    """Tests for interface extraction."""

    def test_simple_interface(self, parser: PHPParser):
        """Test extracting simple interface."""
        source = b'''<?php
interface Renderable {
    public function render(): string;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        assert interfaces[0]["name"] == "Renderable"

    def test_interface_extends(self, parser: PHPParser):
        """Test extracting interface that extends another."""
        source = b'''<?php
interface AdvancedLogger extends LoggerInterface {
    public function debug(string $message): void;
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert len(interfaces) == 1
        extends = interfaces[0]["metadata"].get("extends", [])
        assert "LoggerInterface" in extends


class TestConstantExtraction:
    """Tests for constant extraction."""

    def test_const_declaration(self, parser: PHPParser):
        """Test extracting const declaration."""
        source = b'''<?php
const VERSION = '1.0.0';
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 1
        assert constants[0]["name"] == "VERSION"

    def test_class_const(self, parser: PHPParser):
        """Test extracting class constant."""
        source = b'''<?php
class Config {
    public const DEBUG = true;
    private const API_KEY = 'secret';
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        constants = [s for s in symbols if s["kind"] == "constant"]
        assert len(constants) == 2

        debug_const = next(c for c in constants if c["name"] == "DEBUG")
        assert debug_const["metadata"].get("visibility") == "public"

        api_const = next(c for c in constants if c["name"] == "API_KEY")
        assert api_const["metadata"].get("visibility") == "private"


class TestCallExtraction:
    """Tests for function/method call extraction."""

    def test_simple_function_call(self, parser: PHPParser):
        """Test extracting simple function call."""
        source = b'''<?php
function caller() {
    helper();
}

function helper() {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        call = next((c for c in calls if c["target"] == "helper"), None)
        assert call is not None
        assert call["source"] == "caller"

    def test_method_call(self, parser: PHPParser):
        """Test extracting method call."""
        source = b'''<?php
class Service {
    private $repo;

    public function process() {
        $this->repo->save();
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        save_call = next((c for c in calls if c["target"] == "save"), None)
        assert save_call is not None

    def test_static_call(self, parser: PHPParser):
        """Test extracting static method call."""
        source = b'''<?php
class Controller {
    public function index() {
        User::find(1);
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        calls = [r for r in refs if r["type"] == "calls"]
        static_call = next((c for c in calls if "User::find" in c["target"]), None)
        assert static_call is not None


class TestWordPressHookExtraction:
    """Tests for WordPress hook pattern extraction."""

    def test_add_action_string_callback(self, parser: PHPParser):
        """Test extracting add_action with string callback."""
        source = b'''<?php
function my_init_handler() {
    // Do something
}

add_action('init', 'my_init_handler');
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        hook_refs = [r for r in refs if r["type"] == "registers_action"]
        assert len(hook_refs) == 1
        assert hook_refs[0]["source"] == "my_init_handler"
        assert hook_refs[0]["target"] == "init"
        assert hook_refs[0]["metadata"].get("wordpress_hook") is True
        assert hook_refs[0]["metadata"].get("hook_type") == "action"

    def test_add_action_array_callback(self, parser: PHPParser):
        """Test extracting add_action with array callback."""
        source = b'''<?php
class Plugin {
    public function __construct() {
        add_action('init', [$this, 'onInit']);
    }

    public function onInit() {
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        hook_refs = [r for r in refs if r["type"] == "registers_action"]
        assert len(hook_refs) == 1
        assert hook_refs[0]["source"] == "onInit"
        assert hook_refs[0]["target"] == "init"

    def test_add_filter(self, parser: PHPParser):
        """Test extracting add_filter."""
        source = b'''<?php
function modify_content($content) {
    return $content . ' - Modified';
}

add_filter('the_content', 'modify_content');
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        hook_refs = [r for r in refs if r["type"] == "registers_filter"]
        assert len(hook_refs) == 1
        assert hook_refs[0]["source"] == "modify_content"
        assert hook_refs[0]["target"] == "the_content"
        assert hook_refs[0]["metadata"].get("hook_type") == "filter"

    def test_do_action(self, parser: PHPParser):
        """Test extracting do_action (hook trigger)."""
        source = b'''<?php
function init_plugin() {
    do_action('my_plugin_init');
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        trigger_refs = [r for r in refs if r["type"] == "triggers_action"]
        assert len(trigger_refs) == 1
        assert trigger_refs[0]["source"] == "init_plugin"
        assert trigger_refs[0]["target"] == "my_plugin_init"

    def test_apply_filters(self, parser: PHPParser):
        """Test extracting apply_filters (filter trigger)."""
        source = b'''<?php
function get_content() {
    $content = "Hello";
    return apply_filters('my_plugin_content', $content);
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        trigger_refs = [r for r in refs if r["type"] == "triggers_filter"]
        assert len(trigger_refs) == 1
        assert trigger_refs[0]["source"] == "get_content"
        assert trigger_refs[0]["target"] == "my_plugin_content"


class TestWordPressAjaxExtraction:
    """Tests for WordPress AJAX handler extraction."""

    def test_ajax_handler_authenticated(self, parser: PHPParser):
        """Test extracting authenticated AJAX handler."""
        source = b'''<?php
function handle_my_action() {
    wp_send_json_success(['data' => 'ok']);
}

add_action('wp_ajax_my_action', 'handle_my_action');
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        ajax_refs = [r for r in refs if r["type"] == "registers_action"
                     and r.get("metadata", {}).get("ajax_action")]
        assert len(ajax_refs) == 1
        assert ajax_refs[0]["metadata"]["ajax_action"] == "my_action"
        assert ajax_refs[0]["metadata"]["authenticated_only"] is True

    def test_ajax_handler_nopriv(self, parser: PHPParser):
        """Test extracting non-authenticated AJAX handler."""
        source = b'''<?php
function handle_public_action() {
    wp_send_json_success(['data' => 'ok']);
}

add_action('wp_ajax_nopriv_public_action', 'handle_public_action');
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        ajax_refs = [r for r in refs if r["type"] == "registers_action"
                     and r.get("metadata", {}).get("ajax_action")]
        assert len(ajax_refs) == 1
        assert ajax_refs[0]["metadata"]["ajax_action"] == "public_action"
        assert ajax_refs[0]["metadata"]["authenticated_only"] is False


class TestWordPressShortcodeExtraction:
    """Tests for WordPress shortcode extraction."""

    def test_shortcode_registration(self, parser: PHPParser):
        """Test extracting shortcode registration."""
        source = b'''<?php
function render_button($atts) {
    return '<button>Click</button>';
}

add_shortcode('button', 'render_button');
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        shortcode_refs = [r for r in refs if r["type"] == "registers_shortcode"]
        assert len(shortcode_refs) == 1
        assert shortcode_refs[0]["source"] == "render_button"
        assert shortcode_refs[0]["target"] == "[button]"
        assert shortcode_refs[0]["metadata"].get("shortcode_tag") == "button"

    def test_shortcode_with_class_method(self, parser: PHPParser):
        """Test extracting shortcode with class method callback."""
        source = b'''<?php
class ShortcodeHandler {
    public function __construct() {
        add_shortcode('gallery', [$this, 'renderGallery']);
    }

    public function renderGallery($atts) {
        return '<div class="gallery"></div>';
    }
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        shortcode_refs = [r for r in refs if r["type"] == "registers_shortcode"]
        assert len(shortcode_refs) == 1
        assert shortcode_refs[0]["source"] == "renderGallery"
        assert shortcode_refs[0]["target"] == "[gallery]"


class TestInheritanceEdges:
    """Tests for inheritance relationship extraction."""

    def test_class_inheritance_edge(self, parser: PHPParser):
        """Test extracting class inheritance edge."""
        source = b'''<?php
class Parent {}
class Child extends Parent {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        inherits = [r for r in refs if r["type"] == "inherits"]
        assert len(inherits) == 1
        assert inherits[0]["source"] == "Child"
        assert inherits[0]["target"] == "Parent"

    def test_implements_edge(self, parser: PHPParser):
        """Test extracting implements edge."""
        source = b'''<?php
interface ServiceInterface {}
class UserService implements ServiceInterface {}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        implements = [r for r in refs if r["type"] == "implements"]
        assert len(implements) == 1
        assert implements[0]["source"] == "UserService"
        assert implements[0]["target"] == "ServiceInterface"

    def test_trait_usage_edge(self, parser: PHPParser):
        """Test extracting trait usage edge."""
        source = b'''<?php
trait Loggable {}
class Service {
    use Loggable;
}
'''
        tree = parser.parse(source)
        refs = parser.extract_references(tree, source)

        uses_trait = [r for r in refs if r["type"] == "uses_trait"]
        assert len(uses_trait) == 1
        assert uses_trait[0]["source"] == "Service"
        assert uses_trait[0]["target"] == "Loggable"


class TestParseToResult:
    """Tests for the high-level parse_to_result method."""

    def test_parse_to_result(self, parser: PHPParser, tmp_path: Path):
        """Test complete parsing workflow."""
        source = '''<?php
namespace MyApp;

use MyApp\\Services\\UserService;

const VERSION = '1.0.0';

interface ServiceInterface {
    public function execute(): void;
}

abstract class BaseService implements ServiceInterface {
    protected string $name;

    public function getName(): string {
        return $this->name;
    }
}

class ConcreteService extends BaseService {
    public function execute(): void {
        $this->process();
    }

    private function process(): void {
    }
}

function helper_function(): void {
}
'''
        test_file = tmp_path / "test.php"
        test_file.write_text(source)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        node_kinds = {n.node_type for n in result.nodes}
        assert "namespace" in node_kinds
        assert "import" in node_kinds
        assert "constant" in node_kinds
        assert "interface" in node_kinds
        assert "class" in node_kinds
        assert "method" in node_kinds
        assert "function" in node_kinds
        assert "property" in node_kinds

        # Check edges
        edge_types = {e.edge_type for e in result.edges}
        assert "imports" in edge_types
        assert "inherits" in edge_types
        assert "implements" in edge_types
        assert "calls" in edge_types


class TestWordPressPluginFixture:
    """Tests using the WordPress plugin fixture."""

    @pytest.fixture
    def wordpress_source(self):
        """Load the WordPress plugin fixture."""
        fixture_path = Path(__file__).parent / "test_parser" / "fixtures" / "php" / "wordpress_plugin.php"
        if fixture_path.exists():
            return fixture_path.read_bytes()
        pytest.skip("WordPress plugin fixture not found")

    def test_plugin_namespace(self, parser: PHPParser, wordpress_source: bytes):
        """Test namespace extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        symbols = parser.extract_symbols(tree, wordpress_source)

        namespaces = [s for s in symbols if s["kind"] == "namespace"]
        assert len(namespaces) >= 1
        assert any(n["name"] == "SamplePlugin" for n in namespaces)

    def test_plugin_classes(self, parser: PHPParser, wordpress_source: bytes):
        """Test class extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        symbols = parser.extract_symbols(tree, wordpress_source)

        classes = [s for s in symbols if s["kind"] == "class"]
        class_names = [c["name"] for c in classes]

        assert "Plugin" in class_names
        assert "BaseWidget" in class_names
        assert "SampleWidget" in class_names

    def test_plugin_interfaces(self, parser: PHPParser, wordpress_source: bytes):
        """Test interface extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        symbols = parser.extract_symbols(tree, wordpress_source)

        interfaces = [s for s in symbols if s["kind"] == "interface"]
        assert any(i["name"] == "WidgetInterface" for i in interfaces)

    def test_plugin_traits(self, parser: PHPParser, wordpress_source: bytes):
        """Test trait extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        symbols = parser.extract_symbols(tree, wordpress_source)

        traits = [s for s in symbols if s["kind"] == "trait"]
        assert any(t["name"] == "LoggingTrait" for t in traits)

    def test_plugin_hooks(self, parser: PHPParser, wordpress_source: bytes):
        """Test WordPress hook extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        refs = parser.extract_references(tree, wordpress_source)

        action_hooks = [r for r in refs if r["type"] == "registers_action"]
        filter_hooks = [r for r in refs if r["type"] == "registers_filter"]

        # Check for expected action hooks
        action_targets = [h["target"] for h in action_hooks]
        assert "init" in action_targets
        assert "admin_menu" in action_targets
        assert "wp_enqueue_scripts" in action_targets

        # Check for expected filter hooks
        filter_targets = [h["target"] for h in filter_hooks]
        assert "the_content" in filter_targets
        assert "post_title" in filter_targets

    def test_plugin_ajax_handlers(self, parser: PHPParser, wordpress_source: bytes):
        """Test WordPress AJAX handler extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        refs = parser.extract_references(tree, wordpress_source)

        ajax_hooks = [r for r in refs if r["type"] == "registers_action"
                      and r.get("metadata", {}).get("ajax_action")]

        # Should have both authenticated and non-authenticated handlers
        assert len(ajax_hooks) >= 2

        auth_hooks = [h for h in ajax_hooks if h["metadata"].get("authenticated_only") is True]
        nopriv_hooks = [h for h in ajax_hooks if h["metadata"].get("authenticated_only") is False]

        assert len(auth_hooks) >= 1
        assert len(nopriv_hooks) >= 1

    def test_plugin_shortcodes(self, parser: PHPParser, wordpress_source: bytes):
        """Test WordPress shortcode extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        refs = parser.extract_references(tree, wordpress_source)

        shortcode_refs = [r for r in refs if r["type"] == "registers_shortcode"]
        shortcode_tags = [r["metadata"]["shortcode_tag"] for r in shortcode_refs]

        assert "sample" in shortcode_tags
        assert "quote" in shortcode_tags

    def test_plugin_hook_triggers(self, parser: PHPParser, wordpress_source: bytes):
        """Test WordPress hook trigger extraction from plugin fixture."""
        tree = parser.parse(wordpress_source)
        refs = parser.extract_references(tree, wordpress_source)

        action_triggers = [r for r in refs if r["type"] == "triggers_action"]
        filter_triggers = [r for r in refs if r["type"] == "triggers_filter"]

        # Check for do_action calls
        action_targets = [t["target"] for t in action_triggers]
        assert "sample_plugin_post_type_registered" in action_targets or \
               "sample_plugin_activated" in action_targets

        # Check for apply_filters calls
        filter_targets = [t["target"] for t in filter_triggers]
        assert "sample_plugin_content" in filter_targets


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: PHPParser):
        """Test parsing empty PHP file."""
        source = b"<?php"
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        refs = parser.extract_references(tree, source)

        assert symbols == []
        assert refs == []

    def test_syntax_error(self, parser: PHPParser):
        """Test parsing file with syntax errors."""
        source = b'''<?php
class Broken {
    public function test( {
'''
        tree = parser.parse(source)
        # Should still be able to parse what's possible
        assert tree.root_node.has_error

    def test_php_8_features(self, parser: PHPParser):
        """Test parsing PHP 8 features like constructor promotion."""
        source = b'''<?php
class User {
    public function __construct(
        public readonly string $name,
        private int $age = 0
    ) {}
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1

    def test_anonymous_class(self, parser: PHPParser):
        """Test handling anonymous classes."""
        source = b'''<?php
$logger = new class {
    public function log(string $msg): void {
        echo $msg;
    }
};
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)
        # Anonymous classes might not be extracted as named symbols
        # but should not cause errors

    def test_closure(self, parser: PHPParser):
        """Test handling closures."""
        source = b'''<?php
$callback = function(int $x): int {
    return $x * 2;
};

array_map(fn($x) => $x * 2, [1, 2, 3]);
'''
        tree = parser.parse(source)
        # Closures should not cause errors

    def test_heredoc(self, parser: PHPParser):
        """Test handling heredoc strings."""
        source = b'''<?php
$html = <<<HTML
<div>Hello World</div>
HTML;
'''
        tree = parser.parse(source)
        # Should not cause errors

    def test_attribute_php8(self, parser: PHPParser):
        """Test handling PHP 8 attributes."""
        source = b'''<?php
#[Route('/api/users')]
class UserController {
    #[Get]
    #[Auth('admin')]
    public function index(): array {
        return [];
    }
}
'''
        tree = parser.parse(source)
        symbols = parser.extract_symbols(tree, source)

        classes = [s for s in symbols if s["kind"] == "class"]
        assert len(classes) == 1
        assert classes[0]["name"] == "UserController"

        methods = [s for s in symbols if s["kind"] == "method"]
        assert len(methods) == 1
