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

// Navegación flotante y panel de control.
$pg_scope    = json_decode( (string) get_post_meta( $post_id, \PowerGIS\CPT::META_SCOPE, true ), true );
$pg_scope    = is_array( $pg_scope ) ? $pg_scope : array();
$pg_business = json_decode( (string) get_post_meta( $post_id, \PowerGIS\CPT::META_BUSINESS, true ), true );
$pg_business = is_array( $pg_business ) ? $pg_business : array();
$pg_user     = wp_get_current_user();
$pg_others   = \PowerGIS\Render::other_projects( $post_id );
$pg_mine_url = \PowerGIS\Render::my_projects_url();
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
	</header>

	<?php if ( in_array( $pg_status, array( 'queued', 'running' ), true ) ) : ?>
		<div class="pg-loading" role="status">
			<?php esc_html_e( 'Estamos calculando tu informe. Esta página se actualiza sola.', 'powergis' ); ?>
		</div>
	<?php endif; ?>

	<?php include POWERGIS_PATH . 'templates/report-nav.php'; ?>

	<!-- Todo lo demás lo pinta assets/js/report.js desde el payload JSON. -->
	<div data-pg-report="<?php echo esc_attr( (string) $post_id ); ?>"></div>
</div>
