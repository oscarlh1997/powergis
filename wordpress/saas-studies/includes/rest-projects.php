<?php
if (!defined('ABSPATH')) exit;

/**
 * GUARDIA AÑADIDO PARA LA PRUEBA CONJUNTA
 * ---------------------------------------
 * Este fichero y el plugin `powergis-connector` registran LAS MISMAS rutas:
 * saas/v1/projects/create, /save-draft y /callback. WordPress no avisa: apila
 * los dos manejadores y despacha el primero que coincida en método, así que
 * gana el que cargue antes — un accidente, no una decisión.
 *
 * Con el conector activo, él se encarga de hablar con el motor: trae
 * `Form_Mapper` (traduce el payload del formulario al contrato del motor) y
 * `Geo_Resolver` (convierte «Comunidad de Madrid» en el código INE 13, que es
 * el TODO que quedó anotado más abajo).
 *
 * Lo demás de este plugin —el shortcode, el CPT, las taxonomías, los roles—
 * sigue funcionando igual. Sólo se apartan las rutas REST.
 *
 * Para volver atrás: desactiva el conector y esto se reactiva solo.
 */
if (class_exists('\\PowerGIS\\REST_Projects')) {
    return;
}


/**
 * rest-projects.php — revisado 23 ago 2026 junto con cpt-project.php, a
 * partir de los dos hallazgos críticos del documento del compañero de
 * backend (20 ago 2026) y de los pendientes ya anotados en sesiones
 * anteriores. Resumen de lo que cambia en este archivo:
 *
 *   1. projects/callback ya NO confía en un campo "signature" dentro del
 *      JSON ni en un secreto con valor por defecto escrito en el código.
 *      Verifica HMAC-SHA256 real sobre cabeceras X-PG-Timestamp /
 *      X-PG-Signature, con ventana anti-repetición de 300s y comparación
 *      en tiempo constante (hash_equals), tal como especifica el
 *      documento de integración. El secreto vive en wp-config.php
 *      (POWERGIS_HMAC_SECRET), nunca en la base de datos.
 *
 *      ⚠️ AVISO IMPORTANTE: el secreto que había por defecto en el código
 *      ('guachineatata2026kimbapaquesuene') hay que darlo por comprometido
 *      y rotarlo cuanto antes — ha estado en texto plano en el repositorio.
 *
 *   2. saas_rest_create_project() y saas_rest_save_draft() ya NO publican
 *      el proyecto de inmediato (post_status => 'publish'). Antes, un
 *      borrador autoguardado o un proyecto recién creado se publicaba en
 *      el acto — con el CPT público (Hallazgo crítico 2) eso exponía los
 *      datos de negocio de cualquier cliente a cualquiera con la URL.
 *      Ahora quedan en 'draft' y solo pasan a 'publish' cuando el motor
 *      confirma por callback que hay un informe real que mostrar.
 *
 *   3. saas_rest_save_draft() ahora hace upsert real: si el body trae
 *      project_id, comprueba propiedad y actualiza ese post en vez de
 *      crear uno nuevo en cada autoguardado.
 *
 *   4. La asignación de la taxonomía "sector" ahora usa "actividad" como
 *      término hijo cuando el formulario lo manda (pendiente anotado el
 *      16 ago), en vez de asignar siempre el sector plano. Se añade un
 *      helper saas_get_or_create_term_id() reutilizado también en
 *      "location", que además corrige un bug: los proyectos a nivel
 *      Provincia o Comunidad Autónoma (sin "poblacion") se quedaban sin
 *      NINGÚN término de location asignado.
 *
 *   5. La llamada al backend ya no apunta al placeholder de desarrollo
 *      localhost:8000/api/profiles/auto. Llama a
 *      {POWERGIS_ENGINE_URL}/v1/reports firmada con HMAC + Idempotency-Key,
 *      tal como describe el contrato del compañero.
 *      ⚠️ TODO: el mapeo de buyer_persona/ecosistema/entorno de
 *      saas_send_project_to_engine() es un primer borrador — los nombres
 *      de campo reales que envía [crear_proyecto_v6] no están confirmados
 *      en este archivo. Revisar antes de dar por cerrado el envío.
 *
 *   6. Se corrige un bug de orden de ejecución: antes se metía
 *      $project_id en user_projects ANTES de comprobar is_wp_error(), así
 *      que un fallo de wp_insert_post podía guardar un objeto WP_Error
 *      dentro del meta user_projects del usuario.
 *
 *   7. Las rutas /projects/create y /projects/save-draft declaran ahora
 *      "args" para validar/sanitizar project_name (y project_id en
 *      save-draft), en línea con el Hallazgo 3 del documento del
 *      compañero (ninguna ruta declaraba esquema).
 *
 * Pendiente, fuera del alcance de este archivo por ahora (no tocado hoy):
 * GET /projects/{id}/status, GET /projects/{id}/report,
 * POST /projects/create-checkout, POST /projects/{id}/placerank,
 * GET /projects/{id}/export/{kind}, y el cron que recupera proyectos
 * colgados en queued/running más de 2h. Todo eso vive en el frente de
 * "Mis Proyectos", que aún no se ha empezado.
 */


/**
 * REGISTRO DE RUTAS REST
 */
add_action('rest_api_init', function () {

    register_rest_route('saas/v1', '/projects/create', [
        'methods'             => 'POST',
        'callback'            => 'saas_rest_create_project',
        'permission_callback' => function () {
            return is_user_logged_in();
        },
        'args' => [
            'project_name' => [
                'required'          => true,
                'type'              => 'string',
                'sanitize_callback' => 'sanitize_text_field',
            ],
        ],
    ]);

    register_rest_route('saas/v1', '/projects/save-draft', [
        'methods'             => 'POST',
        'callback'            => 'saas_rest_save_draft',
        'permission_callback' => function () {
            return is_user_logged_in();
        },
        'args' => [
            'project_name' => [
                'required'          => true,
                'type'              => 'string',
                'sanitize_callback' => 'sanitize_text_field',
            ],
            'project_id' => [
                'required' => false,
                'type'     => 'integer',
            ],
        ],
    ]);

    // Callback del motor. Sin nonce ni sesión de WP: la autenticación es
    // HMAC sobre cabeceras, verificada en saas_verify_engine_signature().
    // Por eso NO es __return_true, aunque no haya sesión de por medio.
    register_rest_route('saas/v1', '/projects/callback', [
        'methods'             => 'POST',
        'callback'            => 'saas_rest_project_callback',
        'permission_callback' => 'saas_verify_engine_signature',
    ]);
});


/**
 * Verifica la firma HMAC del motor sobre timestamp + cuerpo crudo.
 * Se usa como permission_callback de /projects/callback.
 */
function saas_verify_engine_signature(WP_REST_Request $request) {

    $timestamp = $request->get_header('x-pg-timestamp');
    $signature = $request->get_header('x-pg-signature');
    $raw_body  = $request->get_body();

    if (empty($timestamp) || empty($signature)) {
        return new WP_Error('missing_signature', 'Falta cabecera de firma', ['status' => 401]);
    }

    if (abs(time() - intval($timestamp)) > 300) {
        return new WP_Error('stale_request', 'Petición fuera de ventana', ['status' => 401]);
    }

    $secret = defined('POWERGIS_HMAC_SECRET') ? POWERGIS_HMAC_SECRET : '';

    if (empty($secret)) {
        error_log('saas_verify_engine_signature: POWERGIS_HMAC_SECRET no está definido en wp-config.php');
        return new WP_Error('server_misconfigured', 'Servidor mal configurado', ['status' => 500]);
    }

    $expected = hash_hmac('sha256', $timestamp . "\n" . $raw_body, $secret);

    if (!hash_equals($expected, (string) $signature)) {
        return new WP_Error('invalid_signature', 'Firma inválida', ['status' => 401]);
    }

    return true;
}


/**
 * Devuelve el term_id de $name en $taxonomy (bajo $parent si se indica),
 * creándolo si no existe. Tolera la condición de carrera de
 * wp_insert_term (dos peticiones casi simultáneas creando el mismo
 * término, p.ej. dos personas creando a la vez el primer proyecto de
 * "Cataluña").
 */
function saas_get_or_create_term_id($name, $taxonomy, $parent = 0) {

    $name = sanitize_text_field($name);

    if ($name === '') {
        return 0;
    }

    $existing = term_exists($name, $taxonomy, $parent ?: null);

    if ($existing && !is_wp_error($existing)) {
        return intval($existing['term_id']);
    }

    $inserted = wp_insert_term($name, $taxonomy, ['parent' => $parent]);

    if (is_wp_error($inserted)) {
        if ($inserted->get_error_code() === 'term_exists') {
            return intval($inserted->get_error_data());
        }
        error_log('saas_get_or_create_term_id error: ' . $inserted->get_error_message());
        return 0;
    }

    return intval($inserted['term_id']);
}


/**
 * Asigna taxonomías (sector/actividad, project_type, location) a partir
 * de $data['definicion']. Separada en su propia función por si
 * save-draft necesita reflejar taxonomías provisionales más adelante.
 */
function saas_assign_project_taxonomies($project_id, array $def) {

    /* Tipo de estudio (nacional / comunidad_autonoma / provincia / poblacion) */
    if (!empty($def['tipo_estudio'])) {
        wp_set_object_terms($project_id, sanitize_text_field($def['tipo_estudio']), 'project_type', false);
    }

    /* Sector económico, jerárquico: sector > actividad */
    if (!empty($def['actividad_economica']['sector'])) {

        $sector_id   = saas_get_or_create_term_id($def['actividad_economica']['sector'], 'sector', 0);
        $assigned_id = $sector_id;

        if ($sector_id && !empty($def['actividad_economica']['actividad'])) {
            $actividad_id = saas_get_or_create_term_id($def['actividad_economica']['actividad'], 'sector', $sector_id);
            if ($actividad_id) {
                $assigned_id = $actividad_id;
            }
        }

        if ($assigned_id) {
            // Se asigna el término más específico (actividad si existe).
            // Las consultas por el sector padre siguen incluyendo a los
            // hijos por defecto (WP_Tax_Query::include_children => true).
            wp_set_object_terms($project_id, $assigned_id, 'sector', false);
        }

        if (!empty($def['actividad_economica']['cnae'])) {
            update_post_meta($project_id, 'cnae', sanitize_text_field($def['actividad_economica']['cnae']));
        }
    }

    /* Ubicación jerárquica: ccaa > provincia > poblacion */
    if (!empty($def['delimitacion_geografica'])) {

        $loc = $def['delimitacion_geografica'];
        $parent_id = 0;

        if (!empty($loc['ccaa'])) {
            $parent_id = saas_get_or_create_term_id($loc['ccaa'], 'location', 0);
        }

        if (!empty($loc['provincia'])) {
            $provincia_id = saas_get_or_create_term_id($loc['provincia'], 'location', $parent_id);
            if ($provincia_id) {
                $parent_id = $provincia_id;
            }
        }

        if (!empty($loc['poblacion'])) {
            $city_id = saas_get_or_create_term_id($loc['poblacion'], 'location', $parent_id);
            if ($city_id) {
                wp_set_object_terms($project_id, $city_id, 'location', false);
            }
        } elseif ($parent_id) {
            // Estudio a nivel provincia o CCAA (sin población): antes se
            // quedaba sin ningún término de location. Se asigna el
            // término más específico disponible.
            wp_set_object_terms($project_id, $parent_id, 'location', false);
        }
    }
}


/**
 * Firma y envía la creación del informe al motor (POST /v1/reports).
 * No lanza excepción si falla: deja el proyecto en 'queued_retry' para
 * que se reintente más tarde (sondeo o cron), en vez de romper la
 * respuesta al usuario porque el motor esté caído.
 *
 * ⚠️ TODO: el mapeo de scope/segments/business/target de aquí abajo es
 * un primer borrador según el contrato del compañero (§5 del doc). Los
 * nombres de campo reales que envía [crear_proyecto_v6] en
 * buyer_persona/ecosistema/entorno no están confirmados en este
 * archivo — revisar antes de dar esta función por cerrada.
 */
function saas_send_project_to_engine($project_id, $user_id, $project_uuid, array $data, $tier = 'basico') {

    $engine_url = defined('POWERGIS_ENGINE_URL') ? POWERGIS_ENGINE_URL : '';
    $secret     = defined('POWERGIS_HMAC_SECRET') ? POWERGIS_HMAC_SECRET : '';

    if (empty($engine_url) || empty($secret)) {
        error_log('saas_send_project_to_engine: POWERGIS_ENGINE_URL o POWERGIS_HMAC_SECRET no definidos en wp-config.php');
        return false;
    }

    $def = $data['definicion']    ?? [];
    $bp  = $data['buyer_persona'] ?? [];
    $eco = $data['ecosistema']    ?? [];
    $ent = $data['entorno']       ?? [];
    $loc = $def['delimitacion_geografica'] ?? [];

    $body = [
        'project_uuid' => $project_uuid,
        'wp_user_id'   => $user_id,
        'wp_post_id'   => $project_id,
        'tier'         => $tier,
        'scope' => [
            'level'    => $def['tipo_estudio'] ?? null,
            'ine_code' => $loc['ine_code'] ?? null, // TODO: confirmar que el árbol de ubicación manda código INE, no solo el nombre
        ],
        'segments' => [
            'age' => $bp['edad']   ?? [],
            'sex' => $bp['genero'] ?? null,
        ],
        'business' => [
            'sector'     => $def['actividad_economica']['sector'] ?? null,
            'avg_ticket' => $def['ticket'] ?? null,
        ],
        'target' => [
            'family_status'            => $bp['estado_civil_y_estructura_familiar'] ?? null,
            'education_level'          => $bp['nivel_de_formacion_academica_br']    ?? null,
            'nse'                      => $bp['nse']                                ?? [],
            'annual_income'            => $bp['renta_anual']                        ?? null,
            'monthly_available_income' => $bp['renta_mensual']                      ?? null,
            'climate'                  => $ent['clima']                            ?? [],
            'pedestrian_traffic'       => $ent['Trafico_peaton']                    ?? null,
            'vehicular_traffic'        => $ent['Trafico_vehicular']                 ?? null,
            'direct_competition'       => $eco['competencia_directa']               ?? null,
        ],
        'callback_url' => rest_url('saas/v1/projects/callback'),
    ];

    $raw_body  = wp_json_encode($body);
    $timestamp = (string) time();
    $signature = hash_hmac('sha256', $timestamp . "\n" . $raw_body, $secret);

    $response = wp_remote_post(rtrim($engine_url, '/') . '/v1/reports', [
        'headers' => [
            'Content-Type'    => 'application/json',
            'X-PG-Timestamp'  => $timestamp,
            'X-PG-Signature'  => $signature,
            'Idempotency-Key' => $project_uuid,
        ],
        'body'    => $raw_body,
        'timeout' => 10,
    ]);

    if (is_wp_error($response)) {
        error_log('saas_send_project_to_engine: ' . $response->get_error_message());
        return false;
    }

    $code = wp_remote_retrieve_response_code($response);

    if ($code >= 300) {
        error_log('saas_send_project_to_engine: el motor respondió ' . $code . ' — ' . wp_remote_retrieve_body($response));
        return false;
    }

    return true;
}


/**
 * GUARDAR PROYECTO COMO BORRADOR (upsert)
 */
function saas_rest_save_draft(WP_REST_Request $request) {

    $user_id = get_current_user_id();
    $data    = $request->get_json_params();

    if (empty($data['project_name'])) {
        return new WP_Error('missing_name', 'Falta el nombre del proyecto', ['status' => 400]);
    }

    $project_id = !empty($data['project_id']) ? intval($data['project_id']) : 0;

    if ($project_id) {

        $existing = get_post($project_id);

        if (
            !$existing ||
            $existing->post_type !== 'project' ||
            intval($existing->post_author) !== $user_id
        ) {
            return new WP_Error('not_owner', 'El proyecto no existe o no te pertenece', ['status' => 403]);
        }

        wp_update_post([
            'ID'         => $project_id,
            'post_title' => sanitize_text_field($data['project_name']),
        ]);

    } else {

        $project_id = wp_insert_post([
            'post_type'   => 'project',
            'post_title'  => sanitize_text_field($data['project_name']),
            'post_author' => $user_id,
            'post_status' => 'draft',
        ]);

        if (is_wp_error($project_id)) {
            return new WP_Error('insert_error', 'No se pudo crear el proyecto', ['status' => 500]);
        }
    }

    update_post_meta($project_id, 'project_status', 'draft');
    update_post_meta($project_id, 'input_data', wp_json_encode($data));

    return rest_ensure_response([
        'success'    => true,
        'project_id' => $project_id,
    ]);
}


/**
 * CREAR PROYECTO Y EJECUTAR ESTUDIO
 */
function saas_rest_create_project(WP_REST_Request $request) {

    $user_id = get_current_user_id();

    if (!saas_can_create_project($user_id)) {
        return new WP_Error(
            'limit_reached',
            'Has alcanzado el límite de proyectos. Actualiza a premium.',
            ['status' => 403]
        );
    }

    $data = $request->get_json_params();

    if (empty($data['project_name'])) {
        return new WP_Error('missing_name', 'Falta el nombre del proyecto', ['status' => 400]);
    }

    $project_id = wp_insert_post([
        'post_type'   => 'project',
        'post_title'  => sanitize_text_field($data['project_name']),
        'post_author' => $user_id,
        // No se publica aquí. Con el CPT público de antes, publicar de
        // inmediato exponía los datos de negocio del cliente a
        // cualquiera (Hallazgo crítico 2). Pasa a 'publish' solo en el
        // callback del motor, cuando ya hay un informe real.
        'post_status' => 'draft',
    ]);

    if (is_wp_error($project_id)) {
        return new WP_Error('insert_error', 'No se pudo crear el proyecto', ['status' => 500]);
    }

    $user_projects = get_user_meta($user_id, 'user_projects', true);

    if (!is_array($user_projects)) {
        $user_projects = [];
    }

    $user_projects[] = $project_id;
    update_user_meta($user_id, 'user_projects', $user_projects);

    $project_uuid = wp_generate_uuid4();

    update_post_meta($project_id, 'project_uuid', $project_uuid);
    update_post_meta($project_id, 'input_data', wp_json_encode($data));
    update_post_meta($project_id, 'project_status', 'processing');
    update_post_meta($project_id, 'edit_count', 0);
    update_post_meta($project_id, 'max_edits', saas_user_is_premium($user_id) ? 999 : 1);

    if (!empty($data['definicion'])) {
        saas_assign_project_taxonomies($project_id, $data['definicion']);
    }

    $sent = saas_send_project_to_engine($project_id, $user_id, $project_uuid, $data, 'basico');

    if (!$sent) {
        update_post_meta($project_id, 'project_status', 'queued_retry');
    }

    return rest_ensure_response([
        'project_id' => $project_id,
        'status'     => get_post_meta($project_id, 'project_status', true),
    ]);
}


/**
 * CALLBACK DEL MOTOR — publica el proyecto cuando hay informe real.
 * La firma ya se comprobó en saas_verify_engine_signature() (permission_callback).
 */
function saas_rest_project_callback(WP_REST_Request $request) {

    $raw_body = $request->get_body();
    $payload  = json_decode($raw_body, true);

    if (!is_array($payload) || empty($payload['project_id'])) {
        return new WP_Error('invalid_payload', 'Payload inválido', ['status' => 422]);
    }

    $project_id = intval($payload['project_id']);

    if (get_post_type($project_id) !== 'project') {
        return new WP_Error('not_found', 'Proyecto no encontrado', ['status' => 404]);
    }

    update_post_meta($project_id, 'preview_results', wp_json_encode($payload['preview'] ?? []));
    update_post_meta($project_id, 'full_results', wp_json_encode($payload['full'] ?? []));
    update_post_meta($project_id, 'project_status', sanitize_text_field($payload['status'] ?? 'limited'));

    if (!empty($payload['tier'])) {
        wp_set_object_terms($project_id, sanitize_text_field($payload['tier']), 'report_tier', false);
    }

    if (!empty($payload['pdf_url'])) {
        update_post_meta($project_id, 'pdf_url', esc_url_raw($payload['pdf_url']));
    }

    if (!empty($payload['excel_url'])) {
        update_post_meta($project_id, 'excel_url', esc_url_raw($payload['excel_url']));
    }

    // Solo aquí se publica: el motor acaba de confirmar que hay datos
    // reales que mostrar.
    wp_update_post([
        'ID'          => $project_id,
        'post_status' => 'publish',
    ]);

    if (function_exists('litespeed_purge_post')) {
        litespeed_purge_post($project_id);
    }

    return rest_ensure_response(['success' => true]);
}
