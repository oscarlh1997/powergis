<?php
/**
 * Stripe Checkout + webhook.
 *
 * El flujo correcto, y por qué cada paso es como es:
 *
 * 1. El precio NUNCA se fija en el cliente: se usa un `price_id` de Stripe.
 *    Si el importe viaja en el formulario, viaja manipulable.
 * 2. La sesión de Checkout se crea en el servidor con `metadata` que lleva el
 *    `project_uuid`: es lo que ata el pago al proyecto.
 * 3. El desbloqueo lo dispara el WEBHOOK, no `success_url`. La URL de éxito la
 *    puede visitar cualquiera sin haber pagado — es el fallo más común.
 * 4. Idempotencia por `event.id`: Stripe reenvía eventos y no puede cobrarse
 *    ni desbloquearse dos veces.
 * 5. Se manejan también `charge.refunded` y `charge.dispute.created` para
 *    retirar el acceso.
 *
 * Se usa la API REST de Stripe directamente con `wp_remote_post`: el SDK de
 * PHP arrastra dependencias que no hacen falta para tres llamadas.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Stripe {

	public const NAMESPACE     = 'saas/v1';
	private const API          = 'https://api.stripe.com/v1';
	private const EVENTS_TABLE = 'powergis_stripe_events';

	public static function hooks(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
		add_action( 'init', array( self::class, 'maybe_install_table' ) );
	}

	public static function register_routes(): void {
		register_rest_route(
			self::NAMESPACE,
			'/checkout',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'create_session' ),
				'permission_callback' => array( REST_Projects::class, 'can_read_project' ),
				'args'                => array(
					'id' => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/stripe/webhook',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				// La verificación es la propia firma de Stripe, dentro del handler.
				'permission_callback' => '__return_true',
				'callback'            => array( self::class, 'webhook' ),
			)
		);
	}

	// ------------------------------------------------------------------ //

	public static function checkout_url( int $post_id ): string {
		return add_query_arg( array( 'id' => $post_id ), rest_url( self::NAMESPACE . '/checkout' ) );
	}

	/**
	 * Crea la sesión de Checkout. Nada de importes desde el navegador.
	 */
	public static function create_session( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$post_id = (int) $request->get_param( 'id' );
		$uuid    = CPT::uuid_of( $post_id );

		if ( ! $uuid ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'El proyecto no tiene informe', 'powergis' ), array( 'status' => 409 ) );
		}
		if ( 'avanzado' === CPT::tier_of( $post_id ) ) {
			return new \WP_REST_Response( array( 'already_advanced' => true, 'url' => get_permalink( $post_id ) ), 200 );
		}

		$secret   = self::secret_key();
		$price_id = defined( 'POWERGIS_STRIPE_PRICE_ID' ) ? (string) POWERGIS_STRIPE_PRICE_ID : '';
		if ( '' === $secret || '' === $price_id ) {
			return new \WP_Error( 'powergis_stripe_config', __( 'Stripe sin configurar', 'powergis' ), array( 'status' => 500 ) );
		}

		$user = wp_get_current_user();
		$body = array(
			'mode'                        => 'payment',
			'success_url'                 => add_query_arg( 'pg_pago', 'ok', get_permalink( $post_id ) ),
			'cancel_url'                  => add_query_arg( 'pg_pago', 'cancelado', get_permalink( $post_id ) ),
			'client_reference_id'         => $uuid,
			'customer_email'              => $user->user_email,
			'line_items'                  => array( array( 'price' => $price_id, 'quantity' => 1 ) ),
			'metadata'                    => array(
				'project_uuid' => $uuid,
				'wp_post_id'   => (string) $post_id,
				'wp_user_id'   => (string) $user->ID,
			),
			'payment_intent_data'         => array(
				'metadata' => array( 'project_uuid' => $uuid, 'wp_post_id' => (string) $post_id ),
			),
			'automatic_tax'               => array( 'enabled' => true ),
			'billing_address_collection'  => 'required',
		);

		$response = wp_remote_post(
			self::API . '/checkout/sessions',
			array(
				'headers' => array(
					'Authorization'   => 'Bearer ' . $secret,
					'Content-Type'    => 'application/x-www-form-urlencoded',
					// Idempotencia también con Stripe: doble clic, una sesión.
					//
					// La ventana es de una hora, NO fija por UUID. Stripe cachea
					// una clave de idempotencia 24 h y una sesión de Checkout
					// caduca a las 24 h: con una clave fija, el usuario que
					// cancela y vuelve mañana recibe la sesión vieja, ya muerta,
					// y no puede pagar. Con el bucket horario, el doble clic
					// sigue devolviendo una sola sesión y el reintento tardío
					// crea una nueva.
					'Idempotency-Key' => 'pg_checkout_' . $uuid . '_' . (int) floor( time() / HOUR_IN_SECONDS ),
				),
				'body'    => self::encode( $body ),
				'timeout' => 20,
			)
		);

		if ( is_wp_error( $response ) ) {
			return $response;
		}

		$data = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( ! is_array( $data ) || empty( $data['url'] ) ) {
			Plugin::log( 'error', 'Stripe no devolvió URL de Checkout', array( 'post_id' => $post_id ) );
			return new \WP_Error( 'powergis_stripe_error', __( 'No se pudo iniciar el pago', 'powergis' ), array( 'status' => 502 ) );
		}

		return new \WP_REST_Response( array( 'url' => (string) $data['url'] ), 200 );
	}

	/**
	 * Webhook de Stripe. Aquí, y SOLO aquí, se desbloquea el informe.
	 */
	public static function webhook( \WP_REST_Request $request ): \WP_REST_Response {
		$payload   = $request->get_body();
		$signature = $request->get_header( 'stripe_signature' );

		if ( ! self::verify_stripe_signature( $payload, (string) $signature ) ) {
			Plugin::log( 'warning', 'Webhook de Stripe con firma no válida' );
			return new \WP_REST_Response( array( 'error' => 'invalid_signature' ), 400 );
		}

		$event = json_decode( $payload, true );
		if ( ! is_array( $event ) || empty( $event['id'] ) || empty( $event['type'] ) ) {
			return new \WP_REST_Response( array( 'error' => 'bad_payload' ), 400 );
		}

		// Idempotencia: Stripe reenvía. Un evento no se procesa dos veces.
		if ( self::already_processed( (string) $event['id'] ) ) {
			return new \WP_REST_Response( array( 'ok' => true, 'duplicate' => true ), 200 );
		}
		self::mark_processed( (string) $event['id'], (string) $event['type'] );

		$object = $event['data']['object'] ?? array();
		$uuid   = self::uuid_from( $object );

		switch ( $event['type'] ) {
			case 'checkout.session.completed':
				if ( 'paid' !== ( $object['payment_status'] ?? '' ) ) {
					break;  // pago aplazado: se espera al evento async
				}
				self::unlock( $uuid, (string) ( $object['payment_intent'] ?? '' ) );
				break;

			case 'checkout.session.async_payment_succeeded':
				self::unlock( $uuid, (string) ( $object['payment_intent'] ?? '' ) );
				break;

			case 'checkout.session.async_payment_failed':
				Plugin::log( 'warning', 'Pago aplazado fallido', array( 'uuid' => $uuid ) );
				break;

			case 'charge.refunded':
			case 'charge.dispute.created':
				self::lock( $uuid );
				break;
		}

		return new \WP_REST_Response( array( 'ok' => true ), 200 );
	}

	// ------------------------------------------------------------------ //

	private static function unlock( string $uuid, string $payment_reference ): void {
		if ( '' === $uuid ) {
			return;
		}
		$post = CPT::find_by_uuid( $uuid );
		if ( ! $post ) {
			Plugin::log( 'error', 'Pago sin proyecto asociado', array( 'uuid' => $uuid ) );
			return;
		}

		$client = new Engine_Client();
		$result = $client->upgrade_report( $uuid, array( 'payment_reference' => $payment_reference ) );

		if ( is_wp_error( $result ) ) {
			// El pago YA está cobrado: esto no se puede perder.
			Plugin::log( 'error', 'Upgrade falló tras el pago', array(
				'uuid'  => $uuid,
				'error' => $result->get_error_message(),
			) );
			update_post_meta( (int) $post->ID, CPT::META_ERROR, 'upgrade_failed:' . $result->get_error_message() );
			// Se reintenta en un minuto en vez de dejarlo perdido.
			wp_schedule_single_event( time() + 60, 'powergis_retry_upgrade', array( $uuid, $payment_reference ) );
			return;
		}

		// El tier sube ya: si el worker tarda, el usuario no ve un 403.
		CPT::set_tier( (int) $post->ID, 'avanzado' );
		update_post_meta( (int) $post->ID, CPT::META_STATUS, 'queued' );
		delete_post_meta( (int) $post->ID, CPT::META_ERROR );

		Plugin::log( 'info', 'Informe desbloqueado', array( 'post_id' => $post->ID ) );
		do_action( 'powergis_report_upgraded', (int) $post->ID );
	}

	private static function lock( string $uuid ): void {
		if ( '' === $uuid ) {
			return;
		}
		$post = CPT::find_by_uuid( $uuid );
		if ( ! $post ) {
			return;
		}
		( new Engine_Client() )->downgrade_report( $uuid );
		CPT::set_tier( (int) $post->ID, 'basico' );
		Plugin::log( 'info', 'Informe revertido a básico', array( 'post_id' => $post->ID ) );
		do_action( 'powergis_report_downgraded', (int) $post->ID );
	}

	/**
	 * @param array<string,mixed> $object
	 */
	private static function uuid_from( array $object ): string {
		$candidates = array(
			$object['metadata']['project_uuid'] ?? null,
			$object['client_reference_id'] ?? null,
		);
		foreach ( $candidates as $candidate ) {
			if ( is_string( $candidate ) && wp_is_uuid( $candidate ) ) {
				return $candidate;
			}
		}
		return '';
	}

	/**
	 * Verificación de la firma de Stripe (esquema `t=...,v1=...`).
	 */
	private static function verify_stripe_signature( string $payload, string $header ): bool {
		$secret = defined( 'POWERGIS_STRIPE_WEBHOOK_SECRET' ) ? (string) POWERGIS_STRIPE_WEBHOOK_SECRET : '';
		if ( '' === $secret || '' === $header ) {
			return false;
		}

		$timestamp = '';
		$signatures = array();
		foreach ( explode( ',', $header ) as $part ) {
			$pair = explode( '=', trim( $part ), 2 );
			if ( 2 !== count( $pair ) ) {
				continue;
			}
			if ( 't' === $pair[0] ) {
				$timestamp = $pair[1];
			} elseif ( 'v1' === $pair[0] ) {
				$signatures[] = $pair[1];
			}
		}

		if ( '' === $timestamp || empty( $signatures ) ) {
			return false;
		}
		if ( abs( time() - (int) $timestamp ) > 300 ) {
			return false;  // anti-reenvío
		}

		$expected = hash_hmac( 'sha256', $timestamp . '.' . $payload, $secret );
		foreach ( $signatures as $signature ) {
			if ( hash_equals( $expected, $signature ) ) {
				return true;
			}
		}
		return false;
	}

	private static function secret_key(): string {
		return defined( 'POWERGIS_STRIPE_SECRET' ) ? (string) POWERGIS_STRIPE_SECRET : '';
	}

	/**
	 * @param array<string,mixed> $data
	 */
	private static function encode( array $data, string $prefix = '' ): string {
		$parts = array();
		foreach ( $data as $key => $value ) {
			$name = '' === $prefix ? (string) $key : $prefix . '[' . $key . ']';
			if ( is_array( $value ) ) {
				$parts[] = self::encode( $value, $name );
			} elseif ( is_bool( $value ) ) {
				$parts[] = rawurlencode( $name ) . '=' . ( $value ? 'true' : 'false' );
			} elseif ( null !== $value ) {
				$parts[] = rawurlencode( $name ) . '=' . rawurlencode( (string) $value );
			}
		}
		return implode( '&', array_filter( $parts ) );
	}

	// -- idempotencia ------------------------------------------------------ //

	public static function maybe_install_table(): void {
		global $wpdb;
		$table = $wpdb->prefix . self::EVENTS_TABLE;
		if ( get_option( 'powergis_stripe_table_version' ) === '1' ) {
			return;
		}
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		$charset = $wpdb->get_charset_collate();
		dbDelta(
			"CREATE TABLE {$table} (
				event_id varchar(128) NOT NULL,
				event_type varchar(64) NOT NULL,
				processed_at datetime NOT NULL,
				PRIMARY KEY  (event_id)
			) {$charset};"
		);
		update_option( 'powergis_stripe_table_version', '1' );
	}

	private static function already_processed( string $event_id ): bool {
		global $wpdb;
		$table = $wpdb->prefix . self::EVENTS_TABLE;
		// phpcs:ignore WordPress.DB.DirectDatabaseQuery
		return (bool) $wpdb->get_var(
			$wpdb->prepare( "SELECT 1 FROM {$table} WHERE event_id = %s", $event_id )
		);
	}

	private static function mark_processed( string $event_id, string $event_type ): void {
		global $wpdb;
		$table = $wpdb->prefix . self::EVENTS_TABLE;
		// phpcs:ignore WordPress.DB.DirectDatabaseQuery
		$wpdb->insert(
			$table,
			array(
				'event_id'     => $event_id,
				'event_type'   => $event_type,
				'processed_at' => current_time( 'mysql' ),
			),
			array( '%s', '%s', '%s' )
		);
	}
}

add_action(
	'powergis_retry_upgrade',
	static function ( string $uuid, string $reference ): void {
		$result = ( new Engine_Client() )->upgrade_report( $uuid, array( 'payment_reference' => $reference ) );
		if ( is_wp_error( $result ) ) {
			Plugin::log( 'error', 'Reintento de upgrade también falló', array( 'uuid' => $uuid ) );
		}
	},
	10,
	2
);
