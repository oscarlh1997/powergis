<?php
/**
 * Navegación flotante de la página del proyecto y panel de control.
 *
 * Tres botones fijos arriba a la derecha: «Panel de control», «Mis
 * proyectos» con el desplegable de los demás proyectos, y la X que cierra el
 * proyecto. En móvil «Mis proyectos» se esconde y pasa a ser una sección
 * del panel, para no comerse la pantalla.
 *
 * El índice del informe lo rellena `assets/js/report.js` cuando termina de
 * pintar el payload: los títulos salen de ahí, no de esta plantilla.
 *
 * Variables disponibles (de templates/report.php): $post_id, $pg_tier,
 * $pg_version, $pg_scope, $pg_business, $pg_user, $pg_others, $pg_mine_url.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

// La misma lista va en el desplegable (escritorio) y en el panel (móvil).
ob_start();
?>
<ul class="pg-projects-menu__list">
	<?php foreach ( $pg_others as $pg_other ) : ?>
		<li>
			<a href="<?php echo esc_url( $pg_other['url'] ); ?>">
				<span><?php echo esc_html( $pg_other['title'] ); ?></span>
				<?php if ( 'avanzado' === $pg_other['tier'] ) : ?>
					<span class="pg-badge pg-badge--avanzado"><?php esc_html_e( 'Avanzado', 'powergis' ); ?></span>
				<?php endif; ?>
			</a>
		</li>
	<?php endforeach; ?>
	<?php if ( ! $pg_others ) : ?>
		<li class="pg-muted pg-projects-menu__empty"><?php esc_html_e( 'No tienes otros proyectos todavía.', 'powergis' ); ?></li>
	<?php endif; ?>
</ul>
<a class="pg-projects-menu__all" href="<?php echo esc_url( $pg_mine_url ); ?>"><?php esc_html_e( 'Ver todos mis proyectos', 'powergis' ); ?></a>
<?php
$pg_projects_list = (string) ob_get_clean();

$pg_level = (string) ( $pg_scope['level'] ?? '' );
$pg_code  = (string) ( $pg_scope['ine_code'] ?? '' );
?>
<div class="pg-dock" data-pg-dock>
	<button type="button" class="pg-dock__btn" data-pg-panel-open aria-controls="pg-panel" aria-expanded="false">
		<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16"><path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
		<span><?php esc_html_e( 'Panel de control', 'powergis' ); ?></span>
	</button>

	<div class="pg-projects-menu pg-dock__projects" data-pg-projects>
		<button type="button" class="pg-dock__btn" data-pg-projects-toggle aria-controls="pg-projects-menu" aria-expanded="false">
			<span><?php esc_html_e( 'Mis proyectos', 'powergis' ); ?></span>
			<svg aria-hidden="true" class="pg-dock__chevron" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
		</button>
		<div class="pg-projects-menu__pop" id="pg-projects-menu" hidden>
			<?php echo $pg_projects_list; // phpcs:ignore WordPress.Security.EscapeOutput -- escapado arriba ?>
		</div>
	</div>

	<a class="pg-dock__btn pg-dock__close" href="<?php echo esc_url( home_url( '/' ) ); ?>" data-pg-close
		aria-label="<?php esc_attr_e( 'Cerrar el proyecto', 'powergis' ); ?>" title="<?php esc_attr_e( 'Cerrar el proyecto', 'powergis' ); ?>">
		<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
	</a>
</div>

<div class="pg-panel-backdrop" data-pg-panel-close hidden></div>
<aside class="pg-panel" id="pg-panel" aria-label="<?php esc_attr_e( 'Panel de control', 'powergis' ); ?>" hidden>
	<div class="pg-panel__head">
		<h2><?php esc_html_e( 'Panel de control', 'powergis' ); ?></h2>
		<button type="button" class="pg-panel__close" data-pg-panel-close aria-label="<?php esc_attr_e( 'Cerrar el panel', 'powergis' ); ?>">
			<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
		</button>
	</div>

	<?php /* Solo en móvil: en escritorio «Mis proyectos» está en la barra flotante. */ ?>
	<section class="pg-panel__section pg-panel__section--mobile">
		<h3><?php esc_html_e( 'Mis proyectos', 'powergis' ); ?></h3>
		<div class="pg-projects-menu"><?php echo $pg_projects_list; // phpcs:ignore WordPress.Security.EscapeOutput ?></div>
	</section>

	<section class="pg-panel__section">
		<h3><?php esc_html_e( 'Ir a', 'powergis' ); ?></h3>
		<div class="pg-panel__jumps">
			<a class="pg-jump" href="#geolens" data-pg-jump>GeoLens</a>
			<a class="pg-jump" href="#placerank" data-pg-jump>PlaceRank</a>
			<a class="pg-jump" href="#pg-resumen" data-pg-jump><?php esc_html_e( 'Resumen de KPI', 'powergis' ); ?></a>
			<a class="pg-jump" href="#pg-conclusiones" data-pg-jump><?php esc_html_e( 'Conclusiones', 'powergis' ); ?></a>
		</div>
	</section>

	<section class="pg-panel__section">
		<h3><?php esc_html_e( 'Contenido del informe', 'powergis' ); ?></h3>
		<nav class="pg-toc" data-pg-toc aria-label="<?php esc_attr_e( 'Contenido del informe', 'powergis' ); ?>">
			<p class="pg-muted"><?php esc_html_e( 'El índice aparece cuando termina de cargar el informe.', 'powergis' ); ?></p>
		</nav>
	</section>

	<section class="pg-panel__section">
		<h3><?php esc_html_e( 'Exportar y compartir', 'powergis' ); ?></h3>
		<?php if ( 'avanzado' === $pg_tier ) : ?>
			<div class="pg-panel__exports">
				<?php foreach ( \PowerGIS\Render::export_links( $post_id ) as $pg_label => $pg_url ) : ?>
					<a class="pg-btn" href="<?php echo esc_url( $pg_url ); ?>"><?php echo esc_html( $pg_label ); ?></a>
				<?php endforeach; ?>
			</div>
		<?php else : ?>
			<p class="pg-muted pg-panel__note">
				<?php esc_html_e( 'La descarga en Excel, PDF y PowerPoint viene con el informe avanzado.', 'powergis' ); ?>
				<a href="#pg-upgrade" data-pg-jump><?php esc_html_e( 'Ver qué incluye', 'powergis' ); ?></a>
			</p>
		<?php endif; ?>
		<?php
		/*
		 * Hueco para «Compartir» (enlace por correo con caducidad). Lo monta
		 * otro desarrollo: basta con pintar el botón dentro de este contenedor
		 * o engancharse a la acción.
		 */
		?>
		<div class="pg-panel__share" data-pg-share-slot>
			<?php do_action( 'powergis_report_share', $post_id ); ?>
		</div>
	</section>

	<section class="pg-panel__section">
		<h3><?php esc_html_e( 'Datos del proyecto', 'powergis' ); ?></h3>
		<dl class="pg-facts">
			<dt><?php esc_html_e( 'Proyecto', 'powergis' ); ?></dt>
			<dd><?php echo esc_html( get_the_title( $post_id ) ); ?></dd>

			<?php if ( $pg_level ) : ?>
				<dt><?php esc_html_e( 'Ámbito', 'powergis' ); ?></dt>
				<dd>
					<?php echo esc_html( \PowerGIS\Render::scope_label( $pg_level ) ); ?>
					<span data-pg-scope-name><?php echo esc_html( $pg_code ); ?></span>
				</dd>
			<?php endif; ?>

			<dt><?php esc_html_e( 'Informe', 'powergis' ); ?></dt>
			<dd>
				<?php echo esc_html( 'avanzado' === $pg_tier ? __( 'Avanzado', 'powergis' ) : __( 'Básico', 'powergis' ) ); ?>
				<?php if ( $pg_version ) : ?>
					· <?php printf( esc_html__( 'versión %d', 'powergis' ), (int) $pg_version ); ?>
				<?php endif; ?>
			</dd>

			<dt><?php esc_html_e( 'Creado', 'powergis' ); ?></dt>
			<dd><?php echo esc_html( get_the_date( '', $post_id ) ); ?></dd>
		</dl>

		<h4><?php esc_html_e( 'Empresa', 'powergis' ); ?></h4>
		<dl class="pg-facts">
			<dt><?php esc_html_e( 'Nombre', 'powergis' ); ?></dt>
			<dd><?php echo esc_html( ! empty( $pg_business['company_name'] ) ? (string) $pg_business['company_name'] : '—' ); ?></dd>
			<?php if ( ! empty( $pg_business['sector'] ) ) : ?>
				<dt><?php esc_html_e( 'Sector', 'powergis' ); ?></dt>
				<dd><?php echo esc_html( (string) $pg_business['sector'] ); ?></dd>
			<?php endif; ?>
		</dl>

		<h4><?php esc_html_e( 'Usuario', 'powergis' ); ?></h4>
		<dl class="pg-facts">
			<dt><?php esc_html_e( 'Nombre', 'powergis' ); ?></dt>
			<dd><?php echo esc_html( $pg_user->display_name ); ?></dd>
			<dt><?php esc_html_e( 'Correo', 'powergis' ); ?></dt>
			<dd><?php echo esc_html( $pg_user->user_email ); ?></dd>
		</dl>

		<ul class="pg-panel__links">
			<li><a href="<?php echo esc_url( \PowerGIS\Render::privacy_url() ); ?>"><?php esc_html_e( 'Política de privacidad', 'powergis' ); ?></a></li>
			<li><a href="<?php echo esc_url( \PowerGIS\Render::support_url() ); ?>"><?php esc_html_e( 'Soporte y ayuda', 'powergis' ); ?></a></li>
		</ul>
	</section>
</aside>
