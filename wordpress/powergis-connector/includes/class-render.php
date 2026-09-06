<?php
/**
 * Render del informe.
 *
 * Una sola plantilla y un bundle JS. Nada de escribir JSON de Elementor por
 * programa: Graphina guarda los datos de cada gráfico dentro del widget, en el
 * meta `_elementor_data` del post. Con 30-60 gráficos por informe eso es
 * imposible de versionar y de mantener.
 *
 * La plantilla imprime contenedores vacíos con `data-pg-*` y el bundle los
 * rellena desde el payload. Añadir un gráfico es añadir un indicador al
 * catálogo del motor; aquí no se toca nada.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Render {

	public static function hooks(): void {
		add_shortcode( 'powergis_report', array( self::class, 'shortcode' ) );
		add_shortcode( 'powergis_my_projects', array( self::class, 'my_projects' ) );
		add_filter( 'the_content', array( self::class, 'inject_into_cpt' ), 20 );
		add_action( 'wp_enqueue_scripts', array( self::class, 'enqueue' ) );
	}

	public static function enqueue(): void {
		if ( ! is_singular( CPT::POST_TYPE ) && ! self::page_has_shortcode() ) {
			return;
		}

		wp_enqueue_script(
			'powergis-report',
			POWERGIS_URL . 'assets/js/report.js',
			array(),
			POWERGIS_VERSION,
			true
		);
		wp_enqueue_style(
			'powergis-report',
			POWERGIS_URL . 'assets/css/report.css',
			array(),
			POWERGIS_VERSION
		);

		// ECharts y MapLibre desde CDN. Si prefieres servirlos tú, cambia la URL:
		// el bundle solo espera `window.echarts` y `window.maplibregl`.
		wp_enqueue_script( 'echarts', 'https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js', array(), '5.5.1', true );
		wp_enqueue_script( 'maplibre-gl', 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.js', array(), '4.7.1', true );
		wp_enqueue_style( 'maplibre-gl', 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.css', array(), '4.7.1' );

		$post_id = get_the_ID();
		wp_localize_script(
			'powergis-report',
			'PowerGISConfig',
			array(
				'restUrl'  => esc_url_raw( rest_url( REST_Projects::NAMESPACE ) ),
				'nonce'    => wp_create_nonce( 'wp_rest' ),
				'postId'   => (int) $post_id,
				'tilesUrl' => esc_url_raw( apply_filters( 'powergis_tiles_url', POWERGIS_URL . 'tiles/' ) ),
				'i18n'     => array(
					'loading'      => __( 'Preparando tu informe…', 'powergis' ),
					'error'        => __( 'No se pudo cargar el informe.', 'powergis' ),
					'locked'       => __( 'Disponible en el informe avanzado', 'powergis' ),
					'unlock'       => __( 'Desbloquear informe completo', 'powergis' ),
					'noData'       => __( 'Dato no disponible', 'powergis' ),
					'secreto'      => __( 'Sin publicar por secreto estadístico', 'powergis' ),
					'generating'   => __( 'Estamos calculando tu informe. Esta página se actualiza sola.', 'powergis' ),
					// Compra desde dentro del propio informe
					'lockedBadge'  => __( 'Incluido en el avanzado', 'powergis' ),
					'seeUnlock'    => __( 'Ver qué incluye el informe avanzado', 'powergis' ),
					'upgradeTitle' => __( 'Completa tu informe', 'powergis' ),
					'upgradeLead'  => __( 'Ya tienes la demografía completa de tu zona. El informe avanzado añade:', 'powergis' ),
					'extraPlaceRank' => __( 'PlaceRank: ranking ponderado de las zonas de tu ámbito', 'powergis' ),
					'extraGeoLens' => __( 'GeoLens: mapa por capas con todos los indicadores', 'powergis' ),
					'extraExports' => __( 'Descarga en Excel, PDF y PowerPoint', 'powergis' ),
					'redirecting'  => __( 'Conectando con el pago…', 'powergis' ),
					'unlocking'    => __( 'Pago confirmado. Estamos ampliando tu informe…', 'powergis' ),
					'upgradeSlow'  => __( 'Tu pago se ha registrado, pero el informe ampliado está tardando más de lo normal. No hace falta que pagues otra vez: recarga en unos minutos o escríbenos y lo revisamos.', 'powergis' ),
				),
			)
		);
	}

	private static function page_has_shortcode(): bool {
		$post = get_post();
		return $post instanceof \WP_Post && (
			has_shortcode( $post->post_content, 'powergis_report' ) ||
			has_shortcode( $post->post_content, 'powergis_my_projects' )
		);
	}

	public static function inject_into_cpt( string $content ): string {
		if ( ! is_singular( CPT::POST_TYPE ) || ! in_the_loop() || ! is_main_query() ) {
			return $content;
		}
		return $content . self::shortcode( array( 'id' => (string) get_the_ID() ) );
	}

	/**
	 * @param array<string,string>|string $atts
	 */
	public static function shortcode( $atts = array() ): string {
		$atts    = shortcode_atts( array( 'id' => (string) get_the_ID() ), (array) $atts, 'powergis_report' );
		$post_id = (int) $atts['id'];

		if ( ! $post_id || CPT::POST_TYPE !== get_post_type( $post_id ) ) {
			return '';
		}
		if ( ! is_user_logged_in() ) {
			return '<div class="pg-notice">' . esc_html__( 'Inicia sesión para ver este informe.', 'powergis' ) . '</div>';
		}
		if ( ! CPT::owns( $post_id, get_current_user_id() ) ) {
			return '<div class="pg-notice">' . esc_html__( 'Este informe no es tuyo.', 'powergis' ) . '</div>';
		}

		ob_start();
		include POWERGIS_PATH . 'templates/report.php';
		return (string) ob_get_clean();
	}

	/**
	 * Listado «Mis proyectos» con el CTA de upgrade.
	 */
	public static function my_projects(): string {
		if ( ! is_user_logged_in() ) {
			return '<div class="pg-notice">' . esc_html__( 'Inicia sesión para ver tus proyectos.', 'powergis' ) . '</div>';
		}

		$query = new \WP_Query(
			array(
				'post_type'      => CPT::POST_TYPE,
				'author'         => get_current_user_id(),
				'post_status'    => array( 'publish', 'draft', 'pending' ),
				'posts_per_page' => 50,
				'orderby'        => 'date',
				'order'          => 'DESC',
			)
		);

		ob_start();
		include POWERGIS_PATH . 'templates/my-projects.php';
		wp_reset_postdata();
		return (string) ob_get_clean();
	}
}
