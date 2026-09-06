<?php
/**
 * Formulario de creación de proyectos.
 *
 * Formulario nativo, sin JetFormBuilder. Sirve para dos cosas:
 *
 * 1. Probar el sistema completo hoy, sin depender del constructor de formularios.
 * 2. Documentar con código exacto qué campos espera `saas/v1/projects/create`.
 *    Cuando conectes tu formulario real, replica estos `name` y funciona.
 *
 * Shortcode: [powergis_form]
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Form {

	/** Comunidades autónomas con su código INE. Coinciden con el seed del motor. */
	public const CCAA = array(
		'01' => 'Andalucía',
		'02' => 'Aragón',
		'03' => 'Principado de Asturias',
		'04' => 'Illes Balears',
		'05' => 'Canarias',
		'06' => 'Cantabria',
		'07' => 'Castilla y León',
		'08' => 'Castilla-La Mancha',
		'09' => 'Cataluña',
		'10' => 'Comunitat Valenciana',
		'11' => 'Extremadura',
		'12' => 'Galicia',
		'13' => 'Comunidad de Madrid',
		'14' => 'Región de Murcia',
		'15' => 'Comunidad Foral de Navarra',
		'16' => 'País Vasco',
		'17' => 'La Rioja',
		'18' => 'Ceuta',
		'19' => 'Melilla',
	);

	public const RANGOS_EDAD = array(
		'0-15'  => '0 a 15 años',
		'16-24' => '16 a 24 años',
		'18-35' => '18 a 35 años',
		'36-55' => '36 a 55 años',
		'56-64' => '56 a 64 años',
		'65+'   => '65 o más',
	);

	public const SECTORES = array(
		'restauracion' => 'Restauración',
		'cafeteria'    => 'Cafetería',
		'retail'       => 'Retail / moda',
		'alimentacion' => 'Alimentación',
		'salud'        => 'Salud / farmacia',
		'belleza'      => 'Belleza',
		'fitness'      => 'Fitness',
		'servicios'    => 'Servicios',
	);

	public const TIPOS = array(
		'apertura'    => 'Nueva apertura',
		'expansion'   => 'Expansión',
		'reubicacion' => 'Reubicación',
	);

	public static function hooks(): void {
		add_shortcode( 'powergis_form', array( self::class, 'render' ) );
	}

	public static function render(): string {
		if ( ! is_user_logged_in() ) {
			return '<div class="pg-notice">'
				. esc_html__( 'Inicia sesión para crear un proyecto.', 'powergis' )
				. ' <a href="' . esc_url( wp_login_url( get_permalink() ) ) . '">'
				. esc_html__( 'Entrar', 'powergis' ) . '</a></div>';
		}

		wp_enqueue_style(
			'powergis-report',
			POWERGIS_URL . 'assets/css/report.css',
			array(),
			POWERGIS_VERSION
		);

		ob_start();
		include POWERGIS_PATH . 'templates/form.php';
		return (string) ob_get_clean();
	}
}
