<?php
/**
 * Banco de pruebas del formulario, sin navegador.
 *
 *   docker compose -f docker-compose.dev.yml --profile setup run --rm wpcli \
 *       wp eval-file /scripts/probar-formulario.php --allow-root
 *
 * Mete el payload real de `[crear_proyecto_v6]` por el mismo camino que
 * recorrería desde el navegador y va contando qué pasa en cada tramo. Sirve
 * para separar los tres fallos que desde el navegador parecen el mismo
 * («no se crea el proyecto»):
 *
 *   · el mapeo del formulario está mal;
 *   · la ubicación no se resuelve a código INE;
 *   · el motor no responde o rechaza el cuerpo.
 *
 * No necesita nonce ni sesión de navegador: cambia el usuario actual con
 * wp_set_current_user(), que es lo que haría WordPress tras el login.
 *
 * @package PowerGIS
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$payload_path = __DIR__ . '/payload-formulario.json';

if ( ! file_exists( $payload_path ) ) {
	WP_CLI::error( "No encuentro $payload_path" );
}

$payload = json_decode( (string) file_get_contents( $payload_path ), true );
unset( $payload['_comentario'] );

function pg_paso( string $texto ): void {
	WP_CLI::log( "\n" . str_repeat( '─', 62 ) . "\n  $texto\n" . str_repeat( '─', 62 ) );
}

function pg_ok( string $texto ): void {
	WP_CLI::log( '  ✓ ' . $texto );
}

function pg_ko( string $texto ): void {
	WP_CLI::log( '  ✗ ' . $texto );
}

// -------------------------------------------------------------------------
pg_paso( '1 · ¿Está el plugin cargado?' );

foreach ( array( 'PowerGIS\\Form_Mapper', 'PowerGIS\\Geo_Resolver', 'PowerGIS\\REST_Projects', 'PowerGIS\\Engine_Client' ) as $class ) {
	class_exists( $class ) ? pg_ok( $class ) : pg_ko( "$class NO existe — ¿está activo powergis-connector?" );
}

foreach ( array( 'POWERGIS_ENGINE_URL', 'POWERGIS_HMAC_SECRET' ) as $constant ) {
	defined( $constant )
		? pg_ok( "$constant definida" )
		: pg_ko( "$constant NO definida en wp-config.php" );
}

if ( defined( 'POWERGIS_DEV_MODE' ) && POWERGIS_DEV_MODE ) {
	pg_ok( 'POWERGIS_DEV_MODE activo (simulador de pago disponible)' );
}

// -------------------------------------------------------------------------
pg_paso( '2 · ¿Contesta el motor?' );

$client = new PowerGIS\Engine_Client();

if ( ! $client->is_configured() ) {
	WP_CLI::error( 'El cliente del motor no está configurado. Revisa POWERGIS_ENGINE_URL.' );
}

$ping = wp_remote_get( rtrim( POWERGIS_ENGINE_URL, '/' ) . '/health', array( 'timeout' => 8 ) );

if ( is_wp_error( $ping ) ) {
	pg_ko( 'El motor no responde: ' . $ping->get_error_message() );
	WP_CLI::error( 'Sin motor no tiene sentido seguir. Arráncalo y repite.' );
}

pg_ok( 'GET /health → ' . wp_remote_retrieve_response_code( $ping ) );

// -------------------------------------------------------------------------
pg_paso( '3 · ¿Se resuelve la ubicación a código INE?' );

// Éste es el tramo que nadie ve fallar: el formulario manda «Madrid», no «28».
$resolver = new PowerGIS\Geo_Resolver();
$def      = $payload['definicion'] ?? array();
$loc      = $def['delimitacion_geografica'] ?? array();
$nivel    = PowerGIS\Form_Mapper::scope_level( $def['tipo_estudio'] ?? '' );

$nombres = array(
	'ccaa'      => (string) ( $loc['ccaa'] ?? '' ),
	'provincia' => (string) ( $loc['provincia'] ?? '' ),
	'municipio' => (string) ( $loc['poblacion'] ?? '' ),
);

WP_CLI::log( '  tipo_estudio «' . ( $def['tipo_estudio'] ?? '' ) . "» → nivel «$nivel»" );
WP_CLI::log( '  nombres: ' . wp_json_encode( $nombres, JSON_UNESCAPED_UNICODE ) );

$codigo = $resolver->resolve( $nivel, $nombres );

if ( null === $codigo || '' === $codigo ) {
	pg_ko( 'NO se pudo resolver el código INE.' );
	WP_CLI::log( '    Causas habituales:' );
	WP_CLI::log( '      · dim_geo vacío → ejecuta «make almacen» en el motor' );
	WP_CLI::log( '      · el municipio no está cargado → «powergis load-municipios»' );
	WP_CLI::log( '      · el nombre del árbol no coincide con el del INE' );
} else {
	pg_ok( "código INE: $codigo" );
}

// -------------------------------------------------------------------------
pg_paso( '4 · ¿Qué sale del mapeo?' );

$mapped = PowerGIS\Form_Mapper::to_engine_payload( $payload, $resolver->as_callable() );

WP_CLI::log( '  scope    : ' . wp_json_encode( $mapped['scope'], JSON_UNESCAPED_UNICODE ) );
WP_CLI::log( '  segments : ' . wp_json_encode( $mapped['segments'], JSON_UNESCAPED_UNICODE ) );
WP_CLI::log( '  business : ' . wp_json_encode( $mapped['business'], JSON_UNESCAPED_UNICODE ) );
WP_CLI::log( '  target   : ' . count( $mapped['target'] ) . ' campos declarados' );

foreach ( $mapped['target'] as $campo => $valor ) {
	WP_CLI::log( sprintf( '     %-26s %s', $campo, wp_json_encode( $valor, JSON_UNESCAPED_UNICODE ) ) );
}

if ( count( $mapped['target'] ) < 5 ) {
	pg_ko( 'Muy pocos campos en target: el Match % saldrá pobre. ¿Se marcó todo «Indiferente»?' );
} else {
	pg_ok( 'El perfil objetivo viaja completo' );
}

// -------------------------------------------------------------------------
pg_paso( '5 · Crear el proyecto de verdad, como usuario «cliente»' );

$user = get_user_by( 'login', 'cliente' );

if ( ! $user ) {
	WP_CLI::error( 'No existe el usuario «cliente». Lanza antes el setup de WordPress.' );
}

wp_set_current_user( $user->ID );
pg_ok( 'sesión como ' . $user->user_login . ' (ID ' . $user->ID . ')' );

$request = new WP_REST_Request( 'POST', '/saas/v1/projects/create' );
$request->set_header( 'content-type', 'application/json' );
$request->set_body( (string) wp_json_encode( $payload ) );

$response = rest_do_request( $request );

if ( $response->is_error() ) {
	$error = $response->as_error();
	pg_ko( 'La creación falló: [' . $error->get_error_code() . '] ' . $error->get_error_message() );
	WP_CLI::error( 'Se corta aquí. El mensaje de arriba dice exactamente qué tramo falló.' );
}

$data       = $response->get_data();
$project_id = (int) ( $data['post_id'] ?? $data['project_id'] ?? 0 );

pg_ok( 'proyecto creado · ' . wp_json_encode( $data, JSON_UNESCAPED_UNICODE ) );

if ( ! $project_id ) {
	WP_CLI::error( 'La respuesta no trae el ID del proyecto.' );
}

// -------------------------------------------------------------------------
pg_paso( '6 · Esperar al callback del motor' );

WP_CLI::log( '  El motor calcula en segundo plano y avisa por callback firmado.' );

$estado = '';

for ( $i = 0; $i < 30; $i++ ) {
	sleep( 2 );
	$estado = (string) get_post_meta( $project_id, '_pg_report_status', true );
	WP_CLI::log( sprintf( '  %2ds · estado: %s', ( $i + 1 ) * 2, $estado ?: '(vacío)' ) );

	if ( in_array( $estado, array( 'ready', 'done', 'limited', 'error' ), true ) ) {
		break;
	}
}

if ( 'error' === $estado ) {
	pg_ko( 'El motor devolvió error: ' . get_post_meta( $project_id, '_pg_last_error', true ) );
	WP_CLI::error( 'Mira los logs del worker: docker compose -f docker-compose.dev.yml logs worker' );
}

if ( ! in_array( $estado, array( 'ready', 'done', 'limited' ), true ) ) {
	pg_ko( 'El callback no llegó en 60 s.' );
	WP_CLI::log( '    Casi siempre es la URL de callback: el motor tiene que poder' );
	WP_CLI::log( '    alcanzar WordPress por su nombre de red, no por localhost.' );
	WP_CLI::log( '    Revisa POWERGIS_CALLBACK_URL en wp-config.php.' );
	WP_CLI::error( 'Se corta aquí.' );
}

pg_ok( "informe listo · estado «$estado»" );

// -------------------------------------------------------------------------
pg_paso( '7 · ¿El informe básico respeta el muro de pago?' );

$version = (int) get_post_meta( $project_id, '_pg_report_version', true );
$uuid    = (string) get_post_meta( $project_id, '_pg_project_uuid', true );

WP_CLI::log( "  versión $version · uuid $uuid" );

$informe = $client->get_report( $uuid, $user->ID );

if ( is_wp_error( $informe ) ) {
	pg_ko( 'No se pudo leer el informe: ' . $informe->get_error_message() );
	WP_CLI::error( 'Se corta aquí.' );
}

$abiertas = array();
$cerradas = array();

foreach ( (array) ( $informe['sections'] ?? array() ) as $seccion ) {
	if ( ! empty( $seccion['available'] ) ) {
		$abiertas[] = $seccion['id'];
	} else {
		$cerradas[] = $seccion['id'] . ' (' . count( $seccion['preview'] ?? array() ) . ' etiquetas)';
	}
}

WP_CLI::log( '  abiertas : ' . implode( ', ', $abiertas ) );
WP_CLI::log( '  cerradas : ' . implode( ', ', $cerradas ) );

$crudo = (string) wp_json_encode( $informe );

// La regla del negocio: lo que no se ha pagado NO viaja al navegador.
foreach ( array( 'eco.income.household.mean', 'cmp.count', 'placerank' ) as $prohibido ) {
	if ( 'placerank' === $prohibido ) {
		empty( $informe['placerank'] )
			? pg_ok( 'PlaceRank ausente en el básico' )
			: pg_ko( 'PlaceRank viaja en el informe básico — FUGA' );
		continue;
	}
	str_contains( $crudo, $prohibido )
		? pg_ko( "«$prohibido» viaja en el informe básico — FUGA" )
		: pg_ok( "«$prohibido» ausente, como debe" );
}

WP_CLI::log( "\n" . str_repeat( '═', 62 ) );
WP_CLI::success( "Circuito completo. Proyecto #$project_id listo para probar el pago." );
WP_CLI::log( '  Siguiente: entra en http://localhost:8080/mis-proyectos/ como cliente/cliente' );
WP_CLI::log( '  y usa el simulador de pago para ver la subida a avanzado.' );
