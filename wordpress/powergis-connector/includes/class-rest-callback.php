<?php
/**
 * Callback del motor.
 *
 * Esta ruta la llama una máquina, no un navegador: se autentica con firma
 * HMAC, no con nonce. Un token en la query string no vale — queda en logs de
 * acceso, en el Referer y en el historial de proxies.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class REST_Callback {

	public const NAMESPACE = 'saas/v1';

	public static function hooks(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
		add_action( 'powergis_poll_pending_reports', array( self::class, 'poll_pending' ) );

		if ( ! wp_next_scheduled( 'powergis_poll_pending_reports' ) ) {
			wp_schedule_event( time() + 300, 'hourly', 'powergis_poll_pending_reports' );
		}
	}

	/**
	 * URL que se le da al motor para avisar de que el informe está listo.
	 *
	 * Se puede sobreescribir con `POWERGIS_CALLBACK_URL` en wp-config.php.
	 * Hace falta cuando el motor alcanza WordPress por una red interna con un
	 * nombre distinto al público (Docker, VPC, VPN).
	 */
	public static function url(): string {
		if ( defined( 'POWERGIS_CALLBACK_URL' ) && '' !== POWERGIS_CALLBACK_URL ) {
			return (string) POWERGIS_CALLBACK_URL;
		}
		return rest_url( self::NAMESPACE . '/projects/callback' );
	}

	public static function register_routes(): void {
		register_rest_route(
			self::NAMESPACE,
			'/projects/callback',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'handle' ),
				'permission_callback' => array( Signer::class, 'verify_request' ),
				'args'                => array(
					'project_uuid' => array(
						'type'              => 'string',
						'required'          => true,
						'validate_callback' => static fn( $v ): bool => (bool) wp_is_uuid( (string) $v ),
					),
					'status'       => array(
						'type'     => 'string',
						'required' => true,
						'enum'     => array( 'queued', 'running', 'partial', 'done', 'failed', 'narrative_ready' ),
					),
					'tier'         => array( 'type' => 'string', 'required' => false, 'enum' => array( 'basico', 'avanzado' ) ),
					'version'      => array( 'type' => 'integer', 'required' => false, 'minimum' => 0 ),
				),
			)
		);
	}

	public static function handle( \WP_REST_Request $request ): \WP_REST_Response {
		$uuid   = (string) $request->get_param( 'project_uuid' );
		$status = (string) $request->get_param( 'status' );
		$post   = CPT::find_by_uuid( $uuid );

		if ( ! $post ) {
			// 200 a propósito: si devolviéramos 404, el motor reintentaría en
			// bucle un callback que nunca va a encajar.
			Plugin::log( 'warning', 'Callback de un proyecto desconocido', array( 'uuid' => $uuid ) );
			return new \WP_REST_Response( array( 'ok' => false, 'reason' => 'unknown_project' ), 200 );
		}

		$post_id = (int) $post->ID;
		update_post_meta( $post_id, CPT::META_STATUS, $status );
		update_post_meta( $post_id, CPT::META_UPDATED, current_time( 'mysql' ) );

		if ( null !== $request->get_param( 'version' ) ) {
			update_post_meta( $post_id, CPT::META_VERSION, (int) $request->get_param( 'version' ) );
		}

		if ( 'failed' === $status ) {
			$error = $request->get_param( 'error' );
			update_post_meta( $post_id, CPT::META_ERROR, wp_json_encode( $error ) );
			Plugin::log( 'error', 'Informe fallido', array( 'post_id' => $post_id, 'error' => $error ) );
			do_action( 'powergis_report_failed', $post_id, $error );
			return new \WP_REST_Response( array( 'ok' => true ), 200 );
		}

		if ( in_array( $status, array( 'done', 'partial' ), true ) ) {
			delete_post_meta( $post_id, CPT::META_ERROR );

			$tier = (string) ( $request->get_param( 'tier' ) ?: 'basico' );
			CPT::set_tier( $post_id, $tier );
			self::assign_location( $post_id );

			if ( 'publish' !== $post->post_status ) {
				wp_update_post( array( 'ID' => $post_id, 'post_status' => 'publish' ) );
			}

			self::purge_cache( $post_id );
			do_action( 'powergis_report_ready', $post_id, $tier, (int) $request->get_param( 'version' ) );
		}

		if ( 'narrative_ready' === $status ) {
			self::purge_cache( $post_id );
			do_action( 'powergis_narrative_ready', $post_id );
		}

		return new \WP_REST_Response( array( 'ok' => true, 'post_id' => $post_id ), 200 );
	}

	/**
	 * Asigna el término de `location` a partir del ámbito guardado.
	 */
	private static function assign_location( int $post_id ): void {
		$scope = json_decode( (string) get_post_meta( $post_id, CPT::META_SCOPE, true ), true );
		if ( ! is_array( $scope ) || empty( $scope['ine_code'] ) ) {
			return;
		}
		$slug = sanitize_key( ( $scope['level'] ?? 'zona' ) . '-' . $scope['ine_code'] );
		$term = term_exists( $slug, CPT::TAX_LOC );
		if ( ! $term ) {
			$term = wp_insert_term( strtoupper( (string) $scope['ine_code'] ), CPT::TAX_LOC, array( 'slug' => $slug ) );
		}
		if ( ! is_wp_error( $term ) ) {
			wp_set_object_terms( $post_id, $slug, CPT::TAX_LOC, false );
		}
	}

	/**
	 * Purga la caché de página. Sin esto el usuario ve el informe viejo.
	 */
	private static function purge_cache( int $post_id ): void {
		if ( function_exists( 'litespeed_purge_single_post' ) ) {
			litespeed_purge_single_post( $post_id );
		}
		do_action( 'litespeed_purge_post', $post_id );
		if ( function_exists( 'wp_cache_post_change' ) ) {
			wp_cache_post_change( $post_id );
		}
		clean_post_cache( $post_id );
	}

	/**
	 * Red de seguridad: si un callback se pierde, se sondea el estado.
	 *
	 * Un callback perdido no puede dejar a un cliente mirando «generando…»
	 * para siempre.
	 */
	public static function poll_pending(): void {
		$query = new \WP_Query(
			array(
				'post_type'      => CPT::POST_TYPE,
				'post_status'    => array( 'draft', 'pending' ),
				'posts_per_page' => 25,
				'no_found_rows'  => true,
				'meta_query'     => array(
					array(
						'key'     => CPT::META_STATUS,
						'value'   => array( 'queued', 'running' ),
						'compare' => 'IN',
					),
				),
			)
		);

		$client = new Engine_Client();
		foreach ( $query->posts as $post ) {
			$uuid = CPT::uuid_of( (int) $post->ID );
			if ( ! $uuid ) {
				continue;
			}
			$payload = $client->get_report( $uuid, (int) $post->post_author );
			if ( is_wp_error( $payload ) ) {
				continue;  // todavía no está listo
			}
			update_post_meta( (int) $post->ID, CPT::META_STATUS, 'done' );
			update_post_meta( (int) $post->ID, CPT::META_VERSION, (int) ( $payload['version'] ?? 1 ) );
			CPT::set_tier( (int) $post->ID, (string) ( $payload['tier'] ?? 'basico' ) );
			wp_update_post( array( 'ID' => $post->ID, 'post_status' => 'publish' ) );
			self::purge_cache( (int) $post->ID );
			Plugin::log( 'info', 'Informe recuperado por sondeo', array( 'post_id' => $post->ID ) );
		}
	}
}
