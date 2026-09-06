<?php
/**
 * «Mis proyectos».
 *
 * Aquí es donde ocurre la conversión básico → avanzado: el usuario ve su
 * informe gratuito y el CTA de desbloqueo. El pago se inicia contra Stripe
 * Checkout desde el servidor; el desbloqueo lo hace el webhook.
 *
 * Variable disponible: $query (WP_Query).
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/** @var \WP_Query $query */
?>
<div class="pg-projects">
	<?php if ( ! $query->have_posts() ) : ?>
		<p class="pg-muted"><?php esc_html_e( 'Todavía no has creado ningún proyecto.', 'powergis' ); ?></p>
	<?php else : ?>
		<table class="pg-projects__table">
			<thead>
				<tr>
					<th><?php esc_html_e( 'Proyecto', 'powergis' ); ?></th>
					<th><?php esc_html_e( 'Ámbito', 'powergis' ); ?></th>
					<th><?php esc_html_e( 'Nivel', 'powergis' ); ?></th>
					<th><?php esc_html_e( 'Estado', 'powergis' ); ?></th>
					<th></th>
				</tr>
			</thead>
			<tbody>
			<?php
			while ( $query->have_posts() ) :
				$query->the_post();
				$pg_id     = get_the_ID();
				$pg_tier   = \PowerGIS\CPT::tier_of( $pg_id );
				$pg_status = \PowerGIS\CPT::status_of( $pg_id );
				$pg_scope  = json_decode( (string) get_post_meta( $pg_id, \PowerGIS\CPT::META_SCOPE, true ), true );
				?>
				<tr>
					<td><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></td>
					<td class="pg-muted">
						<?php
						echo esc_html(
							is_array( $pg_scope )
								? sprintf( '%s · %s', $pg_scope['level'] ?? '', $pg_scope['ine_code'] ?? '' )
								: '—'
						);
						?>
					</td>
					<td>
						<span class="pg-badge pg-badge--<?php echo esc_attr( $pg_tier ); ?>">
							<?php echo esc_html( 'avanzado' === $pg_tier ? __( 'Avanzado', 'powergis' ) : __( 'Básico', 'powergis' ) ); ?>
						</span>
					</td>
					<td class="pg-muted"><?php echo esc_html( $pg_status ); ?></td>
					<td>
						<?php if ( 'avanzado' !== $pg_tier && 'done' === $pg_status ) : ?>
							<button type="button" class="pg-cta" data-pg-upgrade="<?php echo esc_attr( (string) $pg_id ); ?>">
								<?php esc_html_e( 'Desbloquear informe completo', 'powergis' ); ?>
							</button>
							<?php if ( \PowerGIS\Dev::enabled() && current_user_can( 'manage_options' ) ) : ?>
								<button type="button" class="pg-btn" data-pg-simulate="<?php echo esc_attr( (string) $pg_id ); ?>">
									<?php esc_html_e( 'Simular pago (dev)', 'powergis' ); ?>
								</button>
							<?php endif; ?>
						<?php else : ?>
							<a class="pg-btn" href="<?php the_permalink(); ?>"><?php esc_html_e( 'Ver', 'powergis' ); ?></a>
						<?php endif; ?>
					</td>
				</tr>
			<?php endwhile; ?>
			</tbody>
		</table>
	<?php endif; ?>
</div>

<script>
document.querySelectorAll('[data-pg-simulate]').forEach(function (button) {
	button.addEventListener('click', async function () {
		button.disabled = true;
		button.textContent = 'Procesando…';
		try {
			const response = await fetch(
				'<?php echo esc_url_raw( rest_url( 'saas/v1/dev/simulate-payment' ) ); ?>?id=' + button.dataset.pgSimulate,
				{
					method: 'POST',
					headers: { 'X-WP-Nonce': '<?php echo esc_js( wp_create_nonce( 'wp_rest' ) ); ?>' },
					credentials: 'same-origin',
				}
			);
			const data = await response.json();
			if (!response.ok) { throw new Error(data.message || response.statusText); }
			window.location.href = data.permalink;
		} catch (error) {
			button.disabled = false;
			button.textContent = 'Simular pago (dev)';
			alert(error.message);
		}
	});
});

document.querySelectorAll('[data-pg-upgrade]').forEach(function (button) {
	button.addEventListener('click', async function () {
		button.disabled = true;
		try {
			const response = await fetch(
				'<?php echo esc_url_raw( rest_url( 'saas/v1/checkout' ) ); ?>?id=' + button.dataset.pgUpgrade,
				{
					method: 'POST',
					headers: { 'X-WP-Nonce': '<?php echo esc_js( wp_create_nonce( 'wp_rest' ) ); ?>' },
					credentials: 'same-origin',
				}
			);
			const data = await response.json();
			if (data.url) { window.location.href = data.url; }
			else { window.location.reload(); }
		} catch (error) {
			button.disabled = false;
			alert('<?php echo esc_js( __( 'No se pudo iniciar el pago.', 'powergis' ) ); ?>');
		}
	});
});
</script>
