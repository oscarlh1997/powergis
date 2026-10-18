<?php
/**
 * Página del invitado: el informe que alguien ha compartido por correo.
 *
 * Es un documento propio y no una página del tema a propósito: así no hereda
 * menús, barras de cuenta ni enlaces a «Mis proyectos», y el invitado no ve
 * nada de quien comparte salvo este informe. `wp_head()` y `wp_footer()` se
 * mantienen para que carguen el bundle y los estilos del informe.
 *
 * Variables disponibles: $pg_share (fila del enlace o null), $pg_title.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/** @var array<string,mixed>|null $pg_share */
/** @var string $pg_title */
$pg_expires = $pg_share && ! empty( $pg_share['expires_at'] ) ? strtotime( $pg_share['expires_at'] . ' UTC' ) : 0;
?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
	<meta charset="<?php bloginfo( 'charset' ); ?>">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<meta name="robots" content="noindex, nofollow">
	<meta name="referrer" content="no-referrer">
	<title><?php echo esc_html( $pg_share ? $pg_title . ' · PowerGIS' : __( 'Enlace no disponible · PowerGIS', 'powergis' ) ); ?></title>
	<?php wp_head(); ?>
</head>
<body class="pg-shared-page">
	<main class="pg-shared">
		<?php if ( ! $pg_share ) : ?>
			<div class="pg-notice">
				<?php esc_html_e( 'Este enlace ya no está disponible. Pide a quien te lo envió que lo comparta de nuevo.', 'powergis' ); ?>
			</div>
		<?php else : ?>
			<div class="pg-report" data-pg-shared="1">
				<header class="pg-report__header">
					<p class="pg-shared__brand">PowerGIS</p>
					<h1><?php echo esc_html( $pg_title ); ?></h1>
					<div class="pg-report__meta">
						<span class="pg-badge"><?php esc_html_e( 'Informe compartido', 'powergis' ); ?></span>
						<?php if ( $pg_expires ) : ?>
							<span class="pg-muted">
								<?php
								/* translators: %s: fecha y hora de caducidad */
								printf( esc_html__( 'Disponible hasta el %s', 'powergis' ), esc_html( wp_date( 'j \d\e F \d\e Y, H:i', $pg_expires ) ) );
								?>
							</span>
						<?php endif; ?>
					</div>
				</header>

				<div data-pg-report="0"></div>
			</div>
		<?php endif; ?>
	</main>
	<?php wp_footer(); ?>
</body>
</html>
