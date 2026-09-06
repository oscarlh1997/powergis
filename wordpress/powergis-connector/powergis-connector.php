<?php
/**
 * Plugin Name:       PowerGIS Connector
 * Plugin URI:        https://powergis.es
 * Description:       Conecta WordPress con el motor de informes de PowerGIS: CPT de proyectos, endpoints firmados, Stripe Checkout y render del informe desde el payload JSON.
 * Version:           1.0.0
 * Requires at least: 6.4
 * Requires PHP:      8.1
 * Author:            PowerGIS
 * Text Domain:       powergis
 *
 * WordPress capta, identifica, presenta y vende. El motor ingiere, calcula,
 * almacena y exporta. Este plugin es la frontera entre los dos y no calcula
 * ni un solo indicador.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'POWERGIS_VERSION', '1.0.0' );
define( 'POWERGIS_FILE', __FILE__ );
define( 'POWERGIS_PATH', plugin_dir_path( __FILE__ ) );
define( 'POWERGIS_URL', plugin_dir_url( __FILE__ ) );

/**
 * Los secretos NO viven en la tabla `options`: se definen en wp-config.php.
 *
 *   define( 'POWERGIS_ENGINE_URL',   'https://motor.powergis.es' );
 *   define( 'POWERGIS_HMAC_SECRET',  '...' );   // el mismo que HMAC_SECRET del motor
 *   define( 'POWERGIS_STRIPE_SECRET','sk_live_...' );
 *   define( 'POWERGIS_STRIPE_WEBHOOK_SECRET', 'whsec_...' );
 *   define( 'POWERGIS_STRIPE_PRICE_ID', 'price_...' );
 */

require_once POWERGIS_PATH . 'includes/class-signer.php';
require_once POWERGIS_PATH . 'includes/class-engine-client.php';
require_once POWERGIS_PATH . 'includes/class-cpt.php';
require_once POWERGIS_PATH . 'includes/class-form-mapper.php';
require_once POWERGIS_PATH . 'includes/class-geo-resolver.php';
require_once POWERGIS_PATH . 'includes/class-rest-projects.php';
require_once POWERGIS_PATH . 'includes/class-rest-callback.php';
require_once POWERGIS_PATH . 'includes/class-stripe.php';
require_once POWERGIS_PATH . 'includes/class-render.php';
require_once POWERGIS_PATH . 'includes/class-form.php';
require_once POWERGIS_PATH . 'includes/class-dev.php';
require_once POWERGIS_PATH . 'includes/class-settings.php';
require_once POWERGIS_PATH . 'includes/class-plugin.php';

add_action(
	'plugins_loaded',
	static function (): void {
		\PowerGIS\Plugin::instance()->boot();
	}
);

register_activation_hook(
	__FILE__,
	static function (): void {
		\PowerGIS\CPT::register();
		\PowerGIS\CPT::seed_terms();
		flush_rewrite_rules();
	}
);

register_deactivation_hook(
	__FILE__,
	static function (): void {
		flush_rewrite_rules();
		wp_clear_scheduled_hook( 'powergis_poll_pending_reports' );
	}
);
