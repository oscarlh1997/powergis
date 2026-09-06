<?php
if (!defined('ABSPATH')) exit;

/**
 * Revisado 23 ago 2026 junto con rest-projects.php, a partir de los dos
 * hallazgos críticos del documento del compañero de backend (20 ago 2026):
 *
 *   HALLAZGO CRÍTICO 2 — el CPT era público: GET /wp-json/wp/v2/project
 *   devolvía los proyectos de TODOS los usuarios a cualquiera, sin sesión.
 *   'public' pasa a false, y se listan explícitos los flags que antes
 *   heredaba de 'public' => true, para que quede documentado que el
 *   cambio es intencional:
 *     - publicly_queryable => false: ya no hay vista pública en
 *       /proyectos/{slug}/. Esto NO afecta a la página de ejemplo
 *       (/ejemplo-estudio/, ID 2293 en el inventario del compañero):
 *       esa es una página normal de WP, no una vista de este CPT.
 *     - show_in_rest => false: cierra del todo la ruta nativa
 *       wp/v2/project. Todo el acceso —lectura y escritura— pasa por el
 *       controlador propio saas/v1/* (rest-projects.php), que sí
 *       comprueba propiedad del proyecto.
 *   show_ui se mantiene en true para que el equipo core siga viendo
 *   "Proyectos" en el escritorio de wp-admin (soporte/depuración).
 *
 *   HALLAZGO CRÍTICO 1 — el dato del informe vivía en HTML de Elementor:
 *   se quita 'editor' de 'supports'. El contenido del informe vive en
 *   post meta (input_data / preview_results / full_results, JSON que
 *   viene del motor), nunca en post_content. Dejar el editor de bloques
 *   activo invitaba a maquetar el informe a mano, que es la causa raíz
 *   de que los ~25 proyectos legacy no tuvieran ningún dato estructurado
 *   (ya eliminados el 23 ago 2026).
 *
 * Lo que NO cambia respecto a la revisión del 16 ago: las capacidades de
 * "project" para administrator se siguen concediendo en roles.php
 * (saas_grant_admin_project_capabilities) — sin eso, ni un administrador
 * vería este CPT en el escritorio.
 */
function saas_register_project_cpt() {

    // El conector registra este mismo CPT con `register_post_type`, que
    // sobrescribe en silencio: gana el que corra más tarde en `init`. Con el
    // conector activo, manda él y este registro se aparta.
    if (class_exists('\\PowerGIS\\CPT')) {
        return;
    }


    register_post_type('project', [
        'labels' => [
            'name' => 'Proyectos',
            'singular_name' => 'Proyecto'
        ],

        // Ver Hallazgo crítico 2 en el comentario de arriba.
        'public'              => false,
        'publicly_queryable'  => false,
        'exclude_from_search' => true,
        'show_in_nav_menus'   => false,

        'show_ui' => true,
        'show_in_rest' => false,
        'menu_icon' => 'dashicons-chart-area',

        // Se quita 'editor' (ver Hallazgo crítico 1 arriba). Se mantiene
        // 'custom-fields' para poder inspeccionar el meta a mano en
        // wp-admin cuando haga falta depurar.
        'supports' => ['title', 'author', 'custom-fields', 'revisions'],

        // Sin publicly_queryable no hay vista pública que enrutar.
        'has_archive' => false,
        'rewrite' => false,

        // Las 4 taxonomías del proyecto (sector jerárquica con actividad
        // como hijo, y report_tier). El registro real de cada una sigue
        // viviendo en taxonomies.php.
        'taxonomies' => ['sector', 'project_type', 'location', 'report_tier'],

        'capability_type' => 'project',
        'map_meta_cap' => true,
    ]);
}
add_action('init', 'saas_register_project_cpt', 0);
