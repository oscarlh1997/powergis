<?php
/**
 * CPT `project` y sus taxonomías.
 *
 * Cambio importante respecto a lo que hay hoy en powergis.es: el CPT pasa a
 * ser NO público. Con `public => true`, `/wp-json/wp/v2/project` lista los
 * proyectos de todos los usuarios a cualquiera que pida la URL, y un
 * `project_uuid` filtrado abre un informe de pago.
 *
 * Aquí se registra con `show_in_rest` pero con un controlador que filtra por
 * autor, y el contenido del informe NO vive en `post_content`: vive en el
 * motor y se pide por `project_uuid`.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class CPT {

	public const POST_TYPE = 'project';

	public const TAX_SECTOR = 'sector';
	public const TAX_TYPE   = 'project_type';
	public const TAX_LOC    = 'location';
	public const TAX_TIER   = 'report_tier';

	public const META_UUID     = '_pg_project_uuid';
	public const META_VERSION  = '_pg_report_version';
	public const META_STATUS   = '_pg_report_status';
	public const META_SCOPE    = '_pg_scope';
	public const META_SEGMENTS = '_pg_segments';
	public const META_BUSINESS = '_pg_business';
	public const META_TARGET   = '_pg_target';
	public const META_RAW      = '_pg_form_raw';
	public const META_ERROR    = '_pg_last_error';
	public const META_UPDATED  = '_pg_updated_at';

	public static function hooks(): void {
		add_action( 'init', array( self::class, 'register' ) );
		add_action( 'init', array( self::class, 'register_meta' ) );
		add_filter( 'rest_project_query', array( self::class, 'restrict_rest_query' ), 10, 2 );
		add_filter( 'rest_prepare_project', array( self::class, 'strip_private_meta' ), 10, 3 );
	}

	public static function register(): void {
		register_post_type(
			self::POST_TYPE,
			array(
				'labels'              => array(
					'name'          => __( 'Proyectos', 'powergis' ),
					'singular_name' => __( 'Proyecto', 'powergis' ),
				),
				'public'              => false,   // ← era true: cerraba la fuga
				'publicly_queryable'  => true,    // la página del informe sí se sirve
				'exclude_from_search' => true,
				'show_ui'             => true,
				'show_in_menu'        => true,
				'show_in_nav_menus'   => false,
				'show_in_rest'        => true,
				'rest_base'           => 'project',
				'menu_icon'           => 'dashicons-chart-area',
				'supports'            => array( 'title', 'author', 'custom-fields' ),
				'has_archive'         => false,
				'rewrite'             => array( 'slug' => 'proyectos', 'with_front' => false ),  // el que ya usa powergis.es
				'capability_type'     => 'post',
				'map_meta_cap'        => true,
			)
		);

		$shared = array(
			'public'            => false,
			'show_ui'           => true,
			'show_in_rest'      => true,
			'show_admin_column' => true,
			'hierarchical'      => false,
		);

		register_taxonomy( self::TAX_SECTOR, self::POST_TYPE, $shared + array(
			'labels' => array( 'name' => __( 'Sectores', 'powergis' ) ),
		) );
		register_taxonomy( self::TAX_TYPE, self::POST_TYPE, $shared + array(
			'labels' => array( 'name' => __( 'Tipos de proyecto', 'powergis' ) ),
		) );
		register_taxonomy( self::TAX_LOC, self::POST_TYPE, $shared + array(
			'hierarchical' => true,   // CCAA → provincia → municipio
			'labels'       => array( 'name' => __( 'Ubicaciones', 'powergis' ) ),
		) );
		register_taxonomy( self::TAX_TIER, self::POST_TYPE, $shared + array(
			'labels' => array( 'name' => __( 'Nivel de informe', 'powergis' ) ),
		) );
	}

	/**
	 * Los meta se registran para poder consultarlos, pero NO se exponen en REST:
	 * `_pg_project_uuid` es una credencial de lectura del informe.
	 */
	public static function register_meta(): void {
		$private = array(
			self::META_UUID    => 'string',
			self::META_STATUS  => 'string',
			self::META_ERROR   => 'string',
			self::META_SCOPE   => 'string',
			self::META_SEGMENTS => 'string',
			self::META_BUSINESS => 'string',
			self::META_TARGET   => 'string',
			self::META_RAW      => 'string',
		);
		foreach ( $private as $key => $type ) {
			register_post_meta( self::POST_TYPE, $key, array(
				'type'         => $type,
				'single'       => true,
				'show_in_rest' => false,
				'auth_callback' => static fn(): bool => current_user_can( 'manage_options' ),
			) );
		}
		register_post_meta( self::POST_TYPE, self::META_VERSION, array(
			'type'          => 'integer',
			'single'        => true,
			'show_in_rest'  => false,
			'auth_callback' => static fn(): bool => current_user_can( 'manage_options' ),
		) );
	}

	public static function seed_terms(): void {
		foreach ( array( 'basico' => 'Básico', 'avanzado' => 'Avanzado' ) as $slug => $name ) {
			if ( ! term_exists( $slug, self::TAX_TIER ) ) {
				wp_insert_term( $name, self::TAX_TIER, array( 'slug' => $slug ) );
			}
		}
		$sectores = array(
			'restauracion' => 'Restauración',
			'cafeteria'    => 'Cafetería',
			'retail'       => 'Retail',
			'alimentacion' => 'Alimentación',
			'salud'        => 'Salud',
			'belleza'      => 'Belleza',
			'fitness'      => 'Fitness',
			'servicios'    => 'Servicios',
		);
		foreach ( $sectores as $slug => $name ) {
			if ( ! term_exists( $slug, self::TAX_SECTOR ) ) {
				wp_insert_term( $name, self::TAX_SECTOR, array( 'slug' => $slug ) );
			}
		}
		foreach ( array( 'apertura' => 'Nueva apertura', 'expansion' => 'Expansión', 'reubicacion' => 'Reubicación' ) as $slug => $name ) {
			if ( ! term_exists( $slug, self::TAX_TYPE ) ) {
				wp_insert_term( $name, self::TAX_TYPE, array( 'slug' => $slug ) );
			}
		}
	}

	/**
	 * En REST, un usuario solo ve SUS proyectos. Los administradores, todos.
	 *
	 * @param array<string,mixed> $args    Argumentos de WP_Query.
	 * @param \WP_REST_Request    $request Petición.
	 * @return array<string,mixed>
	 */
	public static function restrict_rest_query( array $args, \WP_REST_Request $request ): array {
		if ( current_user_can( 'manage_options' ) ) {
			return $args;
		}
		$user_id = get_current_user_id();
		if ( ! $user_id ) {
			$args['post__in'] = array( 0 );  // sin sesión, sin resultados
			return $args;
		}
		$args['author'] = $user_id;
		return $args;
	}

	/**
	 * Ni el UUID ni el estado interno salen por REST.
	 */
	public static function strip_private_meta( \WP_REST_Response $response, \WP_Post $post, \WP_REST_Request $request ): \WP_REST_Response {
		$data = $response->get_data();
		if ( isset( $data['meta'] ) && is_array( $data['meta'] ) ) {
			foreach ( array_keys( $data['meta'] ) as $key ) {
				if ( str_starts_with( (string) $key, '_pg_' ) ) {
					unset( $data['meta'][ $key ] );
				}
			}
			$response->set_data( $data );
		}
		return $response;
	}

	// -- utilidades -------------------------------------------------------- //

	public static function find_by_uuid( string $uuid ): ?\WP_Post {
		$query = new \WP_Query(
			array(
				'post_type'      => self::POST_TYPE,
				'post_status'    => 'any',
				'posts_per_page' => 1,
				'no_found_rows'  => true,
				'meta_key'       => self::META_UUID,
				'meta_value'     => $uuid,
			)
		);
		return $query->have_posts() ? $query->posts[0] : null;
	}

	public static function uuid_of( int $post_id ): string {
		return (string) get_post_meta( $post_id, self::META_UUID, true );
	}

	public static function tier_of( int $post_id ): string {
		$terms = wp_get_object_terms( $post_id, self::TAX_TIER, array( 'fields' => 'slugs' ) );
		return ( is_array( $terms ) && ! empty( $terms ) ) ? (string) $terms[0] : 'basico';
	}

	public static function set_tier( int $post_id, string $tier ): void {
		wp_set_object_terms( $post_id, sanitize_key( $tier ), self::TAX_TIER, false );
	}

	public static function status_of( int $post_id ): string {
		$status = get_post_meta( $post_id, self::META_STATUS, true );
		return $status ? (string) $status : 'queued';
	}

	public static function owns( int $post_id, int $user_id ): bool {
		if ( user_can( $user_id, 'manage_options' ) ) {
			return true;
		}
		return (int) get_post_field( 'post_author', $post_id ) === $user_id;
	}
}
