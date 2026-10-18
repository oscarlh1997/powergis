<?php
/**
 * Compartir un proyecto por correo.
 *
 * El dueño escribe uno o varios correos y elige durante cuánto tiempo pueden
 * ver el informe. Cada destinatario recibe SU enlace, con un token aleatorio
 * de 256 bits. En la base de datos sólo se guarda el hash del token: si
 * alguien se lleva una copia de la tabla, no se lleva los enlaces.
 *
 * Lo que ve el invitado es exactamente un informe y nada más:
 *
 *   · una página propia (`/?pg_compartido=TOKEN`), que no pasa por el CPT ni
 *     por la comprobación de dueño del shortcode;
 *   · el payload del informe por una ruta pública que sólo acepta un token
 *     vigente, sin `_links` (exportaciones, pago) ni `project_uuid`;
 *   · sin exportaciones, sin reajuste del PlaceRank, sin «Mis proyectos» ni
 *     ningún otro dato de la cuenta que comparte.
 *
 * Un enlace se puede revocar en cualquier momento; uno caducado deja de
 * funcionar solo, sin cron: la caducidad se comprueba en cada lectura.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Shares {

	public const QUERY_VAR  = 'pg_compartido';
	public const DB_VERSION = '1';
	public const MAX_EMAILS = 20;

	/**
	 * Duraciones que ofrece el diálogo. `siempre` es la de por defecto y no
	 * caduca. «1 mes» y «1 año» son de calendario (del 18/10 al 18/11), no
	 * 30 ni 365 días.
	 */
	public const DURATIONS = array(
		'siempre' => null,
		'1h'      => 'PT1H',
		'3h'      => 'PT3H',
		'24h'     => 'PT24H',
		'1m'      => 'P1M',
		'1a'      => 'P1Y',
	);

	public static function hooks(): void {
		add_action( 'plugins_loaded', array( self::class, 'maybe_install' ), 20 );
		add_action( 'rest_api_init', array( self::class, 'register_routes' ), 20 );
		add_filter( 'query_vars', array( self::class, 'query_vars' ) );
		add_action( 'template_redirect', array( self::class, 'render_guest_page' ) );
		add_action( 'powergis_report_share', array( self::class, 'render_button' ) );
	}

	/**
	 * El botón, en el hueco «Exportar y compartir» del panel de control
	 * (`templates/report-nav.php`). Lo abre `assets/js/share.js`, que
	 * escucha cualquier `[data-pg-share-open]` de la página: para ponerlo en
	 * otro sitio basta con copiar este botón.
	 */
	public static function render_button( int $post_id ): void {
		if ( '' === CPT::uuid_of( $post_id ) ) {
			return;   // sin informe no hay nada que enseñar
		}
		printf(
			'<button type="button" class="pg-btn pg-share-open" data-pg-share-open="%d">%s</button>',
			(int) $post_id,
			esc_html__( 'Compartir por correo', 'powergis' )
		);
	}

	public static function table(): string {
		global $wpdb;
		return $wpdb->prefix . 'pg_shares';
	}

	/**
	 * Crea la tabla al activar y también si el plugin ya estaba activo cuando
	 * se actualizó: el hook de activación no se dispara al sobrescribir los
	 * ficheros por FTP o con un `git pull`.
	 */
	public static function maybe_install(): void {
		if ( self::DB_VERSION === get_option( 'powergis_shares_db' ) ) {
			return;
		}
		self::install();
	}

	public static function install(): void {
		global $wpdb;
		require_once ABSPATH . 'wp-admin/includes/upgrade.php';

		$charset = $wpdb->get_charset_collate();
		$table   = self::table();

		// dbDelta es quisquilloso: dos espacios tras PRIMARY KEY y un campo
		// por línea, o no reconoce la tabla al comparar.
		dbDelta(
			"CREATE TABLE {$table} (
				id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
				post_id bigint(20) unsigned NOT NULL,
				owner_id bigint(20) unsigned NOT NULL,
				email varchar(190) NOT NULL,
				token_hash char(64) NOT NULL,
				duration varchar(10) NOT NULL DEFAULT 'siempre',
				created_at datetime NOT NULL,
				expires_at datetime NULL DEFAULT NULL,
				revoked_at datetime NULL DEFAULT NULL,
				last_view_at datetime NULL DEFAULT NULL,
				views int(10) unsigned NOT NULL DEFAULT 0,
				PRIMARY KEY  (id),
				UNIQUE KEY token_hash (token_hash),
				KEY post_id (post_id)
			) {$charset};"
		);
		update_option( 'powergis_shares_db', self::DB_VERSION, false );
	}

	/**
	 * @param string[] $vars
	 * @return string[]
	 */
	public static function query_vars( array $vars ): array {
		$vars[] = self::QUERY_VAR;
		return $vars;
	}

	public static function guest_url( string $token ): string {
		return add_query_arg( self::QUERY_VAR, rawurlencode( $token ), home_url( '/' ) );
	}

	// -- rutas ------------------------------------------------------------- //

	public static function register_routes(): void {
		$id_arg = array( 'type' => 'integer', 'required' => true, 'sanitize_callback' => 'absint' );

		register_rest_route(
			REST_Projects::NAMESPACE,
			'/projects/(?P<id>\d+)/shares',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( self::class, 'list' ),
					'permission_callback' => array( self::class, 'can_manage' ),
					'args'                => array( 'id' => $id_arg ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( self::class, 'create' ),
					'permission_callback' => array( self::class, 'can_manage' ),
					'args'                => array(
						'id'       => $id_arg,
						'emails'   => array(
							'type'     => 'array',
							'required' => true,
							'items'    => array( 'type' => 'string' ),
						),
						'duration' => array(
							'type'    => 'string',
							'enum'    => array_keys( self::DURATIONS ),
							'default' => 'siempre',
						),
					),
				),
			)
		);

		register_rest_route(
			REST_Projects::NAMESPACE,
			'/projects/(?P<id>\d+)/shares/(?P<share>\d+)',
			array(
				'methods'             => \WP_REST_Server::DELETABLE,
				'callback'            => array( self::class, 'revoke' ),
				'permission_callback' => array( self::class, 'can_manage' ),
				'args'                => array( 'id' => $id_arg, 'share' => $id_arg ),
			)
		);

		// Pública a propósito: el invitado no tiene cuenta. La autorización
		// es el token, que se valida en el propio callback de permiso.
		register_rest_route(
			REST_Projects::NAMESPACE,
			'/shared/(?P<token>[A-Za-z0-9_-]{43})/report',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( self::class, 'guest_report' ),
				'permission_callback' => array( self::class, 'can_view' ),
			)
		);
	}

	/**
	 * Sólo el dueño gestiona los enlaces. Misma comprobación que el resto de
	 * rutas del proyecto, más el nonce: crear un enlace manda correos.
	 *
	 * @return true|\WP_Error
	 */
	public static function can_manage( \WP_REST_Request $request ) {
		$ok = REST_Projects::can_read_project( $request );
		if ( true !== $ok ) {
			return $ok;
		}
		$nonce = $request->get_header( 'x_wp_nonce' );
		if ( ! $nonce || ! wp_verify_nonce( $nonce, 'wp_rest' ) ) {
			return new \WP_Error( 'powergis_nonce', __( 'Nonce no válido', 'powergis' ), array( 'status' => 403 ) );
		}
		return true;
	}

	/**
	 * @return true|\WP_Error
	 */
	public static function can_view( \WP_REST_Request $request ) {
		return self::find_valid( (string) $request->get_param( 'token' ) )
			? true
			: self::gone();
	}

	private static function gone(): \WP_Error {
		// Lo mismo para inexistente, caducado y revocado: no se le dice a
		// quien prueba tokens cuál de los tres ha encontrado.
		return new \WP_Error(
			'powergis_share_gone',
			__( 'Este enlace ya no está disponible. Pide a quien te lo envió que lo comparta de nuevo.', 'powergis' ),
			array( 'status' => 404 )
		);
	}

	// -- endpoints --------------------------------------------------------- //

	public static function list( \WP_REST_Request $request ): \WP_REST_Response {
		global $wpdb;
		$post_id = (int) $request->get_param( 'id' );
		$rows    = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT id, email, duration, created_at, expires_at, last_view_at, views FROM ' . self::table()
				. ' WHERE post_id = %d AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > %s) ORDER BY id DESC',
				$post_id,
				gmdate( 'Y-m-d H:i:s' )
			),
			ARRAY_A
		);
		return new \WP_REST_Response( array_map( array( self::class, 'public_row' ), $rows ?: array() ), 200 );
	}

	public static function create( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		global $wpdb;
		$post_id  = (int) $request->get_param( 'id' );
		$owner_id = get_current_user_id();
		$duration = (string) $request->get_param( 'duration' );

		if ( '' === CPT::uuid_of( $post_id ) ) {
			return new \WP_Error( 'powergis_no_uuid', __( 'El proyecto aún no tiene informe', 'powergis' ), array( 'status' => 409 ) );
		}

		$emails = self::parse_emails( (array) $request->get_param( 'emails' ) );
		if ( is_wp_error( $emails ) ) {
			return $emails;
		}

		$limited = self::check_rate_limit( $owner_id, count( $emails ) );
		if ( true !== $limited ) {
			return $limited;
		}

		$now     = new \DateTimeImmutable( 'now', new \DateTimeZone( 'UTC' ) );
		$expires = self::DURATIONS[ $duration ] ? $now->add( new \DateInterval( self::DURATIONS[ $duration ] ) ) : null;

		$created = array();
		$failed  = array();
		foreach ( $emails as $email ) {
			$token = self::new_token();
			$wpdb->insert(
				self::table(),
				array(
					'post_id'    => $post_id,
					'owner_id'   => $owner_id,
					'email'      => $email,
					'token_hash' => self::hash( $token ),
					'duration'   => $duration,
					'created_at' => $now->format( 'Y-m-d H:i:s' ),
					'expires_at' => $expires ? $expires->format( 'Y-m-d H:i:s' ) : null,
				),
				array( '%d', '%d', '%s', '%s', '%s', '%s', '%s' )   // un null se escribe como NULL
			);
			$share_id = (int) $wpdb->insert_id;

			if ( ! self::send_invitation( $post_id, $owner_id, $email, $token, $expires ) ) {
				// Un enlace que nadie ha recibido no debe quedar vivo.
				$wpdb->delete( self::table(), array( 'id' => $share_id ), array( '%d' ) );
				$failed[] = $email;
				continue;
			}
			$created[] = $share_id;
		}

		Plugin::log( 'info', 'proyecto compartido', array(
			'post_id'  => $post_id,
			'enviados' => count( $created ),
			'fallidos' => count( $failed ),
			'duracion' => $duration,
		) );

		if ( ! $created ) {
			return new \WP_Error(
				'powergis_share_mail',
				__( 'No hemos podido enviar el correo. Inténtalo de nuevo en unos minutos.', 'powergis' ),
				array( 'status' => 502, 'failed' => $failed )
			);
		}

		return new \WP_REST_Response(
			array(
				'sent'   => count( $created ),
				'failed' => $failed,
				'shares' => self::list( $request )->get_data(),
			),
			201
		);
	}

	public static function revoke( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		global $wpdb;
		$updated = $wpdb->update(
			self::table(),
			array( 'revoked_at' => gmdate( 'Y-m-d H:i:s' ) ),
			array(
				'id'      => (int) $request->get_param( 'share' ),
				'post_id' => (int) $request->get_param( 'id' ),   // el enlace es de ESTE proyecto
			),
			array( '%s' ),
			array( '%d', '%d' )
		);
		if ( ! $updated ) {
			return new \WP_Error( 'powergis_share_not_found', __( 'Enlace no encontrado', 'powergis' ), array( 'status' => 404 ) );
		}
		return new \WP_REST_Response( array( 'revoked' => true ), 200 );
	}

	/**
	 * El payload del informe para el invitado, sin nada que le lleve más allá.
	 */
	public static function guest_report( \WP_REST_Request $request ): \WP_REST_Response|\WP_Error {
		global $wpdb;
		$share = self::find_valid( (string) $request->get_param( 'token' ) );
		if ( ! $share ) {
			return self::gone();
		}
		$post_id = (int) $share['post_id'];
		$uuid    = CPT::uuid_of( $post_id );
		if ( ! $uuid ) {
			return self::gone();
		}

		$payload = ( new Engine_Client() )->get_report( $uuid, (int) get_post_field( 'post_author', $post_id ) );
		if ( is_wp_error( $payload ) ) {
			return $payload;
		}

		$wpdb->query(
			$wpdb->prepare(
				'UPDATE ' . self::table() . ' SET views = views + 1, last_view_at = %s WHERE id = %d',
				gmdate( 'Y-m-d H:i:s' ),
				(int) $share['id']
			)
		);

		return new \WP_REST_Response( self::guest_payload( $payload, $post_id ), 200 );
	}

	/**
	 * @param array<string,mixed> $payload
	 * @return array<string,mixed>
	 */
	public static function guest_payload( array $payload, int $post_id ): array {
		// El UUID es la credencial de lectura del motor; `_links` lleva a las
		// exportaciones y al pago, que son del dueño.
		unset( $payload['project_uuid'], $payload['_links'], $payload['wp_user_id'], $payload['wp_post_id'] );
		$payload['title']  = get_the_title( $post_id );
		$payload['shared'] = true;
		return $payload;
	}

	// -- página del invitado ----------------------------------------------- //

	public static function render_guest_page(): void {
		$token = (string) get_query_var( self::QUERY_VAR );
		if ( '' === $token ) {
			return;
		}

		nocache_headers();
		header( 'X-Robots-Tag: noindex, nofollow' );
		// El token va en la URL: que no viaje a otros sitios en el Referer.
		header( 'Referrer-Policy: no-referrer' );

		$share = self::find_valid( $token );
		if ( ! $share ) {
			status_header( 404 );
		} else {
			Render::enqueue_assets( 0, array( 'shareToken' => $token ) );
		}

		$pg_share = $share;
		$pg_title = $share ? get_the_title( (int) $share['post_id'] ) : '';
		include POWERGIS_PATH . 'templates/shared-report.php';
		exit;
	}

	// -- correo ------------------------------------------------------------ //

	private static function send_invitation( int $post_id, int $owner_id, string $email, string $token, ?\DateTimeImmutable $expires ): bool {
		$owner   = get_userdata( $owner_id );
		$from    = $owner && $owner->display_name ? $owner->display_name : __( 'Un usuario de PowerGIS', 'powergis' );
		$title   = get_the_title( $post_id );
		$url     = self::guest_url( $token );
		$caduca  = $expires
			? sprintf(
				/* translators: %s: fecha y hora de caducidad */
				__( 'El enlace estará disponible hasta el %s.', 'powergis' ),
				wp_date( 'j \d\e F \d\e Y, H:i', $expires->getTimestamp() )
			)
			: __( 'El enlace no caduca, salvo que quien lo comparte lo retire.', 'powergis' );

		/* translators: 1: nombre de quien comparte, 2: título del proyecto */
		$subject = sprintf( __( '%1$s ha compartido contigo «%2$s» en PowerGIS', 'powergis' ), $from, $title );

		$body = implode(
			"\n\n",
			array(
				/* translators: 1: nombre de quien comparte, 2: título del proyecto */
				sprintf( __( '%1$s te ha invitado a ver el informe «%2$s».', 'powergis' ), $from, $title ),
				__( 'Ábrelo aquí:', 'powergis' ) . "\n" . $url,
				$caduca,
				__( 'El enlace es personal: no lo reenvíes. Si no esperabas este correo, puedes ignorarlo.', 'powergis' ),
				'— PowerGIS',
			)
		);

		$args = apply_filters(
			'powergis_share_email',
			array( 'to' => $email, 'subject' => $subject, 'message' => $body, 'headers' => array() ),
			$post_id,
			$owner_id,
			$url
		);

		return (bool) wp_mail( $args['to'], $args['subject'], $args['message'], $args['headers'] );
	}

	// -- utilidades -------------------------------------------------------- //

	/**
	 * @param array<int,mixed> $raw
	 * @return string[]|\WP_Error
	 */
	public static function parse_emails( array $raw ) {
		$emails  = array();
		$invalid = array();
		foreach ( $raw as $item ) {
			// Se aceptan pegados en un solo campo: «a@x.es, b@y.es; c@z.es».
			foreach ( preg_split( '/[\s,;]+/', (string) $item, -1, PREG_SPLIT_NO_EMPTY ) as $candidate ) {
				$email = sanitize_email( $candidate );
				if ( '' === $email || ! is_email( $email ) ) {
					$invalid[] = $candidate;
					continue;
				}
				$emails[ strtolower( $email ) ] = $email;
			}
		}
		if ( $invalid ) {
			return new \WP_Error(
				'powergis_share_email',
				/* translators: %s: lista de correos no válidos */
				sprintf( __( 'Revisa estos correos: %s', 'powergis' ), implode( ', ', array_map( 'sanitize_text_field', $invalid ) ) ),
				array( 'status' => 400, 'invalid' => $invalid )
			);
		}
		if ( ! $emails ) {
			return new \WP_Error( 'powergis_share_email', __( 'Escribe al menos un correo.', 'powergis' ), array( 'status' => 400 ) );
		}
		if ( count( $emails ) > self::MAX_EMAILS ) {
			return new \WP_Error(
				'powergis_share_email',
				/* translators: %d: máximo de correos */
				sprintf( __( 'Puedes compartir con %d personas a la vez como máximo.', 'powergis' ), self::MAX_EMAILS ),
				array( 'status' => 400 )
			);
		}
		return array_values( $emails );
	}

	/**
	 * Tope de correos por hora y usuario: esta ruta manda correo desde
	 * nuestro dominio a direcciones que escribe el cliente, y sin tope sería
	 * un relé de spam con la reputación de powergis.es.
	 *
	 * @return true|\WP_Error
	 */
	private static function check_rate_limit( int $user_id, int $count ) {
		$key   = 'pg_compartir_' . $user_id;
		$sent  = (int) get_transient( $key );
		$limit = (int) apply_filters( 'powergis_shares_per_hour', 50 );
		if ( $sent + $count > $limit ) {
			return new \WP_Error(
				'powergis_rate_limited',
				__( 'Has enviado muchas invitaciones en poco tiempo. Vuelve a intentarlo dentro de un rato.', 'powergis' ),
				array( 'status' => 429 )
			);
		}
		set_transient( $key, $sent + $count, HOUR_IN_SECONDS );
		return true;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public static function find_valid( string $token ): ?array {
		global $wpdb;
		if ( ! preg_match( '/^[A-Za-z0-9_-]{43}$/', $token ) ) {
			return null;
		}
		$row = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT * FROM ' . self::table()
				. ' WHERE token_hash = %s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > %s)',
				self::hash( $token ),
				gmdate( 'Y-m-d H:i:s' )
			),
			ARRAY_A
		);
		if ( ! $row || CPT::POST_TYPE !== get_post_type( (int) $row['post_id'] ) ) {
			return null;   // proyecto borrado: el enlace muere con él
		}
		return $row;
	}

	private static function new_token(): string {
		return rtrim( strtr( base64_encode( random_bytes( 32 ) ), '+/', '-_' ), '=' );   // 43 caracteres
	}

	private static function hash( string $token ): string {
		return hash_hmac( 'sha256', $token, wp_salt( 'auth' ) );
	}

	/**
	 * @param array<string,string> $row
	 * @return array<string,mixed>
	 */
	private static function public_row( array $row ): array {
		$iso = static fn( ?string $d ): ?string => $d ? gmdate( 'c', strtotime( $d . ' UTC' ) ) : null;
		return array(
			'id'           => (int) $row['id'],
			'email'        => $row['email'],
			'duration'     => $row['duration'],
			'created_at'   => $iso( $row['created_at'] ),
			'expires_at'   => $iso( $row['expires_at'] ),
			'last_view_at' => $iso( $row['last_view_at'] ),
			'views'        => (int) $row['views'],
		);
	}
}
