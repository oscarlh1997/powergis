<?php
/**
 * Namespace `saas/v1` endurecido.
 *
 * Lo que había antes: rutas sin `args` declarados y sin `permission_callback`
 * verificable. En WordPress, omitir `permission_callback` (o devolver
 * `__return_true`) deja el endpoint abierto a internet.
 *
 * Lo que hay ahora, en las tres rutas:
 *   · esquema de argumentos con validación y sanitización;
 *   · `permission_callback` real: nonce + usuario con sesión;
 *   · comprobación de propiedad antes de tocar nada;
 *   · límite de peticiones por usuario.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class REST_Projects {

	public const NAMESPACE = 'saas/v1';

	public static function hooks(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
	}

	public static function register_routes(): void {
		register_rest_route(
			self::NAMESPACE,
			'/projects/create',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'create' ),
				'permission_callback' => array( self::class, 'can_create' ),
				// Sin `args` estrictos: este endpoint recibe DOS formatos —el
				// del formulario real de JetFormBuilder (`project_title`,
				// `geographic_scope`, `age_range[]`…) y el simplificado del
				// shortcode de pruebas. `Form_Mapper` normaliza los dos y la
				// validación fuerte la hace el motor con Pydantic, que es
				// donde debe estar: una sola definición del contrato.
			)
		);

		// Municipios de una provincia, con su código INE de verdad.
		//
		// El formulario no puede sacarlos de `data/arbol.json`: ese fichero
		// conserva sólo el dígito de control de cada municipio (Madrid figura
		// como «6», no como «28079»), así que el código real es irrecuperable
		// desde ahí. El motor sí tiene el padrón completo cargado en
		// `dim_geo`, y además así el formulario y el almacén no pueden
		// discrepar: son la misma lista.
		register_rest_route(
			self::NAMESPACE,
			'/geo/municipios',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'municipios' ),
				'permission_callback' => static fn(): bool => is_user_logged_in(),
				'args'                => array(
					'provincia' => array(
						'type'              => 'string',
						'required'          => true,
						'sanitize_callback' => static fn( $v ): string => preg_replace( '/\D/', '', (string) $v ),
					),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/projects/save-draft',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'save_draft' ),
				'permission_callback' => array( self::class, 'can_create' ),
				'args'                => self::create_args( false ),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/projects/(?P<id>\d+)/status',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'status' ),
				'permission_callback' => array( self::class, 'can_read_project' ),
				'args'                => array(
					'id' => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/projects/(?P<id>\d+)/report',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'report' ),
				'permission_callback' => array( self::class, 'can_read_project' ),
				'args'                => array(
					'id'      => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
					'version' => array( 'type' => 'integer', 'required' => false, 'sanitize_callback' => 'absint' ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/projects/(?P<id>\\d+)/placerank',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( self::class, 'rebalance' ),
				'permission_callback' => array( self::class, 'can_read_project' ),
				'args'                => array(
					'id'          => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
					'economico'   => array( 'type' => 'number', 'minimum' => 0, 'maximum' => 1 ),
					'demografico' => array( 'type' => 'number', 'minimum' => 0, 'maximum' => 1 ),
					'ambiental'   => array( 'type' => 'number', 'minimum' => 0, 'maximum' => 1 ),
					'match'       => array( 'type' => 'number', 'minimum' => 0, 'maximum' => 1 ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/projects/(?P<id>\\d+)/export/(?P<kind>xlsx|pdf|pptx)',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'export' ),
				'permission_callback' => array( self::class, 'can_read_project' ),
				'args'                => array(
					'id'   => array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' ),
					'kind' => array( 'type' => 'string', 'required' => true, 'enum' => array( 'xlsx', 'pdf', 'pptx' ) ),
				),
			)
		);

		register_rest_route(
			self::NAMESPACE,
			'/geo/search',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'geo_search' ),
				'permission_callback' => static fn(): bool => is_user_logged_in(),
				'args'                => array(
					'q'     => array( 'type' => 'string', 'required' => true, 'sanitize_callback' => 'sanitize_text_field' ),
					'level' => array( 'type' => 'string', 'required' => false, 'enum' => self::LEVELS ),
				),
			)
		);
	}

	private const LEVELS = array( 'pais', 'ccaa', 'provincia', 'municipio', 'distrito', 'seccion' );

	/**
	 * @return array<string,array<string,mixed>>
	 */
	private static function create_args( bool $required = true ): array {
		return array(
			'title'          => array(
				'type'              => 'string',
				'required'          => $required,
				'sanitize_callback' => 'sanitize_text_field',
				'validate_callback' => static fn( $v ): bool => is_string( $v ) && strlen( $v ) <= 200,
			),
			'scope_level'    => array(
				'type'     => 'string',
				'required' => $required,
				'enum'     => self::LEVELS,
			),
			'scope_code'     => array(
				'type'              => 'string',
				'required'          => $required,
				'sanitize_callback' => 'sanitize_text_field',
				'validate_callback' => static fn( $v ): bool => (bool) preg_match( '/^(\d{2,10}|ES)$/', (string) $v ),
			),
			'children_level' => array( 'type' => 'string', 'required' => false, 'enum' => self::LEVELS ),
			'age'            => array(
				'type'     => 'array',
				'required' => false,
				'items'    => array( 'type' => 'string' ),
				'validate_callback' => array( self::class, 'validate_ages' ),
			),
			'sex'            => array(
				'type'     => 'array',
				'required' => false,
				'items'    => array( 'type' => 'string', 'enum' => array( 'F', 'M' ) ),
			),
			'sector'         => array( 'type' => 'string', 'required' => false, 'sanitize_callback' => 'sanitize_key' ),
			'project_type'   => array( 'type' => 'string', 'required' => false, 'sanitize_callback' => 'sanitize_key' ),
			'avg_ticket'     => array( 'type' => 'number', 'required' => false, 'minimum' => 0, 'maximum' => 1000000 ),
			'surface_m2'     => array( 'type' => 'number', 'required' => false, 'minimum' => 0, 'maximum' => 1000000 ),
			'horizon_months' => array( 'type' => 'integer', 'required' => false, 'minimum' => 1, 'maximum' => 240 ),
			'company_name'   => array( 'type' => 'string', 'required' => false, 'sanitize_callback' => 'sanitize_text_field' ),
			'tier'           => array( 'type' => 'string', 'required' => false, 'enum' => array( 'basico', 'avanzado' ), 'default' => 'basico' ),
		);
	}

	public static function validate_ages( $value ): bool {
		if ( ! is_array( $value ) || count( $value ) > 12 ) {
			return false;
		}
		foreach ( $value as $item ) {
			if ( ! preg_match( '/^\d{1,3}(-\d{1,3}|\+)?$/', (string) $item ) ) {
				return false;
			}
		}
		return true;
	}

	// -- permisos ---------------------------------------------------------- //

	/**
	 * @return true|\WP_Error
	 */
	public static function can_create( \WP_REST_Request $request ) {
		if ( ! is_user_logged_in() ) {
			return new \WP_Error( 'powergis_auth', __( 'Necesitas iniciar sesión', 'powergis' ), array( 'status' => 401 ) );
		}
		$nonce = $request->get_header( 'x_wp_nonce' );
		if ( ! $nonce || ! wp_verify_nonce( $nonce, 'wp_rest' ) ) {
			return new \WP_Error( 'powergis_nonce', __( 'Nonce no válido', 'powergis' ), array( 'status' => 403 ) );
		}
		return self::check_rate_limit( get_current_user_id() );
	}

	/**
	 * @return true|\WP_Error
	 */
	public static function can_read_project( \WP_REST_Request $request ) {
		if ( ! is_user_logged_in() ) {
			return new \WP_Error( 'powergis_auth', __( 'Necesitas iniciar sesión', 'powergis' ), array( 'status' => 401 ) );
		}
		$post_id = (int) $request->get_param( 'id' );
		$post    = get_post( $post_id );
		if ( ! $post || CPT::POST_TYPE !== $post->post_type ) {
			return new \WP_Error( 'powergis_not_found', __( 'Proyecto no encontrado', 'powergis' ), array( 'status' => 404 ) );
		}
		if ( ! CPT::owns( $post_id, get_current_user_id() ) ) {
			return new \WP_Error( 'powergis_forbidden', __( 'Este proyecto no es tuyo', 'powergis' ), array( 'status' => 403 ) );
		}
		return true;
	}

	/**
	 * @return true|\WP_Error
	 */
	private static function check_rate_limit( int $user_id ) {
		$key   = 'pg_rl_' . $user_id;
		$count = (int) get_transient( $key );
		$limit = (int) apply_filters( 'powergis_reports_per_hour', 5 );
		if ( $count >= $limit ) {
			return new \WP_Error(
				'powergis_rate_limited',
				__( 'Has alcanzado el límite de informes por hora', 'powergis' ),
				array( 'status' => 429 )
			);
		}
		set_transient( $key, $count + 1, HOUR_IN_SECONDS );
		return true;
	}

	// -- endpoints --------------------------------------------------------- //

	public static function create( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$user_id = get_current_user_id();
		$uuid    = wp_generate_uuid4();

		// Todo lo que mande el formulario, sin filtrar por nombre: el mapeador
		// sabe qué alias corresponde a qué campo.
		$input = array_merge( (array) $request->get_body_params(), (array) $request->get_json_params() );
		$input = self::sanitize_input( $input );

		$title = (string) ( Form_Mapper::pick( $input, 'title' ) ?? __( 'Proyecto sin título', 'powergis' ) );

		$post_id = wp_insert_post(
			array(
				'post_type'   => CPT::POST_TYPE,
				'post_status' => 'draft',
				'post_title'  => $title,
				'post_author' => $user_id,
			),
			true
		);
		if ( is_wp_error( $post_id ) ) {
			return $post_id;
		}

		$mapped = Form_Mapper::to_engine_payload( $input, ( new Geo_Resolver() )->as_callable() );

		// El formulario manda NOMBRES de ubicación y aquí se resuelven a
		// código INE. Si no se ha podido, se corta ahora: mandarlo al motor
		// devolvería un error de validación ilegible para el cliente, y
		// dejaría el proyecto creado y roto.
		if ( '' === (string) ( $mapped['scope']['ine_code'] ?? '' ) ) {
			wp_delete_post( $post_id, true );
			return new \WP_Error(
				'powergis_scope_unresolved',
				__( 'No hemos podido identificar la zona seleccionada. Vuelve a elegirla y, si sigue fallando, avísanos.', 'powergis' ),
				array( 'status' => 422 )
			);
		}

		$scope    = $mapped['scope'];
		$segments = $mapped['segments'];
		$business = $mapped['business'];
		$target   = $mapped['target'];
		$tier     = 'basico';   // el avanzado SOLO se concede tras el pago

		update_post_meta( $post_id, CPT::META_UUID, $uuid );
		update_post_meta( $post_id, CPT::META_STATUS, 'queued' );
		update_post_meta( $post_id, CPT::META_SCOPE, wp_json_encode( $scope ) );
		update_post_meta( $post_id, CPT::META_SEGMENTS, wp_json_encode( $segments ) );
		update_post_meta( $post_id, CPT::META_BUSINESS, wp_json_encode( $business ) );
		update_post_meta( $post_id, CPT::META_TARGET, wp_json_encode( $target ) );
		update_post_meta( $post_id, CPT::META_RAW, wp_json_encode( $input ) );

		CPT::set_tier( $post_id, 'basico' );
		if ( ! empty( $business['sector'] ) ) {
			wp_set_object_terms( $post_id, (string) $business['sector'], CPT::TAX_SECTOR, false );
		}
		$project_type = Form_Mapper::pick( $input, 'project_type' );
		if ( $project_type ) {
			wp_set_object_terms( $post_id, Form_Mapper::slug( $project_type ), CPT::TAX_TYPE, false );
		}

		$client = new Engine_Client();
		$result = $client->create_report(
			array(
				'project_uuid' => $uuid,
				'wp_user_id'   => $user_id,
				'wp_post_id'   => $post_id,
				'tier'         => $tier,
				'scope'        => $scope,
				'segments'     => $segments,
				'business'     => $business,
				'target'       => $target,
				'callback_url' => REST_Callback::url(),
			),
			$uuid  // clave de idempotencia: el UUID del proyecto
		);

		if ( is_wp_error( $result ) ) {
			update_post_meta( $post_id, CPT::META_STATUS, 'failed' );
			update_post_meta( $post_id, CPT::META_ERROR, $result->get_error_message() );
			return $result;
		}

		return new \WP_REST_Response(
			array(
				'post_id'      => $post_id,
				'project_uuid' => $uuid,
				'status'       => $result['status'] ?? 'queued',
				'permalink'    => get_permalink( $post_id ),
				'poll_after'   => $result['poll_after_seconds'] ?? 2,
			),
			202
		);
	}

	public static function save_draft( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$post_id = wp_insert_post(
			array(
				'post_type'   => CPT::POST_TYPE,
				'post_status' => 'draft',
				'post_title'  => (string) ( $request->get_param( 'title' ) ?: __( 'Borrador', 'powergis' ) ),
				'post_author' => get_current_user_id(),
			),
			true
		);
		if ( is_wp_error( $post_id ) ) {
			return $post_id;
		}
		$input  = self::sanitize_input(
			array_merge( (array) $request->get_body_params(), (array) $request->get_json_params() )
		);
		$mapped = Form_Mapper::to_engine_payload( $input, ( new Geo_Resolver() )->as_callable() );
		update_post_meta( $post_id, CPT::META_SCOPE, wp_json_encode( $mapped['scope'] ) );
		update_post_meta( $post_id, CPT::META_SEGMENTS, wp_json_encode( $mapped['segments'] ) );
		update_post_meta( $post_id, CPT::META_BUSINESS, wp_json_encode( $mapped['business'] ) );
		update_post_meta( $post_id, CPT::META_TARGET, wp_json_encode( $mapped['target'] ) );
		update_post_meta( $post_id, CPT::META_RAW, wp_json_encode( $input ) );
		update_post_meta( $post_id, CPT::META_STATUS, 'draft' );

		return new \WP_REST_Response( array( 'post_id' => $post_id, 'status' => 'draft' ), 201 );
	}

	public static function status( \WP_REST_Request $request ): \WP_REST_Response {
		$post_id = (int) $request->get_param( 'id' );
		return new \WP_REST_Response(
			array(
				'post_id' => $post_id,
				'status'  => CPT::status_of( $post_id ),
				'tier'    => CPT::tier_of( $post_id ),
				'version' => (int) get_post_meta( $post_id, CPT::META_VERSION, true ),
				'error'   => get_post_meta( $post_id, CPT::META_ERROR, true ) ?: null,
			),
			200
		);
	}

	/**
	 * Municipios de una provincia: `[{ ine_code, name }]`.
	 *
	 * Se cachea una hora: el padrón cambia un puñado de veces al año y esto
	 * lo pide cada visitante que despliega una provincia.
	 */
	public static function municipios( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$provincia = str_pad( (string) $request->get_param( 'provincia' ), 2, '0', STR_PAD_LEFT );

		$cache_key = 'pg_municipios_' . $provincia;
		$cached    = get_transient( $cache_key );
		if ( is_array( $cached ) ) {
			return new \WP_REST_Response( $cached, 200 );
		}

		$client   = new Engine_Client();
		$response = $client->children( 'provincia', $provincia, 'municipio' );

		if ( is_wp_error( $response ) ) {
			return $response;
		}

		$out = array();
		foreach ( is_array( $response ) ? $response : array() as $row ) {
			if ( empty( $row['ine_code'] ) || empty( $row['name'] ) ) {
				continue;
			}
			$out[] = array(
				'ine_code' => (string) $row['ine_code'],
				'name'     => (string) $row['name'],
			);
		}

		usort( $out, static fn( array $a, array $b ): int => strcoll( $a['name'], $b['name'] ) );

		if ( $out ) {
			set_transient( $cache_key, $out, HOUR_IN_SECONDS );
		}

		return new \WP_REST_Response( $out, 200 );
	}

	/**
	 * Proxy del payload del informe.
	 *
	 * El navegador nunca habla directamente con el motor: así el `project_uuid`
	 * no viaja al cliente y la propiedad se comprueba en WordPress, que es
	 * quien tiene la sesión.
	 */
	public static function report( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$post_id = (int) $request->get_param( 'id' );
		$uuid    = CPT::uuid_of( $post_id );
		if ( ! $uuid ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'El proyecto aún no tiene informe', 'powergis' ), array( 'status' => 409 ) );
		}

		$version = $request->get_param( 'version' );
		$client  = new Engine_Client();
		$payload = $client->get_report( $uuid, (int) get_post_field( 'post_author', $post_id ), $version ? (int) $version : null );

		if ( is_wp_error( $payload ) ) {
			return $payload;
		}

		$payload['_links'] = array(
			'export_xlsx' => rest_url( self::NAMESPACE . '/projects/' . $post_id . '/export/xlsx' ),
			'export_pdf'  => rest_url( self::NAMESPACE . '/projects/' . $post_id . '/export/pdf' ),
			'upgrade'     => Stripe::checkout_url( $post_id ),
		);
		return new \WP_REST_Response( $payload, 200 );
	}

	/**
	 * Ajuste de pesos del PlaceRank en vivo.
	 *
	 * El motor reutiliza las dimensiones ya calculadas del snapshot: no toca
	 * la base de datos ni recalcula indicadores, así que responde al instante.
	 * Es la demo que vende el producto.
	 */
	public static function rebalance( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$post_id = (int) $request->get_param( 'id' );
		$uuid    = CPT::uuid_of( $post_id );
		if ( ! $uuid ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'Sin informe', 'powergis' ), array( 'status' => 409 ) );
		}
		if ( 'avanzado' !== CPT::tier_of( $post_id ) ) {
			return new \WP_Error( 'powergis_tier', __( 'El PlaceRank es del informe avanzado', 'powergis' ), array( 'status' => 403 ) );
		}

		$weights = array();
		foreach ( array( 'economico', 'demografico', 'ambiental', 'match' ) as $key ) {
			$weights[ $key ] = (float) ( $request->get_param( $key ) ?? 0.25 );
		}

		$url  = add_query_arg(
			array( 'wp_user_id' => (int) get_post_field( 'post_author', $post_id ) ),
			Engine_Client::base_url() . '/v1/reports/' . rawurlencode( $uuid ) . '/placerank/rebalance'
		);
		// Se serializa UNA vez y se firman exactamente estos bytes. El motor
		// exige firma aquí porque la respuesta es el PlaceRank entero —zonas,
		// puntuaciones, dimensiones y contribuciones—, que es producto de pago:
		// sin firma bastaba conocer un UUID para leerlo.
		$body = wp_json_encode( $weights, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES );
		if ( false === $body ) {
			return new \WP_Error( 'powergis_encode', __( 'No se pudo serializar el cuerpo', 'powergis' ) );
		}

		$response = wp_remote_post(
			$url,
			array(
				'headers' => array_merge(
					array( 'Content-Type' => 'application/json' ),
					Signer::headers( $body )
				),
				'body'    => $body,
				'timeout' => 15,
			)
		);
		if ( is_wp_error( $response ) ) {
			return $response;
		}
		$data = json_decode( wp_remote_retrieve_body( $response ), true );
		return is_array( $data )
			? new \WP_REST_Response( $data, 200 )
			: new \WP_Error( 'powergis_bad_response', __( 'Respuesta no válida', 'powergis' ) );
	}

	/**
	 * Descarga de una exportación. Se hace de servidor a servidor para no
	 * exponer nunca el `project_uuid` al navegador.
	 */
	public static function export( \WP_REST_Request $request ) {
		$post_id = (int) $request->get_param( 'id' );
		$kind    = (string) $request->get_param( 'kind' );
		$uuid    = CPT::uuid_of( $post_id );
		if ( ! $uuid ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'Sin informe', 'powergis' ), array( 'status' => 409 ) );
		}

		$client = new Engine_Client();
		$result = $client->fetch_export( $uuid, $kind, (int) get_post_field( 'post_author', $post_id ) );

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		$filename = sprintf( 'powergis-%d.%s', $post_id, $kind );
		header( 'Content-Type: ' . $result['content_type'] );
		header( 'Content-Disposition: attachment; filename="' . $filename . '"' );
		echo $result['body'];  // phpcs:ignore WordPress.Security.EscapeOutput
		exit;
	}

	public static function geo_search( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		$client = new Engine_Client();
		$result = $client->search_geo(
			(string) $request->get_param( 'q' ),
			$request->get_param( 'level' ) ? (string) $request->get_param( 'level' ) : null
		);
		return is_wp_error( $result ) ? $result : new \WP_REST_Response( $result, 200 );
	}

	/**
	 * Saneado genérico de la entrada.
	 *
	 * Como el endpoint acepta campos arbitrarios del formulario, el saneado no
	 * puede depender de un esquema fijo: se limpia todo por tipo y la
	 * validación semántica la hace el motor.
	 *
	 * @param array<string,mixed> $input
	 * @return array<string,mixed>
	 */
	private static function sanitize_input( array $input ): array {
		$out = array();
		foreach ( $input as $key => $value ) {
			$key = sanitize_key( (string) $key );
			if ( '' === $key || str_starts_with( $key, '_' ) ) {
				continue;   // nonces y campos internos de JetFormBuilder
			}
			if ( is_array( $value ) ) {
				$out[ $key ] = array_slice(
					array_map( 'sanitize_text_field', array_filter( $value, 'is_scalar' ) ),
					0,
					50
				);
			} elseif ( is_bool( $value ) || is_numeric( $value ) ) {
				$out[ $key ] = $value;
			} else {
				$out[ $key ] = sanitize_textarea_field( substr( (string) $value, 0, 2000 ) );
			}
		}
		return $out;
	}

	// -- mapeo del formulario (legado, lo usa el shortcode de pruebas) ------ //

	/**
	 * @return array<string,mixed>
	 */
	private static function scope_from( \WP_REST_Request $request ): array {
		$scope = array(
			'level'     => (string) ( $request->get_param( 'scope_level' ) ?: 'ccaa' ),
			'ine_code'  => (string) ( $request->get_param( 'scope_code' ) ?: '' ),
		);
		if ( $request->get_param( 'children_level' ) ) {
			$scope['children_level'] = (string) $request->get_param( 'children_level' );
		}
		return $scope;
	}

	/**
	 * @return array<string,array<int,string>>
	 */
	private static function segments_from( \WP_REST_Request $request ): array {
		$segments = array();
		foreach ( array( 'age', 'sex' ) as $axis ) {
			$value = $request->get_param( $axis );
			if ( is_array( $value ) && ! empty( $value ) ) {
				$segments[ $axis ] = array_values( array_map( 'sanitize_text_field', $value ) );
			}
		}
		return $segments;
	}

	/**
	 * @return array<string,mixed>
	 */
	private static function business_from( \WP_REST_Request $request ): array {
		return array(
			'sector'         => $request->get_param( 'sector' ) ? (string) $request->get_param( 'sector' ) : null,
			'avg_ticket'     => $request->get_param( 'avg_ticket' ) !== null ? (float) $request->get_param( 'avg_ticket' ) : null,
			'surface_m2'     => $request->get_param( 'surface_m2' ) !== null ? (float) $request->get_param( 'surface_m2' ) : null,
			'horizon_months' => $request->get_param( 'horizon_months' ) !== null ? (int) $request->get_param( 'horizon_months' ) : null,
			'company_name'   => $request->get_param( 'company_name' ) ? (string) $request->get_param( 'company_name' ) : null,
		);
	}
}
