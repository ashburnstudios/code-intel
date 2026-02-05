<?php
/**
 * Plugin Name: Sample WordPress Plugin
 * Description: A sample plugin for testing code-intel PHP parser
 * Version: 1.0.0
 */

namespace SamplePlugin;

use WP_Query;
use WP_Post;
use SamplePlugin\Admin\Settings as AdminSettings;

// Constants
const PLUGIN_VERSION = '1.0.0';
define('SAMPLE_PLUGIN_PATH', __FILE__);

/**
 * Main plugin class.
 */
class Plugin {
    /** @var Plugin|null Singleton instance */
    private static ?Plugin $instance = null;

    /** @var string Plugin version */
    private string $version = '1.0.0';

    /** @var array Plugin settings */
    protected array $settings = [];

    /**
     * Get singleton instance.
     *
     * @return Plugin
     */
    public static function getInstance(): Plugin {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    /**
     * Constructor.
     */
    private function __construct() {
        $this->initHooks();
    }

    /**
     * Initialize WordPress hooks.
     */
    private function initHooks(): void {
        // Action hooks
        add_action('init', [$this, 'registerPostType']);
        add_action('admin_menu', [$this, 'addAdminMenu']);
        add_action('wp_enqueue_scripts', 'sample_plugin_enqueue_assets');

        // Filter hooks
        add_filter('the_content', [$this, 'filterContent']);
        add_filter('post_title', array($this, 'filterTitle'), 10, 2);

        // AJAX handlers
        add_action('wp_ajax_sample_action', [$this, 'handleAjax']);
        add_action('wp_ajax_nopriv_sample_action', [$this, 'handleAjaxNoPriv']);

        // Shortcodes
        add_shortcode('sample', [$this, 'renderShortcode']);
        add_shortcode('quote', 'render_quote_shortcode');
    }

    /**
     * Register custom post type.
     */
    public function registerPostType(): void {
        register_post_type('sample_post', [
            'label' => 'Sample Posts',
            'public' => true,
        ]);

        // Trigger custom action
        do_action('sample_plugin_post_type_registered');
    }

    /**
     * Add admin menu.
     */
    public function addAdminMenu(): void {
        add_menu_page(
            'Sample Plugin',
            'Sample',
            'manage_options',
            'sample-plugin',
            [$this, 'renderAdminPage']
        );
    }

    /**
     * Render admin page.
     */
    public function renderAdminPage(): void {
        echo '<div class="wrap"><h1>Sample Plugin</h1></div>';
    }

    /**
     * Filter content.
     *
     * @param string $content The post content.
     * @return string Modified content.
     */
    public function filterContent(string $content): string {
        // Apply custom filter
        $content = apply_filters('sample_plugin_content', $content);
        return $content;
    }

    /**
     * Filter post title.
     *
     * @param string $title The post title.
     * @param int $post_id The post ID.
     * @return string Modified title.
     */
    public function filterTitle(string $title, int $post_id): string {
        return $title;
    }

    /**
     * Handle AJAX request (authenticated).
     */
    public function handleAjax(): void {
        check_ajax_referer('sample_nonce');
        wp_send_json_success(['message' => 'Success']);
    }

    /**
     * Handle AJAX request (non-authenticated).
     */
    public function handleAjaxNoPriv(): void {
        wp_send_json_error(['message' => 'Not allowed']);
    }

    /**
     * Render shortcode.
     *
     * @param array $atts Shortcode attributes.
     * @param string|null $content Shortcode content.
     * @return string Rendered output.
     */
    public function renderShortcode(array $atts, ?string $content = null): string {
        $atts = shortcode_atts([
            'id' => 0,
            'class' => 'default',
        ], $atts);

        return sprintf('<div class="%s">%s</div>', esc_attr($atts['class']), esc_html($content));
    }
}

/**
 * Simple interface for widgets.
 */
interface WidgetInterface {
    public function render(): string;
    public function getId(): int;
}

/**
 * Base widget class.
 */
abstract class BaseWidget implements WidgetInterface {
    protected int $id;
    protected string $title;

    public function __construct(int $id, string $title) {
        $this->id = $id;
        $this->title = $title;
    }

    public function getId(): int {
        return $this->id;
    }

    abstract public function render(): string;
}

/**
 * Trait for logging functionality.
 */
trait LoggingTrait {
    protected function log(string $message): void {
        error_log("[SamplePlugin] {$message}");
    }

    protected function logError(string $error): void {
        error_log("[SamplePlugin ERROR] {$error}");
    }
}

/**
 * Concrete widget implementation.
 */
class SampleWidget extends BaseWidget {
    use LoggingTrait;

    private array $options = [];

    public function __construct(int $id, string $title, array $options = []) {
        parent::__construct($id, $title);
        $this->options = $options;
    }

    public function render(): string {
        $this->log("Rendering widget {$this->id}");
        return sprintf('<div class="widget">%s</div>', esc_html($this->title));
    }

    public function setOptions(array $options): void {
        $this->options = $options;
    }
}

// Standalone functions

/**
 * Enqueue plugin assets.
 */
function sample_plugin_enqueue_assets(): void {
    wp_enqueue_style('sample-plugin', plugins_url('css/style.css', __FILE__));
    wp_enqueue_script('sample-plugin', plugins_url('js/script.js', __FILE__), ['jquery'], '1.0.0', true);
}

/**
 * Render quote shortcode.
 *
 * @param array $atts Shortcode attributes.
 * @param string|null $content Shortcode content.
 * @return string Rendered quote.
 */
function render_quote_shortcode(array $atts, ?string $content = null): string {
    $atts = shortcode_atts([
        'author' => '',
        'cite' => '',
    ], $atts);

    $output = '<blockquote>';
    $output .= esc_html($content);
    if ($atts['author']) {
        $output .= '<cite>' . esc_html($atts['author']) . '</cite>';
    }
    $output .= '</blockquote>';

    return $output;
}

/**
 * Plugin activation hook.
 */
function sample_plugin_activate(): void {
    // Create database tables, etc.
    do_action('sample_plugin_activated');
}

/**
 * Plugin deactivation hook.
 */
function sample_plugin_deactivate(): void {
    // Cleanup
    do_action('sample_plugin_deactivated');
}

// Hook into WordPress activation/deactivation
register_activation_hook(__FILE__, 'sample_plugin_activate');
register_deactivation_hook(__FILE__, 'sample_plugin_deactivate');

// Initialize plugin
add_action('plugins_loaded', function() {
    Plugin::getInstance();
});
