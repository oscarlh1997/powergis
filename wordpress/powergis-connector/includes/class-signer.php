<?php
/**
 * Firma HMAC compartida con el motor Python.
 *
 * El esquema es idéntico en los dos lados:
 *
 *     payload = timestamp . "\n" . cuerpo_crudo
 *     firma   = hash_hmac( 'sha256', payload, secreto )
 *
 * Tres reglas que no son negociables:
 *
 * 1. Se firma el CUERPO CRUDO (`php://input`), nunca un JSON reserializado:
 *    dos serializadores producen bytes distintos y la firma dejaría de casar.
 * 2. Ventana temporal de 300 s contra reenvío.
 * 3. Comparación en tiempo constante con `hash_equals`. Un `===` sobre la
 *    firma filtra información por el tiempo de respuesta.
 *
 * Si cambias algo aquí, cambia `engine/src/powergis/api/security.py` a la vez.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Signer {

	public const HEADER_TIMESTAMP = 'X-PG-Timestamp';
	public const HEADER_SIGNATURE = 'X-PG-Signature';
	public const WINDOW_SECONDS   = 300;

	public static function secret(): string {
		if ( defined( 'POWERGIS_HMAC_SECRET' ) && '' !== POWERGIS_HMAC_SECRET ) {
			return (string) POWERGIS_HMAC_SECRET;
		}
		// Sin secreto no se firma nada: mejor fallar que enviar sin proteger.
		return '';
	}

	public static function compute( string $timestamp, string $body, ?string $secret = null ): string {
		$secret = $secret ?? self::secret();
		return hash_hmac( 'sha256', $timestamp . "\n" . $body, $secret );
	}

	/**
	 * Cabeceras para una petición saliente hacia el motor.
	 *
	 * @return array<string,string>
	 */
	public static function headers( string $body ): array {
		$timestamp = (string) time();
		return array(
			self::HEADER_TIMESTAMP => $timestamp,
			self::HEADER_SIGNATURE => self::compute( $timestamp, $body ),
		);
	}

	/**
	 * Cadena canónica de una petición GET.
	 *
	 * Un GET no tiene cuerpo, así que se firma `GET\nruta?query`. Sin esto,
	 * `GET /v1/reports/{uuid}` quedaría abierto: `wp_user_id` lo pone quien
	 * llama, y bastaría conocer un UUID para leer el informe de pago de otro.
	 *
	 * Equivalente en Python: `powergis.api.security.canonical_get`.
	 */
	public static function canonical_get( string $path, string $query = '' ): string {
		return "GET\n" . $path . ( '' !== $query ? '?' . $query : '' );
	}

	/**
	 * Cabeceras para un GET firmado.
	 *
	 * @return array<string,string>
	 */
	public static function headers_for_get( string $url ): array {
		$parts = wp_parse_url( $url );
		$path  = $parts['path'] ?? '/';
		$query = $parts['query'] ?? '';
		return self::headers( self::canonical_get( $path, $query ) );
	}

	/**
	 * Verifica una petición entrante (callback del motor).
	 *
	 * @return true|\WP_Error
	 */
	public static function verify_request( \WP_REST_Request $request ) {
		$secret = self::secret();
		if ( '' === $secret ) {
			return new \WP_Error(
				'powergis_no_secret',
				__( 'POWERGIS_HMAC_SECRET no está definido en wp-config.php', 'powergis' ),
				array( 'status' => 500 )
			);
		}

		$timestamp = $request->get_header( 'x_pg_timestamp' );
		$signature = $request->get_header( 'x_pg_signature' );

		if ( empty( $timestamp ) || empty( $signature ) ) {
			return new \WP_Error(
				'powergis_missing_signature',
				__( 'Faltan cabeceras de firma', 'powergis' ),
				array( 'status' => 401 )
			);
		}

		$drift = abs( time() - (int) $timestamp );
		if ( $drift > self::WINDOW_SECONDS ) {
			return new \WP_Error(
				'powergis_stale_request',
				__( 'Petición fuera de la ventana temporal', 'powergis' ),
				array( 'status' => 401 )
			);
		}

		$body     = $request->get_body();
		$expected = self::compute( (string) $timestamp, $body, $secret );

		if ( ! hash_equals( $expected, (string) $signature ) ) {
			return new \WP_Error(
				'powergis_invalid_signature',
				__( 'Firma no válida', 'powergis' ),
				array( 'status' => 401 )
			);
		}

		return true;
	}
}
