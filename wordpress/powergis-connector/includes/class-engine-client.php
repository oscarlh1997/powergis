<?php
/**
 * Cliente HTTP hacia el motor.
 *
 * Todas las llamadas van firmadas y con `Idempotency-Key`: un doble submit del
 * formulario o un reintento de WordPress no deben crear dos ejecuciones.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Engine_Client {

	/** Opción con la URL del motor. SOLO se usa si no hay constante. */
	public const URL_OPTION = 'powergis_engine_url_pruebas';

	private string $base_url;
	private int $timeout;

	public function __construct( ?string $base_url = null, int $timeout = 20 ) {
		$this->base_url = rtrim( $base_url ?? self::base_url(), '/' );
		$this->timeout  = $timeout;
	}

	/**
	 * De dónde sale la URL del motor.
	 *
	 * La constante de `wp-config.php` manda SIEMPRE. Si no está definida, se
	 * mira una opción editable desde el escritorio.
	 *
	 * Por qué esa excepción, y por qué sólo para la URL:
	 *
	 * Al probar con un túnel efímero (`trycloudflare.com`), el nombre público
	 * cambia en cada arranque. Sin esto habría que entrar por FTP a editar
	 * `wp-config.php` en cada sesión de pruebas, que es la clase de fricción
	 * que hace que la gente deje de probar.
	 *
	 * El SECRETO nunca sale de aquí: `Signer::secret()` sigue leyendo sólo la
	 * constante. La diferencia importa — una URL en la base de datos permite,
	 * a quien ya tenga acceso de administrador, redirigir las llamadas a un
	 * motor suyo; un secreto en la base de datos se lo regala a cualquiera
	 * que consiga un volcado. Por eso uno se relaja y el otro no.
	 *
	 * En producción define la constante y esta opción queda inerte.
	 */
	public static function base_url(): string {
		if ( defined( 'POWERGIS_ENGINE_URL' ) && '' !== POWERGIS_ENGINE_URL ) {
			return rtrim( (string) POWERGIS_ENGINE_URL, '/' );
		}
		return rtrim( (string) get_option( self::URL_OPTION, '' ), '/' );
	}

	/** True si la URL viene de la opción y no de la constante. */
	public static function url_es_provisional(): bool {
		return ! ( defined( 'POWERGIS_ENGINE_URL' ) && '' !== POWERGIS_ENGINE_URL )
			&& '' !== (string) get_option( self::URL_OPTION, '' );
	}

	/**
	 * Cabeceras que van en TODAS las llamadas al motor.
	 *
	 * `ngrok-skip-browser-warning` existe por una razón concreta: el plan
	 * gratuito de ngrok interpone una página de aviso que el visitante tiene
	 * que pulsar. Una llamada de servidor a servidor no pulsa nada, así que
	 * recibiría ese HTML en vez de la respuesta del motor y fallaría al
	 * interpretar el JSON, con un error que no menciona a ngrok por ningún
	 * lado. Con la cabecera puesta, ngrok deja pasar.
	 *
	 * Contra un motor normal es una cabecera de más que nadie lee. Cuesta
	 * nada y ahorra una tarde.
	 *
	 * @return array<string,string>
	 */
	private static function cabeceras_base(): array {
		return array( 'ngrok-skip-browser-warning' => 'true' );
	}

	public function is_configured(): bool {
		return '' !== $this->base_url && '' !== Signer::secret();
	}

	/**
	 * Crea (o reutiliza) una ejecución de informe.
	 *
	 * @param array<string,mixed> $payload Cuerpo ya validado.
	 * @return array<string,mixed>|\WP_Error
	 */
	public function create_report( array $payload, string $idempotency_key ) {
		return $this->post( '/v1/reports', $payload, array( 'Idempotency-Key' => $idempotency_key ) );
	}

	/**
	 * Promueve un informe a avanzado. Solo lo llama el webhook de Stripe.
	 *
	 * @return array<string,mixed>|\WP_Error
	 */
	public function upgrade_report( string $uuid, array $payload = array() ) {
		return $this->post( '/v1/reports/' . rawurlencode( $uuid ) . '/upgrade', $payload );
	}

	/**
	 * @return array<string,mixed>|\WP_Error
	 */
	public function downgrade_report( string $uuid ) {
		return $this->post( '/v1/reports/' . rawurlencode( $uuid ) . '/downgrade', array() );
	}

	/**
	 * Payload del informe. El tier lo decide el motor con el estado del
	 * proyecto: aquí no se pide nunca «dame el avanzado».
	 *
	 * @return array<string,mixed>|\WP_Error
	 */
	public function get_report( string $uuid, int $wp_user_id, ?int $version = null ) {
		$args = array( 'wp_user_id' => $wp_user_id );
		if ( null !== $version ) {
			$args['version'] = $version;
		}
		return $this->get( '/v1/reports/' . rawurlencode( $uuid ), $args );
	}

	/**
	 * @return array<string,mixed>|\WP_Error
	 */
	public function search_geo( string $query, ?string $level = null ) {
		$args = array( 'q' => $query, 'limit' => 20 );
		if ( $level ) {
			$args['level'] = $level;
		}
		return $this->get( '/v1/geo/search', $args );
	}

	/**
	 * @return array<string,mixed>|\WP_Error
	 */
	public function children( string $level, string $code, ?string $child_level = null ) {
		$path = sprintf( '/v1/geo/%s/%s/children', rawurlencode( $level ), rawurlencode( $code ) );
		return $this->get( $path, $child_level ? array( 'child_level' => $child_level ) : array() );
	}

	/**
	 * URL de descarga de una exportación (xlsx | pdf | pptx).
	 */
	public function export_url( string $uuid, string $kind, int $wp_user_id ): string {
		return add_query_arg(
			array( 'wp_user_id' => $wp_user_id ),
			sprintf( '%s/v1/reports/%s/export/%s', $this->base_url, rawurlencode( $uuid ), rawurlencode( $kind ) )
		);
	}

	/**
	 * Descarga una exportación firmada. Nunca se da esta URL al navegador:
	 * la petición sale de servidor a servidor y WordPress hace de proxy.
	 *
	 * @return array{body:string,content_type:string}|\WP_Error
	 */
	public function fetch_export( string $uuid, string $kind, int $wp_user_id ) {
		$url      = $this->export_url( $uuid, $kind, $wp_user_id );
		$response = wp_remote_get(
			$url,
			array(
				'timeout' => 120,
				'headers' => array_merge( self::cabeceras_base(), Signer::headers_for_get( $url ) ),
			)
		);
		if ( is_wp_error( $response ) ) {
			return $response;
		}
		if ( 200 !== (int) wp_remote_retrieve_response_code( $response ) ) {
			return new \WP_Error(
				'powergis_export_failed',
				__( 'No se pudo generar la exportación', 'powergis' ),
				array( 'status' => 502 )
			);
		}
		return array(
			'body'         => wp_remote_retrieve_body( $response ),
			'content_type' => (string) wp_remote_retrieve_header( $response, 'content-type' ),
		);
	}

	// ------------------------------------------------------------------ //

	/**
	 * @param array<string,mixed> $payload
	 * @param array<string,string> $extra_headers
	 * @return array<string,mixed>|\WP_Error
	 */
	private function post( string $path, array $payload, array $extra_headers = array() ) {
		if ( ! $this->is_configured() ) {
			return new \WP_Error(
				'powergis_not_configured',
				__( 'Define POWERGIS_ENGINE_URL y POWERGIS_HMAC_SECRET en wp-config.php', 'powergis' ),
				array( 'status' => 500 )
			);
		}

		// Se serializa UNA vez y se firman exactamente estos bytes.
		$body = wp_json_encode( $payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES );
		if ( false === $body ) {
			return new \WP_Error( 'powergis_encode', __( 'No se pudo serializar el cuerpo', 'powergis' ) );
		}

		$headers = array_merge(
			self::cabeceras_base(),
			array( 'Content-Type' => 'application/json' ),
			Signer::headers( $body ),
			$extra_headers
		);

		$response = wp_remote_post(
			$this->base_url . $path,
			array(
				'headers'     => $headers,
				'body'        => $body,
				'timeout'     => $this->timeout,
				'redirection' => 0,
			)
		);

		return $this->handle( $response, $path );
	}

	/**
	 * @param array<string,mixed> $args
	 * @return array<string,mixed>|\WP_Error
	 */
	private function get( string $path, array $args = array() ) {
		if ( ! $this->is_configured() ) {
			return new \WP_Error( 'powergis_not_configured', __( 'Motor sin configurar', 'powergis' ) );
		}
		$url = add_query_arg( $args, $this->base_url . $path );

		// Las lecturas van firmadas igual que las escrituras. WordPress es
		// quien tiene la sesión: si el motor aceptara GET sin firma, el
		// `wp_user_id` de la query sería una declaración de intenciones.
		$response = wp_remote_get(
			$url,
			array(
				'timeout'     => $this->timeout,
				'redirection' => 0,
				'headers'     => array_merge( self::cabeceras_base(), Signer::headers_for_get( $url ) ),
			)
		);
		return $this->handle( $response, $path );
	}

	/**
	 * @param array<string,mixed>|\WP_Error $response
	 * @return array<string,mixed>|\WP_Error
	 */
	private function handle( $response, string $path ) {
		if ( is_wp_error( $response ) ) {
			Plugin::log( 'error', 'Motor inalcanzable', array( 'path' => $path, 'error' => $response->get_error_message() ) );
			return $response;
		}

		$code = (int) wp_remote_retrieve_response_code( $response );
		$body = wp_remote_retrieve_body( $response );
		$data = json_decode( $body, true );

		if ( $code >= 400 ) {
			$message = is_array( $data ) && isset( $data['message'] )
				? (string) $data['message']
				: __( 'Error del motor de informes', 'powergis' );
			Plugin::log( 'warning', 'Motor devolvió error', array( 'path' => $path, 'status' => $code ) );
			return new \WP_Error(
				is_array( $data ) && isset( $data['code'] ) ? (string) $data['code'] : 'powergis_engine_error',
				$message,
				array( 'status' => $code, 'context' => is_array( $data ) ? ( $data['context'] ?? array() ) : array() )
			);
		}

		if ( ! is_array( $data ) ) {
			return new \WP_Error( 'powergis_bad_response', __( 'Respuesta no válida del motor', 'powergis' ) );
		}

		return $data;
	}
}
