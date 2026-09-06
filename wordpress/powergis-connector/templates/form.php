<?php
/**
 * Formulario de creación de proyecto.
 *
 * Los `name` de los campos son EXACTAMENTE los que valida
 * `REST_Projects::create_args()`. Si conectas JetFormBuilder, replica estos
 * nombres y el backend no cambia.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>
<form class="pg-form" id="pg-form" novalidate>

	<fieldset>
		<legend><?php esc_html_e( '1 · Tu proyecto', 'powergis' ); ?></legend>

		<label>
			<span><?php esc_html_e( 'Nombre del proyecto', 'powergis' ); ?> *</span>
			<input type="text" name="title" required maxlength="200"
			       placeholder="<?php esc_attr_e( 'Cafetería en el centro', 'powergis' ); ?>">
		</label>

		<div class="pg-form__row">
			<label>
				<span><?php esc_html_e( 'Sector', 'powergis' ); ?></span>
				<select name="sector">
					<option value=""><?php esc_html_e( '— Selecciona —', 'powergis' ); ?></option>
					<?php foreach ( \PowerGIS\Form::SECTORES as $slug => $name ) : ?>
						<option value="<?php echo esc_attr( $slug ); ?>"><?php echo esc_html( $name ); ?></option>
					<?php endforeach; ?>
				</select>
			</label>

			<label>
				<span><?php esc_html_e( 'Tipo de proyecto', 'powergis' ); ?></span>
				<select name="project_type">
					<?php foreach ( \PowerGIS\Form::TIPOS as $slug => $name ) : ?>
						<option value="<?php echo esc_attr( $slug ); ?>"><?php echo esc_html( $name ); ?></option>
					<?php endforeach; ?>
				</select>
			</label>
		</div>

		<div class="pg-form__row">
			<label>
				<span><?php esc_html_e( 'Ticket medio (€)', 'powergis' ); ?></span>
				<input type="number" name="avg_ticket" step="0.01" min="0" placeholder="18.50">
			</label>
			<label>
				<span><?php esc_html_e( 'Superficie (m²)', 'powergis' ); ?></span>
				<input type="number" name="surface_m2" step="1" min="0" placeholder="90">
			</label>
			<label>
				<span><?php esc_html_e( 'Horizonte (meses)', 'powergis' ); ?></span>
				<input type="number" name="horizon_months" step="1" min="1" max="240" placeholder="24">
			</label>
		</div>

		<label>
			<span><?php esc_html_e( 'Empresa', 'powergis' ); ?></span>
			<input type="text" name="company_name" maxlength="200">
		</label>
	</fieldset>

	<fieldset>
		<legend><?php esc_html_e( '2 · Ámbito del análisis', 'powergis' ); ?></legend>
		<p class="pg-muted">
			<?php esc_html_e( 'El ámbito decide qué compara la tabla avanzada de cada sección: si eliges una comunidad, las filas son sus provincias.', 'powergis' ); ?>
		</p>

		<div class="pg-form__row">
			<label>
				<span><?php esc_html_e( 'Nivel', 'powergis' ); ?> *</span>
				<select name="scope_level" id="pg-scope-level">
					<option value="ccaa"><?php esc_html_e( 'Comunidad autónoma', 'powergis' ); ?></option>
					<option value="pais"><?php esc_html_e( 'Nacional', 'powergis' ); ?></option>
					<option value="provincia"><?php esc_html_e( 'Provincia', 'powergis' ); ?></option>
				</select>
			</label>

			<label id="pg-ccaa-wrap">
				<span><?php esc_html_e( 'Comunidad autónoma', 'powergis' ); ?> *</span>
				<select name="scope_code" id="pg-scope-code">
					<?php foreach ( \PowerGIS\Form::CCAA as $code => $name ) : ?>
						<option value="<?php echo esc_attr( $code ); ?>" <?php selected( '13', $code ); ?>>
							<?php echo esc_html( $name ); ?>
						</option>
					<?php endforeach; ?>
				</select>
			</label>

			<label>
				<span><?php esc_html_e( 'Desagregar por', 'powergis' ); ?></span>
				<select name="children_level" id="pg-children-level">
					<option value="provincia"><?php esc_html_e( 'Provincias', 'powergis' ); ?></option>
					<option value="municipio"><?php esc_html_e( 'Municipios', 'powergis' ); ?></option>
				</select>
			</label>
		</div>
	</fieldset>

	<fieldset>
		<legend><?php esc_html_e( '3 · Público objetivo', 'powergis' ); ?></legend>

		<span class="pg-form__label"><?php esc_html_e( 'Rangos de edad', 'powergis' ); ?></span>
		<div class="pg-form__checks">
			<?php foreach ( \PowerGIS\Form::RANGOS_EDAD as $value => $label ) : ?>
				<label class="pg-check">
					<input type="checkbox" name="age[]" value="<?php echo esc_attr( $value ); ?>"
						<?php checked( '18-35', $value ); ?>>
					<span><?php echo esc_html( $label ); ?></span>
				</label>
			<?php endforeach; ?>
		</div>

		<span class="pg-form__label"><?php esc_html_e( 'Género', 'powergis' ); ?></span>
		<div class="pg-form__checks">
			<label class="pg-check">
				<input type="checkbox" name="sex[]" value="F" checked>
				<span><?php esc_html_e( 'Mujeres', 'powergis' ); ?></span>
			</label>
			<label class="pg-check">
				<input type="checkbox" name="sex[]" value="M" checked>
				<span><?php esc_html_e( 'Hombres', 'powergis' ); ?></span>
			</label>
		</div>
	</fieldset>

	<fieldset>
		<legend><?php esc_html_e( '4 · Nivel de informe', 'powergis' ); ?></legend>
		<p class="pg-muted">
			<?php esc_html_e( 'El informe básico es gratuito e incluye el análisis demográfico completo. Podrás ampliarlo a avanzado en cualquier momento desde «Mis proyectos», sin volver a esperar por los datos que ya tienes.', 'powergis' ); ?>
		</p>
	</fieldset>

	<div class="pg-form__actions">
		<button type="submit" class="pg-cta"><?php esc_html_e( 'Generar informe gratuito', 'powergis' ); ?></button>
		<span class="pg-form__status" id="pg-form-status" role="status"></span>
	</div>
</form>

<script>
(function () {
	const form   = document.getElementById('pg-form');
	const status = document.getElementById('pg-form-status');
	const level  = document.getElementById('pg-scope-level');
	const code   = document.getElementById('pg-scope-code');
	const wrap   = document.getElementById('pg-ccaa-wrap');
	const child  = document.getElementById('pg-children-level');

	// Coherencia del ámbito: el motor rechaza «provincia desagregada por CCAA».
	function sync() {
		const isNational = level.value === 'pais';
		wrap.style.display = isNational ? 'none' : '';
		if (isNational) {
			code.value = 'ES';
			child.innerHTML = '<option value="ccaa">Comunidades autónomas</option>' +
			                  '<option value="provincia">Provincias</option>';
		} else if (level.value === 'provincia') {
			child.innerHTML = '<option value="municipio">Municipios</option>';
		} else {
			child.innerHTML = '<option value="provincia">Provincias</option>' +
			                  '<option value="municipio">Municipios</option>';
		}
	}
	level.addEventListener('change', sync);

	form.addEventListener('submit', async function (event) {
		event.preventDefault();
		const button = form.querySelector('button[type=submit]');
		button.disabled = true;
		status.textContent = '<?php echo esc_js( __( 'Creando el proyecto…', 'powergis' ) ); ?>';
		status.className = 'pg-form__status';

		const data = new FormData(form);
		const payload = {
			title:          data.get('title'),
			scope_level:    level.value === 'pais' ? 'pais' : data.get('scope_level'),
			scope_code:     level.value === 'pais' ? 'ES' : data.get('scope_code'),
			children_level: data.get('children_level'),
			age:            data.getAll('age[]'),
			sex:            data.getAll('sex[]'),
			sector:         data.get('sector') || undefined,
			project_type:   data.get('project_type') || undefined,
			company_name:   data.get('company_name') || undefined,
		};
		['avg_ticket', 'surface_m2', 'horizon_months'].forEach(function (key) {
			const raw = data.get(key);
			if (raw !== null && raw !== '') { payload[key] = Number(raw); }
		});
		Object.keys(payload).forEach(function (k) {
			if (payload[k] === undefined) { delete payload[k]; }
		});

		try {
			const response = await fetch('<?php echo esc_url_raw( rest_url( 'saas/v1/projects/create' ) ); ?>', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'X-WP-Nonce': '<?php echo esc_js( wp_create_nonce( 'wp_rest' ) ); ?>',
				},
				credentials: 'same-origin',
				body: JSON.stringify(payload),
			});
			const result = await response.json();
			if (!response.ok) {
				throw new Error(
					(result.context && result.context.errors)
						? result.context.errors.map(function (e) { return e.field + ': ' + e.message; }).join(' · ')
						: (result.message || response.statusText)
				);
			}
			status.textContent = '<?php echo esc_js( __( 'Listo. Abriendo tu informe…', 'powergis' ) ); ?>';
			window.location.href = result.permalink;
		} catch (error) {
			button.disabled = false;
			status.textContent = error.message;
			status.className = 'pg-form__status pg-form__status--error';
		}
	});

	sync();
})();
</script>
