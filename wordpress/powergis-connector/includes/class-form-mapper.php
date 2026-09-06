<?php
/**
 * Mapeo del formulario real de powergis.es al contrato del motor.
 *
 * ORIGEN DE ESTOS NOMBRES
 * -----------------------
 * Del shortcode `[crear_proyecto_v6]` (`shortcodes.php` del tema, revisión de
 * agosto de 2026), publicado en `/crear-proyecto/` y
 * `/crear-proyecto-geolocalizado/`. El JetFormBuilder 3118 queda descartado.
 *
 * El formulario manda un payload ANIDADO, construido por `buildPayload()`:
 *
 *   {
 *     project_id, project_name, ultimo_paso, report_tier,
 *     definicion: {
 *       tipo_estudio: 'nacional'|'ccaa'|'provincia'|'poblacion',
 *       actividad_economica: { sector, actividad, cnae },
 *       delimitacion_geografica: { ccaa, provincia, poblacion }
 *     },
 *     ticket: [...],
 *     buyer_persona: { edad[], genero, estado_civil[], academia,
 *                      nacionalidad[], nse[], renta_anual[], renta_mensual },
 *     ecosistema:    { comp_directa, comp_indirecta_alta, comp_indirecta_media,
 *                      gen_trafico_alto, gen_trafico_medio },
 *     entorno:       { clima[], trafico_peaton[], trafico_vehicular[], comentarios }
 *   }
 *
 * EL PROBLEMA QUE RESUELVE ESTA CLASE
 * -----------------------------------
 * `delimitacion_geografica` trae NOMBRES, no códigos: el árbol se pinta con
 * `opt.value = c.label`. El motor necesita el código INE, y `scope.ine_code`
 * es obligatorio, así que hoy toda creación de proyecto se rechaza en el
 * borde. Es el TODO que quedó anotado en `rest-projects.php`:
 *
 *     'ine_code' => $loc['ine_code'] ?? null,
 *     // TODO: confirmar que el árbol de ubicación manda código INE
 *
 * Confirmado: no lo manda. Aquí se resuelve el nombre contra el padrón del
 * motor, que es la única fuente que puede hacerlo bien —`data/arbol.json`
 * conserva el código de CCAA y provincia, pero de los 8.131 municipios sólo
 * guarda el dígito de control (Madrid figura como «6», no «28079»), así que
 * desde ahí el código municipal es irrecuperable.
 *
 * @package PowerGIS
 */

declare( strict_types = 1 );

namespace PowerGIS;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

final class Form_Mapper {

	/** `tipo_estudio` del formulario → nivel geográfico del motor. */
	private const LEVELS = array(
		'nacional'  => 'pais',
		'ccaa'      => 'ccaa',
		'provincia' => 'provincia',
		'poblacion' => 'municipio',
		'municipio' => 'municipio',
	);

	/**
	 * Nivel de desagregación. Es lo que el propio formulario promete al
	 * usuario en `TIPO_EXPLANATIONS`: «nacional» compara comunidades,
	 * «ccaa» compara provincias, «provincia» compara poblaciones.
	 */
	private const CHILDREN = array(
		'pais'      => 'ccaa',
		'ccaa'      => 'provincia',
		'provincia' => 'municipio',
		// «poblacion» promete comparar zonas y barrios: eso es sección
		// censal, y en la fase del INE no hay datos a ese nivel. Se deja sin
		// declarar para que el motor avise en vez de devolver un ranking
		// vacío con pinta de error.
		'municipio' => null,
	);

	/** Tramos de ticket → euros representativos (punto medio del tramo). */
	private const TICKET_EUROS = array(
		'micro'      => 5.0,
		'bajo'       => 30.0,
		'medio'      => 125.0,
		'medio-alto' => 600.0,
		'alto'       => 3000.0,
		'lujo'       => 8000.0,
	);

	/** Marca de «me da igual»: no genera criterio de Match. */
	private const INDIFERENTE = 'indiferente';

	/**
	 * TRADUCCIÓN AL VOCABULARIO DEL MOTOR
	 * -----------------------------------
	 * Varios `<option>` del shortcode no llevan atributo `value`, así que
	 * envían el texto visible («Universitario / Grado Licenciatura»). El
	 * motor busca claves cortas (`universitario`). Sin esta traducción el
	 * criterio no casa con nada y el Match % se calcula sin él: no da error,
	 * simplemente puntúa peor y nadie se entera.
	 *
	 * Se compara por prefijo tras normalizar, así que un retoque de redacción
	 * en el formulario no rompe el mapeo.
	 *
	 * @var array<string,array<string,string>>
	 */
	private const VOCAB = array(
		'education'    => array(
			'sin estudios'     => 'sin_estudios',
			'educacion basica' => 'sin_estudios',
			'educacion secund' => 'secundaria',
			'bachillerato'     => 'secundaria',
			'tecnico superior' => 'tecnico_superior',
			'grado medio'      => 'tecnico_superior',
			'universitario'    => 'universitario',
			'postgrado'        => 'postgrado',
		),
		'family'       => array(
			'soltero'           => 'soltero',
			'pareja'            => 'pareja_sin_hijos',
			'casado'            => 'pareja_sin_hijos',
			'nido lleno'        => 'nido_lleno',
			'nido adolescentes' => 'nido_adolescentes',
			'nido con adoles'   => 'nido_adolescentes',
			'nido vacio'        => 'nido_vacio',
			'monoparental'      => 'monoparental',
		),
		'income_year'  => array(
			'subsistencia'    => '<12k',
			'baja-media'      => '12-24k',
			'media-alta'      => '45-75k',   // antes que 'media': gana el prefijo largo
			'media'           => '24-45k',
			'alta'            => '75-150k',
			'hnwi'            => '>150k',
			'alto patrimonio' => '>150k',
		),
		'income_month' => array(
			'renta critica'      => '<300',
			'renta ajustada'     => '301-800',
			'renta holgada'      => '801-2500',
			'renta discrecional' => '>2500',
		),
		'ticket'       => array(
			'micro'      => 'micro',
			'bajo'       => 'bajo',
			'medio-alto' => 'medio_alto',    // antes que 'medio'
			'medio'      => 'medio',
			'alto'       => 'alto',
			'lujo'       => 'lujo',
		),
		'intensity'    => array(
			'muy alta' => 'muy_alto',
			'alta'     => 'alto',
			'media'    => 'medio',
			'baja'     => 'bajo',
		),
	);

	// ---------------------------------------------------------------------- //

	/**
	 * Traduce el formulario al cuerpo de `POST /v1/reports`.
	 *
	 * @param array<string,mixed> $input        Payload del formulario.
	 * @param callable|null       $geo_resolver fn(string $level, array $names): ?string
	 *                                          Devuelve el código INE. Se inyecta
	 *                                          para poder probar el mapeo sin red.
	 * @return array<string,mixed>
	 */
	public static function to_engine_payload( array $input, ?callable $geo_resolver = null ): array {
		$def   = self::sub( $input, 'definicion' );
		$level = self::scope_level( $def['tipo_estudio'] ?? null );

		return array(
			'scope'    => array(
				'level'          => $level,
				'ine_code'       => self::scope_code( $input, $level, $geo_resolver ),
				'children_level' => self::CHILDREN[ $level ] ?? null,
			),
			'segments' => self::segments( $input ),
			'business' => self::business( $input ),
			'target'   => self::target( $input ),
		);
	}

	/**
	 * Segmentos con los que se PIDEN los datos al almacén.
	 *
	 * Ojo a la diferencia con `target`: aquí van los cortes del dato; allí, el
	 * perfil con el que se PUNTÚA. «Indiferente» aquí significa no filtrar.
	 *
	 * @param array<string,mixed> $input
	 * @return array<string,mixed>
	 */
	public static function segments( array $input ): array {
		$bp = self::sub( $input, 'buyer_persona' );

		$sex    = array();
		$gender = self::slug( $bp['genero'] ?? null );
		if ( 'masculino' === $gender ) {
			$sex = array( 'M' );
		} elseif ( 'femenino' === $gender ) {
			$sex = array( 'F' );
		}

		return array(
			'age'         => self::normalize_ages( $bp['edad'] ?? null ),
			'sex'         => $sex,
			'nationality' => array(),
		);
	}

	/**
	 * @param array<string,mixed> $input
	 * @return array<string,mixed>
	 */
	public static function business( array $input ): array {
		$def = self::sub( $input, 'definicion' );
		$act = is_array( $def['actividad_economica'] ?? null ) ? $def['actividad_economica'] : array();

		return array(
			'sector'     => self::sector( $act ),
			'avg_ticket' => self::ticket_to_euros( $input['ticket'] ?? null ),
		);
	}

	/**
	 * Perfil de cliente objetivo: alimenta el Match % y la dimensión `perfil`
	 * de PlaceRank.
	 *
	 * @param array<string,mixed> $input
	 * @return array<string,mixed>
	 */
	public static function target( array $input ): array {
		$bp  = self::sub( $input, 'buyer_persona' );
		$eco = self::sub( $input, 'ecosistema' );
		$ent = self::sub( $input, 'entorno' );

		$target = array(
			'age_range'                 => self::normalize_ages( $bp['edad'] ?? null ),
			'gender'                    => self::clean_one( $bp['genero'] ?? null ),
			'family_status'             => self::vocab( 'family', self::first_of( $bp['estado_civil'] ?? null ) ),
			'education_level'           => self::vocab( 'education', $bp['academia'] ?? null ),
			'nationality'               => self::clean_one( self::first_of( $bp['nacionalidad'] ?? null ) ),
			'nse'                       => array_map( 'strtolower', self::clean_list( $bp['nse'] ?? null ) ),
			'annual_income'             => self::vocab( 'income_year', self::first_of( $bp['renta_anual'] ?? null ) ),
			'monthly_available_income'  => self::vocab( 'income_month', $bp['renta_mensual'] ?? null ),
			// De varios tramos marcados gana el más alto, igual que en
			// `business.avg_ticket`: dimensionar por lo bajo subestima.
			'average_ticket'            => self::top_ticket( $input['ticket'] ?? null ),
			'climate'                   => array_map(
				static fn( string $c ): string => self::slug( $c ),
				self::clean_list( $ent['clima'] ?? null )
			),
			'pedestrian_traffic'        => self::vocab( 'intensity', self::first_of( $ent['trafico_peaton'] ?? null ) ),
			'vehicular_traffic'         => self::vocab( 'intensity', self::first_of( $ent['trafico_vehicular'] ?? null ) ),
			'traffic_generators_high'   => self::split_terms( $eco['gen_trafico_alto'] ?? null ),
			'traffic_generators_medium' => self::split_terms( $eco['gen_trafico_medio'] ?? null ),
			'direct_competition'        => self::to_bool( $eco['comp_directa'] ?? null ),
		);

		// Quitar lo vacío deja claro en los logs qué declaró el cliente y qué
		// dejó en «indiferente».
		return array_filter(
			$target,
			static fn( $value ): bool => ! ( null === $value || '' === $value || array() === $value )
		);
	}

	// ---------------------------------------------------------------------- //
	// Ámbito geográfico
	// ---------------------------------------------------------------------- //

	public static function scope_level( $raw ): string {
		return self::LEVELS[ self::slug( $raw ) ] ?? 'provincia';
	}

	/**
	 * Código INE del ámbito consultado.
	 *
	 * El formulario manda nombres, así que hay que resolverlos. Se pasan los
	 * tres niveles al resolutor —CCAA, provincia y población— porque hay
	 * decenas de municipios homónimos en España y sin la provincia no se
	 * puede desambiguar «Villanueva» ni «Los Santos».
	 *
	 * @param array<string,mixed> $input
	 */
	public static function scope_code( array $input, string $level, ?callable $resolver = null ): string {
		if ( 'pais' === $level ) {
			return 'ES';
		}

		$def = self::sub( $input, 'definicion' );
		$loc = is_array( $def['delimitacion_geografica'] ?? null ) ? $def['delimitacion_geografica'] : array();

		// Si algún día el formulario empieza a mandar el código, se usa tal cual.
		$explicit = self::pad( $loc['ine_code'] ?? null, 'municipio' === $level ? 5 : 2 );
		if ( '' !== $explicit ) {
			return $explicit;
		}

		if ( null === $resolver ) {
			return '';
		}

		$names = array(
			'ccaa'      => (string) ( $loc['ccaa'] ?? '' ),
			'provincia' => (string) ( $loc['provincia'] ?? '' ),
			'municipio' => (string) ( $loc['poblacion'] ?? '' ),
		);

		return (string) ( $resolver( $level, $names ) ?? '' );
	}

	/**
	 * Los códigos del INE llevan ceros a la izquierda («01», «08019»). Si
	 * viajan como número, JSON se los come y «08019» llega como 8019.
	 */
	private static function pad( $raw, int $length ): string {
		$digits = preg_replace( '/\D/', '', (string) $raw );
		return '' === $digits ? '' : str_pad( $digits, $length, '0', STR_PAD_LEFT );
	}

	// ---------------------------------------------------------------------- //
	// Negocio
	// ---------------------------------------------------------------------- //

	/**
	 * Sector del catálogo de PlaceRank a partir del CNAE o del texto.
	 *
	 * @param array<string,mixed> $actividad Bloque `definicion.actividad_economica`.
	 */
	public static function sector( array $actividad ): ?string {
		$known = array( 'restauracion', 'cafeteria', 'retail', 'alimentacion', 'salud', 'belleza', 'fitness', 'servicios' );

		$explicit = self::slug( $actividad['sector'] ?? null );
		if ( in_array( $explicit, $known, true ) ) {
			return $explicit;
		}

		// El CNAE es más fiable que un desplegable de texto libre.
		$cnae = preg_replace( '/\D/', '', (string) ( $actividad['cnae'] ?? '' ) );
		if ( is_string( $cnae ) && strlen( $cnae ) >= 2 ) {
			$map = array(
				56 => 'restauracion',
				47 => 'retail',
				10 => 'alimentacion',
				86 => 'salud',
				96 => 'belleza',
				93 => 'fitness',
			);
			$division = (int) substr( $cnae, 0, 2 );
			if ( isset( $map[ $division ] ) ) {
				return $map[ $division ];
			}
		}

		$text = self::slug( $actividad['actividad'] ?? null );
		foreach ( $known as $candidate ) {
			if ( '' !== $text && str_contains( $text, $candidate ) ) {
				return $candidate;
			}
		}

		return null;
	}

	/** Tramo de ticket más alto marcado, en euros. */
	public static function ticket_to_euros( $raw ): ?float {
		$best = null;
		foreach ( self::as_array( $raw ) as $item ) {
			$key = self::slug( $item );
			if ( isset( self::TICKET_EUROS[ $key ] ) ) {
				$best = ( null === $best ) ? self::TICKET_EUROS[ $key ] : max( $best, self::TICKET_EUROS[ $key ] );
			}
		}
		return $best;
	}

	/** Tramo de ticket más alto, en vocabulario del motor. */
	private static function top_ticket( $raw ): ?string {
		$order = array( 'micro', 'bajo', 'medio', 'medio_alto', 'alto', 'lujo' );
		$best  = null;
		foreach ( self::as_array( $raw ) as $item ) {
			$key = self::vocab( 'ticket', $item );
			if ( null === $key ) {
				continue;
			}
			if ( null === $best || array_search( $key, $order, true ) > array_search( $best, $order, true ) ) {
				$best = $key;
			}
		}
		return $best;
	}

	// ---------------------------------------------------------------------- //
	// Utilidades
	// ---------------------------------------------------------------------- //

	/**
	 * Bloque anidado del payload, siempre como array.
	 *
	 * @param array<string,mixed> $input
	 * @return array<string,mixed>
	 */
	private static function sub( array $input, string $key ): array {
		return is_array( $input[ $key ] ?? null ) ? $input[ $key ] : array();
	}

	/**
	 * Traduce una etiqueta del formulario a la clave que entiende el motor.
	 * Si no reconoce nada devuelve null: mejor sin criterio que con uno
	 * inventado.
	 */
	public static function vocab( string $table, $value ): ?string {
		$text = self::slug( $value );
		if ( '' === $text || self::INDIFERENTE === $text ) {
			return null;
		}
		foreach ( self::VOCAB[ $table ] ?? array() as $needle => $key ) {
			if ( str_starts_with( $text, $needle ) || str_contains( $text, $needle ) ) {
				return $key;
			}
		}
		return null;
	}

	/**
	 * Los campos de anclas son buscadores de texto libre: pueden traer varios
	 * términos separados por coma.
	 *
	 * @return array<int,string>
	 */
	private static function split_terms( $value ): array {
		$out = array();
		foreach ( self::as_array( $value ) as $chunk ) {
			foreach ( preg_split( '/[,;]+/', (string) $chunk ) ?: array() as $term ) {
				$term = trim( $term );
				if ( '' !== $term && self::INDIFERENTE !== self::slug( $term ) ) {
					$out[] = $term;
				}
			}
		}
		return array_values( array_unique( $out ) );
	}

	/** Etiqueta sin acentos ni mayúsculas, para comparar. */
	public static function slug( $value ): string {
		if ( is_array( $value ) ) {
			$value = reset( $value );
		}
		return strtr(
			strtolower( trim( (string) $value ) ),
			array( 'á' => 'a', 'é' => 'e', 'í' => 'i', 'ó' => 'o', 'ú' => 'u', 'ü' => 'u', 'ñ' => 'n' )
		);
	}

	/**
	 * @return array<int,mixed>
	 */
	public static function as_array( $value ): array {
		if ( null === $value ) {
			return array();
		}
		return is_array( $value ) ? array_values( $value ) : array( $value );
	}

	private static function first_of( $value ) {
		return self::as_array( $value )[0] ?? null;
	}

	/**
	 * Lista sin «Indiferente»: el motor entiende la ausencia de criterio, y
	 * mandarle la palabra le haría buscar una zona que se le parezca.
	 *
	 * @return array<int,string>
	 */
	private static function clean_list( $value ): array {
		$out = array();
		foreach ( self::as_array( $value ) as $item ) {
			$text = trim( (string) $item );
			if ( '' !== $text && self::INDIFERENTE !== self::slug( $text ) ) {
				$out[] = $text;
			}
		}
		return array_values( array_unique( $out ) );
	}

	private static function clean_one( $value ): ?string {
		$text = trim( (string) ( is_array( $value ) ? ( $value[0] ?? '' ) : $value ) );
		return ( '' === $text || self::INDIFERENTE === self::slug( $text ) ) ? null : $text;
	}

	/**
	 * @return array<int,string>
	 */
	private static function normalize_ages( $value ): array {
		$out = array();
		foreach ( self::as_array( $value ) as $age ) {
			$normalised = self::normalize_age( $age );
			if ( '' !== $normalised ) {
				$out[] = $normalised;
			}
		}
		return array_values( array_unique( $out ) );
	}

	/** Rangos al formato del motor: «25-34», «65+». */
	public static function normalize_age( $value ): string {
		$text = trim( (string) $value );
		if ( '' === $text || self::INDIFERENTE === self::slug( $text ) ) {
			return '';
		}
		$text = str_replace( array( '–', '—', ' ' ), array( '-', '-', '' ), $text );
		if ( preg_match( '/^(\d{1,3})-(\d{1,3})$/', $text, $m ) ) {
			return $m[1] . '-' . $m[2];
		}
		if ( preg_match( '/^(\d{1,3})\+?$/', $text, $m ) ) {
			return $m[1] . '+';
		}
		return '';
	}

	public static function to_bool( $value ): bool {
		if ( is_bool( $value ) ) {
			return $value;
		}
		return in_array( self::slug( $value ), array( '1', 'true', 'on', 'si', 'sí', 'yes' ), true );
	}
}
