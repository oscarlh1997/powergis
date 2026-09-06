<?php
if (!defined('ABSPATH')) exit;

/**
 * Shortcode: Mis Proyectos
 */
add_shortcode('mis_proyectos', function () {

    if (!is_user_logged_in()) {
        return '<p>Debes iniciar sesión para ver tus proyectos.</p>';
    }

    $projects = get_posts([
        'post_type'   => 'project',
        'author'      => get_current_user_id(),
        'numberposts' => -1,
        'orderby'     => 'date',
        'order'       => 'DESC'
    ]);

    if (!$projects) {
        return '<p>No tienes proyectos todavía.</p>';
    }

    ob_start();
?>

<div class="saas-project-list">

<?php foreach ($projects as $project):

    $status = get_post_meta($project->ID, 'project_status', true);

    $date = get_the_date('d/m/Y', $project->ID);

    /* -------- UBICACION -------- */

    $location_terms = wp_get_post_terms($project->ID, 'location');

    $location = 'España';

    if (!empty($location_terms) && !is_wp_error($location_terms)) {

        $deepest = $location_terms[0];

        foreach ($location_terms as $term) {

            if ($term->parent != 0) {
                $deepest = $term;
            }
        }

        $location = $deepest->name;
    }

    /* -------- SECTOR -------- */

    $sector_terms = wp_get_post_terms($project->ID, 'sector');

    $sector_code = '';
    $sector_name = '';

    if (!empty($sector_terms) && !is_wp_error($sector_terms)) {

        $sector_code = $sector_terms[0]->slug;
        $sector_name = $sector_terms[0]->name;
    }

?>

<div class="saas-project-row" style="border:1px solid #ddd;margin-bottom:15px;padding:12px;">

    <!-- CONTENEDOR SUPERIOR -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">

        <div style="flex:1;">
            <a href="<?php echo esc_url(get_permalink($project->ID)); ?>" style="font-weight:bold;text-decoration:none;color:#000;">
                <?php echo esc_html($project->post_title); ?>
            </a>
        </div>

        <div style="color:#777;font-size:13px;">
            <?php echo esc_html($date); ?>
        </div>

    </div>


    <!-- CONTENEDOR INFERIOR -->

    <div style="display:flex;align-items:center;">

        <!-- UBICACION 20% -->

        <div style="width:20%;">
            <?php echo esc_html($location); ?>
        </div>


        <!-- SECTOR 20% -->

        <div style="width:20%;">

            <?php if ($sector_code): ?>

                <span title="<?php echo esc_attr($sector_name); ?>">
                    <?php echo esc_html(strtoupper($sector_code)); ?>
                </span>

            <?php endif; ?>

        </div>


        <!-- ESTADO 50% -->

        <div style="width:50%;">

            <?php if ($status === 'completed'): ?>

                Completado

            <?php else: ?>

                <a href="<?php echo esc_url(get_permalink($project->ID)); ?>"
                   style="background:#0073aa;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:14px;">
                    Realizar Proyecto
                </a>

            <?php endif; ?>

        </div>


        <!-- LUPA 10% -->

        <div style="width:10%;text-align:right;">

            <a href="<?php echo esc_url(get_permalink($project->ID)); ?>" style="font-size:18px;text-decoration:none;">
                🔍
            </a>

        </div>

    </div>

</div>

<?php endforeach; ?>

</div>

<?php

return ob_get_clean();

});



/**
 * Shortcode: Crear Proyecto V6
 * Reescrito 16 ago 2026: mismo mecanismo de datos/nonce que la versión original
 * (probada y funcionando), con nuevo diseño de marca PowerGIS, formulario en pasos,
 * autoguardado de borrador, tooltips de ayuda y payload anidado bajo "definicion"
 * para que la asignación automática de taxonomías en rest-projects.php funcione.
 */
add_shortcode('crear_proyecto_v6', function () {

    if (!is_user_logged_in()) {

        $actual_link = (isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] === 'on' ? "https" : "http")
            . "://$_SERVER[HTTP_HOST]$_SERVER[REQUEST_URI]";
        $login_url = wp_login_url($actual_link);
        $register_url = site_url('/wp-login.php?action=register&redirect_to=' . urlencode($actual_link));

        ob_start(); ?>
        <div id="pg-wizard" class="pg-loggedout">
            <div class="pg-loggedout__card">
                <h2>Inicia sesión para crear tu proyecto</h2>
                <p>Necesitas una cuenta en PowerGIS para guardar tu formulario y generar informes.</p>
                <a class="pg-btn pg-btn--primary" href="<?php echo esc_url($login_url); ?>">Iniciar sesión</a>
                <a class="pg-btn pg-btn--ghost" href="<?php echo esc_url($register_url); ?>">Crear cuenta gratis</a>
            </div>
        </div>
        <style>
            #pg-wizard.pg-loggedout { max-width:480px;margin:60px auto;font-family:'Poppins',sans-serif;text-align:center; }
            .pg-loggedout__card{border:1.5px solid #E7E2DC;border-radius:14px;padding:34px 28px;}
            .pg-loggedout__card h2{font-family:'Raleway',sans-serif;color:#505050;margin:0 0 10px;font-size:20px;}
            .pg-loggedout__card p{color:#888;font-size:13.5px;margin-bottom:22px;}
            .pg-btn{display:inline-flex;font-weight:600;font-size:13.5px;border-radius:999px;padding:12px 22px;border:1.5px solid transparent;cursor:pointer;text-decoration:none;margin:0 5px;}
            .pg-btn--primary{background:#FF7124;color:#fff;}
            .pg-btn--ghost{border-color:#E7E2DC;color:#505050;}
        </style>
        <?php
        return ob_get_clean();
    }

    $cnae_url    = SAAS_STUDIES_URL . 'data/Estructura_CNAE2025.csv';
    $arbol_url   = SAAS_STUDIES_URL . 'data/arbol.json';
    $paises_url  = SAAS_STUDIES_URL . 'data/paises.csv';

    $rest_create_url = rest_url('saas/v1/projects/create');
    $rest_draft_url  = rest_url('saas/v1/projects/save-draft');
    $wp_nonce = wp_create_nonce('wp_rest');

    ob_start();
    ?>

<style>
  #pg-wizard * { box-sizing: border-box; }
  #pg-wizard {
    --pg-orange: #FF7124; --pg-orange-dark: #E15C10; --pg-orange-light: #FFF1E7;
    --pg-ink: #505050; --pg-ink-soft: #888888; --pg-line: #E7E2DC;
    --pg-surface: #FAF8F6; --pg-white: #FFFFFF; --pg-success: #2E9E5B; --pg-error: #D64545;
    --pg-radius: 14px; --pg-radius-sm: 8px;
    font-family: 'Roboto', sans-serif; color: var(--pg-ink); background: var(--pg-white);
    max-width: 980px; margin: 0 auto; line-height: 1.5; -webkit-font-smoothing: antialiased;
  }
  #pg-wizard a { color: var(--pg-orange); }
  #pg-wizard h1, #pg-wizard h2, #pg-wizard h3, #pg-wizard legend { font-family: 'Raleway', sans-serif; color: var(--pg-ink); margin: 0; }

  .pg-head { padding: 28px 24px 0; }
  .pg-head h1 { font-size: 26px; font-weight: 800; }
  .pg-head p { color: var(--pg-ink-soft); font-size: 14.5px; margin-top: 6px; }

  .pg-stepper { display: flex; gap: 4px; margin: 22px 24px 0; padding: 0; list-style: none; }
  .pg-step { flex: 1; padding-bottom: 14px; cursor: pointer; border: none; background: none; text-align: left; font-family: 'Poppins', sans-serif; }
  .pg-step__bar { height: 4px; border-radius: 4px; background: var(--pg-line); transition: background .25s ease; }
  .pg-step.is-done .pg-step__bar, .pg-step.is-active .pg-step__bar { background: var(--pg-orange); }
  .pg-step__label { display: flex; align-items: center; gap: 7px; margin-top: 10px; font-size: 12.5px; font-weight: 600; color: var(--pg-ink-soft); }
  .pg-step.is-active .pg-step__label, .pg-step.is-done .pg-step__label { color: var(--pg-ink); }
  .pg-step__num { width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; border: 1.5px solid var(--pg-line); color: var(--pg-ink-soft); flex: none; }
  .pg-step.is-active .pg-step__num { border-color: var(--pg-orange); color: var(--pg-orange); }
  .pg-step.is-done .pg-step__num { background: var(--pg-orange); border-color: var(--pg-orange); color: #fff; }
  .pg-step__label span.pg-step__text { display: none; }
  @media (min-width: 640px) { .pg-step__label span.pg-step__text { display: inline; } }

  .pg-section { display: none; padding: 30px 24px 8px; animation: pgFade .35s ease; }
  .pg-section.is-active { display: block; }
  @keyframes pgFade { from { opacity: 0; transform: translateY(6px);} to { opacity: 1; transform: translateY(0);} }
  @media (prefers-reduced-motion: reduce) { .pg-section { animation: none; } }
  .pg-section__title { font-size: 20px; font-weight: 700; }
  .pg-section__desc { color: var(--pg-ink-soft); font-size: 14px; margin-top: 6px; max-width: 62ch; }
  .pg-block { margin-top: 30px; }
  .pg-block__title { font-family: 'Poppins', sans-serif; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: var(--pg-orange); margin-bottom: 4px; }
  .pg-block__desc { font-size: 13px; color: var(--pg-ink-soft); margin-bottom: 14px; }

  .pg-field { margin-top: 18px; }
  .pg-label { display: flex; align-items: center; gap: 6px; font-family: 'Poppins', sans-serif; font-size: 14px; font-weight: 600; margin-bottom: 6px; }
  .pg-label .req { color: var(--pg-orange); margin-left: -2px; }
  .pg-hint { font-size: 12.5px; color: var(--pg-ink-soft); margin-top: 5px; }
  .pg-error-msg { font-size: 12.5px; color: var(--pg-error); margin-top: 5px; display: none; }
  .pg-field.has-error .pg-error-msg { display: block; }
  .pg-field.has-error input, .pg-field.has-error select, .pg-field.has-error textarea { border-color: var(--pg-error) !important; }

  .pg-input, .pg-select, .pg-textarea { width: 100%; font-family: 'Roboto', sans-serif; font-size: 14.5px; color: var(--pg-ink); background: var(--pg-white); border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); padding: 11px 13px; transition: border-color .15s ease; }
  .pg-input:focus, .pg-select:focus, .pg-textarea:focus { outline: none; border-color: var(--pg-orange); box-shadow: 0 0 0 3px var(--pg-orange-light); }
  .pg-input[readonly] { background: var(--pg-surface); color: var(--pg-ink-soft); }
  .pg-row2 { display: grid; grid-template-columns: 1fr; gap: 14px; }
  @media (min-width: 640px) { .pg-row2 { grid-template-columns: 1fr 1fr; } }

  /* Tooltip "i" de ayuda */
  .pg-info { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 15px; height: 15px; border-radius: 50%; background: var(--pg-line); color: var(--pg-ink-soft); font-size: 10px; font-weight: 700; font-family: 'Poppins', sans-serif; cursor: help; flex: none; }
  .pg-info::after { content: attr(data-tip); position: absolute; left: 50%; bottom: calc(100% + 8px); transform: translateX(-50%) translateY(4px); background: var(--pg-ink); color: #fff; font-family: 'Roboto', sans-serif; font-weight: 400; font-size: 12px; line-height: 1.4; padding: 9px 12px; border-radius: 8px; width: max-content; max-width: 240px; opacity: 0; pointer-events: none; transition: all .15s ease; z-index: 20; text-align: left; }
  .pg-info:hover::after, .pg-info:focus::after, .pg-info.is-open::after { opacity: 1; transform: translateX(-50%) translateY(0); }
  .pg-info:focus { outline: none; }

  .pg-cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  @media (min-width: 560px) { .pg-cards--4 { grid-template-columns: repeat(4, 1fr); } }
  .pg-card { position: relative; }
  .pg-card input { position: absolute; opacity: 0; inset: 0; cursor: pointer; margin: 0; width: 100%; height: 100%; }
  .pg-card__ui { border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); padding: 18px 10px; text-align: center; font-family: 'Poppins', sans-serif; font-size: 12.5px; font-weight: 600; color: var(--pg-ink); transition: all .15s ease; height: 100%; display: flex; flex-direction: column; align-items: center; gap: 9px; }
  .pg-card__ui svg { width: 22px; height: 22px; stroke: var(--pg-ink-soft); transition: stroke .15s ease; }
  .pg-card__ui img { width: 60px; height: 60px; object-fit: contain; }
  .pg-tipo-explainer { display: none; align-items: flex-start; gap: 10px; background: var(--pg-orange-light); border: 1px solid #FFD9BE; border-radius: var(--pg-radius-sm); padding: 12px 14px; margin-top: 12px; animation: pgFadeIn .2s ease; }
  .pg-tipo-explainer.is-visible { display: flex; }
  .pg-tipo-explainer__icon { font-size: 16px; flex: none; line-height: 1.4; }
  .pg-tipo-explainer p { margin: 0; font-size: 13px; color: var(--pg-ink); line-height: 1.5; }
  @keyframes pgFadeIn { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: translateY(0); } }
  .pg-card input:checked + .pg-card__ui { border-color: var(--pg-orange); background: var(--pg-orange-light); color: var(--pg-orange-dark); }
  .pg-card input:checked + .pg-card__ui svg { stroke: var(--pg-orange); }
  .pg-card input:focus-visible + .pg-card__ui { outline: 2px solid var(--pg-orange); outline-offset: 2px; }
  .pg-card__scale { width: 100%; height: 3px; background: var(--pg-line); border-radius: 3px; position: relative; margin-top: 2px; }
  .pg-card__scale i { position: absolute; top: -2.5px; width: 8px; height: 8px; border-radius: 50%; background: var(--pg-ink-soft); }
  .pg-card input:checked + .pg-card__ui .pg-card__scale i { background: var(--pg-orange); }

  /* Ticket: tarjetas seleccionables múltiples */
  .pg-ticket-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
  @media (min-width: 640px) { .pg-ticket-grid { grid-template-columns: 1fr 1fr; } }
  .pg-ticket { position: relative; }
  .pg-ticket input { position: absolute; opacity: 0; inset: 0; cursor: pointer; margin: 0; }
  .pg-ticket__ui { display: flex; align-items: center; justify-content: space-between; gap: 8px; border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); padding: 12px 14px; transition: all .15s ease; }
  .pg-ticket input:checked + .pg-ticket__ui { border-color: var(--pg-orange); background: var(--pg-orange-light); }
  .pg-ticket__name { font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 13px; }
  .pg-ticket__range { font-size: 11.5px; color: var(--pg-ink-soft); }
  .pg-max-warning { font-size: 12px; color: var(--pg-orange-dark); margin-top: 8px; display: none; }
  .pg-max-warning.is-visible { display: block; }

  .pg-list { display: flex; flex-direction: column; gap: 8px; }
  .pg-opt { position: relative; }
  .pg-opt input { position: absolute; opacity: 0; inset: 0; cursor: pointer; margin: 0; }
  .pg-opt__ui { display: flex; align-items: center; gap: 11px; border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); padding: 11px 13px; transition: all .15s ease; cursor: pointer; }
  .pg-opt__dot { flex: none; width: 17px; height: 17px; border-radius: 5px; border: 1.5px solid var(--pg-line); position: relative; }
  .pg-opt input:checked ~ .pg-opt__ui { border-color: var(--pg-orange); background: var(--pg-orange-light); }
  .pg-opt input:checked ~ .pg-opt__ui .pg-opt__dot { border-color: var(--pg-orange); background: var(--pg-orange); }
  .pg-opt input:checked ~ .pg-opt__ui .pg-opt__dot::after { content: ''; position: absolute; inset: 4px; background: #fff; border-radius: 2px; }
  .pg-opt input:focus-visible ~ .pg-opt__ui { outline: 2px solid var(--pg-orange); outline-offset: 1px; }
  .pg-opt__text { flex: 1; font-family: 'Poppins', sans-serif; font-size: 13.5px; font-weight: 600; }
  .pg-opt .pg-info { margin-left: auto; }

  .pg-switch-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); padding: 13px 15px; }
  .pg-switch { position: relative; width: 42px; height: 24px; flex: none; }
  .pg-switch input { opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; position: absolute; z-index: 1; }
  .pg-switch__track { position: absolute; inset: 0; background: var(--pg-line); border-radius: 20px; transition: background .15s ease; }
  .pg-switch__track::after { content: ''; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; background: #fff; border-radius: 50%; transition: transform .15s ease; box-shadow: 0 1px 2px rgba(0,0,0,.2); }
  .pg-switch input:checked ~ .pg-switch__track { background: var(--pg-orange); }
  .pg-switch input:checked ~ .pg-switch__track::after { transform: translateX(18px); }

  /* Autocompletado (competencia / generadores de tráfico) */
  .pg-autocomplete { position: relative; }
  .pg-suggestions { position: absolute; left: 0; right: 0; top: calc(100% + 4px); background: #fff; border: 1.5px solid var(--pg-line); border-radius: var(--pg-radius-sm); max-height: 180px; overflow-y: auto; z-index: 15; display: none; box-shadow: 0 8px 20px rgba(80,80,80,.1); }
  .pg-suggestions.is-visible { display: block; }
  .pg-suggestion { padding: 9px 13px; font-size: 13.5px; cursor: pointer; }
  .pg-suggestion:hover, .pg-suggestion.is-active { background: var(--pg-orange-light); }

  /* Selector de nacionalidades (chips, hasta 5) */
  .pg-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
  .pg-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--pg-orange-light); color: var(--pg-orange-dark); font-family: 'Poppins', sans-serif; font-size: 12.5px; font-weight: 600; padding: 6px 8px 6px 12px; border-radius: 999px; }
  .pg-chip button { background: none; border: none; color: var(--pg-orange-dark); cursor: pointer; font-size: 13px; line-height: 1; padding: 2px; }
  .pg-chips-note { font-size: 12px; color: var(--pg-ink-soft); margin-top: 6px; }

  .pg-actions { position: sticky; bottom: 0; background: var(--pg-white); border-top: 1px solid var(--pg-line); padding: 14px 24px; display: flex; align-items: center; gap: 10px; margin-top: 30px; flex-wrap: wrap; }
  .pg-validation-banner { display: none; flex: 1 0 100%; background: var(--pg-orange); color: #fff; font-family: 'Poppins', sans-serif; font-size: 13px; font-weight: 600; padding: 10px 14px; border-radius: 10px; text-align: center; margin-bottom: 2px; animation: pgBannerIn .2s ease; }
  .pg-validation-banner.is-visible { display: block; }
  @keyframes pgBannerIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
  .pg-btn { font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 13.5px; border-radius: 999px; padding: 12px 20px; border: 1.5px solid transparent; cursor: pointer; transition: all .15s ease; display: inline-flex; align-items: center; gap: 6px; }
  .pg-btn:disabled { opacity: .5; cursor: not-allowed; }
  .pg-btn--ghost { background: transparent; border-color: var(--pg-line); color: var(--pg-ink); }
  .pg-btn--ghost:hover:not(:disabled) { border-color: var(--pg-ink-soft); }
  .pg-btn--soft { background: var(--pg-surface); color: var(--pg-ink); }
  .pg-btn--soft:hover:not(:disabled) { background: var(--pg-line); }
  .pg-btn--primary { background: var(--pg-orange); color: #fff; }
  .pg-btn--primary:hover:not(:disabled) { background: var(--pg-orange-dark); }
  .pg-actions .pg-btn--soft { margin-left: auto; }
  .pg-save-status { font-size: 12px; color: var(--pg-ink-soft); font-family: 'Poppins', sans-serif; white-space: nowrap; }
  .pg-save-status.is-ok { color: var(--pg-success); }

  .pg-toast { position: fixed; left: 50%; bottom: 24px; transform: translate(-50%, 12px); background: var(--pg-ink); color: #fff; font-family: 'Poppins', sans-serif; font-size: 13px; padding: 11px 18px; border-radius: 999px; opacity: 0; pointer-events: none; transition: all .25s ease; z-index: 9999; }
  .pg-toast.is-visible { opacity: 1; transform: translate(-50%, 0); }

  .pg-conditional { display: none; }
  .pg-conditional.is-visible { display: block; }
  .pg-fallback-note { font-size: 11px; color: var(--pg-ink-soft); background: var(--pg-surface); border-radius: 6px; padding: 6px 9px; margin-top: 6px; display: none; }
  .pg-fallback-note.is-visible { display: block; }
</style>

<div id="pg-wizard">
  <div class="pg-head">
    <h1>Crear proyecto</h1>
    <p>Cuéntanos sobre tu negocio y la ubicación que quieres evaluar. Cuanto más completo el brief, más preciso el informe.</p>
  </div>

  <ul class="pg-stepper" id="pgStepper">
    <li class="pg-step is-active" data-step="0"><div class="pg-step__bar"></div><div class="pg-step__label"><span class="pg-step__num">1</span><span class="pg-step__text">Definición</span></div></li>
    <li class="pg-step" data-step="1"><div class="pg-step__bar"></div><div class="pg-step__label"><span class="pg-step__num">2</span><span class="pg-step__text">Buyer Persona</span></div></li>
    <li class="pg-step" data-step="2"><div class="pg-step__bar"></div><div class="pg-step__label"><span class="pg-step__num">3</span><span class="pg-step__text">Ecosistema</span></div></li>
    <li class="pg-step" data-step="3"><div class="pg-step__bar"></div><div class="pg-step__label"><span class="pg-step__num">4</span><span class="pg-step__text">Entorno</span></div></li>
  </ul>

  <form id="pgForm" novalidate>

    <!-- ============ SECCIÓN 1: DEFINICIÓN ============ -->
    <section class="pg-section is-active" data-section="0">
      <h2 class="pg-section__title">Definición y contexto del proyecto</h2>
      <p class="pg-section__desc">Esta sección establece el marco operativo y la naturaleza del negocio a analizar.</p>

      <div class="pg-field">
        <label class="pg-label" for="f-nombre">Nombre del proyecto<span class="req">*</span></label>
        <input class="pg-input" type="text" id="f-nombre" name="project_name" placeholder="Ej: Lavandería en Madrid" autocomplete="off">
        <p class="pg-error-msg">Ponle un nombre a tu proyecto para poder guardarlo.</p>
      </div>

      <div class="pg-field">
        <label class="pg-label">1. Tipo de estudio<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Selecciona el tipo de estudio que deseas realizar.">i</span></label>
        <div class="pg-cards pg-cards--4" data-group="tipo_estudio">
          <label class="pg-card"><input type="radio" name="tipo_estudio" value="nacional"><span class="pg-card__ui"><img src="https://powergis.es/wp-content/uploads/2026/07/spaintrans.png" alt="" loading="lazy">Nacional</span></label>
          <label class="pg-card"><input type="radio" name="tipo_estudio" value="ccaa"><span class="pg-card__ui"><img src="https://powergis.es/wp-content/uploads/2026/07/comuni-trans.png" alt="" loading="lazy">Comunidad</span></label>
          <label class="pg-card"><input type="radio" name="tipo_estudio" value="provincia"><span class="pg-card__ui"><img src="https://powergis.es/wp-content/uploads/2026/07/municipio-trans.png" alt="" loading="lazy">Provincia</span></label>
          <label class="pg-card"><input type="radio" name="tipo_estudio" value="poblacion"><span class="pg-card__ui"><img src="https://powergis.es/wp-content/uploads/2026/07/prov-trans.png" alt="" loading="lazy">Población</span></label>
        </div>
        <div class="pg-tipo-explainer" id="tipoExplainer">
          <span class="pg-tipo-explainer__icon">💡</span>
          <p id="tipoExplainerText"></p>
        </div>
        <p class="pg-error-msg">Elige hasta qué nivel territorial quieres el análisis.</p>
      </div>

      <div class="pg-conditional" id="cond-ccaa">
        <div class="pg-field">
          <label class="pg-label" for="f-ccaa">Comunidad autónoma<span class="req">*</span></label>
          <select class="pg-select" id="f-ccaa" name="ccaa"><option value="">Cargando...</option></select>
          <p class="pg-error-msg">Selecciona la comunidad autónoma.</p>
        </div>
      </div>
      <div class="pg-conditional" id="cond-provincia">
        <div class="pg-field">
          <label class="pg-label" for="f-provincia">Provincia<span class="req">*</span></label>
          <select class="pg-select" id="f-provincia" name="provincia" disabled><option value="">Elige antes la comunidad...</option></select>
          <p class="pg-error-msg">Selecciona la provincia.</p>
        </div>
      </div>
      <div class="pg-conditional" id="cond-poblacion">
        <div class="pg-field">
          <label class="pg-label" for="f-poblacion">Población<span class="req">*</span></label>
          <select class="pg-select" id="f-poblacion" name="poblacion" disabled><option value="">Elige antes la provincia...</option></select>
          <p class="pg-error-msg">Selecciona la población.</p>
        </div>
      </div>

      <div class="pg-field">
        <label class="pg-label">3. Sector y actividad económica<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Describe el giro comercial de tu empresa y la categoría específica de productos o servicios.">i</span></label>
        <p class="pg-hint" style="margin:0 0 10px">Si no encuentras tu actividad exacta, elige la más aproximada.</p>
        <div class="pg-row2">
          <div class="pg-field" style="margin-top:0">
            <label class="pg-label" for="f-sector">Sector<span class="req">*</span></label>
            <select class="pg-select" id="f-sector" name="sector"><option value="">Cargando sectores...</option></select>
            <p class="pg-fallback-note" id="sector-fallback-note">Mostrando categorías de ejemplo — pendiente de conectar el catálogo CNAE completo.</p>
            <p class="pg-error-msg">Elige el sector económico del negocio.</p>
          </div>
          <div class="pg-field" style="margin-top:0">
            <label class="pg-label" for="f-actividad">Actividad económica<span class="req">*</span></label>
            <select class="pg-select" id="f-actividad" name="actividad" disabled><option value="">Elige antes el sector...</option></select>
            <p class="pg-error-msg">Elige la actividad concreta.</p>
          </div>
        </div>
        <div class="pg-field">
          <label class="pg-label" for="f-cnae">Código CNAE</label>
          <input class="pg-input" type="text" id="f-cnae" name="cnae" readonly placeholder="Se autocompleta al elegir la actividad">
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">4. Clasificación del ticket promedio<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Valor medio de una transacción de venta habitual, para determinar el posicionamiento de precio.">i</span></label>
          <div class="pg-ticket-grid" id="ticket-grid" data-warn-max="2">
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Micro"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Micro-gasto</span><br><span class="pg-ticket__range">&lt; 10€ · impulso / recurrente</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Bajo"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Bajo</span><br><span class="pg-ticket__range">10-50€ · consumo diario</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Medio"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Medio</span><br><span class="pg-ticket__range">51-200€ · compra planificada</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Medio-Alto"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Medio-Alto</span><br><span class="pg-ticket__range">201-1.000€ · bienes duraderos</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Alto"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Alto / Premium</span><br><span class="pg-ticket__range">1.001-5.000€ · inversión de estatus</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Lujo"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Lujo</span><br><span class="pg-ticket__range">&gt; 5.000€ · alta consideración</span></span></span></label>
          </div>
          <p class="pg-max-warning" id="ticket-warning">Se recomienda marcar 1 o 2 opciones para obtener resultados más precisos.</p>
          <p class="pg-error-msg">Elige al menos una franja de ticket promedio.</p>
        </div>
      </div>
    </section>

    <!-- ============ SECCIÓN 2: BUYER PERSONA ============ -->
    <section class="pg-section" data-section="1">
      <h2 class="pg-section__title">Perfil del público objetivo (Buyer Persona)</h2>
      <p class="pg-section__desc">Detalla quién es el consumidor ideal al que dirigiremos los esfuerzos. Ninguno de estos campos es obligatorio.</p>

      <div class="pg-block">
        <div class="pg-block__title">Atributos demográficos</div>
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">1. Rango de edad prioritario<span class="pg-info" tabindex="0" data-tip="Identifica los grupos de edad que concentran la mayor parte de tu demanda potencial.">i</span></label>
          <div class="pg-list" data-group="edad" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="edad" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="18-24"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">18 – 24 años</span><span class="pg-info" tabindex="0" data-tip="Jóvenes adultos, estudiantes o primer empleo.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="25-34"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">25 – 34 años</span><span class="pg-info" tabindex="0" data-tip="Profesionales jóvenes, inicio de independencia financiera.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="35-44"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">35 – 44 años</span><span class="pg-info" tabindex="0" data-tip="Consolidación profesional y familiar.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="45-54"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">45 – 54 años</span><span class="pg-info" tabindex="0" data-tip="Mayor poder adquisitivo, hogares maduros.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="55-64"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">55 – 64 años</span><span class="pg-info" tabindex="0" data-tip="Pre-jubilación y enfoque en salud/bienestar.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="65+"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">65 años o más</span><span class="pg-info" tabindex="0" data-tip="Jubilados con necesidades específicas de ocio y salud.">i</span></span></label>
          </div>
          <div id="gen-labels" class="pg-hint"></div>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-genero">2. Segmentación por género<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Indica si tu producto se dirige a un sexo específico o si tiene un enfoque neutro/unisex.">i</span></label>
          <select class="pg-select" id="f-genero" name="genero">
            <option value="Indiferente">Indiferente</option>
            <option value="Femenino">Femenino</option>
            <option value="Masculino">Masculino</option>
          </select>
        </div>

        <div class="pg-field">
          <label class="pg-label">3. Estado civil y estructura familiar<span class="pg-info" tabindex="0" data-tip="Define si tu cliente ideal es soltero, casado, o si su decisión de compra depende de su rol familiar. Puedes marcar varias.">i</span></label>
          <div class="pg-list" data-group="estado_civil" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Soltero"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Soltero(a) sin hijos</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Pareja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">En pareja / casado(a) sin hijos</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Nido Lleno"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Nido lleno</span><span class="pg-info" tabindex="0" data-tip="Pareja con hijos menores de 12 años.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Nido Adolescentes"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Nido con adolescentes</span><span class="pg-info" tabindex="0" data-tip="Hijos de 13 a 18 años.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Nido Vacío"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Nido vacío</span><span class="pg-info" tabindex="0" data-tip="Hijos que ya se independizaron.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Monoparental"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Monoparental</span><span class="pg-info" tabindex="0" data-tip="Padre o madre soltero(a) con hijos.">i</span></span></label>
          </div>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-academia">4. Nivel de formación académica<span class="pg-info" tabindex="0" data-tip="Grado máximo de estudios que suele tener tu cliente.">i</span></label>
          <select class="pg-select" id="f-academia" name="academia">
            <option>Indiferente</option>
            <option>Sin estudios / Educación básica</option>
            <option>Educación Secundaria / Bachillerato</option>
            <option>Técnico Superior / Grado Medio</option>
            <option>Universitario / Grado Licenciatura</option>
            <option>Postgrado (Maestría, Doctorado, MBA)</option>
          </select>
        </div>

        <div class="pg-field">
          <label class="pg-label">5. Nacionalidad<span class="pg-info" tabindex="0" data-tip="Especifica si tu público es local, extranjero o pertenece a una comunidad cultural determinada.">i</span></label>
          <select class="pg-select" id="f-nacionalidad-picker"><option value="">Cargando países...</option></select>
          <div class="pg-chips" id="nacionalidad-chips"></div>
          <p class="pg-chips-note" id="nacionalidad-note">Elige hasta 5. Déjalo vacío si es indiferente.</p>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Perfil socioeconómico</div>
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">6. Nivel socioeconómico (NSE)<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Clasifica el estatus social de tu audiencia según su capacidad de consumo y acceso a bienes.">i</span></label>
          <div class="pg-list" data-group="nse" data-exclusive="Indiferente" data-max="3">
            <label class="pg-opt"><input type="checkbox" name="nse" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="nse" value="A/B"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">A/B — Clase alta</span><span class="pg-info" tabindex="0" data-tip="Lujo, alta capacidad de ahorro.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="nse" value="C+"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">C+ — Media-alta</span><span class="pg-info" tabindex="0" data-tip="Confort, servicios premium.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="nse" value="C"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">C — Media</span><span class="pg-info" tabindex="0" data-tip="Consumo estándar, créditos.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="nse" value="D+"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">D+ — Media-baja</span><span class="pg-info" tabindex="0" data-tip="Consumo básico, sensible al precio.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="nse" value="D/E"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">D/E — Baja</span><span class="pg-info" tabindex="0" data-tip="Subsistencia.">i</span></span></label>
          </div>
          <p class="pg-max-warning" id="nse-warning">Hemos limitado la selección a máximo 3 para obtener mejores resultados.</p>
        </div>

        <div class="pg-field">
          <label class="pg-label">7. Renta bruta anual por hogar<span class="pg-info" tabindex="0" data-tip="Estima el ingreso total acumulado por la unidad familiar del cliente objetivo.">i</span></label>
          <div class="pg-list" data-group="renta_anual" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Subsistencia"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Subsistencia</span><span class="pg-info" tabindex="0" data-tip="< 12.000 €/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Baja-Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase baja-media</span><span class="pg-info" tabindex="0" data-tip="12.000€ a 24.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase media</span><span class="pg-info" tabindex="0" data-tip="24.001€ a 45.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Media-Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase media-alta</span><span class="pg-info" tabindex="0" data-tip="45.001€ a 75.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase alta</span><span class="pg-info" tabindex="0" data-tip="75.001€ a 150.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="HNWI"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alto patrimonio (HNWI)</span><span class="pg-info" tabindex="0" data-tip="> 150.000 €/año">i</span></span></label>
          </div>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-renta-mensual">8. Renta mensual disponible<span class="pg-info" tabindex="0" data-tip="Excedente de dinero que le queda al cliente tras cubrir sus necesidades básicas.">i</span></label>
          <select class="pg-select" id="f-renta-mensual" name="renta_mensual">
            <option value="Indiferente">Indiferente</option>
            <option value="Renta Crítica">Renta crítica — &lt; 300€ libres/mes (ahorro nulo)</option>
            <option value="Renta Ajustada">Renta ajustada — 301€-800€ libres/mes (busca ofertas)</option>
            <option value="Renta Holgada">Renta holgada — 801€-2.500€ libres/mes (ocio, marcas premium)</option>
            <option value="Renta Discrecional">Renta discrecional — &gt; 2.500€ libres/mes (lujo e inversión)</option>
          </select>
        </div>
      </div>
    </section>

    <!-- ============ SECCIÓN 3: ECOSISTEMA ============ -->
    <section class="pg-section" data-section="2">
      <h2 class="pg-section__title">Análisis del ecosistema comercial</h2>
      <p class="pg-section__desc">Dinámica del área elegida: competidores y puntos de interés cercanos. Todos opcionales.</p>

      <div class="pg-field">
        <div class="pg-switch-row">
          <div>
            <b style="font-family:'Poppins',sans-serif;font-size:13.5px">Competencia directa</b>
            <p class="pg-hint" style="margin-top:2px">Negocios que ofrecen exactamente el mismo producto o servicio que el tuyo, en tu radio de influencia. Ej: si abres una lavandería, tu competencia directa son otras lavanderías cercanas.</p>
          </div>
          <label class="pg-switch"><input type="checkbox" name="comp_directa"><span class="pg-switch__track"></span></label>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Competencia indirecta <span style="text-transform:none;font-weight:400;color:var(--pg-ink-soft)">(opcional)</span></div>
        <div class="pg-block__desc">Negocios distintos al tuyo que igualmente compiten por el gasto o el tiempo de tu mismo cliente — no venden lo mismo, pero son una alternativa a tu servicio. Ej: en una lavandería, un hotel o un geriátrico pueden ser competencia indirecta porque también gestionan la colada de sus clientes.</div>
        <div class="pg-row2">
          <div class="pg-field" style="margin-top:0">
            <label class="pg-label" for="f-comp-alta">Nivel alto</label>
            <div class="pg-autocomplete">
              <input class="pg-input cnae-search" type="search" id="f-comp-alta" name="comp_indirecta_alta" placeholder="Escribe libremente, ej: hoteles, geriátricos..." autocomplete="off">
              <div class="pg-suggestions"></div>
            </div>
          </div>
          <div class="pg-field" style="margin-top:0">
            <label class="pg-label" for="f-comp-media">Nivel medio</label>
            <div class="pg-autocomplete">
              <input class="pg-input cnae-search" type="search" id="f-comp-media" name="comp_indirecta_media" placeholder="Escribe libremente, ej: coworkings..." autocomplete="off">
              <div class="pg-suggestions"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Generadores de tráfico <span style="text-transform:none;font-weight:400;color:var(--pg-ink-soft)">(opcional)</span></div>
        <div class="pg-block__desc">Comercios o lugares cercanos que atraen visitantes que podrían convertirse en tus clientes, aunque no compren en tu categoría. Ej: un gimnasio o una parada de metro cercana generan tráfico de personas que luego pueden entrar a tu negocio.</div>
        <div class="pg-row2">
          <div class="pg-field" style="margin-top:0">
            <label class="pg-label" for="f-trafico-alto">Nivel alto</label>
            <div class="pg-autocomplete">
              <input class="pg-input cnae-search" type="search" id="f-trafico-alto" name="gen_trafico_alto" placeholder="Escribe libremente, ej: estación de metro..." autocomplete="off">
              <div class="pg-suggestions"></div>
            </div>
          </div>
          <div class="pg-field" style="margin-top:0">
          <label class="pg-label" for="f-trafico-medio">Nivel medio</label>
          <div class="pg-autocomplete">
            <input class="pg-input cnae-search" type="search" id="f-trafico-medio" name="gen_trafico_medio" placeholder="Escribe libremente, ej: gimnasios, colegios..." autocomplete="off">
            <div class="pg-suggestions"></div>
          </div>
        </div>
      </div>
      </div>
    </section>

    <!-- ============ SECCIÓN 4: ENTORNO ============ -->
    <section class="pg-section" data-section="3">
      <h2 class="pg-section__title">Análisis del entorno y factores externos</h2>
      <p class="pg-section__desc">Variables del contexto físico que influyen en el comportamiento del mercado.</p>

      <div class="pg-field">
        <label class="pg-label">Climatología y factores estacionales<span class="pg-info" tabindex="0" data-tip="Indica si la demanda de tu producto varía según el clima dominante.">i</span></label>
        <div class="pg-list" data-group="clima" data-exclusive="Indiferente">
          <label class="pg-opt"><input type="checkbox" name="clima" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
          <label class="pg-opt"><input type="checkbox" name="clima" value="Calido"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Cálido</span></span></label>
          <label class="pg-opt"><input type="checkbox" name="clima" value="Templado"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Templado</span></span></label>
          <label class="pg-opt"><input type="checkbox" name="clima" value="Frio"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Frío</span></span></label>
          <label class="pg-opt"><input type="checkbox" name="clima" value="Seco"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Seco</span></span></label>
          <label class="pg-opt"><input type="checkbox" name="clima" value="Humedo"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Húmedo</span></span></label>
        </div>
      </div>

      <div class="pg-row2" style="margin-top:22px">
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">Tráfico peatonal<span class="pg-info" tabindex="0" data-tip="Flujo de personas a pie en la zona.">i</span></label>
          <div class="pg-list" data-group="trafico_peaton" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Muy Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Muy alta (Premium)</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Media</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Baja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Baja</span></span></label>
          </div>
        </div>
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">Tráfico vehicular<span class="pg-info" tabindex="0" data-tip="Flujo de coches y transporte en la zona.">i</span></label>
          <div class="pg-list" data-group="trafico_vehicular" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Indiferente"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Muy Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Muy alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Media</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Baja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Baja</span></span></label>
          </div>
        </div>
      </div>

      <div class="pg-field">
        <label class="pg-label" for="f-comentarios">¿Algún comentario que debamos saber al realizar este proyecto?</label>
        <textarea class="pg-input" id="f-comentarios" name="comentarios" rows="3" placeholder="Opcional" style="resize:vertical"></textarea>
      </div>
    </section>

    <div class="pg-actions">
      <div class="pg-validation-banner" id="pgValidationBanner">Datos obligatorios sin rellenar</div>
      <button type="button" class="pg-btn pg-btn--ghost" id="pgBtnPrev">← Anterior</button>
      <button type="button" class="pg-btn pg-btn--soft" id="pgBtnDraft">Guardar borrador</button>
      <span class="pg-save-status" id="pgSaveStatus" aria-live="polite"></span>
      <button type="button" class="pg-btn pg-btn--primary" id="pgBtnNext" style="margin-left:auto">Siguiente →</button>
    </div>
  </form>
</div>

<div class="pg-toast" id="pgToast"></div>


<script>
(function () {
  'use strict';

  var arbolUrl = "<?php echo esc_js($arbol_url); ?>";
  var cnaeUrl  = "<?php echo esc_js($cnae_url); ?>";
  var paisesUrl = "<?php echo esc_js($paises_url); ?>";
  var restCreateUrl = "<?php echo esc_js($rest_create_url); ?>";
  var restDraftUrl  = "<?php echo esc_js($rest_draft_url); ?>";
  var wpNonce = "<?php echo esc_js($wp_nonce); ?>";

  var arbol = [];
  var cnaeRows = [];
  var cnaeFullData = [];
  var nacionalidadesElegidas = [];

  var state = { projectId: null, step: 0, saving: false, firstSaveTriggered: false };
  var form = document.getElementById('pgForm');
  var wizard = document.getElementById('pg-wizard');

  /* ============ TOOLTIPS (click en móvil) ============ */
  document.querySelectorAll('.pg-info').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.stopPropagation();
      var wasOpen = el.classList.contains('is-open');
      document.querySelectorAll('.pg-info.is-open').forEach(function (o) { o.classList.remove('is-open'); });
      if (!wasOpen) el.classList.add('is-open');
    });
  });
  document.addEventListener('click', function () {
    document.querySelectorAll('.pg-info.is-open').forEach(function (o) { o.classList.remove('is-open'); });
  });

  /* ============ TOAST / ESTADO DE GUARDADO ============ */
  var toastEl = document.getElementById('pgToast');
  var toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-visible'); }, 2600);
  }
  var saveStatusEl = document.getElementById('pgSaveStatus');
  function setSaveStatus(text, ok) {
    saveStatusEl.textContent = text;
    saveStatusEl.classList.toggle('is-ok', !!ok);
  }

  /* ============ REST ============ */
  function apiFetch(url, body, keepalive) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      keepalive: !!keepalive,
      headers: { 'Content-Type': 'application/json', 'X-WP-Nonce': wpNonce },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) { var err = new Error(data.message || ('HTTP ' + res.status)); err.status = res.status; throw err; }
        return data;
      });
    });
  }

  /* ============ RECOLECCIÓN DE DATOS ============ */
  function getVal(name) { var el = form.querySelector('[name="' + name + '"]'); return el ? el.value : ''; }
  function getMulti(name) { return Array.prototype.slice.call(form.querySelectorAll('[name="' + name + '"]:checked')).map(function (el) { return el.value; }); }
  function getChecked(name) { var el = form.querySelector('[name="' + name + '"]'); return el ? el.checked : false; }

  function buildPayload(reportTier) {
    return {
      project_id: state.projectId || undefined,
      project_name: getVal('project_name'),
      ultimo_paso: state.step,
      definicion: {
        tipo_estudio: getVal('tipo_estudio') || (form.querySelector('[name="tipo_estudio"]:checked') || {}).value || '',
        actividad_economica: { sector: getVal('sector'), actividad: getVal('actividad'), cnae: getVal('cnae') },
        delimitacion_geografica: { ccaa: getVal('ccaa'), provincia: getVal('provincia'), poblacion: getVal('poblacion') }
      },
      ticket: getMulti('ticket'),
      buyer_persona: {
        edad: getMulti('edad'),
        genero: getVal('genero'),
        estado_civil: getMulti('estado_civil'),
        academia: getVal('academia'),
        nacionalidad: nacionalidadesElegidas.slice(),
        nse: getMulti('nse'),
        renta_anual: getMulti('renta_anual'),
        renta_mensual: getVal('renta_mensual')
      },
      ecosistema: {
        comp_directa: getChecked('comp_directa'),
        comp_indirecta_alta: getVal('comp_indirecta_alta'),
        comp_indirecta_media: getVal('comp_indirecta_media'),
        gen_trafico_alto: getVal('gen_trafico_alto'),
        gen_trafico_medio: getVal('gen_trafico_medio')
      },
      entorno: {
        clima: getMulti('clima'),
        trafico_peaton: getMulti('trafico_peaton'),
        trafico_vehicular: getMulti('trafico_vehicular'),
        comentarios: getVal('comentarios')
      },
      report_tier: reportTier || 'borrador'
    };
  }

  function getTipoEstudio() {
    var el = form.querySelector('[name="tipo_estudio"]:checked');
    return el ? el.value : '';
  }

  /* ============ AUTOGUARDADO ============ */
  function saveDraft(opts) {
    opts = opts || {};
    var name = getVal('project_name').trim();
    if (!name) return Promise.resolve(null);
    if (state.saving) return Promise.resolve(null);
    state.saving = true;
    if (!opts.silent) setSaveStatus('Guardando…', false);

    return apiFetch(restDraftUrl, buildPayload('borrador'), opts.keepalive).then(function (res) {
      state.saving = false;
      if (res && res.project_id) state.projectId = res.project_id;
      var now = new Date();
      setSaveStatus('Borrador guardado ' + now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }), true);
      if (!opts.silent) toast('Borrador guardado');
      return res;
    }).catch(function (err) {
      state.saving = false;
      setSaveStatus('No se pudo guardar (revisa tu conexión)', false);
      console.warn('[PowerGIS] Error guardando borrador:', err);
      return null;
    });
  }

  document.getElementById('f-nombre').addEventListener('blur', function () {
    if (!state.projectId && !state.firstSaveTriggered && this.value.trim()) {
      state.firstSaveTriggered = true;
      saveDraft({ silent: true });
    }
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') saveDraft({ silent: true, keepalive: true });
  });

  /* ============ NAVEGACIÓN ============ */
  var sections = Array.prototype.slice.call(document.querySelectorAll('.pg-section'));
  var steps = Array.prototype.slice.call(document.querySelectorAll('.pg-step'));
  var btnPrev = document.getElementById('pgBtnPrev');
  var btnNext = document.getElementById('pgBtnNext');
  var btnDraft = document.getElementById('pgBtnDraft');

  function renderStep() {
    sections.forEach(function (s) { s.classList.toggle('is-active', +s.dataset.section === state.step); });
    steps.forEach(function (s) {
      var n = +s.dataset.step;
      s.classList.toggle('is-active', n === state.step);
      s.classList.toggle('is-done', n < state.step);
    });
    btnPrev.disabled = state.step === 0;
    btnNext.textContent = state.step === sections.length - 1 ? 'Realizar proyecto →' : 'Siguiente →';
    window.scrollTo({ top: wizard.offsetTop - 10, behavior: 'smooth' });
  }
  function goToStep(n) {
    if (n < 0 || n > sections.length - 1) return;
    state.step = n;
    renderStep();
    saveDraft({ silent: true });
  }
  steps.forEach(function (s) { s.addEventListener('click', function () { goToStep(+s.dataset.step); }); });
  btnPrev.addEventListener('click', function () { goToStep(state.step - 1); });
  btnDraft.addEventListener('click', function () { saveDraft(); });
  btnNext.addEventListener('click', function () {
    var invalid = validateStep(state.step);
    if (invalid) { invalid.scrollIntoView({ behavior: 'smooth', block: 'center' }); showValidationBanner(); return; }
    hideValidationBanner();
    if (state.step < sections.length - 1) goToStep(state.step + 1);
    else handleFinalSubmit();
  });

  /* ============ AVISO DE CAMPOS OBLIGATORIOS ============ */
  var validationBanner = document.getElementById('pgValidationBanner');
  var bannerTimer = null;
  function showValidationBanner() {
    validationBanner.classList.add('is-visible');
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(hideValidationBanner, 4500);
  }
  function hideValidationBanner() {
    validationBanner.classList.remove('is-visible');
    clearTimeout(bannerTimer);
  }
  form.addEventListener('input', hideValidationBanner);
  form.addEventListener('change', hideValidationBanner);

  /* ============ VALIDACIÓN POR PASO (bloquea "Siguiente") ============ */
  // Solo el paso 0 (Definición) tiene campos obligatorios en el negocio actual;
  // Buyer Persona / Ecosistema / Entorno son 100% opcionales. Se deja la
  // estructura por pasos por si en el futuro se añaden obligatorios en otros.
  var REQUIRED = {
    0: [
      { field: 'project_name', check: function () { return getVal('project_name').trim() !== ''; } },
      { field: 'tipo_estudio', check: function () { return getTipoEstudio() !== ''; }, wrapSelector: '[data-group="tipo_estudio"]' },
      { field: 'ccaa', check: function () { var t = getTipoEstudio(); return t === 'nacional' || t === '' || getVal('ccaa') !== ''; } },
      { field: 'provincia', check: function () { var t = getTipoEstudio(); return !(t === 'provincia' || t === 'poblacion') || getVal('provincia') !== ''; } },
      { field: 'poblacion', check: function () { var t = getTipoEstudio(); return t !== 'poblacion' || getVal('poblacion') !== ''; } },
      { field: 'sector', check: function () { return getVal('sector') !== ''; } },
      { field: 'actividad', check: function () { return getVal('actividad') !== ''; } },
      { field: 'ticket', check: function () { return getMulti('ticket').length > 0; }, wrapSelector: '#ticket-grid' }
    ]
  };

  function wrapFor(rule) {
    if (rule.wrapSelector) return document.querySelector(rule.wrapSelector).closest('.pg-field');
    var el = form.querySelector('[name="' + rule.field + '"]');
    return el ? (el.closest('.pg-field') || el.closest('.pg-conditional')) : null;
  }

  function validateStep(stepIndex) {
    var rules = REQUIRED[stepIndex] || [];
    var firstInvalid = null;
    rules.forEach(function (r) {
      var wrap = wrapFor(r);
      var visible = !wrap || wrap.offsetParent !== null;
      var ok = r.check();
      if (wrap) wrap.classList.toggle('has-error', visible && !ok);
      if (!ok && visible && !firstInvalid) firstInvalid = wrap;
    });
    return firstInvalid;
  }
  function validateAll() {
    for (var i = 0; i < sections.length; i++) {
      var invalid = validateStep(i);
      if (invalid) { goToStep(i); invalid.scrollIntoView({ behavior: 'smooth', block: 'center' }); showValidationBanner(); return false; }
    }
    return true;
  }

  /* ============ UBICACIÓN: árbol real (arbol.json) ============ */
  var selCcaa = document.getElementById('f-ccaa');
  var selProvincia = document.getElementById('f-provincia');
  var selPoblacion = document.getElementById('f-poblacion');

  fetch(arbolUrl).then(function (r) { return r.json(); }).then(function (data) {
    arbol = data || [];
    selCcaa.innerHTML = '<option value="">Selecciona...</option>';
    arbol.forEach(function (c) {
      var opt = document.createElement('option'); opt.value = c.label; opt.textContent = c.label;
      selCcaa.appendChild(opt);
    });
  }).catch(function (err) { console.warn('[PowerGIS] No se pudo cargar arbol.json:', err); });

  selCcaa.addEventListener('change', function () {
    var ccaaObj = arbol.filter(function (c) { return c.label === selCcaa.value; })[0];
    selProvincia.innerHTML = '';
    selPoblacion.innerHTML = '<option value="">Elige antes la provincia...</option>';
    selPoblacion.disabled = true;
    if (!ccaaObj || !ccaaObj.provinces || !ccaaObj.provinces.length) {
      selProvincia.disabled = true;
      selProvincia.innerHTML = '<option value="">Sin provincias disponibles</option>';
      return;
    }
    selProvincia.disabled = false;
    var ph = document.createElement('option'); ph.value = ''; ph.textContent = 'Selecciona...';
    selProvincia.appendChild(ph);
    ccaaObj.provinces.forEach(function (p) {
      var opt = document.createElement('option'); opt.value = p.label; opt.textContent = p.label;
      selProvincia.appendChild(opt);
    });
  });

  selProvincia.addEventListener('change', function () {
    var ccaaObj = arbol.filter(function (c) { return c.label === selCcaa.value; })[0];
    var provObj = ccaaObj && ccaaObj.provinces ? ccaaObj.provinces.filter(function (p) { return p.label === selProvincia.value; })[0] : null;
    selPoblacion.innerHTML = '';
    if (!provObj || !provObj.towns || !provObj.towns.length) {
      selPoblacion.disabled = true;
      selPoblacion.innerHTML = '<option value="">Sin poblaciones disponibles</option>';
      return;
    }
    selPoblacion.disabled = false;
    var ph = document.createElement('option'); ph.value = ''; ph.textContent = 'Selecciona...';
    selPoblacion.appendChild(ph);
    provObj.towns.forEach(function (t) {
      var opt = document.createElement('option'); opt.value = t.label; opt.textContent = t.label;
      selPoblacion.appendChild(opt);
    });
  });

  function updateLocationVisibility() {
    var tipo = getTipoEstudio();
    document.getElementById('cond-ccaa').classList.toggle('is-visible', tipo === 'ccaa' || tipo === 'provincia' || tipo === 'poblacion');
    document.getElementById('cond-provincia').classList.toggle('is-visible', tipo === 'provincia' || tipo === 'poblacion');
    document.getElementById('cond-poblacion').classList.toggle('is-visible', tipo === 'poblacion');
  }

  var TIPO_EXPLANATIONS = {
    nacional: 'Compararemos entre sí las Comunidades Autónomas de España, para encontrar las mejores regiones del país para tu negocio.',
    ccaa: 'Compararemos entre sí las provincias dentro de la comunidad autónoma que elijas, para encontrar la mejor provincia.',
    provincia: 'Compararemos entre sí las poblaciones dentro de la provincia que elijas, para encontrar la mejor población.',
    poblacion: 'Compararemos entre sí las zonas y barrios dentro de la población que elijas, para encontrar la ubicación exacta más adecuada.'
  };
  function updateTipoExplainer() {
    var tipo = getTipoEstudio();
    var box = document.getElementById('tipoExplainer');
    var text = document.getElementById('tipoExplainerText');
    if (tipo && TIPO_EXPLANATIONS[tipo]) {
      text.textContent = TIPO_EXPLANATIONS[tipo];
      box.classList.add('is-visible');
    } else {
      box.classList.remove('is-visible');
    }
  }

  form.querySelectorAll('[name="tipo_estudio"]').forEach(function (el) {
    el.addEventListener('change', function () { updateLocationVisibility(); updateTipoExplainer(); });
  });

  /* ============ SECTOR / ACTIVIDAD / CNAE (Estructura_CNAE2025.csv real) ============ */
  var selSector = document.getElementById('f-sector');
  var selActividad = document.getElementById('f-actividad');
  var inputCnae = document.getElementById('f-cnae');
  var fallbackNote = document.getElementById('sector-fallback-note');

  var CNAE_FALLBACK_ROWS = [
    ['SECTOR', 'Hostelería'], ['56.10', 'Cafeterías y salones de té'], ['56.10', 'Restaurantes'], ['56.30', 'Bares y pubs'],
    ['SECTOR', 'Comercio al por menor'], ['47.71', 'Comercio de ropa'], ['47.11', 'Comercio de alimentación'],
    ['SECTOR', 'Salud y estética'], ['86.23', 'Clínicas dentales'], ['96.02', 'Centros de estética'],
    ['SECTOR', 'Servicios profesionales'], ['70.22', 'Consultoría'], ['69.20', 'Asesoría legal/fiscal'],
    ['SECTOR', 'Tecnología'], ['62.01', 'Desarrollo de software'], ['95.11', 'Reparación informática']
  ];

  function parseCnaeRows(text) {
    return text.split(/\r?\n/).filter(Boolean).map(function (line) { return line.split(',').map(function (c) { return c.trim(); }); });
  }

  function loadCnaeIntoForm(rows, isFallback) {
    cnaeRows = rows;
    cnaeFullData = rows.map(function (r) { return r[1] || r[0]; }).filter(Boolean);
    selSector.innerHTML = '<option value="">Selecciona...</option>';
    rows.forEach(function (row, i) {
      if (row[0] && row[0].toUpperCase().indexOf('SECTOR') === 0) {
        var opt = document.createElement('option'); opt.value = i; opt.textContent = row[1] || row[0];
        selSector.appendChild(opt);
      }
    });
    fallbackNote.classList.toggle('is-visible', !!isFallback);
  }

  fetch(cnaeUrl).then(function (r) {
    if (!r.ok) throw new Error('CNAE dataset no disponible en ' + cnaeUrl);
    return r.text();
  }).then(function (text) {
    var rows = parseCnaeRows(text);
    if (!rows.length) throw new Error('CSV de CNAE vacío');
    loadCnaeIntoForm(rows, false);
  }).catch(function (err) {
    console.warn('[PowerGIS] Usando catálogo de sectores de ejemplo:', err.message);
    loadCnaeIntoForm(CNAE_FALLBACK_ROWS, true);
  });

  selSector.addEventListener('change', function () {
    selActividad.innerHTML = '';
    inputCnae.value = '';
    var start = parseInt(selSector.value, 10);
    if (isNaN(start)) { selActividad.disabled = true; selActividad.innerHTML = '<option value="">Elige antes el sector...</option>'; return; }
    selActividad.disabled = false;
    var ph = document.createElement('option'); ph.value = ''; ph.textContent = 'Selecciona...';
    selActividad.appendChild(ph);
    for (var i = start + 1; i < cnaeRows.length; i++) {
      var row = cnaeRows[i];
      if (row[0] && row[0].toUpperCase().indexOf('SECTOR') === 0) break;
      if (row[0] && row[1]) {
        var opt = document.createElement('option'); opt.value = row[1]; opt.dataset.cnae = row[0]; opt.textContent = row[1];
        selActividad.appendChild(opt);
      }
    }
  });
  selActividad.addEventListener('change', function () {
    var opt = selActividad.options[selActividad.selectedIndex];
    inputCnae.value = opt ? (opt.dataset.cnae || '') : '';
  });

  /* ============ AUTOCOMPLETADO (competencia / tráfico) ============ */
  document.querySelectorAll('.cnae-search').forEach(function (input) {
    var box = input.closest('.pg-autocomplete').querySelector('.pg-suggestions');
    input.addEventListener('input', function () {
      var val = this.value.toLowerCase();
      box.innerHTML = '';
      if (val.length < 2) { box.classList.remove('is-visible'); return; }
      var matches = cnaeFullData.filter(function (x) { return x.toLowerCase().indexOf(val) !== -1; }).slice(0, 10);
      matches.forEach(function (item) {
        var d = document.createElement('div');
        d.className = 'pg-suggestion'; d.textContent = item;
        d.addEventListener('click', function () { input.value = item; box.classList.remove('is-visible'); });
        box.appendChild(d);
      });
      box.classList.toggle('is-visible', matches.length > 0);
    });
    input.addEventListener('blur', function () { setTimeout(function () { box.classList.remove('is-visible'); }, 150); });
  });

  /* ============ NACIONALIDAD: selector repetible hasta 5 ============ */
  var selNacPicker = document.getElementById('f-nacionalidad-picker');
  var chipsBox = document.getElementById('nacionalidad-chips');
  var nacNote = document.getElementById('nacionalidad-note');
  var PAISES_FALLBACK = ["España","Marruecos","Rumanía","Colombia","Venezuela","Ecuador","Perú","Argentina","Italia","China","Reino Unido","Francia","Alemania","Portugal","Ucrania","República Dominicana","Cuba","Bolivia","Honduras","Paraguay","Senegal","Nigeria","Pakistán","India","Brasil","México","Estados Unidos","Chile","Uruguay","Polonia","Otro"];

  function renderNacPicker(paises) {
    var disponibles = paises.filter(function (p) { return nacionalidadesElegidas.indexOf(p) === -1; });
    selNacPicker.innerHTML = '<option value="">' + (nacionalidadesElegidas.length ? 'Añadir otra...' : 'Selecciona un país...') + '</option>';
    disponibles.forEach(function (p) {
      var opt = document.createElement('option'); opt.value = p; opt.textContent = p;
      selNacPicker.appendChild(opt);
    });
    var atMax = nacionalidadesElegidas.length >= 5;
    selNacPicker.disabled = atMax;
    nacNote.textContent = atMax ? 'Has alcanzado el máximo de 5 nacionalidades.' : 'Elige hasta 5. Déjalo vacío si es indiferente. (' + nacionalidadesElegidas.length + '/5)';
  }
  function renderChips() {
    chipsBox.innerHTML = '';
    nacionalidadesElegidas.forEach(function (p) {
      var chip = document.createElement('span'); chip.className = 'pg-chip';
      chip.innerHTML = '<span></span><button type="button" aria-label="Quitar ' + p + '">✕</button>';
      chip.querySelector('span').textContent = p;
      chip.querySelector('button').addEventListener('click', function () {
        nacionalidadesElegidas = nacionalidadesElegidas.filter(function (x) { return x !== p; });
        renderChips(); renderNacPicker(window.__pgPaisesCache || PAISES_FALLBACK);
      });
      chipsBox.appendChild(chip);
    });
  }
  selNacPicker.addEventListener('change', function () {
    if (this.value && nacionalidadesElegidas.length < 5) {
      nacionalidadesElegidas.push(this.value);
      renderChips();
      renderNacPicker(window.__pgPaisesCache || PAISES_FALLBACK);
    }
  });

  fetch(paisesUrl).then(function (r) { return r.text(); }).then(function (t) {
    var rows = t.split(/\r?\n/).slice(1);
    var paises = rows.map(function (r) { return (r.split(',')[0] || '').replace(/"/g, '').trim(); }).filter(Boolean);
    if (!paises.length) throw new Error('CSV de países vacío');
    window.__pgPaisesCache = paises;
    renderNacPicker(paises);
  }).catch(function (err) {
    console.warn('[PowerGIS] Usando lista de países de ejemplo:', err.message);
    window.__pgPaisesCache = PAISES_FALLBACK;
    renderNacPicker(PAISES_FALLBACK);
  });

  /* ============ GRUPOS EXCLUSIVOS ("Indiferente") + MÁXIMOS ============ */
  document.querySelectorAll('[data-exclusive]').forEach(function (group) {
    var exclusiveValue = group.dataset.exclusive;
    var max = group.dataset.max ? parseInt(group.dataset.max, 10) : null;
    var warningEl = max ? group.parentElement.querySelector('.pg-max-warning') : null;
    group.addEventListener('change', function (e) {
      if (e.target.type !== 'checkbox') return;
      var boxes = Array.prototype.slice.call(group.querySelectorAll('input[type=checkbox]'));
      if (e.target.value === exclusiveValue && e.target.checked) {
        boxes.forEach(function (b) { if (b !== e.target) b.checked = false; });
      } else if (e.target.checked) {
        boxes.forEach(function (b) { if (b.value === exclusiveValue) b.checked = false; });
      }
      if (max && warningEl) {
        var count = boxes.filter(function (b) { return b.checked && b.value !== exclusiveValue; }).length;
        warningEl.classList.toggle('is-visible', count > max);
      }
    });
  });

  /* Ticket: aviso (no bloqueante) al marcar más de 2 */
  var ticketGrid = document.getElementById('ticket-grid');
  var ticketWarning = document.getElementById('ticket-warning');
  ticketGrid.addEventListener('change', function () {
    var count = form.querySelectorAll('[name="ticket"]:checked').length;
    ticketWarning.classList.toggle('is-visible', count > 2);
  });

  updateLocationVisibility();
  updateTipoExplainer();
  renderStep();

  /* ============ ENVÍO FINAL: crea el proyecto básico directamente ============ */
  // 16 ago 2026: se retiró el popup de elección básico/avanzado. El botón final
  // ahora lanza siempre el proyecto gratuito/básico, exactamente con la misma
  // llamada a /projects/create de siempre. El informe avanzado (de pago) se pide
  // más adelante desde "Mis Proyectos" o desde la propia página del proyecto,
  // ya no forma parte de este formulario.
  function handleFinalSubmit() {
    if (!validateAll()) return;
    btnNext.disabled = true;
    btnNext.textContent = 'Enviando...';
    saveDraft({ silent: true }).then(function () {
      return apiFetch(restCreateUrl, buildPayload('basico'));
    }).then(function () {
      toast('¡Listo! Tu informe se está procesando.');
      setSaveStatus('Proyecto creado', true);
      setTimeout(function () { window.location.href = '/mis-proyectos/'; }, 1200);
    }).catch(function (err) {
      btnNext.disabled = false;
      btnNext.textContent = 'Realizar proyecto →';
      setSaveStatus('No se pudo crear el informe. Tu borrador está a salvo.', false);
      toast('No se pudo crear el informe. Inténtalo de nuevo.');
      console.warn('[PowerGIS] Error creando proyecto:', err);
    });
  }


})();
</script>

    <?php
    return ob_get_clean();
});
