<?php
/**
 * Plantilla del informe.
 *
 * Deliberadamente mínima: un contenedor y el bundle. Todo el contenido lo
 * inyecta `assets/js/report.js` desde el payload del motor. Añadir una sección
 * al informe NO requiere tocar esta plantilla.
 *
 * Variables disponibles: $post_id.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/** @var int $post_id */
$pg_status  = \PowerGIS\CPT::status_of( $post_id );
$pg_tier    = \PowerGIS\CPT::tier_of( $post_id );
$pg_version = (int) get_post_meta( $post_id, \PowerGIS\CPT::META_VERSION, true );
$pg_paid    = isset( $_GET['pg_pago'] ) ? sanitize_key( wp_unslash( (string) $_GET['pg_pago'] ) ) : '';
?>
<div class="pg-report" data-pg-tier="<?php echo esc_attr( $pg_tier ); ?>">

	<?php if ( 'ok' === $pg_paid ) : ?>
		<div class="pg-notice pg-notice--success">
			<?php esc_html_e( 'Pago recibido. Estamos preparando tu informe completo; esta página se actualizará sola.', 'powergis' ); ?>
		</div>
	<?php elseif ( 'cancelado' === $pg_paid ) : ?>
		<div class="pg-notice">
			<?php esc_html_e( 'Has cancelado el pago. Tu informe básico sigue disponible.', 'powergis' ); ?>
		</div>
	<?php endif; ?>

	<header class="pg-report__header">
		<h1><?php echo esc_html( get_the_title( $post_id ) ); ?></h1>
		<div class="pg-report__meta">
			<span class="pg-badge pg-badge--<?php echo esc_attr( $pg_tier ); ?>">
				<?php echo esc_html( 'avanzado' === $pg_tier ? __( 'Informe avanzado', 'powergis' ) : __( 'Informe básico', 'powergis' ) ); ?>
			</span>
			<?php if ( $pg_version ) : ?>
				<span class="pg-muted"><?php printf( esc_html__( 'versión %d', 'powergis' ), (int) $pg_version ); ?></span>
			<?php endif; ?>
		</div>

		<?php if ( 'avanzado' === $pg_tier ) : ?>
			<nav class="pg-report__actions">
				<a class="pg-btn" href="<?php echo esc_url( rest_url( 'saas/v1/projects/' . $post_id . '/export/xlsx' ) ); ?>">Excel</a>
				<a class="pg-btn" href="<?php echo esc_url( rest_url( 'saas/v1/projects/' . $post_id . '/export/pdf' ) ); ?>">PDF</a>
				<a class="pg-btn" href="<?php echo esc_url( rest_url( 'saas/v1/projects/' . $post_id . '/export/pptx' ) ); ?>">PowerPoint</a>
				<a class="pg-btn" href="#geolens">GeoLens</a>
				<a class="pg-btn" href="#placerank">PlaceRank</a>
			</nav>
		<?php endif; ?>
	</header>

	<?php if ( in_array( $pg_status, array( 'queued', 'running' ), true ) ) : ?>
		<div class="pg-loading" role="status">
			<?php esc_html_e( 'Estamos calculando tu informe. Esta página se actualiza sola.', 'powergis' ); ?>
		</div>
	<?php endif; ?>

	<!-- Todo lo demás lo pinta assets/js/report.js desde el payload JSON. -->
	<div data-pg-report="<?php echo esc_attr( (string) $post_id ); ?>"></div>
</div>
