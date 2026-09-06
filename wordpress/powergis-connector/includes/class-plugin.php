<?php
/**
 * Arranque del plugin.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Plugin {

	private static ?self $instance = null;

	public static function instance(): self {
		return self::$instance ??= new self();
	}

	public function boot(): void {
		CPT::hooks();
		REST_Projects::hooks();
		REST_Callback::hooks();
		Stripe::hooks();
		Render::hooks();
		Form::hooks();
		Settings::hooks();
		Dev::hooks();   // no hace nada salvo con POWERGIS_DEV_MODE

		load_plugin_textdomain( 'powergis', false, dirname( plugin_basename( POWERGIS_FILE ) ) . '/languages' );
	}

	/**
	 * Log estructurado. En producción va al error_log; con un hook se puede
	 * enviar a n8n, Slack o Sentry sin tocar este fichero.
	 *
	 * @param array<string,mixed> $context
	 */
	public static function log( string $level, string $message, array $context = array() ): void {
		do_action( 'powergis_log', $level, $message, $context );

		if ( ! defined( 'WP_DEBUG' ) || ! WP_DEBUG ) {
			if ( ! in_array( $level, array( 'error', 'warning' ), true ) ) {
				return;
			}
		}
		error_log( sprintf(   // phpcs:ignore WordPress.PHP.DevelopmentFunctions
			'[powergis][%s] %s %s',
			$level,
			$message,
			$context ? (string) wp_json_encode( $context ) : ''
		) );
	}
}
