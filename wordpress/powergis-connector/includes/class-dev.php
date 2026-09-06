<?php
/**
 * Utilidades de desarrollo.
 *
 * Todo lo de este fichero está APAGADO salvo que `POWERGIS_DEV_MODE` esté
 * definido a `true` en wp-config.php. Y aun así, cada ruta exige capacidad
 * `manage_options`. Nunca lo actives en producción: el simulador de pago
 * desbloquea informes de pago sin pasar por Stripe.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Dev {

	public const NAMESPACE = 'saas/v1';

	public static function enabled(): bool {
		return defined( 'POWERGIS_DEV_MODE' ) && POWERGIS_DEV_MODE;
	}

	public static function hooks(): void {
		if ( ! self::enabled() ) {
			return;
		}
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
		add_action( 'admin_notices', array( self::class, 'notice' ) );
	}

	public static function notice(): void {
		echo '<div class="notice notice-warning"><p><strong>PowerGIS:</strong> '
			. esc_html__( 'modo desarrollo activo. El simulador de pago está habilitado — no lo dejes así en producción.', 'powergis' )
			. '</p></div>';
	}

	public static function register_routes(): void {
		register_rest_route(
			self::NAMESPACE,
			'/dev/simulate-payment',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'simulate_payment' ),
				'permission_callback' => array( self::class, 'can_use' ),
				'args'                => array(
					'id' => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/dev/ping-engine',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'ping_engine' ),
				'permission_callback' => array( self::class, 'can_use' ),
			)
		);
	}

	/**
	 * @return true|\WP_Error
	 */
	public static function can_use() {
		if ( ! self::enabled() ) {
			return new \WP_Error( 'powergis_dev_off', __( 'Modo desarrollo desactivado', 'powergis' ), array( 'status' => 404 ) );
		}
		if ( ! current_user_can( 'manage_options' ) ) {
			return new \WP_Error( 'powergis_forbidden', __( 'Solo administradores', 'powergis' ), array( 'status' => 403 ) );
		}
		return true;
	}

	/**
	 * Simula el webhook `checkout.session.completed` de Stripe.
	 *
	 * Hace exactamente lo mismo que haría el webhook real: llama al motor para
	 * el upgrade y sube el tier. Sirve para probar el flujo básico → avanzado
	 * sin configurar Stripe ni exponer un webhook a internet.
	 */
	public static function simulate_payment( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$post_id = (int) $request->get_param( 'id' );
		$uuid    = CPT::uuid_of( $post_id );

		if ( ! $uuid ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'El proyecto no tiene informe', 'powergis' ), array( 'status' => 409 ) );
		}

		$result = ( new Engine_Client() )->upgrade_report(
			$uuid,
			array( 'payment_reference' => 'dev_simulado_' . time() )
		);

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		CPT::set_tier( $post_id, 'avanzado' );
		update_post_meta( $post_id, CPT::META_STATUS, 'queued' );
		delete_post_meta( $post_id, CPT::META_ERROR );

		Plugin::log( 'info', 'Pago SIMULADO (modo desarrollo)', array( 'post_id' => $post_id ) );

		return new \WP_REST_Response(
			array(
				'ok'        => true,
				'post_id'   => $post_id,
				'tier'      => 'avanzado',
				'run'       => $result,
				'permalink' => get_permalink( $post_id ),
			),
			200
		);
	}

	/**
	 * Comprueba el apretón de manos HMAC de punta a punta.
	 *
	 * Es el primer sitio donde mirar cuando «no funciona»: dice si el motor
	 * responde y si los dos lados comparten el mismo secreto.
	 */
	public static function ping_engine(): \WP_REST_Response {
		$base = Engine_Client::base_url();
		$out  = array(
			'engine_url'    => $base,
			'secret_length' => strlen( Signer::secret() ),
		);

		if ( '' === $base ) {
			$out['error'] = 'POWERGIS_ENGINE_URL sin definir';
			return new \WP_REST_Response( $out, 200 );
		}

		$health          = wp_remote_get( $base . '/health', array( 'timeout' => 8 ) );
		$out['health']   = is_wp_error( $health ) ? $health->get_error_message()
			: (int) wp_remote_retrieve_response_code( $health );

		// Prueba de firma: una búsqueda geográfica firmada. Si el secreto no
		// coincide en los dos lados, esto devuelve 401 y ya sabes dónde mirar.
		$geo = ( new Engine_Client() )->search_geo( 'Madrid', 'ccaa' );
		if ( is_wp_error( $geo ) ) {
			$out['hmac'] = 'ERROR: ' . $geo->get_error_message();
			$out['pista'] = 'invalid_signature = HMAC_SECRET distinto en motor y wp-config.php';
		} else {
			$out['hmac']      = 'OK';
			$out['geo_hits']  = is_array( $geo ) ? count( $geo ) : 0;
			$out['geo_first'] = $geo[0]['name'] ?? null;
		}

		return new \WP_REST_Response( $out, 200 );
	}
}
