<?php
/**
 * Pantalla de ajustes y diagnóstico.
 *
 * Los SECRETOS no se editan aquí: van en wp-config.php. Esta pantalla solo
 * dice si están puestos y si el motor responde, que es lo que de verdad
 * necesitas mirar cuando algo falla.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Settings {

	public static function hooks(): void {
		add_action( 'admin_menu', array( self::class, 'menu' ) );
		add_action( 'admin_post_powergis_url_pruebas', array( self::class, 'guardar_url_pruebas' ) );
	}

	/**
	 * Guarda la URL provisional del motor.
	 *
	 * Existe sólo para probar con un túnel efímero, cuyo nombre público cambia
	 * en cada arranque. Se niega a hacer nada si `POWERGIS_ENGINE_URL` está
	 * definida: en producción manda la constante y este formulario no aparece.
	 */
	public static function guardar_url_pruebas(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Sin permisos', 'powergis' ) );
		}
		check_admin_referer( 'powergis_url_pruebas' );

		if ( defined( 'POWERGIS_ENGINE_URL' ) && '' !== POWERGIS_ENGINE_URL ) {
			wp_die( esc_html__( 'POWERGIS_ENGINE_URL está definida en wp-config.php: esa manda.', 'powergis' ) );
		}

		$url = esc_url_raw( wp_unslash( $_POST['powergis_url'] ?? '' ) );

		// Sólo https y sólo host externo. Un http:// aquí mandaría el payload
		// del cliente —y la firma— en claro por internet.
		if ( '' !== $url && 0 !== strpos( $url, 'https://' ) ) {
			wp_die( esc_html__( 'La URL del motor tiene que empezar por https://', 'powergis' ) );
		}

		if ( '' === $url ) {
			delete_option( Engine_Client::URL_OPTION );
		} else {
			update_option( Engine_Client::URL_OPTION, untrailingslashit( $url ), false );
		}

		wp_safe_redirect(
			add_query_arg(
				array( 'post_type' => CPT::POST_TYPE, 'page' => 'powergis-status', 'pg_guardado' => '1' ),
				admin_url( 'edit.php' )
			)
		);
		exit;
	}

	public static function menu(): void {
		add_submenu_page(
			'edit.php?post_type=' . CPT::POST_TYPE,
			__( 'PowerGIS · Diagnóstico', 'powergis' ),
			__( 'Diagnóstico', 'powergis' ),
			'manage_options',
			'powergis-status',
			array( self::class, 'render' )
		);
	}

	public static function render(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Sin permisos', 'powergis' ) );
		}

		$checks = self::checks();
		echo '<div class="wrap"><h1>PowerGIS · Diagnóstico</h1><table class="widefat striped"><tbody>';
		foreach ( $checks as $label => $check ) {
			printf(
				'<tr><td style="width:280px"><strong>%s</strong></td><td>%s %s</td></tr>',
				esc_html( $label ),
				$check['ok'] ? '✅' : '❌',
				esc_html( $check['detail'] )
			);
		}
		echo '</tbody></table>';

		self::render_url_pruebas();

		echo '<h2>' . esc_html__( 'Constantes esperadas en wp-config.php', 'powergis' ) . '</h2>';
		echo '<pre style="background:#f6f7f7;padding:16px;border-radius:6px">';
		echo esc_html(
			"define( 'POWERGIS_ENGINE_URL',            'https://motor.powergis.es' );\n" .
			"define( 'POWERGIS_HMAC_SECRET',           '…mismo valor que HMAC_SECRET del motor…' );\n" .
			"define( 'POWERGIS_STRIPE_SECRET',         'sk_live_…' );\n" .
			"define( 'POWERGIS_STRIPE_WEBHOOK_SECRET', 'whsec_…' );\n" .
			"define( 'POWERGIS_STRIPE_PRICE_ID',       'price_…' );"
		);
		echo '</pre></div>';
	}

	/**
	 * Campo para la URL provisional del motor.
	 *
	 * Sólo se pinta si NO hay constante. Cuando la hay —o sea, en producción—
	 * esta sección no existe y no hay nada que tocar por error.
	 */
	private static function render_url_pruebas(): void {
		if ( defined( 'POWERGIS_ENGINE_URL' ) && '' !== POWERGIS_ENGINE_URL ) {
			return;
		}

		$actual = (string) get_option( Engine_Client::URL_OPTION, '' );

		echo '<h2>' . esc_html__( 'URL del motor (modo pruebas)', 'powergis' ) . '</h2>';
		echo '<div class="notice notice-warning inline"><p>';
		echo esc_html__(
			'POWERGIS_ENGINE_URL no está definida en wp-config.php. Puedes poner aquí la URL de un túnel mientras pruebas; el nombre de un túnel efímero cambia en cada arranque y así no hay que editar wp-config cada vez. En cuanto tengas el motor en su sitio, define la constante: manda sobre esto y este formulario desaparece.',
			'powergis'
		);
		echo '</p><p><strong>';
		echo esc_html__( 'El secreto HMAC no se toca desde aquí y nunca se guarda en la base de datos.', 'powergis' );
		echo '</strong></p></div>';

		printf(
			'<form method="post" action="%s"><input type="hidden" name="action" value="powergis_url_pruebas">',
			esc_url( admin_url( 'admin-post.php' ) )
		);
		wp_nonce_field( 'powergis_url_pruebas' );
		printf(
			'<p><input type="url" name="powergis_url" value="%s" placeholder="https://algo.trycloudflare.com" class="regular-text" style="width:26rem"></p>',
			esc_attr( $actual )
		);
		echo '<p>';
		submit_button( __( 'Guardar', 'powergis' ), 'primary', 'submit', false );
		echo ' <span class="description">';
		esc_html_e( 'Déjalo vacío para borrarla.', 'powergis' );
		echo '</span></p></form>';
	}

	/**
	 * @return array<string,array{ok:bool,detail:string}>
	 */
	public static function checks(): array {
		$client = new Engine_Client();
		$out    = array();

		$url = Engine_Client::base_url();
		$out[ __( 'URL del motor', 'powergis' ) ] = array(
			'ok'     => '' !== $url,
			'detail' => '' === $url
				? __( 'sin definir', 'powergis' )
				: $url . ( Engine_Client::url_es_provisional()
					? __( '  ← provisional, desde el escritorio', 'powergis' )
					: '' ),
		);

		$secret = Signer::secret();
		$out[ __( 'Secreto HMAC', 'powergis' ) ] = array(
			'ok'     => strlen( $secret ) >= 32,
			'detail' => '' === $secret
				? __( 'sin definir', 'powergis' )
				: sprintf( __( 'definido (%d caracteres)', 'powergis' ), strlen( $secret ) ),
		);

		$health = $client->is_configured()
			? wp_remote_get( Engine_Client::base_url() . '/ready', array( 'timeout' => 8 ) )
			: null;
		$code   = $health && ! is_wp_error( $health ) ? (int) wp_remote_retrieve_response_code( $health ) : 0;
		$out[ __( 'Motor accesible', 'powergis' ) ] = array(
			'ok'     => 200 === $code,
			'detail' => 0 === $code ? __( 'sin respuesta', 'powergis' ) : 'HTTP ' . $code,
		);

		$out[ __( 'Stripe', 'powergis' ) ] = array(
			'ok'     => defined( 'POWERGIS_STRIPE_SECRET' ) && defined( 'POWERGIS_STRIPE_WEBHOOK_SECRET' ) && defined( 'POWERGIS_STRIPE_PRICE_ID' ),
			'detail' => __( 'clave, webhook y price_id', 'powergis' ),
		);

		$post_type = get_post_type_object( CPT::POST_TYPE );
		$out[ __( 'CPT no público', 'powergis' ) ] = array(
			'ok'     => $post_type && ! $post_type->public,
			'detail' => __( 'evita que /wp-json/wp/v2/project liste proyectos ajenos', 'powergis' ),
		);

		$out[ __( 'Callback registrado', 'powergis' ) ] = array(
			'ok'     => true,
			'detail' => rest_url( REST_Callback::NAMESPACE . '/projects/callback' ),
		);

		$out[ __( 'Webhook de Stripe', 'powergis' ) ] = array(
			'ok'     => true,
			'detail' => rest_url( Stripe::NAMESPACE . '/stripe/webhook' ),
		);

		return $out;
	}
}
