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
 * Animación de la pantalla de carga de «Realizar proyecto».
 *
 * La URL sale, por este orden, de la constante POWERGIS_LOADING_ANIMATION_URL
 * (wp-config.php), de la opción `powergis_loading_animation_url` o del filtro
 * del mismo nombre. Admite Lottie (.json), vídeo (.mp4/.webm) e imagen
 * (.gif/.webp/.svg/.png). Sin URL (lo normal) se usa la animación «Órbita» de
 * Aldo, en línea en la plantilla; la URL sólo sirve para sustituirla.
 */
function saas_pg_loading_animation_markup() {
    $url = defined('POWERGIS_LOADING_ANIMATION_URL') ? (string) POWERGIS_LOADING_ANIMATION_URL
        : (string) get_option('powergis_loading_animation_url', '');
    $url = (string) apply_filters('powergis_loading_animation_url', $url);
    if ($url === '') {
        return '';
    }
    $ext = strtolower(pathinfo((string) wp_parse_url($url, PHP_URL_PATH), PATHINFO_EXTENSION));
    $src = esc_url($url);
    if ($ext === 'json') {
        return '<div class="pg-loading-screen__media" data-pg-anim data-pg-lottie="' . $src . '" aria-hidden="true"></div>'
            . '<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js" defer></script>'
            . '<script>window.addEventListener("load",function(){var n=document.querySelector("[data-pg-lottie]");'
            . 'if(n&&window.lottie){window.lottie.loadAnimation({container:n,renderer:"svg",loop:true,autoplay:true,path:n.getAttribute("data-pg-lottie")});}});</script>';
    }
    if ($ext === 'mp4' || $ext === 'webm') {
        return '<video class="pg-loading-screen__media" data-pg-anim src="' . $src . '" autoplay loop muted playsinline aria-hidden="true"></video>';
    }
    return '<img class="pg-loading-screen__media" data-pg-anim src="' . $src . '" alt="" aria-hidden="true">';
}

/**
 * Shortcode: Crear Proyecto V6 (perfil de cliente y capas territoriales)
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

  /* Chips de selección múltiple */
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
  .pg-actions.is-final { display:block; padding:18px 24px; }
  .pg-actions__nav { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .pg-final-submit { width:100%; justify-content:center; margin-top:12px; padding:16px 22px; font-size:15px; }
  .pg-policy-note { font-size:12px; line-height:1.55; color:var(--pg-ink-soft); text-align:center; margin:10px 0 0; }
  .pg-switch-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:12px 14px; border:1px solid var(--pg-line); border-radius:12px; }
  .pg-switch-row p { margin:3px 0 0; }
  .pg-switch-row input[type=checkbox] { position:absolute; opacity:0; width:1px; height:1px; }
  .pg-switch__track { display:block; width:44px; height:25px; border-radius:99px; background:#c7cbd1; position:relative; transition:background .2s; flex-shrink:0; cursor:pointer; }
  .pg-switch__track:after { content:""; position:absolute; top:3px; left:3px; width:19px; height:19px; border-radius:50%; background:#fff; box-shadow:0 1px 3px #0002; transition:transform .2s; }
  .pg-switch input:checked + .pg-switch__track { background:var(--pg-orange); }
  .pg-switch input:checked + .pg-switch__track:after { transform:translateX(19px); }
  .pg-layer-subsections.is-disabled { opacity:.38; filter:grayscale(1); pointer-events:none; }
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
          <label class="pg-card"><input type="radio" name="tipo_estudio" value="nacional" checked><span class="pg-card__ui"><img src="https://powergis.es/wp-content/uploads/2026/07/spaintrans.png" alt="" loading="lazy">Nacional</span></label>
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
          <p class="pg-hint" id="poblacion-distritos-hint">Compararemos los distritos de la población. Si solo tiene un distrito censal, compararemos sus secciones censales; si tampoco hay secciones, no habrá zonas con las que comparar y el informe lo indicará.</p>
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
          <div class="pg-ticket-grid" id="ticket-grid" data-warn-max="2" data-exclusive="Indiferente">
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Indiferente" checked><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Indiferente</span><br><span class="pg-ticket__range">Cualquier rango de gasto</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Micro"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Micro-gasto</span><br><span class="pg-ticket__range">&lt; 10€ · impulso / recurrente</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Bajo"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Bajo</span><br><span class="pg-ticket__range">10-50€ · consumo diario</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Medio"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Medio</span><br><span class="pg-ticket__range">51-200€ · compra planificada</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Medio-Alto"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Medio-Alto</span><br><span class="pg-ticket__range">201-1.000€ · bienes duraderos</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Alto"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Alto / Premium</span><br><span class="pg-ticket__range">1.001-5.000€ · inversión de estatus</span></span></span></label>
            <label class="pg-ticket"><input type="checkbox" name="ticket" value="Lujo"><span class="pg-ticket__ui"><span><span class="pg-ticket__name">Lujo</span><br><span class="pg-ticket__range">&gt; 5.000€ · alta consideración</span></span></span></label>
          </div>
          <p class="pg-max-warning" id="ticket-warning">Se recomienda marcar 1 o 2 opciones para obtener resultados más precisos.</p>
          <p class="pg-error-msg">Selecciona un rango de ticket o deja «Indiferente».</p>
        </div>
      </div>
    </section>

    <!-- ============ SECCIÓN 2: BUYER PERSONA ============ -->
    <section class="pg-section" data-section="1">
      <h2 class="pg-section__title">Perfil del público objetivo (Buyer Persona)</h2>
      <p class="pg-section__desc">Define el perfil del cliente objetivo. La edad y las dos variables de renta son obligatorias; puedes dejar «Indiferente» si no tienes una preferencia concreta.</p>

      <div class="pg-block">
        <div class="pg-block__title">Atributos demográficos</div>
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">1. Rango de edad prioritario<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Identifica los grupos de edad que concentran la mayor parte de tu demanda potencial.">i</span></label>
          <div class="pg-list" data-group="edad" data-exclusive="Indiferente" aria-required="true">
            <label class="pg-opt"><input type="checkbox" name="edad" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="18-24"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">18 – 24 años</span><span class="pg-info" tabindex="0" data-tip="Jóvenes adultos, estudiantes o primer empleo.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="25-34"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">25 – 34 años</span><span class="pg-info" tabindex="0" data-tip="Profesionales jóvenes, inicio de independencia financiera.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="35-44"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">35 – 44 años</span><span class="pg-info" tabindex="0" data-tip="Consolidación profesional y familiar.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="45-54"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">45 – 54 años</span><span class="pg-info" tabindex="0" data-tip="Mayor poder adquisitivo, hogares maduros.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="55-64"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">55 – 64 años</span><span class="pg-info" tabindex="0" data-tip="Pre-jubilación y enfoque en salud/bienestar.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="edad" value="65+"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">65 años o más</span><span class="pg-info" tabindex="0" data-tip="Jubilados con necesidades específicas de ocio y salud.">i</span></span></label>
          </div>
          <div id="gen-labels" class="pg-hint"></div>
          <p class="pg-error-msg">Selecciona una franja de edad o marca «Indiferente».</p>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-genero">2. Segmentación por género<span class="pg-info" tabindex="0" data-tip="Indica si tu producto se dirige a un sexo específico o si tiene un enfoque neutro/unisex.">i</span></label>
          <select class="pg-select" id="f-genero" name="genero">
            <option value="Indiferente" selected>Indiferente</option>
            <option value="Femenino">Femenino</option>
            <option value="Masculino">Masculino</option>
          </select>
        </div>

        <div class="pg-field">
          <label class="pg-label">3. Estado civil y estructura familiar<span class="pg-info" tabindex="0" data-tip="Define si tu cliente ideal es soltero, casado, o si su decisión de compra depende de su rol familiar. Puedes marcar varias.">i</span></label>
          <div class="pg-list" data-group="estado_civil" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Soltero"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Soltero(a) sin hijos</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Pareja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">En pareja / casado(a) sin hijos</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Pareja con hijos"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Pareja con hijos</span><span class="pg-info" tabindex="0" data-tip="Pareja con hijos menores o adolescentes.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Nido Vacío"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Nido vacío</span><span class="pg-info" tabindex="0" data-tip="Hijos que ya se independizaron.">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="estado_civil" value="Monoparental"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Monoparental</span><span class="pg-info" tabindex="0" data-tip="Padre o madre soltero(a) con hijos.">i</span></span></label>
          </div>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-academia">4. Nivel de formación académica<span class="pg-info" tabindex="0" data-tip="Grado máximo de estudios que suele tener tu cliente.">i</span></label>
          <select class="pg-select" id="f-academia" name="academia">
            <option value="Indiferente" selected>Indiferente</option>
            <option value="Sin estudios o primaria">Sin estudios o primaria</option>
            <option value="Secundaria y FP de grado medio">Secundaria y FP de grado medio</option>
            <option value="Estudios superiores (FP superior y universidad)">Estudios superiores (FP superior y universidad)</option>
          </select>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-peso-extranjera">5. Peso de población extranjera<span class="pg-info" tabindex="0" data-tip="Indica la proporción de población extranjera que te interesa en el área. PowerGIS deberá contrastarla con los datos disponibles para cada zona.">i</span></label>
          <select class="pg-select" id="f-peso-extranjera" name="peso_poblacion_extranjera">
            <option value="Indiferente" selected>Indiferente</option>
            <option value="Baja">Baja</option>
            <option value="Media">Media</option>
            <option value="Alta">Alta</option>
          </select>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Variables de contexto del público objetivo</div>
        <div class="pg-field">
          <div class="pg-switch-row"><div><b>Incluir resultados electorales</b><p class="pg-hint">Añade resultados electorales agregados al análisis territorial, sin inferir la ideología de personas concretas.</p></div><label class="pg-switch"><input type="checkbox" name="datos_votaciones_politicas" checked><span class="pg-switch__track"></span></label></div>
        </div>
        <div class="pg-field">
          <div class="pg-switch-row"><div><b>Incluir traslados entre provincias</b><p class="pg-hint">Considera los movimientos entre provincias como contexto de movilidad y demanda.</p></div><label class="pg-switch"><input type="checkbox" name="datos_traslados_entre_provincias" checked><span class="pg-switch__track"></span></label></div>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Capacidad económica del público objetivo</div>
        <div class="pg-field">
          <label class="pg-label">6. Renta bruta anual por hogar<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Estima el ingreso total acumulado por la unidad familiar del cliente objetivo.">i</span></label>
          <div class="pg-list" data-group="renta_anual" data-exclusive="Indiferente" aria-required="true">
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Subsistencia"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Subsistencia</span><span class="pg-info" tabindex="0" data-tip="< 12.000 €/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Baja-Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase baja-media</span><span class="pg-info" tabindex="0" data-tip="12.000€ a 24.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase media</span><span class="pg-info" tabindex="0" data-tip="24.001€ a 45.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Media-Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase media-alta</span><span class="pg-info" tabindex="0" data-tip="45.001€ a 75.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Clase alta</span><span class="pg-info" tabindex="0" data-tip="75.001€ a 150.000€/año">i</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="renta_anual" value="HNWI"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alto patrimonio (HNWI)</span><span class="pg-info" tabindex="0" data-tip="> 150.000 €/año">i</span></span></label>
          </div>
          <p class="pg-error-msg">Selecciona una franja de renta anual o marca «Indiferente».</p>
        </div>

        <div class="pg-field">
          <label class="pg-label" for="f-renta-mensual">7. Renta mensual disponible (ahorro)<span class="req">*</span><span class="pg-info" tabindex="0" data-tip="Dinero que queda al hogar después de cubrir sus gastos básicos. Es una aproximación a su capacidad de ahorro y gasto discrecional.">i</span></label>
          <select class="pg-select" id="f-renta-mensual" name="renta_mensual" aria-required="true">
            <option value="Indiferente" selected>Indiferente</option>
            <option value="Renta Crítica">Renta crítica — menos de 300 €/mes disponibles (ahorro bajo o nulo)</option>
            <option value="Renta Ajustada">Renta ajustada — 301–800 €/mes disponibles (ahorro limitado; sensible al precio)</option>
            <option value="Renta Holgada">Renta holgada — 801–2.500 €/mes disponibles (capacidad de ahorro y ocio)</option>
            <option value="Renta Discrecional">Renta discrecional — más de 2.500 €/mes disponibles (mayor ahorro, inversión y consumo premium)</option>
          </select>
          <p class="pg-error-msg">Selecciona una opción de renta mensual disponible o marca «Indiferente».</p>
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
          <label class="pg-switch"><input type="checkbox" name="comp_directa" checked><span class="pg-switch__track"></span></label>
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
          <label class="pg-opt"><input type="checkbox" name="clima" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
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
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Muy Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Muy alta (Premium)</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Media</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_peaton" value="Baja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Baja</span></span></label>
          </div>
        </div>
        <div class="pg-field" style="margin-top:0">
          <label class="pg-label">Tráfico vehicular<span class="pg-info" tabindex="0" data-tip="Flujo de coches y transporte en la zona.">i</span></label>
          <div class="pg-list" data-group="trafico_vehicular" data-exclusive="Indiferente">
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Indiferente" checked><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Indiferente</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Muy Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Muy alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Alta"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Alta</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Media"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Media</span></span></label>
            <label class="pg-opt"><input type="checkbox" name="trafico_vehicular" value="Baja"><span class="pg-opt__ui"><span class="pg-opt__dot"></span><span class="pg-opt__text">Baja</span></span></label>
          </div>
        </div>
      </div>

      <div class="pg-block">
        <div class="pg-block__title">Capas territoriales complementarias</div>
        <p class="pg-block__desc">Activa las fuentes que quieres incorporar al informe. Las capas inmobiliarias se activan o desactivan todas juntas.</p>
        <div class="pg-field">
          <div class="pg-switch-row"><div><b>Incluir nivel turístico</b><p class="pg-hint">Añade el contexto turístico al informe cuando esté activado.</p></div><label class="pg-switch"><input type="checkbox" name="datos_nivel_turistico" checked><span class="pg-switch__track"></span></label></div>
        </div>
        <div class="pg-field">
          <div class="pg-switch-row"><div><b>Incluir mercado inmobiliario y parque residencial</b><p class="pg-hint">Activa conjuntamente todas las subsecciones inmobiliarias. No se pueden configurar de forma individual.</p></div><label class="pg-switch"><input type="checkbox" id="f-datos-inmobiliario" name="datos_mercado_inmobiliario" checked><span class="pg-switch__track"></span></label></div>
        </div>
        <div id="pgLayerSubsections" class="pg-layer-subsections">
          <div class="pg-row2">
            <div class="pg-field"><label class="pg-label" for="f-datos-compraventa">Compra-venta de inmuebles</label><select class="pg-select" id="f-datos-compraventa" name="datos_compra_venta_inmuebles" disabled><option value="incluir" selected>Incluida</option><option value="excluir">Excluida</option></select></div>
            <div class="pg-field"><label class="pg-label" for="f-datos-viviendas">Viviendas vacías y principales</label><select class="pg-select" id="f-datos-viviendas" name="datos_viviendas_vacias_principales" disabled><option value="incluir" selected>Incluida</option><option value="excluir">Excluida</option></select></div>
            <div class="pg-field"><label class="pg-label" for="f-datos-precio-vivienda">Precio de vivienda e histórico</label><select class="pg-select" id="f-datos-precio-vivienda" name="datos_precio_vivienda_historico" disabled><option value="incluir" selected>Incluida</option><option value="excluir">Excluida</option></select></div>
            <div class="pg-field"><label class="pg-label" for="f-datos-catastro">Catastro (locales y cartografía)</label><select class="pg-select" id="f-datos-catastro" name="datos_catastro_locales_cartografia" disabled><option value="incluir" selected>Incluida</option><option value="excluir">Excluida</option></select></div>
            <div class="pg-field"><label class="pg-label" for="f-datos-alquiler">Alquiler de vivienda (proxy/estimación)</label><select class="pg-select" id="f-datos-alquiler" name="datos_alquiler_vivienda_proxy" disabled><option value="incluir" selected>Incluida</option><option value="excluir">Excluida</option></select></div>
          </div>
        </div>
      </div>
    </section>

    <div class="pg-actions">
      <div class="pg-validation-banner" id="pgValidationBanner">Datos obligatorios sin rellenar</div>
      <div class="pg-actions__nav" id="pgActionNav">
        <button type="button" class="pg-btn pg-btn--ghost" id="pgBtnPrev">← Anterior</button>
        <button type="button" class="pg-btn pg-btn--soft" id="pgBtnDraft">Guardar borrador</button>
        <span class="pg-save-status" id="pgSaveStatus" aria-live="polite"></span>
      </div>
      <button type="button" class="pg-btn pg-btn--primary" id="pgBtnNext">Siguiente →</button>
      <p class="pg-policy-note" id="pgPolicyNote" hidden>Al realizar el proyecto, confirmas que estás de acuerdo con nuestra <a href="https://powergis.es/privacy-policy/" target="_blank" rel="noopener noreferrer">política de tratamiento de datos</a>. Una vez enviado, no podrás deshacer la creación desde este formulario.</p>
    </div>
  </form>
</div>

<div class="pg-toast" id="pgToast"></div>

<!--
  Pantalla de carga tras «Realizar proyecto». Se queda hasta que el motor
  termina y entonces abre el proyecto recién creado.

  La animación definitiva se enlaza SIN tocar este fichero: define en
  wp-config.php `define('POWERGIS_LOADING_ANIMATION_URL', 'https://…/carga.json');`
  (o la opción / el filtro `powergis_loading_animation_url`). Lottie .json,
  .mp4/.webm o .gif/.webp/.svg/.png. Sin URL se usa la animación «Órbita» de
  Aldo (abajo, SVG en línea animado por JS; el SVG en reposo es el logo final,
  que es lo que se ve sin JS o con «reducir movimiento»).
-->
<div class="pg-loading-screen" id="pgLoadingScreen" role="status" aria-live="polite" hidden>
  <div class="pg-loading-screen__anim" data-pg-anim-slot>
    <?php $pg_anim = saas_pg_loading_animation_markup(); ?>
    <?php if ($pg_anim !== ''): ?>
      <?php echo $pg_anim; // phpcs:ignore WordPress.Security.EscapeOutput -- URL escapada en el helper ?>
    <?php else: ?>
    <svg class="pg-loader" data-pg-anim data-pg-loader viewBox="132 503 1600 800" aria-hidden="true" focusable="false">
      <g data-pg-part="cam">
        <path data-pg-part="P" fill="#0B0B0C" d="M183.4 797V682.9H215Q226.1 682.9 234 687.5Q241.9 692.1 246.2 700.6Q250.4 709.2 250.4 721.3Q250.4 733.3 246.2 741.9Q241.9 750.5 234 755.1Q226.1 759.7 215 759.7H186.9L189.8 755.8V797ZM189.8 756.2 186.9 752.2H215Q229.1 752.2 236.5 744.1Q243.9 736 243.9 721.3Q243.9 706.5 236.5 698.4Q229.1 690.3 215 690.3H186.9L189.8 686.4Z"/>
        <path data-pg-part="O" fill="#0B0B0C" d="M346 797.8Q335 797.8 325.6 793.5Q316.2 789.1 309.3 781.3Q302.4 773.4 298.5 762.9Q294.7 752.4 294.7 740Q294.7 727.5 298.5 717Q302.4 706.5 309.3 698.6Q316.3 690.8 325.6 686.4Q335 682.1 346 682.1Q357 682.1 366.4 686.4Q375.7 690.7 382.6 698.6Q389.6 706.4 393.4 716.9Q397.3 727.5 397.3 740Q397.3 752.4 393.4 763Q389.6 773.5 382.6 781.3Q375.7 789.2 366.4 793.5Q357 797.8 346 797.8ZM346 790.2Q355.4 790.2 363.4 786.5Q371.4 782.7 377.4 775.9Q383.4 769 386.7 759.9Q390 750.8 390 739.9Q390 729.1 386.7 720Q383.4 710.9 377.4 704.1Q371.5 697.2 363.4 693.5Q355.4 689.7 346 689.7Q336.6 689.7 328.6 693.5Q320.5 697.2 314.6 704.1Q308.6 710.9 305.3 720Q302 729.1 302 739.9Q302 750.8 305.3 759.9Q308.6 769 314.5 775.9Q320.5 782.7 328.6 786.5Q336.6 790.2 346 790.2Z"/>
        <path data-pg-part="W" fill="#0B0B0C" d="M473.7 797 437.2 682.9H445.5L480.3 791.9H476.1L512 682.9H519.5L555.1 791.9H551.1L586.1 682.9H593.9L557.3 797H549.1L514.6 691.6H516.6L482 797Z"/>
        <path data-pg-part="E" fill="#0B0B0C" d="M650.1 797V682.9H708.2V690.3H656.5V789.6H710V797ZM655.7 742.7V735.4H702.7V742.7Z"/>
        <path data-pg-part="R" fill="#0B0B0C" d="M769.9 797V682.9H800.6Q816.7 682.9 825.9 693Q835.1 703.2 835.1 721.3Q835.1 733.3 830.9 741.9Q826.8 750.4 819.1 755Q811.4 759.6 800.6 759.6H773.4L776.2 755.8V797ZM829.3 797 807.1 755.6H814.2L836.4 797ZM776.2 756.2 773.4 752.3H800.6Q814.4 752.3 821.5 744.1Q828.7 736 828.7 721.3Q828.7 706.5 821.5 698.4Q814.4 690.3 800.6 690.3H773.4L776.2 686.4Z"/>
        <path data-pg-part="G" fill="#0B0B0C" d="M171 845 A337 337 0 1 0 839 845 L468 845 L468 975 L684 975 A198 198 0 0 1 312 845 Z"/>
        <rect data-pg-part="stem" fill="#0B0B0C" x="947" y="845" width="132" height="382"/>
        <path data-pg-part="Sb" fill="#0B0B0C" d="M1599.7 722.4 A310 310 0 0 1 1174.3 1173.6 L1261.5 1081.2 A183 183 0 0 0 1512.5 814.8 Z"/>
        <path data-pg-part="St" fill="#0B0B0C" d="M1684.7 632.4 A310 310 0 0 0 1259.3 1083.6 L1346.5 991.2 A183 183 0 0 1 1597.5 724.8 Z"/>
        <circle data-pg-part="halo" cx="1009" cy="740" r="66" fill="none" stroke="#FF7417" stroke-width="6" opacity="0"/>
        <circle data-pg-part="dot" cx="1009" cy="740" r="66" fill="#FF7417"/>
      </g>
    </svg>
    <?php endif; ?>
  </div>
  <p class="pg-loading-screen__text" id="pgLoadingText">Preparando tu análisis…</p>
  <div class="pg-loading-screen__error" id="pgLoadingError" hidden>
    <p>No hemos podido terminar el informe. Tu proyecto está guardado.</p>
    <a class="pg-btn pg-btn--primary" id="pgLoadingErrorLink" href="/mis-proyectos/">Ver el proyecto</a>
  </div>
</div>
<style>
  .pg-loading-screen {
    position: fixed; inset: 0; z-index: 100000;    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 22px; padding: 24px; text-align: center;
    background: #FAFAF8; color: #0B0B0C; font-family: 'Montserrat', 'Roboto', sans-serif;
  }
  .pg-loading-screen[hidden] { display: none; }
  .pg-loading-screen__anim { display: flex; flex-direction: column; align-items: center; gap: 22px; }
  .pg-loading-screen__media { width: min(320px, 70vw); height: auto; aspect-ratio: auto; }
  div.pg-loading-screen__media { height: min(320px, 70vw); }
  /* Selectores con #id: el tema no puede pisar tamaño ni recorte del SVG. */
  #pgLoadingScreen .pg-loader {
    display: block; width: min(560px, 86vw); max-width: none; height: auto;
    aspect-ratio: 2 / 1; overflow: visible; margin: 0; padding: 0; border: 0; background: none;
  }
  #pgLoadingScreen .pg-loader[hidden] { display: none; }
  .pg-loading-screen__text {
    margin: 0; min-height: 1.6em; font-size: clamp(17px, 1.6vw, 24px); font-weight: 400;
    letter-spacing: .04em; color: #0B0B0C;
  }
  .pg-loading-screen__text.is-new { animation: pg-loading-in .5s cubic-bezier(.2,.8,.2,1) both; }
  .pg-loading-screen__error p { margin: 0 0 14px; }
  .pg-loading-screen__error .pg-btn {
    display: inline-flex; font-weight: 600; font-size: 13.5px; border-radius: 999px;
    padding: 12px 22px; text-decoration: none; background: #0B0B0C; color: #fff;   /* blanco sobre naranja no llega a 4,5:1 */
  }
  @keyframes pg-loading-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) { .pg-loading-screen__text.is-new { animation: none; } }
</style>


<script>
(function () {
  'use strict';

  var arbolUrl = "<?php echo esc_js($arbol_url); ?>";
  var cnaeUrl  = "<?php echo esc_js($cnae_url); ?>";
  var restCreateUrl = "<?php echo esc_js($rest_create_url); ?>";
  var restDraftUrl  = "<?php echo esc_js($rest_draft_url); ?>";
  var wpNonce = "<?php echo esc_js($wp_nonce); ?>";
  var restStatusBase = "<?php echo esc_js(rest_url('saas/v1/projects/')); ?>";

  var arbol = [];
  var cnaeRows = [];
  var cnaeFullData = [];

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
        // Son radios: getVal() leería el primero («nacional») aunque no esté marcado.
        tipo_estudio: getTipoEstudio(),
        actividad_economica: { sector: getVal('sector'), actividad: getVal('actividad'), cnae: getVal('cnae') },
        delimitacion_geografica: { ccaa: getVal('ccaa'), provincia: getVal('provincia'), poblacion: getVal('poblacion') }
      },
      ticket: getMulti('ticket'),
      buyer_persona: {
        edad: getMulti('edad'),
        genero: getVal('genero'),
        estado_civil: getMulti('estado_civil'),
        academia: getVal('academia'),
        nacionalidad: [],
        peso_poblacion_extranjera: getVal('peso_poblacion_extranjera'),
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
      },
      datos_territoriales: {
        votaciones_politicas: getChecked('datos_votaciones_politicas') ? 'incluir' : 'excluir',
        compra_venta_inmuebles: getChecked('datos_mercado_inmobiliario') ? 'incluir' : 'excluir',
        viviendas_vacias_principales: getChecked('datos_mercado_inmobiliario') ? 'incluir' : 'excluir',
        nivel_turistico: getChecked('datos_nivel_turistico') ? 'incluir' : 'excluir',
        precio_vivienda_historico: getChecked('datos_mercado_inmobiliario') ? 'incluir' : 'excluir',
        traslados_entre_provincias: getChecked('datos_traslados_entre_provincias') ? 'incluir' : 'excluir',
        catastro_locales_cartografia: getChecked('datos_mercado_inmobiliario') ? 'incluir' : 'excluir',
        alquiler_vivienda_proxy: getChecked('datos_mercado_inmobiliario') ? 'incluir' : 'excluir'
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
    var isFinalStep = state.step === sections.length - 1;
    btnNext.textContent = isFinalStep ? 'Realizar proyecto →' : 'Siguiente →';
    var actions = btnNext.closest('.pg-actions');
    actions.classList.toggle('is-final', isFinalStep);
    document.getElementById('pgPolicyNote').hidden = !isFinalStep;
    btnNext.classList.toggle('pg-final-submit', isFinalStep);
    document.getElementById('pgActionNav').style.display = isFinalStep ? 'none' : 'flex';
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
  // Obligatorios de definición y perfil del cliente objetivo.
  // Edad y ambas variables de renta aceptan «Indiferente» como respuesta explícita,
  // pero no permiten que el usuario deje los controles sin selección.
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
    ],
    1: [
      { field: 'edad', check: function () { return getMulti('edad').length > 0; }, wrapSelector: '[data-group="edad"]' },
      { field: 'renta_anual', check: function () { return getMulti('renta_anual').length > 0; }, wrapSelector: '[data-group="renta_anual"]' },
      { field: 'renta_mensual', check: function () { return getVal('renta_mensual') !== ''; } }
    ]
  };

  function wrapFor(rule) {
    if (rule.wrapSelector) return document.querySelector(rule.wrapSelector).closest('.pg-field');
    var el = form.querySelector('[name="' + rule.field + '"]');
    return el ? (el.closest('.pg-field') || el.closest('.pg-conditional')) : null;
  }

  function validateStep(stepIndex, includeHidden) {
    var rules = REQUIRED[stepIndex] || [];
    var firstInvalid = null;
    rules.forEach(function (r) {
      var wrap = wrapFor(r);
      var visible = !!includeHidden || !wrap || wrap.offsetParent !== null;
      var ok = r.check();
      if (wrap) wrap.classList.toggle('has-error', visible && !ok);
      if (!ok && visible && !firstInvalid) firstInvalid = wrap;
    });
    return firstInvalid;
  }
  function validateAll() {
    for (var i = 0; i < sections.length; i++) {
      var invalid = validateStep(i, true);
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
    poblacion: 'Compararemos entre sí las zonas y barrios dentro de la población que elijas, para encontrar la ubicación exacta más adecuada. Si la población tiene un solo distrito censal, la comparación se hace por secciones censales.'
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

  var inmobiliarioToggle = form.querySelector('[name="datos_mercado_inmobiliario"]');
  var inmobiliarioSubsections = document.getElementById('pgLayerSubsections');
  function syncInmobiliario() {
    var enabled = inmobiliarioToggle.checked;
    inmobiliarioSubsections.classList.toggle('is-disabled', !enabled);
    // Los cinco desplegables sólo enseñan lo que hace el interruptor: siguen
    // deshabilitados, pero dicen «Excluida» cuando está apagado.
    inmobiliarioSubsections.querySelectorAll('select').forEach(function (el) {
      el.disabled = true;
      el.value = enabled ? 'incluir' : 'excluir';
    });
  }
  inmobiliarioToggle.addEventListener('change', syncInmobiliario);
  syncInmobiliario();

  updateLocationVisibility();
  updateTipoExplainer();
  renderStep();

  /* ============ PANTALLA DE CARGA → PROYECTO ============ */
  // Tras crear el proyecto se muestra la pantalla de carga y se consulta el
  // estado hasta que el motor termina. Sólo entonces se abre el proyecto: hasta
  // `done` el post sigue en borrador y su enlace no se puede ver todavía.
  var LOADING_PHRASES = [
    'Preparando tu análisis…',
    'Reuniendo datos oficiales de la zona…',
    'Calculando indicadores demográficos…',
    'Comparando territorios…',
    'Redactando las conclusiones…'
  ];
  var READY_STATUSES = ['done', 'partial', 'narrative_ready'];
  var POLL_EVERY_MS = 3000;
  var POLL_MAX_MS = 5 * 60 * 1000;   // pasado esto se abre igualmente: la página del proyecto se actualiza sola

  /*
   * Animación «Órbita» de Aldo (Claude Design, PieceC de pg-loaders.jsx),
   * pasada a JS sin dependencias. Ciclo de 5 s: Giro 1,6 · Despliegue 1,0 ·
   * Logo 1,4 · Repliegue 1,0. Las S giran como spinner con el punto en órbita,
   * se despliegan en el logo y se repliegan. Devuelve la función que la para.
   */
  function startLoaderAnimation(svg) {
    if (!svg || !window.requestAnimationFrame) return function () {};
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return function () {};
    var GIRO = 0, DESP = 1.6, LOGO = 2.6, REPL = 4.0, TOTAL = 5.0;
    var CENTER = [932, 903];
    var PIV = { P: [213, 740], O: [346, 740], W: [515, 740], E: [676, 740], R: [799, 740],
      G: [505, 890], dot: [1009, 740], St: [1472, 858], Sb: [1387, 948], stem: [1013, 1227], cam: CENTER };
    var LETTERS = ['P', 'O', 'W', 'E', 'R'];
    var el = {};
    Array.prototype.forEach.call(svg.querySelectorAll('[data-pg-part]'), function (n) { el[n.getAttribute('data-pg-part')] = n; });
    var clamp = function (v) { return Math.max(0, Math.min(1, v)); };
    var prog = function (T, a, b) { return clamp((T - a) / (b - a)); };
    var lerp = function (a, b, k) { return a + (b - a) * k; };
    var outQuad = function (t) { return t * (2 - t); };
    var outCubic = function (t) { return (--t) * t * t + 1; };
    var inCubic = function (t) { return t * t * t; };
    var inOutCubic = function (t) { return t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1; };
    var outBack = function (t) { return 1 + 2.70158 * Math.pow(t - 1, 3) + 1.70158 * Math.pow(t - 1, 2); };
    var enter = function (T, a, b) { return outCubic(prog(T, a, b)); };
    var exit = function (T, a, b) { return inCubic(prog(T, a, b)); };
    var pop = function (T, a, b) { return outBack(prog(T, a, b)); };
    var glide = function (T, a, b) { return inOutCubic(prog(T, a, b)); };
    function set(id, q) {
      var c = PIV[id], sx = q.sx != null ? q.sx : (q.s != null ? q.s : 1), sy = q.sy != null ? q.sy : (q.s != null ? q.s : 1);
      el[id].setAttribute('transform', 'translate(' + (c[0] + (q.dx || 0)) + ' ' + (c[1] + (q.dy || 0)) + ') rotate(' + (q.r || 0)
        + ') scale(' + sx + ' ' + sy + ') translate(' + (-c[0]) + ' ' + (-c[1]) + ')');
      el[id].setAttribute('opacity', q.o != null ? q.o : 1);
    }
    function frame(T) {
      var theta;
      if (T < DESP) theta = 540 * prog(T, GIRO, DESP);
      else if (T < LOGO) theta = 540 + 180 * outQuad(prog(T, DESP, LOGO));
      else if (T < REPL) theta = 0;
      else theta = 180 * Math.pow(prog(T, REPL, TOTAL), 2);
      var k = T < LOGO ? glide(T, DESP, DESP + 0.95) : 1 - glide(T, REPL + 0.05, TOTAL);
      var rad = theta * Math.PI / 180, cos = Math.cos(rad), sin = Math.sin(rad);
      [['St', -1], ['Sb', 1]].forEach(function (h) {
        var x = h[1] * 0.728 * 26, y = h[1] * 0.686 * 26, c = PIV[h[0]];
        set(h[0], { dx: lerp(CENTER[0] + x * cos - y * sin - c[0], 0, k), dy: lerp(CENTER[1] + x * sin + y * cos - c[1], 0, k), r: theta, s: lerp(0.42, 1, k) });
      });
      var phi = (2 * theta - 90) * Math.PI / 180;
      var kd = T < LOGO ? glide(T, DESP + 0.12, DESP + 0.9) : 1 - glide(T, REPL, REPL + 0.8);
      var ddx = lerp(CENTER[0] + 250 * Math.cos(phi) - 1009, 0, kd), ddy = lerp(CENTER[1] + 250 * Math.sin(phi) - 740, 0, kd);
      set('dot', { dx: ddx, dy: ddy, s: lerp(0.5, 1, kd) });
      set('stem', { sy: Math.max(0, T < LOGO ? pop(T, DESP + 0.4, DESP + 0.95) : 1 - exit(T, REPL, REPL + 0.45)) });
      var kg = T < LOGO ? enter(T, DESP + 0.3, DESP + 1.0) : 1 - exit(T, REPL, REPL + 0.5);
      set('G', { r: -150 * (1 - kg), o: kg, s: lerp(0.85, 1, kg) });
      LETTERS.forEach(function (id, i) {
        var kl = T < LOGO ? enter(T, DESP + 0.45 + i * 0.06, DESP + 0.9 + i * 0.06) : 1 - exit(T, REPL + i * 0.03, REPL + 0.32 + i * 0.03);
        set(id, { dy: 34 * (1 - kl), o: kl });
      });
      var h = prog(T, LOGO + 0.1, LOGO + 1.2);
      el.halo.setAttribute('cx', 1009 + ddx);
      el.halo.setAttribute('cy', 740 + ddy);
      el.halo.setAttribute('r', 66 + 110 * outCubic(h));
      el.halo.setAttribute('opacity', h > 0 && h < 1 ? 0.5 * (1 - h) : 0);
      set('cam', { s: lerp(1, 1.02, prog(T, DESP, REPL)) });
    }
    var t0 = null, raf = 0;
    (function loop(now) {
      if (t0 === null) t0 = now;
      frame(((now - t0) / 1000) % TOTAL);
      raf = window.requestAnimationFrame(loop);
    })(window.performance ? performance.now() : Date.now());
    return function () { window.cancelAnimationFrame(raf); };
  }

  function showLoadingScreen() {
    var screen = document.getElementById('pgLoadingScreen');
    var text = document.getElementById('pgLoadingText');
    // Al <body> para que ningún contenedor del tema con transform/overflow
    // recorte el position:fixed.
    document.body.appendChild(screen);
    screen.hidden = false;
    document.documentElement.style.overflow = 'hidden';
    var stopAnim = startLoaderAnimation(screen.querySelector('[data-pg-loader]'));
    var i = 0;
    var timer = setInterval(function () {
      i = (i + 1) % LOADING_PHRASES.length;
      text.textContent = LOADING_PHRASES[i];
      text.classList.remove('is-new');
      void text.offsetWidth;   // reinicia la animación de entrada de la frase
      text.classList.add('is-new');
    }, 3500);
    return {
      hide: function () {
        clearInterval(timer);
        stopAnim();
        screen.hidden = true;
        document.documentElement.style.overflow = '';
      },
      fail: function (href) {
        clearInterval(timer);
        stopAnim();
        text.hidden = true;
        var anim = screen.querySelector('[data-pg-anim]');
        // setAttribute: en un <svg> la propiedad .hidden no existe.
        if (anim) anim.setAttribute('hidden', '');
        document.getElementById('pgLoadingErrorLink').href = href;
        document.getElementById('pgLoadingError').hidden = false;
      }
    };
  }

  function getStatus(postId) {
    return fetch(restStatusBase + postId + '/status', {
      credentials: 'same-origin',
      headers: { 'X-WP-Nonce': wpNonce }
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }

  function waitForProject(postId, fallbackHref) {
    var started = Date.now();
    return new Promise(function (resolve, reject) {
      (function tick() {
        getStatus(postId).then(function (st) {
          var href = st.permalink || fallbackHref;
          if (READY_STATUSES.indexOf(st.status) !== -1) return resolve(href);
          if (st.status === 'failed') { var err = new Error('failed'); err.href = href; return reject(err); }
          if (Date.now() - started > POLL_MAX_MS) return resolve(href);
          setTimeout(tick, POLL_EVERY_MS);
        }).catch(function () {
          // Un fallo de red puntual no corta la espera.
          if (Date.now() - started > POLL_MAX_MS) return resolve(fallbackHref);
          setTimeout(tick, POLL_EVERY_MS);
        });
      })();
    });
  }

  /* ============ ENVÍO FINAL: crea el proyecto básico directamente ============ */
  // 16 ago 2026: se retiró el popup de elección básico/avanzado. El botón final
  // ahora lanza siempre el proyecto gratuito/básico, exactamente con la misma
  // llamada a /projects/create de siempre. El informe avanzado (de pago) se pide
  // más adelante desde "Mis Proyectos" o desde la propia página del proyecto,
  // ya no forma parte de este formulario.
  function handleFinalSubmit() {
    if (!validateAll()) return;
    if (!window.confirm('¿Confirmas que deseas realizar el proyecto? Una vez enviado, no podrás deshacer esta acción desde el formulario.')) return;
    btnNext.disabled = true;
    btnNext.textContent = 'Enviando...';
    var loading = showLoadingScreen();
    saveDraft({ silent: true }).then(function () {
      return apiFetch(restCreateUrl, buildPayload('basico'));
    }).then(function (res) {
      var postId = res && (res.post_id || res.project_id);
      // Sin id (ruta antigua del tema) no se puede seguir el proyecto.
      if (!postId) { window.location.href = '/mis-proyectos/'; return; }
      var href = res.permalink || '/mis-proyectos/';
      return waitForProject(postId, href).then(function (url) {
        window.location.href = url;
      }, function (err) {
        loading.fail(err.href || href);
      });
    }).catch(function (err) {
      loading.hide();
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
